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


def fetch_page(url, limit=8000):
    try:
        r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        html = r.text
        html = re.sub(r"(?is)<(script|style|nav|footer|header).*?</\1>", " ", html)
        txt = re.sub(r"<[^>]+>", " ", html)
        return re.sub(r"\s+", " ", txt).strip()[:limit]
    except Exception:
        return ""


def fetch_pdf(url, limit=12000):
    try:
        import fitz

        r = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
        doc = fitz.open(stream=r.content, filetype="pdf")
        txt = " ".join(pg.get_text() for pg in doc[:10])
        return re.sub(r"\s+", " ", txt).strip()[:limit]
    except Exception:
        return ""


def build_context(item, ident, cfg, counter=None):
    """Search products by normalized specs, then fetch datasheets/official links for AI verification."""
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
