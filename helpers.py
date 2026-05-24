import asyncio, csv, json, logging, os, re, time, uuid
from datetime import datetime
from pathlib import Path
import yt_dlp
from playwright.async_api import async_playwright
from config import SETTINGS_FILE, DATABASE_FILE, REMINDERS_FILE, DOWNLOAD_DIR, COOKIES_FILE, REMINDER_ALERT_IMAGE

logger = logging.getLogger(__name__)

def now(): return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

def load_json(path, default):
    path = Path(path)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding='utf-8'))
        except Exception as e:
            logger.error(f'JSON read error {path}: {type(e).__name__}: {repr(e)}')
    return default

def save_json(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')

# users/settings

def load_settings():
    data = load_json(SETTINGS_FILE, {'users': {}})
    if not isinstance(data, dict): data = {'users': {}}
    data.setdefault('users', {})
    return data

def save_settings(data): save_json(SETTINGS_FILE, data)

def ensure_owner(owner_id):
    if not owner_id: return
    data = load_settings(); users = data['users']; key = str(owner_id)
    users.setdefault(key, {'name':'Owner','role':'owner','chat_id':None,'topics':{}})
    users[key]['role'] = 'owner'
    save_settings(data)

def is_allowed(user_id, owner_id=0):
    return (owner_id and int(user_id)==int(owner_id)) or str(user_id) in load_settings()['users']

def allow_user(user_id, name='User', role='user'):
    data = load_settings(); key = str(user_id)
    data['users'].setdefault(key, {'name': name, 'role': role, 'chat_id': None, 'topics': {}})
    data['users'][key]['name'] = name or data['users'][key].get('name','User')
    data['users'][key].setdefault('chat_id', None); data['users'][key].setdefault('topics', {})
    save_settings(data); return data['users'][key]

def revoke_user(user_id):
    data=load_settings(); removed=data['users'].pop(str(user_id), None); save_settings(data); return removed

def list_users(): return load_settings()['users']

def get_user(user_id): return load_settings()['users'].get(str(user_id))

def set_chat(user_id, chat_id):
    data=load_settings(); key=str(user_id)
    data['users'].setdefault(key, {'name':'User','role':'user','chat_id':None,'topics':{}})
    data['users'][key]['chat_id']=int(chat_id); data['users'][key].setdefault('topics', {})
    save_settings(data)

def get_chat(user_id):
    u=get_user(user_id); return u.get('chat_id') if u else None

def get_topics(user_id):
    u=get_user(user_id); return u.get('topics', {}) if u else {}

def save_topics(user_id, topics):
    data=load_settings(); key=str(user_id)
    data['users'].setdefault(key, {'name':'User','role':'user','chat_id':None,'topics':{}})
    data['users'][key]['topics']=topics; save_settings(data)

def icon_for(name):
    s=name.lower()
    if 'sport' in s or 'спорт' in s: return '⚽'
    if 'inst' in s: return '📸'
    if 'tiktok' in s: return '🎵'
    if 'x' == s or 'twitter' in s: return '𝕏'
    if 'thread' in s: return '🧵'
    if 'meme' in s or 'мем' in s: return '😂'
    if 'cow' in s: return '🤠'
    return '📌'

def add_topic(user_id, name, thread_id, icon=None):
    topics=get_topics(user_id); topics[name]={'id':int(thread_id),'icon':icon or icon_for(name)}; save_topics(user_id, topics); return topics[name]

def remove_topic(user_id, name):
    topics=get_topics(user_id); item=topics.pop(name, None); save_topics(user_id, topics); return item

def rename_topic(user_id, old, new):
    topics=get_topics(user_id)
    if old not in topics: return None
    item=topics.pop(old); item['icon']=icon_for(new); topics[new]=item; save_topics(user_id, topics); return item

def topics_text(user_id):
    topics=get_topics(user_id)
    if not topics: return '📂 Топиков пока нет. Создай новый или подключи существующий через /connecttopic Название внутри темы.'
    return '📂 Текущие топики:\n\n' + '\n'.join(f"{v.get('icon','📌')} {k} — ID: {v.get('id')}" for k,v in topics.items())

# database/reminders

def load_db():
    d=load_json(DATABASE_FILE, []); return d if isinstance(d, list) else []

def save_db(d): save_json(DATABASE_FILE, d)

def add_item(item):
    d=load_db(); d.append(item); save_db(d)

def find_item(item_id):
    return next((i for i in load_db() if i.get('id')==item_id), None)

def update_item(item_id, updates):
    d=load_db()
    for i in d:
        if i.get('id')==item_id:
            i.update(updates); i['updated_at']=now(); save_db(d); return i
    return None

def load_reminders():
    d=load_json(REMINDERS_FILE, []); return d if isinstance(d, list) else []

def save_reminders(d): save_json(REMINDERS_FILE, d)

def add_reminder(item_id, user_id, due_ts, label):
    remove_reminders(item_id)
    d = load_reminders()
    r = {
        'id': str(uuid.uuid4()),
        'item_id': item_id,
        'user_id': int(user_id),
        'due_ts': due_ts,
        'label': label,
        'created_at': now(),
        'sent': False,
        'cancelled': False,
    }
    d.append(r)
    save_reminders(d)
    return r

def remove_reminders(item_id):
    d = load_reminders()
    changed = False
    for r in d:
        if r.get('item_id') == item_id and not r.get('sent') and not r.get('cancelled'):
            r['sent'] = True
            r['cancelled'] = True
            r['cancelled_at'] = now()
            changed = True
    if changed:
        save_reminders(d)

def active_reminders(user_id=None):
    d = load_reminders()
    out = []
    for r in d:
        if r.get('sent') or r.get('cancelled'):
            continue
        if user_id is not None and str(r.get('user_id')) != str(user_id):
            continue
        item = find_item(r.get('item_id'))
        if item:
            out.append((r, item))
    out.sort(key=lambda pair: pair[0].get('due_ts', 0))
    return out

def completed_reminders(user_id=None):
    d = load_reminders()
    out = []
    for r in d:
        if not r.get('sent'):
            continue
        if user_id is not None and str(r.get('user_id')) != str(user_id):
            continue
        item = find_item(r.get('item_id'))
        if item:
            out.append((r, item))
    out.sort(key=lambda pair: pair[0].get('sent_at', ''), reverse=True)
    return out

def clear_completed_reminders(user_id=None):
    d = load_reminders()
    before = len(d)
    kept = []
    for r in d:
        if r.get('sent') or r.get('cancelled'):
            if user_id is None or str(r.get('user_id')) == str(user_id):
                continue
        kept.append(r)
    save_reminders(kept)
    return before - len(kept)

def reminder_due_label(ts):
    try:
        return datetime.fromtimestamp(float(ts)).strftime('%d.%m.%Y %H:%M')
    except Exception:
        return 'неизвестно'

def post_link(item):
    chat = item.get('chat_id')
    msg = item.get('message_id')
    if not chat or not msg:
        return None
    s = str(chat)
    if s.startswith('-100'):
        return f"https://t.me/c/{s[4:]}/{msg}"
    return None

def reminder_text(item):
    return (
        "⏰ НАПОМИНАНИЕ\n\n"
        "Пора вернуться к этому референсу.\n\n"
        f"🎬 Платформа: {item.get('platform','')}\n"
        f"⚡ Приоритет: {item.get('priority_label','')}\n"
        f"📌 Статус: {item.get('status_label','')}\n"
        f"📂 Топик: {item.get('topic','')}\n\n"
        f"💭 Заметка:\n{item.get('notes','')}"
    )

def reminder_alert_kb(item_id):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    item = find_item(item_id)
    link = post_link(item or {})
    rows = []
    if link:
        rows.append([InlineKeyboardButton('🔗 Открыть пост', url=link)])
    rows.append([
        InlineKeyboardButton('✅ Готово', callback_data=f'reminder_done:{item_id}'),
        InlineKeyboardButton('💤 Отложить', callback_data=f'reminder_snooze_menu:{item_id}'),
    ])
    rows.append([InlineKeyboardButton('🗑 Удалить напоминание', callback_data=f'reminder_delete:{item_id}')])
    return InlineKeyboardMarkup(rows)

def reminder_snooze_kb(item_id):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('⏱ По часам', callback_data=f'reminder_snooze_hours:{item_id}'),
         InlineKeyboardButton('📅 По дням', callback_data=f'reminder_snooze_days:{item_id}')],
        [InlineKeyboardButton('✅ Готово', callback_data=f'reminder_done:{item_id}')],
    ])


def reference_post_kb(item_id):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton('⚡ Приоритет', callback_data=f'post_priority_menu:{item_id}'),
            InlineKeyboardButton('📌 Статус', callback_data=f'post_status_menu:{item_id}'),
        ],
        [InlineKeyboardButton('⏰ Напомнить', callback_data=f'post_reminder_menu:{item_id}')],
    ])

async def send_reminder_alert(context, user_id, item):
    text = reminder_text(item)
    markup = reminder_alert_kb(item.get('id'))
    try:
        if file_exists(REMINDER_ALERT_IMAGE):
            with open(REMINDER_ALERT_IMAGE, 'rb') as f:
                await context.bot.send_photo(chat_id=user_id, photo=f, caption=text, reply_markup=markup)
        else:
            await context.bot.send_message(chat_id=user_id, text=text, reply_markup=markup)
        if item.get('chat_id') and item.get('message_id'):
            await context.bot.copy_message(chat_id=user_id, from_chat_id=item.get('chat_id'), message_id=item.get('message_id'))
    except Exception as e:
        logger.error(f'reminder send error: {type(e).__name__}: {repr(e)}')

async def remove_reminder_from_original_post(context, item):
    if not item:
        return
    try:
        new_item = update_item(item.get('id'), {
            'reminder': None,
            'reminder_label': None,
            'reminder_due_ts': None,
        })
        if new_item and new_item.get('chat_id') and new_item.get('message_id'):
            cap = video_caption(
                new_item.get('platform',''),
                new_item.get('url',''),
                new_item.get('notes',''),
                new_item.get('priority_label',''),
                new_item.get('status_label',''),
                new_item.get('reminder_label')
            )
            try:
                await context.bot.edit_message_caption(
                    chat_id=new_item.get('chat_id'),
                    message_id=new_item.get('message_id'),
                    caption=cap,
                    reply_markup=reference_post_kb(new_item.get('id'))
                )
            except Exception:
                try:
                    await context.bot.edit_message_text(
                        chat_id=new_item.get('chat_id'),
                        message_id=new_item.get('message_id'),
                        text=cap,
                        reply_markup=reference_post_kb(new_item.get('id'))
                    )
                except Exception:
                    pass
    except Exception as e:
        logger.error(f'original reminder cleanup error: {type(e).__name__}: {repr(e)}')

async def reminders_job(context):
    try:
        d = load_reminders()
        changed = False
        t = time.time()
        for r in d:
            if r.get('sent') or r.get('cancelled') or r.get('due_ts', 0) > t:
                continue
            item = find_item(r.get('item_id'))
            if item:
                await send_reminder_alert(context, r.get('user_id'), item)
                await remove_reminder_from_original_post(context, item)
            r['sent'] = True
            r['sent_at'] = now()
            changed = True
        if changed:
            save_reminders(d)
    except Exception as e:
        logger.error(f'reminder job error: {type(e).__name__}: {repr(e)}')

# URL/platform

def has_link(t): return 'http://' in t or 'https://' in t

def clean_url(u): return u.strip().rstrip(').,]')

def extract_url_note(t):
    m=re.search(r'https?://\S+', t)
    if not m: return None, t.strip()
    raw=m.group(0); return clean_url(raw), (t.replace(raw,'',1).strip() or 'Без заметки')

def norm_inst(u):
    u=clean_url(u).split('?')[0].split('#')[0]
    return u+'/' if 'instagram.com' in u.lower() and not u.endswith('/') else u

def norm_threads(u):
    u=clean_url(u).split('?')[0].split('#')[0]
    u=u.replace('https://www.threads.com/','https://www.threads.net/').replace('https://threads.com/','https://www.threads.net/')
    if u.endswith('/media'): u=u[:-6]
    if '/media/' in u: u=u.split('/media/')[0]
    return u

def ig_user(u):
    u=norm_inst(u); m=re.search(r'instagram\.com/([^/?#]+)/?',u,re.I)
    if not m: return None
    x=m.group(1); return None if x.lower() in {'reel','reels','p','stories','tv','explore','accounts','direct'} else x

def tt_user(u):
    m=re.search(r'tiktok\.com/@([^/?#]+)',u,re.I); return m.group(1) if m else None

def x_user(u):
    m=re.search(r'(?:x\.com|twitter\.com)/([^/?#]+)',u,re.I)
    if not m: return None
    x=m.group(1); return None if x.lower() in {'i','intent','share','home','search','explore','notifications','messages','settings','compose'} else x

def th_user(u):
    u=norm_threads(u); m=re.search(r'threads\.net/@([^/?#]+)',u,re.I); return m.group(1) if m else None

def is_ig_profile(u):
    l=u.lower(); return 'instagram.com' in l and not any(p in l for p in ['/reel/','/reels/','/p/','/stories/','/tv/','/explore/','/accounts/','/direct/'])

def is_tt_profile(u):
    l=u.lower(); return 'tiktok.com/@' in l and not any(p in l for p in ['/video/','/photo/','/t/','/embed/'])

def is_x_profile(u):
    l=u.lower(); return ('x.com/' in l or 'twitter.com/' in l) and not any(p in l for p in ['/status/','/statuses/','/i/','/intent/','/share','/search','/hashtag/']) and x_user(u)

def is_th_profile(u):
    u=norm_threads(u); l=u.lower(); return 'threads.net/@' in l and not any(p in l for p in ['/post/','/t/']) and th_user(u)

def is_profile(u): return is_ig_profile(u) or is_tt_profile(u) or is_x_profile(u) or is_th_profile(u)

def platform(u):
    l=u.lower()
    if 'instagram.com' in l:
        if '/reel/' in l or '/reels/' in l: return 'Instagram Reels'
        if '/p/' in l: return 'Instagram Post'
        if '/stories/' in l: return 'Instagram Story'
        return 'Instagram Profile'
    if 'tiktok.com' in l or 'vm.tiktok.com' in l:
        if is_tt_profile(u): return 'TikTok Profile'
        if '/video/' in l or 'vm.tiktok.com' in l: return 'TikTok Video'
        return 'TikTok'
    if 'x.com' in l or 'twitter.com' in l:
        if is_x_profile(u): return 'X Profile'
        if '/status/' in l or '/statuses/' in l: return 'X Post'
        return 'X'
    if 'threads.net' in l or 'threads.com' in l:
        nu=norm_threads(u); nl=nu.lower()
        if is_th_profile(nu): return 'Threads Profile'
        if '/post/' in nl or '/t/' in nl: return 'Threads Post'
        return 'Threads'
    if 'youtube.com/shorts' in l: return 'YouTube Shorts'
    if 'youtube.com' in l or 'youtu.be' in l: return 'YouTube'
    return 'Video'

def profile_username(u, p):
    return {'Instagram Profile':ig_user,'TikTok Profile':tt_user,'X Profile':x_user,'Threads Profile':th_user}.get(p, lambda x:None)(u)

def threads_disabled(p): return p in {'Threads Post','Threads'}

def screenshot_fallback(p): return p in {'X Post','Instagram Post'}

def video_caption(p, u, n, pri, st, rem=None):
    reminder_line = f'\n⏰ Напоминание: {rem}\n#напоминание' if rem else ''
    return (
        f'🎬 {p}\n\n'
        f'⚡ Приоритет: {pri}\n'
        f'📌 Статус: {st}'
        f'{reminder_line}\n\n'
        f'🔗 Ссылка:\n{u}\n\n'
        f'💭 Заметка:\n{n}'
    )
def profile_caption(u,n,p):
    title={'Instagram Profile':'📸 Instagram Profile Reference','TikTok Profile':'🎵 TikTok Profile Reference','X Profile':'𝕏 X Profile Reference','Threads Profile':'🧵 Threads Profile Reference'}.get(p,'📸 Profile Reference')
    acc=profile_username(u,p) or 'Unknown'
    link=norm_threads(u) if p=='Threads Profile' else norm_inst(u) if p=='Instagram Profile' else clean_url(u)
    return f'{title}\n\n👤 Account:\n@{acc}\n\n🔗 Profile Link:\n{link}\n\n💭 Notes:\n{n}'

# Telegram/media helpers

def file_exists(p): return Path(p).exists() and Path(p).is_file()

async def send_photo_or_text(msg, image, caption, markup=None):
    if file_exists(image):
        with open(image,'rb') as f: await msg.reply_photo(photo=f, caption=caption, reply_markup=markup)
    else: await msg.reply_text(caption, reply_markup=markup)

async def safe_edit(query, text, markup=None):
    try:
        if query.message and query.message.photo: await query.edit_message_caption(caption=text, reply_markup=markup)
        else: await query.edit_message_text(text=text, reply_markup=markup)
    except Exception:
        try: await query.message.reply_text(text, reply_markup=markup)
        except Exception as e: logger.error(f'safe_edit fail: {type(e).__name__}: {repr(e)}')

async def edit_or_send_photo(query, image, caption, markup=None):
    try: await query.message.delete()
    except Exception: pass
    if file_exists(image):
        with open(image,'rb') as f: await query.message.chat.send_photo(photo=f, caption=caption, reply_markup=markup)
    else: await query.message.chat.send_message(caption, reply_markup=markup)

# download/screenshot

def best_file(vid):
    files=[p for p in DOWNLOAD_DIR.glob(f'{vid}.*') if p.is_file() and p.stat().st_size>0]
    if not files: return None
    pr={'.mp4':1,'.mov':2,'.m4v':3,'.webm':4,'.mkv':5}
    vids=[p for p in files if p.suffix.lower() in pr]
    if vids:
        vids.sort(key=lambda p:(pr.get(p.suffix.lower(),99), -p.stat().st_size)); return str(vids[0])
    files.sort(key=lambda p:-p.stat().st_size); return str(files[0])

def download_video_sync(u):
    vid=str(uuid.uuid4()); tmpl=str(DOWNLOAD_DIR / f'{vid}.%(ext)s')
    opts={'outtmpl':tmpl,'format':'best[vcodec^=avc1][height<=720][ext=mp4]/best[height<=720][ext=mp4]/best[ext=mp4]/best','format_sort':['vcodec:h264','ext:mp4','res:720','fps'],'noplaylist':True,'quiet':True,'no_warnings':True,'noprogress':True,'max_filesize':48*1024*1024,'merge_output_format':'mp4','socket_timeout':25,'retries':3,'fragment_retries':3,'concurrent_fragment_downloads':2}
    if COOKIES_FILE.exists(): opts['cookiefile']=str(COOKIES_FILE)
    with yt_dlp.YoutubeDL(opts) as ydl: ydl.extract_info(u, download=True)
    path=best_file(vid)
    if not path or not os.path.exists(path): raise FileNotFoundError('Видео не было скачано или подходящий файл не найден.')
    return path

async def download_video(u): return await asyncio.to_thread(download_video_sync, u)

def cookies_for_playwright():
    if not COOKIES_FILE.exists(): return []
    out=[]
    try:
        for line in COOKIES_FILE.read_text(encoding='utf-8').splitlines():
            line=line.strip(); http=False
            if not line or line.startswith('# Netscape'): continue
            if line.startswith('#HttpOnly_'): http=True; line=line.replace('#HttpOnly_','',1)
            if line.startswith('#'): continue
            parts=line.split('\t')
            if len(parts)<7: continue
            domain, flag, path, secure, exp, name, val=parts[:7]
            try: expires=int(exp)
            except Exception: expires=-1
            if expires==0: expires=-1
            out.append({'name':name,'value':val,'domain':domain,'path':path,'expires':expires,'httpOnly':http,'secure':secure.upper()=='TRUE','sameSite':'Lax'})
    except Exception as e: logger.error(f'cookies read err {type(e).__name__}: {repr(e)}')
    return out

async def click_words(page, words):
    try:
        await page.evaluate("""(words)=>{const t=words.map(w=>w.toLowerCase()); for (const el of Array.from(document.querySelectorAll('button,div[role="button"],a,span,div'))) {const text=(el.innerText||el.textContent||'').trim().toLowerCase(); if(!text) continue; if(t.some(w=>text.includes(w))){(el.closest('button,div[role="button"],a')||el).click(); return true;}} return false;}""", words)
        await page.wait_for_timeout(1500)
    except Exception: pass

async def screenshot_page(u):
    out=str(DOWNLOAD_DIR / f'{uuid.uuid4()}.png')
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True, args=['--no-sandbox','--disable-dev-shm-usage','--disable-gpu','--disable-blink-features=AutomationControlled'])
        try:
            ctx=await browser.new_context(viewport={'width':390,'height':844}, device_scale_factor=2, is_mobile=True, has_touch=True, locale='en-US', timezone_id='America/New_York', user_agent='Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1')
            cs=cookies_for_playwright()
            if cs: await ctx.add_cookies(cs)
            page=await ctx.new_page()
            try: await page.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
            except Exception: pass
            try: await page.goto(u, wait_until='domcontentloaded', timeout=30000)
            except Exception: pass
            await page.wait_for_timeout(5000)
            await click_words(page, ['Continue','Not now','Not Now','Maybe later','Accept all','Accept'])
            await page.wait_for_timeout(2500)
            await page.screenshot(path=out, full_page=False)
            return out
        finally:
            await browser.close()

def export_json(user_id=None):
    d=load_db();
    if user_id is not None: d=[x for x in d if str(x.get('owner_id'))==str(user_id)]
    p=DOWNLOAD_DIR / f'referens_database_{user_id or "all"}.json'; p.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding='utf-8'); return str(p)

def export_csv(user_id=None):
    d=load_db();
    if user_id is not None: d=[x for x in d if str(x.get('owner_id'))==str(user_id)]
    p=DOWNLOAD_DIR / f'referens_database_{user_id or "all"}.csv'
    fields=['id','owner_id','created_at','updated_at','type','topic','platform','username','url','notes','priority_label','status_label','reminder_label','reminder_due_ts','message_id','chat_id']
    with p.open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f, fieldnames=fields); w.writeheader()
        for x in d: w.writerow({k:x.get(k,'') for k in fields})
    return str(p)
