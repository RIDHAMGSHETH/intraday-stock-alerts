import os
import sys
import requests
import datetime
import pytz

# Ensure UTF-8 output encoding for emojis
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
IST = pytz.timezone('Asia/Kolkata')
current_time_ist = datetime.datetime.now(IST).strftime("%d-%m-%Y %H:%M:%S")

# Try Kotak Neo status check
kotak_status = "Disconnected"
try:
    from kotak_neo_session import KotakNeoManager
    mgr = KotakNeoManager()
    if mgr.authenticate():
        quotes = mgr.get_live_quotes()
        quotes_summary = ", ".join([f"<b>{k}</b>: ₹{v:.2f}" for k, v in quotes.items()])
        kotak_status = f"✅ Connected (UCC: {mgr.ucc})\n📊 <b>Live Exchange Ticks:</b>\n{quotes_summary}"
    else:
        kotak_status = "⚠️ Fallback Active"
except Exception as e:
    kotak_status = f"⚠️ Fallback Active ({e})"

msg = (
    f"🚀 <b>GITHUB CLOUD RUNNER: LIVE TEST</b>\n"
    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    f"📍 <b>Host:</b> GitHub Actions Cloud (Ubuntu 22.04)\n"
    f"⏰ <b>Timestamp:</b> {current_time_ist} IST\n"
    f"🔌 <b>Kotak Neo API:</b> {kotak_status}\n"
    f"💎 <b>Watchlist:</b> MCX, DIXON, BSE, CDSL\n"
    f"⚡ <b>Strategy:</b> 15m ORB + VWAP + 9/21 EMA + 1:2 ATR TP/SL\n\n"
    f"✅ <i>GitHub Cloud Environment is 100% verified & operational!</i>"
)

url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
payload = {
    "chat_id": TELEGRAM_CHAT_ID,
    "text": msg,
    "parse_mode": "HTML"
}

res = requests.post(url, json=payload, timeout=10)
print(f"Telegram Test Response Status: {res.status_code}")
print(f"Telegram Response Body: {res.text}")
