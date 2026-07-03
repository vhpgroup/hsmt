# -*- coding: utf-8 -*-
"""Pipeline: cache -> AI trích thông số -> web search -> AI đối chiếu -> chỉ giữ model đạt 100%.
Chạy SONG SONG có kiểm soát: lô extract song song, từng hàng (dòng con) song song; semaphore
chống dội rate-limit nằm ở core.search; UI callbacks (Qt Signal.emit / threading.Event) đều thread-safe."""
import copy
import re
import threading
from concurrent import futures

from . import cache
from . import search as websearch
from .ai_engine import CMP_CTX_LIMIT
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


def _adapt_ai_spec_schema(spec):
    """Map the strict extraction JSON schema into the legacy internal shape."""
    if not isinstance(spec, dict) or "hang_muc_con" not in spec:
        return spec

    out = dict(spec)
    comps = []
    flat_rows = []
    for comp in spec.get("hang_muc_con") or []:
        if not isinstance(comp, dict):
            continue
        comp_name = comp.get("ten_hang_muc_con") or spec.get("ten_hang_hoa_muc") or ""
        rows = []
        for row in comp.get("thong_so") or []:
            if not isinstance(row, dict):
                continue
            mapped = {
                "nhom": row.get("nhom_thong_so"),
                "ten": row.get("ten_thong_so", ""),
                "gia_tri": row.get("gia_tri_yeu_cau", ""),
                "don_vi": row.get("don_vi"),
                "toan_tu_so_sanh": row.get("toan_tu_so_sanh", ""),
                "gia_tri_so": row.get("gia_tri_so"),
                "gia_tri_so_min": row.get("gia_tri_so_min"),
                "gia_tri_so_max": row.get("gia_tri_so_max"),
                "loai_du_lieu": row.get("loai_du_lieu", ""),
                "muc_do": row.get("muc_do", ""),
                "nguyen_van": row.get("trich_dan_nguon") or row.get("nguyen_van") or "",
            }
            rows.append(mapped)
            flat_rows.append(mapped)
        comps.append({
            "ten_thiet_bi": comp_name,
            "trang_thai_thong_so": comp.get("trang_thai_thong_so") or ("co_thong_so" if rows else "khong_co_thong_so"),
            "loai_hang_muc": comp.get("loai_hang_muc") or ("doc_lap" if rows else "phu_kien_di_kem"),
            "phu_thuoc_hang_muc_con": comp.get("phu_thuoc_hang_muc_con"),
            "tu_khoa_tim": " ".join([comp_name] + [r.get("gia_tri", "") for r in rows[:4]]).strip(),
            "thong_so": rows,
        })

    out["loai_thiet_bi"] = out.get("loai_thiet_bi") or out.get("ten_hang_hoa_muc", "")
    out["thanh_phan"] = comps
    out["thong_so"] = flat_rows
    out["tu_khoa_tim"] = out.get("tu_khoa_tim") or " ".join(
        [out.get("loai_thiet_bi", "")] + [r.get("gia_tri", "") for r in flat_rows[:6]]
    ).strip()
    if not out.get("can_cu"):
        names = ", ".join(c.get("ten_thiet_bi", "") for c in comps if c.get("ten_thiet_bi"))
        out["can_cu"] = f"Yeu cau ky thuat ve {names}" if names else out.get("loai_thiet_bi", "")
    return out


def _norm(text):
    text = (text or "").lower()
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _name_tokens(s):
    return {t for t in re.split(r"[^a-z0-9à-ỹ]+", _norm(s)) if len(t) >= 2}


def _similar_name(a, b):
    """Dedup MỜ (B3-2): trùng ≥60% token (theo tập nhỏ hơn) hoặc chuỗi chứa nhau → coi là một."""
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return na == nb
    if na in nb or nb in na:
        return True
    ta, tb = _name_tokens(a), _name_tokens(b)
    if not ta or not tb:
        return False
    return len(ta & tb) / min(len(ta), len(tb)) >= 0.6


def _extra_empty_components_from_text(item, existing):
    """Keep named child items that have no spec rows, e.g. Rail Kit accessories."""
    existing_names = [(c.get("ten_thiet_bi") or c.get("ten_hang_muc_con") or "") for c in existing or []]
    out = []
    text = item.get("thongso", "") or ""
    for m in re.finditer(r"(?m)^\s*\d+/\s*([^\n]+?)\s*$", text):
        name = m.group(1).strip(" .:-")
        if not name or any(_similar_name(name, e) for e in existing_names):
            continue          # dedup mờ: AI đã bắt dưới tên hơi khác → không nhân đôi hàng
        if re.search(r"\brail\s*kit\b|thanh\s+trượt|thanh\s+truot", name, re.I):
            parent = (existing or [{}])[0].get("ten_thiet_bi") or item.get("ten", "")
            out.append({
                "ten_thiet_bi": name,
                "trang_thai_thong_so": "khong_co_thong_so",
                "loai_hang_muc": "phu_kien_di_kem",
                "phu_thuoc_hang_muc_con": parent,
                "tu_khoa_tim": name,
                "thong_so": [],
            })
    return out


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


def _is_passing_candidate(candidate, optional=None):
    """Đạt 100% = mọi dòng BẮT BUỘC Đạt/Vượt. Dòng thuộc tiêu chí muc_do=khong_ro (A5)
    không quyết định kết quả — tránh loại oan vì 1 dòng mơ hồ không phải thông số."""
    if not candidate.get("dat_100"):
        return False
    rows = candidate.get("bang") or []
    if not rows:
        return False
    seen_required = False
    for row in rows:
        verdict = str(row.get("danh_gia", "")).strip().lower()
        if verdict in ("dat", "vuot", "đạt", "vượt"):
            seen_required = True
            continue
        if _in_optional(_norm(row.get("yeu_cau")), optional):
            continue          # tiêu chí không bắt buộc — không tính rớt
        return False
    return seen_required


VERIFY_CTX_LIMIT = CMP_CTX_LIMIT  # 1 nguồn sự thật duy nhất — luôn khớp giới hạn ngữ cảnh ai_engine.compare


def _norm_loose(text):
    """Chuẩn hóa 'lỏng' để so trích dẫn: bỏ dấu cách/ký tự đặc biệt — chịu được '10KVA / 10KW' vs '10KVA/10KW'."""
    return re.sub(r"[^a-z0-9à-ỹ]", "", (text or "").lower())


def _in_optional(crit_norm, optional):
    return any(o and (o in crit_norm or crit_norm in o) for o in (optional or ()))


def _verify_quotes(result, ctx, optional=None):
    """Kiểm chứng máy: từng 'trich_dan' phải xuất hiện NGUYÊN VĂN trong ngữ cảnh đã đưa cho AI.
    Trích dẫn không khớp = AI bịa/nhớ nhầm → loại ứng viên (dat_100=False).
    A5: dòng thuộc tiêu chí KHÔNG bắt buộc (muc_do=khong_ro) mà AI ghi 'Chưa rõ' thì không đòi trích dẫn."""
    if not isinstance(result, dict) or not ctx:
        return result
    hay = _norm_loose(ctx[:VERIFY_CTX_LIMIT])
    for candidate in result.get("ung_vien", []) or []:
        bad = []
        for row in candidate.get("bang", []) or []:
            verdict = str(row.get("danh_gia", "")).strip().lower()
            if not _pass_verdict(verdict) and _in_optional(_norm(row.get("yeu_cau")), optional):
                continue          # tiêu chí không bắt buộc, AI không nhận đạt → không cần bằng chứng
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


# Ngoại lệ: hãng thuộc tập đoàn có domain khác tên (APC→Schneider, Ricoh/Fujitsu scanner→PFU,
# ắc quy Long/Kung Long→klb.com.tw...)
CORP_DOMAINS = ("se.com", "pfu.ricoh", "ricoh.com", "fujitsu.com", "hpe.com", "hp.com", "mi.com",
                "klb.com.tw", "kunglong")


def _check_official_source(result):
    """PHÂN LOẠI nguồn (không loại): domain khớp tên hãng → 'Chính hãng', còn lại → 'Đại lý/tổng hợp'.
    Chính hãng được ƯU TIÊN xếp trước; nguồn đại lý vẫn hợp lệ nhưng gắn nhãn khuyến nghị xác nhận.
    A6: so 'chứa' thay vì 'bằng tuyệt đối' — arestech.vn khớp brand ARES, santak-vn khớp Santak."""
    if not isinstance(result, dict):
        return result
    for candidate in result.get("ung_vien", []) or []:
        url = str(candidate.get("nguon", ""))
        try:
            domain = url.split("/")[2].lower()
        except IndexError:
            domain = url.lower()
        brand = _norm_brand(candidate.get("hang", ""))
        labels = [l.replace("-", "") for l in domain.split(".")]
        ok = bool(brand) and len(brand) >= 3 and any(
            l and (brand in l or (len(l) >= 3 and l in brand)) for l in labels[:2])
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


def _pass_verdict(v):
    return str(v or "").strip().lower() in ("dat", "vuot", "đạt", "vượt")


def _candidate_percent(cand):
    """% dòng Đạt/Vượt trên tổng số dòng của ứng viên."""
    rows = cand.get("bang") or []
    if not rows:
        return 0
    ok = sum(1 for r in rows if _pass_verdict(r.get("danh_gia")))
    return round(100 * ok / len(rows))


def _missing_rows(cand):
    return [r for r in (cand.get("bang") or []) if not _pass_verdict(r.get("danh_gia"))]


def _best_effort(cands):
    """Chọn ứng viên gần nhất (%, cao nhất) để gắn cờ 'cần review thủ công' khi không có model 100%."""
    scored = [(c, _candidate_percent(c)) for c in (cands or []) if (c.get("bang"))]
    if not scored:
        return None
    scored.sort(key=lambda x: x[1], reverse=True)
    c, pct = scored[0]
    return {"model": c.get("model", ""), "hang": c.get("hang", ""), "phan_tram": pct,
            "nguon": c.get("nguon", ""), "thieu": [r.get("yeu_cau", "") for r in _missing_rows(c)][:8]}


def _only_100_percent(result, spec, item=None, optional=None):
    result = _normalize_compare_rows(result, spec)
    if item is not None:
        result = _flag_hsmt_model(result, item)
    all_cands = result.get("ung_vien", []) or []
    kept = [u for u in all_cands if _is_passing_candidate(u, optional)]
    # Ghi chú rõ các dòng không bắt buộc được bỏ qua (minh bạch cho báo cáo)
    for u in kept:
        for row in u.get("bang", []) or []:
            v = str(row.get("danh_gia", "")).strip().lower()
            if v not in ("dat", "vuot", "đạt", "vượt") and _in_optional(_norm(row.get("yeu_cau")), optional):
                row["danh_gia"] = str(row.get("danh_gia", "")).strip() or "Chưa rõ"
                if "không bắt buộc" not in row["danh_gia"]:
                    row["danh_gia"] += " (tiêu chí không bắt buộc)"
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


# ===================== A1 — MÁY SO SỐ HỌC =====================
# Code tự so sánh số với toan_tu_so_sanh + gia_tri_so (schema đã tách sẵn) — KHÔNG tin verdict AI ở khâu số.
# Nguyên tắc an toàn: chỉ ĐÁNH RỚT khi mọi cách đọc số đều vi phạm; không bao giờ nâng điểm; đơn vị lạ thì bỏ qua.
_UNIT_SCALE = {
    "w": ("w", 1), "kw": ("w", 1e3),
    "va": ("va", 1), "kva": ("va", 1e3),
    "hz": ("hz", 1), "khz": ("hz", 1e3), "mhz": ("hz", 1e6), "ghz": ("hz", 1e9),
    "bps": ("bps", 1), "kbps": ("bps", 1e3), "mbps": ("bps", 1e6), "gbps": ("bps", 1e9),
    "pps": ("pps", 1), "kpps": ("pps", 1e3), "mpps": ("pps", 1e6),
    "v": ("v", 1), "kv": ("v", 1e3), "vdc": ("v", 1), "vac": ("v", 1),
    "a": ("a", 1), "ma": ("a", 1e-3),
    "ah": ("ah", 1), "mah": ("ah", 1e-3),
    "mm": ("mm", 1), "cm": ("mm", 10),
    "gb": ("gb", 1), "tb": ("gb", 1024), "mb": ("gb", 1.0 / 1024),
    "inch": ("inch", 1), '"': ("inch", 1),
    "nit": ("nit", 1), "nits": ("nit", 1), "cd/m2": ("nit", 1), "cd/m²": ("nit", 1),
    "db": ("db", 1), "dbi": ("dbi", 1), "kg": ("kg", 1), "%": ("%", 1),
}
_QTY_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*([a-zA-Zµ%\"²/]{0,6})")


def _num_variants(tok):
    """'23,8'→[23.8] · '86.5'→[86.5] · '1.300'→[1.3, 1300.0] (dấu chấm 3 số cuối: mơ hồ thập phân vs
    phân cách nghìn kiểu VN — trả cả hai; máy so chỉ đánh rớt khi MỌI cách đọc đều vi phạm)."""
    s = tok.strip()
    if "," in s:
        return [float(s.replace(".", "").replace(",", "."))]
    if "." in s:
        head, frac = s.rsplit(".", 1)
        vals = [float(s)]
        if len(frac) == 3:
            vals.append(float(head.replace(".", "") + frac))
        return vals
    return [float(s)]


def _comparable_values(text, unit_hint):
    """Rút các giá trị số so sánh được từ chuỗi giá trị model. unit_hint (don_vi của HSMT) nếu có
    → chỉ lấy số mang cùng đơn vị gốc; không có → lấy mọi số (kiểm tra 'yếu' nhưng không sai hướng)."""
    base_hint = _UNIT_SCALE.get((unit_hint or "").lower().strip("."), (None, 1))[0]
    out = []
    for m in _QTY_RE.finditer(str(text or "")):
        unit = m.group(2).lower().strip(".")
        base, scale = _UNIT_SCALE.get(unit, (unit, 1))
        if base_hint and base != base_hint:
            continue
        for v in _num_variants(m.group(1)):
            out.append(v * scale)
    return out


def _spec_need(srow):
    """Chuẩn hóa ngưỡng yêu cầu về đơn vị gốc (370 + 'kW' → 370000 w)."""
    need = float(srow.get("gia_tri_so"))
    unit = (srow.get("don_vi") or "").lower().strip(".")
    base, scale = _UNIT_SCALE.get(unit, (unit or None, 1))
    return need * scale, base


def _numeric_recheck(result, spec, optional=None):
    """A1 — chốt chặn cuối: dòng AI chấm Đạt/Vượt nhưng số máy so ra kém yêu cầu → hạ Không đạt + loại model."""
    if not isinstance(result, dict):
        return result
    spec_rows = [r for r in (spec.get("thong_so") or [])
                 if r.get("toan_tu_so_sanh") in (">=", "<=") and isinstance(r.get("gia_tri_so"), (int, float))]
    if not spec_rows:
        return result
    for cand in result.get("ung_vien", []) or []:
        viol = []
        for row in cand.get("bang", []) or []:
            if not _pass_verdict(row.get("danh_gia")):
                continue                                    # chỉ soát dòng AI nhận Đạt/Vượt
            crit = _norm(row.get("yeu_cau"))
            if _in_optional(crit, optional):
                continue
            srow = None
            for s in spec_rows:
                nm = _norm(s.get("ten"))
                if nm and (nm in crit or crit in nm):
                    srow = s
                    break
            if srow is None:
                continue
            need, base_unit = _spec_need(srow)
            got = _comparable_values(row.get("gia_tri", ""), srow.get("don_vi") or "")
            if not got:
                continue                                    # không đọc được số cùng đơn vị → giữ verdict AI
            op = srow["toan_tu_so_sanh"]
            ok = any((v >= need - 1e-9) if op == ">=" else (v <= need + 1e-9) for v in got)
            if not ok:
                row["danh_gia"] = "Không đạt (máy so số học)"
                row["may_so"] = f"model={got[:3]} {op} yêu_cầu={need:g}{(' ' + base_unit) if base_unit else ''} → sai"
                viol.append(row.get("yeu_cau", "?"))
        if viol:
            cand["dat_100"] = False
            prev = (cand.get("ly_do_loai") or "").strip()
            cand["ly_do_loai"] = (prev + " | " if prev else "") + "Máy so số học: " + ", ".join(viol[:4])
    return result


def _optional_crits(spec):
    """A5 — tập tiêu chí KHÔNG bắt buộc (muc_do=khong_ro): dòng mơ hồ không được quyền loại model."""
    return {_norm(r.get("ten")) for r in (spec.get("thong_so") or [])
            if str(r.get("muc_do", "")).strip() == "khong_ro" and r.get("ten")}


# ===================== B3-1 — LỌC VẬT TƯ THI CÔNG KHỎI TÌM KIẾM =====================
SEARCHABLE_KINDS = ("thong_so_ky_thuat", "tieu_chuan_chung_chi")


def _searchable_spec(spec):
    """Chỉ thông số kỹ thuật + tiêu chuẩn/chứng chỉ được dùng tìm kiếm & đối chiếu.
    vat_tu_thi_cong / yeu_cau_chung bị loại khỏi tiêu chí 100% (dòng 'dây, cos, CB' không phải datasheet).
    Trả (spec_đã_lọc, còn_dòng_tìm_được?, có_dòng_phi_sản_phẩm?)."""
    rows = spec.get("thong_so") or []
    keep = [r for r in rows if (r.get("loai_du_lieu") or "thong_so_ky_thuat") in SEARCHABLE_KINDS]
    out = dict(spec)
    out["thong_so"] = keep
    return out, bool(keep), len(keep) < len(rows)


def _make_batches(todo, max_items=3, max_chars=2000, solo_chars=800):
    """Lô ĐỘNG AN TOÀN TIMEOUT (rút kinh nghiệm run thật 36 STT: lô 6 mục × mục dài → output
    JSON strict 10-15K token → sinh >90s → ReadTimeout → CẢ LÔ rơi về thông số rỗng, 21/39 hàng hỏng).
    Luật mới:
    - Mục DÀI (> solo_chars ký tự) đi LÔ RIÊNG MỘT MÌNH — không kéo mục khác chết chung
    - Lô ghép chỉ nhận mục ngắn: tối đa max_items mục VÀ tổng ≤ max_chars ký tự
    Tốc độ giữ nguyên nhờ các lô chạy SONG SONG (parallel_ai) — gộp to không còn cần thiết."""
    batches, cur, size = [], [], 0
    for it in todo:
        ln = len(it.get("thongso", ""))
        if ln > solo_chars:
            if cur:
                batches.append(cur)
                cur, size = [], 0
            batches.append([it])          # mục dài: một mình một lô
            continue
        if cur and (len(cur) >= max_items or size + ln > max_chars):
            batches.append(cur)
            cur, size = [], 0
        cur.append(it)
        size += ln
    if cur:
        batches.append(cur)
    return batches


def run(items, cfg, ai, progress=lambda s, p: None, counter=None, on_item=None, pause_check=None):
    """Pipeline chính — SONG SONG có kiểm soát (S1). on_item(row): callback từng dòng ngay khi xong.
    - Lô extract chạy song song (parallel_ai, mặc định 3)
    - Từng hàng (dòng con 1a/1b/...) tìm kiếm + đối chiếu song song (parallel_items, mặc định 4)
    - Trong mỗi hàng: các engine/fetch song song tiếp ở core.search (semaphore chống 429)
    - progress/on_item là Qt Signal.emit (an toàn từ thread con); pause_check là Event.wait (chặn được mọi worker)"""
    cfg = dict(cfg)                                        # không sửa dict của caller
    cfg.setdefault("_lock", threading.Lock())              # khóa chung cho counter
    cfg.setdefault("_qcache", {"lock": threading.Lock(), "data": {}})   # S3: dedup query toàn phiên

    def wait_if_needed():
        if pause_check:
            pause_check()

    ttl = int(cfg.get("ttl_days", 30))
    results, todo = {}, []
    for it in items:
        wait_if_needed()
        hit = cache.get(item_key(it, "specs_v11"), ttl) or cache.get(item_key(it, "specs_v10"), ttl)
        if hit:
            results[it["id"]] = hit
        else:
            todo.append(it)

    # ===== GIAI ĐOẠN 1: AI trích thông số — lô động, các lô chạy SONG SONG =====
    batches = _make_batches(todo)
    _plock = threading.Lock()
    _pdone = {"n": 0}

    def _fallback_spec(b, msg):
        return _filter_specs({"stt": b["stt"], "loai_thiet_bi": b.get("ten", ""), "thong_so": [],
                              "tin_cay": "Thấp", "can_cu": msg, "tu_khoa_tim": b.get("ten", "")})

    def run_batch(batch):
        wait_if_needed()
        try:
            ai_specs = ai.extract_specs_batch(batch)
            arr = [_filter_specs(_adapt_ai_spec_schema(x)) for x in ai_specs]
        except Exception as e:
            if len(batch) > 1:
                # BISECT RETRY: lô lỗi (thường ReadTimeout vì output dài) → chia đôi chạy lại,
                # lỗi cuối cùng chỉ còn dính đúng 1 mục thay vì thiêu cả lô
                mid = len(batch) // 2
                return run_batch(batch[:mid]) + run_batch(batch[mid:])
            arr = [_fallback_spec(b, f"Lỗi AI: {e}") for b in batch]
        # GHÉP THEO STT (không ghép theo vị trí) — chống lệch cột khi AI tách 1 mục thành nhiều phần tử
        by_stt = {}
        for r in arr:
            key = str(r.get("stt", "")).strip().rstrip(".")
            if key in by_stt:  # mục bị tách (UPS/tủ/ắc quy...) → gộp thông số về đúng STT
                by_stt[key]["thong_so"] = (by_stt[key].get("thong_so") or []) + (r.get("thong_so") or [])
                extra = r.get("thanh_phan") or []
                if extra:
                    by_stt[key]["thanh_phan"] = (by_stt[key].get("thanh_phan") or []) + extra
            else:
                by_stt[key] = r
        out_rows = []
        for b in batch:
            r = by_stt.get(str(b.get("stt", "")).strip().rstrip("."))
            if r is None:
                r = _fallback_spec(b, "Lỗi AI: thiếu phần tử STT trong JSON trả về")
            if "lỗi ai" not in str(r.get("can_cu", "")).lower():
                try:
                    cache.put(item_key(b, "specs_v11"), r)
                except Exception:
                    pass
            out_rows.append((b, r))
        return out_rows

    if batches:
        n_ai = max(1, int(cfg.get("parallel_ai", 3)))
        with futures.ThreadPoolExecutor(max_workers=min(n_ai, len(batches))) as pool:
            futs = [pool.submit(run_batch, b) for b in batches]
            for f in futures.as_completed(futs):
                rows = f.result()
                with _plock:
                    _pdone["n"] += len(rows)
                    progress(f"AI trích thông số {_pdone['n']}/{len(todo)} mục...",
                             10 + int(30 * _pdone["n"] / max(len(todo), 1)))
                for b, r in rows:
                    results[b["id"]] = r
                    if on_item:
                        r0 = dict(b)
                        # deepcopy: GUI thread giữ bản RIÊNG — giai đoạn 2 còn mutate row dict
                        # (_fix_operator sửa gia_tri tại chỗ) trên bản trong pipeline
                        r0["ident"] = copy.deepcopy(r)
                        r0["risk"] = risk_level(r)
                        on_item(r0)

    if on_item:
        for it in items:
            if it not in todo and it["id"] in results:
                r0 = dict(it)
                r0["ident"] = copy.deepcopy(results[it["id"]])
                r0["risk"] = risk_level(r0["ident"])
                on_item(r0)

    # ===== TÁCH THIẾT BỊ CON: hạng mục nhiều thành phần → hàng riêng 1a/1b/1c, mỗi hàng tìm model 100% riêng =====
    letters = "abcdefghijklmnopqrstuvwxyz"
    work = []
    for it in items:
        spec = _filter_specs(results.get(it["id"], {}))
        comps = [c for c in (spec.get("thanh_phan") or []) if c]
        extras = _extra_empty_components_from_text(it, comps)
        if extras:
            comps.extend(extras)
            spec["thanh_phan"] = comps
        if len(comps) >= 2:
            primary_comp_name = next((c.get("ten_thiet_bi") for c in comps if (c or {}).get("thong_so")), it.get("ten", ""))
            for ci, comp in enumerate(comps[:26]):
                sub = dict(it)
                sub["stt"] = f"{it['stt']}{letters[ci]}"
                sub["ten"] = f"{it['ten']} — {comp.get('ten_thiet_bi', '') or f'Thành phần {ci + 1}'}"
                sub["id"] = it["id"] if ci == 0 else f"{it['id']}#{ci}"
                sub_specs = comp.get("thong_so") or []
                comp_status = comp.get("trang_thai_thong_so") or ("co_thong_so" if sub_specs else "khong_co_thong_so")
                comp_kind = comp.get("loai_hang_muc") or ("doc_lap" if sub_specs else "phu_kien_di_kem")
                sub["thongso"] = "\n".join(
                    (s.get("nguyen_van") or f"{s.get('ten', '')}: {s.get('gia_tri', '')}") for s in sub_specs)
                sub["ident"] = _filter_specs({
                    "stt": sub["stt"], "loai_thiet_bi": comp.get("ten_thiet_bi", ""),
                    "tin_cay": spec.get("tin_cay", ""), "can_cu": spec.get("can_cu", ""),
                    "thong_so": sub_specs,
                    "trang_thai_thong_so": comp_status,
                    "loai_hang_muc": comp_kind,
                    "phu_thuoc_hang_muc_con": comp.get("phu_thuoc_hang_muc_con") or (
                        primary_comp_name if comp_kind == "phu_kien_di_kem" else None
                    ),
                    "tu_khoa_tim": comp.get("tu_khoa_tim") or comp.get("ten_thiet_bi", ""),
                })
                work.append(sub)
        else:
            row0 = dict(it)
            row0["ident"] = spec
            work.append(row0)

    # ===== GIAI ĐOẠN 2: tìm kiếm + đối chiếu — TỪNG HÀNG CHẠY SONG SONG =====
    out = [None] * len(work)
    do_cmp = cfg.get("compare", True)
    _cdone = {"n": 0}

    def process(idx, it):
        wait_if_needed()
        spec = it["ident"]
        row = it
        row["risk"] = risk_level(spec)
        search_spec, has_searchable, has_nonproduct = _searchable_spec(spec)
        all_rows = spec.get("thong_so") or []
        has_vattu = any((r.get("loai_du_lieu") or "") == "vat_tu_thi_cong" for r in all_rows)
        if not has_searchable and all_rows and not has_vattu:
            # Toàn dòng yeu_cau_chung (phần mềm/tính năng mô tả chữ — vd Sophos) KHÔNG phải dịch vụ:
            # vẫn tìm + đối chiếu bằng toàn bộ dòng gốc (bài học run thật: STT 36 bị giết nhầm)
            search_spec, has_searchable = dict(spec), True
        if (
            spec.get("trang_thai_thong_so") == "khong_co_thong_so"
            and spec.get("loai_hang_muc") == "phu_kien_di_kem"
        ):
            parent = spec.get("phu_thuoc_hang_muc_con") or "thiet bi chinh"
            row["so_sanh"] = {
                "ung_vien": [],
                "nhan_xet": f"N/A - cho nha cung cap xac nhan phu kien di kem, tuong thich voi {parent}.",
                "can_review": True,
                "trang_thai": "N/A - cho xac nhan",
            }
        elif do_cmp and (all_rows and not has_searchable and has_vattu):
            # B3-1: hàng con toàn nhân công/vật tư phụ/lắp đặt THẬT → không tốn lượt search nào
            row["so_sanh"] = {
                "ung_vien": [],
                "nhan_xet": "Dịch vụ/thi công/vật tư phụ — không áp dụng tìm model, tính trọn gói theo khối lượng.",
                "trang_thai": "N/A - dịch vụ/thi công",
            }
        elif do_cmp and (has_searchable or spec.get("tu_khoa_tim")):
            ck = item_key(it, "compare_v18")   # v18: xóa sạch kết quả rác của run bị timeout extract
            cmp_hit = cache.get(ck, ttl)
            if not cmp_hit:
                wait_if_needed()
                with _plock:
                    _cdone["n"] += 1
                    progress(f"Tìm & đối chiếu ({_cdone['n']}/{len(work)}): {it['ten'][:30]}...",
                             40 + int(55 * _cdone["n"] / max(len(work), 1)))
                optional = _optional_crits(spec)
                try:
                    ctx = websearch.build_context(it, search_spec, cfg, counter)
                    raw_cmp = ai.compare(it, search_spec, ctx)
                    raw_cmp = _verify_quotes(raw_cmp, ctx, optional)     # máy dò lại từng trích dẫn — bịa là loại
                    raw_cmp = _numeric_recheck(raw_cmp, search_spec, optional)  # A1: máy so số — chấm sai là hạ
                    raw_cmp = _check_official_source(raw_cmp)            # phân loại domain nguồn
                    all_cands = list(raw_cmp.get("ung_vien", []) or [])  # giữ TẤT CẢ ứng viên (kể cả gần đạt)
                    cmp_hit = _only_100_percent(raw_cmp, spec, it, optional)

                    # ===== TAVILY CỨU HỘ HẸP: chỉ khi CHƯA có model 100%, cho ứng viên gần nhất + đúng dòng thiếu =====
                    tav_key = cfg.get("tavily_key") or (cfg.get("search_key", "") if cfg.get("search_provider") == "tavily" else "")
                    if (not cmp_hit.get("ung_vien")) and cfg.get("search_mode") == "hybrid" and tav_key and all_cands:
                        best = max(all_cands, key=_candidate_percent)
                        missing = _missing_rows(best)
                        if missing:
                            try:
                                progress(f"Tavily cứu hộ {len(missing)} dòng thiếu: {best.get('model', '')[:24]}...",
                                         40 + int(55 * _cdone["n"] / max(len(work), 1)))
                                bundle = []
                                for r in missing[:6]:
                                    q = f"{best.get('model', '')} {best.get('hang', '')} {r.get('yeu_cau', '')} {r.get('thong_so_hsmt', '')}"
                                    ex = websearch.tavily_research(q.strip(), tav_key)
                                    if counter is not None:
                                        with cfg["_lock"]:
                                            counter["used"] = counter.get("used", 0) + 1
                                    if ex:
                                        bundle.append(f"[TAVILY · {r.get('yeu_cau', '')}] {ex}")
                                tav_ctx = "\n---\n".join(bundle)
                                if tav_ctx:
                                    fixed = ai.recheck_lines(it, best, missing, tav_ctx)
                                    by_crit = {_norm(x.get("yeu_cau")): x for x in (fixed.get("bang") or [])}
                                    for r in best.get("bang", []):
                                        nx = by_crit.get(_norm(r.get("yeu_cau")))
                                        if nx:
                                            r.update({"gia_tri": nx.get("gia_tri", r.get("gia_tri", "")),
                                                      "danh_gia": nx.get("danh_gia", r.get("danh_gia", "")),
                                                      "trich_dan": nx.get("trich_dan", r.get("trich_dan", ""))})
                                    best["dat_100"] = True
                                    # B1 FIX: tav_ctx đặt TRƯỚC ctx — trích dẫn cứu hộ nằm trong cửa sổ kiểm chứng
                                    # (bug cũ: ctx ≥ giới hạn → tav_ctx bị cắt khỏi haystack → cứu luôn thất bại)
                                    ver = _verify_quotes({"ung_vien": [best]}, tav_ctx + "\n" + ctx, optional)
                                    ver = _numeric_recheck(ver, search_spec, optional)
                                    best = ver["ung_vien"][0]
                                    promoted = _only_100_percent({"ung_vien": [best]}, spec, it, optional)
                                    if promoted.get("ung_vien"):
                                        cmp_hit = promoted            # cứu thành công → đạt 100%
                            except Exception:
                                pass

                    # ===== ĐIỂM DỪNG: vẫn không có 100% → best-effort + cờ cần review (KHÔNG lặp vô hạn) =====
                    if not cmp_hit.get("ung_vien"):
                        be = _best_effort(all_cands)
                        if be:
                            cmp_hit["best_effort"] = be
                            cmp_hit["can_review"] = True
                            cmp_hit["nhan_xet"] = (f"Chưa có model đạt 100%. Cao nhất: {be['model']} ({be['hang']}) "
                                                   f"đạt ~{be['phan_tram']}%, thiếu: {', '.join(be['thieu'][:5])}. "
                                                   f"⚠ CẦN REVIEW THỦ CÔNG.")
                    if has_nonproduct:
                        cmp_hit["ghi_chu_pham_vi"] = ("Đã loại dòng vật tư phụ/nhân công khỏi tiêu chí 100% "
                                                      "(không phải thông số datasheet).")
                    # KHÔNG cache kết quả so sánh khi bóc tách đã lỗi (spec rỗng → kết quả rác):
                    # chạy lại sau khi extract thành công sẽ tính lại sạch sẽ
                    if "lỗi ai" not in str(spec.get("can_cu", "")).lower():
                        try:
                            cache.put(ck, cmp_hit)
                        except Exception:
                            pass
                except Exception as e:
                    cmp_hit = {"tieu_chi": [], "ung_vien": [], "nhan_xet": f"Lỗi: {e}"}
            row["so_sanh"] = cmp_hit
        out[idx] = row
        if on_item:
            on_item(row)

    n_workers = max(1, int(cfg.get("parallel_items", 4)))
    if len(work) <= 1 or n_workers == 1:
        for i, it in enumerate(work):
            process(i, it)
    else:
        with futures.ThreadPoolExecutor(max_workers=min(n_workers, len(work))) as pool:
            futs = [pool.submit(process, i, it) for i, it in enumerate(work)]
            for f in futures.as_completed(futs):
                f.result()          # nổi lỗi bất ngờ của worker thay vì nuốt im lặng
    return out
