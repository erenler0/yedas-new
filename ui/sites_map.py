"""Sahalar ve ilçe merkezleri: OSRM mesafe / rota."""

from __future__ import annotations

import json

import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from src import db
from src.config import PROVINCES
from src.excel_io import dataframe_to_xlsx_bytes
from src.maps import sites_district_map
from src.reports import table_card_jpg
from src.services import enrich_sites_with_routes, load_districts_cached, load_sites_cached, route_geometry_for


def render() -> None:
    st.subheader("Sahalar ve ilçe merkezleri")
    sites = load_sites_cached()
    districts = load_districts_cached()
    if not sites:
        st.info("Saha verisi yok. Admin panelinden Excel yükleyin.")
        return
    if not districts:
        st.warning("İlçe merkezi tanımlı değil. Admin panelinden ekleyin veya resmi listeyi yükleyin.")

    provinces = ["(tümü)"] + [p for p in PROVINCES]
    extra = sorted({s.get("il") for s in sites if s.get("il") and s.get("il") not in PROVINCES})
    provinces += extra

    c1, c2, c3 = st.columns(3)
    with c1:
        il = st.selectbox("İl", provinces)
    with c2:
        q = st.text_input("Saha adı")
    with c3:
        compute = st.checkbox("Eksik OSRM mesafelerini hesapla", value=False)

    filtered = sites
    if il != "(tümü)":
        filtered = [s for s in filtered if (s.get("il") or "") == il]
    if q:
        filtered = [s for s in filtered if q.lower() in (s.get("name") or "").lower()]

    progress = st.empty()
    enriched = enrich_sites_with_routes(filtered, compute_missing=compute, progress=progress if compute else None)

    names = [s["name"] for s in enriched]
    selected_name = st.selectbox("Rota çizilecek saha (isteğe bağlı)", ["(yok)"] + names)
    route = None
    if selected_name != "(yok)":
        site = next(s for s in enriched if s["name"] == selected_name)
        with st.spinner("OSRM tam geometri alınıyor…"):
            geom = route_geometry_for(site)
            if isinstance(geom, str):
                try:
                    geom = json.loads(geom)
                except Exception:
                    geom = None
            route = geom

    fmap = sites_district_map(enriched, districts, route_geojson=route)
    st_folium(fmap, width=None, height=560, returned_objects=[], use_container_width=True)
    st.caption("Mavi: GSM sahası. Kırmızı: ilçe merkezi. Hover: bağlı merkez, yol km, sürüş süresi.")

    table = pd.DataFrame(
        [
            {
                "Saha": s.get("name"),
                "İl": s.get("il"),
                "İlçe (adres)": s.get("ilce"),
                "Mahalle": s.get("mahalle"),
                "Bağlı ilçe merkezi": s.get("district_name"),
                "Atama": "Manuel" if s.get("assignment_override") else "Otomatik (en yakın)",
                "Yol (km)": s.get("distance_km"),
                "Süre (dk)": s.get("duration_min"),
                "Kaynak": s.get("route_source"),
                "Latitude": s.get("lat"),
                "Longitude": s.get("lon"),
            }
            for s in enriched
        ]
    )
    st.dataframe(table, use_container_width=True, hide_index=True)

    a, b = st.columns(2)
    with a:
        st.download_button(
            "Excel indir",
            data=dataframe_to_xlsx_bytes(table, "Mesafe"),
            file_name="saha_mesafe.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    with b:
        jpg_rows = [
            (str(r["Saha"]), f"{r['Bağlı ilçe merkezi'] or '—'}  {r['Yol (km)'] or '—'} km / {r['Süre (dk)'] or '—'} dk")
            for r in table.head(18).to_dict("records")
        ]
        jpg = table_card_jpg("Saha – ilçe merkezi mesafe", jpg_rows)
        st.download_button("JPG indir", data=jpg, file_name="saha_mesafe.jpg", mime="image/jpeg")
