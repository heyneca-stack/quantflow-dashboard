"""
Universe-Modul — Kandidaten-Universum für QuantFlow (Arbeitspapier Phase 1).

Ersetzt die alte, ungefilterte Yahoo-Trending-Ergänzung (get_dynamic_trending
in quantflow_agent.py), die laut Root-Cause-Analyse (Arbeitspapier Abschnitt 2)
dafür verantwortlich war, dass kryptonahe Aktien unbemerkt ins Hauptdepot
rutschten: Statt "was bewegt sich heute am meisten" wird das Universum jetzt
über tatsächliche Indexmitgliedschaft plus GICS-Sektor definiert (Abschnitt 4.1
und 4.2).

Quellen:
  - S&P 500, Nasdaq-100, Dow Jones Industrial Average: Wikipedia-Tabellen.
    Die S&P-500-Tabelle hat praktisch immer eine "GICS Sector"-Spalte; bei
    Nasdaq-100/Dow ist die Sektor-/Industry-Spalte teils nur Freitext oder
    fehlt für einzelne Titel. Fehlende Sektor-Angaben werden zuerst über die
    S&P-500-Zuordnung nachgeschlagen (hohe Überschneidung), erst danach als
    "Sektor unbekannt" markiert — nie stillschweigend verworfen.
  - Krypto-/Digital-Asset-nahe Aktien: eine bewusst separate, manuell
    kuratierte Liste (CRYPTO_UNIVERSE), die nur einfließt, wenn die Kategorie
    "Krypto/Digital-Asset" in der aktiven Konfiguration ausdrücklich aktiviert
    ist (siehe config.py) — Standard ist deaktiviert.

Ergebnis wird lokal gecacht (UNIVERSE_CACHE_FILE), damit nicht jeder 4-Stunden-
Lauf erneut alle drei Wikipedia-Seiten abruft (Nachrichten-/Themenradar-
Erfahrung aus dem Arbeitspapier Abschnitt 10: langsam veränderliche Daten
brauchen kein 4-Stunden-Raster). Schlägt ein Abruf fehl, wird auf einen auch
veralteten Cache-Stand zurückgefallen statt die Quelle stillschweigend leer
zu lassen; ist gar kein Cache vorhanden, bleibt diese eine Quelle leer und
wird als Warnung ausgegeben, statt den ganzen Lauf abzubrechen.

Bekannte Einschränkung (siehe Arbeitspapier Abschnitt 7, offene Frage zur
Korbgröße): Die Kappung auf max_basket_size ist noch KEINE echte
Handelsvolumen-Vorfilterung, sondern eine kostenlose Näherung ohne
Zusatz-Abrufe: Dow (30 Standardwerte) zuerst, dann neue Nasdaq-100-Titel,
dann der S&P-500-Rest in Tabellenreihenfolge. Eine echte Liquiditäts-
Vorfilterung bleibt ein offener Ausbauschritt.
"""

import io
import json
import os
import time

import requests

HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
}

WIKI_SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
WIKI_NASDAQ100_URL = "https://en.wikipedia.org/wiki/Nasdaq-100"
WIKI_DOW_URL = "https://en.wikipedia.org/wiki/Dow_Jones_Industrial_Average"

UNIVERSE_CACHE_FILE = "universe_cache.json"
UNIVERSE_CACHE_TTL_HOURS = 24

# GICS-11-Standardsektoren (deutsch), siehe Arbeitspapier Abschnitt 4.2.
# Schlüssel sind kleingeschriebene Varianten, wie sie auf Wikipedia in
# "GICS Sector"- bzw. "Industry"-Spalten vorkommen.
GICS_SECTOR_DE = {
    "energy": "Energie",
    "materials": "Grundstoffe",
    "industrials": "Industrie",
    "consumer discretionary": "Nicht-Basiskonsumgüter",
    "consumer staples": "Basiskonsumgüter",
    "health care": "Gesundheitswesen",
    "healthcare": "Gesundheitswesen",
    "financials": "Finanzwerte",
    "financial services": "Finanzwerte",
    "information technology": "Informationstechnologie",
    "technology": "Informationstechnologie",
    "communication services": "Kommunikationsdienste",
    "telecommunications services": "Kommunikationsdienste",
    "telecommunication services": "Kommunikationsdienste",
    "utilities": "Versorger",
    "real estate": "Immobilien",
}
UNBEKANNTER_SEKTOR = "Sektor unbekannt"
KRYPTO_KATEGORIE = "Krypto/Digital-Asset"

# Bewusst separate, kuratierte Liste kryptowährungs-/kryptonaher Aktien.
# Ursprung: exakt die Titel, die laut Root-Cause-Analyse (Arbeitspapier
# Abschnitt 2) über die alte, ungefilterte Yahoo-Trending-Liste ins
# Hauptdepot rutschten, ergänzt um weitere bekannte Krypto-Proxies.
# Fließt nur ein, wenn KRYPTO_KATEGORIE in der aktiven Konfiguration eine
# Gewichtung > 0 hat.
CRYPTO_UNIVERSE = {
    "MARA": "Marathon Digital Holdings Inc. (Bitcoin-Miner)",
    "RIOT": "Riot Platforms Inc. (Bitcoin-Miner)",
    "CLSK": "CleanSpark Inc. (Bitcoin-Miner)",
    "HUT": "Hut 8 Corp. (Bitcoin-Miner)",
    "CIFR": "Cipher Mining Inc. (Bitcoin-Miner)",
    "WULF": "TeraWulf Inc. (Bitcoin-Miner)",
    "COIN": "Coinbase Global Inc. (Krypto-Börse)",
    "MSTR": "Strategy Inc., vormals MicroStrategy (Bitcoin-Treasury)",
    "BMNR": "Bitmine Immersion Technologies Inc. (Krypto-Treasury)",
    "SBET": "SharpLink Gaming Inc. (Krypto-Treasury)",
    "PURR": "Hyperliquid Strategies Inc. (Krypto-Treasury)",
}


def _normalize_sector(raw):
    if not raw:
        return None
    return GICS_SECTOR_DE.get(str(raw).strip().lower())


def _find_column(columns, keywords):
    for col in columns:
        lc = str(col).lower()
        if any(kw in lc for kw in keywords):
            return col
    return None


def _parse_constituent_table(html, ticker_keywords, sector_keywords):
    """Sucht unter allen <table>-Elementen der Seite diejenige mit einer
    Ticker-Spalte (und wenn vorhanden einer Sektor-/Industry-Spalte) und
    gibt eine Liste von {"symbol": ..., "sector_raw": ... oder None} zurück.
    Robust gegenüber leicht wechselnden Wikipedia-Tabellenlayouts, da nach
    Spalten-KEYWORDS statt fester Position/Name gesucht wird."""
    import pandas as pd
    tables = pd.read_html(io.StringIO(html))
    for table in tables:
        cols = list(table.columns)
        ticker_col = _find_column(cols, ticker_keywords)
        if ticker_col is None:
            continue
        sector_col = _find_column(cols, sector_keywords)
        result = []
        for _, row in table.iterrows():
            sym = str(row[ticker_col]).strip()
            if not sym or sym.lower() == "nan":
                continue
            sym = sym.replace(".", "-")  # Wikipedia "BRK.B" -> yfinance "BRK-B"
            sector_raw = str(row[sector_col]).strip() if sector_col is not None else None
            result.append({"symbol": sym, "sector_raw": sector_raw})
        if result:
            return result
    return []


def fetch_sp500():
    resp = requests.get(WIKI_SP500_URL, headers=HTTP_HEADERS, timeout=15)
    resp.raise_for_status()
    return _parse_constituent_table(resp.text, ("symbol", "ticker"), ("gics sector", "sector"))


def fetch_nasdaq100():
    resp = requests.get(WIKI_NASDAQ100_URL, headers=HTTP_HEADERS, timeout=15)
    resp.raise_for_status()
    return _parse_constituent_table(resp.text, ("ticker", "symbol"), ("gics sector", "sector"))


def fetch_dow():
    resp = requests.get(WIKI_DOW_URL, headers=HTTP_HEADERS, timeout=15)
    resp.raise_for_status()
    return _parse_constituent_table(resp.text, ("symbol",), ("industry", "gics sector", "sector"))


FETCHERS = {"sp500": fetch_sp500, "nasdaq100": fetch_nasdaq100, "dow": fetch_dow}


def _load_cache():
    if not os.path.exists(UNIVERSE_CACHE_FILE):
        return None
    try:
        with open(UNIVERSE_CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _save_cache(data):
    with open(UNIVERSE_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_raw_universe_data(force_refresh=False):
    """{"sp500": [...], "nasdaq100": [...], "dow": [...], "fetched_at": ts}.
    Nutzt den Cache, solange er jünger als UNIVERSE_CACHE_TTL_HOURS ist. Bei
    Cache-Ablauf wird neu abgerufen; schlägt der Abruf für eine einzelne
    Quelle fehl, wird für GENAU diese Quelle der alte Cache-Wert behalten
    statt sie leer zu räumen. Schlägt alles fehl und existiert ein (auch
    abgelaufener) Cache, wird dieser komplett weiterverwendet."""
    cache = _load_cache()
    cache_age_h = (time.time() - cache["fetched_at"]) / 3600 if cache else None
    if cache and not force_refresh and cache_age_h is not None and cache_age_h < UNIVERSE_CACHE_TTL_HOURS:
        return cache

    fresh = {"fetched_at": time.time()}
    any_ok = False
    for key, fetcher in FETCHERS.items():
        try:
            fresh[key] = fetcher()
            any_ok = True
        except Exception as e:
            print(f"⚠️ Universum-Abruf '{key}' fehlgeschlagen ({e}).")
            fresh[key] = None

    if not any_ok:
        if cache:
            print("⚠️ Kein Universum-Abruf erfolgreich — nutze zuletzt gecachten Stand (evtl. veraltet).")
            return cache
        print("⚠️ Kein Universum-Abruf erfolgreich UND kein Cache vorhanden — Universum bleibt leer.")
        return fresh

    if cache:
        for key in FETCHERS:
            if fresh.get(key) is None and cache.get(key):
                print(f"   Behalte gecachten Stand für '{key}' (aktueller Abruf fehlgeschlagen).")
                fresh[key] = cache[key]

    _save_cache(fresh)
    return fresh


def build_universe(config, force_refresh=False):
    """Baut den Kandidaten-Pool gemäß aktiver Konfiguration: {symbol: sector_label}.
    Ersetzt die alte, ungefilterte Yahoo-Trending-Ergänzung vollständig
    (Arbeitspapier Abschnitt 2 und 4.1)."""
    raw = get_raw_universe_data(force_refresh=force_refresh)
    active_universes = config.get("universes", {})
    active_sectors = config.get("sectors", {})

    sp500_sector_by_symbol = {}
    for row in (raw.get("sp500") or []):
        sec = _normalize_sector(row.get("sector_raw"))
        if sec:
            sp500_sector_by_symbol[row["symbol"]] = sec

    def sector_allowed(sector):
        weight = active_sectors.get(sector)
        if weight is None:
            # Sektor kommt in der Konfiguration gar nicht vor (z.B. ältere,
            # unvollständige Konfigurationsdatei) -> defensiv erlauben statt
            # den Titel stillschweigend zu verlieren.
            return True
        return weight > 0.0

    pool = {}
    # Priorität Dow -> Nasdaq-100 -> S&P 500: siehe Modul-Docstring zur
    # (noch approximativen) Korbgrößen-Kappung.
    for key in ("dow", "nasdaq100", "sp500"):
        if not active_universes.get(key, False):
            continue
        for row in (raw.get(key) or []):
            sym = row["symbol"]
            if sym in pool:
                continue
            sector = _normalize_sector(row.get("sector_raw")) or sp500_sector_by_symbol.get(sym) or UNBEKANNTER_SEKTOR
            if not sector_allowed(sector):
                continue
            pool[sym] = sector

    if active_sectors.get(KRYPTO_KATEGORIE, 0.0) > 0.0:
        for sym in CRYPTO_UNIVERSE:
            if sym not in pool:
                pool[sym] = KRYPTO_KATEGORIE

    max_size = config.get("max_basket_size")
    if max_size and len(pool) > max_size:
        print(f"   Universum ({len(pool)} Titel) auf Korb-Obergrenze {max_size} gekappt "
              f"(Priorität Dow → Nasdaq-100 → S&P 500, siehe Arbeitspapier Abschnitt 7).")
        pool = dict(list(pool.items())[:max_size])

    return pool
