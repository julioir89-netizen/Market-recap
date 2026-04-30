import os
import csv
import sys
import json
import time
import requests
import yfinance as yf
import smtplib
from datetime import datetime, date, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ─── CONFIG ───────────────────────────────────────────────────────────────────
SANDBOX_URL      = "https://api.cert.tastyworks.com"
LIVE_URL         = "https://api.tastyworks.com"
TT_USERNAME      = os.environ["TT_SANDBOX_USERNAME"]
TT_PASSWORD      = os.environ["TT_SANDBOX_PASSWORD"]
TT_ACCOUNT       = os.environ["TT_SANDBOX_ACCOUNT"]
TT_LIVE_USER     = os.environ["TT_LIVE_USERNAME"]
TT_LIVE_PASS     = os.environ["TT_LIVE_PASSWORD"]
EMAIL_TO         = os.environ["EMAIL_TO"]
EMAIL_FROM       = os.environ["EMAIL_FROM"]
EMAIL_PASS       = os.environ["EMAIL_PASSWORD"]
TELEGRAM_TOKEN   = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

WATCHLIST = ["SPY","QQQ","SOXX","AAPL","NVDA","MU","XLI","XLV","IAU","KBWB"]
LOG_FILE  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trade_log.csv")
LOG_HEADERS = [
    "date","ticker","strategy","strikes","expiration","dte",
    "delta","gamma","theta","ivr","grade","score",
    "max_risk","max_gain","regime","status","pl_result","notes"
]

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# ─── TELEGRAM ─────────────────────────────────────────────────────────────────
def telegram_send(text):
    try:
        requests.post(
            f"{TELEGRAM_API}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text,
                "parse_mode": "HTML"
            },
            timeout=10
        )
    except Exception as e:
        print(f"Telegram send error: {e}")

def telegram_send_buttons(text, setup_index):
    try:
        r = requests.post(
            f"{TELEGRAM_API}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text,
                "parse_mode": "HTML",
                "reply_markup": {
                    "inline_keyboard": [[
                        {"text": "✅ EXECUTE TRADE", "callback_data": f"execute_{setup_index}"},
                        {"text": "❌ SKIP",          "callback_data": f"skip_{setup_index}"}
                    ]]
                }
            },
            timeout=10
        )
        data = r.json()
        return data.get("result", {}).get("message_id")
    except Exception as e:
        print(f"Telegram button error: {e}")
        return None

def telegram_get_updates(offset=None):
    try:
        params = {"timeout": 30, "allowed_updates": ["callback_query"]}
        if offset:
            params["offset"] = offset
        r = requests.get(f"{TELEGRAM_API}/getUpdates", params=params, timeout=35)
        return r.json().get("result", [])
    except Exception as e:
        print(f"Telegram updates error: {e}")
        return []

def telegram_answer_callback(callback_id, text):
    try:
        requests.post(
            f"{TELEGRAM_API}/answerCallbackQuery",
            json={"callback_query_id": callback_id, "text": text},
            timeout=10
        )
    except:
        pass

def wait_for_response(setup_index, timeout_seconds=300):
    print(f"  Waiting up to {timeout_seconds}s for response on setup {setup_index}...")
    start_time = time.time()
    offset     = None
    old_updates = telegram_get_updates()
    if old_updates:
        offset = old_updates[-1]["update_id"] + 1
    while time.time() - start_time < timeout_seconds:
        updates = telegram_get_updates(offset)
        for update in updates:
            offset = update["update_id"] + 1
            cb     = update.get("callback_query", {})
            data   = cb.get("data", "")
            cb_id  = cb.get("id")
            if data == f"execute_{setup_index}":
                telegram_answer_callback(cb_id, "Executing trade...")
                return "execute"
            elif data == f"skip_{setup_index}":
                telegram_answer_callback(cb_id, "Trade skipped.")
                return "skip"
        time.sleep(3)
    return "timeout"

# ─── TASTYTRADE AUTH ──────────────────────────────────────────────────────────
def get_session_token():
    r = requests.post(
        f"{SANDBOX_URL}/sessions",
        json={"login": TT_USERNAME, "password": TT_PASSWORD},
        headers={"Content-Type": "application/json"}
    )
    r.raise_for_status()
    return r.json()["data"]["session-token"]

def get_live_session_token():
    r = requests.post(
        f"{LIVE_URL}/sessions",
        json={"login": TT_LIVE_USER, "password": TT_LIVE_PASS},
        headers={"Content-Type": "application/json"}
    )
    r.raise_for_status()
    return r.json()["data"]["session-token"]

def tt_headers(token):
    return {"Authorization": token, "Content-Type": "application/json"}

def live_headers(token):
    return {"Authorization": token, "Content-Type": "application/json"}

# ─── MARKET DATA ──────────────────────────────────────────────────────────────
def get_market_data():
    spy      = yf.Ticker("SPY")
    qqq      = yf.Ticker("QQQ")
    vix      = yf.Ticker("^VIX")
    spy_hist = spy.history(period="60d")
    qqq_hist = qqq.history(period="5d")
    vix_hist = vix.history(period="5d")
    spy_close   = spy_hist["Close"]
    spy_price   = round(float(spy_close.iloc[-1]), 2)
    spy_ma20    = round(float(spy_close.rolling(20).mean().iloc[-1]), 2)
    spy_ma50    = round(float(spy_close.rolling(50).mean().iloc[-1]), 2)
    qqq_price   = round(float(qqq_hist["Close"].iloc[-1]), 2)
    qqq_prev    = round(float(qqq_hist["Close"].iloc[-2]), 2)
    spy_prev    = round(float(spy_close.iloc[-2]), 2)
    spy_chg_pct = round(((spy_price - spy_prev) / spy_prev) * 100, 2)
    qqq_chg_pct = round(((qqq_price - qqq_prev) / qqq_prev) * 100, 2)
    vix_price   = round(float(vix_hist["Close"].iloc[-1]), 2)
    vix_prev    = round(float(vix_hist["Close"].iloc[-2]), 2)
    vix_chg     = round(vix_price - vix_prev, 2)
    vix_dir     = "RISING" if vix_chg > 0 else "FALLING"
    return {
        "spy_price": spy_price, "spy_ma20": spy_ma20, "spy_ma50": spy_ma50,
        "spy_chg_pct": spy_chg_pct, "qqq_chg_pct": qqq_chg_pct,
        "vix_price": vix_price, "vix_chg": vix_chg, "vix_dir": vix_dir,
        "spy_above_20": spy_price > spy_ma20,
        "spy_above_50": spy_price > spy_ma50,
        "qqq_leading":  qqq_chg_pct > spy_chg_pct,
    }

# ─── IVR ─────────────────────────────────────────────────────────────────────
def get_ivr_yahoo(ticker):
    try:
        t    = yf.Ticker(ticker)
        hist = t.history(period="1y")
        if hist.empty:
            return None, "No data"
        hist["range"] = hist["High"] - hist["Low"]
        current_range = float(hist["range"].iloc[-1])
        high_52w      = float(hist["range"].max())
        low_52w       = float(hist["range"].min())
        if high_52w == low_52w:
            return 50, "NEUTRAL"
        ivr = round(((current_range - low_52w) / (high_52w - low_52w)) * 100, 1)
        if ivr < 25:   bias = "BUY (debit spreads)"
        elif ivr < 50: bias = "BUY-LEAN"
        elif ivr < 75: bias = "NEUTRAL"
        elif ivr < 90: bias = "SELL (credit spreads)"
        else:          bias = "EXTREME — far OTM only"
        return ivr, bias
    except Exception as e:
        return None, f"Error: {e}"

# ─── EVENT CALENDAR ───────────────────────────────────────────────────────────
def check_event_risk():
    fed_dates = [
        date(2026,1,29), date(2026,3,19), date(2026,4,29),
        date(2026,6,11), date(2026,7,29), date(2026,9,17),
        date(2026,11,5), date(2026,12,10),
    ]
    today      = date.today()
    days_ahead = [(d - today).days for d in fed_dates if (d - today).days >= 0]
    nearest    = min(days_ahead) if days_ahead else 99
    if nearest == 0:   return "FED TODAY",              "RED"
    elif nearest == 1: return "FED TOMORROW",            "RED"
    elif nearest <= 3: return f"FED IN {nearest} DAYS",  "YELLOW"
    else:              return f"Next Fed in {nearest} days", "GREEN"

# ─── REGIME ──────────────────────────────────────────────────────────────────
def classify_regime(data):
    above_20 = data["spy_above_20"]
    above_50 = data["spy_above_50"]
    vix_val  = data["vix_price"]
    vix_dir  = data["vix_dir"]
    spy_chg  = abs(data["spy_chg_pct"])
    if vix_val > 28 or (vix_val > 22 and spy_chg > 2.0):
        return "D", "HIGH VOLATILITY / RISK-OFF"
    if above_20 and above_50 and vix_dir == "FALLING" and vix_val < 20:
        return "A", "BULL TREND"
    if not above_20 and not above_50 and vix_dir == "RISING":
        return "B", "BEAR TREND / DOWNTREND"
    return "C", "RANGE / CHOP"

# ─── GRADE ───────────────────────────────────────────────────────────────────
def calculate_grade(regime, ivr, vix, event_color, spy_chg):
    score = 0
    if regime in ["A","B","C"]: score += 20
    elif regime == "D":         score += 8
    else:                       score += 5
    if ivr is not None:
        if ivr < 50:   score += 20
        elif ivr < 75: score += 12
        else:          score += 6
    if vix < 18:         score += 20
    elif vix < 22:       score += 14
    elif vix < 28:       score += 8
    if event_color == "GREEN":    score += 20
    elif event_color == "YELLOW": score += 10
    if abs(spy_chg) < 0.8:   score += 20
    elif abs(spy_chg) < 1.5: score += 12
    elif abs(spy_chg) < 2.0: score += 6
    if score >= 90:   return score, "A+", "STRONG RECOMMEND"
    elif score >= 80: return score, "A",  "RECOMMEND"
    elif score >= 70: return score, "A-", "RECOMMEND reduced size"
    elif score >= 60: return score, "B+", "BORDERLINE"
    elif score >= 50: return score, "B",  "GRAY ZONE"
    elif score >= 40: return score, "B-", "LEAN SKIP"
    else:             return score, "--", "NO EDGE"

# ─── OPTIONS CHAIN ────────────────────────────────────────────────────────────
def get_option_chain(live_token, ticker):
    try:
        r = requests.get(
            f"{LIVE_URL}/option-chains/{ticker}/nested",
            headers=live_headers(live_token)
        )
        if r.status_code != 200:
            return None
        return r.json().get("data", {}).get("items", [])
    except Exception as e:
        print(f"  Chain error {ticker}: {e}")
        return None

def find_best_expiration(chain, min_dte=30, max_dte=60):
    today    = date.today()
    best     = None
    best_dte = 999
    for expiry_group in
