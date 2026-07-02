# -*- coding: utf-8 -*-
"""Web search: Serper.dev (mặc định, gl=vn) + tải nội dung top-3. Adapter đổi được Tavily."""
import re, requests


def serper(query, key, num=5):
    r = requests.post("https://google.serper.dev/search", timeout=30,
                      headers={"X-API-KEY": key, "Content-Type": "application/json"},
                      json={"q": query, "gl": "vn", "hl": "vi", "num": num})
    r.raise_for_status()
    return [{"title": o.get("title", ""), "link": o.get("link", ""), "snippet": o.get("snippet", "")}
            for o in r.json().get("organic", [])[:num]]


def tavily(query, key, num=5):
    r = requests.post("https://api.tavily.com/search", timeout=40,
                      json={"api_key": key, "query": query, "max_results": num, "include_answer": False})
    r.raise_for_status()
    return [{"title": o.get("title", ""), "link": o.get("url", ""), "snippet": o.get("content", "")[:400]}
            for o in r.json().get("results", [])[:num]]


AGGREGATORS = ("displayspecifications", "tiki.", "shopee", "lazada", "sieuthi", "phongvu", "gearvn",
               "cellphones", "dienmay", "hoangduong", "phucquang", "cpn.vn", "wikipedia", "amazon.",
               "anphat", "tinhoc", "memoryzone", "hanoicomputer", "nguyenkim")


def is_official(link):
    """Heuristic: không thuộc danh sách trang tổng hợp/đại lý → coi là trang hãng."""
    try:
        d = link.split("/")[2].lower()
    except IndexError:
        return False
    return not any(a in d for a in AGGREGATORS)


def fetch_page(url, limit=3000):
    try:
        r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        html = r.text
        html = re.sub(r"(?is)<(script|style|nav|footer|header).*?</\1>", " ", html)
        txt = re.sub(r"<[^>]+>", " ", html)
        return re.sub(r"\s+", " ", txt).strip()[:limit]
    except Exception:
        return ""


def fetch_pdf(url, limit=4000):
    """Tải và trích văn bản PDF datasheet (PyMuPDF)."""
    try:
        import fitz
        r = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
        doc = fitz.open(stream=r.content, filetype="pdf")
        txt = " ".join(pg.get_text() for pg in doc[:6])
        return re.sub(r"\s+", " ", txt).strip()[:limit]
    except Exception:
        return ""


def build_context(item, ident, cfg, counter=None):
    """Luồng mới: tìm SẢN PHẨM THEO THÔNG SỐ (từ khóa do AI chuẩn hóa) → lấy datasheet/link hãng
    (tải nội dung tối đa 3 trang) → trả ngữ cảnh cho AI đối chiếu từng dòng."""
    provider, key = cfg.get("search_provider", "serper"), cfg.get("search_key", "")
    if provider == "off" or not key:
        return ""
    fn = serper if provider == "serper" else tavily
    kw = (ident.get("tu_khoa_tim") or f"{item['ten']} {item['thongso'][:60]}").strip()
    queries = [kw, kw + " datasheet thông số kỹ thuật", kw + " datasheet filetype:pdf"]
    ctx, all_res = [], []
    for q in queries:
        try:
            res = fn(q, key)
            if counter is not None:
                counter["used"] = counter.get("used", 0) + 1
            all_res.extend(res)
            for o in res[:4]:
                tag = "CHÍNH HÃNG" if is_official(o["link"]) else "trang tổng hợp/đại lý"
                ctx.append(f"[{o['title']}] ({tag}) {o['link']}\n{o['snippet']}")
        except Exception as e:
            ctx.append(f"(lỗi tra cứu: {e})")
    if cfg.get("fetch_pages", True):
        # Ưu tiên đọc sâu: PDF chính hãng → PDF khác → trang HTML chính hãng
        pdfs = [o for o in all_res if ".pdf" in o["link"].lower()]
        pdfs.sort(key=lambda o: not is_official(o["link"]))
        pages = [o for o in all_res if ".pdf" not in o["link"].lower() and is_official(o["link"])]
        fetched = 0
        for o in pdfs[:2]:
            txt = fetch_pdf(o["link"])
            if txt:
                tag = "PDF DATASHEET CHÍNH HÃNG" if is_official(o["link"]) else "PDF (nguồn tổng hợp)"
                ctx.append(f"{tag} ({o['link']}): {txt}")
                fetched += 1
        for o in pages:
            if fetched >= 3:
                break
            txt = fetch_page(o["link"])
            if txt:
                ctx.append(f"TRANG CHÍNH HÃNG ({o['link']}): {txt}")
                fetched += 1
    return "\n---\n".join(ctx)
