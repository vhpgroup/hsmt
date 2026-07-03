# -*- coding: utf-8 -*-
"""Web search: Serper/Tavily -> collect result snippets -> fetch official pages and PDF datasheets."""
import re

import requests


def _is_windows_11_pro(text):
    return bool(
        re.search(r"\bwindows\s*11\s*(pro|professional)\b", text or "", re.I)
        or re.search(r"\bwin\s*11\s*pro\b", text or "", re.I)
    )


def _strip_windows_terms(text):
    text = re.sub(r"\bWindows\s*11\s*(Pro|Professional)\b", " ", text or "", flags=re.I)
    text = re.sub(r"\bWin\s*11\s*Pro\b", " ", text, flags=re.I)
    return re.sub(r"\s+", " ", text).strip()


def serper(query, key, num=5):
    r = requests.post(
        "https://google.serper.dev/search",
        timeout=30,
        headers={"X-API-KEY": key, "Content-Type": "application/json"},
        json={"q": query, "gl": "vn", "hl": "vi", "num": num},
    )
    r.raise_for_status()
    return [
        {"title": o.get("title", ""), "link": o.get("link", ""), "snippet": o.get("snippet", "")}
        for o in r.json().get("organic", [])[:num]
    ]


def tavily(query, key, num=5):
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


def tavily_research(query, key, max_results=5):
    """Tavily research: tổng hợp NHIỀU nguồn + câu trả lời — dùng cứu hộ khi dòng chưa xác minh."""
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
        r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
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
        r = requests.get(url, timeout=45, headers={"User-Agent": "Mozilla/5.0"})
        doc = fitz.open(stream=r.content, filetype="pdf")
        parts = []
        for pg in doc[:12]:
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


def _fetch_deep(all_res, cfg, max_deep, brand_hints=None):
    """Đọc sâu: ưu tiên PDF domain-hãng > PDF chính hãng > PDF khác > trang. brand_hints boost domain khớp hãng."""
    if not cfg.get("fetch_pages", True):
        return []
    brand_hints = brand_hints or set()

    def rank(o):
        # 0 = tốt nhất (domain khớp hãng), 1 = chính hãng chung, 2 = đại lý/tổng hợp
        if _brand_domain_match(o["link"], brand_hints):
            return 0
        return 1 if is_official(o["link"]) else 2

    deep = []
    pdfs = sorted([o for o in all_res if ".pdf" in o["link"].lower()], key=rank)
    pages = sorted([o for o in all_res if ".pdf" not in o["link"].lower()], key=rank)
    n = 0
    for o in pdfs[:4]:                        # đọc tối đa 4 PDF (ưu tiên chính xác hơn tiết kiệm)
        txt = fetch_pdf(o["link"])
        if txt:
            n += 1
            tag = "PDF DATASHEET CHINH HANG" if is_official(o["link"]) else "PDF (dai ly/tong hop)"
            deep.append(f"[NGUON {n}] {tag} ({o['link']}): {txt}")
    for o in pages:
        if n >= max_deep:
            break
        txt = fetch_page(o["link"])
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


def _hybrid_context(item, ident, cfg, counter=None):
    """Luồng 2 tầng: Exa tìm ỨNG VIÊN (ngữ nghĩa) → Serper lấy BẰNG CHỨNG datasheet/PDF theo tên ứng viên."""
    exa_key = cfg.get("exa_key") or (cfg.get("search_key", "") if cfg.get("search_provider") == "exa" else "")
    serper_key = cfg.get("serper_key") or (cfg.get("search_key", "") if cfg.get("search_provider") == "serper" else "")
    num = int(cfg.get("results_per_query", 8))
    max_deep = int(cfg.get("max_deep_sources", 5))
    kw = _kw_from(item, ident)

    def bump():
        if counter is not None:
            counter["used"] = counter.get("used", 0) + 1

    all_res, snip, cand = [], [], []
    # TIER 1 — Exa: tìm ứng viên theo ngữ nghĩa
    if exa_key:
        try:
            er = exa("sản phẩm thiết bị đáp ứng thông số " + kw, exa_key, num); bump()
            all_res += er
            cand = [o["title"] for o in er[:5] if o.get("title")]
            for o in er[:6]:
                snip.append(f"[ỨNG VIÊN·Exa] {o['link']}\n{o['snippet']}")
        except Exception as e:
            snip.append(f"(lỗi Exa: {e})")

    # TIER 2 — Serper: lấy bằng chứng datasheet/PDF
    if serper_key:
        # 2a. Truy vấn chung theo từ khóa
        for q in [kw + " datasheet filetype:pdf", kw + " datasheet thông số kỹ thuật"]:
            try:
                sr = serper(q, serper_key, num); bump()
                all_res += sr
                for o in sr[:4]:
                    tag = "CHINH HANG" if is_official(o["link"]) else "dai ly/tong hop"
                    snip.append(f"[BẰNG CHỨNG·Serper] ({tag}) {o['link']}\n{o['snippet']}")
            except Exception:
                pass
        # 2b. VỚI TỪNG ỨNG VIÊN Exa: retry đổi từ khóa đến khi có PDF chính hãng, không thì mới thôi
        variants = [
            "{c} datasheet filetype:pdf",
            "{c} datasheet",
            "{c} spec sheet specifications",
            "{c} thông số kỹ thuật",
        ]
        for c in cand[:5]:                       # phủ tối đa 5 ứng viên (không lo chi phí)
            cq = c[:70]
            found_pdf = False
            for v in variants:
                try:
                    sr = serper(v.format(c=cq), serper_key, num); bump()
                    all_res += sr
                    for o in sr[:3]:
                        tag = "CHINH HANG" if is_official(o["link"]) else "dai ly/tong hop"
                        snip.append(f"[BẰNG CHỨNG·{cq[:24]}] ({tag}) {o['link']}\n{o['snippet']}")
                    if any(is_official(o["link"]) and ".pdf" in o["link"].lower() for o in sr):
                        found_pdf = True
                        break                    # đã có PDF chính hãng cho ứng viên này → sang ứng viên khác
                except Exception:
                    pass
            # hết biến thể mà vẫn chưa có PDF chính hãng → vẫn giữ ứng viên (dùng nguồn khác), không bỏ

    brand_hints = _brand_tokens(cand)
    deep = _fetch_deep(_dedup(all_res), cfg, max_deep, brand_hints)
    return "\n---\n".join(deep + snip)


def build_context(item, ident, cfg, counter=None):
    """Search products by normalized specs, then fetch datasheets/official links for AI verification."""
    if cfg.get("search_mode") == "hybrid":
        return _hybrid_context(item, ident, cfg, counter)
    provider, key = cfg.get("search_provider", "serper"), cfg.get("search_key", "")
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

    deep, snip, all_res, seen = [], [], [], set()
    for q in queries:
        try:
            res = fn(q, key, num)
            if counter is not None:
                counter["used"] = counter.get("used", 0) + 1
            for o in res:
                if o["link"] in seen:   # khử trùng link giữa các truy vấn
                    continue
                seen.add(o["link"])
                all_res.append(o)
            for o in res[:5]:
                tag = "CHINH HANG" if is_official(o["link"]) else "trang tong hop/dai ly"
                snip.append(f"[KQ TIM] ({tag}) {o['link']}\n{o['snippet']}")
        except Exception as e:
            snip.append(f"(loi tra cuu: {e})")

    if cfg.get("fetch_pages", True):
        pdfs = [o for o in all_res if ".pdf" in o["link"].lower()]
        pdfs.sort(key=lambda o: not is_official(o["link"]))         # PDF chính hãng trước
        pages = [o for o in all_res if ".pdf" not in o["link"].lower()]
        pages.sort(key=lambda o: not is_official(o["link"]))         # trang chính hãng trước
        n_src = 0
        for o in pdfs[:3]:                                            # đọc tối đa 3 PDF (trước 2)
            txt = fetch_pdf(o["link"])
            if txt:
                n_src += 1
                tag = "PDF DATASHEET CHINH HANG" if is_official(o["link"]) else "PDF (nguon tong hop)"
                deep.append(f"[NGUON {n_src}] {tag} ({o['link']}): {txt}")
        for o in pages:
            if n_src >= max_deep:                                     # tổng tối đa 5 nguồn đọc sâu
                break
            txt = fetch_page(o["link"])
            if txt:
                n_src += 1
                tag = "TRANG CHINH HANG" if is_official(o["link"]) else "TRANG dai ly/tong hop"
                deep.append(f"[NGUON {n_src}] {tag} ({o['link']}): {txt}")
    # QUAN TRỌNG: nội dung đọc sâu (datasheet) đặt LÊN ĐẦU để không bị cắt khi giới hạn ngữ cảnh
    return "\n---\n".join(deep + snip)
