# sheets_worker.py — guarded, non-crashing Google Sheets worker
import asyncio
import logging
from typing import Optional

try:
    import gspread
    from oauth2client.service_account import ServiceAccountCredentials
except Exception:  # gspread / oauth may not be available or may fail on import
    gspread = None
    ServiceAccountCredentials = None

from telegram import Bot
from config import (
    GOOGLE_SERVICE_ACCOUNT_FILE,
    GOOGLE_SHEET_ID,
    GOOGLE_SHEET_TOKEN_COLUMN_NAME,
)

from database import (
    get_token_owner,
    is_token_used,
    mark_token_used,
)

logger = logging.getLogger(__name__)

CHECK_INTERVAL = 20  # seconds


async def _run_blocking(fn, *args, **kwargs):
    """
    Helper to run blocking IO in a thread so we don't block asyncio loop.
    """
    return await asyncio.to_thread(fn, *args, **kwargs)


async def sheets_worker(bot: Bot):
    """Background worker to check Google Sheets for token submissions.

    This worker is *guarded*: if gspread/credentials/open_by_key fails it logs
    the error and exits cleanly (does not raise an exception that kills the bot).
    """
    logger.info("🟢 Starting Google Sheets worker...")

    # Basic pre-checks
    if not gspread or not ServiceAccountCredentials:
        logger.warning("sheets_worker: gspread or oauth library not available — worker disabled.")
        return

    if not GOOGLE_SERVICE_ACCOUNT_FILE or not GOOGLE_SHEET_ID:
        logger.warning(
            "sheets_worker: GOOGLE_SERVICE_ACCOUNT_FILE or GOOGLE_SHEET_ID not configured — worker disabled."
        )
        return

    # Authorize Google Sheets API (guarded)
    try:
        scope = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
        creds = ServiceAccountCredentials.from_json_keyfile_name(GOOGLE_SERVICE_ACCOUNT_FILE, scope)
        client = gspread.authorize(creds)
    except Exception as e:
        logger.exception("sheets_worker: failed to authorize Google Sheets (disabled): %s", e)
        return

    # Open the sheet (guarded)
    try:
        # open_by_key is blocking; run in thread
        sheet = await _run_blocking(client.open_by_key, GOOGLE_SHEET_ID)
        # use sheet.sheet1 in main loop via thread calls
        sheet = sheet.sheet1
    except Exception as e:
        logger.exception("sheets_worker: failed to open Google Sheet (disabled): %s", e)
        return

    last_checked_row = 0  # index in Python terms relative to get_all_records() list

    while True:
        try:
            # get_all_records is blocking — run in thread
            all_values = await _run_blocking(sheet.get_all_records)
            total_rows = len(all_values)

            if total_rows > last_checked_row:
                new_rows = all_values[last_checked_row:]
                logger.info("sheets_worker: detected %d new row(s)", len(new_rows))

                for row in new_rows:
                    try:
                        token = str(row.get(GOOGLE_SHEET_TOKEN_COLUMN_NAME, "")).strip()
                        if not token:
                            continue

                        user_id = get_token_owner(token)
                        if not user_id:
                            # unknown token — skip
                            continue

                        if is_token_used(token):
                            # already processed
                            continue

                        # mark token used (DB)
                        mark_token_used(token)

                        # notify user — best-effort, don't raise
                        try:
                            await bot.send_message(chat_id=user_id, text="Sizning javobingiz qabul qilindi ✅")
                        except Exception as e_send:
                            logger.exception("sheets_worker: failed to send confirmation to %s: %s", user_id, e_send)

                    except Exception as row_exc:
                        logger.exception("sheets_worker: failed to process row: %s", row_exc)

                last_checked_row = total_rows

        except Exception as e:
            # Log and continue; do not raise so bot stays running
            logger.exception("sheets_worker: unexpected error while reading sheet: %s", e)

        await asyncio.sleep(CHECK_INTERVAL)
