import os
from datetime import datetime

# ---------- Storage channels ----------
FEEDBACKS_STORAGE = int(os.getenv("FEEDBACKS_STORAGE"))
WRITING_STORAGE = int(os.getenv("WRITING_STORAGE"))


# ---------- FEEDBACK STORAGE (ALL SKILLS) ----------

def send_admin_card(bot, user_id: int, title: str, content: str):
    """
    Sends AI feedback (Listening / Reading / Writing / Speaking)
    to the FEEDBACKS_STORAGE channel.
    """

    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

    text = (
        f"📥 {title}\n"
        f"👤 User ID: {user_id}\n"
        f"🕒 {timestamp}\n\n"
        f"{content}"
    )

    bot.send_message(
        chat_id=FEEDBACKS_STORAGE,
        text=text,
        parse_mode="Markdown"
    )


# ---------- WRITING ESSAY STORAGE (TASK 1 & 2 ONLY) ----------

def store_writing_essay(bot, text: str, tag: str):
    """
    Stores RAW user writing text to WRITING_STORAGE.

    The BOT sets the tag internally:
      - #writing1
      - #writing2

    The user never sees or provides hashtags.
    """

    if not text or not text.strip():
        return

    message = f"{text.strip()}\n\n{tag}"

    bot.send_message(
        chat_id=WRITING_STORAGE,
        text=message
    )
