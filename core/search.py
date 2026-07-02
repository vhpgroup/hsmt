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


def fetch_page(url, limit=3000):
    try:
        r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        html = r.text
        html = re.sub(r"(?is)<(script|style|nav|footer|header).*?</\1>", " ", html)
        txt = re.sub(r"<[^>]+>", " ", html)
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
    queries = [kw, kw + " datasheet thông số kỹ thuật"]
    ctx, fetched = [], 0
    for qi, q in enumerate(queries):
        try:
            res = fn(q, key)
            if counter is not None:
                counter["used"] = counter.get("used", 0) + 1
            for o in res[:4]:
                ctx.append(f"[{o['title']}] {o['link']}\n{o['snippet']}")
            if cfg.get("fetch_pages", True):
                for o in (res[:2] if qi == 0 else res[:1]):
                    if fetched >= 3:
                        break
                    page = fetch_page(o["link"])
                    if page:
                        ctx.append(f"DATASHEET/TRANG HÃNG ({o['link']}): {page}")
                        fetched += 1
        except Exception as e:
            ctx.append(f"(lỗi tra cứu: {e})")
    return "\n---\n".join(ctx)
