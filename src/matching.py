"""Hızlandırılmış Shapely Point-in-Polygon eşleştirme.

STRtree ile 1300+ saha için her poligonda tüm sahaları taramak yerine
önce mekansal adayları bulur. Polygon sınırı da ``covers`` ile dahil edilir.
"""
from __future__ import annotations

from typing import Any, Optional

from shapely.geometry import MultiPolygon, Point, Polygon, box, shape
from shapely.strtree import STRtree
from shapely.validation import make_valid

from src.config import NEARBY_KM
from src.utils import haversine_km, names_match, normalize_tr, safe_float


def build_polygon(outage: dict[str, Any]) -> Optional[Polygon | MultiPolygon]:
    coords = outage.get("coords") or []
    pts: list[tuple[float, float]] = []
    try:
        for c in coords:
            if not isinstance(c, dict):
                continue
            lat = safe_float(c.get("latitude") if "latitude" in c else c.get("lat"))
            lon = safe_float(c.get("longitude") if "longitude" in c else c.get("lon") or c.get("lng"))
            if lat is None or lon is None:
                continue
            pts.append((lon, lat))
        if len(pts) >= 3:
            if pts[0] != pts[-1]:
                pts.append(pts[0])
            return _repair(Polygon(pts))
        geo = outage.get("geojson") or {}
        geom = geo.get("geometry") if isinstance(geo, dict) and "geometry" in geo else geo
        if isinstance(geom, dict) and geom.get("type") and geom.get("coordinates"):
            return _repair(shape(geom))
    except Exception:
        return None
    return None


def _repair(geom):
    try:
        if geom is None or geom.is_empty:
            return None
        if not geom.is_valid:
            geom = make_valid(geom)
        if geom.geom_type in ("Polygon", "MultiPolygon"):
            return geom
        if geom.geom_type == "GeometryCollection":
            polys = [g for g in geom.geoms if g.geom_type in ("Polygon", "MultiPolygon") and not g.is_empty]
            if not polys:
                return None
            merged = polys[0]
            for g in polys[1:]:
                merged = merged.union(g)
            return merged if merged.geom_type in ("Polygon", "MultiPolygon") else None
        buffered = geom.buffer(0)
        return buffered if buffered.geom_type in ("Polygon", "MultiPolygon") and not buffered.is_empty else None
    except Exception:
        return None


def site_point(site: dict[str, Any]) -> Optional[Point]:
    try:
        lat, lon = safe_float(site.get("lat")), safe_float(site.get("lon"))
        if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return None
        return Point(float(lon), float(lat))
    except Exception:
        return None


def _address_match(outage: dict[str, Any], site: dict[str, Any]) -> bool:
    addresses = outage.get("address") or []
    if not isinstance(addresses, list):
        return False
    for addr in addresses:
        if not isinstance(addr, dict):
            continue
        city = addr.get("city_name") or addr.get("city")
        district = addr.get("district_name") or addr.get("district")
        mah = addr.get("mah_name") or addr.get("neighborhood")
        il_ok = names_match(site.get("il"), city) if city else False
        ilce_ok = names_match(site.get("ilce"), district) if district else False
        mah_ok = names_match(site.get("mahalle"), mah) if mah else False
        if il_ok and (ilce_ok or mah_ok):
            return True
        if ilce_ok and mah_ok:
            return True
    return False


def _address_index(sites: list[dict[str, Any]]) -> dict[str, set[int]]:
    idx: dict[str, set[int]] = {}
    for i, s in enumerate(sites):
        for field in ("il", "ilce", "mahalle"):
            value = normalize_tr(s.get(field))
            if value:
                idx.setdefault(f"{field}:{value}", set()).add(i)
    return idx


def _address_candidates(outage: dict[str, Any], index: dict[str, set[int]]) -> set[int]:
    candidates: set[int] = set()
    for addr in outage.get("address") or []:
        if not isinstance(addr, dict):
            continue
        vals = {
            "il": normalize_tr(addr.get("city_name") or addr.get("city")),
            "ilce": normalize_tr(addr.get("district_name") or addr.get("district")),
            "mahalle": normalize_tr(addr.get("mah_name") or addr.get("neighborhood")),
        }
        for field, value in vals.items():
            if value:
                candidates.update(index.get(f"{field}:{value}", set()))
    return candidates


def _nearby_candidates(tree: STRtree, centroid: Point) -> list[int]:
    """15 km için yaklaşık derece kutusu; son mesafe Haversine ile doğrulanır."""
    try:
        lat = centroid.y
        lat_delta = NEARBY_KM / 110.574
        lon_delta = NEARBY_KM / max(111.320 * abs(__import__("math").cos(__import__("math").radians(lat))), 1e-6)
        ids = tree.query(box(centroid.x - lon_delta, lat - lat_delta, centroid.x + lon_delta, lat + lat_delta))
        return [int(i) for i in ids]
    except Exception:
        return []


def match_sites(outages: list[dict[str, Any]], sites: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Her kesinti için etkilenen ve 15 km içindeki yakın sahaları döndürür."""
    valid_sites: list[dict[str, Any]] = []
    points: list[Point] = []
    for site in sites:
        pt = site_point(site)
        if pt is not None:
            valid_sites.append(site)
            points.append(pt)
    tree = STRtree(points) if points else None
    addr_idx = _address_index(valid_sites)

    results: list[dict[str, Any]] = []
    for outage in outages:
        geom = build_polygon(outage)
        affected_idx: set[int] = set()
        if geom is not None and tree is not None:
            try:
                affected_idx = {int(i) for i in tree.query(geom, predicate="covers")}
            except Exception:
                try:
                    affected_idx = {int(i) for i in tree.query(geom) if geom.covers(points[int(i)])}
                except Exception:
                    affected_idx = set()

        # Adres fallback yalnızca spatial eşleşme bulunmayan adres adaylarında çalışır.
        address_candidates = _address_candidates(outage, addr_idx)
        for i in address_candidates:
            if i not in affected_idx and _address_match(outage, valid_sites[i]):
                affected_idx.add(i)

        affected = []
        for i in sorted(affected_idx):
            rec = dict(valid_sites[i])
            rec["match_type"] = "polygon" if (geom is not None and tree is not None and geom.covers(points[i])) else "address"
            affected.append(rec)

        nearby = []
        if geom is not None and tree is not None:
            try:
                centroid = geom.representative_point()
                for i in _nearby_candidates(tree, centroid):
                    if i in affected_idx:
                        continue
                    s = valid_sites[i]
                    dist = haversine_km(float(s["lat"]), float(s["lon"]), centroid.y, centroid.x)
                    if dist <= NEARBY_KM:
                        rec = dict(s)
                        rec["nearby_km"] = round(dist, 2)
                        nearby.append(rec)
            except Exception:
                pass
        nearby.sort(key=lambda r: r.get("nearby_km", 9999))
        item = dict(outage)
        item["polygon"] = geom
        item["affected"] = affected
        item["nearby"] = nearby[:80]
        results.append(item)
    return results
