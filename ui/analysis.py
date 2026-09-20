"""Detay ve analiz: KPI, arama, mum timeline, dışa aktarım."""

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from src import db
from src.charts import kpi_bar, outage_timeline
from src.excel_io import dataframe_to_xlsx_bytes
from src.reports import table_card_jpg
from src.utils import fmt_dt
from src.services import load_matches_cached


def render() -> None:
    st.subheader("Detay ve analiz")
    rows = load_matches_cached()
    if not rows:
        st.info("Analiz için eşleşmiş kesinti geçmişi yok. Ana ekran YEDAŞ verisini çektikten sonra kayıt birikir.")
        return

    df = pd.DataFrame(rows)
    df["start_dt"] = pd.to_datetime(df["start_at"], errors="coerce", utc=True)
    df["end_dt"] = pd.to_datetime(df["end_at"], errors="coerce", utc=True)

    c1, c2, c3 = st.columns(3)
    top_site = df.groupby("site_name").size().sort_values(ascending=False).head(5)
    top_il = df.dropna(subset=["il"]).groupby("il").size().sort_values(ascending=False).head(5)
    top_ilce = df.dropna(subset=["ilce"]).groupby("ilce").size().sort_values(ascending=False).head(5)

    with c1:
        st.markdown("**Top 5 saha**")
        for name, n in top_site.items():
            st.metric(str(name)[:28], int(n))
    with c2:
        st.markdown("**Top 5 il**")
        for name, n in top_il.items():
            st.metric(str(name), int(n))
    with c3:
        st.markdown("**Top 5 ilçe**")
        for name, n in top_ilce.items():
            st.metric(str(name), int(n))

    g1, g2, g3 = st.columns(3)
    with g1:
        st.plotly_chart(kpi_bar(list(top_site.index), list(map(int, top_site.values)), "Saha"), use_container_width=True)
    with g2:
        st.plotly_chart(kpi_bar(list(top_il.index), list(map(int, top_il.values)), "İl"), use_container_width=True)
    with g3:
        st.plotly_chart(kpi_bar(list(top_ilce.index), list(map(int, top_ilce.values)), "İlçe"), use_container_width=True)

    sites = sorted(df["site_name"].dropna().unique().tolist())
    iller = ["(tümü)"] + sorted([x for x in df["il"].dropna().unique().tolist()])
    ilceler = ["(tümü)"] + sorted([x for x in df["ilce"].dropna().unique().tolist()])

    f1, f2, f3, f4 = st.columns(4)
    with f1:
        q = st.text_input("Saha ara")
    with f2:
        site_sel = st.selectbox("Saha", ["(tümü)"] + sites)
    with f3:
        il_sel = st.selectbox("İl", iller)
    with f4:
        ilce_sel = st.selectbox("İlçe", ilceler)
    d1, d2 = st.columns(2)
    with d1:
        start_d = st.date_input("Başlangıç", value=date.today().replace(day=1))
    with d2:
        end_d = st.date_input("Bitiş", value=date.today())

    filt = df.copy()
    if q:
        filt = filt[filt["site_name"].str.contains(q, case=False, na=False)]
    if site_sel != "(tümü)":
        filt = filt[filt["site_name"] == site_sel]
    if il_sel != "(tümü)":
        filt = filt[filt["il"] == il_sel]
    if ilce_sel != "(tümü)":
        filt = filt[filt["ilce"] == ilce_sel]
    if start_d and end_d:
        filt = filt[
            filt["start_dt"].isna()
            | ((filt["start_dt"].dt.date <= end_d) & (filt["end_dt"].fillna(filt["start_dt"]).dt.date >= start_d))
        ]

    show = filt.copy()
    def _fmt(ts):
        if pd.isna(ts):
            return "—"
        return fmt_dt(ts.to_pydatetime())

    show["Başlangıç"] = show["start_dt"].apply(_fmt)
    show["Bitiş"] = show["end_dt"].apply(_fmt)
    table = show[["site_name", "il", "ilce", "mahalle", "title", "Başlangıç", "Bitiş", "match_type"]].rename(
        columns={
            "site_name": "Saha",
            "il": "İl",
            "ilce": "İlçe",
            "mahalle": "Mahalle",
            "title": "Başlık",
            "match_type": "Eşleşme",
        }
    )
    st.dataframe(table, use_container_width=True, hide_index=True)

    chart_site = site_sel if site_sel != "(tümü)" else (q if q in sites else (sites[0] if len(sites) == 1 else None))
    if chart_site:
        site_rows = filt[filt["site_name"] == chart_site].to_dict("records")
        st.plotly_chart(outage_timeline(site_rows, chart_site), use_container_width=True)
    else:
        st.caption("Mum/timeline için listeden tek bir saha seçin.")

    cdl, cdr = st.columns(2)
    with cdl:
        st.download_button(
            "Excel indir",
            data=dataframe_to_xlsx_bytes(table, "Analiz"),
            file_name="kesinti_analiz.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    with cdr:
        jpg_rows = [(str(r["Saha"]), f"{r['İl']}/{r['İlçe']}  {r['Başlangıç']} → {r['Bitiş']}") for r in table.head(18).to_dict("records")]
        jpg = table_card_jpg("Kesinti analiz özeti", jpg_rows, footer=f"{len(table)} kayıt")
        st.download_button("JPG indir", data=jpg, file_name="kesinti_analiz.jpg", mime="image/jpeg")
