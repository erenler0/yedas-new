"""OSRM gerçek sürüş mesafesi / süresi."""

from __future__ import annotations

import time
from typing import Any, Optional

import requests

from src.config import OSRM_BASE_URL, OSRM_SLEEP_SEC, REQUEST_TIMEOUT, USER_AGENT
from src.utils import haversine_km


def driving_route(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
    overview: str = "false",
) -> dict[str, Any]:
    url = (
        f"{OSRM_BASE_URL}/route/v1/driving/"
        f"{lon1:.6f},{lat1:.6f};{lon2:.6f},{lat2:.6f}"
    )
    params = {"overview": overview, "geometries": "geojson", "alternatives": "false", "steps": "false"}
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    last_exc = None
    for attempt in range(3):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 429:
                time.sleep(1.5 * (attempt + 1))
                continue
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") != "Ok" or not data.get("routes"):
                raise RuntimeError(data.get("message") or data.get("code") or "OSRM hata")
            route = data["routes"][0]
            km = float(route["distance"]) / 1000.0
            minutes = float(route["duration"]) / 60.0
            geom = route.get("geometry")
            time.sleep(OSRM_SLEEP_SEC)
            return {
                "distance_km": round(km, 2),
                "duration_min": round(minutes, 1),
                "geometry": geom,
                "source": "osrm",
            }
        except Exception as exc:
            last_exc = exc
            time.sleep(0.6 * (attempt + 1))
    km = haversine_km(lat1, lon1, lat2, lon2)
    return {
        "distance_km": round(km, 2),
        "duration_min": round((km / 50.0) * 60.0, 1),
        "geometry": None,
        "source": "haversine_fallback",
        "error": str(last_exc) if last_exc else None,
    }


def nearest_district(site: dict, districts: list[dict]) -> Optional[dict]:
    if not districts:
        return None
    best = None
    best_d = 1e18
    for d in districts:
        try:
            dist = haversine_km(float(site["lat"]), float(site["lon"]), float(d["lat"]), float(d["lon"]))
        except Exception:
            continue
        if dist < best_d:
            best_d = dist
            best = d
    return best
