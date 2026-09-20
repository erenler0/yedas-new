"""Nominatim reverse geocoding.

Nominatim public sunucusunun hız/rate-limit kuralları nedeniyle paralel istek
atılmaz. Asıl optimizasyon: aynı koordinatı ikinci kez asla sorgulamamak,
başarısız isteği tüm senkronu durdurmamak ve tek bir geocoder instance kullanmaktır.
"""
from __future__ import annotations

import time
from typing import Optional

from geopy.geocoders import Nominatim

from src.config import NOMINATIM_SLEEP_SEC, NOMINATIM_TIMEOUT, USER_AGENT


def _geocoder() -> Nominatim:
    return Nominatim(user_agent=USER_AGENT, timeout=NOMINATIM_TIMEOUT)


def _parse_location(location) -> dict[str, Optional[str]]:
    addr = (location.raw.get("address") if location else {}) or {}
    il = addr.get("province") or addr.get("state") or addr.get("region")
    ilce = addr.get("town") or addr.get("county") or addr.get("city_district") or addr.get("municipality") or addr.get("city")
    if ilce and il and str(ilce).strip().lower() == str(il).strip().lower():
        ilce = addr.get("county") or addr.get("town") or ilce
    mahalle = addr.get("suburb") or addr.get("neighbourhood") or addr.get("neighborhood") or addr.get("village") or addr.get("quarter") or addr.get("hamlet")
    return {
        "il": _clean_place(il),
        "ilce": _clean_place(ilce),
        "mahalle": _clean_place(mahalle),
        "raw": location.address if location else None,
    }


def reverse_one(lat: float, lon: float) -> dict[str, Optional[str]]:
    geolocator = _geocoder()
    try:
        return _parse_location(geolocator.reverse((lat, lon), language="tr", exactly_one=True, addressdetails=True))
    except Exception:
        return {"il": None, "ilce": None, "mahalle": None, "raw": None}


def reverse_many(points: list[tuple[int, float, float]], progress_cb=None) -> dict[int, dict]:
    """points: (site_id, lat, lon). Tek process, tek geocoder, kontrollü hız."""
    geolocator = _geocoder()
    out: dict[int, dict] = {}
    total = len(points)
    last_request = 0.0
    for i, (key, lat, lon) in enumerate(points, start=1):
        # Public Nominatim için güvenli aralık. Network yanıtı zaten hızlıysa yalnızca kalan süre beklenir.
        wait = NOMINATIM_SLEEP_SEC - (time.monotonic() - last_request)
        if wait > 0:
            time.sleep(wait)
        try:
            last_request = time.monotonic()
            loc = geolocator.reverse(
                (float(lat), float(lon)), language="tr", exactly_one=True,
                addressdetails=True, zoom=18,
            )
            out[key] = _parse_location(loc)
        except Exception as exc:
            out[key] = {"il": None, "ilce": None, "mahalle": None, "raw": f"hata: {exc}"}
        if progress_cb:
            progress_cb(i, total, key)
    return out


def _clean_place(value) -> Optional[str]:
    if not value:
        return None
    text = str(value).strip()
    for suffix in (" İli", " ili", " Province"):
        if text.endswith(suffix):
            text = text[: -len(suffix)].strip()
    return text or None
