# -*- coding: utf-8 -*-
"""Làm sạch, gộp dòng, chuẩn hóa hạng mục."""
import hashlib, re


def _norm(s):
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def item_key(item, kind="identify"):
    """Khóa cache theo NỘI DUNG thông số (không phụ thuộc tên file)."""
    raw = kind + "|" + _norm(item.get("ten")) + "|" + _norm(item.get("thongso"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def stt_sort_key(stt):
    """Khóa sắp xếp STT tự nhiên: '1' < '1a' < '1b' < '2' < '10'.
    Pipeline song song trả hàng theo thứ tự HOÀN THÀNH — UI phải sort lại theo khóa này
    để bảng live không nhảy loạn vị trí giữa các lần cập nhật."""
    m = re.match(r"^\s*(\d+)\s*([a-z]*)", str(stt or "").lower())
    if not m:
        return (10 ** 9, str(stt or ""))
    return (int(m.group(1)), m.group(2))


def clean(items):
    """KHÔNG gộp dòng trùng — có bao nhiêu mục giữ bấy nhiêu, đúng thứ tự file.
    Các dòng trùng nội dung tự dùng chung cache (item_key theo nội dung) nên không tốn thêm credit."""
    out = []
    for idx, it in enumerate(items):
        ten, ts = it.get("ten", "").strip(), it.get("thongso", "").strip()
        if not ten or ten.lower() in ("tên hàng hóa",):
            continue
        ts = re.sub(r"[ \t]+", " ", ts)
        rec = {"stt": str(it.get("stt", "")).strip() or str(idx + 1), "ten": ten, "thongso": ts}
        rec["id"] = item_key(rec) + f"#{idx}"  # id duy nhất theo vị trí, cache key vẫn theo nội dung
        out.append(rec)
    return out
