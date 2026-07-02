# -*- coding: utf-8 -*-
"""Smoke test THẬT: chạy pipeline với AI + Serper thật (key từ env/CI secrets), không cần GUI.
Chạy cục bộ:  AI_API_KEY=... SERPER_API_KEY=... python tests/smoke_test.py
Trên CI: tự chạy mỗi lần push (xem .github/workflows/test.yml)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import analyzer  # noqa: E402
from core.ai_engine import AIEngine  # noqa: E402
from core.extractor import extract  # noqa: E402
from core.preprocess import clean  # noqa: E402


def _ensure_sample(path):
    """Tự sinh file hồ sơ mẫu nếu chưa có — khỏi cần commit file nhị phân vào repo."""
    if os.path.exists(path):
        return path
    from docx import Document
    doc = Document()
    t = doc.add_table(rows=1, cols=3)
    hdr = t.rows[0].cells
    hdr[0].text, hdr[1].text, hdr[2].text = "STT", "Tên hàng hóa", "Thông số kỹ thuật và các tiêu chuẩn"
    rows = [
        ("1", "Bộ lưu điện",
         "1/ Bộ Lưu Điện 10KVA 10KW\n. Công suất: 10KVA/10KW\n. Thiết kế dạng Rack\n. Công nghệ Online\n"
         ". Hệ số công suất PF 1.0\n. Điện áp ắc quy: ±120Vdc\n2/ Tủ đựng bình Ắc Quy\n. Dạng Rack\n"
         ". Có sức chứa ≥ 20 bình 12V9AH\n3/ Ắc quy 12V9AH\n. Loại: kín khí\n. Điện áp DC: 12V"),
        ("2", "Màn hình hỗ trợ thanh toán",
         "Màn hình ≤ 23,8 inch, IPS, FHD 1920x1080, tương phản tĩnh 1.300:1, độ sáng 250 cd/m², "
         "tỷ lệ 16:9, kết nối VGA + HDMI + Audio 3.5mm"),
        ("3", "Hạt mạng RJ45", "Đầu mạng RJ45 UTP Cat6"),
    ]
    for r in rows:
        c = t.add_row().cells
        c[0].text, c[1].text, c[2].text = r
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    doc.save(path)
    print(f"(đã tự sinh file mẫu: {path})")
    return path


def main():
    cfg = {
        "api_key": os.environ["AI_API_KEY"],
        "model": os.environ.get("AI_MODEL", "gpt-4.1-mini"),
        "base_url": os.environ.get("AI_BASE_URL", ""),
        "search_provider": os.environ.get("SEARCH_PROVIDER", "serper"),
        "search_key": os.environ["SERPER_API_KEY"],
        "fetch_pages": True,
        "compare": True,
        "ttl_days": 0,  # 0 = bỏ qua cache, luôn gọi thật
    }
    sample = _ensure_sample(os.environ.get("SAMPLE_FILE", "tests/sample.docx"))
    n_items = int(os.environ.get("SMOKE_ITEMS", "3"))  # 3 mục đầu cho nhanh/rẻ (~9 lượt Serper)

    raw = extract(sample)
    items = clean(raw["items"])[:n_items]
    assert items, "FAIL: không trích được hạng mục nào từ file mẫu"
    print(f"File mẫu: {raw['meta'].get('file')} — test {len(items)}/{raw['meta'].get('n_items')} mục đầu\n")

    ai = AIEngine(cfg)
    counter = {"used": 0}
    res = analyzer.run(items, cfg, ai, progress=lambda s, p: print(f"[{p:3d}%] {s}"), counter=counter)

    ok_specs = sum(1 for r in res if (r.get("ident") or {}).get("thong_so"))
    with_cand = [r for r in res if (r.get("so_sanh") or {}).get("ung_vien")]
    print(f"\n== KẾT QUẢ: {len(res)} hàng (sau tách thiết bị con) | {ok_specs} hàng có thông số | "
          f"{len(with_cand)} hàng có ứng viên đạt 100% | Serper: {counter['used']} lượt | "
          f"token: {ai.usage['in']} vào / {ai.usage['out']} ra")
    for r in res:
        uv = (r.get("so_sanh") or {}).get("ung_vien", [])
        if uv:
            top = f"✔ {uv[0].get('model', '')} — {uv[0].get('hang', '')} [{uv[0].get('nguon_loai', '')[:20]}]"
        else:
            top = "· " + str((r.get("so_sanh") or {}).get("nhan_xet", ""))[:70]
        print(f"  {str(r['stt']):>4} | {r['ten'][:38]:38} | {top}")

    # Điều kiện PASS: mọi hàng phải trích được thông số; pipeline không văng lỗi
    assert ok_specs == len(res), f"FAIL: {len(res) - ok_specs} hàng không trích được thông số"
    print("\nSMOKE TEST PASS ✅")


if __name__ == "__main__":
    main()
