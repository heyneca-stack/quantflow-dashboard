"""
Konfigurations-Modul — Grundlage für das "Parameter-Modal" aus dem
Arbeitspapier (Abschnitt 6). Für Phase 1 gibt es noch keine Bedienoberfläche;
die aktive Konfiguration liegt bereits als benannte JSON-Datei unter
configs/<Name>.json, und active_config.json zeigt auf den Namen der gerade
aktiven Konfiguration. run_agent_update() liest beim Start immer nur die
aktive Konfiguration ein — ein künftiger Strategiewechsel bedeutet dann
"andere Konfiguration aktivieren", nicht "Code ändern" (siehe Abschnitt 6,
letzter Absatz).

DEFAULT_CONFIG entspricht den in Abschnitt 7 vorgeschlagenen und vom Nutzer
bestätigten Standardwerten:
  - Krypto/Digital-Asset bewusst wählbar (Gewicht 1.0 setzen), aber
    standardmäßig deaktiviert (Gewicht 0.0).
  - Korb-Obergrenze 180 (Mitte des vorgeschlagenen 150-200-Korridors).
  - Small-Cap-Universum (Russell-2000-Proxy) ist Phase 4 und hier noch aus.
"""

import json
import os

CONFIG_DIR = "configs"
ACTIVE_CONFIG_POINTER_FILE = "active_config.json"
DEFAULT_CONFIG_NAME = "Standard"

DEFAULT_CONFIG = {
    "universes": {
        "dow": True,
        "nasdaq100": True,
        "sp500": True,
        "russell2000_small_cap": False,  # Phase 4, Arbeitspapier Abschnitt 8
    },
    "sectors": {
        "Energie": 1.0,
        "Grundstoffe": 1.0,
        "Industrie": 1.0,
        "Nicht-Basiskonsumgüter": 1.0,
        "Basiskonsumgüter": 1.0,
        "Gesundheitswesen": 1.0,
        "Finanzwerte": 1.0,
        "Informationstechnologie": 1.0,
        "Kommunikationsdienste": 1.0,
        "Versorger": 1.0,
        "Immobilien": 1.0,
        "Sektor unbekannt": 1.0,
        "Krypto/Digital-Asset": 0.0,  # bewusst aus, siehe Abschnitt 4.2 & 7
    },
    "max_basket_size": 180,
}


def _config_path(name):
    return os.path.join(CONFIG_DIR, f"{name}.json")


def ensure_default_config_exists():
    os.makedirs(CONFIG_DIR, exist_ok=True)
    path = _config_path(DEFAULT_CONFIG_NAME)
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, ensure_ascii=False, indent=2)
    if not os.path.exists(ACTIVE_CONFIG_POINTER_FILE):
        with open(ACTIVE_CONFIG_POINTER_FILE, "w", encoding="utf-8") as f:
            json.dump({"active": DEFAULT_CONFIG_NAME}, f, ensure_ascii=False, indent=2)


def load_active_config():
    """Liest, welche benannte Konfiguration aktiv ist, und lädt sie. Fällt bei
    fehlenden oder kaputten Dateien defensiv auf DEFAULT_CONFIG zurück, damit
    ein Lauf nie allein wegen einer fehlenden Konfigurationsdatei scheitert."""
    ensure_default_config_exists()
    try:
        with open(ACTIVE_CONFIG_POINTER_FILE, "r", encoding="utf-8") as f:
            active_name = json.load(f).get("active", DEFAULT_CONFIG_NAME)
    except Exception as e:
        print(f"⚠️ Konnte {ACTIVE_CONFIG_POINTER_FILE} nicht lesen ({e}), nutze '{DEFAULT_CONFIG_NAME}'.")
        active_name = DEFAULT_CONFIG_NAME

    path = _config_path(active_name)
    try:
        with open(path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        print(f"   Aktive Korb-Konfiguration: '{active_name}'")
        return cfg
    except Exception as e:
        print(f"⚠️ Konnte Konfiguration '{active_name}' nicht laden ({e}), nutze eingebauten Standard.")
        return DEFAULT_CONFIG
