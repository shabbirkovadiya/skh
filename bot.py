# bot.py
# Simple Telegram bot (polling) — Mobile Leak Checker (made by SK)
# Usage:
#   /start
#   /check 7990127515   -> bot asks consent, then calls upstream and returns redacted results
#   /raw 7990127515     -> returns raw upstream JSON (only if ADMIN_TOKEN set & you are ADMIN_ID)
#
# Env vars required:
#   TELEGRAM_TOKEN  (bot token)
#   REMOTE_API_KEY  (TheDarkAgain or real key)
# Optional:
#   REMOTE_API_BASE (default https://osintt.onrender.com/index.php)
#   ADMIN_TOKEN (string to authorize raw output)
#   ADMIN_ID (your Telegram user id as integer) - required to use /raw
#
# Run: python bot.py

import os
import logging
import asyncio
import json
from functools import wraps
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes,
    CallbackQueryHandler, MessageHandler, filters
)
import requests
from time import time

# --- config ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
REMOTE_API_KEY = os.environ.get("REMOTE_API_KEY", "TheDarkAgain")
REMOTE_API_BASE = os.environ.get("REMOTE_API_BASE", "https://osintt.onrender.com/index.php")
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0")) if os.environ.get("ADMIN_ID") else None

if not TELEGRAM_TOKEN:
    raise SystemExit("Set TELEGRAM_TOKEN env var")

# --- logging ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- simple in-memory rate limit per chat (seconds) ---
LAST_CALL = {}  # chat_id -> timestamp
COOLDOWN = 3  # seconds between calls per chat

# --- helpers ---
def validate_indian_number(n: str):
    s = "".join(ch for ch in (n or "") if ch.isdigit())
    return s if len(s) == 10 and s[0] in "6789" else None

def redact_mobile(m):
    if not m: return ""
    m = str(m)
    return "***-***-" + m[-4:] if len(m) >= 4 else "***"

def redact_id(idn):
    if not idn: return ""
    s = str(idn)
    return (s[0] + "***" + s[-2:]) if len(s) > 4 else "***"

def redact_address(addr):
    if not addr: return "REDACTED"
    parts = [p.strip() for p in str(addr).replace(";", "!").split("!") if p.strip()]
    if not parts: return "REDACTED"
    if len(parts) == 1:
        return parts[0][:30] + ("..." if len(parts[0])>30 else "")
    return f"{parts[0][:30]} ... {parts[-1]}"

def redact_record(r):
    return {
        "id": redact_id(r.get("id") or r.get("id_number","")),
        "mobile": redact_mobile(r.get("mobile") or ""),
        "alt_mobile": redact_mobile(r.get("alt_mobile") or ""),
        "name": r.get("name",""),
        "father_name": r.get("father_name",""),
        "address": redact_address(r.get("address","")),
        "circle": r.get("circle",""),
        "id_number": redact_id(r.get("id_number","")),
    }

def rate_limited(chat_id):
    now = time()
    last = LAST_CALL.get(chat_id, 0)
    if now - last < COOLDOWN:
        return True, COOLDOWN - (now - last)
    LAST_CALL[chat_id] = now
    return False, 0

# decorator to require admin
def require_admin(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if not ADMIN_TOKEN or not ADMIN_ID:
            await update.message.reply_text("Admin functionality not configured on server.")
            return
        if user and user.id == ADMIN_ID:
            return await func(update, context)
        await update.message.reply_text("You are not authorized to use this command.")
    return wrapper

# --- bot handlers ---
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Bot started — made by SK\n\n"
        "Usage:\n"
        "/check <10-digit-number>  — run a safe check (asks consent)\n"
        "/raw <number>             — (admin only) returns raw upstream JSON\n\n"
        "Only check numbers you own or have permission for."
    )

async def check_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if rate_limited(chat_id)[0]:
        await update.message.reply_text("Slow down a bit. Try again in a moment.")
        return

    args = context.args
    if not args:
        await update.message.reply_text("Usage: /check 7990127515")
        return

    num = args[0]
    clean = validate_indian_number(num)
    if not clean:
        await update.message.reply_text("Enter valid 10-digit Indian number (starts with 6-9).")
        return

    # Ask for consent using inline keyboard
    keyboard = [
        [InlineKeyboardButton("Confirm (this is mine / I have permission)", callback_data=f"confirm|{clean}"),
         InlineKeyboardButton("Cancel", callback_data="cancel")]
    ]
    await update.message.reply_text(
        f"You're about to check `{clean}`. Do you confirm this is your number or you have permission?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def callback_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    chat_id = query.message.chat_id

    if data == "cancel":
        await query.edit_message_text("Cancelled.")
        return

    if data.startswith("confirm|"):
        num = data.split("|",1)[1]
        # rate limit check again
        limited, wait = rate_limited(chat_id)
        if limited:
            await query.edit_message_text(f"Rate limit: try again in {int(wait)+1}s.")
            return

        # Call upstream
        await query.edit_message_text("Checking... (server-side call)")
        upstream_url = f"{REMOTE_API_BASE}?num={num}&key={REMOTE_API_KEY}"

        try:
            r = requests.get(upstream_url, timeout=10)
        except Exception as e:
            await query.edit_message_text(f"Upstream request failed: {e}")
            return

        if r.status_code != 200:
            await query.edit_message_text(f"Upstream error: {r.status_code} — {r.text[:500]}")
            return

        # parse JSON if possible
        try:
            payload = r.json()
        except Exception:
            text = r.text
            # if not JSON, present raw text but trimmed
            await query.edit_message_text(f"Upstream returned non-json:\n\n{(text or '')[:4000]}")
            return

        rows = payload if isinstance(payload, list) else ([payload] if payload else [])
        if not rows:
            await query.edit_message_text("Good — no records found for this number.")
            return

        # prepare redacted output
        redacted = [redact_record(rec) for rec in rows]
        # send redacted JSON pretty
        pretty = json.dumps(redacted, indent=2, ensure_ascii=False)
        # if too long, send as file
        if len(pretty) > 4000:
            await query.message.reply_document(document=bytes(pretty, "utf-8"), filename=f"result-{num}.json")
            await query.edit_message_text(f"Found {len(rows)} record(s). Sent redacted JSON as file.")
        else:
            await query.edit_message_text(f"Found {len(rows)} record(s). Redacted results:\n\n<pre>{pretty}</pre>", parse_mode="HTML")

# admin raw command
@require_admin
async def raw_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /raw 7990127515")
        return
    num = args[0]
    clean = validate_indian_number(num)
    if not clean:
        await update.message.reply_text("Enter valid 10-digit Indian number.")
        return
    await update.message.reply_text("Fetching raw upstream (admin) ...")
    upstream_url = f"{REMOTE_API_BASE}?num={clean}&key={REMOTE_API_KEY}"
    try:
        r = requests.get(upstream_url, timeout=10)
    except Exception as e:
        await update.message.reply_text(f"Upstream request failed: {e}")
        return
    if r.status_code != 200:
        await update.message.reply_text(f"Upstream error: {r.status_code} — {r.text[:500]}")
        return
    # try to send JSON prettified or as file
    try:
        payload = r.json()
        pretty = json.dumps(payload, indent=2, ensure_ascii=False)
        if len(pretty) > 4000:
            await update.message.reply_document(document=bytes(pretty, "utf-8"), filename=f"raw-{clean}.json")
        else:
            await update.message.reply_text(f"<pre>{pretty}</pre>", parse_mode="HTML")
    except Exception:
        await update.message.reply_text(r.text[:4000])

# fallback: if user just sends a number by message, treat like /check
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (update.message.text or "").strip()
    # if message is exactly 10 digits, trigger check flow
    if validate_indian_number(txt):
        context.args = [txt]
        await check_cmd(update, context)
    else:
        await update.message.reply_text("Send /check <number> or just send a 10-digit Indian number.")

# --- main ---
def main():
    print("Bot started — made by SK")
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("check", check_cmd))
    app.add_handler(CommandHandler("raw", raw_cmd))
    app.add_handler(CallbackQueryHandler(callback_query_handler))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), message_handler))

    # start polling (blocking). Suitable on Render as a background service.
    app.run_polling()

if __name__ == "__main__":
    main()
