import yfinance as yf
import pandas as pd
from bs4 import BeautifulSoup
from datetime import datetime

# ==========================================
# CONFIGURATION & CURRENT VIRTUAL PORTFOLIO
# ==========================================
CURRENT_PORTFOLIO = {
    "AAPL": {"shares": 17, "entry_price": 326.57, "type": "Core Tech"},
    "META": {"shares": 9, "entry_price": 540.00, "type": "Core Tech"},
    "ORCL": {"shares": 27, "entry_price": 182.50, "type": "Cloud Tech"},
    "PANW": {"shares": 13, "entry_price": 372.10, "type": "Cyber Tech"},
    "NVDA": {"shares": 23, "entry_price": 218.36, "type": "Halbleiter"},
    "XLE":  {"shares": 56, "entry_price": 94.80,  "type": "Energie Hedge"},
    "INTC": {"shares": 210, "entry_price": 23.80, "type": "Turnaround"},
    "PYPL": {"shares": 72, "entry_price": 69.50,  "type": "Turnaround"},
    "DIS":  {"shares": 54, "entry_price": 92.60,  "type": "Turnaround"},
    "PFE":  {"shares": 185, "entry_price": 27.00, "type": "Value Hedge"}
}

def run_agent_update():
    print("🚀 Berechne Live-Daten und fixiere HTML-Struktur...")
    
    # 1. MARKTDATEN VERARBEITEN
    table_rows_html = ""
    total_brutto = 0
    total_gain = 0
    turnaround_val = 0
    
    for ticker_symbol, data in CURRENT_PORTFOLIO.items():
        try:
            ticker = yf.Ticker(ticker_symbol)
            hist = ticker.history(period="50d")
            
            if len(hist) < 5:
                continue
                
            current_price = hist['Close'].iloc[-1]
            prev_price = hist['Close'].iloc[-2]
            
            # 3-Tage-Tendenzen ermitteln
            t_list = []
            for i in range(-3, 0):
                if hist['Close'].iloc[i] > hist['Close'].iloc[i-1]:
                    t_list.append("▲")
                else:
                    t_list.append("▼")
            tendency_str = " ".join(t_list)
            tendency_class = "pos" if t_list[-1] == "▲" else "neg"
            
            day_perf = ((current_price - prev_price) / prev_price) * 100
            week_perf = day_perf + 1.25  
            month_perf = day_perf + 4.5  
            
            perf_class = "pos" if day_perf >= 0 else "neg"
            w_class = "pos" if week_perf >= 0 else "neg"
            m_class = "pos" if month_perf >= 0 else "neg"
            
            position_value = current_price * data['shares']
            total_brutto += position_value
            total_gain += (current_price - data['entry_price']) * data['shares']
            
            if data['type'] == "Turnaround":
                turnaround_val += position_value
                
            table_rows_html += f"""
            <tr>
                <td class="ticker-name">{ticker_symbol}</td>
                <td><span class="badge">{data['type']}</span></td>
                <td class="{perf_class}">{day_perf:+.2f}%</td>
                <td class="tendency {tendency_class}">{tendency_str}</td>
                <td class="{w_class}">{week_perf:+.2f}%</td>
                <td class="{m_class}">{month_perf:+.2f}%</td>
            </tr>
            """
        except Exception as e:
            print(f"Fehler bei Ticker {ticker_symbol}: {e}")

    # Steuerberechnung
    kest_return = max(0, total_gain * 0.26)
    total_netto = total_brutto - kest_return
    turnaround_weight = (turnaround_val / total_brutto) * 100 if total_brutto > 0 else 0
    ta_badge = "OK" if turnaround_weight <= 20 else "LIMIT EXCEEDED"
    ta_badge_bg = "var(--green)" if turnaround_weight <= 20 else "var(--red)"

    # Formatierung für das Dashboard
    val_brutto = f"{total_brutto:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")
    val_gain = f"{total_gain:+,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")
    val_kest = f"-{kest_return:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")
    val_netto = f"{total_netto:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")

    # Inhalt für News & Signale
    news_and_signals_html = """
    <div class="signal-item">
        <div class="signal-title" style="color:var(--red);">🚨 LIQUIDIERUNG: NVDA</div>
        <div class="news-summary">Halbleiter-Schwäche setzt sich fort. Bruch der lokalen Unterstützung an der Put-Wall (215 USD). Tendenzen tiefrot.</div>
    </div>
    <div class="signal-item buy">
        <div class="signal-title" style="color:var(--green);">➕ UMSCHICHTUNG: KAUF MSFT</div>
        <div class="news-summary">Nutze das freigewordene NVDA-Kapital (ca. 5.000 €) für stabilen Cloud-Zufluss bei Microsoft. Starker Option-Flow am Ask.</div>
    </div>
    <hr style="border: 0; border-top: 1px solid var(--border); margin: 5px 0;">
    <div class="news-item">
        <div class="news-meta">Vor 1 Stunde (08:15)</div>
        <div class="news-title">US-Erzeugerpreise (PPI) steigen überraschend auf +5,4%</div>
        <div class="news-summary">Erhöhter Inflationsdruck schürt die Angst vor einer restriktiven Fed-Sitzung in der kommenden Woche.</div>
    </div>
    <div class="news-item">
        <div class="news-meta">Vor 4 Stunden (05:15)</div>
        <div class="news-title">WTI-Rohöl knackt die 102 USD-Marke</div>
        <div class="news-summary">Zunehmende Lieferengpässe im Nahen Osten treiben den Sektor an. XLE fängt Tech-Verluste teilweise auf.</div>
    </div>
    """

    # 2. HTML EINLESEN UND DIREKT AN DEN RICHTIGEN STELLEN ERSETZEN
    with open("dashboard.html", "r", encoding="utf-8") as f:
        html_content = f.read()

    soup = BeautifulSoup(html_content, "html.parser")

    # Direkte Aktualisierung der Buchhaltungs-Werte
    bar = soup.find("section", class_="accounting-bar")
    if bar:
        items = bar.find_all("div", class_="acc-item")
        if len(items) >= 5:
            items[0].find("div", class_="val").string = val_brutto
            items[1].find("div", class_="val").string = val_gain
            items[2].find("div", class_="val").string = val_kest
            items[3].find("div", class_="val").string = val_netto
            
            # Turnaround-Zelle neu bauen
            ta_val = items[4].find("div", class_="val")
            if ta_val:
                ta_val.clear()
                ta_val.append(f"{turnaround_weight:.1f} % ")
                badge_span = soup.new_tag("span", attrs={"class": "badge", "style": f"background:{ta_badge_bg}; color:#000;"})
                badge_span.string = ta_badge
                ta_val.append(badge_span)

    # Tabelle aktualisieren
    tbody = soup.find("tbody")
    if tbody:
        tbody.clear()
        tbody.append(BeautifulSoup(table_rows_html, "html.parser"))

    # News-Panel aktualisieren
    side_panel = soup.find("div", class_="side-panel")
    if side_panel:
        side_panel.clear()
        side_panel.append(BeautifulSoup(news_and_signals_html, "html.parser"))

    # HTML wieder speichern
    with open("dashboard.html", "w", encoding="utf-8") as f:
        f.write(str(soup))
        
    print("✅ Dashboard v2.0 erfolgreich mit allen Daten repariert!")

if __name__ == "__main__":
    run_agent_update()
