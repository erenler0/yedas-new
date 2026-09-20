"""Plotly mum / timeline ve arıza Gantt grafikleri."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

import plotly.graph_objects as go

from src.utils import from_iso, TR_TZ


def outage_timeline(rows: list[dict[str, Any]], site_name: str) -> go.Figure:
    fig = go.Figure()
    if not rows:
        fig.update_layout(title=f"{site_name} — kesinti kaydı yok", template="plotly_dark", height=420)
        return fig
    for i, r in enumerate(rows):
        start = from_iso(r.get("start_at"))
        end = from_iso(r.get("end_at")) or start
        if start is None:
            continue
        fig.add_trace(
            go.Scatter(
                x=[start, end, end, start, start],
                y=[i + 0.15, i + 0.15, i + 0.85, i + 0.85, i + 0.15],
                fill="toself",
                mode="lines",
                line=dict(color="#c62828", width=1),
                fillcolor="rgba(198,40,40,0.55)",
                name=r.get("title") or "Kesinti",
                hovertext=(
                    f"{r.get('title')}<br>{r.get('start_at')}<br>{r.get('end_at')}<br>"
                    f"{r.get('match_type')}"
                ),
                hoverinfo="text",
                showlegend=False,
            )
        )
    fig.update_layout(
        title=f"{site_name} — geçmiş kesinti zaman dilimleri",
        template="plotly_dark",
        height=max(380, 48 * len(rows) + 140),
        yaxis=dict(
            tickmode="array",
            tickvals=list(range(len(rows))),
            ticktext=[(r.get("title") or r.get("yedas_id") or "")[:40] for r in rows],
        ),
        xaxis_title="Zaman",
        margin=dict(l=160, r=30, t=60, b=50),
    )
    return fig


def fault_candle(events: list[dict[str, Any]]) -> go.Figure:
    """X: gün, Y: 00:00–24:00. Yeşil: akü (mains→down), kırmızı: kesinti (down→restored)."""
    fig = go.Figure()
    if not events:
        fig.update_layout(title="Arıza kaydı yok", template="plotly_dark", height=520)
        fig.update_yaxes(range=[0, 24], title="Saat")
        return fig

    days: set[datetime] = set()
    shapes_data = []

    def add_span(start: datetime, end: datetime, color: str, label: str, ev: dict):
        cur = start
        while cur.date() <= end.date():
            day0 = datetime(cur.year, cur.month, cur.day, tzinfo=TR_TZ)
            day1 = day0 + timedelta(days=1)
            seg_start = max(cur, day0)
            seg_end = min(end, day1)
            if seg_end <= seg_start:
                break
            y0 = seg_start.hour + seg_start.minute / 60.0 + seg_start.second / 3600.0
            y1 = 24.0 if seg_end >= day1 else (
                seg_end.hour + seg_end.minute / 60.0 + seg_end.second / 3600.0
            )
            shapes_data.append((day0, y0, y1, color, label, ev))
            days.add(day0)
            cur = day1

    for ev in events:
        mains = from_iso(ev.get("mains_at"))
        down = from_iso(ev.get("down_at"))
        restored = from_iso(ev.get("restored_at"))
        if mains and down and down > mains:
            add_span(mains, down, "rgba(46,125,50,0.85)", "Akü (mains → down)", ev)
        if down and restored and restored > down:
            add_span(down, restored, "rgba(198,40,40,0.88)", "Kesinti (down → enerji)", ev)
        elif down and not restored:
            add_span(down, down + timedelta(hours=1), "rgba(198,40,40,0.4)", "Kesinti (devam)", ev)

    day_list = sorted(days)
    index = {d: i for i, d in enumerate(day_list)}

    for day0, y0, y1, color, label, ev in shapes_data:
        x = index[day0]
        fig.add_trace(
            go.Scatter(
                x=[x - 0.35, x + 0.35, x + 0.35, x - 0.35, x - 0.35],
                y=[y0, y0, y1, y1, y0],
                fill="toself",
                mode="lines",
                line=dict(width=0.5, color=color),
                fillcolor=color,
                name=label,
                legendgroup=label,
                hovertext=(
                    f"{ev.get('site_name')}<br>{label}<br>"
                    f"Mains: {ev.get('mains_at')}<br>Down: {ev.get('down_at')}<br>"
                    f"Enerji: {ev.get('restored_at') or '—'}<br>{ev.get('comment') or ''}"
                ),
                hoverinfo="text",
                showlegend=False,
            )
        )

    fig.add_trace(go.Scatter(x=[None], y=[None], mode="markers",
                             marker=dict(size=12, color="rgba(46,125,50,0.85)"), name="Akü çalışma"))
    fig.add_trace(go.Scatter(x=[None], y=[None], mode="markers",
                             marker=dict(size=12, color="rgba(198,40,40,0.88)"), name="Saha kesik"))

    fig.update_layout(
        title="Arıza mum grafiği — akü (yeşil) ve kesinti (kırmızı)",
        template="plotly_dark",
        height=620,
        xaxis=dict(
            tickmode="array",
            tickvals=list(range(len(day_list))),
            ticktext=[d.strftime("%d.%m.%Y") for d in day_list],
            title="Gün",
        ),
        yaxis=dict(range=[24, 0], title="Günün saati", dtick=2, zeroline=False),
        legend=dict(orientation="h", y=1.08),
        margin=dict(l=60, r=30, t=80, b=60),
    )
    return fig


def kpi_bar(labels: list[str], values: list[int], title: str) -> go.Figure:
    fig = go.Figure(go.Bar(x=values[::-1], y=labels[::-1], orientation="h", marker_color="#c62828"))
    fig.update_layout(title=title, template="plotly_dark", height=320, margin=dict(l=120, r=20, t=50, b=40))
    return fig
