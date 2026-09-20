"""Uygulama sabitleri ve relatif yollar."""

from __future__ import annotations

import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
DB_PATH = DATA_DIR / "yedas_gsm.db"

YEDAS_API_URL = "https://www.yedas.com/api/planli-kesinti-harita"
OSRM_BASE_URL = os.environ.get("OSRM_BASE_URL", "https://router.project-osrm.org")
NOMINATIM_URL = "https://nominatim.openstreetmap.org"

USER_AGENT = os.environ.get(
    "APP_USER_AGENT",
    "yedas-gsm-kesinti/1.0 (Streamlit; planned-outage matching; contact: local-admin)",
)

NOMINATIM_SLEEP_SEC = 1.0
NOMINATIM_TIMEOUT = 8
OSRM_SLEEP_SEC = 0.25
YEDAS_CACHE_TTL = 300
REQUEST_TIMEOUT = 30

NEARBY_KM = 15.0
ADMIN_PASSWORD_DEFAULT = "admin5555"

PROVINCES = ("Samsun", "Sinop", "Ordu", "Amasya", "Tokat", "Çorum")

EXCEL_COLUMNS = {
    "kml": ("KML Dosyası", "KML Dosyasi", "kml"),
    "name": ("Placemark Adı", "Placemark Adi", "Saha Adı", "Saha Adi", "name"),
    "description": ("Açıklama", "Aciklama", "description"),
    "lat": ("Latitude", "Enlem", "lat"),
    "lon": ("Longitude", "Boylam", "lon", "lng"),
    "alt": ("Altitude", "Yükseklik", "Yukseklik"),
    "raw": ("Koordinat (Ham)", "Koordinat", "raw"),
}


def admin_password() -> str:
    try:
        import streamlit as st

        if "ADMIN_PASSWORD" in st.secrets:
            return str(st.secrets["ADMIN_PASSWORD"])
    except Exception:
        pass
    return os.environ.get("ADMIN_PASSWORD", ADMIN_PASSWORD_DEFAULT)


def ensure_data_dir() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR
