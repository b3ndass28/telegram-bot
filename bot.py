import logging
import json
import os
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

# Настройки логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Конфиг
BOT_TOKEN = os.getenv('BOT_TOKEN', '8874972095:AAGsabDd2bc0Sdm72Z80IJMUnXgJ6K2sYxQ')
CHAT_ID = -3794802790  # Твой чат ID
TOPICS = ['CowGirl', 'Student', 'Meme', 'Telegram', 'X', 'Threads']

# Сохраняем счётчик постов
POST_COUNTER_FILE = 'post_counter.json'

def load_post_counter():
    """Загружает счётчик постов из файла"""
    if os.path.exists(POST_COUNTER_FILE):
        with open(POST_COUNTER_FILE, 'r') as f:
            return json.load(f)
    return {topic: 0 for topic in TOPICS}

def save_post_counter(counter):
    """Сохраняет счётчик постов в файл"""
    with open(POST_COUNTER_FILE, 'w') as f:
        json.dump(counter, f)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start"""
    await update.message.reply_text(
        "🤖 Привет! Я бот для сохранения контента.\n\n"
        "Использование:\n"
        "/save [ССЫЛКА] [ТВОИ_МЫСЛИ]\n\n"
        "Пример:\n"
        "/save https://www.youtube.com/watch?v=xxx Крутое видео про AI"
    )

async def save_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /save - сохранить контент"""
    
    # Проверяем, есть ли аргументы
    if not context.args:
        await update.message.reply_text(
            "❌ Ошибка! Используй:\n"
            "/save [ССЫЛКА] [ТВОИ_МЫСЛИ]\n\n"
            "Пример:\n"
            "/save https://youtube.com/watch?v=xxx Мои мысли"
        )
        return
    
    # Парсим аргументы
    text = ' '.join(context.args)
    
    # Проверяем, есть ли ссылка
    if not ('http://' in text or 'https://' in text):
        await update.message.reply_text(
            "❌ Ошибка! В сообщении должна быть ссылка (http:// или https://)"
        )
        return
    
    # Сохраняем данные во временное хранилище
    context.user_data['save_content'] = text
    
    # Создаём кнопки для выбора топика
    keyboard = []
    for topic in TOPICS:
        keyboard.append([InlineKeyboardButton(topic, callback_data=f"topic_{topic}")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "📁 Выбери топик для сохранения:",
        reply_markup=reply_markup
    )

async def topic_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора топика"""
    query = update.callback_query
    await query.answer()
    
    # Получаем выбранный топик
    selected_topic = query.data.replace('topic_', '')
    
    # Получаем сохранённые данные
    content = context.user_data.get('save_content', '')
    
    if not content:
        await query.edit_message_text("❌ Ошибка: контент не найден")
        return
    
    # Парсим ссылку и мысли
    parts = content.split(maxsplit=1)
    url = parts[0]
    thoughts = parts[1] if len(parts) > 1 else "Без комментариев"
    
    # Загружаем счётчик постов
    counter = load_post_counter()
    counter[selected_topic] += 1
    post_number = counter[selected_topic]
    save_post_counter(counter)
    
    # Формируем сообщение для отправки в топик
    message_text = (
        f"📌 Post #{post_number}\n\n"
        f"💭 Мысли:\n{thoughts}\n\n"
        f"🔗 Ссылка:\n{url}\n\n"
        f"⏰ Дата: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
    )
    
    try:
        # Получаем ID топика для выбранной темы
        topic_id = get_topic_id(selected_topic)
        
        if topic_id:
            # Отправляем сообщение в топик
            await context.bot.send_message(
                chat_id=CHAT_ID,
                message_thread_id=topic_id,
                text=message_text
            )
        else:
            # Если топик не найден, просто отправляем в чат
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

def get_topic_id(topic_name: str) -> int:
    """
    Получает ID топика по названию
    """
    topic_mapping = {
        'CowGirl': 2,
        'Student': 6,
        'Meme': 7,
        'Telegram': 4,
        'X': 8,
        'Threads': 9
    }
    return topic_mapping.get(topic_name)

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик ошибок"""
    logger.error(f"Update {update} caused error {context.error}")

def main():
    """Запуск бота"""
    # Создаём приложение
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Добавляем обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("save", save_command))
    
    # Обработчик нажатия на кнопки
    application.add_handler(CallbackQueryHandler(topic_selected, pattern="^topic_"))
    
    # Обработчик ошибок
    application.add_error_handler(error_handler)
    
    # Запускаем бота
    logger.info("Бот запущен!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
