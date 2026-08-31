import os
import time
import datetime
import pytz
import requests
import yfinance as yf
import pandas as pd
import numpy as np

# ==========================================
# CONFIGURATION
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

# Store state to prevent duplicate alerts
active_signals = {ticker: None for ticker in STOCKS}

def send_telegram_alert(message: str):
    """Sends a formatted message to your Telegram account."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print(f"[LOCAL LOG - No Telegram keys configured]:\n{message}\n")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Error sending Telegram message: {e}")

def calculate_vwap(df: pd.DataFrame) -> pd.Series:
    """Calculates intraday VWAP."""
    typical_price = (df['High'] + df['Low'] + df['Close']) / 3
    tp_vol = typical_price * df['Volume']
    cum_tp_vol = tp_vol.cumsum()
    cum_vol = df['Volume'].cumsum()
    return cum_tp_vol / cum_vol

def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Calculates Average True Range (ATR)."""
    high = df['High']
    low = df['Low']
    close = df['Close']
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def analyze_stock(ticker: str, display_name: str):
    global active_signals
    
    # Fetch today's 5-minute intraday data
    df = yf.download(ticker, period="1d", interval="5m", progress=False)
    if df.empty or len(df) < 5:
        return

    # Handle multi-index columns if returned by yfinance
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    # Convert index to IST
    if df.index.tz is None:
        df.index = df.index.tz_localize('UTC').tz_convert(IST)
    else:
        df.index = df.index.tz_convert(IST)

    # Filter Opening Range (09:15 to 09:30 AM IST)
    orb_df = df.between_time("09:15", "09:30")
    if orb_df.empty:
        return

    orb_high = orb_df['High'].max()
    orb_low = orb_df['Low'].min()

    # Calculate Indicators
    df['EMA9'] = df['Close'].ewm(span=EMA_FAST, adjust=False).mean()
    df['EMA21'] = df['Close'].ewm(span=EMA_SLOW, adjust=False).mean()
    df['VWAP'] = calculate_vwap(df)
    df['ATR'] = calculate_atr(df, ATR_LEN)

    # Current Candle (Latest confirmed bar)
    current = df.iloc[-1]
    curr_time = df.index[-1].strftime("%H:%M")
    
    current_time_obj = df.index[-1].time()
    # Check if we are in trading window (09:30 - 15:00)
    if not (datetime.time(9, 30) <= current_time_obj <= datetime.time(15, 0)):
        return

    close_val = float(current['Close'])
    open_val = float(current['Open'])
    low_val = float(current['Low'])
    high_val = float(current['High'])
    ema9_val = float(current['EMA9'])
    ema21_val = float(current['EMA21'])
    vwap_val = float(current['VWAP'])
    atr_val = float(current['ATR']) if not np.isnan(current['ATR']) else close_val * 0.008

    bull_trend = (ema9_val > ema21_val) and (close_val > vwap_val)
    bear_trend = (ema9_val < ema21_val) and (close_val < vwap_val)

    # Long Conditions
    long_breakout = (close_val > orb_high) and bull_trend
    long_pullback = (low_val <= ema9_val or low_val <= vwap_val) and (close_val > ema9_val) and (close_val > open_val) and (close_val > orb_high) and bull_trend
    
    # Short Conditions
    short_breakout = (close_val < orb_low) and bear_trend
    short_pullback = (high_val >= ema9_val or high_val >= vwap_val) and (close_val < ema9_val) and (close_val < open_val) and (close_val < orb_low) and bear_trend

    # Check for Long Signal
    if (long_breakout or long_pullback) and active_signals[ticker] != "BUY":
        active_signals[ticker] = "BUY"
        sl = close_val - (atr_val * SL_ATR_MULT)
        tp = close_val + ((close_val - sl) * RR_RATIO)
        
        msg = (
            f"🟢 *BUY SIGNAL: {display_name}*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💰 *Entry Price:* ₹{close_val:.2f}\n"
            f"🎯 *Target (1:2 R:R):* ₹{tp:.2f}\n"
            f"🛑 *Stop-Loss:* ₹{sl:.2f}\n"
            f"📊 *ORB High:* ₹{orb_high:.2f} | *VWAP:* ₹{vwap_val:.2f}\n"
            f"⏰ *Time:* {curr_time} IST"
        )
        send_telegram_alert(msg)

    # Check for Short Signal
    elif (short_breakout or short_pullback) and active_signals[ticker] != "SELL":
        active_signals[ticker] = "SELL"
        sl = close_val + (atr_val * SL_ATR_MULT)
        tp = close_val - ((sl - close_val) * RR_RATIO)
        
        msg = (
            f"🔴 *SELL SIGNAL: {display_name}*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💰 *Entry Price:* ₹{close_val:.2f}\n"
            f"🎯 *Target (1:2 R:R):* ₹{tp:.2f}\n"
            f"🛑 *Stop-Loss:* ₹{sl:.2f}\n"
            f"📊 *ORB Low:* ₹{orb_low:.2f} | *VWAP:* ₹{vwap_val:.2f}\n"
            f"⏰ *Time:* {curr_time} IST"
        )
        send_telegram_alert(msg)

def run_market_loop():
    send_telegram_alert("🚀 *Intraday Scanner Started for MCX, DIXON, BSE, CDSL*")
    print("Intraday Scanner Active...")
    
    while True:
        now = datetime.datetime.now(IST)
        
        # Stop scanner after market close (15:30 IST)
        if now.time() >= datetime.time(15, 30):
            send_telegram_alert("🏁 *Market Closed (15:30 IST). Scanner Stopping.*")
            break
            
        # Scan stocks
        for ticker, name in STOCKS.items():
            try:
                analyze_stock(ticker, name)
            except Exception as e:
                print(f"Error scanning {name}: {e}")
                
        time.sleep(60)

if __name__ == "__main__":
    run_market_loop()
