import os
import csv
import time
import math
import requests
import yfinance as yf
import smtplib
from datetime import datetime, date, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
 
# CONFIG
SANDBOX_URL      = "https://api.cert.tastyworks.com"
TT_USERNAME      = os.environ["TT_SANDBOX_USERNAME"]
TT_PASSWORD      = os.environ["TT_SANDBOX_PASSWORD"]
TT_ACCOUNT       = os.environ["TT_SANDBOX_ACCOUNT"]
EMAIL_TO         = os.environ["EMAIL_TO"]
EMAIL_FROM       = os.environ["EMAIL_FROM"]
EMAIL_PASS       = os.environ["EMAIL_PASSWORD"]
TELEGRAM_TOKEN   = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
 
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
 
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trade_log.csv")
LOG_HEADERS = [
    "date","ticker","strategy","strikes","expiration","dte",
    "delta","gamma","theta","ivr","grade","score",
    "max_risk","max_gain","regime","status","pl_result",
    "sandbox_executed","hypothetical_result","notes"
]
 
 
def telegram_send(text):
    try:
        requests.post(
            f"{TELEGRAM_API}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"},
            timeout=10
        )
    except Exception as e:
        print(f"Telegram error: {e}")
 
 
def telegram_send_buttons(text, trade_id):
    try:
        requests.post(
            f"{TELEGRAM_API}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text,
                "parse_mode": "HTML",
                "reply_markup": {
                    "inline_keyboard": [[
                        {"text": "YES - CLOSE NOW", "callback_data": f"close_{trade_id}"},
                        {"text": "NO - HOLD",       "callback_data": f"hold_{trade_id}"}
                    ]]
                }
            },
            timeout=10
        )
    except Exception as e:
        print(f"Telegram button error: {e}")
 
 
def telegram_get_updates(offset=None):
    try:
        params = {"timeout": 10, "allowed_updates": ["callback_query"]}
        if offset:
            params["offset"] = offset
        r = requests.get(f"{TELEGRAM_API}/getUpdates", params=params, timeout=15)
        return r.json().get("result", [])
    except:
        return []
 
 
def wait_for_close_response(trade_id, timeout_seconds=120):
    start  = time.time()
    offset = None
    old    = telegram_get_updates()
    if old:
        offset = old[-1]["update_id"] + 1
    while time.time() - start < timeout_seconds:
        updates = telegram_get_updates(offset)
        for update in updates:
            offset = update["update_id"] + 1
            cb     = update.get("callback_query", {})
            data   = cb.get("data", "")
            cb_id  = cb.get("id")
            if data == f"close_{trade_id}":
                requests.post(f"{TELEGRAM_API}/answerCallbackQuery",
                    json={"callback_query_id": cb_id, "text": "Closing..."}, timeout=5)
                return "close"
            elif data == f"hold_{trade_id}":
                requests.post(f"{TELEGRAM_API}/answerCallbackQuery",
                    json={"callback_query_id": cb_id, "text": "Holding."}, timeout=5)
                return "hold"
        time.sleep(3)
    return "timeout"
 
 
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
 
 
def get_sandbox_positions(token):
    try:
        r = requests.get(
            f"{SANDBOX_URL}/accounts/{TT_ACCOUNT}/positions",
            headers=tt_headers(token)
        )
        if r.status_code != 200:
            return []
        return r.json().get("data", {}).get("items", [])
    except Exception as e:
        print(f"Position fetch error: {e}")
        return []
 
 
def close_sandbox_position(token, ticker, strategy_type):
    try:
        positions = get_sandbox_positions(token)
        legs      = []
        for pos in positions:
            sym = pos.get("symbol", "")
            if ticker.strip() in sym:
                qty       = int(pos.get("quantity", 0))
                direction = pos.get("quantity-direction", "Long")
                action    = "Sell to Close" if direction == "Long" else "Buy to Close"
                legs.append({
                    "instrument-type": "Equity Option",
                    "symbol":          sym,
                    "quantity":        str(qty),
                    "action":          action
                })
        if not legs:
            return False, "No matching positions in sandbox"
        effect = "Credit" if strategy_type == "debit" else "Debit"
        r = requests.post(
            f"{SANDBOX_URL}/accounts/{TT_ACCOUNT}/orders",
            headers=tt_headers(token),
            json={
                "time-in-force": "Day",
                "order-type":    "Market",
                "price-effect":  effect,
                "legs":          legs
            }
        )
        if r.status_code in [200, 201]:
            order_id = r.json().get("data", {}).get("order", {}).get("id", "N/A")
            return True, f"Close order placed - ID: {order_id}"
        else:
            return False, f"Close failed: {r.status_code} - {r.text[:200]}"
    except Exception as e:
        return False, f"Close exception: {e}"
 
 
def calculate_greeks(stock_price, strike, t_years, iv, option_type):
    try:
        if t_years <= 0 or iv <= 0 or stock_price <= 0:
            return 0.5, 0.02, -0.03
        S   = stock_price
        K   = strike
        r   = 0.05
        sig = iv
        d1  = (math.log(S / K) + (r + 0.5 * sig**2) * t_years) / (sig * math.sqrt(t_years))
 
        def norm_cdf(x):
            return (1.0 + math.erf(x / math.sqrt(2.0))) / 2.0
 
        def norm_pdf(x):
            return math.exp(-0.5 * x**2) / math.sqrt(2 * math.pi)
 
        delta = norm_cdf(d1) if option_type == "C" else norm_cdf(d1) - 1
        gamma = norm_pdf(d1) / (S * sig * math.sqrt(t_years))
        theta = (-(S * norm_pdf(d1) * sig) / (2 * math.sqrt(t_years))) / 365
        return round(abs(delta), 3), round(gamma, 4), round(theta, 4)
    except:
        return 0.5, 0.02, -0.03
 
 
def get_current_spread_value(trade):
    try:
        ticker     = trade["ticker"]
        strikes    = trade["strikes"]
        expiration = trade["expiration"]
        strategy   = trade["strategy"]
 
        long_strike, short_strike = [float(x) for x in strikes.split("/")]
        t    = yf.Ticker(ticker)
        hist = t.history(period="2d")
        if hist.empty:
            return None, None
        stock_price = float(hist["Close"].iloc[-1])
 
        chain    = t.option_chain(expiration)
        today    = date.today()
        exp_date = datetime.strptime(expiration, "%Y-%m-%d").date()
        dte      = max((exp_date - today).days, 1)
        t_years  = dte / 365
 
        if "Call" in strategy:
            calls     = chain.calls
            long_row  = calls[calls["strike"] == long_strike]
            short_row = calls[calls["strike"] == short_strike]
            if long_row.empty or short_row.empty:
                return None, stock_price
            long_price  = float(long_row.iloc[0].get("lastPrice", 0))
            short_price = float(short_row.iloc[0].get("lastPrice", 0))
            spread_value = long_price - short_price
        else:
            puts      = chain.puts
            long_row  = puts[puts["strike"] == long_strike]
            short_row = puts[puts["strike"] == short_strike]
            if long_row.empty or short_row.empty:
                return None, stock_price
            long_price  = float(long_row.iloc[0].get("lastPrice", 0))
            short_price = float(short_row.iloc[0].get("lastPrice", 0))
            spread_value = short_price - long_price
 
        return round(spread_value * 100, 2), stock_price
    except Exception as e:
        print(f"  Spread value error for {trade['ticker']}: {e}")
        return None, None
 
 
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
 
 
def get_open_trades():
    return [t for t in load_trade_log() if t.get("status", "") == "OPEN"]
 
 
def is_market_hours():
    now = datetime.utcnow()
    if now.weekday() >= 5:
        return False
    market_open  = now.replace(hour=14, minute=30, second=0)
    market_close = now.replace(hour=21, minute=0,  second=0)
    return market_open <= now <= market_close
 
 
def get_current_regime():
    try:
        spy      = yf.Ticker("SPY")
        vix      = yf.Ticker("^VIX")
        spy_hist = spy.history(period="60d")
        vix_hist = vix.history(period="5d")
        spy_close = spy_hist["Close"]
        spy_price = float(spy_close.iloc[-1])
        spy_ma20  = float(spy_close.rolling(20).mean().iloc[-1])
        spy_ma50  = float(spy_close.rolling(50).mean().iloc[-1])
        vix_price = float(vix_hist["Close"].iloc[-1])
        vix_prev  = float(vix_hist["Close"].iloc[-2])
        vix_dir   = "RISING" if vix_price > vix_prev else "FALLING"
        spy_chg   = abs((spy_price - float(spy_close.iloc[-2])) / float(spy_close.iloc[-2]) * 100)
 
        if vix_price > 28 or (vix_price > 22 and spy_chg > 2.0):
            return "D", vix_price
        if spy_price > spy_ma20 and spy_price > spy_ma50 and vix_dir == "FALLING" and vix_price < 20:
            return "A", vix_price
        if spy_price < spy_ma20 and spy_price < spy_ma50 and vix_dir == "RISING":
            return "B", vix_price
        return "C", vix_price
    except:
        return "C", 20.0
 
 
def monitor_positions(token):
    open_trades = get_open_trades()
    if not open_trades:
        print("  No open trades to monitor.")
        return []
 
    print(f"  Monitoring {len(open_trades)} open trade(s)...")
    current_regime, current_vix = get_current_regime()
    all_trades   = load_trade_log()
    updates_made = False
    alerts_sent  = []
 
    for trade in open_trades:
        ticker       = trade["ticker"]
        strategy     = trade["strategy"]
        max_risk     = float(trade.get("max_risk", 0))
        max_gain     = float(trade.get("max_gain", 0))
        entry_regime = trade.get("regime", "A")
        sandbox_exec = trade.get("sandbox_executed", "NO")
        trade_id     = f"{trade['date']}_{ticker}_{strategy[:4]}"
 
        print(f"  Checking {ticker} - {strategy}...")
        current_value, stock_price = get_current_spread_value(trade)
 
        if current_value is None:
            print(f"    Could not get current value for {ticker}")
            continue
 
        # Calculate P/L based on strategy type
        if "Credit" in strategy:
            entry_credit = max_gain / 100
            current_pl   = round((entry_credit - current_value / 100) * 100, 2)
        else:
            entry_debit  = max_risk / 100
            current_pl   = round((current_value / 100 - entry_debit) * 100, 2)
 
        pct_of_max = round((current_pl / max_gain) * 100, 1) if max_gain > 0 else 0
        pl_str     = f"+${current_pl}" if current_pl >= 0 else f"-${abs(current_pl)}"
        exp_date   = datetime.strptime(trade["expiration"], "%Y-%m-%d").date()
        dte_left   = (exp_date - date.today()).days
 
        print(f"    {ticker}: P/L={pl_str} ({pct_of_max}% of max) | {dte_left} DTE left | Stock: ${stock_price}")
 
        alert_msg     = None
        action_needed = False
 
        # TAKE PROFIT
        if pct_of_max >= 70:
            action_needed = True
            alert_msg = (
                f"TAKE PROFIT ALERT\n"
                f"{ticker} - {strategy}\n"
                f"Strikes: {trade['strikes']}\n"
                f"P/L: {pl_str} ({pct_of_max}% of max gain)\n"
                f"Stock: ${stock_price}\n"
                f"DTE remaining: {dte_left}\n\n"
                f"Framework target is 50-70% of max.\n"
                f"You are there. Close now?"
            )
        elif pct_of_max >= 50:
            alert_msg = (
                f"PROFIT ZONE REACHED\n"
                f"{ticker} - {strategy}\n"
                f"P/L: {pl_str} ({pct_of_max}% of max gain)\n"
                f"DTE remaining: {dte_left}\n\n"
                f"In the take profit zone (50-70%).\n"
                f"Monitor closely."
            )
 
        # LOSS WARNING
        elif pct_of_max <= -60:
            action_needed = True
            alert_msg = (
                f"EMERGENCY CUT\n"
                f"{ticker} - {strategy}\n"
                f"Strikes: {trade['strikes']}\n"
                f"P/L: {pl_str} ({pct_of_max}% — MAX LOSS)\n"
                f"Stock: ${stock_price}\n"
                f"DTE remaining: {dte_left}\n\n"
                f"Past 60% of max loss.\n"
                f"Framework says CLOSE. Close now?"
            )
        elif pct_of_max <= -40:
            alert_msg = (
                f"LOSS WARNING\n"
                f"{ticker} - {strategy}\n"
                f"P/L: {pl_str} ({pct_of_max}% of max)\n"
                f"DTE remaining: {dte_left}\n\n"
                f"Approaching max loss. Review thesis."
            )
 
        # REGIME CHANGE
        if current_regime == "D" and entry_regime in ["A","B","C"]:
            regime_warning = (
                f"\n\nREGIME CHANGE WARNING\n"
                f"Entry regime: {entry_regime}\n"
                f"Current regime: D - HIGH VOLATILITY\n"
                f"VIX: {current_vix}\n"
                f"Framework says reduce exposure."
            )
            alert_msg = (alert_msg or "") + regime_warning
            action_needed = True
 
        # DTE WARNING
        if 0 < dte_left <= 7:
            dte_warning = (
                f"\n\nDTE WARNING\n"
                f"{dte_left} days to expiration.\n"
                f"Gamma risk accelerating.\n"
                f"Close or roll before expiration."
            )
            alert_msg = (alert_msg or "") + dte_warning
            action_needed = True
 
        # SEND ALERT AND HANDLE RESPONSE
        if alert_msg:
            alerts_sent.append(f"{ticker}: {pct_of_max}% of max")
            print(f"    Alert: {ticker} at {pct_of_max}%")
 
            if action_needed:
                telegram_send_buttons(alert_msg, trade_id)
                response = wait_for_close_response(trade_id, timeout_seconds=120)
 
                if response == "close":
                    if sandbox_exec == "YES" and token:
                        stype   = "debit" if "Call" in strategy else "credit"
                        success, result = close_sandbox_position(token, ticker, stype)
                        if success:
                            telegram_send(
                                f"POSITION CLOSED\n"
                                f"{ticker} - {strategy}\n"
                                f"Final P/L: {pl_str}\n"
                                f"{result}"
                            )
                        else:
                            telegram_send(f"Close failed: {result}\nUpdate manually in trade_log.csv")
 
                    else:
                        telegram_send(
                            f"HYPOTHETICAL POSITION CLOSED\n"
                            f"{ticker} - {strategy}\n"
                            f"Hypothetical P/L: {pl_str}\n"
                            f"Logged in trade_log.csv"
                        )
 
                    for t in all_trades:
                        if (t["ticker"] == ticker and
                            t["strategy"] == strategy and
                            t["status"] == "OPEN"):
                            t["status"]              = "WIN" if current_pl >= 0 else "LOSS"
                            t["pl_result"]           = str(current_pl)
                            t["hypothetical_result"] = str(current_pl)
                            break
                    updates_made = True
 
                elif response == "hold":
                    telegram_send(f"Holding {ticker}. Monitoring continues.")
                else:
                    telegram_send(f"No response for {ticker} in 2 min. Holding.")
 
            else:
                telegram_send(alert_msg)
 
        # Always update hypothetical P/L for tracking
        for t in all_trades:
            if (t["ticker"] == ticker and
                t["strategy"] == strategy and
                t["status"] == "OPEN"):
                t["hypothetical_result"] = f"Current: {pl_str} ({pct_of_max}%)"
                updates_made = True
                break
 
    if updates_made:
        save_trade_log(all_trades)
        print("  Trade log updated.")
 
    return alerts_sent
 
 
def send_position_summary(token):
    open_trades = get_open_trades()
    if not open_trades:
        return
 
    lines    = []
    total_pl = 0.0
 
    for trade in open_trades:
        current_value, stock_price = get_current_spread_value(trade)
        max_risk = float(trade.get("max_risk", 0))
        max_gain = float(trade.get("max_gain", 0))
 
        if current_value is not None:
            if "Credit" in trade["strategy"]:
                pl = round((max_gain / 100 - current_value / 100) * 100, 2)
            else:
                pl = round((current_value / 100 - max_risk / 100) * 100, 2)
 
            pct    = round((pl / max_gain) * 100, 1) if max_gain > 0 else 0
            pl_str = f"+${pl}" if pl >= 0 else f"-${abs(pl)}"
            total_pl += pl
            tag     = "SANDBOX" if trade.get("sandbox_executed") == "YES" else "HYPOTHETICAL"
            exp_date = datetime.strptime(trade["expiration"], "%Y-%m-%d").date()
            dte_left = (exp_date - date.today()).days
            lines.append(f"{trade['ticker']} | {pl_str} ({pct}%) | {dte_left}DTE | {tag}")
        else:
            lines.append(f"{trade['ticker']} | Price unavailable")
 
    total_str = f"+${round(total_pl,2)}" if total_pl >= 0 else f"-${round(abs(total_pl),2)}"
 
    telegram_send(
        f"<b>POSITION MONITOR - UPDATE</b>\n"
        f"{datetime.now().strftime('%b %d %Y - %I:%M %p PT')}\n\n"
        f"Open positions: {len(open_trades)}\n\n" +
        "\n".join(lines) +
        f"\n\nTotal P/L: {total_str}"
    )
 
 
def main():
    print(f"=== PHASE 6: POSITION MONITOR ===")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}")
 
    if not is_market_hours():
        print("  Outside market hours. Skipping.")
        return
 
    open_trades = get_open_trades()
    if not open_trades:
        print("  No open trades.")
        telegram_send(
            f"<b>POSITION MONITOR</b>\n"
            f"No open trades to monitor.\n"
            f"All clear."
        )
        return
 
    try:
        token = get_session_token()
        print("  Sandbox authenticated.")
    except Exception as e:
        print(f"  Sandbox auth failed: {e}")
        token = None
 
    alerts = monitor_positions(token)
    send_position_summary(token)
 
    if not alerts:
        print("  All positions in normal range.")
    else:
        print(f"  Sent {len(alerts)} alert(s).")
 
    print("Done.")
 
 
if __name__ == "__main__":
    main()
