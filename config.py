# config.py

import os

# 🛡️ Admin users
ADMIN_IDS = {1150875355}

# 📤 Storage channel
STORAGE_CHANNEL_ID = -1002714023986  # change if needed

# 🧠 User file for legacy compatibility
USER_FILE = "user_data.json"

# 🔐 Bot token from environment
BOT_TOKEN = os.environ.get("BOT_TOKEN") 

GOOGLE_SERVICE_ACCOUNT_FILE = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE", "service_account.json")
GOOGLE_SHEET_ID = os.environ.get("GOOGLE_SHEET_ID")
GOOGLE_FORM_BASE = os.environ.get("GOOGLE_FORM_BASE")
GOOGLE_FORM_ENTRY_TOKEN = os.environ.get("GOOGLE_FORM_ENTRY_TOKEN")
GOOGLE_SHEET_TOKEN_COLUMN_NAME = os.environ.get("GOOGLE_SHEET_TOKEN_COLUMN_NAME", "Your token")
