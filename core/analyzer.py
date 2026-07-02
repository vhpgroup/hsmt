# -*- coding: utf-8 -*-
"""Điều phối phân tích: cache → AI nhận diện → search → so sánh → rủi ro khóa hãng."""
from . import cache
from .preprocess import item_key
from . import search as websearch


def risk_level(ident):
    if ident.get("khoa_hang"):
        return "CAO"
    tc = (ident.get("tin_cay") or "").lower()
    if "cao" in tc:
        return "TRUNG BÌNH" if ident.get("model", "").lower() != "hàng phổ thông" else "THẤP"
    return "THẤP"


def run(items, cfg, ai, progress=lambda s, p: None, counter=None, on_item=None):
    """Pipeline chính. on_item(row): callback bắn từng dòng ngay khi xong để UI hiển thị live."""
    ttl = int(cfg.get("ttl_days", 30))
    results, todo = {}, []
    for it in items:
        hit = cache.get(item_key(it, "identify"), ttl)
        if hit:
            results[it["id"]] = hit
        else:
            todo.append(it)
    # Nhận diện theo lô 6
    for i in range(0, len(todo), 6):
        batch = todo[i:i + 6]
        progress(f"AI nhận diện lô {i//6+1}/{(len(todo)+5)//6}…", 10 + int(30 * i / max(len(todo), 1)))
        try:
            arr = ai.identify_batch(batch)
        except Exception as e:
            arr = [{"stt": b["stt"], "model": f"Lỗi AI: {e}", "hang": "", "tin_cay": "Thấp", "can_cu": "", "khoa_hang": False} for b in batch]
        for b, r in zip(batch, arr):
            if "lỗi ai" not in str(r.get("model", "")).lower():  # KHÔNG cache kết quả lỗi
                cache.put(item_key(b, "identify"), r)
            results[b["id"]] = r
            if on_item:  # hiện ngay kết quả nhận diện, chưa cần chờ so sánh
                r0 = dict(b); r0["ident"] = r; r0["risk"] = risk_level(r)
                on_item(r0)
    # Các mục trúng cache nhận diện cũng bắn lên UI ngay
    if on_item:
        for it in items:
            if it not in todo and it["id"] in results:
                r0 = dict(it); r0["ident"] = results[it["id"]]; r0["risk"] = risk_level(r0["ident"])
                on_item(r0)
    # So sánh tương đương (nếu bật)
    out = []
    do_cmp = cfg.get("compare", True)
    for n, it in enumerate(items):
        ident = results.get(it["id"], {})
        row = dict(it); row["ident"] = ident; row["risk"] = risk_level(ident)
        if do_cmp and ident.get("model"):  # tra web MỌI hạng mục, yêu cầu ứng viên đạt 100%
            ck = item_key(it, "compare")
            cmp_hit = cache.get(ck, ttl)
            if not cmp_hit:
                progress(f"Tra cứu & so sánh: {it['ten'][:30]}…", 40 + int(55 * n / len(items)))
                ctx = websearch.build_context(it, ident, cfg, counter)
                try:
                    cmp_hit = ai.compare(it, ident, ctx)
                    cache.put(ck, cmp_hit)  # chỉ cache khi thành công
                except Exception as e:
                    cmp_hit = {"tieu_chi": [], "ung_vien": [], "nhan_xet": f"Lỗi: {e}"}
            row["so_sanh"] = cmp_hit
        out.append(row)
        if on_item:  # cập nhật dòng này ngay khi so sánh xong
            on_item(row)
    return out
