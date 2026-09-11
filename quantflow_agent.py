"""
QuantFlow Tech Agent — automatisiertes Paper-Trading-Dashboard.

WICHTIG: Dies ist ein simuliertes ("Papier"-)Portfolio zu Test-/Beobachtungszwecken.
Es wird kein echtes Geld gehandelt, keine Anlageberatung, keine Garantie auf
Richtigkeit der Kurs-, News- oder Optionsdaten (kostenlose, teils verzögerte
Quellen). Die Auswahl basiert auf einfachen, transparenten Heuristiken
(Kursmomentum, Abstand vom 52-Wochen-Hoch, Schlagzeilen-Keywords,
Options-Volumen/Open-Interest) — keine echte KI-Textanalyse und kein
echter institutioneller Option-Flow.

Läuft alle 4 Stunden per GitHub Actions (siehe .github/workflows/run_agent.yml).
Zustand (aktuelle Positionen, News-Cache) wird in JSON-Dateien zwischen den
Läufen persistiert und vom Workflow mit zurückcommitet.
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

# Basis-Kandidatenliste (Sicherheitsnetz, falls die dynamische Trend-Abfrage
# mal ausfällt). Tech-Schwerpunkt mit etwas Streuung in andere Sektoren.
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

# Freie Yahoo-Finance-Screener, die zusätzlich zur Basisliste abgefragt werden,
# damit tagesaktuell auffällige Werte (die gerade in den News/im Markt
# auftauchen) automatisch mit ins Scoring rutschen können.
TRENDING_SCREENER_IDS = ("day_gainers", "growth_technology_stocks", "most_actives")
TRENDING_COUNT_PER_SCREENER = 15

NUM_POSITIONS = 10
ALLOCATION_PER_POSITION = 5000.0  # EUR, fiktives Kapital pro Slot
KEST_RATE = 0.26
NEWS_RETENTION_DAYS = 7
NEWS_MAX_PER_TICKER = 15
NEWS_MAX_FETCH = 8  # wie viele Artikel pro Ticker/Lauf neu abgerufen werden

# Scoring-Gewichte (bewusst als Konstanten, damit sie später leicht angepasst
# werden können)
W_DAY = 1.0
W_WEEK = 0.6
W_MONTH = 0.3
W_REBOUND = 0.15   # je % Abstand vom 52W-Hoch (gedeckelt)
W_NEWS = 1.5
W_OPTIONS = 2.0

STATE_FILE = "portfolio_state.json"
NEWS_CACHE_FILE = "news_cache.json"
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

HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
}


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


# ---------------------------------------------------------------------------
# DATENBESCHAFFUNG: KURSE, TRENDING, NEWS, OPTIONEN
# ---------------------------------------------------------------------------

def get_dynamic_trending():
    """Fragt Yahoo Finances kostenlose Screener ab, um tagesaktuell auffällige
    Ticker zu finden. Bei jedem Fehler (Timeout, geänderte API, Rate-Limit)
    wird einfach eine leere Menge zurückgegeben — der Agent läuft dann nur
    mit der Basisliste weiter, statt komplett zu scheitern."""
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

        return {
            "symbol": symbol,
            "current_price": current_price,
            "day_perf": day_perf,
            "week_perf": week_perf,
            "month_perf": month_perf,
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
    """Nutzt yfinance's eingebautes Ticker.news (kostenlose Yahoo-Finance-
    Schlagzeilen) statt fragilem RSS-/Webseiten-Scraping."""
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
    """Rudimentäre, aber echte (kostenlose) Optionsdaten über yfinances
    Options-Chain: Put/Call-Volumenverhältnis der nächsten Verfallsserie
    sowie die Strikes mit dem höchsten Open Interest als grobe Näherung
    für 'Call-Wand' / 'Put-Wand'. Kein echter institutioneller Order-Flow
    (Sweeps/Blocks) — dafür gibt es keine stabile kostenlose Quelle."""
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
# SCORING & PORTFOLIO-REBALANCING
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

    return new_positions, events


def update_news_cache(cache, symbol, new_articles, now_ts):
    existing = cache.get(symbol, [])
    combined = existing + new_articles
    seen = set()
    deduped = []
    for a in combined:
        key = (a.get("title"), a.get("link"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(a)

    cutoff = now_ts - NEWS_RETENTION_DAYS * 86400
    filtered = [a for a in deduped if a.get("ts") and a["ts"] >= cutoff]
    filtered.sort(key=lambda a: a["ts"], reverse=True)
    cache[symbol] = filtered[:NEWS_MAX_PER_TICKER]
    return cache


def prune_cache_fully(cache, now_ts):
    """Entfernt Ticker komplett, deren News alle älter als das Retention-
    Fenster sind (hält den News-Cache über die Zeit klein)."""
    cutoff = now_ts - NEWS_RETENTION_DAYS * 86400
    pruned = {}
    for sym, articles in cache.items():
        fresh = [a for a in articles if a.get("ts") and a["ts"] >= cutoff]
        if fresh:
            pruned[sym] = fresh
    return pruned


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


def render_position_card(symbol, pos, price_lookup, news_cache, now_ts):
    price_m = price_lookup.get(symbol)
    current_price = price_m["current_price"] if price_m else pos["entry_price"]
    day_perf = price_m["day_perf"] if price_m else 0.0
    week_perf = price_m["week_perf"] if price_m else 0.0
    month_perf = price_m["month_perf"] if price_m else 0.0
    tendency = price_m["tendency"] if price_m else "–"
    tendency_class = price_m["tendency_class"] if price_m else "neutral"

    gain = (current_price - pos["entry_price"]) * pos["shares"]
    value = current_price * pos["shares"]
    gain_cls = "pos" if gain >= 0 else "neg"
    day_cls = "pos" if day_perf >= 0 else "neg"
    week_cls = "pos" if week_perf >= 0 else "neg"
    month_cls = "pos" if month_perf >= 0 else "neg"
    cat_cls = "buy" if pos.get("category") == "Quick Win" else ""

    news_html = render_news_html(symbol, news_cache, now_ts)

    return f'''            <div class="position-card">
                <div class="position-header">
                    <div>
                        <span class="ticker-name">{symbol}</span>
                        <span class="badge">{pos.get("type", "")}</span>
                        <span class="badge category-badge {cat_cls}">{pos.get("category", "")}</span>
                    </div>
                    <div class="position-value">
                        <div class="val">{fmt_eur(value)}</div>
                        <div class="val {gain_cls}" style="font-size:13px;">{fmt_eur(gain, signed=True)}</div>
                    </div>
                </div>
                <div class="position-meta">
                    Einstieg: {pos.get("entry_date", "–")} @ {fmt_eur(pos["entry_price"])} ·
                    Aktuell: {fmt_eur(current_price)} ·
                    Tag <span class="{day_cls}">{day_perf:+.2f}%</span> ·
                    Woche <span class="{week_cls}">{week_perf:+.2f}%</span> ·
                    Monat <span class="{month_cls}">{month_perf:+.2f}%</span> ·
                    Trend <span class="tendency {tendency_class}">{tendency}</span>
                </div>
                <div class="news-list">
{news_html}
                </div>
            </div>
'''


def render_trade_log_html(events_history, limit=10):
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
        rows += (
            f'<div class="signal-item {cls}">'
            f'<div class="signal-title">{aktion}: {ticker} @ {float(preis):.2f} €{realized_txt}</div>'
            f'<div class="news-meta">{ts} · {grund}</div>'
            f'</div>\n'
        )
    return rows or '<div class="news-summary">Noch keine Umschichtungen protokolliert.</div>'


def render_html(timestamp, positions, price_lookup, news_cache, events,
                 total_brutto, total_unrealized, realized_total, kest, total_netto,
                 prev_run_html, trade_log_html):

    position_cards = "\n".join(
        render_position_card(sym, pos, price_lookup, news_cache, time.time())
        for sym, pos in positions.items()
    )

    val_brutto = fmt_eur(total_brutto)
    val_unrealized = fmt_eur(total_unrealized, signed=True)
    val_realized = fmt_eur(realized_total, signed=True)
    val_kest = fmt_eur(-kest)
    val_netto = fmt_eur(total_netto)

    return f"""<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>QuantFlow Tech Agent Dashboard v3.0</title>
    <style>
        :root {{
            --bg-dark: #0f111a;--bg-card: #161925;--text-main: #f0f2f5;--text-muted: #8a92b2;--green: #00e676;--red: #ff3d00;--blue: #00b0ff;--border: #22273d;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }}
        body {{ background-color: var(--bg-dark); color: var(--text-main); padding: 20px; line-height: 1.5; }}
        header {{ display: flex; justify-content: space-between; align-items: center; padding-bottom: 20px; border-bottom: 1px solid var(--border); margin-bottom: 20px; flex-wrap: wrap; gap: 10px; }}
        .logo-area h1 {{ font-size: 24px; font-weight: 700; color: var(--text-main); }}
        .logo-area span {{ color: var(--text-muted); font-size: 12px; }}
        .controls-area {{ display: flex; align-items: center; gap: 15px; }}
        .btn-refresh {{ background-color: var(--blue); color: white; border: none; padding: 8px 16px; border-radius: 6px; cursor: pointer; font-weight: bold; transition: background 0.3s; display: flex; align-items: center; gap: 8px; text-decoration: none; }}
        .btn-refresh:hover {{ background-color: #0091ea; }}

        @keyframes blink {{ 0% {{ opacity: 0.4; }} 50% {{ opacity: 1; }} 100% {{ opacity: 0.4; }} }}
        .loading-active {{ background-color: #ff9100 !important; animation: blink 1.2s infinite; }}

        .disclaimer {{ background: #1c2030; border-left: 4px solid var(--blue); padding: 12px 16px; border-radius: 8px; font-size: 12px; color: var(--text-muted); margin-bottom: 20px; }}

        .accounting-bar {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 15px; margin-bottom: 25px; }}
        .acc-item {{ background-color: var(--bg-card); padding: 12px 20px; border-radius: 8px; border: 1px solid var(--border); }}
        .acc-item label {{ font-size: 11px; text-transform: uppercase; color: var(--text-muted); letter-spacing: 0.5px; display: block; margin-bottom: 4px; }}
        .acc-item .val {{ font-size: 18px; font-weight: 700; }}

        .section-title {{ font-size: 16px; font-weight: 600; margin: 25px 0 15px; display: flex; align-items: center; gap: 10px; }}

        .positions-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(360px, 1fr)); gap: 16px; }}
        .position-card {{ background-color: var(--bg-card); border-radius: 12px; border: 1px solid var(--border); padding: 16px; }}
        .position-header {{ display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 8px; }}
        .position-value {{ text-align: right; }}
        .position-meta {{ font-size: 12px; color: var(--text-muted); margin-bottom: 12px; line-height: 1.8; }}
        .ticker-name {{ font-weight: 700; font-size: 15px; margin-right: 6px; }}
        .badge {{ padding: 2px 6px; border-radius: 4px; font-size: 10px; font-weight: bold; background: #22273d; margin-right: 4px; display: inline-block; }}
        .category-badge {{ background: #3a2a1a; color: #ffb74d; }}
        .category-badge.buy {{ background: #1b251f; color: var(--green); }}
        .pos {{ color: var(--green); }}
        .neg {{ color: var(--red); }}
        .neutral {{ color: var(--text-muted); }}
        .tendency {{ font-family: monospace; letter-spacing: 2px; }}

        .news-list {{ display: flex; flex-direction: column; gap: 6px; max-height: 220px; overflow-y: auto; padding-right: 4px; border-top: 1px solid var(--border); padding-top: 8px; }}
        .news-item {{ background: #1c2030; padding: 8px 10px; border-radius: 6px; border-left: 3px solid var(--text-muted); }}
        .news-item.sentiment-pos {{ border-left-color: var(--green); }}
        .news-item.sentiment-neg {{ border-left-color: var(--red); }}
        .news-meta {{ font-size: 10px; color: var(--text-muted); margin-bottom: 2px; }}
        .news-title {{ font-size: 12px; font-weight: 600; color: var(--text-main); text-decoration: none; display: block; }}
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

        @media (max-width: 700px) {{
            .accounting-bar {{ grid-template-columns: repeat(2, 1fr); }}
            .hist-grid {{ grid-template-columns: 1fr; }}
        }}
    </style>
</head>
<body>
    <header>
        <div class="logo-area">
            <h1>QuantFlow Tech Agent Dashboard <span style="color:var(--blue); font-size:14px;">v3.0</span></h1>
            <span>Simuliertes Momentum-/News-/Options-Portfolio (Paper Trading) — Letztes Update: {timestamp}</span>
        </div>
        <div class="controls-area">
            <button id="refresh-btn" onclick="triggerManualUpdate()" class="btn-refresh">🔄 Jetzt aktualisieren</button>
            <a href="portfolio_log.csv" download class="btn-refresh" style="background-color: #28a745;">📊 Wert-Historie</a>
            <a href="trade_log.csv" download class="btn-refresh" style="background-color: #6c5ce7;">🔄 Trade-Log</a>
        </div>
    </header>

    <div class="disclaimer">
        ⚠️ <strong>Keine Anlageberatung.</strong> Dies ist ein automatisiertes, simuliertes Papier-Portfolio zu Test-/Beobachtungszwecken.
        Kursdaten, Schlagzeilen und Optionskennzahlen stammen aus kostenlosen, teils verzögerten Quellen (Yahoo Finance).
        Die "Sentiment"-Einschätzung ist eine simple Keyword-Heuristik, keine echte KI-Textanalyse. Die Options-Kennzahlen
        basieren auf öffentlichen Volumen-/Open-Interest-Daten, nicht auf echtem institutionellem Order-Flow.
    </div>

    <section class="accounting-bar">
        <div class="acc-item"><label>Gesamtwert Depot (Brutto)</label><div class="val">{val_brutto}</div></div>
        <div class="acc-item"><label>Unrealisierter Gewinn/Verlust</label><div class="val {'pos' if total_unrealized >= 0 else 'neg'}">{val_unrealized}</div></div>
        <div class="acc-item"><label>Realisiert (kumuliert)</label><div class="val {'pos' if realized_total >= 0 else 'neg'}">{val_realized}</div></div>
        <div class="acc-item"><label>Rückstellung KESt (26%)</label><div class="val neg">{val_kest}</div></div>
        <div class="acc-item"><label>Netto-Wert</label><div class="val">{val_netto}</div></div>
    </section>

    <div class="section-title">📈 Aktuelle Positionen ({len(positions)})</div>
    <div class="positions-grid">
{position_cards}
    </div>

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
    </div>

    <script>
        function triggerManualUpdate() {{
            var btn = document.getElementById('refresh-btn');
            btn.classList.add('loading-active');
            btn.innerText = '⏳ Aktualisiere...';
            setTimeout(function () {{ location.reload(true); }}, 800);
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

    print("🚀 Baue Kandidaten-Pool auf (Basisliste + Trending)...")
    candidate_pool = build_candidate_pool()
    print(f"   {len(candidate_pool)} Kandidaten im Pool.")

    state = load_json(STATE_FILE, {"positions": {}, "realized_pnl_total": 0.0})
    news_cache = load_json(NEWS_CACHE_FILE, {})
    prev_snapshot_cols = read_prev_snapshot()

    scored = []
    price_lookup = {}

    for symbol, sec_type in candidate_pool.items():
        price_m = fetch_price_metrics(symbol)
        if price_m is None:
            continue
        price_lookup[symbol] = price_m

        articles = fetch_news(symbol)
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

    scored.sort(key=lambda c: c["score"], reverse=True)
    print(f"   {len(scored)} Kandidaten erfolgreich bewertet.")

    if not scored:
        print("⚠️ Keine Kandidaten-Daten verfügbar — Portfolio bleibt unverändert, überspringe Rebalancing.")
        new_positions = state.get("positions", {})
        events = []
    else:
        new_positions, events = rebalance(scored, state, price_lookup, timestamp)

    realized_total = state.get("realized_pnl_total", 0.0)
    for e in events:
        if e["aktion"] == "VERKAUF" and e.get("realized_pnl") is not None:
            realized_total += e["realized_pnl"]

    news_cache = prune_cache_fully(news_cache, now_ts)

    new_state = {"positions": new_positions, "realized_pnl_total": realized_total, "last_run": timestamp}
    save_json(STATE_FILE, new_state)
    save_json(NEWS_CACHE_FILE, news_cache)

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
    trade_log_html = render_trade_log_html(trade_history)

    html = render_html(
        timestamp, new_positions, price_lookup, news_cache, events,
        total_brutto, total_unrealized, realized_total, kest, total_netto,
        prev_run_html, trade_log_html,
    )

    with open(DASHBOARD_FILE, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"✅ Dashboard aktualisiert: {DASHBOARD_FILE} "
          f"({len(new_positions)} Positionen, {len(events)} Umschichtungen)")


if __name__ == "__main__":
    run_agent_update()
