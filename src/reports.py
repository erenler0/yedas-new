"""Pillow ile JPG görsel raporlar."""

from __future__ import annotations

from datetime import datetime
from io import BytesIO
from typing import Any, Optional

from PIL import Image, ImageDraw, ImageFont

from src.utils import fmt_dt, from_iso, now_tr


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, width: int) -> list[str]:
    words = (text or "—").split()
    if not words:
        return ["—"]
    lines, cur = [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if draw.textlength(trial, font=font) <= width:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines[:12]


def _card_base(width: int, height: int, title: str) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (width, height), "#0f1419")
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, width, 110], fill="#8b1515")
    draw.rectangle([0, 110, width, 116], fill="#e0a060")
    draw.text((48, 28), "YEDAŞ  ×  GSM", font=_font(22, True), fill="#f7d9b0")
    draw.text((48, 58), title, font=_font(32, True), fill="#ffffff")
    draw.text((width - 420, 40), now_tr().strftime("%d.%m.%Y  %H:%M"), font=_font(18), fill="#f3e6d8")
    return img, draw


def outage_card_jpg(
    site: dict[str, Any],
    outage: dict[str, Any],
) -> bytes:
    img, draw = _card_base(1600, 900, "Planlı Kesinti Bildirimi")
    start = from_iso(outage.get("start_at")) or outage.get("start_dt")
    end = from_iso(outage.get("end_at")) or outage.get("end_dt")
    hours = None
    if isinstance(start, datetime) and isinstance(end, datetime):
        hours = round((end - start).total_seconds() / 3600.0, 1)

    rows = [
        ("Saha Adı", site.get("name") or "—"),
        ("İl / İlçe / Mahalle", " / ".join([p for p in [site.get("il"), site.get("ilce"), site.get("mahalle")] if p]) or "—"),
        ("Koordinat", f"{site.get('lat')}, {site.get('lon')}"),
        ("Eşleşme", "Poligon (Point-in-Polygon)" if site.get("match_type") == "polygon" else "Adres (yedek)"),
        ("Çalışma başı", fmt_dt(start) if not isinstance(start, str) else start),
        ("Çalışma sonu", fmt_dt(end) if not isinstance(end, str) else end),
        ("Çalışma süresi", f"{hours} saat" if hours is not None else "—"),
        ("YEDAŞ başlık", outage.get("title") or "—"),
    ]

    y = 150
    label_font, value_font = _font(20, True), _font(26)
    for label, value in rows:
        draw.text((56, y), label.upper(), font=_font(14, True), fill="#9bb0c7")
        for line in _wrap(draw, str(value), value_font, 1480):
            draw.text((56, y + 24), line, font=value_font, fill="#e8eef5")
            y += 34
        y += 28

    draw.rounded_rectangle([48, 700, 1552, 860], radius=18, fill="#1a2332", outline="#2c3d55")
    draw.text((72, 718), "İŞ AÇIKLAMASI", font=_font(14, True), fill="#e0a060")
    details = str(outage.get("details") or "—").replace("\n", "  |  ")
    ty = 748
    for line in _wrap(draw, details, _font(20), 1440):
        draw.text((72, ty), line, font=_font(20), fill="#d7e3f0")
        ty += 28

    return _to_jpg(img)


def sync_diff_jpg(added: list[str], removed: list[str], updated: list[str], geocoded: int) -> bytes:
    img, draw = _card_base(1400, 900, "Saha Senkron Fark Raporu")
    boxes = [
        ("EKLENEN", len(added), "#1b5e20", added),
        ("SİLİNEN", len(removed), "#b71c1c", removed),
        ("GÜNCELLENEN", len(updated), "#e65100", updated),
    ]
    x = 48
    for title, count, color, names in boxes:
        draw.rounded_rectangle([x, 150, x + 420, 300], radius=16, fill=color)
        draw.text((x + 28, 170), title, font=_font(18, True), fill="#ffe0c0")
        draw.text((x + 28, 210), str(count), font=_font(48, True), fill="#ffffff")
        draw.text((x + 28, 268), "saha", font=_font(16), fill="#f3e6d8")
        y = 330
        draw.text((x, y), title.title() + " listesi", font=_font(16, True), fill="#9bb0c7")
        y += 28
        show = names[:12] or ["(yok)"]
        for n in show:
            for line in _wrap(draw, "• " + n, _font(18), 400):
                draw.text((x, y), line, font=_font(18), fill="#e8eef5")
                y += 24
        if len(names) > 12:
            draw.text((x, y), f"… +{len(names) - 12} kayıt", font=_font(16), fill="#9bb0c7")
        x += 440

    draw.text((48, 840), f"Reverse geocoding uygulanan yeni saha: {geocoded}", font=_font(20), fill="#d7e3f0")
    return _to_jpg(img)


def table_card_jpg(title: str, rows: list[tuple[str, str]], footer: str = "") -> bytes:
    height = max(700, 200 + 70 * len(rows) + 80)
    img, draw = _card_base(1400, min(height, 1800), title)
    y = 150
    for label, value in rows[:22]:
        draw.text((56, y), str(label), font=_font(18, True), fill="#9bb0c7")
        draw.text((56, y + 26), str(value)[:90], font=_font(24), fill="#e8eef5")
        y += 64
    if footer:
        draw.text((56, min(y + 20, img.height - 50)), footer, font=_font(16), fill="#9bb0c7")
    return _to_jpg(img)


def _to_jpg(img: Image.Image) -> bytes:
    buf = BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=92, optimize=True)
    return buf.getvalue()
