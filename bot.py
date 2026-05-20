import logging
import json
import os
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv('BOT_TOKEN')
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не найден в переменных окружения")

CHAT_ID = -3794802790
TOPICS = ['CowGirl', 'Student', 'Meme', 'Telegram', 'X', 'Threads']
POST_COUNTER_FILE = 'post_counter.json'

def load_post_counter():
    if os.path.exists(POST_COUNTER_FILE):
        try:
            with open(POST_COUNTER_FILE, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError:
            return {topic: 0 for topic in TOPICS}
    return {topic: 0 for topic in TOPICS}

def save_post_counter(counter):
    with open(POST_COUNTER_FILE, 'w') as f:
        json.dump(counter, f)

def get_topic_id(topic_name):
    topic_mapping = {
        'CowGirl': 2,
        'Student': 6,
        'Meme': 7,
        'Telegram': 4,
        'X': 8,
        'Threads': 9
    }
    return topic_mapping.get(topic_name)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 Привет! Я бот для сохранения контента.\n\n"
        "Использование:\n"
        "/save [ССЫЛКА] [ТВОИ_МЫСЛИ]\n\n"
        "Пример:\n"
        "/save https://www.youtube.com/watch?v=xxx Крутое видео про AI"
    )

async def save_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "❌ Ошибка! Используй:\n"
            "/save [ССЫЛКА] [ТВОИ_МЫСЛИ]\n\n"
            "Пример:\n"
            "/save https://youtube.com/watch?v=xxx Мои мысли"
        )
        return
    
    text = ' '.join(context.args)
    
    if not ('http://' in text or 'https://' in text):
        await update.message.reply_text(
            "❌ Ошибка! В сообщении должна быть ссылка (http:// или https://)"
        )
        return
    
    context.user_data['save_content'] = text
    
    keyboard = []
    for topic in TOPICS:
        keyboard.append([InlineKeyboardButton(topic, callback_data=f"topic_{topic}")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "📁 Выбери топик для сохранения:",
        reply_markup=reply_markup
    )

async def topic_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    selected_topic = query.data.replace('topic_', '')
    content = context.user_data.get('save_content', '')
    
    if not content:
        await query.edit_message_text("❌ Ошибка: контент не найден")
        return
    
    parts = content.split(maxsplit=1)
    url = parts[0]
    thoughts = parts[1] if len(parts) > 1 else "Без комментариев"
    
    counter = load_post_counter()
    counter[selected_topic] += 1
    post_number = counter[selected_topic]
    save_post_counter(counter)
    
    message_text = (
        f"📌 Post #{post_number}\n\n"
        f"💭 Мысли:\n{thoughts}\n\n"
        f"🔗 Ссылка:\n{url}\n\n"
        f"⏰ Дата: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
    )
    
    try:
        topic_id = get_topic_id(selected_topic)
        
        if topic_id is not None:
            await context.bot.send_message(
                chat_id=CHAT_ID,
                message_thread_id=topic_id,
                text=message_text
            )
        else:
            await context.bot.send_message(
                chat_id=CHAT_ID,
                text=message_text
            )
        
        await query.edit_message_text(
            f"✅ Контент сохранён в топик '{selected_topic}' (Post #{post_number})!"
        )
    
    except Exception as e:
        logger.error(f"Ошибка при отправке: {e}")
        await query.edit_message_text(f"❌ Ошибка при сохранении: {str(e)}")

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update {update} caused error {context.error}")

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("save", save_command))
    application.add_handler(CallbackQueryHandler(topic_selected, pattern="^topic_"))
    
    application.add_error_handler(error_handler)
    
    logger.info("Бот запущен!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
