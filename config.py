import os
from pathlib import Path

BOT_TOKEN = os.getenv('BOT_TOKEN')
OWNER_ID = int(os.getenv('OWNER_ID', '0'))

BASE_DIR = Path(__file__).resolve().parent
SETTINGS_FILE = BASE_DIR / 'settings.json'
DATABASE_FILE = BASE_DIR / 'database.json'
REMINDERS_FILE = BASE_DIR / 'reminders.json'
BACKUP_SETTINGS_FILE = BASE_DIR / 'backup_settings.json'
DOWNLOAD_DIR = BASE_DIR / 'downloads'
COOKIES_FILE = BASE_DIR / 'cookies.txt'
ASSETS_DIR = BASE_DIR / 'assets'

TOPICS_IMAGE = ASSETS_DIR / 'topics.jpg'
INFO_IMAGE = ASSETS_DIR / 'info.jpg'
EXPORT_IMAGE = ASSETS_DIR / 'export.jpg'
MENU_IMAGE = ASSETS_DIR / 'menu.jpg'
REMINDERS_IMAGE = ASSETS_DIR / 'reminders.jpg'
REMINDER_ALERT_IMAGE = ASSETS_DIR / 'reminder_alert.jpg'
OWNER_IMAGE = ASSETS_DIR / 'owner.jpg'
BACKUP_IMAGE = ASSETS_DIR / 'backup.jpg'
USERS_IMAGE = ASSETS_DIR / 'users.jpg'
SETTINGS_IMAGE = ASSETS_DIR / 'settings.jpg'
EMPTY_IMAGE = ASSETS_DIR / 'empty.jpg'

DOWNLOAD_DIR.mkdir(exist_ok=True)
ASSETS_DIR.mkdir(exist_ok=True)

PRIORITIES = {
    'high': {'label': '🔥 Высокий'},
    'normal': {'label': '⭐ Обычный'},
    'later': {'label': '🧊 Потом'},
}
STATUSES = {
    'new': '🆕 Новый',
    'reviewed': '👀 Просмотрен',
    'progress': '🟡 В работе',
    'done': '✅ Сделано',
    'bad': '❌ Не подходит',
}
