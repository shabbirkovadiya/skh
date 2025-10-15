# bot.py
# Simple Telegram bot — Mobile Leak Checker (made by SK)
# Usage:
#   /start
#   /check <10-digit-number>  -> bot calls upstream API and returns raw JSON
#
# Env vars required:
#   TELEGRAM_TOKEN
#   REMOTE_API_KEY
# Optional:
#   REMOTE_API_BASE (default https://osintt.onrender.com/index.php)
# Run: python bot.py

import os
import json
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters
import requests

# --- config ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
REMOTE_API_KEY = os.environ.get("REMOTE_API_KEY", "TheDarkAgain")
REMOTE_API_BASE = os.environ.get("REMOTE_API_BASE", "https://osintt.onrender.com/index.php")

if not TELEGRAM_TOKEN:
    raise SystemExit("Set TELEGRAM_TOKEN env var")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def validate_indian_number(n: str):
    s = "".join(ch for ch in (n or "") if ch.isdigit())
    return s if len(s) == 10 and s[0] in "6789" else None

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Bot started — made by Shabbir Kovadiya  \ninsta id: sk.jsx\n"
        "Send /check <10-digit-number> or just send a 10-digit number.\n"
        "Only check numbers you own or have permission for."
    )

async def check_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /check 1234567890")
        return

    num = args[0]
    clean = validate_indian_number(num)
    if not clean:
        await update.message.reply_text("Enter valid 10-digit Indian number (starts with 6-9).")
        return

    await update.message.reply_text("Checking...")

    try:
        r = requests.get(f"{REMOTE_API_BASE}?num={clean}&key={REMOTE_API_KEY}", timeout=10)
        r.raise_for_status()
        try:
            payload = r.json()
            pretty = json.dumps(payload, indent=2, ensure_ascii=False)
            # If too long, send as file
            if len(pretty) > 4000:
                await update.message.reply_document(document=bytes(pretty, "utf-8"), filename=f"{clean}.json")
            else:
                await update.message.reply_text(f"<pre>{pretty}</pre>", parse_mode="HTML")
        except Exception:
            # If response is not JSON, send raw text
            await update.message.reply_text(r.text[:4000])
    except Exception as e:
        await update.message.reply_text(f"API request failed: {e}")

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (update.message.text or "").strip()
    if validate_indian_number(txt):
        context.args = [txt]
        await check_cmd(update, context)
    else:
        await update.message.reply_text("Send /check <number> or just a 10-digit Indian number.")

def main():
    print("Bot started")
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("check", check_cmd))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), message_handler))

    app.run_polling()

if __name__ == "__main__":
    main()
