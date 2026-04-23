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
TT_USERNAME      = os.environ["TT_SANDBOX_USERNAME"]
TT_PASSWORD      = os.environ["TT_SANDBOX_PASSWORD"]
TT_ACCOUNT       = os.environ["TT_SANDBOX_ACCOUNT"]
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

# ─── TELEGRAM FUNCTIONS ───────────────────────────────────────────────────────
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
                        {
                            "text": "✅ EXECUTE TRADE",
                            "callback_data": f"execute_{setup_index}"
                        },
                        {
                            "text": "❌ SKIP",
                            "callback_data": f"skip_{setup_index}"
                        }
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
        r = requests.get(
            f"{TELEGRAM_API}/getUpdates",
            params=params,
            timeout=35
        )
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
    """Wait for user to tap EXECUTE or SKIP. Returns 'execute' or 'skip'."""
    print(f"  Waiting up to {timeout_seconds}s for response on setup {setup_index}...")
    start_time = time.time()
    offset     = None

    # Clear old updates first
    old_updates = telegram_get_updates()
    if old_updates:
        offset = old_updates[-1]["update_id"] + 1

    while time.time() - start_time < timeout_seconds:
        updates = telegram_get_updates(offset)
        for update in updates:
            offset = update["update_id"] + 1
            cb = update.get("callback_query", {})
            data = cb.get("data", "")
            cb_id = cb.get("id")

            if data == f"execute_{setup_index}":
                telegram_answer_callback(cb_id, "✅ Executing trade...")
                return "execute"
            elif data == f"skip_{setup_index}":
                telegram_answer_callback(cb_id, "❌ Trade skipped.")
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

def tt_headers(token):
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
    if nearest == 0:   return "FED TODAY",             "RED"
    elif nearest == 1: return "FED TOMORROW",           "RED"
    elif nearest <= 3: return f"FED IN {nearest} DAYS", "YELLOW"
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
    else:             return score, "—",  "NO EDGE"

# ─── OPTIONS CHAIN ────────────────────────────────────────────────────────────
def get_option_chain(token, ticker):
    try:
        r = requests.get(
            f"{SANDBOX_URL}/option-chains/{ticker}/nested",
            headers=tt_headers(token)
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
    for expiry_group in chain:
        exp_str = expiry_group.get("expiration-date", "")
        try:
            exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()
            dte = (exp_date - today).days
            if min_dte <= dte <= max_dte and dte < best_dte:
                best_dte = dte
                best     = expiry_group
        except:
            continue
    return best, best_dte

def find_strike_by_delta(strikes, target_min, target_max, option_type="C"):
    candidates = []
    for strike in strikes:
        for opt in strike.get("options", []):
            if opt.get("option-type") != option_type:
                continue
            greeks = opt.get("greeks", {})
            delta  = greeks.get("delta")
            if delta is None:
                continue
            delta = abs(float(delta))
            if target_min <= delta <= target_max:
                candidates.append({
                    "strike":      float(strike.get("strike-price", 0)),
                    "delta":       round(delta, 3),
                    "gamma":       round(abs(float(greeks.get("gamma", 0))), 4),
                    "theta":       round(float(greeks.get("theta", 0)), 4),
                    "iv":          round(float(greeks.get("volatility", 0)) * 100, 1),
                    "option_type": option_type,
                    "symbol":      opt.get("symbol", ""),
                })
    if not candidates:
        return None
    target_mid = (target_min + target_max) / 2
    return min(candidates, key=lambda x: abs(x["delta"] - target_mid))

# ─── GREEK FILTER ─────────────────────────────────────────────────────────────
def greek_filter(delta, gamma, theta, dte, stype):
    flags  = []
    passed = True
    if stype == "debit":
        if not (0.40 <= delta <= 0.65): flags.append(f"Delta {delta}"); passed = False
        if gamma > 0.06:                flags.append(f"Gamma {gamma}"); passed = False
        if theta < -0.09:               flags.append(f"Theta {theta}"); passed = False
        if not (30 <= dte <= 90):       flags.append(f"DTE {dte}");     passed = False
    elif stype == "credit":
        if not (0.15 <= delta <= 0.30): flags.append(f"Delta {delta}"); passed = False
        if gamma > 0.05:                flags.append(f"Gamma {gamma}"); passed = False
        if theta < 0.05:                flags.append(f"Theta {theta}"); passed = False
        if not (25 <= dte <= 50):       flags.append(f"DTE {dte}");     passed = False
    return passed, flags

# ─── SCORER ───────────────────────────────────────────────────────────────────
def score_setup(regime, ivr, delta, gamma, theta, dte, stype, vix, event_color):
    score = 0
    match = {
        "A": ["debit","credit"], "B": ["debit","credit"],
        "C": ["credit"], "D": ["credit"], "E": []
    }
    if stype in match.get(regime, []): score += 25
    else:                              score += 5
    if ivr is not None:
        if stype == "debit"  and ivr < 40:  score += 20
        elif stype == "debit"  and ivr < 60: score += 12
        elif stype == "credit" and ivr > 60: score += 20
        elif stype == "credit" and ivr > 40: score += 12
        else:                                score += 5
    if stype == "debit":
        if 0.45 <= delta <= 0.60:   score += 10
        elif 0.40 <= delta <= 0.65: score += 7
        if gamma <= 0.04:  score += 8
        elif gamma <= 0.06: score += 5
        if theta >= -0.05:  score += 7
        elif theta >= -0.08: score += 4
    else:
        if 0.18 <= delta <= 0.25:   score += 10
        elif 0.15 <= delta <= 0.30: score += 7
        if gamma <= 0.03:  score += 8
        elif gamma <= 0.05: score += 5
        if theta >= 0.08:  score += 7
        elif theta >= 0.05: score += 4
    if stype == "debit":
        if 45 <= dte <= 75:   score += 15
        elif 35 <= dte <= 90: score += 10
        else:                 score += 3
    else:
        if 30 <= dte <= 45:   score += 15
        elif 25 <= dte <= 50: score += 10
        else:                 score += 3
    if vix < 18:   score += 10
    elif vix < 22: score += 7
    elif vix < 28: score += 4
    if "GREEN"  in event_color: score += 5
    elif "YELLOW" in event_color: score += 2
    return min(score, 100)

def score_to_grade(score):
    if score >= 90:   return "A+", "STRONG RECOMMEND", "🟢"
    elif score >= 80: return "A",  "RECOMMEND", "🟢"
    elif score >= 70: return "A-", "RECOMMEND reduced size", "🟢"
    elif score >= 60: return "B+", "BORDERLINE", "🟡"
    elif score >= 50: return "B",  "GRAY ZONE", "🟡"
    else:             return "—",  "NO EDGE", "🔴"

# ─── STRATEGY BUILDERS ────────────────────────────────────────────────────────
def build_bull_call_spread(token, ticker, chain, regime, ivr, vix, event_color):
    exp_group, dte = find_best_expiration(chain, 35, 75)
    if not exp_group: return None
    strikes   = exp_group.get("strikes", [])
    long_leg  = find_strike_by_delta(strikes, 0.40, 0.65, "C")
    short_leg = find_strike_by_delta(strikes, 0.20, 0.35, "C")
    if not long_leg or not short_leg: return None
    if short_leg["strike"] <= long_leg["strike"]: return None
    passed, flags = greek_filter(long_leg["delta"], long_leg["gamma"],
                                 long_leg["theta"], dte, "debit")
    width = short_leg["strike"] - long_leg["strike"]
    score = score_setup(regime, ivr, long_leg["delta"], long_leg["gamma"],
                        long_leg["theta"], dte, "debit", vix, event_color)
    grade, desc, emoji = score_to_grade(score)
    if score < 50: return None
    return {
        "ticker": ticker, "strategy": "Bull Call Debit Spread",
        "type": "debit", "direction": "BULLISH",
        "long_strike": long_leg["strike"], "short_strike": short_leg["strike"],
        "long_symbol":  long_leg.get("symbol",""),
        "short_symbol": short_leg.get("symbol",""),
        "long_type": "C", "short_type": "C",
        "expiration": exp_group.get("expiration-date"), "dte": dte,
        "delta": long_leg["delta"], "gamma": long_leg["gamma"],
        "theta": long_leg["theta"], "iv": long_leg["iv"],
        "max_risk": round(width * 40, 0), "max_gain": round(width * 60, 0),
        "score": score, "grade": grade, "grade_desc": desc, "emoji": emoji,
        "greek_passed": passed, "greek_flags": flags,
        "ivr": ivr, "ivr_bias": "", "live_ready": round(width * 40, 0) <= 300,
    }

def build_put_credit_spread(token, ticker, chain, regime, ivr, vix, event_color):
    exp_group, dte = find_best_expiration(chain, 25, 50)
    if not exp_group: return None
    strikes   = exp_group.get("strikes", [])
    short_leg = find_strike_by_delta(strikes, 0.15, 0.30, "P")
    long_leg  = find_strike_by_delta(strikes, 0.05, 0.14, "P")
    if not long_leg or not short_leg: return None
    if long_leg["strike"] >= short_leg["strike"]: return None
    passed, flags = greek_filter(short_leg["delta"], short_leg["gamma"],
                                 short_leg["theta"], dte, "credit")
    width = short_leg["strike"] - long_leg["strike"]
    score = score_setup(regime, ivr, short_leg["delta"], short_leg["gamma"],
                        short_leg["theta"], dte, "credit", vix, event_color)
    grade, desc, emoji = score_to_grade(score)
    if score < 50: return None
    return {
        "ticker": ticker, "strategy": "Put Credit Spread",
        "type": "credit", "direction": "BULLISH-NEUTRAL",
        "long_strike": long_leg["strike"], "short_strike": short_leg["strike"],
        "long_symbol":  long_leg.get("symbol",""),
        "short_symbol": short_leg.get("symbol",""),
        "long_type": "P", "short_type": "P",
        "expiration": exp_group.get("expiration-date"), "dte": dte,
        "delta": short_leg["delta"], "gamma": short_leg["gamma"],
        "theta": short_leg["theta"], "iv": short_leg["iv"],
        "max_risk": round(width * 70, 0), "max_gain": round(width * 30, 0),
        "score": score, "grade": grade, "grade_desc": desc, "emoji": emoji,
        "greek_passed": passed, "greek_flags": flags,
        "ivr": ivr, "ivr_bias": "", "live_ready": round(width * 70, 0) <= 300,
    }

# ─── SCANNER ─────────────────────────────────────────────────────────────────
def scan_all_tickers(token, regime, vix, event_color):
    setups = []
    for ticker in WATCHLIST:
        print(f"  Scanning {ticker}...")
        chain = get_option_chain(token, ticker)
        if not chain:
            print(f"    No chain for {ticker}")
            continue
        ivr, ivr_bias = get_ivr_yahoo(ticker)
        if regime in ["A","B"]:
            s = build_bull_call_spread(token, ticker, chain,
                                       regime, ivr, vix, event_color)
            if s:
                s["ivr_bias"] = ivr_bias
                setups.append(s)
        s = build_put_credit_spread(token, ticker, chain,
                                    regime, ivr, vix, event_color)
        if s:
            s["ivr_bias"] = ivr_bias
            setups.append(s)
    setups.sort(key=lambda x: x["score"], reverse=True)
    return [s for s in setups if s["score"] >= 60]

# ─── ORDER EXECUTION ─────────────────────────────────────────────────────────
def place_spread_order(token, setup):
    """Place a 2-leg spread order on Tastytrade sandbox."""
    try:
        # Determine actions based on strategy type
        if setup["type"] == "debit":
            long_action  = "Buy to Open"
            short_action = "Sell to Open"
        else:
            long_action  = "Buy to Open"
            short_action = "Sell to Open"

        order_payload = {
            "time-in-force": "Day",
            "order-type":    "Limit",
            "price":         str(round(setup["max_risk"] / 100, 2)),
            "price-effect":  "Debit" if setup["type"] == "debit" else "Credit",
            "legs": [
                {
                    "instrument-type": "Equity Option",
                    "symbol":          setup["long_symbol"],
                    "quantity":        "1",
                    "action":          long_action,
                },
                {
                    "instrument-type": "Equity Option",
                    "symbol":          setup["short_symbol"],
                    "quantity":        "1",
                    "action":          short_action,
                }
            ]
        }

        r = requests.post(
            f"{SANDBOX_URL}/accounts/{TT_ACCOUNT}/orders",
            headers=tt_headers(token),
            json=order_payload
        )

        if r.status_code in [200, 201]:
            order_data = r.json().get("data", {})
            order_id   = order_data.get("order", {}).get("id", "N/A")
            return True, f"Order placed — ID: {order_id}"
        else:
            return False, f"Order failed: {r.status_code} — {r.text[:200]}"

    except Exception as e:
        return False, f"Order exception: {e}"

# ─── TRADE LOG ────────────────────────────────────────────────────────────────
def load_trade_log():
    if not os.path.exists(LOG_FILE):
        return []
    with open(LOG_FILE, "r") as f:
        return list(csv.DictReader(f))

def save_trade_log(trades):
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    with open(LOG_FILE, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=LOG_HEADERS)
        writer.writeheader()
        writer.writerows(trades)

def log_new_setups(setups, regime):
    trades    = load_trade_log()
    today_str = date.today().isoformat()
    existing  = {(t["date"], t["ticker"], t["strategy"]) for t in trades}
    for s in setups:
        key = (today_str, s["ticker"], s["strategy"])
        if key not in existing:
            trades.append({
                "date":       today_str,
                "ticker":     s["ticker"],
                "strategy":   s["strategy"],
                "strikes":    f"{s['long_strike']}/{s['short_strike']}",
                "expiration": s["expiration"],
                "dte":        s["dte"],
                "delta":      s["delta"],
                "gamma":      s["gamma"],
                "theta":      s["theta"],
                "ivr":        s.get("ivr","N/A"),
                "grade":      s["grade"],
                "score":      s["score"],
                "max_risk":   s["max_risk"],
                "max_gain":   s["max_gain"],
                "regime":     regime,
                "status":     "OPEN",
                "pl_result":  "",
                "notes":      "",
            })
            existing.add(key)
    save_trade_log(trades)
    return trades

def get_performance_summary(trades):
    closed = [t for t in trades if t["status"] in ["WIN","LOSS","SCRATCH"]]
    if not closed: return None
    total    = len(closed)
    wins     = len([t for t in closed if t["status"] == "WIN"])
    losses   = len([t for t in closed if t["status"] == "LOSS"])
    win_rate = round((wins / total) * 100, 1) if total > 0 else 0
    pl_vals  = []
    for t in closed:
        try: pl_vals.append(float(t["pl_result"]))
        except: pass
    a_plus      = [t for t in closed if t["grade"] == "A+"]
    a_plus_wins = len([t for t in a_plus if t["status"] == "WIN"])
    return {
        "total": total, "wins": wins, "losses": losses,
        "win_rate": win_rate, "total_pl": round(sum(pl_vals), 2),
        "a_plus_count": len(a_plus),
        "a_plus_rate": round((a_plus_wins/len(a_plus))*100,1) if a_plus else 0,
        "open_trades": len([t for t in trades if t["status"] == "OPEN"]),
    }

# ─── TELEGRAM ALERT SYSTEM ───────────────────────────────────────────────────
def build_telegram_message(i, total, s, regime, regime_label, vix, event_label):
    greek_ok = "✅ Greeks passed" if s["greek_passed"] \
               else f"⚠️ Flags: {', '.join(s['greek_flags'])}"
    live_tag = "✅ Live ready ($2k)" if s["live_ready"] else "📋 Paper only"

    return (
        f"<b>OPTIONS BOT — SETUP {i}/{total}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>{s['ticker']}</b>  {s['emoji']} <b>GRADE: {s['grade']} ({s['score']}/100)</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Strategy:   {s['strategy']}\n"
        f"Direction:  {s['direction']}\n"
        f"Strikes:    {s['long_strike']} / {s['short_strike']}\n"
        f"Expiry:     {s['expiration']} ({s['dte']} DTE)\n"
        f"\n"
        f"Delta: {s['delta']}  Gamma: {s['gamma']}\n"
        f"Theta: {s['theta']}  IV: {s['iv']}%\n"
        f"IVR:   {s.get('ivr','N/A')} — {s.get('ivr_bias','N/A')}\n"
        f"\n"
        f"Max Risk:  ${s['max_risk']} per contract\n"
        f"Max Gain:  ${s['max_gain']} per contract\n"
        f"\n"
        f"{greek_ok}\n"
        f"{live_tag}\n"
        f"\n"
        f"Regime {regime} — {regime_label}\n"
        f"VIX: {vix}  |  {event_label}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Tap your choice below 👇"
    )

def process_setups_with_confirmation(token, setups, regime, regime_label,
                                     vix, event_label):
    executed = []
    skipped  = []

    if not setups:
        telegram_send(
            "📊 <b>OPTIONS BOT — DAILY SCAN</b>\n\n"
            f"Regime {regime} — {regime_label}\n"
            f"VIX: {vix}  |  {event_label}\n\n"
            "❌ No setups passed the framework filters today.\n"
            "Framework says: NO-GO — wait for better environment."
        )
        return executed, skipped

    # Send opening summary
    telegram_send(
        f"📊 <b>OPTIONS BOT — DAILY SCAN</b>\n\n"
        f"Regime {regime} — {regime_label}\n"
        f"VIX: {vix}  |  {event_label}\n\n"
        f"✅ <b>{len(setups)} setup(s) found</b>\n"
        f"Sending each one now for your review...\n"
        f"You have <b>5 minutes per setup</b> to decide."
    )

    time.sleep(2)

    for i, setup in enumerate(setups[:5], 1):
        msg_text = build_telegram_message(
            i, min(len(setups), 5), setup,
            regime, regime_label, vix, event_label
        )

        print(f"  Sending setup {i} to Telegram...")
        telegram_send_buttons(msg_text, i)

        response = wait_for_response(i, timeout_seconds=300)

        if response == "execute":
            print(f"  User confirmed EXECUTE for setup {i} — {setup['ticker']}")
            telegram_send(f"⏳ Placing order for <b>{setup['ticker']}</b>...")

            success, result_msg = place_spread_order(token, setup)

            if success:
                telegram_send(
                    f"✅ <b>ORDER EXECUTED</b>\n"
                    f"{setup['ticker']} — {setup['strategy']}\n"
                    f"Strikes: {setup['long_strike']} / {setup['short_strike']}\n"
                    f"{result_msg}"
                )
                executed.append(setup)
            else:
                telegram_send(
                    f"⚠️ <b>ORDER FAILED</b>\n"
                    f"{setup['ticker']}\n"
                    f"{result_msg}\n"
                    f"Please check Tastytrade sandbox manually."
                )

        elif response == "skip":
            print(f"  User skipped setup {i} — {setup['ticker']}")
            telegram_send(f"⏭ Skipped <b>{setup['ticker']}</b>. Moving to next setup...")
            skipped.append(setup)

        else:  # timeout
            print(f"  Timeout on setup {i} — {setup['ticker']}")
            telegram_send(
                f"⏰ <b>Timeout</b> on {setup['ticker']}.\n"
                f"No response in 5 minutes — setup skipped."
            )
            skipped.append(setup)

        time.sleep(2)

    return executed, skipped

# ─── EMAIL SUMMARY ────────────────────────────────────────────────────────────
def send_summary_email(regime, regime_label, data, event_label,
                       setups, executed, skipped, perf, today_str,
                       day_grade, day_score):
    exec_lines = ""
    for s in executed:
        exec_lines += f"  ✅ {s['ticker']} — {s['strategy']} | Grade {s['grade']}\n"
    skip_lines = ""
    for s in skipped:
        skip_lines += f"  ⏭ {s['ticker']} — {s['strategy']} | Grade {s['grade']}\n"

    if perf:
        pl_e = "🟢" if perf["total_pl"] >= 0 else "🔴"
        perf_sec = (
            f"Record:      {perf['wins']}W / {perf['losses']}L "
            f"({perf['win_rate']}% win rate)\n"
            f"Total P/L:   {pl_e} ${perf['total_pl']:+.2f}\n"
            f"Open trades: {perf['open_trades']}\n"
            f"A+ accuracy: {perf['a_plus_rate']}%"
        )
    else:
        perf_sec = "No closed trades yet — tracking starts today."

    body = f"""
╔══════════════════════════════════════════╗
   OPTIONS BOT — DAILY SUMMARY
   {today_str}
╚══════════════════════════════════════════╝

REGIME {regime} — {regime_label}
SPY: ${data['spy_price']} ({data['spy_chg_pct']:+.2f}%)
VIX: {data['vix_price']} {data['vix_dir']}
Day Grade: {day_grade} ({day_score}/100)
Event: {event_label}

━━━ SETUPS FOUND: {len(setups)} ━━━━━━━━━━━━━━━━━
━━━ EXECUTED: {len(executed)} ━━━━━━━━━━━━━━━━━━━
{exec_lines if exec_lines else '  None executed today.'}
━━━ SKIPPED: {len(skipped)} ━━━━━━━━━━━━━━━━━━━━
{skip_lines if skip_lines else '  None skipped.'}
━━━ P/L TRACKER (Paper) ━━━━━━━━━━━━━━━━
{perf_sec}

━━━ RULES ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  1. Regime first   2. Greeks must pass
  3. Grade B+ min   4. Paper until 20+ trades
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Options Bot v1.0 | Phase 5 Active
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
    msg            = MIMEMultipart()
    msg["From"]    = EMAIL_FROM
    msg["To"]      = EMAIL_TO
    msg["Subject"] = (
        f"OPTIONS BOT | Regime {regime} {day_grade} | "
        f"{len(executed)} Executed | {date.today().strftime('%b %d')}"
    )
    msg.attach(MIMEText(body, "plain"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_FROM, EMAIL_PASS)
        server.send_message(msg)
    print("Summary email sent.")

# ─── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    today_str = datetime.now().strftime("%A, %B %d %Y — %I:%M %p PT")

    print("=== PHASE 1: REGIME ===")
    data                     = get_market_data()
    ivr_spy, _               = get_ivr_yahoo("SPY")
    event_label, event_color = check_event_risk()
    regime, regime_label     = classify_regime(data)
    day_score, day_grade, _  = calculate_grade(
        regime, ivr_spy, data["vix_price"],
        event_color, data["spy_chg_pct"]
    )
    print(f"Regime: {regime} — {regime_label}")
    print(f"Grade:  {day_grade} ({day_score}/100)")

    print("\n=== PHASE 3: SCANNER ===")
    token  = get_session_token()
    setups = scan_all_tickers(token, regime, data["vix_price"], event_color)
    print(f"Valid setups: {len(setups)}")

    print("\n=== PHASE 5: TELEGRAM CONFIRMATION ===")
    executed, skipped = process_setups_with_confirmation(
        token, setups, regime, regime_label,
        data["vix_price"], event_label
    )

    print(f"Executed: {len(executed)} | Skipped: {len(skipped)}")

    all_trades = log_new_setups(setups, regime)
    perf       = get_performance_summary(all_trades)

    send_summary_email(
        regime, regime_label, data, event_label,
        setups, executed, skipped, perf,
        today_str, day_grade, day_score
    )

    print("Done.")

if __name__ == "__main__":
    main()
