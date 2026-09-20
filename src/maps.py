"""Folium haritaları."""

from __future__ import annotations

import json
from typing import Any, Optional

import folium
from folium.plugins import MarkerCluster, Fullscreen, MeasureControl

DEFAULT_CENTER = [41.28, 36.33]


def outage_map(matched: list[dict[str, Any]], show_nearby: bool = True) -> folium.Map:
    m = folium.Map(location=DEFAULT_CENTER, zoom_start=8, tiles="CartoDB positron")
    Fullscreen().add_to(m)
    MeasureControl(primary_length_unit="kilometers").add_to(m)
    poly_group = folium.FeatureGroup(name="Kesinti poligonları", show=True)
    red = folium.FeatureGroup(name="Etkilenen sahalar")
    blue = folium.FeatureGroup(name="Yakın (etkilenmeyen) sahalar")
    red_cluster = MarkerCluster().add_to(red)
    blue_cluster = MarkerCluster().add_to(blue)

    bounds: list[list[float]] = []
    # Aynı saha birden fazla kesintinin yakınında/etkisinde olabilir. Harita HTML'ini
    # gereksiz yüzlerce tekrar marker ile şişirmemek için pinleri tekilleştiriyoruz.
    seen_red: set[Any] = set()
    seen_blue: set[Any] = set()
    for item in matched:
        geom = item.get("polygon")
        color = "#c62828" if item.get("affected") else "#ef6c00"
        if geom is not None and not geom.is_empty:
            try:
                gj = json.loads(json.dumps(geom.__geo_interface__))
                folium.GeoJson(
                    gj,
                    style_function=lambda _x, c=color: {
                        "fillColor": c,
                        "color": c,
                        "weight": 2,
                        "fillOpacity": 0.28,
                    },
                    tooltip=folium.Tooltip(
                        f"{item.get('title') or 'Kesinti'}<br>{(item.get('details') or '')[:180]}"
                    ),
                ).add_to(poly_group)
                b = geom.bounds
                bounds.extend([[b[1], b[0]], [b[3], b[2]]])
            except Exception:
                pass
        for site in item.get("affected") or []:
            key = site.get("id") or f"{site.get('lat')}|{site.get('lon')}"
            if key in seen_red:
                continue
            seen_red.add(key)
            _pin(
                red_cluster,
                site,
                color="red",
                extra=f"Eşleşme: {site.get('match_type')}",
            )
            bounds.append([site["lat"], site["lon"]])
        if show_nearby:
            for site in item.get("nearby") or []:
                key = site.get("id") or f"{site.get('lat')}|{site.get('lon')}"
                if key in seen_blue or key in seen_red:
                    continue
                seen_blue.add(key)
                _pin(
                    blue_cluster,
                    site,
                    color="blue",
                    extra=f"Yakın: {site.get('nearby_km')} km",
                )

    poly_group.add_to(m)
    red.add_to(m)
    blue.add_to(m)
    folium.LayerControl().add_to(m)
    if bounds:
        try:
            m.fit_bounds(bounds, padding=(30, 30))
        except Exception:
            pass
    return m


def sites_district_map(
    sites: list[dict[str, Any]],
    districts: list[dict[str, Any]],
    route_geojson: Optional[dict] = None,
) -> folium.Map:
    m = folium.Map(location=DEFAULT_CENTER, zoom_start=7, tiles="CartoDB positron")
    Fullscreen().add_to(m)
    site_group = MarkerCluster(name="GSM sahaları")
    d_group = folium.FeatureGroup(name="İlçe merkezleri")

    bounds = []
    for d in districts:
        folium.CircleMarker(
            location=[d["lat"], d["lon"]],
            radius=8,
            color="#b71c1c",
            fill=True,
            fill_color="#ef5350",
            fill_opacity=0.95,
            tooltip=f"{d['province']} / {d['name']}",
            popup=f"<b>{d['name']}</b><br>{d['province']}",
        ).add_to(d_group)
        bounds.append([d["lat"], d["lon"]])

    for s in sites:
        dc = s.get("district_name") or "Atanmamış"
        dist = s.get("distance_km")
        dur = s.get("duration_min")
        src = s.get("route_source") or ""
        dist_txt = f"{dist} km" if dist is not None else "—"
        dur_txt = f"{dur} dk" if dur is not None else "—"
        html = (
            f"<b>{s.get('name')}</b><br>"
            f"Bağlı ilçe merkezi: {dc}<br>"
            f"Yol mesafesi: {dist_txt}<br>"
            f"Sürüş süresi: {dur_txt}<br>"
            f"{s.get('il') or ''} / {s.get('ilce') or ''}"
        )
        folium.CircleMarker(
            location=[s["lat"], s["lon"]],
            radius=5,
            color="#1565c0",
            fill=True,
            fill_color="#42a5f5",
            fill_opacity=0.9,
            tooltip=folium.Tooltip(html, sticky=True),
            popup=html,
        ).add_to(site_group)
        bounds.append([s["lat"], s["lon"]])

    site_group.add_to(m)
    d_group.add_to(m)
    if route_geojson:
        try:
            folium.GeoJson(
                route_geojson,
                name="Sürüş rotası",
                style_function=lambda _: {"color": "#6a1b9a", "weight": 5, "opacity": 0.8},
            ).add_to(m)
        except Exception:
            pass
    folium.LayerControl().add_to(m)
    if bounds:
        try:
            m.fit_bounds(bounds, padding=(24, 24))
        except Exception:
            pass
    return m


def _pin(target, site: dict[str, Any], color: str, extra: str) -> None:
    addr = " / ".join([p for p in [site.get("il"), site.get("ilce"), site.get("mahalle")] if p])
    html = f"<b>{site.get('name')}</b><br>{addr}<br>{extra}"
    folium.Marker(
        location=[site["lat"], site["lon"]],
        tooltip=html,
        popup=html,
        icon=folium.Icon(color=color, icon="info-sign"),
    ).add_to(target)
