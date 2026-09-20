"""YEDAŞ planlı kesinti API istemcisi."""

from __future__ import annotations

import json
from typing import Any

import requests

from src.config import REQUEST_TIMEOUT, USER_AGENT, YEDAS_API_URL
from src.utils import iso, parse_yedas_datetimes, safe_float


def fetch_yedas_raw() -> dict[str, Any]:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://www.yedas.com/",
    }
    last_error = None
    for attempt in range(3):
        try:
            resp = requests.get(YEDAS_API_URL, headers=headers, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            resp.encoding = resp.apparent_encoding or "utf-8"
            return resp.json()
        except (requests.RequestException, json.JSONDecodeError) as exc:
            last_error = exc
    raise RuntimeError(f"YEDAŞ API okunamadı: {last_error}") from last_error


def normalize_outages(payload: dict[str, Any]) -> list[dict[str, Any]]:
    result = payload.get("result") if isinstance(payload, dict) else None
    data = []
    if isinstance(result, dict):
        data = result.get("data") or []
    elif isinstance(payload, dict):
        data = payload.get("data") or []
    out: list[dict[str, Any]] = []
    if not isinstance(data, list):
        return out
    for item in data:
        if not isinstance(item, dict):
            continue
        yedas_id = str(item.get("id") or item.get("_id") or "")
        if not yedas_id:
            continue
        details = item.get("details") or ""
        start, end = parse_yedas_datetimes(str(details))
        coords = _clean_coords(item.get("coords"))
        if not coords:
            coords = _coords_from_geojson(item.get("geoJson") or item.get("geojson"))
        out.append(
            {
                "yedas_id": yedas_id,
                "title": item.get("title") or "",
                "details": details,
                "start_at": iso(start),
                "end_at": iso(end),
                "address": item.get("address") or [],
                "coords": coords,
                "geojson": item.get("geoJson") or item.get("geojson") or {},
            }
        )
    return out


def _clean_coords(raw) -> list[dict[str, float]]:
    coords: list[dict[str, float]] = []
    if not isinstance(raw, list):
        return coords
    for pt in raw:
        if not isinstance(pt, dict):
            continue
        lat = safe_float(pt.get("latitude") if "latitude" in pt else pt.get("lat"))
        lon = safe_float(pt.get("longitude") if "longitude" in pt else pt.get("lon") or pt.get("lng"))
        if lat is None or lon is None:
            continue
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue
        coords.append({"latitude": lat, "longitude": lon})
    return coords


def _coords_from_geojson(geo) -> list[dict[str, float]]:
    if not isinstance(geo, dict):
        return []
    geom = geo.get("geometry") if "geometry" in geo else geo
    if not isinstance(geom, dict):
        return []
    rings = geom.get("coordinates")
    gtype = geom.get("type")
    ring = None
    if gtype == "Polygon" and rings:
        ring = rings[0]
    elif gtype == "MultiPolygon" and rings:
        ring = rings[0][0]
    if not ring:
        return []
    coords = []
    for pair in ring:
        if not isinstance(pair, (list, tuple)) or len(pair) < 2:
            continue
        lon, lat = safe_float(pair[0]), safe_float(pair[1])
        if lat is None or lon is None:
            continue
        coords.append({"latitude": lat, "longitude": lon})
    return coords
