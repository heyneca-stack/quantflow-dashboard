import yfinance as yf
from datetime import datetime
import os

# DEIN DIVERSIFIZIERTES PORTFOLIO (Tech-Kern + Hedges + Turnarounds)
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
    print("🚀 Berechne Live-Marktdaten und generiere sauberes HTML-Dashboard...")

    table_rows = ""
    signals_list = []
    total_brutto = 0
    total_gain = 0
    turnaround_val = 0
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

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
                if hist['Close'].iloc[i] > hist['Close'].iloc[i - 1]:
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

            if data['type'] == "Turnaround":
                turnaround_val += position_value

            table_rows += f'''                    <tr>
                        <td class="ticker-name">{ticker_symbol}</td>
                        <td><span class="badge">{data["type"]}</span></td>
                        <td class="{p_cl}">{day_perf:+.2f}%</td>
                        <td class="tendency {tendency_class}">{tendency_str}</td>
                        <td class="{w_cl}">{week_perf:+.2f}%</td>
                        <td class="{m_cl}">{month_perf:+.2f}%</td>
                    </tr>\n'''

            # Auffällige Bewegungen fürs Seitenpanel sammeln (rein informativ, keine Anlageberatung)
            if month_perf <= -10:
                signals_list.append((
                    "signal-item",
                    f"{ticker_symbol}: {month_perf:+.1f}% seit Einstieg – größter Rücksetzer im Depot"
                ))
            elif day_perf >= 3:
                signals_list.append((
                    "signal-item buy",
                    f"{ticker_symbol}: starker Tagesgewinn {day_perf:+.2f}%"
                ))
            elif day_perf <= -3:
                signals_list.append((
                    "signal-item",
                    f"{ticker_symbol}: starker Tagesverlust {day_perf:+.2f}%"
                ))
        except Exception as e:
            print(f"Fehler bei Ticker {ticker_symbol}: {e}")

    # 2. FINANZEN & STEUERN BERECHNEN (26% KESt)
    kest_return = max(0, total_gain * 0.26)
    total_netto = total_brutto - kest_return
    turnaround_weight = (turnaround_val / total_brutto) * 100 if total_brutto > 0 else 0
    ta_badge = "OK" if turnaround_weight <= 20 else "LIMIT EXCEEDED"
    ta_badge_bg = "var(--green)" if turnaround_weight <= 20 else "var(--red)"

    val_brutto = f"{total_brutto:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")
    val_gain = f"{total_gain:+,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")
    val_kest = f"-{kest_return:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")
    val_netto = f"{total_netto:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")

    # Panel mit auffälligen Bewegungen bauen
    if signals_list:
        signal_html = "\n".join(
            f'                <div class="{css_cls}"><div class="signal-title">{title}</div></div>'
            for css_cls, title in signals_list
        )
    else:
        signal_html = '                <div class="news-summary">Keine auffälligen Bewegungen erkannt.</div>'

    # 3. CSV-HISTORIE LESEN (für den Vorheriger-Lauf-Vergleich) UND LOGGEN
    csv_file = "portfolio_log.csv"
    prev_run_html = "Noch keine vorherigen Daten vorhanden."
    if os.path.exists(csv_file):
        with open(csv_file, "r", encoding="utf-8") as f:
            existing_lines = [line for line in f.read().splitlines() if line.strip()]
        if len(existing_lines) > 1:  # Header + mindestens ein Datensatz
            last_fields = existing_lines[-1].split(",")
            if len(last_fields) >= 5:
                prev_ts, prev_brutto, _prev_gain, _prev_kest, prev_netto = last_fields[:5]
                prev_brutto_fmt = f"{float(prev_brutto):,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")
                prev_netto_fmt = f"{float(prev_netto):,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")
                prev_run_html = f"{prev_ts}<br>Brutto: {prev_brutto_fmt}<br>Netto: {prev_netto_fmt}"
    else:
        with open(csv_file, "w", encoding="utf-8") as f:
            f.write("Zeitstempel,Brutto_Wert,Gewinn_Verlust,Steuer_Rueckstellung,Netto_Wert,Turnaround_Anteil_Prozent\n")

    with open(csv_file, "a", encoding="utf-8") as f:
        f.write(f"{timestamp},{total_brutto:.2f},{total_gain:.2f},{kest_return:.2f},{total_netto:.2f},{turnaround_weight:.1f}\n")

    # 4. DAS GESAMTE DASHBOARD-HTML ABSOLUT STABIL GENERIEREN
    full_html = f"""<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>QuantFlow Tech Agent Dashboard v2.0</title>
    <style>
        :root {{
            --bg-dark: #0f111a;--bg-card: #161925;--text-main: #f0f2f5;--text-muted: #8a92b2;--green: #00e676;--red: #ff3d00;--blue: #00b0ff;--border: #22273d;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }}
        body {{ background-color: var(--bg-dark); color: var(--text-main); padding: 20px; line-height: 1.5; }}
        header {{ display: flex; justify-content: space-between; align-items: center; padding-bottom: 20px; border-bottom: 1px solid var(--border); margin-bottom: 20px; }}
        .logo-area h1 {{ font-size: 24px; font-weight: 700; color: var(--text-main); }}
        .logo-area span {{ color: var(--text-muted); font-size: 12px; }}
        .controls-area {{ display: flex; align-items: center; gap: 15px; }}
        .btn-refresh {{ background-color: var(--blue); color: white; border: none; padding: 8px 16px; border-radius: 6px; cursor: pointer; font-weight: bold; transition: background 0.3s; display: flex; align-items: center; gap: 8px; text-decoration: none; }}
        .btn-refresh:hover {{ background-color: #0091ea; }}

        @keyframes blink {{ 0% {{ opacity: 0.4; }} 50% {{ opacity: 1; }} 100% {{ opacity: 0.4; }} }}
        .loading-active {{ background-color: #ff9100 !important; animation: blink 1.2s infinite; }}

        .accounting-bar {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 15px; margin-bottom: 25px; }}
        .acc-item {{ background-color: var(--bg-card); padding: 12px 20px; border-radius: 8px; border: 1px solid var(--border); }}
        .acc-item label {{ font-size: 11px; text-transform: uppercase; color: var(--text-muted); letter-spacing: 0.5px; display: block; margin-bottom: 4px; }}
        .acc-item .val {{ font-size: 18px; font-weight: 700; }}
        .main-layout {{ display: grid; grid-template-columns: 1.4fr 1fr; gap: 20px; }}
        .card {{ background-color: var(--bg-card); border-radius: 12px; border: 1px solid var(--border); padding: 20px; display: flex; flex-direction: column; }}
        .card-title {{ font-size: 16px; font-weight: 600; margin-bottom: 15px; display: flex; align-items: center; gap: 10px; }}
        table {{ width: 100%; border-collapse: collapse; text-align: left; }}
        th {{ color: var(--text-muted); font-size: 12px; font-weight: 500; padding-bottom: 12px; border-bottom: 1px solid var(--border); }}
        td {{ padding: 12px 0; border-bottom: 1px solid #1f2336; font-size: 14px; }}
        .ticker-name {{ font-weight: 600; }}
        .badge {{ padding: 2px 6px; border-radius: 4px; font-size: 11px; font-weight: bold; background: #22273d; }}
        .pos {{ color: var(--green); }}
        .neg {{ color: var(--red); }}
        .tendency {{ font-family: monospace; letter-spacing: 2px; }}
        .side-panel {{ display: flex; flex-direction: column; gap: 15px; max-height: 520px; overflow-y: auto; padding-right: 5px; }}
        .news-item {{ background: #1c2030; padding: 12px; border-radius: 8px; border-left: 4px solid var(--blue); margin-bottom: 10px; }}
        .news-meta {{ font-size: 11px; color: var(--text-muted); margin-bottom: 4px; }}
        .news-title {{ font-size: 13px; font-weight: 600; margin-bottom: 4px; }}
        .news-summary {{ font-size: 12px; color: var(--text-muted); }}
        .signal-item {{ background: #251b22; padding: 12px; border-radius: 8px; border-left: 4px solid var(--red); margin-bottom: 10px; }}
        .signal-item.buy {{ background: #1b251f; border-left: 4px solid var(--green); }}
        .signal-title {{ font-size: 13px; font-weight: bold; margin-bottom: 4px; text-transform: uppercase; }}
        .historical-view {{ margin-top: 25px; background-color: var(--bg-card); border-radius: 12px; border: 1px solid var(--border); padding: 20px; }}
        .hist-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-top: 15px; }}
        .hist-box {{ background: #1c2030; padding: 15px; border-radius: 8px; font-size: 13px; }}
        .hist-box h4 {{ margin-bottom: 8px; font-size: 14px; color: var(--blue); }}
    </style>
</head>
<body>
    <header>
        <div class="logo-area">
            <h1>QuantFlow Tech Agent Dashboard <span style="color:var(--blue); font-size:14px;">v2.0</span></h1>
            <span>Live Option Flow & Macro Engine — Letztes Update: {timestamp}</span>
        </div>
        <div class="controls-area">
            <button id="refresh-btn" onclick="triggerManualUpdate()" class="btn-refresh">🔄 Jetzt aktualisieren</button>
            <a href="portfolio_log.csv" download class="btn-refresh" style="background-color: #28a745;">📊 CSV Historie</a>
        </div>
    </header>

    <section class="accounting-bar">
        <div class="acc-item"><label>Gesamtwert Depot (Brutto)</label><div class="val">{val_brutto}</div></div>
        <div class="acc-item"><label>Nicht realisierter Gewinn</label><div class="val pos">{val_gain}</div></div>
        <div class="acc-item"><label>Rückstellung KESt (26%)</label><div class="val neg">{val_kest}</div></div>
        <div class="acc-item"><label>Netto-Wert (nach Steuer)</label><div class="val">{val_netto}</div></div>
        <div class="acc-item"><label>Turnaround-Anteil</label><div class="val" style="color:{ta_badge_bg};">{turnaround_weight:.1f}% <span class="badge" style="background:{ta_badge_bg}; color:#0f111a;">{ta_badge}</span></div></div>
    </section>

    <div class="main-layout">
        <div class="card">
            <div class="card-title">📈 Portfolio-Positionen</div>
            <table>
                <thead>
                    <tr>
                        <th>Ticker</th>
                        <th>Sektor</th>
                        <th>Tag %</th>
                        <th>Trend (3T)</th>
                        <th>Woche %</th>
                        <th>Seit Einstieg %</th>
                    </tr>
                </thead>
                <tbody>
{table_rows}                </tbody>
            </table>
        </div>
        <div class="side-panel">
            <div class="card-title">⚡ Auffällige Bewegungen</div>
{signal_html}
        </div>
    </div>

    <div class="historical-view">
        <div class="card-title">🕓 Verlauf</div>
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

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(full_html)

    print("✅ Dashboard erfolgreich aktualisiert: index.html")


if __name__ == "__main__":
    run_agent_update()
