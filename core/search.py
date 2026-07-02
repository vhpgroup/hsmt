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
    """Tra model gốc + tương đương; kèm nội dung top-3 trang. Trả chuỗi ngữ cảnh cho AI."""
    provider, key = cfg.get("search_provider", "serper"), cfg.get("search_key", "")
    if cfg.get("search_provider") == "off" or not key:
        return ""
    fn = serper if provider == "serper" else tavily
    ctx = []
    queries = [f"{ident.get('hang','')} {ident.get('model','')} thông số datasheet",
               f"thiết bị tương đương {item['ten']} {item['thongso'][:80]}"]
    for q in queries:
        try:
            res = fn(q, key)
            if counter is not None:
                counter["used"] = counter.get("used", 0) + 1
            for o in res[:3]:
                ctx.append(f"[{o['title']}] {o['link']}\n{o['snippet']}")
            if cfg.get("fetch_pages", True) and res:
                ctx.append("NỘI DUNG TRANG: " + fetch_page(res[0]["link"]))
        except Exception as e:
            ctx.append(f"(lỗi tra cứu: {e})")
    return "\n---\n".join(ctx)
