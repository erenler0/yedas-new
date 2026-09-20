"""Ana ekran: canlı YEDAŞ kesintileri, poligon eşleştirme, harita."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from src import db
from src.excel_io import dataframe_to_xlsx_bytes
from src.maps import outage_map
from src.reports import outage_card_jpg
from src.services import filter_window, load_sites_cached, load_yedas_cached, persist_and_match
from src.utils import duration_hours, fmt_dt, from_iso


def render() -> None:
    st.subheader("YEDAŞ canlı planlı kesintiler")
    sites = load_sites_cached()
    if not sites:
        st.info("Henüz saha yüklenmedi. Admin panelinden Excel senkronu yapın.")
        return

    col_f1, col_f2, col_f3 = st.columns([1, 1, 2])
    with col_f1:
        window = st.radio("Zaman filtresi", ["Günlük", "3 Günlük", "7 Günlük"], horizontal=True)
    days = {"Günlük": 1, "3 Günlük": 3, "7 Günlük": 7}[window]

    try:
        outages = load_yedas_cached()
    except Exception as exc:
        st.error(f"YEDAŞ API şu an okunamadı: {exc}")
        stored = db.list_outages()
        if not stored:
            return
        st.warning("Veritabanındaki son kesinti anlık görüntüsü gösteriliyor.")
        outages = stored
        for o in outages:
            o["start_dt"] = from_iso(o.get("start_at"))
            o["end_dt"] = from_iso(o.get("end_at"))
            import json

            o["coords"] = json.loads(o.get("coords_json") or "[]")
            o["address"] = json.loads(o.get("address_json") or "[]")
            o["geojson"] = json.loads(o.get("geojson_json") or "{}")

    # Kritik performans noktası: API yüzlerce kayıt döndürse bile yalnızca seçilen
    # gün penceresindeki kesintiler Shapely eşleştirmesine girer.
    window_outages = filter_window(outages, days)
    matched = persist_and_match(window_outages, sites)
    visible = filter_window(matched, days)

    affected_n = sum(len(i.get("affected") or []) for i in visible)
    with col_f2:
        st.metric("Kesinti kaydı", len(visible))
    with col_f3:
        st.metric("Etkilenen saha (çakışma)", affected_n)

    st.caption("Kırmızı pin: poligon/adres ile etkilenen saha. Mavi pin: poligon merkezine 15 km içindeki etkilenmeyen saha.")
    fmap = outage_map(visible, show_nearby=True)
    st_folium(fmap, width=None, height=560, returned_objects=[], use_container_width=True)

    rows = []
    pick_options = []
    for item in visible:
        for site in item.get("affected") or []:
            start = item.get("start_dt") or from_iso(item.get("start_at"))
            end = item.get("end_dt") or from_iso(item.get("end_at"))
            rec = {
                "Saha": site.get("name"),
                "İl": site.get("il"),
                "İlçe": site.get("ilce"),
                "Mahalle": site.get("mahalle"),
                "Eşleşme": "Poligon" if site.get("match_type") == "polygon" else "Adres",
                "Başlangıç": fmt_dt(start) if isinstance(start, datetime) else (item.get("start_at") or "—"),
                "Bitiş": fmt_dt(end) if isinstance(end, datetime) else (item.get("end_at") or "—"),
                "Süre (saat)": duration_hours(start, end) if isinstance(start, datetime) else None,
                "YEDAŞ başlık": item.get("title"),
                "İş açıklaması": item.get("details"),
            }
            rows.append(rec)
            pick_options.append((f"{site.get('name')} | {item.get('title')}", site, item))

    if not rows:
        st.success("Seçilen pencerede poligon/adres eşleşmesi bulunan saha yok.")
        return

    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)

    st.download_button(
        "Listeyi Excel indir",
        data=dataframe_to_xlsx_bytes(df, "Etkilenen"),
        file_name="etkilenen_sahalar.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    labels = [p[0] for p in pick_options]
    choice = st.selectbox("JPG kartı için kesinti/saha seçin", labels)
    if choice:
        _, site, item = pick_options[labels.index(choice)]
        jpg = outage_card_jpg(site, item)
        st.image(jpg, caption="Önizleme")
        st.download_button("Görsel dışa aktar (JPG)", data=jpg, file_name="kesinti_karti.jpg", mime="image/jpeg")
