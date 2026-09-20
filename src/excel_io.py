"""Saha Excel okuma / yazma."""

from __future__ import annotations

from io import BytesIO
from typing import Any

import pandas as pd

from src.config import EXCEL_COLUMNS
from src.utils import safe_float


def _pick(df: pd.DataFrame, keys: tuple[str, ...]) -> str | None:
    lower = {str(c).strip().lower(): c for c in df.columns}
    for key in keys:
        if key.lower() in lower:
            return lower[key.lower()]
    return None


def read_sites_excel(file) -> pd.DataFrame:
    df = pd.read_excel(file, engine="openpyxl")
    df.columns = [str(c).strip() for c in df.columns]
    mapping = {}
    for canon, aliases in EXCEL_COLUMNS.items():
        col = _pick(df, aliases)
        if col:
            mapping[col] = canon
    if "lat" not in mapping.values() or "lon" not in mapping.values() or "name" not in mapping.values():
        raise ValueError(
            "Excel'de zorunlu sütunlar eksik: Placemark Adı, Latitude, Longitude"
        )
    out = df.rename(columns=mapping)
    records = []
    for _, row in out.iterrows():
        lat = safe_float(row.get("lat"))
        lon = safe_float(row.get("lon"))
        name = str(row.get("name") or "").strip()
        if lat is None or lon is None or not name:
            continue
        records.append(
            {
                "kml_file": _str(row.get("kml")),
                "name": name,
                "description": _str(row.get("description")),
                "lat": lat,
                "lon": lon,
                "altitude": safe_float(row.get("alt")),
                "raw_coords": _str(row.get("raw")),
                "identity_key": f"{name.lower()}|{lat:.6f}|{lon:.6f}",
            }
        )
    return pd.DataFrame.from_records(records)


def _str(value) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    return text or None


def sites_template_bytes() -> bytes:
    buf = BytesIO()
    df = pd.DataFrame(
        columns=[
            "KML Dosyası",
            "Placemark Adı",
            "Açıklama",
            "Latitude",
            "Longitude",
            "Altitude",
            "Koordinat (Ham)",
        ]
    )
    df.to_excel(buf, index=False, engine="openpyxl")
    return buf.getvalue()


def dataframe_to_xlsx_bytes(df: pd.DataFrame, sheet: str = "Veri") -> bytes:
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=sheet[:31])
    return buf.getvalue()
