"""Tarih, metin ve mesafe yardımcıları."""

from __future__ import annotations

import math
import re
import unicodedata
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

TR_TZ = ZoneInfo("Europe/Istanbul")
DATE_RE = re.compile(r"\d{2}\.\d{2}\.\d{4}\s+\d{2}:\d{2}:\d{2}")

_TR_MAP = str.maketrans(
    {
        "İ": "i",
        "I": "i",
        "ı": "i",
        "Ş": "s",
        "ş": "s",
        "Ğ": "g",
        "ğ": "g",
        "Ü": "u",
        "ü": "u",
        "Ö": "o",
        "ö": "o",
        "Ç": "c",
        "ç": "c",
    }
)


def now_tr() -> datetime:
    return datetime.now(TR_TZ)


def parse_yedas_datetimes(details: str | None) -> tuple[Optional[datetime], Optional[datetime]]:
    found = DATE_RE.findall(details or "")
    start = _parse_one(found[0]) if found else None
    end = _parse_one(found[1]) if len(found) > 1 else None
    return start, end


def _parse_one(value: str) -> Optional[datetime]:
    try:
        dt = datetime.strptime(value.strip(), "%d.%m.%Y %H:%M:%S")
        return dt.replace(tzinfo=TR_TZ)
    except ValueError:
        return None


def parse_user_dt(value) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=TR_TZ)
        return value.astimezone(TR_TZ)
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%d.%m.%Y %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=TR_TZ)
        except ValueError:
            continue
    return None


def iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TR_TZ)
    return dt.astimezone(TR_TZ).isoformat(timespec="seconds")


def from_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TR_TZ)
        return dt.astimezone(TR_TZ)
    except ValueError:
        return None


def fmt_dt(dt: Optional[datetime]) -> str:
    if dt is None:
        return "—"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TR_TZ)
    return dt.astimezone(TR_TZ).strftime("%d.%m.%Y %H:%M")


def duration_hours(start: Optional[datetime], end: Optional[datetime]) -> Optional[float]:
    if not start or not end:
        return None
    seconds = (end - start).total_seconds()
    if seconds < 0:
        return None
    return round(seconds / 3600.0, 2)


def normalize_tr(text: Optional[str]) -> str:
    if not text:
        return ""
    s = unicodedata.normalize("NFKC", str(text)).translate(_TR_MAP).lower()
    s = re.sub(r"\b(mah(allesi)?|mh\.?|ilcesi|ilce|ilçe)\b", " ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def names_match(a: Optional[str], b: Optional[str]) -> bool:
    na, nb = normalize_tr(a), normalize_tr(b)
    if not na or not nb:
        return False
    return na == nb or na in nb or nb in na


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(min(1.0, a)))


def safe_float(value) -> Optional[float]:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    text = str(value).strip().replace(",", ".")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None
