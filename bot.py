# bot.py

from telegram.ext import ApplicationBuilder
from config import BOT_TOKEN
from handlers import register_handlers

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    register_handlers(app)
    app.run_polling()

if __name__ == "__main__":
    main()
