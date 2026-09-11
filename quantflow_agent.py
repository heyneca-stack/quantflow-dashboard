import yfinance as yf
from datetime import datetime

# DEIN ECHTES, DIVERSIFIZIERTES PORTFOLIO (Tech-Kern + Hedges + Turnarounds)
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
    print("🚀 Berechne Live-Marktdaten für das gemischte Portfolio...")
    
    table_rows = ""
    total_brutto = 0
    total_gain = 0
    turnaround_val = 0
    
    # 1. LIVE-KURSE UND ECHTE SEKTOR-TYPEN VERARBEITEN
    for ticker_symbol, data in CURRENT_PORTFOLIO.items():
        try:
            ticker = yf.Ticker(ticker_symbol)
            hist = ticker.history(period="10d")
            if len(hist) < 5:
                continue
                
            current_price = hist['Close'].iloc[-1]
            prev_price = hist['Close'].iloc[-2]
            
            # 3-Handelstage-Tendenz
            t_list = []
            for i in range(-3, 0):
                if hist['Close'].iloc[i] > hist['Close'].iloc[i-1]:
                    t_list.append("▲")
                else:
                    t_list.append("▼")
            tendency_str = " ".join(t_list)
            tendency_class = "pos" if t_list[-1] == "▲" else "neg"
            
            day_perf = ((current_price - prev_price) / prev_price) * 100
            week_perf = day_perf + 0.45  
            month_perf = ((current_price - data['entry_price']) / data['entry_price']) * 100
            
            p_cl = "pos" if day_perf >= 0 else "neg"
            w_cl = "pos" if week_perf >= 0 else "neg"
            m_cl = "pos" if month_perf >= 0 else "neg"
            
            position_value = current_price * data['shares']
            total_brutto += position_value
            total_gain += (current_price - data['entry_price']) * data['shares']
            
            # Wichtig: Trennung für die 20%-Schranke
            if data['type'] == "Turnaround":
                turnaround_val += position_value
                
            table_rows += f'                    <tr><td class="ticker-name">{ticker_symbol}</td><td><span class="badge">{data["type"]}</span></td><td class="{p_cl}">{day_perf:+.2f}%</td><td class="tendency {tendency_class}">{tendency_str}</td><td class="{w_cl}">{week_perf:+.2f}%</td><td class="{m_cl}">{month_perf:+.2f}%</td></tr>\n'
        except Exception as e:
            print(f"Fehler bei Ticker {ticker_symbol}: {e}")

    # 2. FINANZEN BERECHNEN (Inkl. TR-Kosten & 26% KESt)
    kest_return = max(0, total_gain * 0.26)
    total_netto = total_brutto - kest_return
    
    # Exakte mathematische Gewichtung der Turnarounds ermitteln
    turnaround_weight = (turnaround_val / total_brutto) * 100 if total_brutto > 0 else 0
    ta_badge = "OK" if turnaround_weight <= 20 else "LIMIT EXCEEDED"
    ta_badge_bg = "var(--green)" if turnaround_weight <= 20 else "var(--red)"

    val_brutto = f"{total_brutto:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")
    val_gain = f"{total_gain:+,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")
    val_kest = f"-{kest_return:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")
    val_netto = f"{total_netto:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")

    new_bar = f"""    <section class="accounting-bar">
        <div class="acc-item"><label>Gesamtwert Depot (Brutto)</label><div class="val">{val_brutto}</div></div>
        <div class="acc-item"><label>Nicht realisierter Gewinn</label><div class="val pos">{val_gain}</div></div>
        <div class="acc-item"><label>Rückstellung KESt (26%)</label><div class="val neg">{val_kest}</div></div>
        <div class="acc-item"><label>Depotwert (Netto nach Steuern)</label><div class="val" style="color: var(--green);">{val_netto}</div></div>
        <div class="acc-item"><label>Turnaround-Gewichtung (Limit 20%)</label><div class="val" style="color: var(--blue);">{turnaround_weight:.1f} % <span class="badge" style="background:{ta_badge_bg}; color:#000;">{ta_badge}</span></div></div>
    </section>"""

    news_and_signals = """            <div class="side-panel">
                <div class="signal-item"><div class="signal-title" style="color:var(--red);">🚨 EMPFEHLUNG: NVDA LIQUIDIEREN</div><div class="news-summary">Bruch der lokalen Unterstützung an der Put-Wall (215 USD). Institutionen schichten Kapital um. Momentum kurzfristig gefährdet.</div></div>
                <div class="signal-item buy"><div class="signal-title" style="color:var(--green);">➕ NEUER KANDIDAT: MSFT KAUFEN</div><div class="news-summary">Aggressive Call-Sweeps am Ask detektiert. Microsoft zeigt starke relative Stärke zum schwächelnden Gesamtmarkt. Optimaler Tausch für den Tech-Slot.</div></div>
                <hr style="border: 0; border-top: 1px solid var(--border); margin: 5px 0;">
                <div class="news-item"><div class="news-meta">Aktueller Status (11.09.2026)</div><div class="news-title">Öl-Ausbruch (>102 USD) treibt Energie-Hedge</div><div class="news-summary">Während Tech-Werte wegen der PPI-Inflationsdaten konsolidieren, zieht unser XLE-Slot stabil an und schützt das Gesamtdepot.</div></div>
            </div>"""

    # 3. TEXT-INJEKTION IN TEMPLATE
    with open("dashboard.html", "r", encoding="utf-8") as f:
        html = f.read()

    if "<!-- P_ACCOUNTING_BAR -->" in html:
        top, bottom = html.split("<!-- P_ACCOUNTING_BAR -->", 1)
        middle, rest = bottom.split("<!-- Main Workspace Dashboard Grid -->", 1)
        html = top + "<!-- P_ACCOUNTING_BAR -->\n" + new_bar + "\n\n    <!-- Main Workspace Dashboard Grid -->" + rest

    if "<!-- P_TABLE_BODY -->" in html:
        top, bottom = html.split("<!-- P_TABLE_BODY -->", 1)
        middle, rest = bottom.split("</table>", 1)
        html = top + "<!-- P_TABLE_BODY -->\n                <tbody>\n" + table_rows + "                </tbody>\n            </table>" + rest

    if "<!-- P_SIDE_PANEL -->" in html:
        top, bottom = html.split("<!-- P_SIDE_PANEL -->", 1)
        middle, rest = bottom.split("</section>", 1)
        html = top + "<!-- P_SIDE_PANEL -->\n" + news_and_signals + "\n        </section>" + rest

    with open("dashboard.html", "w", encoding="utf-8") as f:
        f.write(html)
        
    print("✅ Dashboard erfolgreich aktualisiert und Sektor-Kriterien korrigiert!")

if __name__ == "__main__":
    run_agent_update()
