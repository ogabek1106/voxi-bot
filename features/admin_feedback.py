from datetime import datetime
from config import STORAGE_CHAT_ID


def send_admin_card(bot, user_id: int, title: str, content: str):
    """
    Sends an admin-style feedback card to the private storage channel.
    Used for mirroring user feedback (Writing / Speaking).
    """

    text = (
        f"📥 {title}\n"
        f"👤 User ID: {user_id}\n\n"
        f"{content}"
    )

    bot.send_message(
        chat_id=STORAGE_CHAT_ID,
        text=text,
        parse_mode="Markdown"
    )
