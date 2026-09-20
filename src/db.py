"""SQLite veri erişimi.

Performans notu:
- Tek tek 1300 kez bağlantı açmak yerine bulk işlemler kullanılır.
- WAL + NORMAL synchronous ile Streamlit ortamındaki kısa sorgular hızlandırılır.
- Geocoding ve OSRM sonuçları kalıcı olarak önbelleklenir.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from typing import Any, Iterator, Optional

from src.config import DB_PATH, ensure_data_dir
from src.utils import iso, now_tr

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS sites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kml_file TEXT,
    name TEXT NOT NULL,
    description TEXT,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    altitude REAL,
    raw_coords TEXT,
    il TEXT,
    ilce TEXT,
    mahalle TEXT,
    district_center_id INTEGER,
    assignment_override INTEGER NOT NULL DEFAULT 0,
    identity_key TEXT NOT NULL UNIQUE,
    geocoded_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (district_center_id) REFERENCES district_centers(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS district_centers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    province TEXT NOT NULL,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(province, name)
);

CREATE TABLE IF NOT EXISTS osrm_cache (
    site_id INTEGER NOT NULL,
    district_center_id INTEGER NOT NULL,
    distance_km REAL,
    duration_min REAL,
    geometry_json TEXT,
    source TEXT NOT NULL DEFAULT 'osrm',
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (site_id, district_center_id),
    FOREIGN KEY (site_id) REFERENCES sites(id) ON DELETE CASCADE,
    FOREIGN KEY (district_center_id) REFERENCES district_centers(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS geocode_cache (
    coord_key TEXT PRIMARY KEY,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    il TEXT,
    ilce TEXT,
    mahalle TEXT,
    raw TEXT,
    fetched_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS outages (
    yedas_id TEXT PRIMARY KEY,
    title TEXT,
    details TEXT,
    start_at TEXT,
    end_at TEXT,
    address_json TEXT,
    coords_json TEXT,
    geojson_json TEXT,
    last_seen_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS outage_matches (
    yedas_id TEXT NOT NULL,
    site_id INTEGER NOT NULL,
    match_type TEXT NOT NULL,
    snapshot_at TEXT NOT NULL,
    PRIMARY KEY (yedas_id, site_id),
    FOREIGN KEY (yedas_id) REFERENCES outages(yedas_id) ON DELETE CASCADE,
    FOREIGN KEY (site_id) REFERENCES sites(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS fault_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id INTEGER NOT NULL,
    mains_at TEXT NOT NULL,
    down_at TEXT NOT NULL,
    restored_at TEXT,
    backup_minutes REAL,
    outage_minutes REAL,
    comment TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (site_id) REFERENCES sites(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS sync_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    added_json TEXT NOT NULL,
    removed_json TEXT NOT NULL,
    updated_json TEXT NOT NULL,
    geocoded_count INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_sites_il ON sites(il, ilce);
CREATE INDEX IF NOT EXISTS idx_sites_coords ON sites(lat, lon);
CREATE INDEX IF NOT EXISTS idx_matches_site ON outage_matches(site_id);
CREATE INDEX IF NOT EXISTS idx_matches_yedas ON outage_matches(yedas_id);
CREATE INDEX IF NOT EXISTS idx_outages_start ON outages(start_at);
CREATE INDEX IF NOT EXISTS idx_faults_site ON fault_events(site_id);
"""


def _configure_connection(conn: sqlite3.Connection) -> None:
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA temp_store = MEMORY")
    conn.execute("PRAGMA cache_size = -20000")


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    ensure_data_dir()
    conn = sqlite3.connect(str(DB_PATH), timeout=30, check_same_thread=False)
    _configure_connection(conn)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA)


def row_to_dict(row: sqlite3.Row | None) -> Optional[dict[str, Any]]:
    return {k: row[k] for k in row.keys()} if row is not None else None


def fetchall(sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    with connect() as conn:
        return [row_to_dict(r) for r in conn.execute(sql, params).fetchall()]


def fetchone(sql: str, params: tuple = ()) -> Optional[dict[str, Any]]:
    with connect() as conn:
        return row_to_dict(conn.execute(sql, params).fetchone())


def execute(sql: str, params: tuple = ()) -> int:
    with connect() as conn:
        cur = conn.execute(sql, params)
        return int(cur.lastrowid or 0)


def executemany(sql: str, seq: list[tuple]) -> None:
    with connect() as conn:
        conn.executemany(sql, seq)


# ----- sites -----

def site_count() -> int:
    row = fetchone("SELECT COUNT(*) AS c FROM sites")
    return int(row["c"]) if row else 0


def list_sites(where: str = "", params: tuple = ()) -> list[dict[str, Any]]:
    sql = "SELECT * FROM sites"
    if where:
        sql += " WHERE " + where
    sql += " ORDER BY name COLLATE NOCASE"
    return fetchall(sql, params)


def get_site(site_id: int) -> Optional[dict[str, Any]]:
    return fetchone("SELECT * FROM sites WHERE id = ?", (site_id,))


def list_identity_keys() -> set[str]:
    return {r["identity_key"] for r in fetchall("SELECT identity_key FROM sites")}


def bulk_upsert_sites(records: list[dict[str, Any]]) -> dict[str, int]:
    """1300 sahayı tek SQLite transaction'ında upsert eder ve identity -> id döndürür."""
    if not records:
        return {}
    now = iso(now_tr())
    sql = """
    INSERT INTO sites (
        kml_file, name, description, lat, lon, altitude, raw_coords,
        il, ilce, mahalle, district_center_id, assignment_override,
        identity_key, geocoded_at, created_at, updated_at
    ) VALUES (?,?,?,?,?,?,?,?,?,?,NULL,0,?,?,?,?)
    ON CONFLICT(identity_key) DO UPDATE SET
        kml_file=excluded.kml_file,
        name=excluded.name,
        description=excluded.description,
        lat=excluded.lat,
        lon=excluded.lon,
        altitude=excluded.altitude,
        raw_coords=excluded.raw_coords,
        il=COALESCE(excluded.il, sites.il),
        ilce=COALESCE(excluded.ilce, sites.ilce),
        mahalle=COALESCE(excluded.mahalle, sites.mahalle),
        geocoded_at=COALESCE(excluded.geocoded_at, sites.geocoded_at),
        updated_at=excluded.updated_at
    """
    rows = []
    for p in records:
        rows.append((
            p.get("kml_file"), p["name"], p.get("description"), p["lat"], p["lon"],
            p.get("altitude"), p.get("raw_coords"), p.get("il"), p.get("ilce"),
            p.get("mahalle"), p["identity_key"], p.get("geocoded_at"), now, now,
        ))
    keys = [p["identity_key"] for p in records]
    result_rows = []
    with connect() as conn:
        conn.executemany(sql, rows)
        for i in range(0, len(keys), 900):
            chunk = keys[i:i + 900]
            placeholders = ",".join("?" for _ in chunk)
            result_rows.extend(conn.execute(
                f"SELECT id, identity_key FROM sites WHERE identity_key IN ({placeholders})", chunk
            ).fetchall())
    return {r["identity_key"]: int(r["id"]) for r in result_rows}


def upsert_site(payload: dict[str, Any]) -> int:
    return bulk_upsert_sites([payload])[payload["identity_key"]]


def delete_sites_not_in(keys: list[str]) -> list[str]:
    # SQLite'ın varsayılan 999 bind-variable sınırına takılmamak için
    # mevcut kayıtları Python'da karşılaştırıp silme işlemini parçalıyoruz.
    incoming = set(keys)
    with connect() as conn:
        rows = conn.execute("SELECT id, name, identity_key FROM sites").fetchall()
        removed = [r for r in rows if r["identity_key"] not in incoming]
        if not removed:
            return []
        ids = [int(r["id"]) for r in removed]
        for i in range(0, len(ids), 900):
            chunk = ids[i:i + 900]
            placeholders = ",".join("?" for _ in chunk)
            conn.execute(f"DELETE FROM sites WHERE id IN ({placeholders})", chunk)
        return [r["name"] for r in removed]


def set_site_address(site_id: int, il: str, ilce: str, mahalle: str) -> None:
    set_site_addresses_bulk({site_id: {"il": il, "ilce": ilce, "mahalle": mahalle}})


def set_site_addresses_bulk(addresses: dict[int, dict[str, Any]]) -> None:
    if not addresses:
        return
    now = iso(now_tr())
    rows = [
        (a.get("il") or "", a.get("ilce") or "", a.get("mahalle") or "", now, now, int(sid))
        for sid, a in addresses.items()
    ]
    with connect() as conn:
        conn.executemany(
            "UPDATE sites SET il=?, ilce=?, mahalle=?, geocoded_at=?, updated_at=? WHERE id=?",
            rows,
        )


def set_site_district(site_id: int, district_id: Optional[int], override: bool) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE sites SET district_center_id=?, assignment_override=?, updated_at=? WHERE id=?",
            (district_id, 1 if override else 0, iso(now_tr()), site_id),
        )
        if district_id is not None:
            conn.execute("DELETE FROM osrm_cache WHERE site_id=?", (site_id,))


def assign_districts_bulk(assignments: list[tuple[int, int]]) -> None:
    if not assignments:
        return
    now = iso(now_tr())
    with connect() as conn:
        conn.executemany(
            "UPDATE sites SET district_center_id=?, assignment_override=0, updated_at=? WHERE id=? AND assignment_override=0",
            [(did, now, sid) for sid, did in assignments],
        )


# ----- districts -----

def list_districts() -> list[dict[str, Any]]:
    return fetchall("SELECT * FROM district_centers ORDER BY province, name")


def add_district(name: str, province: str, lat: float, lon: float) -> int:
    return execute(
        "INSERT OR IGNORE INTO district_centers (name, province, lat, lon, created_at) VALUES (?,?,?,?,?)",
        (name.strip(), province.strip(), lat, lon, iso(now_tr())),
    )


def delete_district(district_id: int) -> None:
    execute("DELETE FROM district_centers WHERE id=?", (district_id,))


def get_district(district_id: int) -> Optional[dict[str, Any]]:
    return fetchone("SELECT * FROM district_centers WHERE id=?", (district_id,))


# ----- geocode cache -----

def get_geocode_cache(coord_keys: list[str]) -> dict[str, dict[str, Any]]:
    if not coord_keys:
        return {}
    out: dict[str, dict[str, Any]] = {}
    chunk = 900
    with connect() as conn:
        for i in range(0, len(coord_keys), chunk):
            keys = coord_keys[i:i + chunk]
            ph = ",".join("?" for _ in keys)
            rows = conn.execute(f"SELECT * FROM geocode_cache WHERE coord_key IN ({ph})", keys).fetchall()
            for r in rows:
                out[r["coord_key"]] = row_to_dict(r)
    return out


def save_geocode_cache(rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    now = iso(now_tr())
    values = [
        (r["coord_key"], r["lat"], r["lon"], r.get("il"), r.get("ilce"), r.get("mahalle"), r.get("raw"), now)
        for r in rows
    ]
    with connect() as conn:
        conn.executemany(
            """INSERT OR REPLACE INTO geocode_cache
            (coord_key, lat, lon, il, ilce, mahalle, raw, fetched_at)
            VALUES (?,?,?,?,?,?,?,?)""",
            values,
        )


# ----- outages -----

def upsert_outage(item: dict[str, Any]) -> None:
    upsert_outages_batch([item])


def upsert_outages_batch(items: list[dict[str, Any]]) -> None:
    if not items:
        return
    now = iso(now_tr())
    rows = [(
        item["yedas_id"], item.get("title"), item.get("details"), item.get("start_at"), item.get("end_at"),
        json.dumps(item.get("address") or [], ensure_ascii=False),
        json.dumps(item.get("coords") or [], ensure_ascii=False),
        json.dumps(item.get("geojson") or {}, ensure_ascii=False), now,
    ) for item in items]
    with connect() as conn:
        conn.executemany(
            """INSERT INTO outages
            (yedas_id,title,details,start_at,end_at,address_json,coords_json,geojson_json,last_seen_at)
            VALUES (?,?,?,?,?,?,?,?,?)
            ON CONFLICT(yedas_id) DO UPDATE SET
                title=excluded.title, details=excluded.details, start_at=excluded.start_at,
                end_at=excluded.end_at, address_json=excluded.address_json,
                coords_json=excluded.coords_json, geojson_json=excluded.geojson_json,
                last_seen_at=excluded.last_seen_at""",
            rows,
        )


def replace_matches(yedas_id: str, site_ids: list[tuple[int, str]]) -> None:
    replace_matches_batch({yedas_id: site_ids})


def replace_matches_batch(matches: dict[str, list[tuple[int, str]]]) -> None:
    if not matches:
        return
    now = iso(now_tr())
    ids = list(matches.keys())
    with connect() as conn:
        for i in range(0, len(ids), 900):
            chunk = ids[i:i + 900]
            ph = ",".join("?" for _ in chunk)
            conn.execute(f"DELETE FROM outage_matches WHERE yedas_id IN ({ph})", chunk)
        rows = []
        for yedas_id, pairs in matches.items():
            rows.extend((yedas_id, int(site_id), match_type or "polygon", now) for site_id, match_type in pairs)
        if rows:
            conn.executemany(
                "INSERT OR REPLACE INTO outage_matches (yedas_id, site_id, match_type, snapshot_at) VALUES (?,?,?,?)",
                rows,
            )


def list_outages() -> list[dict[str, Any]]:
    return fetchall("SELECT * FROM outages ORDER BY start_at")


def matches_for_analysis() -> list[dict[str, Any]]:
    return fetchall(
        """SELECT m.yedas_id, m.site_id, m.match_type, m.snapshot_at,
               o.title, o.details, o.start_at, o.end_at,
               s.name AS site_name, s.il, s.ilce, s.mahalle, s.lat, s.lon
        FROM outage_matches m
        JOIN outages o ON o.yedas_id=m.yedas_id
        JOIN sites s ON s.id=m.site_id
        ORDER BY o.start_at DESC"""
    )


# ----- osrm -----

def get_osrm(site_id: int, district_id: int) -> Optional[dict[str, Any]]:
    return fetchone("SELECT * FROM osrm_cache WHERE site_id=? AND district_center_id=?", (site_id, district_id))


def get_osrm_bulk(site_ids: list[int]) -> dict[tuple[int, int], dict[str, Any]]:
    if not site_ids:
        return {}
    out: dict[tuple[int, int], dict[str, Any]] = {}
    with connect() as conn:
        for i in range(0, len(site_ids), 900):
            chunk = site_ids[i:i + 900]
            ph = ",".join("?" for _ in chunk)
            rows = conn.execute(f"SELECT * FROM osrm_cache WHERE site_id IN ({ph})", chunk).fetchall()
            for r in rows:
                out[(int(r["site_id"]), int(r["district_center_id"]))] = row_to_dict(r)
    return out


def save_osrm(site_id: int, district_id: int, distance_km: float, duration_min: float, geometry, source: str) -> None:
    save_osrm_bulk([{
        "site_id": site_id, "district_id": district_id, "distance_km": distance_km,
        "duration_min": duration_min, "geometry": geometry, "source": source,
    }])


def save_osrm_bulk(rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    now = iso(now_tr())
    values = [(
        int(r["site_id"]), int(r["district_id"]), r.get("distance_km"), r.get("duration_min"),
        json.dumps(r.get("geometry")) if r.get("geometry") is not None else None,
        r.get("source") or "osrm", now,
    ) for r in rows]
    with connect() as conn:
        conn.executemany(
            """INSERT OR REPLACE INTO osrm_cache
            (site_id,district_center_id,distance_km,duration_min,geometry_json,source,fetched_at)
            VALUES (?,?,?,?,?,?,?)""",
            values,
        )


# ----- faults -----

def add_fault(site_id: int, mains_at: str, down_at: str, restored_at: Optional[str], backup_min: Optional[float], outage_min: Optional[float], comment: str) -> int:
    return execute(
        "INSERT INTO fault_events (site_id,mains_at,down_at,restored_at,backup_minutes,outage_minutes,comment,created_at) VALUES (?,?,?,?,?,?,?,?)",
        (site_id, mains_at, down_at, restored_at, backup_min, outage_min, comment, iso(now_tr())),
    )


def list_faults(site_id: Optional[int] = None) -> list[dict[str, Any]]:
    if site_id:
        return fetchall(
            "SELECT f.*, s.name AS site_name, s.il, s.ilce FROM fault_events f JOIN sites s ON s.id=f.site_id WHERE f.site_id=? ORDER BY f.mains_at",
            (site_id,),
        )
    return fetchall(
        "SELECT f.*, s.name AS site_name, s.il, s.ilce FROM fault_events f JOIN sites s ON s.id=f.site_id ORDER BY f.mains_at DESC"
    )


def delete_fault(fault_id: int) -> None:
    execute("DELETE FROM fault_events WHERE id=?", (fault_id,))


def save_sync_run(added: list[str], removed: list[str], updated: list[str], geocoded: int) -> int:
    return execute(
        "INSERT INTO sync_runs (created_at,added_json,removed_json,updated_json,geocoded_count) VALUES (?,?,?,?,?)",
        (iso(now_tr()), json.dumps(added, ensure_ascii=False), json.dumps(removed, ensure_ascii=False), json.dumps(updated, ensure_ascii=False), geocoded),
    )


def last_sync() -> Optional[dict[str, Any]]:
    return fetchone("SELECT * FROM sync_runs ORDER BY id DESC LIMIT 1")
