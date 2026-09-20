"""İş kuralları ve performans katmanı."""
from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from typing import Any, Optional

import streamlit as st

from src import db
from src.config import YEDAS_CACHE_TTL
from src.district_seed import DISTRICT_CENTERS
from src.excel_io import read_sites_excel
from src.geocoding import reverse_many
from src.matching import match_sites
from src.osrm_client import driving_route, nearest_district
from src.utils import from_iso, normalize_tr, now_tr
from src.yedas_api import fetch_yedas_raw, normalize_outages


@st.cache_data(ttl=YEDAS_CACHE_TTL, show_spinner="YEDAŞ planlı kesintiler güncelleniyor…")
def load_yedas_cached() -> list[dict[str, Any]]:
    return normalize_outages(fetch_yedas_raw())


@st.cache_data(ttl=60, show_spinner=False)
def load_sites_cached() -> list[dict[str, Any]]:
    return db.list_sites()


@st.cache_data(ttl=60, show_spinner=False)
def load_districts_cached() -> list[dict[str, Any]]:
    return db.list_districts()


@st.cache_data(ttl=60, show_spinner=False)
def load_matches_cached() -> list[dict[str, Any]]:
    return db.matches_for_analysis()


@st.cache_data(ttl=30, show_spinner=False)
def load_faults_cached() -> list[dict[str, Any]]:
    return db.list_faults()


def invalidate_site_caches() -> None:
    load_sites_cached.clear()
    load_districts_cached.clear()


def invalidate_history_caches() -> None:
    load_matches_cached.clear()
    load_faults_cached.clear()


def _match_payload(outages: list[dict[str, Any]], sites: list[dict[str, Any]]) -> str:
    # Streamlit'in nested dict hashing maliyetini azaltmak için deterministik JSON kullanılır.
    return json.dumps({"outages": outages, "sites": sites}, ensure_ascii=False, separators=(",", ":"), sort_keys=True, default=str)


@st.cache_data(ttl=300, max_entries=8, show_spinner="Kesintiler sahalarla eşleştiriliyor…")
def _match_cached(payload: str) -> list[dict[str, Any]]:
    obj = json.loads(payload)
    return match_sites(obj["outages"], obj["sites"])


def persist_and_match(outages: list[dict[str, Any]], sites: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not outages or not sites:
        return []
    payload = _match_payload(outages, sites)
    matched = _match_cached(payload)

    # Aynı Streamlit oturumunda menü/radio değişiminde SQLite'a tekrar tekrar yazma.
    persist_key = hashlib.sha1(payload.encode("utf-8")).hexdigest()
    if st.session_state.get("_last_persist_key") != persist_key:
        db.upsert_outages_batch(matched)
        match_rows = {
            item["yedas_id"]: [(int(s["id"]), s.get("match_type") or "polygon") for s in item.get("affected") or []]
            for item in matched
        }
        db.replace_matches_batch(match_rows)
        st.session_state["_last_persist_key"] = persist_key
        load_matches_cached.clear()
    return matched


def filter_window(matched: list[dict[str, Any]], days: int) -> list[dict[str, Any]]:
    start = now_tr().replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=days)
    out = []
    for item in matched:
        s = item.get("start_dt") or from_iso(item.get("start_at"))
        e = item.get("end_dt") or from_iso(item.get("end_at"))
        if s is None and e is None:
            out.append(item)
            continue
        s = s or e
        e = e or s
        if s < end and e >= start:
            out.append(item)
    return out


def _coord_key(lat: float, lon: float) -> str:
    return f"{float(lat):.6f}|{float(lon):.6f}"


def sync_sites_from_excel(uploaded, progress) -> dict[str, Any]:
    """Excel senkronunu tek transaction + kalıcı geocode cache ile yapar."""
    df = read_sites_excel(uploaded)
    incoming = df.to_dict("records")
    incoming_keys = [r["identity_key"] for r in incoming]
    existing_rows = db.list_sites()
    existing_keys = {r["identity_key"] for r in existing_rows}
    existing_by_coord = {
        _coord_key(r["lat"], r["lon"]): r
        for r in existing_rows
        if r.get("il") or r.get("ilce") or r.get("mahalle")
    }

    added_names = [r["name"] for r in incoming if r["identity_key"] not in existing_keys]
    updated_names = [r["name"] for r in incoming if r["identity_key"] in existing_keys]
    removed_names = db.delete_sites_not_in(incoming_keys)

    # Aynı koordinat daha önce başka isimle kayıtlıysa Nominatim'e tekrar gitme.
    for rec in incoming:
        coord = _coord_key(rec["lat"], rec["lon"])
        old = existing_by_coord.get(coord)
        if old:
            rec["il"] = old.get("il")
            rec["ilce"] = old.get("ilce")
            rec["mahalle"] = old.get("mahalle")
            rec["geocoded_at"] = old.get("geocoded_at")

    ids = db.bulk_upsert_sites(incoming)

    # Kalıcı koordinat cache: yeniden yüklenen/ismi değişen sahalarda tekrar geocoding yok.
    coord_keys = [_coord_key(r["lat"], r["lon"]) for r in incoming]
    cache = db.get_geocode_cache(coord_keys)
    geocode_jobs: list[tuple[int, float, float]] = []
    addresses_to_apply: dict[int, dict[str, Any]] = {}
    cache_rows_to_save: list[dict[str, Any]] = []
    site_by_id = {ids[r["identity_key"]]: r for r in incoming}
    for rec in incoming:
        sid = ids[rec["identity_key"]]
        ck = _coord_key(rec["lat"], rec["lon"])
        cached = cache.get(ck)
        if cached:
            addresses_to_apply[sid] = cached
        elif rec.get("il") or rec.get("ilce") or rec.get("mahalle"):
            addresses_to_apply[sid] = rec
            cache_rows_to_save.append({
                "coord_key": ck, "lat": rec["lat"], "lon": rec["lon"],
                "il": rec.get("il"), "ilce": rec.get("ilce"), "mahalle": rec.get("mahalle"), "raw": None,
            })
        else:
            geocode_jobs.append((sid, float(rec["lat"]), float(rec["lon"])))

    # Yeni koordinatları Nominatim ile tek geocoder üzerinden işler.
    geocoded = 0
    if geocode_jobs:
        bar = progress.progress(0.0, text=f"Adres çözülüyor 0/{len(geocode_jobs)}…") if progress else None

        def cb(i, total, _key):
            if bar:
                bar.progress(i / total, text=f"Adres çözülüyor {i}/{total}")

        results = reverse_many(geocode_jobs, progress_cb=cb)
        cache_rows = []
        for sid, addr in results.items():
            addresses_to_apply[int(sid)] = addr
            site = site_by_id.get(sid)
            if site and (addr.get("il") or addr.get("ilce") or addr.get("mahalle")):
                cache_rows.append({
                    "coord_key": _coord_key(site["lat"], site["lon"]),
                    "lat": site["lat"], "lon": site["lon"], **addr,
                })
                geocoded += 1
        cache_rows_to_save.extend(cache_rows)
        if bar:
            bar.progress(1.0, text=f"Reverse geocoding tamamlandı: {geocoded} yeni sonuç")

    if cache_rows_to_save:
        db.save_geocode_cache(cache_rows_to_save)
    db.set_site_addresses_bulk(addresses_to_apply)
    assign_nearest_districts()
    db.save_sync_run(added_names, removed_names, sorted(set(updated_names) - set(added_names)), geocoded)
    invalidate_site_caches()
    invalidate_history_caches()
    return {
        "added": added_names,
        "removed": removed_names,
        "updated": sorted(set(updated_names) - set(added_names)),
        "geocoded": geocoded,
        "total": db.site_count(),
    }


def seed_districts() -> int:
    n = 0
    for d in DISTRICT_CENTERS:
        db.add_district(d["name"], d["province"], d["lat"], d["lon"])
        n += 1
    assign_nearest_districts()
    invalidate_site_caches()
    return n


def assign_nearest_districts() -> None:
    districts = db.list_districts()
    if not districts:
        return
    assignments: list[tuple[int, int]] = []
    for site in db.list_sites():
        if site.get("assignment_override"):
            continue
        nearest = nearest_district(site, districts)
        if nearest and site.get("district_center_id") != nearest["id"]:
            assignments.append((int(site["id"]), int(nearest["id"])))
    db.assign_districts_bulk(assignments)


def enrich_sites_with_routes(sites: list[dict[str, Any]], compute_missing: bool = False, progress=None) -> list[dict[str, Any]]:
    districts = {d["id"]: d for d in db.list_districts()}
    cached_routes = db.get_osrm_bulk([int(s["id"]) for s in sites])
    missing: list[tuple[dict, dict]] = []
    enriched: list[dict[str, Any]] = []

    for s in sites:
        rec = dict(s)
        dc_id = s.get("district_center_id")
        dc = districts.get(dc_id) if dc_id else None
        rec["district_name"] = f"{dc['province']} / {dc['name']}" if dc else None
        rec["district_lat"] = dc["lat"] if dc else None
        rec["district_lon"] = dc["lon"] if dc else None
        cached = cached_routes.get((int(s["id"]), int(dc_id))) if dc_id else None
        if cached:
            rec["distance_km"] = cached.get("distance_km")
            rec["duration_min"] = cached.get("duration_min")
            rec["route_source"] = cached.get("source")
            rec["route_geometry"] = cached.get("geometry_json")
        elif dc and compute_missing:
            missing.append((s, dc))
        enriched.append(rec)

    route_rows = []
    total = len(missing)
    for i, (s, dc) in enumerate(missing, start=1):
        if progress:
            progress.progress(i / total, text=f"OSRM rota {i}/{total}: {s.get('name')}")
        result = driving_route(float(s["lat"]), float(s["lon"]), float(dc["lat"]), float(dc["lon"]), overview="false")
        route_rows.append({
            "site_id": int(s["id"]), "district_id": int(dc["id"]),
            "distance_km": result["distance_km"], "duration_min": result["duration_min"],
            "geometry": result.get("geometry"), "source": result["source"],
        })
        for rec in enriched:
            if rec["id"] == s["id"]:
                rec["distance_km"] = result["distance_km"]
                rec["duration_min"] = result["duration_min"]
                rec["route_source"] = result["source"]
                break
    db.save_osrm_bulk(route_rows)
    return enriched


def route_geometry_for(site: dict[str, Any]) -> Optional[dict]:
    dc_id = site.get("district_center_id")
    if not dc_id:
        return None
    cached = db.get_osrm(int(site["id"]), int(dc_id))
    dc = db.get_district(int(dc_id))
    if not dc:
        return None
    if cached and cached.get("geometry_json"):
        try:
            return json.loads(cached["geometry_json"])
        except Exception:
            pass
    result = driving_route(float(site["lat"]), float(site["lon"]), float(dc["lat"]), float(dc["lon"]), overview="full")
    db.save_osrm(int(site["id"]), int(dc["id"]), result["distance_km"], result["duration_min"], result.get("geometry"), result["source"])
    return result.get("geometry")
