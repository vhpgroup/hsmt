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


def run(items, cfg, ai, progress=lambda s, p: None, counter=None):
    """Pipeline chính. Trả {items:[{...ident, so_sanh}], duties, usage}."""
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
            cache.put(item_key(b, "identify"), r)
            results[b["id"]] = r
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
                except Exception as e:
                    cmp_hit = {"tieu_chi": [], "ung_vien": [], "nhan_xet": f"Lỗi: {e}"}
                cache.put(ck, cmp_hit)
            row["so_sanh"] = cmp_hit
        out.append(row)
    return out
