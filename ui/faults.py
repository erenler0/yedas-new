"""Arıza takip formu ve mum/Gantt grafiği."""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import streamlit as st

from src import db
from src.charts import fault_candle
from src.excel_io import dataframe_to_xlsx_bytes
from src.reports import table_card_jpg
from src.utils import TR_TZ, fmt_dt, from_iso, iso, now_tr
from src.services import load_faults_cached, load_sites_cached, invalidate_history_caches


def render() -> None:
    st.subheader("Arıza takip ve şebeke/kesinti analizi")
    sites = load_sites_cached()
    if not sites:
        st.info("Önce Admin panelinden saha Excel'i yükleyin.")
        return

    names = {s["name"]: s for s in sites}
    with st.form("fault_form", clear_on_submit=True):
        st.markdown("**Yeni arıza kaydı**")
        q = st.text_input("Saha ara / seç")
        options = [n for n in names if q.lower() in n.lower()] if q else list(names)
        site_name = st.selectbox("Saha", options if options else ["—"])
        c1, c2, c3 = st.columns(3)
        default = now_tr().replace(second=0, microsecond=0)
        with c1:
            mains = st.datetime_input("Mains saati (elektrik kesilme)", value=default)
        with c2:
            down = st.datetime_input("Kesinti saati (saha down)", value=default + timedelta(minutes=30))
        with c3:
            restored = st.datetime_input("Enerjilenme saati", value=default + timedelta(hours=2))
        comment = st.text_area("Yorum")
        submitted = st.form_submit_button("Kaydet")

    if submitted:
        site = names.get(site_name)
        if not site:
            st.error("Saha seçilmedi.")
        else:
            mains_dt = _as_tr(mains)
            down_dt = _as_tr(down)
            rest_dt = _as_tr(restored)
            backup = (down_dt - mains_dt).total_seconds() / 60.0 if down_dt > mains_dt else 0.0
            outage = (rest_dt - down_dt).total_seconds() / 60.0 if rest_dt > down_dt else 0.0
            db.add_fault(
                int(site["id"]),
                iso(mains_dt),
                iso(down_dt),
                iso(rest_dt),
                round(backup, 1),
                round(outage, 1),
                comment or "",
            )
            invalidate_history_caches()
            st.success(f"Kayıt eklendi. Akü: {backup:.0f} dk, kesik: {outage:.0f} dk")

    events = load_faults_cached()
    if not events:
        st.info("Arıza kaydı yok.")
        return

    f1, f2 = st.columns(2)
    with f1:
        only = st.selectbox("Grafik sahası", ["(tümü)"] + sorted({e["site_name"] for e in events}))
    with f2:
        del_id = st.number_input("Silinecek kayıt no (id)", min_value=0, step=1, value=0)
        if st.button("Kaydı sil") and del_id:
            db.delete_fault(int(del_id))
            invalidate_history_caches()
            st.rerun()

    view = [e for e in events if only == "(tümü)" or e["site_name"] == only]
    backups = [e["backup_minutes"] for e in view if e.get("backup_minutes") is not None]
    outages = [e["outage_minutes"] for e in view if e.get("outage_minutes") is not None]
    m1, m2, m3 = st.columns(3)
    m1.metric("Kayıt", len(view))
    m2.metric("Ort. backup (dk)", f"{(sum(backups) / len(backups)):.1f}" if backups else "—")
    m3.metric("Ort. kesik kalma (dk)", f"{(sum(outages) / len(outages)):.1f}" if outages else "—")

    st.plotly_chart(fault_candle(view), use_container_width=True)
    st.caption("Yeşil bar: mains → down (akü). Kırmızı bar: down → enerjilenme (saha kesik). Y ekseni günün 24 saati.")

    table = pd.DataFrame(
        [
            {
                "id": e["id"],
                "Saha": e["site_name"],
                "İl": e.get("il"),
                "İlçe": e.get("ilce"),
                "Mains": fmt_dt(from_iso(e["mains_at"])),
                "Down": fmt_dt(from_iso(e["down_at"])),
                "Enerji": fmt_dt(from_iso(e.get("restored_at"))),
                "Akü (dk)": e.get("backup_minutes"),
                "Kesik (dk)": e.get("outage_minutes"),
                "Yorum": e.get("comment"),
            }
            for e in view
        ]
    )
    st.dataframe(table, use_container_width=True, hide_index=True)

    a, b = st.columns(2)
    with a:
        st.download_button(
            "Excel indir",
            data=dataframe_to_xlsx_bytes(table, "Ariza"),
            file_name="ariza_kayitlari.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    with b:
        jpg_rows = [
            (str(r["Saha"]), f"akü {r['Akü (dk)']} dk / kesik {r['Kesik (dk)']} dk")
            for r in table.head(18).to_dict("records")
        ]
        avg_b = f"{(sum(backups) / len(backups)):.1f}" if backups else "—"
        avg_o = f"{(sum(outages) / len(outages)):.1f}" if outages else "—"
        jpg = table_card_jpg("Arıza özeti", jpg_rows, footer=f"Ort. backup {avg_b} dk · Ort. kesik {avg_o} dk")
        st.download_button("JPG indir", data=jpg, file_name="ariza_ozet.jpg", mime="image/jpeg")


def _as_tr(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=TR_TZ)
    return value.astimezone(TR_TZ)
