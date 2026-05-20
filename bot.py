import logging
import json
import os
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv('BOT_TOKEN')
CHAT_ID = -3794802790
TOPICS = ['CowGirl', 'Student', 'Meme', 'Telegram', 'X', 'Threads']

def load_counter():
    if os.path.exists('counter.json'):
        try:
            with open('counter.json', 'r') as f:
                return json.load(f)
        except:
            return {t: 0 for t in TOPICS}
    return {t: 0 for t in TOPICS}

def save_counter(c):
    with open('counter.json', 'w') as f:
        json.dump(c, f)

def get_topic_id(name):
    mapping = {'CowGirl': 2, 'Student': 6, 'Meme': 7, 'Telegram': 4, 'X': 8, 'Threads': 9}
    return mapping.get(name)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет! Используй: /save [ссылка] [мысли]")

async def save_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Ошибка! /save [ссылка] [мысли]")
        return
    
    text = ' '.join(context.args)
    if 'http' not in text:
        await update.message.reply_text("Нужна ссылка!")
        return
    
    context.user_data['content'] = text
    keyboard = [[InlineKeyboardButton(t, callback_data=f"t_{t}")] for t in TOPICS]
    await update.message.reply_text("Выбери топик:", reply_markup=InlineKeyboardMarkup(keyboard))

async def on_topic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    topic = query.data.replace('t_', '')
    content = context.user_data.get('content', '')
    
    if not content:
        await query.edit_message_text("Ошибка!")
        return
    
    parts = content.split(maxsplit=1)
    url = parts[0]
    thought = parts[1] if len(parts) > 1 else "Без текста"
    
    c = load_counter()
    c[topic] += 1
    num = c[topic]
    save_counter(c)
    
    msg = f"📌 Post #{num}\n\n💭 {thought}\n\n🔗 {url}\n\n⏰ {datetime.now().strftime('%d.%m.%Y %H:%M')}"
    
    try:
        tid = get_topic_id(topic)
        if tid:
            await context.bot.send_message(chat_id=CHAT_ID, message_thread_id=tid, text=msg)
        else:
            await context.bot.send_message(chat_id=CHAT_ID, text=msg)
        await query.edit_message_text(f"✅ Сохранено в {topic} (Post #{num})")
    except Exception as e:
        await query.edit_message_text(f"❌ Ошибка: {e}")

if __name__ == '__main__':
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("save", save_cmd))
    app.add_handler(CallbackQueryHandler(on_topic, pattern="^t_"))
    app.run_polling()
