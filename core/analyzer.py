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


def _dir_ops(s):
    """Trả về (có_≥, có_≤) từ chuỗi — chuẩn hóa >= <= và biến thể."""
    s = (s or "").replace(">=", "≥").replace("<=", "≤").replace("≧", "≥").replace("≦", "≤")
    return ("≥" in s or ">" in s.replace("≥", ""), "≤" in s or "<" in s.replace("≤", ""))


def _fix_operator(row):
    """Chốt cứng chống đảo dấu: nếu 'gia_tri' lệch chiều ≥/≤ so với 'nguyen_van' → sửa theo nguyen_van (chân lý)."""
    nv, gv = row.get("nguyen_van", ""), row.get("gia_tri", "")
    if not nv or not gv:
        return row
    nv_ge, nv_le = _dir_ops(nv)
    gv_ge, gv_le = _dir_ops(gv)
    # nguyen_van chỉ 1 chiều rõ ràng, gia_tri lại chiều NGƯỢC → đảo lại
    if nv_ge and not nv_le and gv_le and not gv_ge:
        row["gia_tri"] = gv.replace("<=", "≥").replace("≤", "≥").replace("<", "≥")
        row["_canh_bao_dao_dau"] = f"Đã sửa chiều toán tử theo HSMT gốc: {nv}"
    elif nv_le and not nv_ge and gv_ge and not gv_le:
        row["gia_tri"] = gv.replace(">=", "≤").replace("≥", "≤").replace(">", "≤")
        row["_canh_bao_dao_dau"] = f"Đã sửa chiều toán tử theo HSMT gốc: {nv}"
    return row


def _filter_specs(spec):
    out = dict(spec or {})
    rows = []
    for row in out.get("thong_so") or []:
        blob = f"{row.get('ten', '')} {row.get('gia_tri', '')}"
        if not _is_windows_11_pro(blob):
            rows.append(_fix_operator(row))
    out["thong_so"] = rows
    # áp cả cho thông số của từng thiết bị con (thanh_phan)
    for comp in out.get("thanh_phan") or []:
        comp["thong_so"] = [_fix_operator(r) for r in (comp.get("thong_so") or [])
                            if not _is_windows_11_pro(f"{r.get('ten','')} {r.get('gia_tri','')}")]
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


VERIFY_CTX_LIMIT = 24000  # phải khớp với giới hạn ngữ cảnh trong ai_engine.compare


def _norm_loose(text):
    """Chuẩn hóa 'lỏng' để so trích dẫn: bỏ dấu cách/ký tự đặc biệt — chịu được '10KVA / 10KW' vs '10KVA/10KW'."""
    return re.sub(r"[^a-z0-9à-ỹ]", "", (text or "").lower())


def _verify_quotes(result, ctx):
    """Kiểm chứng máy: từng 'trich_dan' phải xuất hiện NGUYÊN VĂN trong ngữ cảnh đã đưa cho AI.
    Trích dẫn không khớp = AI bịa/nhớ nhầm → loại ứng viên (dat_100=False)."""
    if not isinstance(result, dict) or not ctx:
        return result
    hay = _norm_loose(ctx[:VERIFY_CTX_LIMIT])
    for candidate in result.get("ung_vien", []) or []:
        bad = []
        for row in candidate.get("bang", []) or []:
            q = _norm_loose(row.get("trich_dan", ""))
            if len(q) < 12 or q not in hay:
                bad.append(row.get("yeu_cau", "?"))
                row["danh_gia"] = "~ Chưa xác minh (trích dẫn không khớp nguồn)"
        if bad:
            candidate["dat_100"] = False
            candidate["ly_do_loai"] = "Trích dẫn không tìm thấy trong nguồn: " + ", ".join(bad[:5])
    return result


def _norm_brand(brand):
    import unicodedata
    s = unicodedata.normalize("NFD", brand or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", s)


# Ngoại lệ: hãng thuộc tập đoàn có domain khác tên (APC→Schneider, Ricoh/Fujitsu scanner→PFU...)
CORP_DOMAINS = ("se.com", "pfu.ricoh", "ricoh.com", "fujitsu.com", "hpe.com", "hp.com", "mi.com")


def _check_official_source(result):
    """PHÂN LOẠI nguồn (không loại): domain khớp tên hãng → 'Chính hãng', còn lại → 'Đại lý/tổng hợp'.
    Chính hãng được ƯU TIÊN xếp trước; nguồn đại lý vẫn hợp lệ nhưng gắn nhãn khuyến nghị xác nhận."""
    if not isinstance(result, dict):
        return result
    for candidate in result.get("ung_vien", []) or []:
        url = str(candidate.get("nguon", ""))
        try:
            domain = url.split("/")[2].lower()
        except IndexError:
            domain = url.lower()
        brand = _norm_brand(candidate.get("hang", ""))
        labels = domain.split(".")
        ok = bool(brand) and (labels[0].replace("-", "") == brand or any(l.replace("-", "") == brand for l in labels[:2]))
        ok = ok or any(c in domain for c in CORP_DOMAINS)
        candidate["nguon_loai"] = "Chính hãng" if ok else "Đại lý/tổng hợp — nên xin datasheet hãng xác nhận"
    # Ưu tiên chính hãng lên đầu danh sách
    result["ung_vien"] = sorted(result.get("ung_vien") or [],
                                key=lambda u: 0 if str(u.get("nguon_loai", "")).startswith("Chính hãng") else 1)
    return result


def _flag_hsmt_model(result, item):
    """A+: gắn nhãn ứng viên TRÙNG model HSMT nhắm tới — CHỈ khi tên model/hãng khớp NGUYÊN VĂN
    chuỗi trong ô thông số HSMT (dấu hiệu chắc chắn, không đoán). Hãng khác xếp TRƯỚC (ưu tiên thay thế)."""
    if not isinstance(result, dict):
        return result
    hay = _norm_loose(item.get("thongso", ""))
    for c in result.get("ung_vien", []) or []:
        model_tokens = [t for t in re.split(r"[\s/\-]+", str(c.get("model", ""))) if len(_norm_loose(t)) >= 3]
        model_hit = any(_norm_loose(t) in hay for t in model_tokens)
        brand_hit = bool(_norm_loose(c.get("hang", ""))) and _norm_loose(c.get("hang", "")) in hay
        c["trung_hsmt"] = bool(model_hit or brand_hit)
        if c["trung_hsmt"]:
            c["nhan_hsmt"] = "⚠ Trùng model HSMT nhắm tới (kiểm tra ràng buộc thương hiệu)"
    # Hãng KHÁC (không trùng HSMT) xếp trước; giữ ưu tiên chính hãng trong từng nhóm
    prev = result.get("ung_vien") or []
    result["ung_vien"] = sorted(
        prev,
        key=lambda u: (1 if u.get("trung_hsmt") else 0,
                       0 if str(u.get("nguon_loai", "")).startswith("Chính hãng") else 1),
    )
    return result


def _only_100_percent(result, spec, item=None):
    result = _normalize_compare_rows(result, spec)
    if item is not None:
        result = _flag_hsmt_model(result, item)
    all_cands = result.get("ung_vien", []) or []
    kept = [u for u in all_cands if _is_passing_candidate(u)]
    out = dict(result)
    out["ung_vien"] = kept
    if not kept:
        # KHÔNG giữ nhan_xet cũ của AI (dễ mâu thuẫn kiểu "đã tìm thấy X đạt 100%") — ghi đúng thực tế sau kiểm chứng
        dropped = [u for u in all_cands if u.get("ly_do_loai")]
        if dropped:
            reasons = "; ".join(f"{u.get('model', '?')} bị loại ({u.get('ly_do_loai', '')})" for u in dropped[:3])
            out["nhan_xet"] = f"Không có model đạt 100% sau kiểm chứng máy. {reasons}"
        else:
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
        hit = cache.get(item_key(it, "specs_v8"), ttl)
        if hit:
            results[it["id"]] = hit
        else:
            todo.append(it)

    # Lô động: tối đa 6 mục VÀ tổng ≤6.000 ký tự — tránh JSON output bị cắt với mục dài
    batches, _cur, _size = [], [], 0
    for _it in todo:
        _ln = len(_it.get("thongso", ""))
        if _cur and (len(_cur) >= 6 or _size + _ln > 6000):
            batches.append(_cur); _cur, _size = [], 0
        _cur.append(_it); _size += _ln
    if _cur:
        batches.append(_cur)
    _done = 0
    for _bi, batch in enumerate(batches):
        wait_if_needed()
        progress(f"AI trích thông số lô {_bi+1}/{len(batches)}...", 10 + int(30 * _done / max(len(todo), 1)))
        _done += len(batch)
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
        # GHÉP THEO STT (không ghép theo vị trí) — chống lệch cột khi AI tách 1 mục thành nhiều phần tử
        by_stt = {}
        for r in arr:
            key = str(r.get("stt", "")).strip().rstrip(".")
            if key in by_stt:  # mục bị tách (UPS/tủ/ắc quy...) → gộp thông số về đúng STT
                by_stt[key]["thong_so"] = (by_stt[key].get("thong_so") or []) + (r.get("thong_so") or [])
            else:
                by_stt[key] = r
        for b in batch:
            wait_if_needed()
            r = by_stt.get(str(b.get("stt", "")).strip().rstrip("."))
            if r is None:
                r = _filter_specs({"stt": b["stt"], "loai_thiet_bi": b.get("ten", ""), "thong_so": [],
                                   "tin_cay": "Thấp", "can_cu": "Lỗi AI: thiếu phần tử STT trong JSON trả về",
                                   "tu_khoa_tim": b.get("ten", "")})
            if "lỗi ai" not in str(r.get("can_cu", "")).lower():
                cache.put(item_key(b, "specs_v8"), r)
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

    # ===== TÁCH THIẾT BỊ CON: hạng mục nhiều thành phần → hàng riêng 1a/1b/1c, mỗi hàng tìm model 100% riêng =====
    letters = "abcdefghijklmnopqrstuvwxyz"
    work = []
    for it in items:
        spec = _filter_specs(results.get(it["id"], {}))
        comps = [c for c in (spec.get("thanh_phan") or []) if (c or {}).get("thong_so")]
        if len(comps) >= 2:
            for ci, comp in enumerate(comps[:26]):
                sub = dict(it)
                sub["stt"] = f"{it['stt']}{letters[ci]}"
                sub["ten"] = f"{it['ten']} — {comp.get('ten_thiet_bi', '') or f'Thành phần {ci + 1}'}"
                sub["id"] = it["id"] if ci == 0 else f"{it['id']}#{ci}"
                sub_specs = comp.get("thong_so") or []
                sub["thongso"] = "\n".join(
                    (s.get("nguyen_van") or f"{s.get('ten', '')}: {s.get('gia_tri', '')}") for s in sub_specs)
                sub["ident"] = _filter_specs({
                    "stt": sub["stt"], "loai_thiet_bi": comp.get("ten_thiet_bi", ""),
                    "tin_cay": spec.get("tin_cay", ""), "can_cu": spec.get("can_cu", ""),
                    "thong_so": sub_specs,
                    "tu_khoa_tim": comp.get("tu_khoa_tim") or comp.get("ten_thiet_bi", ""),
                })
                work.append(sub)
        else:
            row0 = dict(it)
            row0["ident"] = spec
            work.append(row0)

    out = []
    do_cmp = cfg.get("compare", True)
    for n, it in enumerate(work):
        wait_if_needed()
        spec = it["ident"]
        row = it
        row["risk"] = risk_level(spec)
        if do_cmp and (spec.get("thong_so") or spec.get("tu_khoa_tim")):
            ck = item_key(it, "compare_v13")
            cmp_hit = cache.get(ck, ttl)
            if not cmp_hit:
                wait_if_needed()
                progress(f"Serper tìm & AI đối chiếu đạt 100%: {it['ten'][:30]}...", 40 + int(55 * n / max(len(work), 1)))
                ctx = websearch.build_context(it, spec, cfg, counter)
                try:
                    raw_cmp = ai.compare(it, spec, ctx)
                    raw_cmp = _verify_quotes(raw_cmp, ctx)  # máy dò lại từng trích dẫn — bịa là loại
                    raw_cmp = _check_official_source(raw_cmp)  # domain nguồn phải là chính hãng
                    cmp_hit = _only_100_percent(raw_cmp, spec, it)
                    cache.put(ck, cmp_hit)
                except Exception as e:
                    cmp_hit = {"tieu_chi": [], "ung_vien": [], "nhan_xet": f"Lỗi: {e}"}
            row["so_sanh"] = cmp_hit
        out.append(row)
        if on_item:
            on_item(row)
    return out
