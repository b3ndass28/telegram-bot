import asyncio, logging, os, threading, time, uuid
from pathlib import Path
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, InputFile
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters
from config import BOT_TOKEN, OWNER_ID, TOPICS_IMAGE, INFO_IMAGE, EXPORT_IMAGE, COOKIES_FILE, SETTINGS_FILE, DATABASE_FILE, REMINDERS_FILE, PRIORITIES, STATUSES
from helpers import *

web_app = Flask(__name__)
@web_app.route('/')
def home(): return 'Bot is running!'
def run_web_server(): web_app.run(host='0.0.0.0', port=int(os.environ.get('PORT',10000)))
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger=logging.getLogger(__name__)

INFO_SHORT='ℹ️ Referens Bot\n\nMulti-user бот для сохранения референсов в Telegram-топики.'
INFO_LONG='''Что умеет бот:\n\n🎬 Сохраняет видео-референсы\n📸 Делает скриншоты профилей\n📂 Создаёт и подключает топики\n⚡ Priority / 📌 Status / 🔔 Reminder\n👥 Работает с разными пользователями и группами через один общий BOT_TOKEN.\n\nНастройка:\n1. Owner выдаёт доступ по Telegram ID\n2. Пользователь добавляет бота в свою группу админом\n3. Пишет /connectchat в группе\n4. Создаёт топики или подключает существующие через /connecttopic Название'''

def is_owner(uid): return OWNER_ID and int(uid)==int(OWNER_ID)
async def require_access(update, context):
    uid=update.effective_user.id
    if is_allowed(uid, OWNER_ID): return True
    txt=f'❌ У тебя нет доступа к этому боту.\n\nТвой Telegram ID:\n`{uid}`\n\nОтправь этот ID владельцу бота.'
    if update.message: await update.message.reply_text(txt, parse_mode='Markdown')
    elif update.callback_query:
        await update.callback_query.answer('Нет доступа', show_alert=True)
        await update.callback_query.message.reply_text(txt, parse_mode='Markdown')
    return False
async def require_owner(update, context):
    if is_owner(update.effective_user.id): return True
    if update.message: await update.message.reply_text('❌ Только владелец бота может делать это.')
    elif update.callback_query: await update.callback_query.answer('Только owner', show_alert=True)
    return False

def reply_panel():
    return ReplyKeyboardMarkup([[KeyboardButton('📂 Topics'),KeyboardButton('⚙️ Setup'),KeyboardButton('ℹ️ Info')],[KeyboardButton('📤 Export'),KeyboardButton('✅ Check')]], resize_keyboard=True, one_time_keyboard=False, is_persistent=True)
def main_kb(uid):
    rows=[[InlineKeyboardButton('📂 Topics',callback_data='menu_topics'),InlineKeyboardButton('⚙️ Setup',callback_data='menu_setup')],[InlineKeyboardButton('ℹ️ Info',callback_data='menu_info'),InlineKeyboardButton('📤 Export',callback_data='menu_export')],[InlineKeyboardButton('✅ Check',callback_data='menu_check'),InlineKeyboardButton('❌ Close',callback_data='menu_close')]]
    if is_owner(uid): rows.insert(0,[InlineKeyboardButton('👑 Owner Panel',callback_data='owner_panel')])
    return InlineKeyboardMarkup(rows)
def setup_kb(): return InlineKeyboardMarkup([[InlineKeyboardButton('🔗 Ввести Chat ID',callback_data='setup_set_chat')],[InlineKeyboardButton('📂 Topics',callback_data='menu_topics')],[InlineKeyboardButton('⬅️ Назад',callback_data='menu_main')]])
def owner_kb(): return InlineKeyboardMarkup([[InlineKeyboardButton('➕ Add User',callback_data='owner_add_user')],[InlineKeyboardButton('👥 Users List',callback_data='owner_users')],[InlineKeyboardButton('🗑 Revoke User',callback_data='owner_revoke_user')],[InlineKeyboardButton('⬅️ Назад',callback_data='menu_main')]])
def topics_menu_kb(): return InlineKeyboardMarkup([[InlineKeyboardButton('➕ Создать новый',callback_data='topics_create')],[InlineKeyboardButton('🔗 Подключить существующий',callback_data='topics_connect_help')],[InlineKeyboardButton('✏️ Изменить текущий',callback_data='topics_rename')],[InlineKeyboardButton('🗑️ Удалить',callback_data='topics_delete')],[InlineKeyboardButton('⬅️ Назад',callback_data='menu_main'),InlineKeyboardButton('❌ Закрыть',callback_data='menu_close')]])
def export_kb(): return InlineKeyboardMarkup([[InlineKeyboardButton('📄 JSON',callback_data='export_json'),InlineKeyboardButton('📊 CSV',callback_data='export_csv')],[InlineKeyboardButton('⬅️ Назад',callback_data='menu_main'),InlineKeyboardButton('❌ Закрыть',callback_data='menu_close')]])
def topic_kb(uid):
    topics=get_topics(uid); rows=[]; names=list(topics.keys())
    for i in range(0,len(names),3): rows.append([InlineKeyboardButton(f"{topics[n].get('icon','📌')} {n}", callback_data=f't_{n}') for n in names[i:i+3]])
    rows.append([InlineKeyboardButton('🔗 Save link only',callback_data='save_link_only')]); rows.append([InlineKeyboardButton('❌ Отмена',callback_data='cancel_save')])
    return InlineKeyboardMarkup(rows)
def priority_kb(): return InlineKeyboardMarkup([[InlineKeyboardButton('🔥 High',callback_data='save_priority_high'),InlineKeyboardButton('⭐ Normal',callback_data='save_priority_normal'),InlineKeyboardButton('🧊 Later',callback_data='save_priority_later')],[InlineKeyboardButton('❌ Отмена',callback_data='cancel_save')]])
def post_kb(item): return InlineKeyboardMarkup([[InlineKeyboardButton('⚡ Priority',callback_data=f'post_priority_menu:{item}'),InlineKeyboardButton('📌 Status',callback_data=f'post_status_menu:{item}')],[InlineKeyboardButton('🔔 Reminder',callback_data=f'post_reminder_menu:{item}')]])
def prio_manage_kb(item): return InlineKeyboardMarkup([[InlineKeyboardButton('🔥 High',callback_data=f'post_priority_set:high:{item}'),InlineKeyboardButton('⭐ Normal',callback_data=f'post_priority_set:normal:{item}'),InlineKeyboardButton('🧊 Later',callback_data=f'post_priority_set:later:{item}')],[InlineKeyboardButton('⬅️ Назад',callback_data=f'post_back:{item}')]])
def status_kb(item): return InlineKeyboardMarkup([[InlineKeyboardButton('🟡 В работе',callback_data=f'post_status_set:progress:{item}'),InlineKeyboardButton('✅ Сделано',callback_data=f'post_status_set:done:{item}')],[InlineKeyboardButton('❌ Не подходит',callback_data=f'post_status_set:bad:{item}')],[InlineKeyboardButton('⬅️ Назад',callback_data=f'post_back:{item}')]])
def reminder_kb(item):
    rows=[[InlineKeyboardButton('🧪 1 min test',callback_data=f'post_reminder_set:test:{item}')]]
    for s in range(1,16,3): rows.append([InlineKeyboardButton(f'{d}d',callback_data=f'post_reminder_set:{d}d:{item}') for d in range(s,min(s+3,16))])
    rows.append([InlineKeyboardButton('🗑 Remove reminder',callback_data=f'post_reminder_remove:{item}')]); rows.append([InlineKeyboardButton('⬅️ Назад',callback_data=f'post_back:{item}')])
    return InlineKeyboardMarkup(rows)
def select_topic_kb(uid, action):
    rows=[[InlineKeyboardButton(f"{v.get('icon','📌')} {k}",callback_data=f'{action}:{k}')] for k,v in get_topics(uid).items()]
    rows.append([InlineKeyboardButton('⬅️ Назад',callback_data='menu_topics'),InlineKeyboardButton('❌ Отмена',callback_data='menu_close')])
    return InlineKeyboardMarkup(rows)
def back_kb(): return InlineKeyboardMarkup([[InlineKeyboardButton('⬅️ Назад',callback_data='menu_topics'),InlineKeyboardButton('❌ Отмена',callback_data='menu_close')]])

def task_done(task):
    try: task.result()
    except asyncio.CancelledError: logger.warning('Background task cancelled')
    except Exception as e: logger.error(f'Background task crashed: {type(e).__name__}: {repr(e)}')
async def start_bg_save(query, context):
    uid=query.from_user.id
    if context.application.bot_data.get(f'processing_{uid}'):
        await query.message.reply_text('⏳ Пожалуйста, подожди. Сейчас бот уже обрабатывает предыдущий референс.'); return
    context.application.bot_data[f'processing_{uid}']=True
    t=asyncio.create_task(save_selected_content(query, context)); t.add_done_callback(task_done)
async def update_post(query, item):
    cap=video_caption(item.get('platform',''),item.get('url',''),item.get('notes',''),item.get('priority_label',''),item.get('status_label',''),item.get('reminder_label'))
    try: await query.edit_message_caption(caption=cap, reply_markup=post_kb(item.get('id')))
    except Exception:
        try: await query.edit_message_text(text=cap, reply_markup=post_kb(item.get('id')))
        except Exception: pass

async def start(update, context):
    ensure_owner(OWNER_ID)
    if not await require_access(update, context): return
    await update.message.reply_text('Привет 👋\n\nЭто multi-user Referens Bot.\n\nСначала подключи свою группу через ⚙️ Setup.', reply_markup=reply_panel())
async def menu_cmd(update, context):
    if not await require_access(update, context): return
    await update.message.reply_text('⚙️ Главное меню', reply_markup=main_kb(update.effective_user.id))
async def panel_cmd(update, context):
    if not await require_access(update, context): return
    await update.message.reply_text('Панель открыта ✅', reply_markup=reply_panel())
async def setup_cmd(update, context):
    if not await require_access(update, context): return
    uid=update.effective_user.id; chat=get_chat(uid); topics=get_topics(uid)
    await update.message.reply_text(f'⚙️ Setup\n\nYour ID: `{uid}`\nConnected Chat ID: `{chat}`\nTopics: {len(topics)}\n\nВ группе напиши /connectchat.\nВ нужном топике напиши /connecttopic Название', parse_mode='Markdown', reply_markup=setup_kb())
async def allow_cmd(update, context):
    if not await require_owner(update, context): return
    if not context.args: await update.message.reply_text('Используй: /allow USER_ID Имя'); return
    try: uid=int(context.args[0])
    except ValueError: await update.message.reply_text('USER_ID должен быть числом.'); return
    name=' '.join(context.args[1:]).strip() or 'User'; allow_user(uid, name)
    await update.message.reply_text(f'✅ Доступ выдан: {name} — {uid}')
async def users_cmd(update, context):
    if not await require_owner(update, context): return
    lines=['👥 Allowed users:\n']
    for uid,u in list_users().items(): lines.append(f"{u.get('name')} — `{uid}`\nChat: `{u.get('chat_id')}`\nTopics: {len(u.get('topics',{}))}\n")
    await update.message.reply_text('\n'.join(lines), parse_mode='Markdown')
async def connectchat_cmd(update, context):
    if not await require_access(update, context): return
    if update.effective_chat.type=='private': await update.message.reply_text('Эту команду нужно отправить в группе.'); return
    set_chat(update.effective_user.id, update.effective_chat.id)
    await update.message.reply_text(f'✅ Группа подключена.\nChat ID: `{update.effective_chat.id}`', parse_mode='Markdown')
async def connecttopic_cmd(update, context):
    if not await require_access(update, context): return
    if update.effective_chat.type=='private' or not update.message.message_thread_id: await update.message.reply_text('Напиши эту команду внутри нужного топика в группе.'); return
    name=' '.join(context.args).strip()
    if not name: await update.message.reply_text('Используй: /connecttopic Название'); return
    uid=update.effective_user.id; set_chat(uid, update.effective_chat.id); item=add_topic(uid, name, update.message.message_thread_id, icon_for(name))
    await update.message.reply_text(f"✅ Топик подключён:\n\n{item['icon']} {name}\nChat ID: `{update.effective_chat.id}`\nThread ID: `{update.message.message_thread_id}`", parse_mode='Markdown')
async def id_cmd(update, context):
    await update.message.reply_text(f'Chat ID: {update.effective_chat.id}\nChat type: {update.effective_chat.type}\nThread ID: {update.message.message_thread_id}\nYour user ID: {update.effective_user.id}')
async def topics_cmd(update, context):
    if not await require_access(update, context): return
    await send_photo_or_text(update.message, TOPICS_IMAGE, f'{topics_text(update.effective_user.id)}\n\nЧто хочешь сделать?', topics_menu_kb())
async def info_cmd(update, context):
    if not await require_access(update, context): return
    if file_exists(INFO_IMAGE):
        with open(INFO_IMAGE,'rb') as f: await update.message.reply_photo(photo=f, caption=INFO_SHORT, reply_markup=main_kb(update.effective_user.id))
        await update.message.reply_text(INFO_LONG)
    else: await update.message.reply_text(INFO_SHORT+'\n\n'+INFO_LONG, reply_markup=main_kb(update.effective_user.id))
async def export_cmd(update, context):
    if not await require_access(update, context): return
    await send_photo_or_text(update.message, EXPORT_IMAGE, '📤 Export', export_kb())
async def check_cmd(update, context):
    if not await require_access(update, context): return
    uid=update.effective_user.id; u=get_user(uid) or {}
    await update.message.reply_text(f"✅ Проверка\n\nYour ID: {uid}\nOwner: {'✅' if is_owner(uid) else '❌'}\nChat ID: {u.get('chat_id')}\nTopics: {len(u.get('topics',{}))}\nCookies: {'✅' if COOKIES_FILE.exists() else '❌'}\nDatabase items: {len(load_db())}\nReminders: {len(load_reminders())}")
async def reset_cmd(update, context):
    if not await require_access(update, context): return
    uid=update.effective_user.id; context.application.bot_data.pop(f'processing_{uid}',None); context.application.bot_data.pop(f'queued_{uid}',None)
    await update.message.reply_text('✅ Processing сброшен.')

async def menu_callback(update, context):
    q=update.callback_query; await q.answer()
    if not await require_access(update, context): return
    data=q.data; uid=q.from_user.id
    if data=='menu_main': await safe_edit(q,'⚙️ Главное меню', main_kb(uid)); return
    if data=='menu_close': context.user_data.clear(); await safe_edit(q,'✅ Закрыто.'); return
    if data=='menu_setup': await safe_edit(q, f"⚙️ Setup\n\nChat ID: `{get_chat(uid)}`\nTopics: {len(get_topics(uid))}\n\n/connectchat в группе\n/connecttopic Название внутри темы", setup_kb()); return
    if data=='setup_set_chat': context.user_data['mode']='awaiting_chat_id'; await safe_edit(q,'🔗 Отправь Chat ID группы.\nПример: -1003900260659', InlineKeyboardMarkup([[InlineKeyboardButton('⬅️ Назад',callback_data='menu_setup')]])); return
    if data=='menu_topics': await edit_or_send_photo(q, TOPICS_IMAGE, f'{topics_text(uid)}\n\nЧто хочешь сделать?', topics_menu_kb()); return
    if data=='menu_info': await q.message.reply_text(INFO_SHORT+'\n\n'+INFO_LONG); return
    if data=='menu_export': await edit_or_send_photo(q, EXPORT_IMAGE, '📤 Export', export_kb()); return
    if data=='menu_check': await safe_edit(q, f"✅ Check\nChat ID: {get_chat(uid)}\nTopics: {len(get_topics(uid))}", main_kb(uid)); return
    if data=='owner_panel' and is_owner(uid): await safe_edit(q,'👑 Owner Panel', owner_kb()); return
    if data=='owner_add_user' and is_owner(uid): context.user_data['mode']='awaiting_allow_user'; await safe_edit(q,'Отправь ID и имя:\n123456789 John', owner_kb()); return
    if data=='owner_users' and is_owner(uid):
        lines=['👥 Users:\n']
        for x,u in list_users().items(): lines.append(f"{u.get('name')} — {x}\nChat: {u.get('chat_id')}\nTopics: {len(u.get('topics',{}))}\n")
        await safe_edit(q,'\n'.join(lines), owner_kb()); return
    if data=='owner_revoke_user' and is_owner(uid): context.user_data['mode']='awaiting_revoke_user'; await safe_edit(q,'Отправь ID для удаления доступа:', owner_kb()); return
    if data=='topics_connect_help': await safe_edit(q,'🔗 Открой нужный топик в группе и напиши:\n/connecttopic Название', topics_menu_kb()); return
    if data=='topics_create': context.user_data['mode']='awaiting_new_topic'; await safe_edit(q,'➕ Отправь название нового топика.', back_kb()); return
    if data=='topics_rename': await safe_edit(q,'✏️ Выбери топик:', select_topic_kb(uid,'rename_select')); return
    if data=='topics_delete': await safe_edit(q,'🗑️ Выбери топик:', select_topic_kb(uid,'delete_select')); return
    if data.startswith('rename_select:'):
        context.user_data['mode']='awaiting_rename_topic'; context.user_data['selected_topic']=data.split(':',1)[1]; await safe_edit(q,'Отправь новое название:', back_kb()); return
    if data.startswith('delete_select:'):
        name=data.split(':',1)[1]; await safe_edit(q,f'⚠️ Точно удалить топик?\n{name}', InlineKeyboardMarkup([[InlineKeyboardButton('✅ Да, удалить',callback_data=f'confirm_delete:{name}')],[InlineKeyboardButton('⬅️ Назад',callback_data='topics_delete')]])); return
    if data.startswith('confirm_delete:'):
        name=data.split(':',1)[1]; chat=get_chat(uid); item=get_topics(uid).get(name)
        if item:
            try: await context.bot.delete_forum_topic(chat_id=chat, message_thread_id=item['id'])
            except Exception as e: await safe_edit(q,f'❌ Не удалось удалить в Telegram, но можно убрать из бота. Ошибка: {e}', topics_menu_kb()); return
            remove_topic(uid,name)
        await safe_edit(q,f'🗑️ Удалено\n\n{topics_text(uid)}', topics_menu_kb()); return
    if data=='export_json':
        p=export_json(uid); await q.message.reply_document(document=InputFile(open(p,'rb'), filename='referens_database.json')); return
    if data=='export_csv':
        p=export_csv(uid); await q.message.reply_document(document=InputFile(open(p,'rb'), filename='referens_database.csv')); return

async def save_priority_callback(update, context):
    q=update.callback_query; await q.answer()
    if not await require_access(update, context): return
    if q.data=='cancel_save': context.user_data.pop('content',None); context.user_data.pop('selected_topic',None); await safe_edit(q,'❌ Отменено.'); return
    if q.data=='save_link_only': await save_selected_content(q, context, link_only=True); return
    pk=q.data.replace('save_priority_',''); context.user_data['selected_priority']=pk; await start_bg_save(q, context)
async def post_action_callback(update, context):
    q=update.callback_query; await q.answer()
    if not await require_access(update, context): return
    d=q.data
    if d.startswith('post_priority_menu:'): await q.edit_message_reply_markup(reply_markup=prio_manage_kb(d.split(':',1)[1])); return
    if d.startswith('post_status_menu:'): await q.edit_message_reply_markup(reply_markup=status_kb(d.split(':',1)[1])); return
    if d.startswith('post_reminder_menu:'): await q.edit_message_reply_markup(reply_markup=reminder_kb(d.split(':',1)[1])); return
    if d.startswith('post_back:'): await q.edit_message_reply_markup(reply_markup=post_kb(d.split(':',1)[1])); return
    if d.startswith('post_priority_set:'):
        _,pk,item=d.split(':',2); it=update_item(item, {'priority':pk,'priority_label':PRIORITIES[pk]['label']}); await update_post(q,it); return
    if d.startswith('post_status_set:'):
        _,sk,item=d.split(':',2); it=update_item(item, {'status':sk,'status_label':STATUSES[sk]}); await update_post(q,it); return
    if d.startswith('post_reminder_remove:'):
        item=d.split(':',1)[1]; remove_reminders(item); it=update_item(item, {'reminder':None,'reminder_label':None}); await update_post(q,it); return
    if d.startswith('post_reminder_set:'):
        _,rk,item=d.split(':',2)
        if rk=='test': seconds=60; label='🧪 Test — 1 min'
        else: days=int(rk[:-1]); seconds=days*86400; label=f'🔔 {days} days'
        add_reminder(item, q.from_user.id, time.time()+seconds, label); it=update_item(item, {'reminder':rk,'reminder_label':label,'reminder_due_ts':time.time()+seconds}); await update_post(q,it); return

async def handle_message(update, context):
    if not update.message or not update.message.text: return
    if not await require_access(update, context): return
    text=update.message.text.strip(); uid=update.effective_user.id; mode=context.user_data.get('mode')
    if context.application.bot_data.get(f'processing_{uid}') and has_link(text):
        old=context.application.bot_data.get(f'queued_{uid}')
        if old:
            try: await context.bot.delete_message(chat_id=old['chat_id'], message_id=old['message_id'])
            except Exception: pass
        msg=await update.message.reply_text('⏳ Пожалуйста, подожди. Когда процесс закончится, я открою выбор топика для этой ссылки.')
        context.application.bot_data[f'queued_{uid}']={'content':text,'chat_id':update.effective_chat.id,'message_id':msg.message_id}; return
    if text=='📂 Topics': await topics_cmd(update, context); return
    if text=='⚙️ Setup': await setup_cmd(update, context); return
    if text=='ℹ️ Info': await info_cmd(update, context); return
    if text=='📤 Export': await export_cmd(update, context); return
    if text=='✅ Check': await check_cmd(update, context); return
    if mode=='awaiting_chat_id':
        try: set_chat(uid, int(text)); context.user_data.pop('mode',None); await update.message.reply_text('✅ Chat ID сохранён.', reply_markup=reply_panel())
        except Exception: await update.message.reply_text('Chat ID должен быть числом.')
        return
    if mode=='awaiting_allow_user' and is_owner(uid):
        parts=text.split(); allow_user(int(parts[0]), ' '.join(parts[1:]) or 'User'); context.user_data.pop('mode',None); await update.message.reply_text('✅ Доступ выдан.', reply_markup=reply_panel()); return
    if mode=='awaiting_revoke_user' and is_owner(uid): revoke_user(int(text)); context.user_data.pop('mode',None); await update.message.reply_text('🗑 Доступ удалён.', reply_markup=reply_panel()); return
    if mode=='awaiting_new_topic': await handle_new_topic(update, context, text); return
    if mode=='awaiting_rename_topic': await handle_rename_topic(update, context, text); return
    await process_content(update, context, text)

async def handle_new_topic(update, context, name):
    uid=update.effective_user.id; chat=get_chat(uid)
    if not chat: await update.message.reply_text('❌ Сначала подключи группу через /connectchat.'); return
    try: created=await context.bot.create_forum_topic(chat_id=chat, name=name); add_topic(uid,name,created.message_thread_id,icon_for(name)); context.user_data.pop('mode',None); await update.message.reply_text(f'✅ Топик создан: {name}', reply_markup=topics_menu_kb())
    except Exception as e: await update.message.reply_text(f'❌ Не удалось создать топик: {e}')
async def handle_rename_topic(update, context, new):
    uid=update.effective_user.id; old=context.user_data.get('selected_topic'); chat=get_chat(uid); item=get_topics(uid).get(old)
    if not item: await update.message.reply_text('Топик не найден.'); return
    try: await context.bot.edit_forum_topic(chat_id=chat, message_thread_id=item['id'], name=new); rename_topic(uid,old,new); context.user_data.pop('mode',None); await update.message.reply_text('✅ Переименовано.', reply_markup=topics_menu_kb())
    except Exception as e: await update.message.reply_text(f'❌ Ошибка: {e}')
async def ask_topic_prompt(context, chat_id, uid, text):
    context.user_data['content']=text
    if not get_chat(uid): await context.bot.send_message(chat_id=chat_id,text='❌ Сначала подключи группу через /connectchat.'); return
    if not get_topics(uid): await context.bot.send_message(chat_id=chat_id,text='❌ Нет топиков. Создай или подключи топик.'); return
    url,_=extract_url_note(text); cap=f'📸 {platform(url)}\n\n📌 Куда сохранить профиль?' if url and is_profile(url) else '📌 Куда сохранить?'
    if file_exists(TOPICS_IMAGE):
        with open(TOPICS_IMAGE,'rb') as f: await context.bot.send_photo(chat_id=chat_id, photo=f, caption=cap, reply_markup=topic_kb(uid))
    else: await context.bot.send_message(chat_id=chat_id,text=cap, reply_markup=topic_kb(uid))
async def process_content(update, context, text):
    if has_link(text): await ask_topic_prompt(context, update.effective_chat.id, update.effective_user.id, text)
async def on_topic(update, context):
    q=update.callback_query; await q.answer()
    if not await require_access(update, context): return
    uid=q.from_user.id
    if q.data=='cancel_save': context.user_data.pop('content',None); await safe_edit(q,'❌ Отменено.'); return
    if q.data=='save_link_only': await save_selected_content(q, context, link_only=True); return
    topic=q.data.replace('t_',''); context.user_data['selected_topic']=topic
    url,_=extract_url_note(context.user_data.get('content',''))
    if url and is_profile(url): await start_bg_save(q, context); return
    await q.edit_message_caption(caption=f"{get_topics(uid)[topic].get('icon','📌')} Topic: {topic}\n\n⚡ Выбери priority:", reply_markup=priority_kb())
async def save_selected_content(q, context, link_only=False):
    uid=q.from_user.id; context.application.bot_data[f'processing_{uid}']=True; media=None
    try:
        content=context.user_data.get('content'); topic=context.user_data.get('selected_topic') or next(iter(get_topics(uid)))
        url,note=extract_url_note(content); url=norm_inst(url) if 'instagram.com' in url.lower() else norm_threads(url) if 'threads.' in url.lower() else clean_url(url)
        p=platform(url); chat=get_chat(uid); tid=get_topics(uid)[topic]['id']; icon=get_topics(uid)[topic].get('icon','📌'); item_id=str(uuid.uuid4())
        if is_profile(url):
            await safe_edit(q,f'📸 Делаю скриншот профиля...\n\n{icon} {topic}\n🎬 {p}')
            media=await screenshot_page(url); cap=profile_caption(url,note,p)
            with open(media,'rb') as f: msg=await context.bot.send_photo(chat_id=chat,message_thread_id=tid,photo=f,caption=cap,read_timeout=120,write_timeout=120,connect_timeout=120)
            add_item({'id':item_id,'owner_id':uid,'created_at':now(),'updated_at':now(),'type':'profile_reference','topic':topic,'topic_id':tid,'platform':p,'username':profile_username(url,p),'url':url,'notes':note,'chat_id':chat,'message_id':msg.message_id})
            await safe_edit(q,f'✅ Скриншот профиля сохранён\n\n{icon} {topic}\n🎬 {p}')
        elif threads_disabled(p) or link_only:
            pri=PRIORITIES[context.user_data.get('selected_priority','normal')]['label']; st=STATUSES['new']; cap=video_caption(p,url,note,pri,st)+'\n\n🔗 Saved as link.'
            msg=await context.bot.send_message(chat_id=chat,message_thread_id=tid,text=cap,reply_markup=post_kb(item_id))
            add_item({'id':item_id,'owner_id':uid,'created_at':now(),'updated_at':now(),'type':'link_reference','topic':topic,'topic_id':tid,'platform':p,'url':url,'notes':note,'priority_label':pri,'status_label':st,'chat_id':chat,'message_id':msg.message_id})
            await safe_edit(q,f'✅ Пост сохранён как ссылка\n\n{icon} {topic}\n🎬 {p}')
        else:
            pri=PRIORITIES[context.user_data.get('selected_priority','normal')]['label']; st=STATUSES['new']; await safe_edit(q,f'⏳ Скачиваю видео...\n\n{icon} {topic}\n⚡ Priority: {pri}\n🎬 {p}')
            media=await download_video(url); cap=video_caption(p,url,note,pri,st)
            try:
                with open(media,'rb') as f: msg=await context.bot.send_video(chat_id=chat,message_thread_id=tid,video=f,caption=cap,reply_markup=post_kb(item_id),supports_streaming=True,read_timeout=120,write_timeout=120,connect_timeout=120)
            except Exception:
                with open(media,'rb') as f: msg=await context.bot.send_document(chat_id=chat,message_thread_id=tid,document=f,caption=cap,reply_markup=post_kb(item_id),read_timeout=120,write_timeout=120,connect_timeout=120)
            add_item({'id':item_id,'owner_id':uid,'created_at':now(),'updated_at':now(),'type':'video_reference','topic':topic,'topic_id':tid,'platform':p,'url':url,'notes':note,'priority_label':pri,'status_label':st,'chat_id':chat,'message_id':msg.message_id})
            await safe_edit(q,f'✅ Видео сохранено\n\n{icon} {topic}\n⚡ Priority: {pri}\n🎬 {p}')
        context.user_data.clear()
    except Exception as e:
        logger.error(f'Ошибка обработки медиа: {type(e).__name__}: {repr(e)}')
        await q.message.reply_text(f'❌ Ошибка обработки: {e}')
    finally:
        context.application.bot_data.pop(f'processing_{uid}',None)
        if media and os.path.exists(media):
            try: os.remove(media)
            except Exception: pass
        queued=context.application.bot_data.pop(f'queued_{uid}',None)
        if queued:
            try: await context.bot.delete_message(chat_id=queued['chat_id'], message_id=queued['message_id'])
            except Exception: pass
            await ask_topic_prompt(context, queued['chat_id'], uid, queued['content'])



# =========================
# MODULAR FEATURE WRAPPERS
# =========================

async def backup_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await backup_cmd_mod(update, context, require_owner)


async def restore_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await restore_cmd_mod(update, context, require_owner)


async def connectbackup_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await connectbackup_cmd_mod(update, context, require_owner)


async def autobackup_on_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await autobackup_on_cmd_mod(update, context, require_owner)


async def autobackup_off_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await autobackup_off_cmd_mod(update, context, require_owner)


async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await broadcast_cmd_mod(update, context, require_owner)


async def social_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_access(update, context):
        return
    return await social_cmd_mod(update, context)


async def backup_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await backup_callback_mod(update, context, require_owner, safe_edit_message)


async def social_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_access(update, context):
        return
    return await social_callback_mod(update, context, safe_edit_message)


async def restore_document_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await handle_restore_document(update, context, require_owner)


async def error_handler(update, context): logger.error(f'Update {update} caused error: {type(context.error).__name__}: {repr(context.error)}')
async def post_init(app):
    ensure_owner(OWNER_ID)
    await app.bot.set_my_commands([('start','Open bot'),('menu','Menu'),('setup','Setup'),('connectchat','Connect group'),('connecttopic','Connect topic'),('topics','Topics'),('check','Check'),('id','Get IDs'),('allow','Owner allow user'),('users','Owner users'),('reset','Reset')])
    if app.job_queue: app.job_queue.run_repeating(reminders_job, interval=30, first=10, name='reminders_job')
def main():
    if not BOT_TOKEN: raise ValueError('BOT_TOKEN не найден')
    if not OWNER_ID: raise ValueError('OWNER_ID не найден')
    threading.Thread(target=run_web_server, daemon=True).start()
    app=Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    for name,fn in [('start',start),('menu',menu_cmd),('panel',panel_cmd),('setup',setup_cmd),('connectchat',connectchat_cmd),('connecttopic',connecttopic_cmd),('allow',allow_cmd),('users',users_cmd),('topics',topics_cmd),('info',info_cmd),('export',export_cmd),('id',id_cmd),('check',check_cmd),('reset',reset_cmd)]: app.add_handler(CommandHandler(name,fn))
    app.add_handler(CallbackQueryHandler(menu_callback, pattern='^(menu_|setup_|owner_|topics_|rename_select:|delete_select:|confirm_delete:|export_)'))
    app.add_handler(CallbackQueryHandler(save_priority_callback, pattern='^(save_priority_|save_link_only|cancel_save)'))
    app.add_handler(CallbackQueryHandler(post_action_callback, pattern='^post_'))
    app.add_handler(CallbackQueryHandler(on_topic, pattern='^(t_|save_link_only|cancel_save)'))
    app.add_handler(MessageHandler(filters.Document.ALL, restore_document_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)
    logger.info('Multi-user Referens Bot запущен!')
    app.run_polling(allowed_updates=Update.ALL_TYPES)
if __name__=='__main__': main()
