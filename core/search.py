# -*- coding: utf-8 -*-
"""Web search: Serper/Tavily/Exa -> snippets -> fetch official pages/PDF datasheets.
SONG SONG có kiểm soát (S1): mọi HTTP call qua semaphore theo provider — chạy chồng nhau
nhưng không bao giờ dội rate-limit; fetch trang/PDF chạy đồng thời (đo thật nhanh 5.6x)."""
import re
import threading
from concurrent import futures

import requests

# Trần đồng thời theo provider — bảo vệ rate-limit khi nhiều dòng con cùng tìm kiếm
_SEM = {
    "serper": threading.BoundedSemaphore(6),
    "exa": threading.BoundedSemaphore(4),
    "tavily": threading.BoundedSemaphore(4),
}


def _bump(counter, cfg=None):
    if counter is None:
        return
    lock = (cfg or {}).get("_lock")
    if lock:
        with lock:
            counter["used"] = counter.get("used", 0) + 1
    else:
        counter["used"] = counter.get("used", 0) + 1


def _run_search(provider, fn, query, key, num, cfg, counter, **kw):
    """S3 — cache truy vấn TOÀN PHIÊN: các dòng con trùng từ khóa (tủ ắc quy ↔ ắc quy...) dùng lại
    kết quả, 0 HTTP / 0 credit. Cache sống trong cfg['_qcache'] do analyzer.run cấp mỗi lần chạy."""
    qc = (cfg or {}).get("_qcache")
    ck = f"{provider}|{kw.get('gl', 'vn')}|{query.strip().lower()}"
    if qc is not None:
        with qc["lock"]:
            if ck in qc["data"]:
                return list(qc["data"][ck])
    res = fn(query, key, num, **kw)
    _bump(counter, cfg)
    if qc is not None:
        with qc["lock"]:
            qc["data"][ck] = list(res)
    return res


def _is_windows_11_pro(text):
    return bool(
        re.search(r"\bwindows\s*11\s*(pro|professional)\b", text or "", re.I)
        or re.search(r"\bwin\s*11\s*pro\b", text or "", re.I)
    )


def _strip_windows_terms(text):
    text = re.sub(r"\bWindows\s*11\s*(Pro|Professional)\b", " ", text or "", flags=re.I)
    text = re.sub(r"\bWin\s*11\s*Pro\b", " ", text, flags=re.I)
    return re.sub(r"\s+", " ", text).strip()


def serper(query, key, num=5, gl="vn", hl="vi"):
    """gl/hl tùy biến (A3): truy vấn tiếng Anh gl=us hl=en bắt datasheet quốc tế mà bản vi bỏ sót."""
    with _SEM["serper"]:
        r = requests.post(
            "https://google.serper.dev/search",
            timeout=30,
            headers={"X-API-KEY": key, "Content-Type": "application/json"},
            json={"q": query, "gl": gl, "hl": hl, "num": num},
        )
    r.raise_for_status()
    return [
        {"title": o.get("title", ""), "link": o.get("link", ""), "snippet": o.get("snippet", "")}
        for o in r.json().get("organic", [])[:num]
    ]


def tavily(query, key, num=5):
    with _SEM["tavily"]:
        r = requests.post(
            "https://api.tavily.com/search",
            timeout=40,
            json={"api_key": key, "query": query, "max_results": num, "include_answer": False},
        )
    r.raise_for_status()
    return [
        {"title": o.get("title", ""), "link": o.get("url", ""), "snippet": o.get("content", "")[:400]}
        for o in r.json().get("results", [])[:num]
    ]


def exa(query, key, num=5):
    """Exa.ai — tìm ngữ nghĩa + trả kèm summary/highlights (nội dung đã bóc sẵn cho AI)."""
    with _SEM["exa"]:
        r = requests.post(
            "https://api.exa.ai/search",
            timeout=45,
            headers={"x-api-key": key, "Content-Type": "application/json"},
            json={"query": query, "numResults": num, "type": "auto",
                  "contents": {"summary": True, "highlights": {"numSentences": 5}}},
        )
    r.raise_for_status()
    out = []
    for o in r.json().get("results", [])[:num]:
        snippet = o.get("summary") or " ".join(o.get("highlights", []) or []) or (o.get("text", "") or "")
        out.append({"title": o.get("title", ""), "link": o.get("url", ""), "snippet": snippet[:800]})
    return out


PROVIDERS = {"serper": serper, "tavily": tavily, "exa": exa}


def provider_key(cfg, provider):
    legacy = cfg.get("search_key", "")
    if provider == "serper":
        return cfg.get("serper_key") or (legacy if cfg.get("search_provider") == "serper" else "")
    if provider == "exa":
        return cfg.get("exa_key") or (legacy if cfg.get("search_provider") == "exa" else "")
    if provider == "tavily":
        return cfg.get("tavily_key") or (legacy if cfg.get("search_provider") == "tavily" else "")
    return legacy


def tavily_research(query, key, max_results=5):
    """Tavily research: tổng hợp NHIỀU nguồn + câu trả lời — dùng cứu hộ khi dòng chưa xác minh."""
    with _SEM["tavily"]:
        r = requests.post(
            "https://api.tavily.com/search",
            timeout=60,
            json={"api_key": key, "query": query, "max_results": max_results,
                  "include_answer": True, "search_depth": "advanced"},
        )
    r.raise_for_status()
    d = r.json()
    ans = d.get("answer", "") or ""
    src = "\n".join(f"{o.get('url', '')}: {(o.get('content', '') or '')[:400]}"
                    for o in d.get("results", [])[:max_results])
    head = ("TAVILY TỔNG HỢP: " + ans + "\n") if ans else ""
    return (head + src).strip()


AGGREGATORS = (
    "displayspecifications",
    "tiki.",
    "shopee",
    "lazada",
    "sieuthi",
    "phongvu",
    "gearvn",
    "cellphones",
    "dienmay",
    "hoangduong",
    "phucquang",
    "cpn.vn",
    "wikipedia",
    "amazon.",
    "anphat",
    "tinhoc",
    "memoryzone",
    "hanoicomputer",
    "nguyenkim",
)


def is_official(link):
    """Heuristic: domains outside the aggregator/dealer list are treated as official/vendor sources."""
    try:
        domain = link.split("/")[2].lower()
    except IndexError:
        return False
    return not any(a in domain for a in AGGREGATORS)


def _brand_domain_match(link, brand_hints):
    """True nếu tên miền chứa 1 trong các brand hint (santak.* khớp brand 'santak') → nguồn hãng đáng tin nhất."""
    try:
        domain = link.split("/")[2].lower()
    except IndexError:
        return False
    flat = re.sub(r"[^a-z0-9]", "", domain)
    return any(b and b in flat for b in brand_hints)


def _brand_tokens(titles):
    """Rút token thương hiệu/model từ tiêu đề ứng viên Exa để so khớp tên miền chính hãng."""
    toks = set()
    for t in titles or []:
        for w in re.split(r"[\s/\-,()]+", (t or "").lower()):
            w = re.sub(r"[^a-z0-9]", "", w)
            if len(w) >= 3 and w not in ("cho", "cua", "may", "thiet", "bi", "chinh", "hang", "gia", "san", "pham"):
                toks.add(w)
    return toks


def fetch_page(url, limit=8000):
    try:
        # S4: timeout 20→10s — trang chậm bỏ qua thay vì ghim cả pipeline (chạy song song nên càng rẻ)
        r = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        html = r.text
        html = re.sub(r"(?is)<(script|style|nav|footer|header).*?</\1>", " ", html)
        txt = re.sub(r"<[^>]+>", " ", html)
        return re.sub(r"\s+", " ", txt).strip()[:limit]
    except Exception:
        return ""


def _ocr_page(page):
    """OCR trang scan/ảnh (best-effort — cần pytesseract + tesseract, thiếu thì bỏ qua)."""
    try:
        import io
        import pytesseract
        from PIL import Image
        pix = page.get_pixmap(dpi=200)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        return pytesseract.image_to_string(img, lang="eng+vie")
    except Exception:
        return ""


def _extract_tables(page):
    """Trích bảng thông số trong datasheet (nhiều datasheet để dạng bảng, không phải text thuần)."""
    out = []
    try:
        tbls = page.find_tables()
        for tb in (tbls.tables if hasattr(tbls, "tables") else tbls):
            for row in tb.extract():
                cells = [str(c).strip() for c in row if c]
                if cells:
                    out.append(" | ".join(cells))
    except Exception:
        pass
    return "\n".join(out)


def fetch_pdf(url, limit=16000):
    """Tải PDF → text thuần + BẢNG thông số + OCR nếu là bản scan/ảnh."""
    try:
        import fitz
        r = requests.get(url, timeout=25, headers={"User-Agent": "Mozilla/5.0"})   # S4: 45→25s
        doc = fitz.open(stream=r.content, filetype="pdf")
        parts = []
        for pg in doc[:10]:
            tbl = _extract_tables(pg)
            if tbl:
                parts.append("[BẢNG] " + tbl)
            t = pg.get_text()
            if len(t.strip()) < 40:          # trang gần như không có text → scan/ảnh → OCR
                t = _ocr_page(pg) or t
            if t.strip():
                parts.append(t)
        return re.sub(r"\s+", " ", " ".join(parts)).strip()[:limit]
    except Exception:
        return ""


def _kw_from(item, ident):
    specs = [s for s in (ident.get("thong_so") or [])
             if not _is_windows_11_pro(f"{s.get('ten', '')} {s.get('gia_tri', '')}")]
    spec_terms = " ".join(f"{s.get('ten', '')} {s.get('gia_tri', '')}" for s in specs[:6]).strip()
    base = (ident.get("tu_khoa_tim") or f"{ident.get('loai_thiet_bi', item['ten'])} {spec_terms}").strip()
    return " ".join(re.sub(r"\s+", " ", _strip_windows_terms(base)).split()[:28])


def _kw_relaxed(item, ident):
    """A4 — truy vấn 'NỚI SỐ' vá bias: từ khóa nguyên văn chứa con số quá đặc thù (61Mpps, 82Gbps...)
    khiến Google thiên về đúng model HSMT 'vẽ'. Bản nới giữ LOẠI thiết bị + các NGƯỠNG ≥/≤ (yêu cầu thật,
    model vượt chuẩn vẫn khớp) + tiêu chuẩn, bỏ các giá trị '=' đặc thù → model thay thế nổi lên được."""
    keep = []
    for r in ident.get("thong_so") or []:
        if _is_windows_11_pro(f"{r.get('ten', '')} {r.get('gia_tri', '')}"):
            continue
        op = str(r.get("toan_tu_so_sanh", ""))
        kind = str(r.get("loai_du_lieu", ""))
        if op in (">=", "<="):
            keep.append(f"{r.get('ten', '')} {r.get('gia_tri', '')}")
        elif kind == "tieu_chuan_chung_chi":
            keep.append(str(r.get("gia_tri", "")))
    base = f"{ident.get('loai_thiet_bi', item.get('ten', ''))} " + " ".join(keep[:5])
    kw = " ".join(re.sub(r"\s+", " ", _strip_windows_terms(base)).split()[:24])
    return kw if len(kw.split()) >= 3 else ""


def _fetch_deep(all_res, cfg, max_deep, brand_hints=None):
    """Đọc sâu SONG SONG (đo thật 5.6x): ưu tiên PDF domain-hãng > PDF chính hãng > PDF khác > trang.
    Tải đồng thời rồi ghép lại đúng thứ tự ưu tiên — kết quả y hệt bản tuần tự, chỉ nhanh hơn."""
    if not cfg.get("fetch_pages", True):
        return []
    brand_hints = brand_hints or set()

    def rank(o):
        # 0 = tốt nhất (domain khớp hãng), 1 = chính hãng chung, 2 = đại lý/tổng hợp
        if _brand_domain_match(o["link"], brand_hints):
            return 0
        return 1 if is_official(o["link"]) else 2

    pdfs = sorted([o for o in all_res if ".pdf" in o["link"].lower()], key=rank)[:4]
    pages = sorted([o for o in all_res if ".pdf" not in o["link"].lower()], key=rank)[:max_deep + 1]
    texts = {}
    pool_n = max(2, int(cfg.get("parallel_fetch", 6)))
    with futures.ThreadPoolExecutor(max_workers=pool_n) as pool:
        futs = {pool.submit(fetch_pdf, o["link"]): o["link"] for o in pdfs}
        futs.update({pool.submit(fetch_page, o["link"]): o["link"] for o in pages})
        for f in futures.as_completed(futs):
            try:
                texts[futs[f]] = f.result()
            except Exception:
                texts[futs[f]] = ""

    deep, n = [], 0
    for o in pdfs:
        txt = texts.get(o["link"], "")
        if txt:
            n += 1
            tag = "PDF DATASHEET CHINH HANG" if is_official(o["link"]) else "PDF (dai ly/tong hop)"
            deep.append(f"[NGUON {n}] {tag} ({o['link']}): {txt}")
    for o in pages:
        if n >= max_deep:
            break
        txt = texts.get(o["link"], "")
        if txt:
            n += 1
            tag = "TRANG CHINH HANG" if is_official(o["link"]) else "TRANG dai ly/tong hop"
            deep.append(f"[NGUON {n}] {tag} ({o['link']}): {txt}")
    return deep


def _dedup(results):
    uniq, seen = [], set()
    for o in results:
        if o["link"] and o["link"] not in seen:
            seen.add(o["link"]); uniq.append(o)
    return uniq


def _official_domain_for(title, results):
    """A3 — tìm domain chính hãng khớp brand-token của ứng viên trong các kết quả đã có (để bắn site:)."""
    hints = _brand_tokens([title])
    for o in results or []:
        link = o.get("link", "")
        if is_official(link) and _brand_domain_match(link, hints):
            try:
                return link.split("/")[2].lower()
            except IndexError:
                continue
    return ""


def _hybrid_context(item, ident, cfg, counter=None):
    """Luồng 2 tầng SONG SONG: Exa tìm ỨNG VIÊN (nguyên văn + nới số) → Serper lấy BẰNG CHỨNG.
    Tầng 1: Exa ×2 + Serper chung VN/EN chạy ĐỒNG THỜI. Tầng 2: các ứng viên chạy ĐỒNG THỜI,
    mỗi ứng viên tối đa 2 biến thể (S3) + 1 truy vấn site: domain hãng khi chưa có PDF chính hãng (A3)."""
    exa_key = cfg.get("exa_key") or (cfg.get("search_key", "") if cfg.get("search_provider") == "exa" else "")
    serper_key = cfg.get("serper_key") or (cfg.get("search_key", "") if cfg.get("search_provider") == "serper" else "")
    num = int(cfg.get("results_per_query", 8))
    max_deep = int(cfg.get("max_deep_sources", 5))
    kw = _kw_from(item, ident)
    kw2 = _kw_relaxed(item, ident)
    pool_n = max(2, int(cfg.get("parallel_fetch", 6)))

    all_res, snip, cand = [], [], []
    with futures.ThreadPoolExecutor(max_workers=pool_n) as pool:
        # ===== TẦNG 1 — song song: Exa nguyên văn + Exa nới số + Serper chung (VN, PDF, EN) =====
        jobs = []
        if exa_key:
            jobs.append(("exa", pool.submit(_run_search, "exa", exa,
                                            "sản phẩm thiết bị đáp ứng thông số " + kw, exa_key, num, cfg, counter)))
            if kw2 and kw2 != kw:
                jobs.append(("exa", pool.submit(_run_search, "exa", exa,
                                                "thiết bị tương đương đáp ứng " + kw2, exa_key, num, cfg, counter)))
        if serper_key:
            jobs.append(("serper", pool.submit(_run_search, "serper", serper,
                                               kw + " datasheet filetype:pdf", serper_key, num, cfg, counter)))
            jobs.append(("serper", pool.submit(_run_search, "serper", serper,
                                               kw + " datasheet thông số kỹ thuật", serper_key, num, cfg, counter)))
            # A3: truy vấn tiếng Anh — bắt datasheet quốc tế mà truy vấn tiếng Việt bỏ sót
            jobs.append(("serper", pool.submit(_run_search, "serper", serper,
                                               kw + " datasheet specifications", serper_key, num, cfg, counter,
                                               gl="us", hl="en")))
        for tag, fut in jobs:
            try:
                res = fut.result()
            except Exception as e:
                snip.append(f"(lỗi {tag}: {e})")
                continue
            all_res += res
            if tag == "exa":
                for o in res[:5]:
                    if o.get("title") and o["title"] not in cand:
                        cand.append(o["title"])
                for o in res[:6]:
                    snip.append(f"[ỨNG VIÊN·Exa] {o['link']}\n{o['snippet']}")
            else:
                for o in res[:4]:
                    t = "CHINH HANG" if is_official(o["link"]) else "dai ly/tong hop"
                    snip.append(f"[BẰNG CHỨNG·Serper] ({t}) {o['link']}\n{o['snippet']}")

        # ===== TẦNG 2 — bằng chứng theo TỪNG ứng viên, các ứng viên chạy song song =====
        cand = cand[:5]
        variants = ["{c} datasheet filetype:pdf", "{c} datasheet"]   # S3: 4 biến thể → 2 (đủ bắt PDF)

        def evidence(c, base_res):
            out_res, out_snip = [], []
            cq = c[:70]
            found_pdf = False
            for v in variants:                      # tuần tự TRONG 1 ứng viên để early-break tiết kiệm
                try:
                    sr = _run_search("serper", serper, v.format(c=cq), serper_key, num, cfg, counter)
                except Exception:
                    continue
                out_res += sr
                for o in sr[:3]:
                    t = "CHINH HANG" if is_official(o["link"]) else "dai ly/tong hop"
                    out_snip.append(f"[BẰNG CHỨNG·{cq[:24]}] ({t}) {o['link']}\n{o['snippet']}")
                if any(is_official(o["link"]) and ".pdf" in o["link"].lower() for o in sr):
                    found_pdf = True
                    break
            if not found_pdf:
                # A3: chưa có PDF chính hãng → bắn thẳng site: domain hãng (rút từ kết quả đã thấy)
                dom = _official_domain_for(c, out_res + base_res)
                if dom:
                    try:
                        sr = _run_search("serper", serper, f"site:{dom} {cq[:50]}", serper_key, num, cfg, counter)
                        out_res += sr
                        for o in sr[:3]:
                            out_snip.append(f"[BẰNG CHỨNG·site:{dom[:24]}] {o['link']}\n{o['snippet']}")
                    except Exception:
                        pass
            return out_res, out_snip

        if serper_key and cand:
            snapshot = list(all_res)
            futs = [pool.submit(evidence, c, snapshot) for c in cand]
            for f in futs:
                try:
                    r2, s2 = f.result()
                    all_res += r2
                    snip += s2
                except Exception:
                    pass

    brand_hints = _brand_tokens(cand)
    deep = _fetch_deep(_dedup(all_res), cfg, max_deep, brand_hints)
    return "\n---\n".join(deep + snip)


def build_context(item, ident, cfg, counter=None):
    """Search products by normalized specs, then fetch datasheets/official links for AI verification."""
    if cfg.get("search_mode") == "hybrid":
        return _hybrid_context(item, ident, cfg, counter)
    provider = cfg.get("search_provider", "serper")
    key = provider_key(cfg, provider)
    if provider == "off" or not key:
        return ""
    fn = PROVIDERS.get(provider, serper)
    num = int(cfg.get("results_per_query", 8))           # tăng độ sâu: 5 -> 8 kết quả/truy vấn
    max_deep = int(cfg.get("max_deep_sources", 5))        # đọc sâu tối đa 5 nguồn (trước 3)

    specs = [
        s for s in (ident.get("thong_so") or [])
        if not _is_windows_11_pro(f"{s.get('ten', '')} {s.get('gia_tri', '')}")
    ]
    spec_terms = " ".join(f"{s.get('ten', '')} {s.get('gia_tri', '')}" for s in specs[:6]).strip()
    base = (ident.get("tu_khoa_tim") or f"{ident.get('loai_thiet_bi', item['ten'])} {spec_terms}").strip()
    # Google chỉ đọc 32 từ đầu của truy vấn — giới hạn ~28 từ để cả 3 biến thể truy vấn còn hiệu lực
    kw = " ".join(re.sub(r"\s+", " ", _strip_windows_terms(base)).split()[:28])
    queries = [
        kw,
        kw + " datasheet thong so ky thuat",
        kw + " datasheet filetype:pdf",
        kw + " tuong duong thay the",   # truy vấn tìm hàng THAY THẾ (hãng khác)
    ]
    kw2 = _kw_relaxed(item, ident)
    if kw2 and kw2 != kw:
        queries.append(kw2 + " datasheet")   # A4: bản nới số — model vượt chuẩn nổi lên được

    snip, all_res, seen = [], [], set()
    # Các truy vấn chạy SONG SONG (semaphore trong provider lo rate-limit)
    with futures.ThreadPoolExecutor(max_workers=min(len(queries), 6)) as pool:
        futs = [pool.submit(_run_search, provider, fn, q, key, num, cfg, counter) for q in queries]
        for f in futs:                        # duyệt THEO THỨ TỰ truy vấn — output ổn định như bản cũ
            try:
                res = f.result()
            except Exception as e:
                snip.append(f"(loi tra cuu: {e})")
                continue
            fresh = []
            for o in res:
                if o["link"] in seen:   # khử trùng link giữa các truy vấn
                    continue
                seen.add(o["link"])
                all_res.append(o)
                fresh.append(o)
            for o in fresh[:5]:
                tag = "CHINH HANG" if is_official(o["link"]) else "trang tong hop/dai ly"
                snip.append(f"[KQ TIM] ({tag}) {o['link']}\n{o['snippet']}")

    deep = _fetch_deep(all_res, cfg, max_deep)   # đọc sâu song song, PDF chính hãng xếp trước
    # QUAN TRỌNG: nội dung đọc sâu (datasheet) đặt LÊN ĐẦU để không bị cắt khi giới hạn ngữ cảnh
    return "\n---\n".join(deep + snip)
