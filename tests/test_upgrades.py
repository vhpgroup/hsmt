# -*- coding: utf-8 -*-
"""Unit test cho gói nâng cấp 3 đợt (chạy: python tests/test_upgrades.py — không cần key, không HTTP)."""
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from core import analyzer as az           # noqa: E402
from core import search as ws             # noqa: E402

PASS = 0


def ok(cond, msg):
    global PASS
    assert cond, "FAIL: " + msg
    PASS += 1
    print(f"  ✓ {msg}")


# ===== B2 — lô extract động AN TOÀN TIMEOUT =====
todo = [{"thongso": "x" * 500} for _ in range(8)]
b = az._make_batches(todo)
ok(len(b) == 3 and [len(x) for x in b] == [3, 3, 2], "B2: 8 mục ngắn → 3 lô (3+3+2) — trần 3 mục/lô")
b2 = az._make_batches([{"thongso": "x" * 4000}, {"thongso": "x" * 4000}])
ok(len(b2) == 2 and all(len(x) == 1 for x in b2), "B2: mục dài 4000 ký tự → mỗi mục MỘT MÌNH một lô")
b3 = az._make_batches([{"thongso": "x" * 100}, {"thongso": "x" * 2500}, {"thongso": "x" * 100}])
ok([len(x) for x in b3] == [1, 1, 1] and len(b3[1]) == 1,
   "B2: mục dài kẹp giữa 2 mục ngắn → tách solo, không kéo mục ngắn chết chung (bài học 21/39 hàng hỏng)")

# ===== A1 — máy so số học =====
ok(az._num_variants("23,8") == [23.8], "A1: '23,8' đọc kiểu VN = 23.8")
ok(az._num_variants("86.5") == [86.5], "A1: '86.5' = 86.5")
ok(set(az._num_variants("1.300")) == {1.3, 1300.0}, "A1: '1.300' mơ hồ → thử cả 1.3 và 1300")

spec_num = {"thong_so": [
    {"ten": "Độ sáng", "gia_tri": "≥ 300 nits", "don_vi": "nits", "toan_tu_so_sanh": ">=", "gia_tri_so": 300},
    {"ten": "Công suất nguồn", "gia_tri": "≥ 370W", "don_vi": "W", "toan_tu_so_sanh": ">=", "gia_tri_so": 370},
    {"ten": "Kích thước màn", "gia_tri": "≤ 23,8 inch", "don_vi": "inch", "toan_tu_so_sanh": "<=", "gia_tri_so": 23.8},
]}
res = {"ung_vien": [{"model": "X1", "hang": "T", "dat_100": True, "bang": [
    {"yeu_cau": "Độ sáng", "gia_tri": "250 nits", "danh_gia": "Đạt", "trich_dan": "brightness 250 nits"},
]}]}
out = az._numeric_recheck(res, spec_num)
ok(out["ung_vien"][0]["dat_100"] is False and "máy so số học" in out["ung_vien"][0]["bang"][0]["danh_gia"],
   "A1: AI chấm Đạt nhưng 250 < 300 → máy hạ Không đạt + loại model")

res2 = {"ung_vien": [{"model": "X2", "hang": "T", "dat_100": True, "bang": [
    {"yeu_cau": "Công suất nguồn", "gia_tri": "0.4 kW PoE budget", "danh_gia": "Đạt", "trich_dan": "0.4kW"},
]}]}
out2 = az._numeric_recheck(res2, spec_num)
ok(out2["ung_vien"][0]["dat_100"] is True, "A1: 0.4kW = 400W ≥ 370W — quy đổi đơn vị đúng, giữ model")

res3 = {"ung_vien": [{"model": "X3", "hang": "T", "dat_100": True, "bang": [
    {"yeu_cau": "Kích thước màn", "gia_tri": "27 inch", "danh_gia": "Đạt", "trich_dan": "27 inch"},
]}]}
out3 = az._numeric_recheck(res3, spec_num)
ok(out3["ung_vien"][0]["dat_100"] is False, "A1: yêu cầu ≤23.8 inch, model 27 inch → máy bắt đúng chiều ≤")

res4 = {"ung_vien": [{"model": "X4", "hang": "T", "dat_100": True, "bang": [
    {"yeu_cau": "Độ sáng", "gia_tri": "sáng rõ ban ngày", "danh_gia": "Đạt", "trich_dan": "x"},
]}]}
out4 = az._numeric_recheck(res4, spec_num)
ok(out4["ung_vien"][0]["dat_100"] is True, "A1: giá trị không có số → không phán bừa, giữ verdict AI")

# ===== A5 — tiêu chí không bắt buộc =====
spec_opt = {"thong_so": [
    {"ten": "Công suất", "gia_tri": "10KVA", "muc_do": "bat_buoc"},
    {"ten": "Màu sắc vỏ", "gia_tri": "đen", "muc_do": "khong_ro"},
]}
opt = az._optional_crits(spec_opt)
cand = {"dat_100": True, "bang": [
    {"yeu_cau": "Công suất", "danh_gia": "Đạt"},
    {"yeu_cau": "Màu sắc vỏ", "danh_gia": "Chưa rõ"},
]}
ok(az._is_passing_candidate(cand, opt) is True, "A5: dòng khong_ro 'Chưa rõ' không làm rớt model")
ok(az._is_passing_candidate(cand, set()) is False, "A5: không có optional → luật 100% chặt như cũ")

# ===== B1 — cứu hộ: trích dẫn Tavily phải nằm trong cửa sổ kiểm chứng =====
tav_ctx = "TAVILY: suc chua 20 binh 12V9AH dang rack thep son tinh dien"
big_ctx = "z" * (az.VERIFY_CTX_LIMIT + 5000)          # ctx dài vượt trần
r = {"ung_vien": [{"model": "C", "hang": "A", "dat_100": True, "bang": [
    {"yeu_cau": "Sức chứa", "danh_gia": "Đạt", "trich_dan": "suc chua 20 binh 12V9AH"}]}]}
bad = az._verify_quotes({"ung_vien": [dict(r["ung_vien"][0], bang=[dict(r["ung_vien"][0]["bang"][0])])]},
                        big_ctx + "\n" + tav_ctx)
ok(bad["ung_vien"][0]["dat_100"] is False, "B1: thứ tự cũ (ctx trước) → trích dẫn bị cắt, cứu hộ thất bại (tái hiện bug)")
good = az._verify_quotes(r, tav_ctx + "\n" + big_ctx)
ok(good["ung_vien"][0]["dat_100"] is True, "B1: thứ tự mới (tav_ctx trước) → trích dẫn nằm trong cửa sổ, cứu thành công")

# ===== A6 — nhãn nguồn =====
r6 = {"ung_vien": [
    {"model": "AR-MP10KRT", "hang": "ARES", "nguon": "https://arestech.vn/p/ups", "dat_100": True, "bang": []},
    {"model": "WP9-12", "hang": "Long", "nguon": "https://www.klb.com.tw/ds.pdf", "dat_100": True, "bang": []},
    {"model": "Z", "hang": "Santak", "nguon": "https://tanphat.com.vn/x", "dat_100": True, "bang": []},
]}
az._check_official_source(r6)
lab = {c["model"]: c["nguon_loai"] for c in r6["ung_vien"]}
ok(lab["AR-MP10KRT"] == "Chính hãng", "A6: arestech.vn chứa brand ARES → Chính hãng (hết gắn nhầm Đại lý)")
ok(lab["WP9-12"] == "Chính hãng", "A6: klb.com.tw (Kung Long) vào CORP_DOMAINS → Chính hãng")
ok(lab["Z"].startswith("Đại lý"), "A6: tanphat.com.vn với brand Santak → vẫn Đại lý (không nới lỏng bừa)")

# ===== B3-2 — dedup mờ =====
ok(az._similar_name("Rail Kit - Thanh trượt gắn tủ Rack cho UPS", "Rail Kit thanh truot gan tu rack") is False or True,
   "B3-2: hàm chạy không lỗi với tiếng Việt có/không dấu")
ok(az._similar_name("Rail Kit - Thanh trượt gắn tủ Rack", "Rail Kit - Thanh trượt gắn tủ Rack cho UPS") is True,
   "B3-2: chuỗi chứa nhau → coi là một (không nhân đôi Rail Kit)")
exist = [{"ten_thiet_bi": "Rail Kit - Thanh trượt gắn tủ Rack cho UPS"}]
extras = az._extra_empty_components_from_text(
    {"ten": "UPS", "thongso": "1/ UPS 10KVA\n4/ Rail Kit - Thanh trượt gắn tủ Rack cho UPS"}, exist)
ok(extras == [], "B3-2: AI đã bắt Rail Kit → regex không thêm bản sao")

# ===== B3-1 — lọc vật tư thi công =====
spec_mixed = {"thong_so": [
    {"ten": "CPU", "gia_tri": "i5", "loai_du_lieu": "thong_so_ky_thuat"},
    {"ten": "TCVN", "gia_tri": "7326-1", "loai_du_lieu": "tieu_chuan_chung_chi"},
    {"ten": "Dây nguồn, cos, CB", "gia_tri": "đồng bộ", "loai_du_lieu": "vat_tu_thi_cong"},
]}
f, has, dropped = az._searchable_spec(spec_mixed)
ok(len(f["thong_so"]) == 2 and has and dropped, "B3-1: giữ kỹ thuật + TCVN, loại dòng vật tư phụ khỏi tiêu chí")
f2, has2, _ = az._searchable_spec({"thong_so": [
    {"ten": "Nhân công lắp đặt", "gia_tri": "trọn gói", "loai_du_lieu": "vat_tu_thi_cong"}]})
ok(not has2, "B3-1: hàng toàn dòng dịch vụ → nhận diện 'không tìm model'")

# ===== A4 — từ khóa nới số =====
ident = {"loai_thiet_bi": "Switch L2 24 cổng PoE", "thong_so": [
    {"ten": "Băng thông", "gia_tri": "82 Gbps", "toan_tu_so_sanh": "=", "loai_du_lieu": "thong_so_ky_thuat"},
    {"ten": "Chuyển mạch", "gia_tri": "61 Mpps", "toan_tu_so_sanh": "=", "loai_du_lieu": "thong_so_ky_thuat"},
    {"ten": "Công suất PoE", "gia_tri": "≥370W", "toan_tu_so_sanh": ">=", "loai_du_lieu": "thong_so_ky_thuat"},
]}
kw2 = ws._kw_relaxed({"ten": "Switch"}, ident)
ok("370" in kw2 and "61" not in kw2 and "82" not in kw2,
   "A4: bản nới giữ ngưỡng ≥370W, bỏ số vân tay 61Mpps/82Gbps")

# ===== S3 — dedup query toàn phiên =====
calls = {"n": 0}


def fake_fn(q, key, num, **kw):
    calls["n"] += 1
    return [{"title": "t", "link": "https://a.vn/x", "snippet": "s"}]


cfg_q = {"_qcache": {"lock": threading.Lock(), "data": {}}}
ctr = {"used": 0}
ws._run_search("serper", fake_fn, "ups 10kva datasheet", "k", 5, cfg_q, ctr)
ws._run_search("serper", fake_fn, "UPS 10KVA datasheet ", "k", 5, cfg_q, ctr)   # khác hoa thường/khoảng trắng
ok(calls["n"] == 1 and ctr["used"] == 1, "S3: query trùng (case/space-insensitive) → 1 HTTP, 1 credit")

# ===== S2 — Structured Outputs: schema hợp lệ + hạ cấp =====
from core.ai_engine import AIEngine, EXTRACT_SCHEMA      # noqa: E402

eng = AIEngine({"api_key": "x", "model": "gpt-4.1-mini"})
rf2 = eng._response_format(EXTRACT_SCHEMA, False)
ok(rf2["type"] == "json_schema" and rf2["json_schema"]["strict"] is True, "S2: mức 2 → json_schema strict")
eng._rf_level = 1
ok(eng._response_format(EXTRACT_SCHEMA, False)["type"] == "json_object", "S2: hạ cấp mức 1 → json_object")
eng._rf_level = 0
ok(eng._response_format(EXTRACT_SCHEMA, True) is None, "S2: mức 0 → tắt response_format")
ok(az.VERIFY_CTX_LIMIT == 90000, "A2: trần kiểm chứng = trần compare = 90K (1 nguồn sự thật)")

# ===== Tích hợp nhỏ: run() song song với AI + search giả =====
class FakeAI:
    usage = {"in": 0, "out": 0}

    def extract_specs_batch(self, items):
        out = []
        for it in items:
            out.append({"stt": it["stt"], "ten_hang_hoa_muc": it["ten"], "tin_cay": "Cao", "can_cu": "t",
                        "hang_muc_con": [{"ten_hang_muc_con": it["ten"], "trang_thai_thong_so": "co_thong_so",
                                          "loai_hang_muc": "doc_lap", "phu_thuoc_hang_muc_con": None,
                                          "thong_so": [{"nhom_thong_so": None, "ten_thong_so": "Công suất",
                                                        "gia_tri_yeu_cau": "≥ 300 W", "don_vi": "W",
                                                        "toan_tu_so_sanh": ">=", "gia_tri_so": 300,
                                                        "gia_tri_so_min": None, "gia_tri_so_max": None,
                                                        "loai_du_lieu": "thong_so_ky_thuat", "muc_do": "bat_buoc",
                                                        "trich_dan_nguon": "Công suất ≥ 300 W"}]}]})
        return out

    def compare(self, item, spec, ctx):
        return {"ung_vien": [{"model": "M1", "hang": "BrandX", "dat_100": True, "nguon": "https://brandx.com/ds",
                              "bang": [{"yeu_cau": "Công suất", "thong_so_hsmt": "≥ 300 W", "gia_tri": "350 W",
                                        "danh_gia": "Đạt", "trich_dan": "cong suat dinh muc 350 W lien tuc"}]}],
                "nhan_xet": "ok"}

    def recheck_lines(self, *a):
        return {"bang": []}


ws_ctx_calls = {"n": 0, "threads": set()}
orig_bc = ws.build_context


def fake_bc(item, ident, cfg, counter=None):
    ws_ctx_calls["n"] += 1
    ws_ctx_calls["threads"].add(threading.current_thread().name)
    import time as _t
    _t.sleep(0.03)          # mô phỏng I/O — không có nó task xong tức thời, pool chỉ kịp mở 1 thread
    return "datasheet BrandX M1 cong suat dinh muc 350 W lien tuc"


ws.build_context = fake_bc
az.cache.get = lambda *a, **k: None          # tắt cache thật (đừng đụng DB local)
az.cache.put = lambda *a, **k: None
items = [{"id": f"i{n}#%d" % n, "stt": str(n + 1), "ten": f"Thiết bị {n + 1}", "thongso": "Công suất ≥ 300 W"}
         for n in range(4)]
rows = az.run(items, {"compare": True, "ttl_days": 0, "parallel_items": 4, "parallel_ai": 3}, FakeAI(),
              counter={"used": 0})
ws.build_context = orig_bc
ok(len(rows) == 4 and all(r is not None for r in rows), "S1: run() song song trả đủ 4 hàng, không None")
ok(all((r.get("so_sanh") or {}).get("ung_vien") for r in rows), "S1: cả 4 hàng có ứng viên đạt 100% sau kiểm chứng")
ok(rows[0]["stt"] == "1" and rows[3]["stt"] == "4", "S1: thứ tự hàng giữ nguyên dù chạy song song")
ok(len(ws_ctx_calls["threads"]) >= 2, "S1: build_context chạy trên ≥2 thread (song song thật)")

# ===== F2 — bisect retry: lô lỗi chia đôi, chỉ 1 mục chịu trận =====
class TimeoutOnBigBatchAI(FakeAI):
    def __init__(self):
        self.calls = []

    def extract_specs_batch(self, items):
        self.calls.append(len(items))
        if len(items) > 1:
            raise RuntimeError("ReadTimeout: endpoint did not return within 150s")
        if items[0]["stt"] == "2":
            raise RuntimeError("ReadTimeout: mục 2 hỏng thật")
        return FakeAI.extract_specs_batch(self, items)


tb_ai = TimeoutOnBigBatchAI()
items3 = [{"id": f"b{n}#%d" % n, "stt": str(n + 1), "ten": f"TB {n + 1}", "thongso": "Công suất ≥ 300 W"}
          for n in range(3)]
ws.build_context = fake_bc
rows3 = az.run(items3, {"compare": True, "ttl_days": 0, "parallel_items": 2}, tb_ai, counter={"used": 0})
ws.build_context = orig_bc
n_ok_specs = sum(1 for r in rows3 if (r.get("ident") or {}).get("thong_so"))
ok(n_ok_specs == 2, "F2: lô 3 mục timeout → bisect → 2 mục sống, chỉ mục hỏng thật rơi fallback")
ok(any("lỗi ai" in str((r.get("ident") or {}).get("can_cu", "")).lower() for r in rows3),
   "F2: mục hỏng thật vẫn ghi rõ 'Lỗi AI' để không bị cache")

# ===== F4 — hàng toàn yeu_cau_chung (phần mềm) KHÔNG bị coi là dịch vụ =====
spec_sw = {"thong_so": [
    {"ten": "Tính năng", "gia_tri": "Synchronized Security Heartbeat", "loai_du_lieu": "yeu_cau_chung"},
    {"ten": "Hệ điều hành", "gia_tri": "Windows và MacOS", "loai_du_lieu": "yeu_cau_chung"},
]}
_, has_s, _ = az._searchable_spec(spec_sw)
has_vt = any((r.get("loai_du_lieu") or "") == "vat_tu_thi_cong" for r in spec_sw["thong_so"])
ok(not has_s and not has_vt, "F4: nhận diện đúng case 'toàn yeu_cau_chung, không vật tư' (Sophos STT 36)")
spec_labor = {"thong_so": [{"ten": "Nhân công", "gia_tri": "trọn gói", "loai_du_lieu": "vat_tu_thi_cong"}]}
_, has_s2, _ = az._searchable_spec(spec_labor)
has_vt2 = any((r.get("loai_du_lieu") or "") == "vat_tu_thi_cong" for r in spec_labor["thong_so"])
ok(not has_s2 and has_vt2, "F4: hàng nhân công thật vẫn vào nhánh dịch vụ (có vat_tu_thi_cong)")

# ===== R1 — sort STT tự nhiên cho bảng live =====
from core.preprocess import stt_sort_key          # noqa: E402

jumbled = ["2", "1b", "10", "1a", "1", "3a"]
ok([s for s in sorted(jumbled, key=stt_sort_key)] == ["1", "1a", "1b", "2", "3a", "10"],
   "R1: thứ tự hoàn thành lộn xộn → sort về 1 < 1a < 1b < 2 < 3a < 10 (không phải '10' < '2' kiểu chuỗi)")

# ===== R5 — hủy run lan qua mọi worker song song =====
import time as _time                              # noqa: E402

calls = {"n": 0}


def cancelling_pause_check():
    calls["n"] += 1
    if calls["n"] >= 3:
        raise RuntimeError("Đã dừng phân tích theo yêu cầu")


t0 = _time.time()
try:
    az.run(items, {"compare": True, "ttl_days": 0, "parallel_items": 4}, FakeAI(),
           counter={"used": 0}, pause_check=cancelling_pause_check)
    raised = False
except RuntimeError as e:
    raised = "Đã dừng" in str(e)
dt_cancel = _time.time() - t0
ok(raised, "R5: pause_check báo hủy → analyzer.run nổi RuntimeError (không nuốt, không treo)")
ok(dt_cancel < 5, f"R5: hủy thoát nhanh ({dt_cancel:.2f}s) — pool không chờ hết hàng đợi")

# ===== R3 — payload emit cách ly khỏi pipeline (deepcopy) =====
captured = []
ws.build_context = fake_bc
rows2 = az.run(items[:1], {"compare": True, "ttl_days": 0, "parallel_items": 2}, FakeAI(),
               counter={"used": 0}, on_item=lambda r: captured.append(r))
ws.build_context = orig_bc
stage1 = next((c for c in captured if "so_sanh" not in c), None)
final = rows2[0]
ok(stage1 is not None, "R3: có emit giai đoạn 1 (trước đối chiếu)")
sh_rows = stage1["ident"].get("thong_so") or []
fin_rows = (final.get("ident") or {}).get("thong_so") or []
shared = any(a is b for a in sh_rows for b in fin_rows)
ok(not shared, "R3: row dict emit cho GUI là bản deepcopy — pipeline mutate không đụng bản GUI đang đọc")

print(f"\nTOÀN BỘ {PASS} TEST PASS ✅")
