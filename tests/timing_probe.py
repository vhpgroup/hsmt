# -*- coding: utf-8 -*-
"""ĐO THỜI GIAN THẬT từng khâu pipeline — KHÔNG sửa core/ (bọc hàm từ ngoài).

Chạy với key thật (đo pipeline thật):
  Windows:  set AI_API_KEY=sk-...
            set SERPER_API_KEY=...
            set EXA_API_KEY=...        (tùy chọn — có thì probe bật hybrid)
            set TAVILY_API_KEY=...     (tùy chọn — bật Tavily cứu hộ)
            python tests\timing_probe.py [file_hsmt.docx] [STT]
  Mặc định không truyền file: tự sinh mẫu STT 1 Bộ lưu điện (4 hàng con 1a-1d).

Chạy MÔ PHỎNG không cần key (kiểm tra cơ khí + ước lượng phân rã):
  PROBE_MOCK=1 [PROBE_SPEED=0.05] python tests/timing_probe.py

Kết quả: bảng thời gian theo khâu (số lần / tổng / trung bình / %),
danh sách call chậm nhất, và chỉ số "độ tuần tự" (tổng leaf-ops ≈ wall-clock
nghĩa là mọi thứ đang nối đuôi — song song hóa sẽ ăn gần trọn phần chênh).
"""
import json
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from core import analyzer, search as ws          # noqa: E402
from core.ai_engine import AIEngine              # noqa: E402
from core.extractor import extract               # noqa: E402
from core.preprocess import clean                # noqa: E402

MOCK = os.environ.get("PROBE_MOCK") == "1"
SPEED = float(os.environ.get("PROBE_SPEED", "1.0"))   # mock: 0.05 = chạy nhanh 20x, số liệu vẫn quy về tốc độ thật

# ===================== BỘ GHI THỜI GIAN =====================
_LOCK = threading.Lock()
_T0 = [None]
STATS = []            # (name, t_start_rel, dur)
_TLS = threading.local()


def _rec(name, t_start, dur):
    with _LOCK:
        STATS.append((name, t_start, dur))


def _wrap(obj, attr, name=None, label_from=None):
    """Bọc hàm/method để đo thời gian. label_from(args) -> hậu tố tên (vd tên hạng mục)."""
    fn = getattr(obj, attr)
    nm = name or attr

    def inner(*a, **k):
        lbl = nm
        if label_from:
            try:
                lbl = f"{nm} [{label_from(a)}]"
            except Exception:
                pass
        t0 = time.time()
        try:
            return fn(*a, **k)
        finally:
            dt = (time.time() - t0) / (SPEED if MOCK else 1.0)
            _rec(lbl, (t0 - _T0[0]) / (SPEED if MOCK else 1.0), dt)
    inner.__wrapped__ = fn
    setattr(obj, attr, inner)
    return fn


def _wrap_ai_op(attr):
    """Bọc method AIEngine cấp cao để gắn nhãn cho các lần chat bên trong (đếm cả repair JSON)."""
    fn = getattr(AIEngine, attr)

    def inner(self, *a, **k):
        prev = getattr(_TLS, "op", None)
        _TLS.op = attr
        _TLS.chat_in_op = 0
        t0 = time.time()
        try:
            return fn(self, *a, **k)
        finally:
            dt = (time.time() - t0) / (SPEED if MOCK else 1.0)
            n_chat = getattr(_TLS, "chat_in_op", 0)
            extra = f" (chat x{n_chat}{' — CÓ REPAIR JSON' if attr == 'extract_specs_batch' and n_chat > 1 else ''})"
            _rec(f"AI.{attr}{extra}", (t0 - _T0[0]) / (SPEED if MOCK else 1.0), dt)
            _TLS.op = prev
    setattr(AIEngine, attr, inner)


def install_probes():
    # Search leaf-ops (module-global lookup → bọc attribute là đủ, kể cả khi analyzer đã import)
    for f in ("serper", "tavily", "exa", "tavily_research", "fetch_page", "fetch_pdf"):
        _wrap(ws, f, name=f"search.{f}")
    ws.PROVIDERS = {"serper": ws.serper, "tavily": ws.tavily, "exa": ws.exa}  # đồng bộ dict với hàm đã bọc
    # Khâu tổng hợp ngữ cảnh cho từng hàng (bao trọn search+fetch của hàng đó)
    _wrap(ws, "build_context", name="build_context",
          label_from=lambda a: str(a[0].get("stt", "")) + " " + str(a[0].get("ten", ""))[:24])
    # AI
    _TLS.op = None
    fn_chat = AIEngine.chat

    def chat(self, *a, **k):
        _TLS.chat_in_op = getattr(_TLS, "chat_in_op", 0) + 1
        t0 = time.time()
        try:
            return fn_chat(self, *a, **k)
        finally:
            dt = (time.time() - t0) / (SPEED if MOCK else 1.0)
            _rec(f"AI.chat[{getattr(_TLS, 'op', None) or '?'}]", (t0 - _T0[0]) / (SPEED if MOCK else 1.0), dt)
    AIEngine.chat = chat
    for op in ("extract_specs_batch", "compare", "recheck_lines"):
        _wrap_ai_op(op)


# ===================== CHẾ ĐỘ MÔ PHỎNG (không cần key) =====================
# Độ trễ danh nghĩa lấy từ ĐO THẬT trong sandbox + latency điển hình của provider:
#   exa (kèm summary+highlights) ~6.0s (đo thật 6.1s) · serper ~1.2s · tavily advanced ~8s
#   fetch_page ~1.9s (đo thật 1.2-3.2s) · fetch_pdf ~6s · AI extract ~25s (+repair ~8s) · compare ~12s · recheck ~8s
def _msleep(nominal):
    time.sleep(nominal * SPEED)


def install_mocks():
    def mk_results(q, official_pdf=False):
        out = [{"title": f"ARES AR-MP10KRT UPS 10KVA {q[:18]}", "link": "https://arestech.vn/p/ar-mp10krt",
                "snippet": "Capacity 10000VA/10000W input voltage range 110~286Vac battery ±120Vdc rack 2U"},
               {"title": "UPS 10KVA đại lý", "link": "https://tanphat.com.vn/ups-ares",
                "snippet": "AR-MP10KRT online PF 1.0 song sine chuan RS232/USB"}]
        if official_pdf:
            out.insert(0, {"title": "Datasheet PDF", "link": "https://arestech.vn/ds/ar-mp10krt.pdf",
                           "snippet": "MP RT series datasheet 440 x 625 x 86.5 mm"})
        return out

    ws.serper = lambda q, key, num=5, **kw: (_msleep(1.2), mk_results(q, official_pdf=("filetype:pdf" in q)))[1]
    ws.exa = lambda q, key, num=5, **kw: (_msleep(6.0), mk_results(q))[1]
    ws.tavily = lambda q, key, num=5, **kw: (_msleep(1.5), mk_results(q))[1]
    ws.tavily_research = lambda q, key, max_results=5: (_msleep(8.0),
        "TAVILY TỔNG HỢP: suc chua 20 binh 12V9AH dang rack 3U thep son tinh dien\n"
        "https://arestech.vn/cabinet: tu dung binh ac quy suc chua 20 binh 12V9AH khoa an toan")[1]
    ws.fetch_page = lambda url, limit=8000: (_msleep(1.9),
        "Trang chinh hang ARES AR-MP10KRT capacity 10000VA/10000W input voltage range 110~286Vac "
        "battery voltage ±120Vdc dimension 440 x 625 x 86.5 mm rack tower RS232/USB pure sinewave PF 1.0 "
        "tan so 50/60 ±0.1% Hz tu dong nhan dien ap nguon ra 208/220/230/240Vac ±1%")[1]
    ws.fetch_pdf = lambda url, limit=16000: (_msleep(6.0),
        "[BANG] Capacity | 10000VA/10000W [BANG] Input voltage range | 110~286Vac [BANG] Battery | ±120Vdc "
        "PDF datasheet AR-MP10KRT rack 2U 440 x 625 x 86.5")[1]
    ws.PROVIDERS = {"serper": ws.serper, "tavily": ws.tavily, "exa": ws.exa}

    state = {"extract_calls": 0}
    SPEC = [{"stt": "1", "ten_hang_hoa_muc": "Bộ lưu điện", "tin_cay": "Cao", "can_cu": "mock",
             "hang_muc_con": [
                 {"ten_hang_muc_con": "Bộ Lưu Điện 10KVA 10KW", "trang_thai_thong_so": "co_thong_so",
                  "loai_hang_muc": "doc_lap", "phu_thuoc_hang_muc_con": None,
                  "thong_so": [{"nhom_thong_so": None, "ten_thong_so": t, "gia_tri_yeu_cau": v, "don_vi": None,
                                "toan_tu_so_sanh": "=", "gia_tri_so": None, "gia_tri_so_min": None,
                                "gia_tri_so_max": None, "loai_du_lieu": "thong_so_ky_thuat", "muc_do": "bat_buoc",
                                "trich_dan_nguon": f"{t}: {v}"}
                               for t, v in [("Công suất", "10KVA/10KW"), ("Thiết kế", "dạng Rack"),
                                            ("Công nghệ", "Online"), ("PF", "1.0"),
                                            ("Điện áp vào", "110~286Vac"), ("Điện áp ắc quy", "±120Vdc")]]},
                 {"ten_hang_muc_con": "Tủ đựng bình Ắc Quy", "trang_thai_thong_so": "co_thong_so",
                  "loai_hang_muc": "doc_lap", "phu_thuoc_hang_muc_con": None,
                  "thong_so": [{"nhom_thong_so": None, "ten_thong_so": "Sức chứa", "gia_tri_yeu_cau": "≥ 20 bình 12V9AH",
                                "don_vi": None, "toan_tu_so_sanh": ">=", "gia_tri_so": 20, "gia_tri_so_min": None,
                                "gia_tri_so_max": None, "loai_du_lieu": "thong_so_ky_thuat", "muc_do": "bat_buoc",
                                "trich_dan_nguon": "Có sức chứa ≥ 20 bình 12V9AH"}]},
                 {"ten_hang_muc_con": "Ắc quy 12V9AH", "trang_thai_thong_so": "co_thong_so",
                  "loai_hang_muc": "doc_lap", "phu_thuoc_hang_muc_con": None,
                  "thong_so": [{"nhom_thong_so": None, "ten_thong_so": "Điện áp DC", "gia_tri_yeu_cau": "12V",
                                "don_vi": "V", "toan_tu_so_sanh": "=", "gia_tri_so": 12, "gia_tri_so_min": None,
                                "gia_tri_so_max": None, "loai_du_lieu": "thong_so_ky_thuat", "muc_do": "bat_buoc",
                                "trich_dan_nguon": "Điện áp DC: 12V"}]},
             ]}]
    CMP_OK = {"ung_vien": [{"model": "AR-MP10KRT", "hang": "ARES", "dat_100": True, "nguon_loai": "Chính hãng",
                            "nguon": "https://arestech.vn/p/ar-mp10krt",
                            "bang": [{"yeu_cau": "Công suất", "thong_so_hsmt": "10KVA/10KW",
                                      "gia_tri": "10000VA/10000W", "danh_gia": "Đạt",
                                      "trich_dan": "capacity 10000VA/10000W input voltage range"}]}],
              "nhan_xet": "mock đạt"}
    CMP_MISS = {"ung_vien": [{"model": "CAB-3U", "hang": "ARES", "dat_100": True, "nguon_loai": "Đại lý/tổng hợp",
                              "nguon": "https://tanphat.com.vn/ups-ares",
                              "bang": [{"yeu_cau": "Sức chứa", "thong_so_hsmt": "≥ 20 bình 12V9AH",
                                        "gia_tri": "20 bình", "danh_gia": "Đạt",
                                        "trich_dan": "TRICH DAN BIA KHONG CO TRONG NGU CANH XYZ"}]}],
                "nhan_xet": "mock thiếu bằng chứng → kích hoạt Tavily cứu hộ"}
    RECHECK = {"bang": [{"yeu_cau": "Sức chứa", "thong_so_hsmt": "≥ 20 bình 12V9AH", "gia_tri": "20 bình 12V9AH",
                         "danh_gia": "Đạt", "trich_dan": "suc chua 20 binh 12V9AH dang rack"}]}

    def chat(self, prompt, retries=3, timeout=60, **kw):
        # KHÔNG tự ghi thời gian ở đây — probe (install_probes chạy SAU) sẽ bọc ngoài và ghi
        op = getattr(_TLS, "op", None)
        if op == "extract_specs_batch":
            state["extract_calls"] += 1
            if state["extract_calls"] == 1:
                _msleep(25.0); out = json.dumps(SPEC, ensure_ascii=False)[:120]     # JSON cụt → kích hoạt repair
            else:
                _msleep(8.0); out = json.dumps(SPEC, ensure_ascii=False)            # repair trả JSON chuẩn
        elif op == "compare":
            _msleep(12.0)
            # chỉ 1a (UPS) đạt ngay; 1b/1c trả trích dẫn bịa → verify loại → kích hoạt Tavily cứu hộ (như bản chạy thật)
            out = json.dumps(CMP_OK if "Bộ Lưu Điện 10KVA" in prompt else CMP_MISS, ensure_ascii=False)
        elif op == "recheck_lines":
            _msleep(8.0); out = json.dumps(RECHECK, ensure_ascii=False)
        else:
            _msleep(3.0); out = "{}"
        self.usage["in"] += len(prompt) // 4
        self.usage["out"] += len(out) // 4
        return out
    AIEngine.chat = chat


# ===================== FILE MẪU & CẤU HÌNH =====================
def _ensure_sample(path):
    if os.path.exists(path):
        return path
    from docx import Document
    doc = Document()
    t = doc.add_table(rows=1, cols=3)
    h = t.rows[0].cells
    h[0].text, h[1].text, h[2].text = "STT", "Tên hàng hóa", "Thông số kỹ thuật và các tiêu chuẩn"
    c = t.add_row().cells
    c[0].text, c[1].text = "1", "Bộ lưu điện"
    c[2].text = ("1/ Bộ Lưu Điện 10KVA 10KW\n. Công suất: 10KVA/10KW\n. Thiết kế dạng Rack\n. Công nghệ Online\n"
                 ". Hệ số công suất PF 1.0\n. Điện áp nguồn vào: 208/220/230/240Vac (110~286Vac)\n"
                 ". Điện áp nguồn ra: 208/220/230/240Vac ± 1%\n. Tần số: 50/60 ± 0.1% Hz (tự động nhận)\n"
                 ". Dạng sóng: Sóng sine chuẩn\n. Cổng kết nối: RS232/USB\n. Điện áp ắc quy: ±120Vdc\n"
                 "2/ Tủ đựng bình Ắc Quy\n. Dạng Rack\n. Có sức chứa ≥ 20 bình 12V9AH\n"
                 "3/ Ắc quy 12V9AH\n. Loại: kín khí\n. Điện áp DC: 12V\n"
                 "4/ Rail Kit - Thanh trượt gắn tủ Rack cho UPS")
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    doc.save(path)
    return path


def build_cfg():
    if MOCK:
        return {"api_key": "mock", "model": "gpt-4.1-mini", "search_mode": "hybrid",
                "serper_key": "mock", "exa_key": "mock", "tavily_key": "mock",
                "fetch_pages": True, "compare": True, "ttl_days": 0}
    cfg = {
        "api_key": os.environ["AI_API_KEY"],
        "model": os.environ.get("AI_MODEL", "gpt-4.1-mini"),
        "base_url": os.environ.get("AI_BASE_URL", ""),
        "serper_key": os.environ.get("SERPER_API_KEY", ""),
        "exa_key": os.environ.get("EXA_API_KEY", ""),
        "tavily_key": os.environ.get("TAVILY_API_KEY", ""),
        "fetch_pages": True, "compare": True,
        "ttl_days": 0,                       # 0 = bỏ cache, đo fresh thật
    }
    # có Exa → đo đúng chế độ hybrid như bản chạy 277.5s; không thì Serper thuần
    cfg["search_mode"] = "hybrid" if cfg["exa_key"] else ""
    cfg["search_provider"] = "serper"
    cfg["search_key"] = cfg["serper_key"]
    return cfg


# ===================== BÁO CÁO =====================
def report(wall, counter, ai):
    by = {}
    for name, _t, dur in STATS:
        key = name.split(" [")[0]
        agg = by.setdefault(key, [0, 0.0])
        agg[0] += 1
        agg[1] += dur
    # leaf-ops = mạng + AI (không tính build_context/op cấp cao để khỏi đếm trùng)
    leaf_keys = [k for k in by if k.startswith("search.") or k.startswith("AI.chat")]
    leaf_sum = sum(by[k][1] for k in leaf_keys)

    print("\n" + "=" * 74)
    print(f"BÁO CÁO THỜI GIAN — wall-clock {wall:.1f}s | search calls: {counter.get('used', 0)} | "
          f"token AI: {ai.usage['in']:,} vào / {ai.usage['out']:,} ra" + ("  [MÔ PHỎNG]" if MOCK else ""))
    print("=" * 74)
    print(f"{'KHÂU':44} {'LẦN':>4} {'TỔNG(s)':>9} {'TB(s)':>7} {'%WALL':>6}")
    order = sorted(((k, v) for k, v in by.items()), key=lambda x: -x[1][1])
    for k, (n, tot) in order:
        print(f"{k:44} {n:>4} {tot:>9.1f} {tot / n:>7.1f} {100 * tot / max(wall, 0.01):>5.0f}%")
    print("-" * 74)
    print("Lưu ý: build_context BAO GỒM các search.*/fetch_* bên trong; AI.<op> bao gồm")
    print("AI.chat[...] — nên % các dòng không cộng dồn thành 100%.")
    ratio = leaf_sum / max(wall, 0.01)
    print(f"Tổng leaf-ops (mạng + AI, cộng dồn): {leaf_sum:.1f}s = {100 * ratio:.0f}% wall-clock")
    if ratio > 1.15:
        print(f"→ Pipeline ĐANG SONG SONG: khối lượng {leaf_sum:.0f}s được nén còn {wall:.0f}s "
              f"(hệ số chạy chồng ~{ratio:.1f}x).")
    elif ratio > 0.85:
        print("→ Pipeline gần như TUẦN TỰ THUẦN: mọi call nối đuôi nhau.")
        print("→ Song song hóa (dòng con + engine + fetch + compare) sẽ đưa wall-clock")
        print("  về ≈ nhánh chậm nhất thay vì tổng tất cả.")
    print("\nTOP 12 CALL CHẬM NHẤT (thời điểm bắt đầu → khoảng chạy):")
    for name, t0, dur in sorted(STATS, key=lambda x: -x[2])[:12]:
        print(f"  t+{t0:>6.1f}s  {dur:>6.1f}s  {name[:58]}")


def main():
    if MOCK:
        install_mocks()      # mock TRƯỚC, probe SAU → đo được cả search leaf-ops giả lập
        print(f"[CHẾ ĐỘ MÔ PHỎNG — độ trễ danh nghĩa từ đo thật, tốc độ x{1 / SPEED:.0f}]")
    install_probes()
    path = sys.argv[1] if len(sys.argv) > 1 else _ensure_sample(
        os.environ.get("SAMPLE_FILE", "tests/sample_timing.docx"))
    only_stt = sys.argv[2] if len(sys.argv) > 2 else os.environ.get("ONLY_STT", "")

    raw = extract(path)
    items = clean(raw["items"])
    if only_stt:
        items = [it for it in items if str(it["stt"]).strip().rstrip(".") == only_stt]
    if not items:
        print("Không có hạng mục nào khớp — kiểm tra file/STT.")
        return
    print(f"File: {raw['meta']['file']} — đo {len(items)} hạng mục: "
          + ", ".join(f"STT {it['stt']} {it['ten'][:20]}" for it in items[:5]))

    cfg = build_cfg()
    ai = AIEngine(cfg)
    counter = {"used": 0}
    _T0[0] = time.time()
    t0 = time.time()
    analyzer.run(items, cfg, ai, progress=lambda s, p: print(f"  [{p:3d}%] {s}"), counter=counter)
    wall = (time.time() - t0) / (SPEED if MOCK else 1.0)
    report(wall, counter, ai)


if __name__ == "__main__":
    main()
