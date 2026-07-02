# -*- coding: utf-8 -*-
"""Pipeline: cache -> AI trích thông số -> web search -> AI đối chiếu -> chỉ giữ model đạt 100%."""
import re

from . import cache
from . import search as websearch
from .preprocess import item_key


def risk_level(spec):
    tc = (spec.get("tin_cay") or "").lower()
    if "cao" in tc:
        return "Cao"
    if "trung" in tc:
        return "Trung bình"
    return "Thấp"


def _is_windows_11_pro(text):
    s = (text or "").lower()
    return bool(
        re.search(r"\bwindows\s*11\s*(pro|professional)\b", s)
        or re.search(r"\bwin\s*11\s*pro\b", s)
    )


def _strip_windows_terms(text):
    s = text or ""
    s = re.sub(r"\bWindows\s*11\s*(Pro|Professional)\b", " ", s, flags=re.I)
    s = re.sub(r"\bWin\s*11\s*Pro\b", " ", s, flags=re.I)
    return re.sub(r"\s+", " ", s).strip()


def _filter_specs(spec):
    out = dict(spec or {})
    rows = []
    for row in out.get("thong_so") or []:
        blob = f"{row.get('ten', '')} {row.get('gia_tri', '')}"
        if not _is_windows_11_pro(blob):
            rows.append(row)
    out["thong_so"] = rows
    out["tu_khoa_tim"] = _strip_windows_terms(out.get("tu_khoa_tim", ""))
    return out


def _norm(text):
    text = (text or "").lower()
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _hsmt_value_for(spec, criterion):
    crit = _norm(criterion)
    for row in spec.get("thong_so") or []:
        name = _norm(row.get("ten"))
        if name and (name in crit or crit in name):
            return row.get("gia_tri", "")
    return ""


def _normalize_compare_rows(result, spec):
    if not isinstance(result, dict):
        return {"ung_vien": [], "nhan_xet": "Không tìm thấy model đạt 100%."}
    for candidate in result.get("ung_vien", []) or []:
        clean_rows = []
        for row in candidate.get("bang", []) or []:
            criterion = row.get("yeu_cau", "")
            hsmt_value = row.get("thong_so_hsmt") or _hsmt_value_for(spec, criterion)
            if _is_windows_11_pro(f"{criterion} {hsmt_value}"):
                continue
            normalized = dict(row)
            normalized["thong_so_hsmt"] = hsmt_value
            clean_rows.append(normalized)
        candidate["bang"] = clean_rows
    return result


def _is_passing_candidate(candidate):
    if not candidate.get("dat_100"):
        return False
    rows = candidate.get("bang") or []
    if not rows:
        return False
    for row in rows:
        verdict = str(row.get("danh_gia", "")).strip().lower()
        if verdict not in ("dat", "vuot", "đạt", "vượt"):
            return False
    return True


def _only_100_percent(result, spec):
    result = _normalize_compare_rows(result, spec)
    kept = [u for u in result.get("ung_vien", []) if _is_passing_candidate(u)]
    out = dict(result)
    out["ung_vien"] = kept
    if not kept:
        out["nhan_xet"] = result.get("nhan_xet") or "Không tìm thấy model đạt 100% với nguồn chính hãng."
    return out


def run(items, cfg, ai, progress=lambda s, p: None, counter=None, on_item=None, pause_check=None):
    """Pipeline chính. on_item(row): callback từng dòng ngay khi xong để UI hiển thị live."""
    def wait_if_needed():
        if pause_check:
            pause_check()

    ttl = int(cfg.get("ttl_days", 30))
    results, todo = {}, []
    for it in items:
        wait_if_needed()
        hit = cache.get(item_key(it, "specs_v5"), ttl)
        if hit:
            results[it["id"]] = hit
        else:
            todo.append(it)

    for i in range(0, len(todo), 6):
        wait_if_needed()
        batch = todo[i:i + 6]
        progress(f"AI trích thông số lô {i//6+1}/{(len(todo)+5)//6}...", 10 + int(30 * i / max(len(todo), 1)))
        try:
            ai_specs = ai.extract_specs_batch(batch)
            arr = [_filter_specs(x) for x in ai_specs]
        except Exception as e:
            arr = [
                _filter_specs({
                    "stt": b["stt"],
                    "loai_thiet_bi": b.get("ten", ""),
                    "thong_so": [],
                    "tin_cay": "Thấp",
                    "can_cu": f"Lỗi AI: {e}",
                    "tu_khoa_tim": b.get("ten", ""),
                })
                for b in batch
            ]
        for b, r in zip(batch, arr):
            wait_if_needed()
            if "lỗi ai" not in str(r.get("can_cu", "")).lower():
                cache.put(item_key(b, "specs_v5"), r)
            results[b["id"]] = r
            if on_item:
                r0 = dict(b)
                r0["ident"] = r
                r0["risk"] = risk_level(r)
                on_item(r0)

    if on_item:
        for it in items:
            if it not in todo and it["id"] in results:
                r0 = dict(it)
                r0["ident"] = results[it["id"]]
                r0["risk"] = risk_level(r0["ident"])
                on_item(r0)

    out = []
    do_cmp = cfg.get("compare", True)
    for n, it in enumerate(items):
        wait_if_needed()
        spec = _filter_specs(results.get(it["id"], {}))
        row = dict(it)
        row["ident"] = spec
        row["risk"] = risk_level(spec)
        if do_cmp and (spec.get("thong_so") or spec.get("tu_khoa_tim")):
            ck = item_key(it, "compare_v6")
            cmp_hit = cache.get(ck, ttl)
            if not cmp_hit:
                wait_if_needed()
                progress(f"Serper tìm & AI đối chiếu đạt 100%: {it['ten'][:30]}...", 40 + int(55 * n / max(len(items), 1)))
                ctx = websearch.build_context(it, spec, cfg, counter)
                try:
                    cmp_hit = _only_100_percent(ai.compare(it, spec, ctx), spec)
                    cache.put(ck, cmp_hit)
                except Exception as e:
                    cmp_hit = {"tieu_chi": [], "ung_vien": [], "nhan_xet": f"Lỗi: {e}"}
            row["so_sanh"] = cmp_hit
        out.append(row)
        if on_item:
            on_item(row)
    return out
