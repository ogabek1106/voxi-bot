#sheets_worker.py

import asyncio
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from telegram import Bot
from config import (
    GOOGLE_SERVICE_ACCOUNT_FILE,
    GOOGLE_SHEET_ID,
    GOOGLE_SHEET_TOKEN_COLUMN_NAME
)
from database import (
    get_token_owner,
    is_token_used,
    mark_token_used
)

CHECK_INTERVAL = 20  # seconds


async def sheets_worker(bot: Bot):
    """Background worker to check Google Sheets for token submissions."""
    print("🟢 Starting Google Sheets worker...")

    # Authorize Google Sheets API
    scope = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
    creds = ServiceAccountCredentials.from_json_keyfile_name(
        GOOGLE_SERVICE_ACCOUNT_FILE, scope
    )
    client = gspread.authorize(creds)

    sheet = client.open_by_key(GOOGLE_SHEET_ID).sheet1

    last_checked_row = 1

    while True:
        try:
            all_values = sheet.get_all_records()
            total_rows = len(all_values)

            if total_rows > last_checked_row:
                # process only new rows
                new_rows = all_values[last_checked_row:]

                for row in new_rows:
                    token = str(row.get(GOOGLE_SHEET_TOKEN_COLUMN_NAME, "")).strip()

                    if not token:
                        continue

                    user_id = get_token_owner(token)

                    # Unknown token
                    if not user_id:
                        continue

                    # Token used → skip
                    if is_token_used(token):
                        continue

                    # Mark used
                    mark_token_used(token)

                    # Send success message
                    try:
                        await bot.send_message(
                            chat_id=user_id,
                            text="Sizning javobingiz qabul qilindi ✅"
                        )
                    except Exception as e:
                        print(f"Error sending message to {user_id}: {e}")

                last_checked_row = total_rows

        except Exception as e:
            print(f"[Sheets Worker Error] {e}")

        await asyncio.sleep(CHECK_INTERVAL)
