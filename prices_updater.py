import yfinance as yf
import json
import os
import numpy as np
import urllib.request
import urllib.error
from datetime import datetime
import pytz
 
TIMEZONE = "America/Los_Angeles"
GIST_ID  = "011eb6e485727c90a1e0634861ff4357"
 
HOLDINGS = [
    {"ticker":"SPY",     "display":"SPY"},
    {"ticker":"QQQ",     "display":"QQQ"},
    {"ticker":"SOXX",    "display":"SOXX"},
    {"ticker":"AAPL",    "display":"AAPL"},
    {"ticker":"NVDA",    "display":"NVDA"},
    {"ticker":"MU",      "display":"MU"},
    {"ticker":"XLI",     "display":"XLI"},
    {"ticker":"XLV",     "display":"XLV"},
    {"ticker":"IAU",     "display":"IAU"},
    {"ticker":"KBWB",    "display":"KBWB"},
    {"ticker":"BTC-USD", "display":"BTC"},
]
 
MACRO_TICKERS = {
    "^VIX":     "VIX",
    "GC=F":     "GOLD",
    "CL=F":     "OIL",
    "^TNX":     "YIELD",
    "DX-Y.NYB": "USD",
}
 
AVG_COSTS = {
    "SPY":673.15,"QQQ":597.57,"SOXX":330.78,"AAPL":257.30,
    "NVDA":181.46,"MU":376.93,"XLI":169.10,"XLV":156.27,
    "IAU":93.76,"KBWB":80.14,"BTC":71896
}
 
def calc_levels(ticker, price, hist):
    try:
        if hist is None or len(hist) < 20:
            return {"s1":round(price*0.95,2),"s2":round(price*0.90,2),"r1":round(price*1.05,2),"r2":round(price*1.10,2)}
        closes = hist["Close"].dropna().values
        highs  = hist["High"].dropna().values if "High" in hist else closes
        lows   = hist["Low"].dropna().values  if "Low"  in hist else closes
        ma20  = float(np.mean(closes[-20:])) if len(closes)>=20 else price
        ma50  = float(np.mean(closes[-50:])) if len(closes)>=50 else price
        ma200 = float(np.mean(closes[-200:])) if len(closes)>=200 else price
        recent_lows  = sorted(lows[-30:])[:5]
        recent_highs = sorted(highs[-30:],reverse=True)[:5]
        avg_swing_low  = float(np.mean(recent_lows))
        avg_swing_high = float(np.mean(recent_highs))
        cands_s1 = [x for x in [avg_swing_low,ma50,ma20] if x < price*0.99]
        s1 = max(cands_s1) if cands_s1 else price*0.95
        cands_s2 = [x for x in [ma200,min(recent_lows)] if x < s1*0.99]
        s2 = max(cands_s2) if cands_s2 else s1*0.94
        cands_r1 = [x for x in [avg_swing_high,ma20*1.03] if x > price*1.01]
        r1 = min(cands_r1) if cands_r1 else price*1.05
        r2 = r1*1.05
        def clean(v,p):
            if p>50000: return round(v/500)*500
            if p>1000:  return round(v/50)*50
            if p>100:   return round(v/5)*5
            return round(v,1)
        return {"s1":clean(s1,price),"s2":clean(s2,price),"r1":clean(r1,price),"r2":clean(r2,price),
                "ma20":round(ma20,2),"ma50":round(ma50,2),"ma200":round(ma200,2)}
    except Exception as e:
        print(f"Level error {ticker}: {e}")
        return {"s1":round(price*0.95,2),"s2":round(price*0.90,2),"r1":round(price*1.05,2),"r2":round(price*1.10,2)}
 
def calc_rsi(closes, period=14):
    try:
        import pandas as pd
        s = pd.Series(closes)
        d = s.diff()
        g = d.clip(lower=0).rolling(period).mean()
        l = (-d.clip(upper=0)).rolling(period).mean()
        rs = g/l
        return round(float((100-(100/(1+rs))).iloc[-1]),1)
    except:
        return 50.0
 
def calc_score(prices, macro, levels):
    score = 0
    above_ma50 = sum(1 for t,p in prices.items()
                     if p.get("price") and levels.get(t,{}).get("ma50") and p["price"]>levels[t]["ma50"])
    score += round((above_ma50/max(len(prices),1))*30)
    spy_p    = prices.get("SPY",{}).get("price",0) or 0
    spy_ma50 = levels.get("SPY",{}).get("ma50",spy_p) or spy_p
    spy_ma200= levels.get("SPY",{}).get("ma200",spy_p) or spy_p
    if spy_p > spy_ma200: score += 10
    if spy_p > spy_ma50:  score += 10
    qqq_p  = prices.get("QQQ",{}).get("price",0) or 0
    soxx_p = prices.get("SOXX",{}).get("price",0) or 0
    if qqq_p  > (levels.get("QQQ",{}).get("ma50",qqq_p) or qqq_p):   score += 10
    if soxx_p > (levels.get("SOXX",{}).get("ma50",soxx_p) or soxx_p): score += 10
    vix = macro.get("VIX",20) or 20
    if vix<15:   score+=15
    elif vix<20: score+=10
    elif vix<25: score+=5
    score += 10
    return min(100, score)
 
def update_gist(content_str):
    token = os.environ.get("GISTTOKEN")
    if not token:
        print("⚠️  No GISTTOKEN found — skipping Gist update")
        return False
    payload = json.dumps({
        "files": {"prices.json": {"content": content_str}}
    }).encode("utf-8")
    req = urllib.request.Request(
        f"https://api.github.com/gists/{GIST_ID}",
        data=payload,
        method="PATCH",
        headers={
            "Authorization": f"token {token}",
            "Content-Type":  "application/json",
            "Accept":        "application/vnd.github.v3+json",
            "User-Agent":    "portfolio-bot"
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            print(f"✅ Gist updated — status {resp.status}")
            return True
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"❌ Gist HTTP error {e.code}: {body}")
        return False
    except Exception as e:
        print(f"❌ Gist error: {e}")
        return False
 
def main():
    la_tz = pytz.timezone(TIMEZONE)
    now   = datetime.now(la_tz)
    print(f"📡 Updating prices — {now.strftime('%I:%M %p PT')}")
 
    prices = {}
    levels = {}
    technicals = {}
 
    for h in HOLDINGS:
        t = h["ticker"]
        d = h["display"]
        try:
            stock = yf.Ticker(t)
            hist  = stock.history(period="1y", interval="1d")
            if hist.empty:
                print(f"  {d}: No data")
                continue
            closes  = hist["Close"].dropna()
            current = round(float(closes.iloc[-1]),2)
            prev    = round(float(closes.iloc[-2]),2) if len(closes)>1 else current
            chg     = round(((current-prev)/prev)*100,2) if prev else 0
            prices[d] = {"price":current,"prev":prev,"change":chg}
            levels[d] = calc_levels(d, current, hist)
            rsi   = calc_rsi(closes.values)
            ma50  = levels[d].get("ma50",current)
            ma200 = levels[d].get("ma200",current)
            trend = "UPTREND" if current>ma50>ma200 else "DOWNTREND" if current<ma50<ma200 else "SIDEWAYS"
            technicals[d] = {"rsi":rsi,"trend":trend,"ma50":ma50,"ma200":ma200}
            print(f"  {d}: ${current} ({chg:+.2f}%) — {trend}")
        except Exception as e:
            print(f"  {d}: Error — {e}")
 
    macro = {}
    try:
        tickers = list(MACRO_TICKERS.keys())
        data = yf.download(tickers, period="2d", interval="1d", progress=False, auto_adjust=True)
        for ticker, name in MACRO_TICKERS.items():
            try:
                series = data["Close"][ticker].dropna()
                val = round(float(series.iloc[-1]),2)
                prv = round(float(series.iloc[-2]),2) if len(series)>1 else val
                macro[name]         = val
                macro[name+"_CHG"]  = round(((val-prv)/prv)*100,2) if prv else 0
            except:
                pass
        print(f"  Macro: VIX={macro.get('VIX','?')} OIL={macro.get('OIL','?')} GOLD={macro.get('GOLD','?')}")
    except Exception as e:
        print(f"Macro error: {e}")
 
    score = calc_score(prices, macro, levels)
    print(f"🧠 Market Score: {score}/100")
 
    output = {
        "updated":    now.isoformat(),
        "score":      score,
        "prices":     prices,
        "macro":      macro,
        "levels":     levels,
        "technicals": technicals,
        "avg_costs":  AVG_COSTS,
    }
 
    content_str = json.dumps(output, indent=2)
 
    # Save locally (for repo commit)
    with open("prices.json","w") as f:
        f.write(content_str)
    print("✅ prices.json saved locally")
 
    # Push to public Gist
    print(f"📤 Pushing to Gist {GIST_ID}...")
    update_gist(content_str)
 
if __name__ == "__main__":
    main()
