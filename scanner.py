import os
import sys
import time
import datetime
import pytz
import requests
import yfinance as yf
import pandas as pd
import numpy as np

# Ensure UTF-8 output encoding for emojis on all platforms
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Import Kotak Neo Integration
try:
    from kotak_neo_session import KotakNeoManager
    kotak_manager = KotakNeoManager()
    kotak_active = kotak_manager.authenticate()
except Exception as e:
    kotak_manager = None
    kotak_active = False
    print(f"[Kotak Neo API] Fallback to primary live feed ({e})")

# ==========================================
# 1. CONFIGURATION & STRATEGY CONSTANTS
# ==========================================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Tickers on Yahoo Finance for your winning Indian NSE stocks
STOCKS = {
    "MCX.NS": "MCX",
    "DIXON.NS": "DIXON",
    "BSE.NS": "BSE",
    "CDSL.NS": "CDSL"
}

IST = pytz.timezone('Asia/Kolkata')
EMA_FAST = 9
EMA_SLOW = 21
ATR_LEN = 14
SL_ATR_MULT = 1.5
RR_RATIO = 2.0

# Active Trade State Tracking: {ticker: {"side": "BUY"|"SELL", "entry": float, "tp": float, "sl": float, "time": str}}
active_trades = {ticker: None for ticker in STOCKS}
orb_notified_today = False
daily_trades_history = []

# ==========================================
# 2. TELEGRAM MESSAGING (HTML SAFE MODE)
# ==========================================
def send_telegram_alert(message: str):
    """Sends a robust HTML formatted message to Telegram with error handling."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print(f"[LOCAL CONSOLE LOG]:\n{message}\n")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    for attempt in range(3):
        try:
            res = requests.post(url, json=payload, timeout=10)
            if res.status_code == 200:
                return
            else:
                print(f"Telegram API response ({res.status_code}): {res.text}")
        except Exception as e:
            print(f"Telegram send attempt {attempt+1} failed: {e}")
            time.sleep(2)

# ==========================================
# 3. MATHEMATICAL INDICATORS (EXACT PINE MATCH)
# ==========================================
def calculate_vwap(df_today: pd.DataFrame) -> pd.Series:
    """Calculates true session VWAP starting fresh from 09:15 AM IST."""
    typical_price = (df_today['High'] + df_today['Low'] + df_today['Close']) / 3
    tp_vol = typical_price * df_today['Volume']
    cum_tp_vol = tp_vol.cumsum()
    cum_vol = df_today['Volume'].cumsum()
    cum_vol = cum_vol.replace(0, np.nan)
    return (cum_tp_vol / cum_vol).ffill()

def calculate_atr_wilder(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Calculates ATR using Wilder's RMA formula (TradingView Exact Match)."""
    high = df['High']
    low = df['Low']
    close = df['Close']
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.ewm(alpha=1/period, adjust=False).mean()

# ==========================================
# 4. CORE STRATEGY ENGINE & TRADE LIFECYCLE
# ==========================================
def process_stock_cycle(ticker: str, display_name: str, live_kotak_price: float = None):
    global active_trades, orb_notified_today, daily_trades_history
    
    # 1. Fetch 5 days of 5m data for convergence of 21 EMA & 14 ATR
    try:
        df = yf.download(ticker, period="5d", interval="5m", progress=False)
    except Exception as e:
        print(f"Error fetching data for {ticker}: {e}")
        return

    if df.empty or len(df) < 20:
        return

    # Handle multi-index column formatting from yfinance
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    # Localize timestamps to IST
    if df.index.tz is None:
        df.index = df.index.tz_localize('UTC').tz_convert(IST)
    else:
        df.index = df.index.tz_convert(IST)

    # If live Kotak Neo price is available, update the current bar close/high/low for real-time accuracy
    if live_kotak_price and live_kotak_price > 0:
        df.iloc[-1, df.columns.get_loc('Close')] = live_kotak_price
        if live_kotak_price > df.iloc[-1]['High']:
            df.iloc[-1, df.columns.get_loc('High')] = live_kotak_price
        if live_kotak_price < df.iloc[-1]['Low']:
            df.iloc[-1, df.columns.get_loc('Low')] = live_kotak_price

    # 2. Compute 9 EMA, 21 EMA, and 14 ATR over the continuous multi-day history
    df['EMA9'] = df['Close'].ewm(span=EMA_FAST, adjust=False).mean()
    df['EMA21'] = df['Close'].ewm(span=EMA_SLOW, adjust=False).mean()
    df['ATR'] = calculate_atr_wilder(df, ATR_LEN)

    # 3. Filter strictly for today's trading session
    today_date = df.index[-1].date()
    df_today = df[df.index.date == today_date].copy()

    if df_today.empty:
        return

    # Calculate Session VWAP starting from 09:15
    df_today['VWAP'] = calculate_vwap(df_today)

    # 4. Extract Opening Range (09:15 - 09:30 AM IST)
    orb_df = df_today.between_time("09:15", "09:30")
    if orb_df.empty:
        return

    orb_high = float(orb_df['High'].max())
    orb_low = float(orb_df['Low'].min())

    # Latest confirmed bar
    current = df_today.iloc[-1]
    prev_bar = df_today.iloc[-2] if len(df_today) >= 2 else current
    bar_time_str = df_today.index[-1].strftime("%H:%M")
    current_time_obj = df_today.index[-1].time()

    close_val = float(current['Close'])
    open_val = float(current['Open'])
    high_val = float(current['High'])
    low_val = float(current['Low'])
    prev_close = float(prev_bar['Close'])

    ema9_val = float(current['EMA9'])
    ema21_val = float(current['EMA21'])
    vwap_val = float(current['VWAP'])
    atr_val = float(current['ATR']) if not np.isnan(current['ATR']) else close_val * 0.008

    # -------------------------------------------------------------
    # A. MONITOR ACTIVE POSITION (Check TP / SL Exits)
    # -------------------------------------------------------------
    active = active_trades[ticker]
    if active is not None:
        side = active["side"]
        entry_price = active["entry"]
        tp_target = active["tp"]
        sl_target = active["sl"]

        # BUY Position Monitoring
        if side == "BUY":
            if high_val >= tp_target:
                pnl = tp_target - entry_price
                pnl_pct = (pnl / entry_price) * 100
                msg = (
                    f"🎯 <b>TARGET ACHIEVED (1:2 R:R): {display_name}</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"🟢 <b>Type:</b> BUY Scalp Exited\n"
                    f"💰 <b>Exit Price:</b> ₹{tp_target:.2f}\n"
                    f"💵 <b>Entry Price:</b> ₹{entry_price:.2f}\n"
                    f"📈 <b>Profit Captured:</b> +₹{pnl:.2f} (+{pnl_pct:.2f}%)\n"
                    f"⏰ <b>Time:</b> {bar_time_str} IST"
                )
                send_telegram_alert(msg)
                daily_trades_history.append({"ticker": display_name, "side": "BUY", "result": "PROFIT", "pnl": pnl})
                active_trades[ticker] = None
                return

            elif low_val <= sl_target:
                loss = entry_price - sl_target
                loss_pct = (loss / entry_price) * 100
                msg = (
                    f"🛑 <b>STOP-LOSS HIT: {display_name}</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"🔴 <b>Type:</b> BUY Scalp Stopped Out\n"
                    f"💰 <b>Exit Price:</b> ₹{sl_target:.2f}\n"
                    f"💵 <b>Entry Price:</b> ₹{entry_price:.2f}\n"
                    f"📉 <b>Loss:</b> -₹{loss:.2f} (-{loss_pct:.2f}%)\n"
                    f"⏰ <b>Time:</b> {bar_time_str} IST"
                )
                send_telegram_alert(msg)
                daily_trades_history.append({"ticker": display_name, "side": "BUY", "result": "LOSS", "pnl": -loss})
                active_trades[ticker] = None
                return

        # SELL Position Monitoring
        elif side == "SELL":
            if low_val <= tp_target:
                pnl = entry_price - tp_target
                pnl_pct = (pnl / entry_price) * 100
                msg = (
                    f"🎯 <b>TARGET ACHIEVED (1:2 R:R): {display_name}</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"🟢 <b>Type:</b> SELL Scalp Exited\n"
                    f"💰 <b>Exit Price:</b> ₹{tp_target:.2f}\n"
                    f"💵 <b>Entry Price:</b> ₹{entry_price:.2f}\n"
                    f"📈 <b>Profit Captured:</b> +₹{pnl:.2f} (+{pnl_pct:.2f}%)\n"
                    f"⏰ <b>Time:</b> {bar_time_str} IST"
                )
                send_telegram_alert(msg)
                daily_trades_history.append({"ticker": display_name, "side": "SELL", "result": "PROFIT", "pnl": pnl})
                active_trades[ticker] = None
                return

            elif high_val >= sl_target:
                loss = sl_target - entry_price
                loss_pct = (loss / entry_price) * 100
                msg = (
                    f"🛑 <b>STOP-LOSS HIT: {display_name}</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"🔴 <b>Type:</b> SELL Scalp Stopped Out\n"
                    f"💰 <b>Exit Price:</b> ₹{sl_target:.2f}\n"
                    f"💵 <b>Entry Price:</b> ₹{entry_price:.2f}\n"
                    f"📉 <b>Loss:</b> -₹{loss:.2f} (-{loss_pct:.2f}%)\n"
                    f"⏰ <b>Time:</b> {bar_time_str} IST"
                )
                send_telegram_alert(msg)
                daily_trades_history.append({"ticker": display_name, "side": "SELL", "result": "LOSS", "pnl": -loss})
                active_trades[ticker] = None
                return

    # -------------------------------------------------------------
    # B. ENTRY SCANNER (Only in 09:30 - 15:00 IST Window)
    # -------------------------------------------------------------
    if not (datetime.time(9, 30) <= current_time_obj <= datetime.time(15, 0)):
        return

    # Only look for entry if no active position in this stock
    if active_trades[ticker] is None:
        bull_trend = (ema9_val > ema21_val) and (close_val > vwap_val)
        bear_trend = (ema9_val < ema21_val) and (close_val < vwap_val)

        # Long Setup (Crossover OR Pullback above ORB High)
        long_breakout = (prev_close <= orb_high and close_val > orb_high) and bull_trend
        long_pullback = (low_val <= ema9_val or low_val <= vwap_val) and (close_val > ema9_val) and (close_val > open_val) and (close_val > orb_high) and bull_trend

        # Short Setup (Crossunder OR Pullback below ORB Low)
        short_breakout = (prev_close >= orb_low and close_val < orb_low) and bear_trend
        short_pullback = (high_val >= ema9_val or high_val >= vwap_val) and (close_val < ema9_val) and (close_val < open_val) and (close_val < orb_low) and bear_trend

        # Execute Long Signal
        if long_breakout or long_pullback:
            sl = close_val - (atr_val * SL_ATR_MULT)
            tp = close_val + ((close_val - sl) * RR_RATIO)
            active_trades[ticker] = {"side": "BUY", "entry": close_val, "tp": tp, "sl": sl, "time": bar_time_str}
            
            trigger_type = "ORB Breakout" if long_breakout else "EMA/VWAP Pullback"
            msg = (
                f"🟢 <b>BUY SIGNAL TRIGGERED: {display_name}</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"⚡ <b>Setup:</b> {trigger_type}\n"
                f"💰 <b>Entry Price:</b> ₹{close_val:.2f}\n"
                f"🎯 <b>Target (1:2 R:R):</b> ₹{tp:.2f} (+₹{tp-close_val:.2f})\n"
                f"🛑 <b>Stop-Loss:</b> ₹{sl:.2f} (-₹{close_val-sl:.2f})\n"
                f"📊 <b>ORB High:</b> ₹{orb_high:.2f} | <b>VWAP:</b> ₹{vwap_val:.2f}\n"
                f"⏰ <b>Time:</b> {bar_time_str} IST"
            )
            send_telegram_alert(msg)

        # Execute Short Signal
        elif short_breakout or short_pullback:
            sl = close_val + (atr_val * SL_ATR_MULT)
            tp = close_val - ((sl - close_val) * RR_RATIO)
            active_trades[ticker] = {"side": "SELL", "entry": close_val, "tp": tp, "sl": sl, "time": bar_time_str}
            
            trigger_type = "ORB Breakdown" if short_breakout else "EMA/VWAP Rejection"
            msg = (
                f"🔴 <b>SELL SIGNAL TRIGGERED: {display_name}</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"⚡ <b>Setup:</b> {trigger_type}\n"
                f"💰 <b>Entry Price:</b> ₹{close_val:.2f}\n"
                f"🎯 <b>Target (1:2 R:R):</b> ₹{tp:.2f} (+₹{close_val-tp:.2f})\n"
                f"🛑 <b>Stop-Loss:</b> ₹{sl:.2f} (-₹{sl-close_val:.2f})\n"
                f"📊 <b>ORB Low:</b> ₹{orb_low:.2f} | <b>VWAP:</b> ₹{vwap_val:.2f}\n"
                f"⏰ <b>Time:</b> {bar_time_str} IST"
            )
            send_telegram_alert(msg)

# ==========================================
# 5. ORB LEVEL REPORT (AT 09:30 AM IST)
# ==========================================
def broadcast_orb_levels():
    """Generates a clean visual summary of 09:15-09:30 ORB levels."""
    levels = []
    for ticker, name in STOCKS.items():
        try:
            df = yf.download(ticker, period="1d", interval="5m", progress=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            if df.index.tz is None:
                df.index = df.index.tz_localize('UTC').tz_convert(IST)
            else:
                df.index = df.index.tz_convert(IST)
            
            orb = df.between_time("09:15", "09:30")
            if not orb.empty:
                h = float(orb['High'].max())
                l = float(orb['Low'].min())
                levels.append(f"• <b>{name}</b>: High ₹{h:.2f} | Low ₹{l:.2f}")
        except Exception as e:
            print(f"Error fetching ORB summary for {name}: {e}")

    if levels:
        msg = (
            f"📊 <b>09:15-09:30 ORB LEVELS ESTABLISHED</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            + "\n".join(levels) +
            f"\n\n🎯 <i>Scanner active for breakout & pullback triggers.</i>"
        )
        send_telegram_alert(msg)

# ==========================================
# 6. EOD AUTO-SQUAREOFF & SUMMARY
# ==========================================
def square_off_all_positions():
    """Squares off any remaining positions at 15:15 IST before market close."""
    global active_trades, daily_trades_history
    for ticker, active in active_trades.items():
        if active is not None:
            name = STOCKS[ticker]
            # Fetch CMP
            try:
                df = yf.download(ticker, period="1d", interval="5m", progress=False)
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                cmp_price = float(df['Close'].iloc[-1])
            except Exception:
                cmp_price = active["entry"]

            entry = active["entry"]
            side = active["side"]
            pnl = (cmp_price - entry) if side == "BUY" else (entry - cmp_price)
            pnl_str = f"+₹{pnl:.2f}" if pnl >= 0 else f"-₹{abs(pnl):.2f}"
            
            msg = (
                f"⏰ <b>EOD 15:15 AUTO-SQUAREOFF: {name}</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📌 <b>Side:</b> {side} Position Closed\n"
                f"💵 <b>Entry:</b> ₹{entry:.2f} | <b>Exit CMP:</b> ₹{cmp_price:.2f}\n"
                f"📊 <b>Net PnL:</b> {pnl_str}"
            )
            send_telegram_alert(msg)
            daily_trades_history.append({"ticker": name, "side": side, "result": "EOD_CLOSE", "pnl": pnl})
            active_trades[ticker] = None

# ==========================================
# 7. MAIN ENGINE LOOP
# ==========================================
def run_market_loop():
    global orb_notified_today, kotak_manager, kotak_active
    
    feed_name = "Kotak Neo Direct Institutional API" if kotak_active else "Direct Market Feed"
    start_msg = (
        f"🚀 <b>Intraday Momentum Cloud Scanner Active</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💎 <b>Watchlist:</b> MCX, DIXON, BSE, CDSL\n"
        f"⚡ <b>Strategy:</b> 15m ORB + VWAP + 9/21 EMA + 1:2 ATR TP/SL\n"
        f"🔌 <b>Data Feed:</b> {feed_name}\n"
        f"⏰ <b>Status:</b> Listening for market signals..."
    )
    send_telegram_alert(start_msg)
    print(f"Intraday Scanner Active & Running ({feed_name})...")

    while True:
        now = datetime.datetime.now(IST)
        current_time = now.time()

        # Check for 09:30 AM ORB broadcast
        if not orb_notified_today and current_time >= datetime.time(9, 30) and current_time < datetime.time(15, 0):
            broadcast_orb_levels()
            orb_notified_today = True

        # Check for 15:15 IST Auto-Squareoff
        if current_time >= datetime.time(15, 15) and current_time < datetime.time(15, 20):
            square_off_all_positions()

        # Check for 15:30 IST Market Close
        if current_time >= datetime.time(15, 30):
            summary_lines = []
            for t in daily_trades_history:
                emoji = "🟢" if t["pnl"] > 0 else "🔴"
                summary_lines.append(f"{emoji} {t['ticker']} ({t['side']}): ₹{t['pnl']:+.2f}")
            
            summary_txt = "\n".join(summary_lines) if summary_lines else "No trades triggered today."
            eod_msg = (
                f"🏁 <b>MARKET CLOSED (15:30 IST)</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"<b>Daily Performance Report:</b>\n"
                f"{summary_txt}\n\n"
                f"💤 <i>Scanner shutting down until tomorrow 09:10 AM IST.</i>"
            )
            send_telegram_alert(eod_msg)
            print("Market session finished. Scanner exiting gracefully.")
            break

        # Fetch Kotak live quotes if active
        live_quotes = {}
        if kotak_active and kotak_manager:
            try:
                live_quotes = kotak_manager.get_live_quotes()
            except Exception as e:
                print(f"[Kotak Neo API] Live quote refresh error: {e}")

        # Process each stock
        for ticker, name in STOCKS.items():
            try:
                kotak_price = live_quotes.get(name)
                process_stock_cycle(ticker, name, live_kotak_price=kotak_price)
            except Exception as e:
                print(f"Error processing {name}: {e}")

        # Sleep for 60 seconds before next scan
        time.sleep(60)

if __name__ == "__main__":
    run_market_loop()
