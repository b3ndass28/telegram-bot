import os
from pathlib import Path

BOT_TOKEN = os.getenv('BOT_TOKEN')
OWNER_ID = int(os.getenv('OWNER_ID', '0'))

BASE_DIR = Path(__file__).resolve().parent
SETTINGS_FILE = BASE_DIR / 'settings.json'
DATABASE_FILE = BASE_DIR / 'database.json'
REMINDERS_FILE = BASE_DIR / 'reminders.json'
ANALYTICS_FILE = BASE_DIR / 'analytics.json'
BACKUP_SETTINGS_FILE = BASE_DIR / 'backup_settings.json'
DOWNLOAD_DIR = BASE_DIR / 'downloads'
COOKIES_FILE = BASE_DIR / 'cookies.txt'
ASSETS_DIR = BASE_DIR / 'assets'
TOPICS_IMAGE = ASSETS_DIR / 'topics.jpg'
INFO_IMAGE = ASSETS_DIR / 'info.jpg'
EXPORT_IMAGE = ASSETS_DIR / 'export.jpg'
DOWNLOAD_DIR.mkdir(exist_ok=True)

PRIORITIES = {
    'high': {'label': '🔥 High'},
    'normal': {'label': '⭐ Normal'},
    'later': {'label': '🧊 Later'},
}
STATUSES = {
    'new': '🆕 New',
    'progress': '🟡 In Progress',
    'done': '✅ Done',
    'bad': '❌ Not Suitable',
}
