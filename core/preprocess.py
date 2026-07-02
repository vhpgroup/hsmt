# -*- coding: utf-8 -*-
"""Làm sạch, gộp dòng, chuẩn hóa hạng mục."""
import hashlib, re


def _norm(s):
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def item_key(item, kind="identify"):
    """Khóa cache theo NỘI DUNG thông số (không phụ thuộc tên file)."""
    raw = kind + "|" + _norm(item.get("ten")) + "|" + _norm(item.get("thongso"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def clean(items):
    out, seen = [], {}
    for it in items:
        ten, ts = it.get("ten", "").strip(), it.get("thongso", "").strip()
        if not ten or ten.lower() in ("tên hàng hóa",):
            continue
        ts = re.sub(r"[ \t]+", " ", ts)
        key = _norm(ten) + "|" + _norm(ts)
        if key in seen:  # dòng lặp (Cat6, RJ45, SFP...)
            seen[key]["stt"] += f", {it.get('stt', '')}"
            continue
        rec = {"stt": str(it.get("stt", "")).strip(), "ten": ten, "thongso": ts}
        rec["id"] = item_key(rec)
        seen[key] = rec
        out.append(rec)
    return out
