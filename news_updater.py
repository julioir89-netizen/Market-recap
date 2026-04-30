import yfinance as yf
import feedparser
import json
import os
import re
import requests
from datetime import datetime
import pytz
 
# ============================================================
# CONFIG
# ============================================================
TIMEZONE   = "America/Los_Angeles"
GIST_ID    = "011eb6e485727c90a1e0634861ff4357"
GIST_TOKEN = os.environ.get("GISTTOKEN")
 
PORTFOLIO_TICKERS = [
    {"t":"SPY",  "d":"SPY",  "role":"anchor"},
    {"t":"QQQ",  "d":"QQQ",  "role":"growth"},
    {"t":"SOXX", "d":"SOXX", "role":"growth"},
    {"t":"AAPL", "d":"AAPL", "role":"anchor"},
    {"t":"NVDA", "d":"NVDA", "role":"growth"},
    {"t":"MU",   "d":"MU",   "role":"risk"},
    {"t":"XLI",  "d":"XLI",  "role":"cyclical"},
    {"t":"XLV",  "d":"XLV",  "role":"defensive"},
    {"t":"IAU",  "d":"IAU",  "role":"hedge"},
    {"t":"KBWB", "d":"KBWB", "role":"cyclical"},
    {"t":"BTC-USD","d":"BTC","role":"risk"},
    {"t":"XLE",  "d":"XLE",  "role":"energy"},
    {"t":"COPX", "d":"COPX", "role":"commodity"},
]
 
TICKER_MAP = {h["t"]: h["d"] for h in PORTFOLIO_TICKERS}
TICKER_KEYWORDS = {
    "nvidia":["NVDA","SOXX"],"nvda":["NVDA","SOXX"],"semiconductor":["SOXX","NVDA","MU"],
    "micron":["MU"],"apple":["AAPL"],"aapl":["AAPL"],"s&p":["SPY"],"spy":["SPY"],
    "nasdaq":["QQQ"],"qqq":["QQQ"],"gold":["IAU"],"iau":["IAU"],"bank":["KBWB"],
    "energy":["XLE"],"oil":["XLE","IAU"],"copper":["COPX"],"bitcoin":["BTC"],
    "crypto":["BTC"],"fed":["SPY","QQQ"],"rate":["SPY","QQQ","KBWB"],
    "inflation":["IAU","XLE"],"nuclear":["XLV"],"health":["XLV"],
    "industrial":["XLI"],"infrastructure":["XLI"],"data center":["NVDA","SOXX"],
    "ai":["NVDA","QQQ","SOXX"],"hormuz":["XLE","IAU"],"iran":["XLE","IAU"],
    "trump":["SPY","QQQ"],"tariff":["SPY","QQQ"],"recession":["IAU","XLV"],
}
 
NEWS_FEEDS = [
    ("https://feeds.reuters.com/reuters/businessNews",     "Reuters",     "MACRO"),
    ("https://feeds.reuters.com/reuters/technologyNews",   "Reuters",     "TECH"),
    ("https://feeds.marketwatch.com/marketwatch/topstories/","MarketWatch","MARKET"),
    ("https://feeds.finance.yahoo.com/rss/2.0/headline?s=SPY,QQQ,NVDA,AAPL,MU,SOXX&region=US&lang=en-US",
                                                           "Yahoo Finance","EARNINGS"),
    ("https://feeds.reuters.com/reuters/energy",           "Reuters",     "ENERGY"),
]
 
# ============================================================
# HELPERS
# ============================================================
def classify_sentiment(text):
    t = text.lower()
    bullish_words = ["surge","rally","gain","rise","jump","beat","strong","record","bull","positive","up","grow","profit","win","soar"]
    bearish_words = ["drop","fall","decline","crash","miss","weak","concern","risk","down","loss","fear","sell","warning","cut"]
    b = sum(1 for w in bullish_words if w in t)
    be= sum(1 for w in bearish_words if w in t)
    if b>be+1: return "BULLISH"
    if be>b+1: return "BEARISH"
    return "NEUTRAL"
 
def classify_category(text):
    t = text.lower()
    if any(w in t for w in ["fed","fomc","rate","yield","inflation","cpi","pce","jerome powell","treasury"]): return "FED"
    if any(w in t for w in ["oil","energy","gas","hormuz","iran","opec","crude","barrel"]): return "ENERGY"
    if any(w in t for w in ["nvidia","semiconductor","chip","ai","data center","microsoft","google","meta","amazon"]): return "TECH"
    if any(w in t for w in ["earnings","revenue","profit","eps","guidance","forecast","beat","miss"]): return "EARNINGS"
    if any(w in t for w in ["trump","tariff","trade","policy","congress","election","white house"]): return "POLICY"
    if any(w in t for w in ["war","conflict","geopolitical","military","sanctions","ukraine","israel","iran","china"]): return "GEO"
    return "MACRO"
 
def classify_impact(text, category):
    t = text.lower()
    high_words = ["crash","crisis","emergency","collapse","surge","record","historic","major","critical"]
    if any(w in t for w in high_words): return "HIGH"
    if category in ["FED","ENERGY","GEO"]: return "MEDIUM"
    return "LOW"
 
def get_affected_tickers(text):
    t = text.lower()
    tickers = set()
    for keyword, affected in TICKER_KEYWORDS.items():
        if keyword in t:
            tickers.update(affected)
    return list(tickers)[:5]
 
def fetch_portfolio_news():
    items = []
    seen  = set()
    for ticker_info in PORTFOLIO_TICKERS[:8]:
        try:
            stock = yf.Ticker(ticker_info["t"])
            news  = stock.news or []
            for item in news[:2]:
                title = item.get("title","").strip()
                if not title or title in seen or len(title)<20: continue
                seen.add(title)
                category = classify_category(title)
                items.append({
                    "title":     title,
                    "source":    item.get("publisher","Yahoo Finance")[:25],
                    "url":       item.get("link",""),
                    "summary":   "",
                    "category":  category,
                    "sentiment": classify_sentiment(title),
                    "impact":    classify_impact(title, category),
                    "tickers":   get_affected_tickers(title) or [ticker_info["d"]],
                    "ts":        item.get("providerPublishTime", 0),
                })
        except Exception as e:
            print(f"  yfinance news {ticker_info['d']}: {e}")
    return items
 
def fetch_rss_news():
    items = []
    seen  = set()
    for url, source, default_cat in NEWS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:4]:
                title = entry.get("title","").strip()
                if not title or title in seen or len(title)<20: continue
                seen.add(title)
                summary = re.sub(r'<[^>]+>','', entry.get("summary",""))[:200].strip()
                category = classify_category(title+" "+summary) or default_cat
                items.append({
                    "title":     title,
                    "source":    source,
                    "url":       entry.get("link",""),
                    "summary":   summary,
                    "category":  category,
                    "sentiment": classify_sentiment(title+" "+summary),
                    "impact":    classify_impact(title+" "+summary, category),
                    "tickers":   get_affected_tickers(title+" "+summary),
                    "ts":        0,
                })
        except Exception as e:
            print(f"  RSS {source}: {e}")
    return items
 
def detect_key_risks(headlines):
    risks = []
    text  = " ".join(h["title"].lower() for h in headlines)
    if "recession" in text: risks.append("Recession signals in news — watch IAU and XLV as hedges")
    if "inflation" in text or "cpi" in text: risks.append("Inflation concerns — IAU and XLE benefit")
    if "rate" in text and "raise" in text: risks.append("Fed rate hike risk — pressure on QQQ/NVDA/SOXX")
    if "oil" in text or "energy" in text: risks.append("Energy volatility — XLE hedge positioned")
    if "tariff" in text or "trade" in text: risks.append("Tariff/trade policy — monitor SPY/QQQ impact")
    if "iran" in text or "hormuz" in text: risks.append("Hormuz disruption ongoing — energy supply risk")
    if "china" in text: risks.append("China/Taiwan geopolitical risk — SOXX chip exposure")
    if "bank" in text: risks.append("Banking sector stress — KBWB exposure to monitor")
    return risks[:5]
 
def detect_opportunities(headlines):
    opps = []
    text = " ".join(h["title"].lower() for h in headlines)
    if "ai" in text or "data center" in text: opps.append("AI data center expansion — NVDA, DTCR, URA beneficiaries")
    if "nuclear" in text: opps.append("Nuclear energy demand — URA/NLR positioned for this")
    if "copper" in text: opps.append("Copper demand rising — COPX supercycle thesis intact")
    if "gold" in text and ("rise" in text or "surge" in text): opps.append("Gold strength — IAU 100% historical WR zone active")
    if "earnings" in text and "beat" in text: opps.append("Earnings beats present — watch for S1 zone entries on pullbacks")
    return opps[:4]
 
# ============================================================
# FETCH MACRO DATA
# ============================================================
def fetch_macro_snapshot():
    macro = {}
    tickers = {"^VIX":"VIX","GC=F":"Gold","CL=F":"Oil","^TNX":"10Y Yield","DX-Y.NYB":"USD"}
    try:
        data = yf.download(list(tickers.keys()), period="1wk", interval="1d", progress=False, auto_adjust=True)
        for ticker, name in tickers.items():
            try:
                series = data["Close"][ticker].dropna()
                current = round(float(series.iloc[-1]),2)
                prev    = round(float(series.iloc[0]),2) if len(series)>1 else current
                chg     = round(((current-prev)/prev)*100,2) if prev else 0
                macro[name] = {"current":current,"week_chg":chg}
            except: pass
    except: pass
    return macro
 
# ============================================================
# UPDATE GIST
# ============================================================
def update_gist(news_payload):
    if not GIST_TOKEN:
        print("No GISTTOKEN — skipping Gist update")
        return
 
    # First read existing Gist content
    headers = {"Authorization":f"Bearer {GIST_TOKEN}","Accept":"application/vnd.github+json"}
    try:
        r = requests.get(f"https://api.github.com/gists/{GIST_ID}", headers=headers)
        existing = json.loads(r.json()["files"]["prices.json"]["content"])
    except:
        existing = {}
 
    # Merge news into existing
    existing["news"] = news_payload
 
    r = requests.patch(
        f"https://api.github.com/gists/{GIST_ID}",
        headers=headers,
        json={"files":{"prices.json":{"content":json.dumps(existing, indent=2)}}}
    )
    if r.status_code == 200:
        print("✅ Gist updated with news data")
    else:
        print(f"❌ Gist update failed: {r.status_code}")
 
# ============================================================
# MAIN
# ============================================================
if __name__ == "__main__":
    la_tz = pytz.timezone(TIMEZONE)
    now   = datetime.now(la_tz)
    print(f"📰 Running News Updater — {now.strftime('%B %d, %Y %I:%M %p PT')}")
 
    print("📡 Fetching portfolio news (yfinance)...")
    yf_news = fetch_portfolio_news()
    print(f"  Got {len(yf_news)} items from yfinance")
 
    print("📡 Fetching RSS news...")
    rss_news = fetch_rss_news()
    print(f"  Got {len(rss_news)} items from RSS")
 
    print("🌍 Fetching macro snapshot...")
    macro = fetch_macro_snapshot()
 
    # Combine, deduplicate, sort by impact
    all_news = yf_news + rss_news
    seen_titles = set()
    unique_news = []
    for item in all_news:
        key = item["title"][:50]
        if key not in seen_titles:
            seen_titles.add(key)
            unique_news.append(item)
 
    # Sort: HIGH impact first, then by category priority
    impact_order = {"HIGH":0,"MEDIUM":1,"LOW":2}
    unique_news.sort(key=lambda x: impact_order.get(x["impact"],2))
    top_news = unique_news[:15]
 
    key_risks   = detect_key_risks(top_news)
    opps        = detect_opportunities(top_news)
 
    # Build news payload
    news_payload = {
        "updated":    now.isoformat(),
        "date":       now.strftime("%B %d, %Y"),
        "headlines":  top_news,
        "key_risks":  key_risks,
        "opportunities": opps,
        "macro_snapshot": macro,
        "total_headlines": len(top_news),
    }
 
    print(f"✅ Assembled {len(top_news)} headlines · {len(key_risks)} risks · {len(opps)} opportunities")
 
    print("📤 Updating Gist...")
    update_gist(news_payload)
    print("✅ Done.")
