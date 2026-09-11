"""
QuantFlow Tech Agent — automatisiertes Paper-Trading-Dashboard.

Simuliertes ("Papier"-)Portfolio zu Test-/Beobachtungszwecken. Kein echtes
Geld, keine Anlageberatung, keine Garantie auf Richtigkeit der Kurs-, News-
oder Optionsdaten (kostenlose, teils verzögerte Quellen). Die Auswahl basiert
auf einfachen, transparenten Heuristiken (Kursmomentum, Abstand vom
52-Wochen-Hoch, Schlagzeilen-Keywords, Options-Volumen/Open-Interest) —
keine echte KI-Textanalyse und kein echter institutioneller Options-Flow.

Läuft alle 4 Stunden per GitHub Actions (siehe .github/workflows/run_agent.yml).
Zustand (Positionen, News-Cache, Score-Historie, Namens-Cache) wird in
JSON-Dateien zwischen den Läufen persistiert und vom Workflow zurückcommitet.

v6.0 Erweiterungen:
  - Score-Historie wird jetzt für ALLE bewerteten Kandidaten geführt (nicht
    nur gehaltene Positionen) UND korrekt gegen den Stand VOR diesem Lauf
    verglichen (vorher verglich sich der Score fälschlich mit sich selbst,
    daher zeigte fast alles nur "→")
  - Score wird jetzt überall angezeigt (Positionen, Watchlist, Musterdepot)
  - Kurstrend (▲▼▲) bricht nicht mehr um; klar von Score-Trend (↑/↓/→) getrennt
  - Eine einzige Gesamtübersichtstabelle (Hauptdepot + Watchlist + Musterdepot)
    mit Score, 4-Wochen-Werten, Kurstrend, Score-Trend und farblichen
    Segment-Badges, wer wo vertreten ist (inkl. Mehrfachzugehörigkeit)
    — engere Zeilenabstände
  - Kurze, aufklappbare Erklärung, was der Score bedeutet und was Quick Win
    vs. Long unterscheidet
  - News-Bereiche sind jetzt standardmäßig zugeklappt, mit "Alle auf/zu"-
    Schaltflächen
"""

import json
import os
import time
from datetime import datetime, timezone

import requests
import yfinance as yf

# ---------------------------------------------------------------------------
# KONFIGURATION
# ---------------------------------------------------------------------------

BASE_UNIVERSE = {
    "AAPL": "Core Tech", "MSFT": "Core Tech", "GOOGL": "Core Tech", "AMZN": "Core Tech", "META": "Core Tech",
    "NVDA": "Halbleiter", "AMD": "Halbleiter", "AVGO": "Halbleiter", "TSM": "Halbleiter",
    "MU": "Halbleiter", "QCOM": "Halbleiter", "INTC": "Halbleiter (Turnaround)",
    "ORCL": "Cloud Tech", "CRM": "Cloud Tech", "ADBE": "Cloud Tech", "NOW": "Cloud Tech", "SNOW": "Cloud Tech",
    "PANW": "Cyber Tech", "CRWD": "Cyber Tech", "FTNT": "Cyber Tech", "ZS": "Cyber Tech",
    "PYPL": "Fintech (Turnaround)", "SQ": "Fintech", "V": "Fintech", "MA": "Fintech",
    "TSLA": "Auto/EV", "NIO": "Auto/EV",
    "XLE": "Energie Hedge", "XOM": "Energie Hedge", "CVX": "Energie Hedge",
    "PFE": "Pharma (Value Hedge)", "MRNA": "Pharma",
    "DIS": "Turnaround/Media", "BA": "Turnaround/Industrie",
    "JPM": "Finanzwerte", "GS": "Finanzwerte",
}

NAME_MAP = {
    "AAPL": "Apple Inc.", "MSFT": "Microsoft Corp.", "GOOGL": "Alphabet Inc. (Google) Cl. A",
    "AMZN": "Amazon.com Inc.", "META": "Meta Platforms Inc.", "NVDA": "NVIDIA Corp.",
    "AMD": "Advanced Micro Devices Inc.", "AVGO": "Broadcom Inc.",
    "TSM": "Taiwan Semiconductor Manufacturing Co. (ADR)", "MU": "Micron Technology Inc.",
    "QCOM": "Qualcomm Inc.", "INTC": "Intel Corp.", "ORCL": "Oracle Corp.",
    "CRM": "Salesforce Inc.", "ADBE": "Adobe Inc.", "NOW": "ServiceNow Inc.", "SNOW": "Snowflake Inc.",
    "PANW": "Palo Alto Networks Inc.", "CRWD": "CrowdStrike Holdings Inc.", "FTNT": "Fortinet Inc.",
    "ZS": "Zscaler Inc.", "PYPL": "PayPal Holdings Inc.", "SQ": "Block Inc. (Square)",
    "V": "Visa Inc.", "MA": "Mastercard Inc.", "TSLA": "Tesla Inc.", "NIO": "NIO Inc. (ADR)",
    "XLE": "Energy Select Sector SPDR Fund (ETF)", "XOM": "Exxon Mobil Corp.", "CVX": "Chevron Corp.",
    "PFE": "Pfizer Inc.", "MRNA": "Moderna Inc.", "DIS": "The Walt Disney Company", "BA": "Boeing Co.",
    "JPM": "JPMorgan Chase & Co.", "GS": "Goldman Sachs Group Inc.",
    "PLTR": "Palantir Technologies Inc.", "SOFI": "SoFi Technologies Inc.", "SHOP": "Shopify Inc.",
    "NET": "Cloudflare Inc.", "COIN": "Coinbase Global Inc.",
    "^GSPC": "S&P 500 Index", "^IXIC": "Nasdaq Composite Index", "^DJI": "Dow Jones Industrial Average",
    "^VIX": "CBOE Volatilitätsindex (VIX)",
}

# "Musterdepot": eine zweite Beobachtungsliste, die nach denselben Maßstäben
# analysiert wird wie das simulierte Hauptdepot. Bewusst OHNE jegliche
# Beträge, Stückzahlen oder Kaufkurse — nur Ticker, Klarname und ggf. ein
# informativer Hinweis (z.B. Datenqualität). Kandidaten hieraus fließen auch
# regulär mit ins Scoring/Ranking des Hauptdepots ein.
MUSTERDEPOT = {
    "GOOGL": {"name": "Alphabet Inc. (Google) Cl. A"},
    "AMZN": {"name": "Amazon.com Inc."},
    "LYMS.DE": {"name": "Amundi Core Nasdaq-100 Swap UCITS ETF Acc", "note": "Ticker mit mittlerer Sicherheit zugeordnet"},
    "AAPL": {"name": "Apple Inc."},
    "ANET": {"name": "Arista Networks Inc."},
    "ASML": {"name": "ASML Holding N.V."},
    "BRK-B": {"name": "Berkshire Hathaway Inc. Cl. B"},
    "BESI.AS": {"name": "BE Semiconductor Industries N.V."},
    "BTCE.DE": {"name": "Bitwise Physical Bitcoin ETP"},
    "AVGO": {"name": "Broadcom Inc."},
    "CDNS": {"name": "Cadence Design Systems Inc."},
    "CAT": {"name": "Caterpillar Inc."},
    "FIX": {"name": "Comfort Systems USA Inc."},
    "CMI": {"name": "Cummins Inc."},
    "EME": {"name": "Emcor Group Inc."},
    "EVR.L": {"name": "Evraz PLC", "note": "Seit März 2022 vom Handel ausgesetzt (Sanktionen) — kein Live-Kurs verfügbar"},
    "GNRC": {"name": "Generac Holdings Inc."},
    "HONA": {"name": "Honeywell Aerospace", "note": "Erst seit Juni 2026 notiert — kurze Kurshistorie"},
    "HON": {"name": "Honeywell Technologies (vormals Honeywell International)"},
    "SXR8.DE": {"name": "iShares Core S&P 500 UCITS ETF (Acc)"},
    "SXRV.DE": {"name": "iShares NASDAQ 100 UCITS ETF (Acc)"},
    "JBL": {"name": "Jabil Inc."},
    "MRVL": {"name": "Marvell Technology Inc."},
    "META": {"name": "Meta Platforms Inc."},
    "MU": {"name": "Micron Technology Inc."},
    "MSFT": {"name": "Microsoft Corp."},
    "MRNA": {"name": "Moderna Inc."},
    "NVDA": {"name": "NVIDIA Corp."},
    "OCGN": {"name": "Ocugen Inc."},
    "PANW": {"name": "Palo Alto Networks Inc."},
    "PWR": {"name": "Quanta Services Inc."},
    "RKLB": {"name": "Rocket Lab USA Inc."},
    "SMSN.L": {"name": "Samsung Electronics Co. Ltd. (GDR)", "note": "GDR-Notierung, ggf. lückenhafte Datenqualität"},
    "S": {"name": "SentinelOne Inc."},
    "HY9H.F": {"name": "SK Hynix Inc. (GDR)", "note": "GDR-Notierung, ggf. lückenhafte Datenqualität"},
    "SNPS": {"name": "Synopsys Inc."},
    "TSM": {"name": "Taiwan Semiconductor Manufacturing Co. (ADR)"},
    "VUAA.DE": {"name": "Vanguard S&P 500 UCITS ETF (Acc)"},
    "VRT": {"name": "Vertiv Holdings Co."},
    "DG.PA": {"name": "VINCI S.A."},
    "WDC": {"name": "Western Digital Corp."},
}

TRENDING_SCREENER_IDS = ("day_gainers", "growth_technology_stocks", "most_actives")
TRENDING_COUNT_PER_SCREENER = 15

MACRO_TICKERS = ["^GSPC", "^IXIC", "^DJI", "^VIX"]

NUM_POSITIONS = 10
ALLOCATION_PER_POSITION = 5000.0  # EUR, fiktives Kapital pro Slot
KEST_RATE = 0.26
NEWS_RETENTION_DAYS = 7
NEWS_MAX_PER_TICKER = 15
NEWS_MAX_FETCH = 8
NUM_DISPOSE_CANDIDATES = 2
NUM_WATCHLIST = 10
SCORE_HISTORY_LENGTH = 10

W_DAY = 1.0
W_WEEK = 0.6
W_MONTH = 0.3
W_REBOUND = 0.15
W_NEWS = 1.5
W_OPTIONS = 2.0

STATE_FILE = "portfolio_state.json"
NEWS_CACHE_FILE = "news_cache.json"
MACRO_NEWS_CACHE_FILE = "macro_news_cache.json"
NAME_CACHE_FILE = "name_cache.json"
TRADE_LOG_FILE = "trade_log.csv"
PORTFOLIO_LOG_FILE = "portfolio_log.csv"
DASHBOARD_FILE = "dashboard.html"

POSITIVE_KEYWORDS = [
    "beat", "beats", "beating", "upgrade", "upgraded", "outperform", "raises", "raised",
    "record", "surge", "surges", "soar", "soars", "rally", "rallies", "strong demand",
    "buyback", "all-time high", "tops estimates", "bullish", "breakthrough", "profit jump",
    "guidance raise", "wins contract", "expands", "strong quarter",
]
NEGATIVE_KEYWORDS = [
    "miss", "misses", "missed", "downgrade", "downgraded", "cuts", "cut guidance",
    "lawsuit", "investigation", "recall", "plunge", "plunges", "slump", "slumps",
    "warns", "warning", "bearish", "layoffs", "fraud", "delay", "delays", "sell-off",
    "selloff", "underperform", "probe", "fine", "bankruptcy", "resigns",
]

TOPIC_KEYWORDS = [
    ("Politik/Makro", [
        "election", "president", "senate", "congress", "white house", "regulation",
        "tariff", "sanction", "fed ", "federal reserve", "interest rate", "rate hike",
        "rate cut", "inflation", "gdp", "central bank", "policy", "government shutdown",
        "treasury", "geopolit", "war", "ukraine", "trade deal", "eu ", "brexit",
    ]),
    ("Wirtschaft", [
        "earnings", "revenue", "profit", "ipo", "merger", "acquisition", "bankruptcy",
        "layoffs", "stock market", "dow jones", "s&p 500", "nasdaq", "recession",
        "unemployment", "jobs report", "consumer spending", "market rally", "market selloff",
        "guidance", "quarterly",
    ]),
    ("Technologie", [
        "ai ", " ai", "artificial intelligence", "chip", "semiconductor", "software",
        "cloud", "data center", "robot", "quantum", "cybersecurity", "app ", "smartphone",
        "electric vehicle", "autonomous", "startup",
    ]),
]
DEFAULT_TOPIC = "Sonstiges"
TOPIC_ORDER = ["Politik/Makro", "Wirtschaft", "Technologie", DEFAULT_TOPIC]

HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
}

SEGMENT_BADGES = {
    "Hauptdepot": ("segment-haupt", "🏆 Hauptdepot"),
    "Watchlist": ("segment-watch", "👀 Watchlist"),
    "Musterdepot": ("segment-muster", "🗂️ Musterdepot"),
}
SEGMENT_ORDER = ["Hauptdepot", "Watchlist", "Musterdepot"]


# ---------------------------------------------------------------------------
# HILFSFUNKTIONEN: JSON / CSV STATE
# ---------------------------------------------------------------------------

def load_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"⚠️ Konnte {path} nicht laden ({e}), starte mit Standardwert.")
        return default


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def fmt_eur(value, signed=False):
    fmt = f"{value:+,.2f} €" if signed else f"{value:,.2f} €"
    return fmt.replace(",", "X").replace(".", ",").replace("X", ".")


def pct_str(value):
    return f"{value:+.2f}%" if value is not None else "–"


def get_company_name(symbol, name_cache):
    """Klarname-Auflösung in drei Stufen: (1) statische Listen (schnell, kein
    API-Aufruf), (2) bereits einmal live aufgelöster Name aus dem Cache,
    (3) Live-Abruf über yfinance's .info (longName/shortName). Erst wenn alle
    drei nichts liefern, wird das Ticker-Kürzel selbst als Name verwendet."""
    if symbol in NAME_MAP:
        return NAME_MAP[symbol]
    if symbol in MUSTERDEPOT and MUSTERDEPOT[symbol].get("name"):
        return MUSTERDEPOT[symbol]["name"]
    if name_cache.get(symbol):
        return name_cache[symbol]
    try:
        info = yf.Ticker(symbol).info or {}
        long_name = info.get("longName") or info.get("shortName")
        if long_name:
            name_cache[symbol] = long_name
            return long_name
    except Exception as e:
        print(f"⚠️ Namens-Abruf für {symbol} fehlgeschlagen: {e}")
    return symbol


# ---------------------------------------------------------------------------
# DATENBESCHAFFUNG: KURSE, TRENDING, NEWS, OPTIONEN
# ---------------------------------------------------------------------------

def get_dynamic_trending():
    trending = set()
    for scr_id in TRENDING_SCREENER_IDS:
        try:
            url = "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved"
            params = {
                "formatted": "true", "lang": "en-US", "region": "US",
                "scrIds": scr_id, "count": TRENDING_COUNT_PER_SCREENER,
            }
            resp = requests.get(url, params=params, headers=HTTP_HEADERS, timeout=8)
            resp.raise_for_status()
            data = resp.json()
            quotes = data["finance"]["result"][0]["quotes"]
            for q in quotes:
                sym = q.get("symbol")
                if sym:
                    trending.add(sym)
        except Exception as e:
            print(f"⚠️ Trending-Abruf '{scr_id}' fehlgeschlagen (nutze nur Basisliste): {e}")
    return trending


def build_candidate_pool():
    pool = dict(BASE_UNIVERSE)
    for sym in get_dynamic_trending():
        if sym not in pool:
            pool[sym] = "Trend-Kandidat"
    for sym in MUSTERDEPOT:
        if sym not in pool:
            pool[sym] = "Musterdepot"
    return pool


def fetch_price_metrics(symbol):
    try:
        hist = yf.Ticker(symbol).history(period="1y")
        closes = hist["Close"].dropna()
        if len(closes) < 30:
            return None

        current_price = float(closes.iloc[-1])
        prev_price = float(closes.iloc[-2])
        day_perf = (current_price - prev_price) / prev_price * 100

        week_ref = float(closes.iloc[-6]) if len(closes) >= 6 else prev_price
        week_perf = (current_price - week_ref) / week_ref * 100 if week_ref else 0.0

        month_ref = float(closes.iloc[-22]) if len(closes) >= 22 else week_ref
        month_perf = (current_price - month_ref) / month_ref * 100 if month_ref else 0.0

        high_52w = float(closes.max())
        pct_below_high = (current_price - high_52w) / high_52w * 100 if high_52w else 0.0

        t_list = []
        for i in range(-3, 0):
            if closes.iloc[i] > closes.iloc[i - 1]:
                t_list.append("▲")
            else:
                t_list.append("▼")

        def week_block(n_back_start, n_back_end):
            if len(closes) <= n_back_start:
                return None
            a = float(closes.iloc[-1 - n_back_start])
            b = float(closes.iloc[-1 - n_back_end]) if n_back_end > 0 else current_price
            return (b - a) / a * 100 if a else None

        week1 = week_block(5, 0)
        week2 = week_block(10, 5)
        week3 = week_block(15, 10)
        week4 = week_block(20, 15)

        return {
            "symbol": symbol,
            "current_price": current_price,
            "day_perf": day_perf,
            "week_perf": week_perf,
            "month_perf": month_perf,
            "week1": week1, "week2": week2, "week3": week3, "week4": week4,
            "pct_below_high": pct_below_high,
            "tendency": " ".join(t_list),
            "tendency_class": "pos" if t_list[-1] == "▲" else "neg",
        }
    except Exception as e:
        print(f"⚠️ Kursdaten für {symbol} nicht verfügbar: {e}")
        return None


def parse_timestamp(value):
    if value is None:
        return None
    try:
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            v = value.replace("Z", "+00:00")
            return datetime.fromisoformat(v).timestamp()
    except Exception:
        return None
    return None


def fetch_news(symbol, max_items=NEWS_MAX_FETCH):
    articles = []
    try:
        raw_news = yf.Ticker(symbol).news or []
        for item in raw_news[:max_items]:
            content = item.get("content") if isinstance(item.get("content"), dict) else item

            title = content.get("title") or item.get("title")
            if not title:
                continue

            link = None
            cturl = content.get("clickThroughUrl")
            if isinstance(cturl, dict):
                link = cturl.get("url")
            if not link:
                canurl = content.get("canonicalUrl")
                if isinstance(canurl, dict):
                    link = canurl.get("url")
            if not link:
                link = item.get("link", "")

            publisher = ""
            provider = content.get("provider")
            if isinstance(provider, dict):
                publisher = provider.get("displayName", "")
            if not publisher:
                publisher = item.get("publisher", "")

            pub_raw = content.get("pubDate") or item.get("providerPublishTime")
            ts = parse_timestamp(pub_raw)
            if ts is None:
                ts = time.time()

            articles.append({
                "ticker": symbol, "title": title, "link": link or "",
                "publisher": publisher or "", "ts": ts,
            })
    except Exception as e:
        print(f"⚠️ News-Abruf für {symbol} fehlgeschlagen: {e}")
    return articles


def classify_headline(title):
    t = title.lower()
    pos = any(kw in t for kw in POSITIVE_KEYWORDS)
    neg = any(kw in t for kw in NEGATIVE_KEYWORDS)
    if pos and not neg:
        return "pos", "🟢"
    if neg and not pos:
        return "neg", "🔴"
    return "neutral", "⚪"


def classify_topic(title):
    t = title.lower()
    for topic, keywords in TOPIC_KEYWORDS:
        if any(kw in t for kw in keywords):
            return topic
    return DEFAULT_TOPIC


def score_sentiment(articles):
    score = 0
    for a in articles:
        cls, _ = classify_headline(a["title"])
        if cls == "pos":
            score += 1
        elif cls == "neg":
            score -= 1
    return max(-5, min(5, score))


def fetch_options_metrics(symbol):
    try:
        tk = yf.Ticker(symbol)
        expirations = tk.options
        if not expirations:
            return None
        nearest = expirations[0]
        chain = tk.option_chain(nearest)
        calls, puts = chain.calls, chain.puts

        call_vol = float(calls["volume"].fillna(0).sum()) if "volume" in calls else 0.0
        put_vol = float(puts["volume"].fillna(0).sum()) if "volume" in puts else 0.0
        pcr = (put_vol / call_vol) if call_vol > 0 else None

        call_wall = None
        if "openInterest" in calls and len(calls) > 0:
            oi = calls["openInterest"].fillna(0)
            if oi.max() > 0:
                call_wall = float(calls.loc[oi.idxmax(), "strike"])

        put_wall = None
        if "openInterest" in puts and len(puts) > 0:
            oi = puts["openInterest"].fillna(0)
            if oi.max() > 0:
                put_wall = float(puts.loc[oi.idxmax(), "strike"])

        bias = 0
        if pcr is not None:
            if pcr < 0.7:
                bias = 1
            elif pcr > 1.3:
                bias = -1

        return {
            "expiration": nearest, "put_call_ratio": pcr,
            "call_wall": call_wall, "put_wall": put_wall, "bias": bias,
        }
    except Exception as e:
        print(f"⚠️ Optionsdaten für {symbol} nicht verfügbar: {e}")
        return None


# ---------------------------------------------------------------------------
# SCORING, RANKING-EXTRAS & PORTFOLIO-REBALANCING
# ---------------------------------------------------------------------------

def compute_score(price_m, news_score, options_m):
    momentum_score = (
        W_DAY * price_m["day_perf"]
        + W_WEEK * price_m["week_perf"]
        + W_MONTH * price_m["month_perf"]
    )
    rebound_component = max(0.0, min(40.0, -price_m["pct_below_high"])) * W_REBOUND
    options_bias = options_m["bias"] if options_m else 0
    total = momentum_score + rebound_component + W_NEWS * news_score + W_OPTIONS * options_bias
    category = "Quick Win" if momentum_score >= rebound_component else "Long"
    return total, category


def score_arrow(symbol, new_score, score_history):
    """Vergleicht den aktuellen Score mit dem beim LETZTEN Lauf gespeicherten
    Score desselben Tickers (score_history muss der Stand VOR diesem Lauf
    sein — siehe run_agent_update, wo bewusst zwischen "alter" und "neuer"
    Score-Historie unterschieden wird, damit hier nicht der Score mit sich
    selbst verglichen wird). Bewusst KEINE numerische Kursprognose, nur eine
    Richtungsangabe."""
    history = score_history.get(symbol, [])
    if not history:
        return "–", None
    prev = history[-1]
    if new_score > prev + 0.05:
        return "↑", prev
    if new_score < prev - 0.05:
        return "↓", prev
    return "→", prev


def update_score_history(score_history, symbol, new_score):
    history = score_history.get(symbol, [])
    history = history + [round(new_score, 4)]
    score_history[symbol] = history[-SCORE_HISTORY_LENGTH:]
    return score_history


def rebalance(scored, state, price_lookup, timestamp):
    top = scored[:NUM_POSITIONS]
    top_symbols = {c["symbol"] for c in top}
    old_positions = state.get("positions", {})
    old_symbols = set(old_positions.keys())

    new_positions = {}
    events = []

    for c in top:
        sym = c["symbol"]
        if sym in old_positions:
            pos = dict(old_positions[sym])
            pos["category"] = c["category"]
            pos["type"] = c["type"]
            pos["last_score"] = c["score"]
            new_positions[sym] = pos
        else:
            entry_price = c["price_m"]["current_price"]
            shares = ALLOCATION_PER_POSITION / entry_price if entry_price else 0.0
            new_positions[sym] = {
                "entry_price": entry_price,
                "entry_date": timestamp,
                "shares": shares,
                "category": c["category"],
                "type": c["type"],
                "last_score": c["score"],
            }
            events.append({
                "aktion": "KAUF", "ticker": sym, "kategorie": c["category"],
                "preis": entry_price, "shares": shares, "realized_pnl": None,
                "grund": f"Neu in Top {NUM_POSITIONS} (Score {c['score']:.2f})",
            })

    dropped = old_symbols - top_symbols
    for sym in dropped:
        pos = old_positions[sym]
        exit_price = price_lookup[sym]["current_price"] if sym in price_lookup else pos["entry_price"]
        realized = (exit_price - pos["entry_price"]) * pos.get("shares", 0.0)
        events.append({
            "aktion": "VERKAUF", "ticker": sym, "kategorie": pos.get("category", ""),
            "preis": exit_price, "shares": pos.get("shares", 0.0), "realized_pnl": realized,
            "grund": "Aus Top 10 gefallen / durch besseren Kandidaten ersetzt",
        })

    by_score = sorted(new_positions.items(), key=lambda kv: kv[1]["last_score"])
    dispose_symbols = {sym for sym, _ in by_score[:NUM_DISPOSE_CANDIDATES]}
    for sym, pos in new_positions.items():
        pos["risk_flag"] = sym in dispose_symbols

    return new_positions, events


def build_watchlist(scored, held_symbols, limit=NUM_WATCHLIST):
    watchlist = [c for c in scored if c["symbol"] not in held_symbols]
    return watchlist[:limit]


def build_musterdepot_view(scored, cutoff_score):
    scored_by_symbol = {c["symbol"]: c for c in scored}
    rows = []
    for sym, meta in MUSTERDEPOT.items():
        c = scored_by_symbol.get(sym)
        if c is None:
            rows.append({
                "symbol": sym, "name": meta["name"], "note": meta.get("note", ""),
                "available": False, "qualifies": False, "entry": None,
            })
            continue
        qualifies = cutoff_score is not None and c["score"] >= cutoff_score
        rows.append({
            "symbol": sym, "name": meta["name"], "note": meta.get("note", ""),
            "available": True, "qualifies": qualifies, "entry": c,
        })
    return rows


def build_master_rows(positions, price_lookup, watchlist, musterdepot_rows, name_cache):
    """Konsolidiert Hauptdepot, Watchlist und Musterdepot zu EINER Zeilenliste
    pro Ticker (ein Ticker kann mehreren Segmenten gleichzeitig angehören,
    z.B. ein Musterdepot-Titel, der gerade auch im Hauptdepot gehalten wird)."""
    rows = {}

    for sym, pos in positions.items():
        pm = price_lookup.get(sym)
        r = rows.setdefault(sym, {
            "symbol": sym, "name": get_company_name(sym, name_cache),
            "category": pos.get("category", ""), "score": pos.get("last_score", 0.0),
            "price_m": pm, "segments": set(), "qualifies": False,
        })
        r["segments"].add("Hauptdepot")

    for c in watchlist:
        sym = c["symbol"]
        r = rows.setdefault(sym, {
            "symbol": sym, "name": get_company_name(sym, name_cache),
            "category": c["category"], "score": c["score"],
            "price_m": c["price_m"], "segments": set(), "qualifies": False,
        })
        r["segments"].add("Watchlist")

    for row in musterdepot_rows:
        if not row["available"]:
            continue
        sym = row["symbol"]
        c = row["entry"]
        r = rows.setdefault(sym, {
            "symbol": sym, "name": row["name"],
            "category": c["category"], "score": c["score"],
            "price_m": c["price_m"], "segments": set(), "qualifies": False,
        })
        r["segments"].add("Musterdepot")
        if row["qualifies"]:
            r["qualifies"] = True

    return sorted(rows.values(), key=lambda r: r["score"], reverse=True)


def update_cache_generic(cache, key, new_articles, now_ts, max_items=NEWS_MAX_PER_TICKER):
    existing = cache.get(key, [])
    combined = existing + new_articles
    seen = set()
    deduped = []
    for a in combined:
        dedupe_key = (a.get("title"), a.get("link"))
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        deduped.append(a)

    cutoff = now_ts - NEWS_RETENTION_DAYS * 86400
    filtered = [a for a in deduped if a.get("ts") and a["ts"] >= cutoff]
    filtered.sort(key=lambda a: a["ts"], reverse=True)
    cache[key] = filtered[:max_items]
    return cache


def update_news_cache(cache, symbol, new_articles, now_ts):
    return update_cache_generic(cache, symbol, new_articles, now_ts, NEWS_MAX_PER_TICKER)


def prune_cache_fully(cache, now_ts):
    cutoff = now_ts - NEWS_RETENTION_DAYS * 86400
    pruned = {}
    for key, articles in cache.items():
        fresh = [a for a in articles if a.get("ts") and a["ts"] >= cutoff]
        if fresh:
            pruned[key] = fresh
    return pruned


def build_macro_topic_overview(all_fetched_news, macro_cache, now_ts):
    buckets = {topic: [] for topic in TOPIC_ORDER}
    for article in all_fetched_news:
        topic = classify_topic(article["title"])
        buckets[topic].append(article)

    for topic in TOPIC_ORDER:
        macro_cache = update_cache_generic(macro_cache, topic, buckets[topic], now_ts, max_items=20)

    return macro_cache


def build_week_summary(price_lookup, positions):
    summary = {
        "netto_now": None, "netto_week_ago": None, "change_abs": None, "change_pct": None,
        "best": None, "worst": None,
    }

    if os.path.exists(PORTFOLIO_LOG_FILE):
        with open(PORTFOLIO_LOG_FILE, "r", encoding="utf-8") as f:
            rows = [line.split(",") for line in f.read().splitlines()[1:] if line.strip()]
        if rows:
            now_ts = time.time()
            target_ts = now_ts - 7 * 86400
            best_row = None
            best_diff = None
            for row in rows:
                if len(row) < 6:
                    continue
                try:
                    row_ts = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S UTC").replace(
                        tzinfo=timezone.utc).timestamp()
                except Exception:
                    continue
                diff = abs(row_ts - target_ts)
                if row_ts <= target_ts and (best_diff is None or diff < best_diff):
                    best_row, best_diff = row, diff
            if best_row:
                summary["netto_week_ago"] = float(best_row[5])
                summary["netto_now"] = float(rows[-1][5])
                summary["change_abs"] = summary["netto_now"] - summary["netto_week_ago"]
                if summary["netto_week_ago"]:
                    summary["change_pct"] = summary["change_abs"] / summary["netto_week_ago"] * 100

    movers = []
    for sym in positions:
        pm = price_lookup.get(sym)
        if pm and pm.get("week1") is not None:
            movers.append((sym, pm["week1"]))
    if movers:
        movers.sort(key=lambda x: x[1], reverse=True)
        summary["best"] = movers[0]
        summary["worst"] = movers[-1]

    return summary


# ---------------------------------------------------------------------------
# CSV LOGGING
# ---------------------------------------------------------------------------

def log_trades(events, timestamp):
    if not events:
        return
    is_new = not os.path.exists(TRADE_LOG_FILE)
    with open(TRADE_LOG_FILE, "a", encoding="utf-8") as f:
        if is_new:
            f.write("Zeitstempel,Aktion,Ticker,Kategorie,Preis,Shares,Realisierter_GewinnVerlust,Grund\n")
        for e in events:
            realized = "" if e["realized_pnl"] is None else f"{e['realized_pnl']:.2f}"
            grund = e["grund"].replace(",", ";")
            f.write(
                f"{timestamp},{e['aktion']},{e['ticker']},{e['kategorie']},"
                f"{e['preis']:.2f},{e['shares']:.4f},{realized},{grund}\n"
            )


def read_prev_snapshot():
    if not os.path.exists(PORTFOLIO_LOG_FILE):
        return None
    with open(PORTFOLIO_LOG_FILE, "r", encoding="utf-8") as f:
        lines = [line for line in f.read().splitlines() if line.strip()]
    if len(lines) <= 1:
        return None
    return lines[-1].split(",")


def log_snapshot(timestamp, total_brutto, total_unrealized, realized_total, kest, total_netto):
    is_new = not os.path.exists(PORTFOLIO_LOG_FILE)
    with open(PORTFOLIO_LOG_FILE, "a", encoding="utf-8") as f:
        if is_new:
            f.write(
                "Zeitstempel,Brutto_Wert,Unrealisierter_GewinnVerlust,"
                "Realisierter_GewinnVerlust_Kumuliert,Steuer_Rueckstellung,Netto_Wert\n"
            )
        f.write(
            f"{timestamp},{total_brutto:.2f},{total_unrealized:.2f},"
            f"{realized_total:.2f},{kest:.2f},{total_netto:.2f}\n"
        )


# ---------------------------------------------------------------------------
# HTML RENDERING
# ---------------------------------------------------------------------------

def relative_time(ts, now_ts):
    diff = max(0, now_ts - ts)
    hours = diff / 3600
    if hours < 1:
        return "vor <1 Std."
    if hours < 24:
        return f"vor {int(hours)} Std."
    return f"vor {int(hours / 24)} Tag(en)"


def render_news_html(symbol, news_cache, now_ts, max_items=5):
    articles = news_cache.get(symbol, [])[:max_items]
    if not articles:
        return '<div class="news-summary">Keine aktuellen Schlagzeilen im 7-Tage-Fenster gefunden.</div>'
    rows = []
    for a in articles:
        cls, icon = classify_headline(a["title"])
        rel = relative_time(a["ts"], now_ts)
        title_safe = a["title"].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        link = a.get("link") or "#"
        publisher = a.get("publisher") or ""
        rows.append(
            f'<div class="news-item sentiment-{cls}">'
            f'<div class="news-meta">{icon} {publisher} · {rel}</div>'
            f'<a class="news-title" href="{link}" target="_blank" rel="noopener">{title_safe}</a>'
            f'</div>'
        )
    return "\n".join(rows)


def render_week_table(pm):
    if not pm:
        return '<div class="news-summary">Keine Kursdaten verfügbar.</div>'
    cells = [
        ("W-4", pm.get("week4")), ("W-3", pm.get("week3")),
        ("W-2", pm.get("week2")), ("W-1", pm.get("week1")),
        ("Tag", pm.get("day_perf")),
    ]
    parts = []
    for label, val in cells:
        cls = "pos" if (val or 0) >= 0 else "neg"
        parts.append(f'<div class="week-cell"><span class="week-label">{label}</span>'
                      f'<span class="{cls}">{pct_str(val)}</span></div>')
    return '<div class="week-table">' + "".join(parts) + '</div>'


def render_card(symbol, name, category, sec_type, price_m, news_cache, score_history,
                 now_ts, mode="watchlist", pos=None, score=None, risk_flag=False,
                 qualifies=None, note=""):
    """Gemeinsamer Karten-Renderer für gehaltene Positionen, Watchlist und
    Musterdepot. Der Score wird IMMER angezeigt (unabhängig vom Modus)."""
    day_perf = price_m["day_perf"] if price_m else 0.0
    tendency = price_m["tendency"] if price_m else "–"
    tendency_class = price_m["tendency_class"] if price_m else "neutral"
    day_cls = "pos" if day_perf >= 0 else "neg"
    cat_cls = "buy" if category == "Quick Win" else ""

    if mode == "held" and pos is not None:
        score_value = pos.get("last_score", 0.0)
    else:
        score_value = score if score is not None else 0.0

    arrow, _prev = score_arrow(symbol, score_value, score_history)
    arrow_cls = {"↑": "pos", "↓": "neg", "→": "neutral", "–": "neutral"}[arrow]

    risk_badge = ""
    if risk_flag:
        risk_badge = '<span class="badge category-badge dispose">⚠️ Potential Dispose</span>'

    qualifies_badge = ""
    if qualifies is True:
        qualifies_badge = '<span class="badge category-badge qualifies">✅ Erfüllt Hauptdepot-Kriterium</span>'

    note_html = f'<div class="position-meta" style="font-style:italic;">Hinweis: {note}</div>' if note else ""

    value_html = ""
    if mode == "held" and pos and price_m:
        current_price = price_m["current_price"]
        gain = (current_price - pos["entry_price"]) * pos["shares"]
        value = current_price * pos["shares"]
        gain_cls = "pos" if gain >= 0 else "neg"
        value_html = (
            f'<div class="position-value"><div class="val">{fmt_eur(value)}</div>'
            f'<div class="val {gain_cls}" style="font-size:13px;">{fmt_eur(gain, signed=True)}</div></div>'
        )

    score_html = f'<span class="badge">Score {score_value:.2f}</span>'

    news_html = render_news_html(symbol, news_cache, now_ts)
    week_table = render_week_table(price_m)

    entry_meta = ""
    if mode == "held" and pos and price_m:
        entry_meta = (
            f'Einstieg: {pos.get("entry_date", "–")} @ {fmt_eur(pos["entry_price"])} · '
            f'Aktuell: {fmt_eur(price_m["current_price"])} · '
        )

    meta_line = (
        f'{entry_meta}Tag <span class="{day_cls}">{day_perf:+.2f}%</span> · '
        f'Kurstrend <span class="tendency {tendency_class}">{tendency}</span>'
        if price_m else "Keine Kursdaten verfügbar."
    )

    return f'''            <details class="position-card" open>
                <summary class="position-header">
                    <div>
                        <span class="ticker-name">{symbol}</span>
                        <span class="company-name">{name}</span><br>
                        <span class="badge">{sec_type}</span>
                        <span class="badge category-badge {cat_cls}">{category}</span>
                        {risk_badge}{qualifies_badge}{score_html}
                        <span class="badge score-arrow {arrow_cls}" title="Score-Trend ggü. vorigem Lauf">{arrow}</span>
                    </div>
                    {value_html}
                </summary>
                <div class="position-meta">{meta_line}</div>
                {note_html}
                {week_table}
                <details class="news-toggle">
                    <summary>Aktuelle News</summary>
                    <div class="news-list">
{news_html}
                    </div>
                </details>
            </details>
'''


def render_master_table(rows, score_history):
    trs = []
    for r in rows:
        segs = "".join(
            f'<span class="segment-badge {SEGMENT_BADGES[s][0]}">{SEGMENT_BADGES[s][1]}</span>'
            for s in SEGMENT_ORDER if s in r["segments"]
        )
        if r.get("qualifies"):
            segs += '<span class="segment-badge segment-qualifies">✅ erfüllt Kriterium</span>'

        pm = r["price_m"]
        cat_cls = "buy" if r["category"] == "Quick Win" else ""

        def cell(val):
            cls = "pos" if (val or 0) >= 0 else "neg"
            return f'<td class="{cls}">{pct_str(val)}</td>'

        w4 = cell(pm.get("week4")) if pm else "<td>–</td>"
        w3 = cell(pm.get("week3")) if pm else "<td>–</td>"
        w2 = cell(pm.get("week2")) if pm else "<td>–</td>"
        w1 = cell(pm.get("week1")) if pm else "<td>–</td>"
        day = cell(pm.get("day_perf")) if pm else "<td>–</td>"
        tendency = pm.get("tendency", "–") if pm else "–"
        tendency_class = pm.get("tendency_class", "neutral") if pm else "neutral"

        arrow, _ = score_arrow(r["symbol"], r["score"], score_history)
        arrow_cls = {"↑": "pos", "↓": "neg", "→": "neutral", "–": "neutral"}[arrow]

        trs.append(
            f'<tr><td>{r["name"]} ({r["symbol"]})</td>'
            f'<td>{segs}</td>'
            f'<td><span class="badge category-badge {cat_cls}">{r["category"]}</span></td>'
            f'<td>{r["score"]:.2f}</td>'
            f'{w4}{w3}{w2}{w1}{day}'
            f'<td class="tendency {tendency_class}" style="white-space:nowrap;">{tendency}</td>'
            f'<td class="{arrow_cls}" style="font-family:monospace;">{arrow}</td></tr>'
        )

    return f'''    <div class="table-wrap">
    <table class="overview-table">
        <thead>
            <tr><th>Position</th><th>Segment(e)</th><th>Kategorie</th><th>Score</th><th>W-4</th><th>W-3</th><th>W-2</th><th>W-1</th><th>Tag</th><th>Kurstrend</th><th>Score-Trend</th></tr>
        </thead>
        <tbody>
{"".join(trs)}
        </tbody>
    </table>
    </div>'''


def render_trade_log_html(events_history, name_cache, limit=10):
    if not events_history:
        return '<div class="news-summary">Noch keine Umschichtungen protokolliert.</div>'
    rows = ""
    for row in events_history[-limit:][::-1]:
        cols = row.split(",")
        if len(cols) < 8:
            continue
        ts, aktion, ticker, kategorie, preis, shares, realized, grund = cols[:8]
        cls = "buy" if aktion == "KAUF" else ""
        realized_txt = f" · Realisiert: {float(realized):+.2f} €" if realized else ""
        name = get_company_name(ticker, name_cache)
        rows += (
            f'<div class="signal-item {cls}">'
            f'<div class="signal-title">{aktion}: {name} ({ticker}) @ {float(preis):.2f} €{realized_txt}</div>'
            f'<div class="news-meta">{ts} · {grund}</div>'
            f'</div>\n'
        )
    return rows or '<div class="news-summary">Noch keine Umschichtungen protokolliert.</div>'


def render_topic_overview_html(macro_cache, now_ts):
    boxes = []
    for topic in TOPIC_ORDER:
        articles = macro_cache.get(topic, [])[:5]
        if not articles:
            body = '<div class="news-summary">Keine aktuellen Schlagzeilen im 7-Tage-Fenster.</div>'
        else:
            rows = []
            for a in articles:
                cls, icon = classify_headline(a["title"])
                rel = relative_time(a["ts"], now_ts)
                title_safe = a["title"].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                link = a.get("link") or "#"
                rows.append(
                    f'<div class="news-item sentiment-{cls}">'
                    f'<div class="news-meta">{icon} {a.get("ticker", "")} · {rel}</div>'
                    f'<a class="news-title" href="{link}" target="_blank" rel="noopener">{title_safe}</a>'
                    f'</div>'
                )
            body = "\n".join(rows)
        boxes.append(f'''            <div class="hist-box">
                <h4>{topic}</h4>
                <div class="news-list" style="max-height:200px;">
{body}
                </div>
            </div>''')
    return '<div class="topic-grid">' + "\n".join(boxes) + '</div>'


def render_week_summary_html(summary, name_cache):
    if summary["netto_now"] is None or summary["netto_week_ago"] is None:
        change_html = "Noch keine Vergleichsdaten von vor 7 Tagen vorhanden (Historie wird mit jedem Lauf länger)."
    else:
        cls = "pos" if summary["change_abs"] >= 0 else "neg"
        change_html = (
            f'Netto-Wert vor 7 Tagen: {fmt_eur(summary["netto_week_ago"])} → heute: '
            f'{fmt_eur(summary["netto_now"])} '
            f'(<span class="{cls}">{fmt_eur(summary["change_abs"], signed=True)} / '
            f'{summary["change_pct"]:+.2f}%</span>)'
        )

    movers_html = "Noch keine ausreichenden Wochendaten für Gewinner/Verlierer."
    if summary["best"] and summary["worst"]:
        b_sym, b_val = summary["best"]
        w_sym, w_val = summary["worst"]
        movers_html = (
            f'Bester Wochen-Performer: <strong>{get_company_name(b_sym, name_cache)} ({b_sym})</strong> '
            f'<span class="pos">{pct_str(b_val)}</span> · '
            f'Schwächster: <strong>{get_company_name(w_sym, name_cache)} ({w_sym})</strong> '
            f'<span class="neg">{pct_str(w_val)}</span>'
        )

    return f'''        <div class="hist-box" style="margin-top:15px;">
            <h4>📅 Wochenzusammenfassung (statistisch, nicht KI-generiert)</h4>
            <div style="font-size:13px; line-height:1.8;">{change_html}<br>{movers_html}</div>
        </div>'''


LEGEND_HTML = '''    <details class="legend-box">
        <summary>ℹ️ Wie funktioniert der Score, und was bedeutet Quick Win vs. Long?</summary>
        <div class="legend-body">
            <p>Der <strong>Score</strong> kombiniert vier Bausteine: Kursmomentum (Tag/Woche/Monat, am stärksten
            gewichtet), einen Rebound-Bonus (wie nah/fern vom 52-Wochen-Hoch, gedeckelt), das News-Sentiment
            (simple Keyword-Zählung, -5 bis +5) und eine Options-Kennzahl (Put/Call-Verhältnis, -1/0/+1).</p>
            <p>Ein höherer Score heißt nur: <em>im Vergleich zu den anderen Kandidaten dieses Laufs</em> gerade
            stärkeres Momentum/Sentiment. Es gibt keinen absoluten "ab X ist es gut"-Wert — es zählt allein die
            Rangfolge (die zehn höchsten Scores kommen ins Hauptdepot). Ein negativer Score ist nicht automatisch
            "schlecht", wenn er trotzdem unter den Top 10 liegt; ein positiver Score reicht nicht, wenn zehn
            andere Kandidaten noch höher liegen.</p>
            <p><strong>Quick Win</strong> wird vergeben, wenn der reine Momentum-Anteil (Tag/Woche/Monat) den
            Rebound-Anteil übersteigt — also ein Titel, der gerade aktiv nach oben läuft.
            <strong>Long</strong> wird vergeben, wenn der Rebound-Anteil (Erholung/Abstand vom Hoch) überwiegt —
            eher ein Titel, der von einem Tief kommt und länger angelegt betrachtet wird. Beides sind reine
            Heuristik-Label zur Einordnung, keine Kauf- oder Verkaufsempfehlung.</p>
            <p>Der kleine Pfeil (↑/↓/→) neben jedem Score ist der <strong>Score-Trend</strong>: er vergleicht nur
            den aktuellen Score mit dem Score desselben Titels beim letzten Lauf (4h zuvor) — keine Kursprognose,
            nur "wird der Kandidat gerade relativ stärker oder schwächer bewertet". Der <strong>Kurstrend</strong>
            (▲▼▲) daneben zeigt dagegen die reine Kursrichtung der letzten drei Handelstage.</p>
        </div>
    </details>'''


def render_html(timestamp, positions, price_lookup, news_cache, macro_cache, score_history,
                 name_cache, events, watchlist, musterdepot_rows, week_summary,
                 total_brutto, total_unrealized, realized_total, kest, total_netto,
                 prev_run_html, trade_log_html):

    now_ts = time.time()

    position_cards = "\n".join(
        render_card(
            sym, get_company_name(sym, name_cache), pos.get("category", ""), pos.get("type", ""),
            price_lookup.get(sym), news_cache, score_history, now_ts,
            mode="held", pos=pos, risk_flag=pos.get("risk_flag", False),
        )
        for sym, pos in positions.items()
    )

    watchlist_cards = "\n".join(
        render_card(
            c["symbol"], get_company_name(c["symbol"], name_cache), c["category"], c["type"],
            c["price_m"], news_cache, score_history, now_ts,
            mode="watchlist", score=c["score"],
        )
        for c in watchlist
    ) or '<div class="news-summary">Aktuell keine weiteren Kandidaten außerhalb der Top 10.</div>'

    musterdepot_cards_list = []
    for row in musterdepot_rows:
        if not row["available"]:
            musterdepot_cards_list.append(
                f'<div class="news-summary">⏸️ {row["name"]} ({row["symbol"]}): {row["note"] or "keine ausreichenden Daten verfügbar"}.</div>'
            )
            continue
        c = row["entry"]
        musterdepot_cards_list.append(render_card(
            c["symbol"], row["name"], c["category"], c["type"],
            c["price_m"], news_cache, score_history, now_ts,
            mode="musterdepot", score=c["score"], qualifies=row["qualifies"], note=row["note"],
        ))
    musterdepot_html = "\n".join(musterdepot_cards_list)

    master_rows = build_master_rows(positions, price_lookup, watchlist, musterdepot_rows, name_cache)
    master_table_html = render_master_table(master_rows, score_history)

    val_brutto = fmt_eur(total_brutto)
    val_unrealized = fmt_eur(total_unrealized, signed=True)
    val_realized = fmt_eur(realized_total, signed=True)
    val_kest = fmt_eur(-kest)
    val_netto = fmt_eur(total_netto)

    topic_overview_html = render_topic_overview_html(macro_cache, now_ts)
    week_summary_html = render_week_summary_html(week_summary, name_cache)

    return f"""<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>QuantFlow Tech Agent Dashboard v6.0</title>
    <style>
        :root {{
            --bg-dark: #0f111a;--bg-card: #161925;--text-main: #f0f2f5;--text-muted: #8a92b2;--green: #00e676;--red: #ff3d00;--blue: #00b0ff;--border: #22273d;--purple: #b388ff;--orange: #ffab40;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }}
        body {{ background-color: var(--bg-dark); color: var(--text-main); padding: 20px; line-height: 1.5; }}
        header {{ display: flex; justify-content: space-between; align-items: center; padding-bottom: 20px; border-bottom: 1px solid var(--border); margin-bottom: 20px; flex-wrap: wrap; gap: 10px; }}
        .logo-area h1 {{ font-size: 24px; font-weight: 700; color: var(--text-main); }}
        .logo-area span {{ color: var(--text-muted); font-size: 12px; }}
        .controls-area {{ display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }}
        .btn-refresh {{ background-color: var(--blue); color: white; border: none; padding: 8px 14px; border-radius: 6px; cursor: pointer; font-weight: bold; font-size: 12px; transition: background 0.3s; display: flex; align-items: center; gap: 6px; text-decoration: none; }}
        .btn-refresh:hover {{ opacity: 0.85; }}

        @keyframes blink {{ 0% {{ opacity: 0.4; }} 50% {{ opacity: 1; }} 100% {{ opacity: 0.4; }} }}
        .loading-active {{ background-color: #ff9100 !important; animation: blink 1.2s infinite; }}

        .footer-note {{ color: var(--text-muted); font-size: 11px; margin-top: 30px; padding-top: 12px; border-top: 1px solid var(--border); }}

        .legend-box {{ background: var(--bg-card); border: 1px solid var(--border); border-radius: 10px; padding: 12px 16px; margin-bottom: 20px; font-size: 12px; }}
        .legend-box summary {{ cursor: pointer; font-weight: 600; color: var(--blue); }}
        .legend-body {{ margin-top: 10px; color: var(--text-muted); display: flex; flex-direction: column; gap: 8px; }}
        .legend-body strong {{ color: var(--text-main); }}

        .accounting-bar {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 15px; margin-bottom: 25px; }}
        .acc-item {{ background-color: var(--bg-card); padding: 12px 20px; border-radius: 8px; border: 1px solid var(--border); }}
        .acc-item label {{ font-size: 11px; text-transform: uppercase; color: var(--text-muted); letter-spacing: 0.5px; display: block; margin-bottom: 4px; }}
        .acc-item .val {{ font-size: 18px; font-weight: 700; }}

        .section-title {{ font-size: 16px; font-weight: 600; margin: 25px 0 15px; display: flex; align-items: center; gap: 10px; }}

        .table-wrap {{ overflow-x: auto; margin-bottom: 20px; }}
        .overview-table {{ width: 100%; border-collapse: collapse; background: var(--bg-card); border-radius: 12px; overflow: hidden; font-size: 12px; }}
        .overview-table th, .overview-table td {{ padding: 5px 10px; text-align: left; border-bottom: 1px solid var(--border); white-space: nowrap; }}
        .overview-table th {{ color: var(--text-muted); font-size: 10px; text-transform: uppercase; }}

        .segment-badge {{ padding: 1px 6px; border-radius: 4px; font-size: 9px; font-weight: bold; margin-right: 3px; display: inline-block; white-space: nowrap; }}
        .segment-haupt {{ background: #1b251f; color: var(--green); }}
        .segment-watch {{ background: #1a2530; color: var(--blue); }}
        .segment-muster {{ background: #241a30; color: var(--purple); }}
        .segment-qualifies {{ background: #123321; color: var(--green); }}

        .positions-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(360px, 1fr)); gap: 16px; }}
        .position-card {{ background-color: var(--bg-card); border-radius: 12px; border: 1px solid var(--border); padding: 16px; }}
        .position-header {{ display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 8px; cursor: pointer; list-style: none; }}
        .position-header::-webkit-details-marker {{ display: none; }}
        .position-value {{ text-align: right; }}
        .position-meta {{ font-size: 12px; color: var(--text-muted); margin-bottom: 8px; line-height: 1.8; white-space: nowrap; overflow-x: auto; }}
        .ticker-name {{ font-weight: 700; font-size: 15px; margin-right: 6px; }}
        .company-name {{ font-size: 11px; color: var(--text-muted); }}
        .badge {{ padding: 2px 6px; border-radius: 4px; font-size: 10px; font-weight: bold; background: #22273d; margin-right: 4px; display: inline-block; margin-top: 4px; white-space: nowrap; }}
        .category-badge {{ background: #3a2a1a; color: #ffb74d; }}
        .category-badge.buy {{ background: #1b251f; color: var(--green); }}
        .category-badge.dispose {{ background: #3a1a1a; color: var(--red); }}
        .category-badge.qualifies {{ background: #123321; color: var(--green); }}
        .score-arrow {{ font-family: monospace; font-size: 12px; }}
        .pos {{ color: var(--green); }}
        .neg {{ color: var(--red); }}
        .neutral {{ color: var(--text-muted); }}
        .tendency {{ font-family: monospace; letter-spacing: 2px; white-space: nowrap; }}

        .week-table {{ display: flex; justify-content: space-between; background: #1c2030; border-radius: 6px; padding: 6px 8px; margin-bottom: 8px; }}
        .week-cell {{ display: flex; flex-direction: column; align-items: center; font-size: 11px; gap: 2px; }}
        .week-label {{ color: var(--text-muted); font-size: 9px; text-transform: uppercase; }}

        .news-toggle summary {{ font-size: 11px; color: var(--text-muted); cursor: pointer; padding: 4px 0; border-top: 1px solid var(--border); }}
        .news-list {{ display: flex; flex-direction: column; gap: 6px; max-height: 220px; overflow-y: auto; padding-right: 4px; padding-top: 8px; }}
        .news-item {{ background: #1c2030; padding: 8px 10px; border-radius: 6px; border-left: 3px solid var(--text-muted); }}
        .news-item.sentiment-pos {{ border-left-color: var(--green); }}
        .news-item.sentiment-neg {{ border-left-color: var(--red); }}
        .news-meta {{ font-size: 10px; color: var(--text-muted); margin-bottom: 2px; }}
        .news-title {{ font-size: 12px; font-weight: 600; color: var(--text-main); text-decoration: none; display: block; white-space: normal; }}
        .news-title:hover {{ color: var(--blue); }}
        .news-summary {{ font-size: 12px; color: var(--text-muted); padding: 8px 0; }}

        .trade-log {{ display: flex; flex-direction: column; gap: 8px; }}
        .signal-item {{ background: #251b22; padding: 12px; border-radius: 8px; border-left: 4px solid var(--red); }}
        .signal-item.buy {{ background: #1b251f; border-left: 4px solid var(--green); }}
        .signal-title {{ font-size: 13px; font-weight: bold; margin-bottom: 4px; }}

        .historical-view {{ margin-top: 25px; background-color: var(--bg-card); border-radius: 12px; border: 1px solid var(--border); padding: 20px; }}
        .hist-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-top: 15px; }}
        .hist-box {{ background: #1c2030; padding: 15px; border-radius: 8px; font-size: 13px; }}
        .hist-box h4 {{ margin-bottom: 8px; font-size: 14px; color: var(--blue); }}

        .topic-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px; }}

        @media (max-width: 700px) {{
            .accounting-bar {{ grid-template-columns: repeat(2, 1fr); }}
            .hist-grid {{ grid-template-columns: 1fr; }}
        }}
    </style>
</head>
<body>
    <header>
        <div class="logo-area">
            <h1>QuantFlow Tech Agent Dashboard <span style="color:var(--blue); font-size:14px;">v6.0</span></h1>
            <span>Simuliertes Momentum-/News-/Options-Portfolio (Paper Trading) — Letztes Update: {timestamp}</span>
        </div>
        <div class="controls-area">
            <button id="refresh-btn" onclick="triggerManualUpdate()" class="btn-refresh">🔄 Jetzt aktualisieren</button>
            <button onclick="toggleAllNews(true)" class="btn-refresh" style="background-color:#495867;">📰 News alle auf</button>
            <button onclick="toggleAllNews(false)" class="btn-refresh" style="background-color:#495867;">📰 News alle zu</button>
            <a href="portfolio_log.csv" download class="btn-refresh" style="background-color: #28a745;">📊 Wert-Historie</a>
            <a href="trade_log.csv" download class="btn-refresh" style="background-color: #6c5ce7;">🔄 Trade-Log</a>
        </div>
    </header>

    <section class="accounting-bar">
        <div class="acc-item"><label>Gesamtwert Depot (Brutto)</label><div class="val">{val_brutto}</div></div>
        <div class="acc-item"><label>Unrealisierter Gewinn/Verlust</label><div class="val {'pos' if total_unrealized >= 0 else 'neg'}">{val_unrealized}</div></div>
        <div class="acc-item"><label>Realisiert (kumuliert)</label><div class="val {'pos' if realized_total >= 0 else 'neg'}">{val_realized}</div></div>
        <div class="acc-item"><label>Rückstellung KESt (26%)</label><div class="val neg">{val_kest}</div></div>
        <div class="acc-item"><label>Netto-Wert</label><div class="val">{val_netto}</div></div>
    </section>

{LEGEND_HTML}

    <div class="section-title">📋 Gesamtübersicht (Hauptdepot · Watchlist · Musterdepot)</div>
{master_table_html}

    <div class="section-title">📈 Aktuelle Positionen ({len(positions)})</div>
    <div class="positions-grid">
{position_cards}
    </div>

    <div class="section-title">👀 Watchlist – nächste Kandidaten (nicht gehalten)</div>
    <div class="positions-grid">
{watchlist_cards}
    </div>

    <div class="section-title">🗂️ Musterdepot – Beobachtungsliste (Titel &amp; Analyse, ohne Beträge)</div>
    <div class="positions-grid">
{musterdepot_html}
    </div>

    <div class="section-title">🌍 Markt-Sentiment Überblick (Politik/Wirtschaft/Technologie/Sonstiges)</div>
    {topic_overview_html}

    <div class="section-title">🔄 Letzte Umschichtungen</div>
    <div class="trade-log">
{trade_log_html}
    </div>

    <div class="historical-view">
        <div class="section-title" style="margin-top:0;">🕓 Verlauf</div>
        <div class="hist-grid">
            <div class="hist-box">
                <h4>Aktueller Lauf</h4>
                {timestamp}<br>Brutto: {val_brutto}<br>Netto: {val_netto}
            </div>
            <div class="hist-box">
                <h4>Vorheriger Lauf</h4>
                {prev_run_html}
            </div>
        </div>
        {week_summary_html}
    </div>

    <div class="footer-note">
        Automatisiertes, simuliertes Paper-Trading-Tool zu Testzwecken · Kurs-/News-/Optionsdaten aus kostenlosen,
        teils verzögerten Quellen · Sentiment = einfache Keyword-Heuristik · Score-Trend zeigt nur die Richtung
        ggü. dem letzten Lauf, keine Kursprognose · Musterdepot zeigt nur Titel, keine Beträge.
    </div>

    <script>
        function triggerManualUpdate() {{
            var btn = document.getElementById('refresh-btn');
            btn.classList.add('loading-active');
            btn.innerText = '⏳ Aktualisiere...';
            setTimeout(function () {{ location.reload(true); }}, 800);
        }}
        function toggleAllNews(openState) {{
            document.querySelectorAll('.news-toggle').forEach(function (d) {{ d.open = openState; }});
        }}
    </script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# HAUPTABLAUF
# ---------------------------------------------------------------------------

def run_agent_update():
    now = datetime.now(timezone.utc)
    now_ts = now.timestamp()
    timestamp = now.strftime("%Y-%m-%d %H:%M:%S UTC")

    print("🚀 Baue Kandidaten-Pool auf (Basisliste + Trending + Musterdepot)...")
    candidate_pool = build_candidate_pool()
    print(f"   {len(candidate_pool)} Kandidaten im Pool.")

    state = load_json(STATE_FILE, {"positions": {}, "realized_pnl_total": 0.0, "score_history": {}})
    news_cache = load_json(NEWS_CACHE_FILE, {})
    macro_cache = load_json(MACRO_NEWS_CACHE_FILE, {})
    name_cache = load_json(NAME_CACHE_FILE, {})

    # WICHTIG: score_history hier ist bewusst der Stand VOR diesem Lauf und
    # bleibt für die Score-Trend-Pfeile beim Rendern unverändert. Erst danach
    # wird eine separate, aktualisierte Kopie für den nächsten Lauf gebaut —
    # sonst würde sich jeder Score nur mit sich selbst vergleichen.
    score_history = state.get("score_history", {})
    prev_snapshot_cols = read_prev_snapshot()

    scored = []
    price_lookup = {}
    all_fetched_news = []

    for symbol, sec_type in candidate_pool.items():
        price_m = fetch_price_metrics(symbol)
        if price_m is None:
            continue
        price_lookup[symbol] = price_m

        articles = fetch_news(symbol)
        all_fetched_news.extend(articles)
        news_cache = update_news_cache(news_cache, symbol, articles, now_ts)
        news_score = score_sentiment(news_cache.get(symbol, []))

        options_m = fetch_options_metrics(symbol)

        score, category = compute_score(price_m, news_score, options_m)
        scored.append({
            "symbol": symbol, "type": sec_type, "price_m": price_m,
            "news_score": news_score, "options_m": options_m,
            "score": score, "category": category,
        })
        time.sleep(0.3)

    for macro_sym in MACRO_TICKERS:
        macro_articles = fetch_news(macro_sym, max_items=5)
        all_fetched_news.extend(macro_articles)

    scored.sort(key=lambda c: c["score"], reverse=True)
    print(f"   {len(scored)} Kandidaten erfolgreich bewertet.")

    if not scored:
        print("⚠️ Keine Kandidaten-Daten verfügbar — Portfolio bleibt unverändert, überspringe Rebalancing.")
        new_positions = state.get("positions", {})
        events = []
    else:
        new_positions, events = rebalance(scored, state, price_lookup, timestamp)

    # Score-Historie für ALLE bewerteten Kandidaten fortschreiben (nicht nur
    # gehaltene Positionen), damit Watchlist und Musterdepot ab dem zweiten
    # Lauf ebenfalls sinnvolle Score-Trend-Pfeile zeigen.
    new_score_history = {k: list(v) for k, v in score_history.items()}
    for c in scored:
        new_score_history = update_score_history(new_score_history, c["symbol"], c["score"])

    watchlist = build_watchlist(scored, set(new_positions.keys())) if scored else []

    cutoff_score = scored[NUM_POSITIONS - 1]["score"] if len(scored) >= NUM_POSITIONS else None
    musterdepot_rows = build_musterdepot_view(scored, cutoff_score)

    realized_total = state.get("realized_pnl_total", 0.0)
    for e in events:
        if e["aktion"] == "VERKAUF" and e.get("realized_pnl") is not None:
            realized_total += e["realized_pnl"]

    news_cache = prune_cache_fully(news_cache, now_ts)
    macro_cache = build_macro_topic_overview(all_fetched_news, macro_cache, now_ts)
    macro_cache = prune_cache_fully(macro_cache, now_ts)

    new_state = {
        "positions": new_positions, "realized_pnl_total": realized_total,
        "last_run": timestamp, "score_history": new_score_history,
    }
    save_json(STATE_FILE, new_state)
    save_json(NEWS_CACHE_FILE, news_cache)
    save_json(MACRO_NEWS_CACHE_FILE, macro_cache)

    log_trades(events, timestamp)

    total_brutto = 0.0
    total_unrealized = 0.0
    for sym, pos in new_positions.items():
        current_price = price_lookup[sym]["current_price"] if sym in price_lookup else pos["entry_price"]
        value = pos["shares"] * current_price
        total_brutto += value
        total_unrealized += (current_price - pos["entry_price"]) * pos["shares"]

    kest = max(0.0, (total_unrealized + realized_total) * KEST_RATE)
    total_netto = total_brutto - kest

    log_snapshot(timestamp, total_brutto, total_unrealized, realized_total, kest, total_netto)

    week_summary = build_week_summary(price_lookup, new_positions)

    if prev_snapshot_cols and len(prev_snapshot_cols) >= 6:
        prev_ts, prev_brutto, prev_unreal, prev_real, _prev_kest, prev_netto = prev_snapshot_cols[:6]
        prev_run_html = (
            f"{prev_ts}<br>Brutto: {fmt_eur(float(prev_brutto))}<br>"
            f"Unrealisiert: {fmt_eur(float(prev_unreal), signed=True)}<br>"
            f"Netto: {fmt_eur(float(prev_netto))}"
        )
    else:
        prev_run_html = "Noch keine vorherigen Daten vorhanden."

    trade_history = []
    if os.path.exists(TRADE_LOG_FILE):
        with open(TRADE_LOG_FILE, "r", encoding="utf-8") as f:
            trade_history = [line for line in f.read().splitlines()[1:] if line.strip()]
    trade_log_html = render_trade_log_html(trade_history, name_cache)

    # Für die Score-Trend-Pfeile beim Rendern wird bewusst die ALTE
    # score_history (Stand vor diesem Lauf) übergeben — new_score_history
    # wird erst mit dem nächsten Lauf zur Vergleichsbasis.
    html = render_html(
        timestamp, new_positions, price_lookup, news_cache, macro_cache, score_history, name_cache,
        events, watchlist, musterdepot_rows, week_summary,
        total_brutto, total_unrealized, realized_total, kest, total_netto,
        prev_run_html, trade_log_html,
    )

    with open(DASHBOARD_FILE, "w", encoding="utf-8") as f:
        f.write(html)

    save_json(NAME_CACHE_FILE, name_cache)  # ggf. während des Renderns neu aufgelöste Namen sichern

    print(f"✅ Dashboard aktualisiert: {DASHBOARD_FILE} "
          f"({len(new_positions)} Positionen, {len(events)} Umschichtungen, "
          f"{len(watchlist)} Watchlist-Kandidaten, {len(musterdepot_rows)} Musterdepot-Titel)")


if __name__ == "__main__":
    run_agent_update()
