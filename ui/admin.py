"""Admin paneli: oturum, Excel senkron, ilçe merkezleri, manuel atama."""

from __future__ import annotations

import streamlit as st

from src import db
from src.config import PROVINCES, admin_password
from src.excel_io import sites_template_bytes
from src.reports import sync_diff_jpg
from src.services import assign_nearest_districts, invalidate_site_caches, load_districts_cached, load_sites_cached, seed_districts, sync_sites_from_excel
from src.utils import safe_float


def render() -> None:
    st.subheader("Admin paneli")
    if not st.session_state.get("admin_ok"):
        pwd = st.text_input("Şifre", type="password")
        if st.button("Giriş"):
            if pwd == admin_password():
                st.session_state["admin_ok"] = True
                st.rerun()
            else:
                st.error("Şifre hatalı.")
        st.caption("Oturum yalnızca bu tarayıcı oturumu (session state) boyunca geçerlidir.")
        return

    if st.button("Çıkış"):
        st.session_state["admin_ok"] = False
        st.rerun()

    st.success(f"Yetkili oturum açık. Kayıtlı saha: {db.site_count()}")

    tab1, tab2, tab3 = st.tabs(["Excel senkron & geocoding", "İlçe merkezleri", "Manuel saha ataması"])

    with tab1:
        st.download_button(
            "Boş saha şablonu (.xlsx)",
            data=sites_template_bytes(),
            file_name="saha_sablonu.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        uploaded = st.file_uploader("Saha Excel (.xlsx)", type=["xlsx"])
        st.caption(
            "Sütunlar: KML Dosyası, Placemark Adı, Açıklama, Latitude, Longitude, Altitude, Koordinat (Ham). "
            "Yalnızca yeni koordinatlar Nominatim ile İl/İlçe/Mahalle alır. Geocode cache sayesinde aynı koordinat ikinci kez sorgulanmaz; ilk 1300 koordinat için kamu Nominatim hız sınırı nedeniyle işlem uzun sürebilir."
        )
        if uploaded and st.button("Akıllı senkron başlat"):
            progress = st.empty()
            try:
                result = sync_sites_from_excel(uploaded, progress)
            except Exception as exc:
                st.error(str(exc))
            else:
                invalidate_site_caches()
                st.session_state["last_sync_result"] = result
                st.success(
                    f"Toplam saha {result['total']}. Eklenen {len(result['added'])}, "
                    f"silinen {len(result['removed'])}, geocoding {result['geocoded']}."
                )

        result = st.session_state.get("last_sync_result")
        last = db.last_sync()
        if result:
            st.write("Eklenen:", result["added"] or "—")
            st.write("Silinen:", result["removed"] or "—")
            jpg = sync_diff_jpg(result["added"], result["removed"], result["updated"], result["geocoded"])
            st.image(jpg)
            st.download_button("Fark raporu çıkart (JPG)", data=jpg, file_name="senkron_fark.jpg", mime="image/jpeg")
        elif last:
            import json

            st.caption(f"Son senkron: {last['created_at']}")
            jpg = sync_diff_jpg(
                json.loads(last["added_json"]),
                json.loads(last["removed_json"]),
                json.loads(last["updated_json"]),
                int(last["geocoded_count"]),
            )
            st.download_button("Son fark raporu (JPG)", data=jpg, file_name="senkron_fark.jpg", mime="image/jpeg")

    with tab2:
        if st.button("6 il resmi ilçe merkezlerini yükle"):
            n = seed_districts()
            invalidate_site_caches()
            st.success(f"{n} ilçe merkezi işlendi. Otomatik en-yakın atama güncellendi.")
        with st.form("add_dc"):
            n1, n2 = st.columns(2)
            with n1:
                province = st.selectbox("İl", PROVINCES)
                name = st.text_input("İlçe merkezi adı")
            with n2:
                lat = st.text_input("Enlem")
                lon = st.text_input("Boylam")
            if st.form_submit_button("Ekle"):
                la, lo = safe_float(lat), safe_float(lon)
                if not name or la is None or lo is None:
                    st.error("Ad ve geçerli koordinat gerekli.")
                else:
                    db.add_district(name, province, la, lo)
                    assign_nearest_districts()
                    invalidate_site_caches()
                    st.success("Eklendi.")
                    st.rerun()

        districts = load_districts_cached()
        if districts:
            st.dataframe(
                [
                    {"id": d["id"], "İl": d["province"], "Ad": d["name"], "Lat": d["lat"], "Lon": d["lon"]}
                    for d in districts
                ],
                use_container_width=True,
                hide_index=True,
            )
            del_id = st.selectbox("Silinecek ilçe merkezi", [f"{d['id']} — {d['province']} / {d['name']}" for d in districts])
            if st.button("İlçe merkezini sil"):
                did = int(del_id.split("—")[0].strip())
                db.delete_district(did)
                assign_nearest_districts()
                invalidate_site_caches()
                st.rerun()
        else:
            st.info("İlçe merkezi yok.")

    with tab3:
        sites = load_sites_cached()
        districts = load_districts_cached()
        if not sites:
            st.info("Saha yok.")
            return
        if not districts:
            st.info("Önce ilçe merkezi ekleyin.")
            return
        site = st.selectbox("Saha", [f"{s['id']} — {s['name']}" for s in sites])
        sid = int(site.split("—")[0].strip())
        rec = db.get_site(sid)
        st.write(
            {
                "Mevcut atama": rec.get("district_center_id"),
                "Override": bool(rec.get("assignment_override")),
                "İl/İlçe": f"{rec.get('il')} / {rec.get('ilce')}",
            }
        )
        labels = {f"{d['province']} / {d['name']}": d["id"] for d in districts}
        choice = st.selectbox("Yeni ilçe merkezi", list(labels))
        c1, c2 = st.columns(2)
        with c1:
            if st.button("Manuel ata (override)"):
                db.set_site_district(sid, labels[choice], override=True)
                invalidate_site_caches()
                st.success("Atama kilitlendi.")
                st.rerun()
        with c2:
            if st.button("Otomatik en yakına bırak"):
                db.set_site_district(sid, None, override=False)
                assign_nearest_districts()
                invalidate_site_caches()
                st.success("Override kaldırıldı.")
                st.rerun()
