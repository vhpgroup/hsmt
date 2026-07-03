# -*- coding: utf-8 -*-
"""Call AI through an OpenAI-compatible endpoint. Extract specs first, then verify only 100%-passing models."""
import json
import re
import time

import requests

DEFAULT_BASE = "https://generativelanguage.googleapis.com/v1beta/openai"
DEFAULT_MODEL = "gemini-2.5-flash"
MODEL_BASES = {
    "gemini-2.5-flash": "https://generativelanguage.googleapis.com/v1beta/openai",
    "gpt-4.1-mini": "https://api.openai.com/v1",
}


def resolve_base_url(model, base_url):
    base = (base_url or "").strip().rstrip("/")
    expected = MODEL_BASES.get(model)
    known_bases = {value.rstrip("/") for value in MODEL_BASES.values()}
    if expected and (not base or base in known_bases):
        return expected.rstrip("/")
    return (base or DEFAULT_BASE).rstrip("/")


SPEC_PROMPT = """Bạn là một chuyên gia bóc tách hồ sơ mời thầu (HSMT) xây dựng/CNTT tại Việt Nam.
Nhiệm vụ: đọc ĐÚNG NGUYÊN VĂN từng dòng/mục trong bảng "Yêu cầu kỹ thuật cụ thể" của HSMT và chuyển thành JSON có cấu trúc để dùng cho việc tìm kiếm, đối chiếu thiết bị/sản phẩm đáp ứng.

QUY TẮC BẮT BUỘC:
1. TUYỆT ĐỐI KHÔNG suy diễn, làm tròn, đổi đơn vị, hoặc tự thêm thông số không có trong văn bản gốc. Nếu không chắc một cụm từ có phải thông số kỹ thuật không, vẫn trích ra nhưng đánh dấu "muc_do": "khong_ro".
2. PHÂN LOẠI mỗi thông số vào đúng "loai_du_lieu":
   - "thong_so_ky_thuat": chỉ số đo lường được, có thể tra trong datasheet nhà sản xuất.
   - "tieu_chuan_chung_chi": tiêu chuẩn/chứng chỉ như TCVN, ISO, CE, FCC.
   - "vat_tu_thi_cong": vật tư phụ, nhân công, lắp đặt/thi công đi kèm; KHÔNG dùng để tìm kiếm sản phẩm.
   - "yeu_cau_chung": yêu cầu không định lượng được.
3. MỘT DÒNG STT có thể chứa NHIỀU THIẾT BỊ CON. Phải tách riêng từng thiết bị con vào "hang_muc_con". Nhận diện ranh giới qua "1/", "2/", tiêu đề in hoa, hoặc dấu "*" đứng đầu dòng mô tả tên thiết bị.
4. GIỮ NGUYÊN VĂN gốc của từng thông số vào "trich_dan_nguon"; không diễn giải lại.
5. TÁCH toán tử so sánh và giá trị số nếu có thể:
   - "≥", "không nhỏ hơn", "tối thiểu" -> ">="
   - "≤", "không lớn hơn", "tối đa" -> "<="
   - "±", "khoảng", hai giá trị nối bằng "~" hoặc "-" -> "khoang"
   - một giá trị cố định -> "="
   - không xác định -> "khac"
   Nếu có nhiều giá trị số, điền "gia_tri_so_min" và "gia_tri_so_max"; nếu chỉ có một giá trị, điền "gia_tri_so".
6. Nếu một dòng chỉ là tiêu đề nhóm không mang giá trị kỹ thuật, KHÔNG tạo entry thông số; chỉ dùng làm ngữ cảnh "nhom_thong_so" cho dòng con.
7. Bỏ qua Windows 11 Pro / Windows 11 Professional / Win 11 Pro.
8. Trả về ĐÚNG MỘT phần tử JSON cho MỖI STT đưa vào, giữ đúng STT gốc.
9. CHỈ xuất JSON hợp lệ. Không markdown, không giải thích, không dấu ``` .

SCHEMA ĐẦU RA là MỘT MẢNG JSON:
QUY TAC THEM VE PHU KIEN KHONG CO THONG SO:
- Bat buoc giu moi thiet bi con da liet ke trong hang_muc_con, ke ca khi khong co dong thong so ben duoi.
- Voi phu kien nhu "Rail Kit - Thanh truot gan tu Rack cho UPS": dat thong_so=[], trang_thai_thong_so="khong_co_thong_so", loai_hang_muc="phu_kien_di_kem", phu_thuoc_hang_muc_con la thiet bi chinh no di kem.
- Voi thiet bi con co thong so binh thuong: trang_thai_thong_so="co_thong_so", loai_hang_muc="doc_lap", phu_thuoc_hang_muc_con=null.

[{
  "stt": "số STT trong bảng",
  "ten_hang_hoa_muc": "tên ở cột Tên hàng hóa",
  "tin_cay": "Cao|Trung bình|Thấp",
  "can_cu": "1-2 câu mô tả dấu hiệu kỹ thuật chính đã trích",
  "hang_muc_con": [{
    "ten_hang_muc_con": "tên thiết bị con, hoặc trùng ten_hang_hoa_muc nếu chỉ có 1 thiết bị",
    "trang_thai_thong_so": "co_thong_so|khong_co_thong_so",
    "loai_hang_muc": "doc_lap|phu_kien_di_kem",
    "phu_thuoc_hang_muc_con": "ten thiet bi chinh neu la phu_kien_di_kem, nguoc lai null",
    "thong_so": [{
      "nhom_thong_so": "tên nhóm cha nếu có, hoặc null",
      "ten_thong_so": "tên thông số",
      "gia_tri_yeu_cau": "giá trị viết nguyên văn",
      "don_vi": "đơn vị nếu tách được, hoặc null",
      "toan_tu_so_sanh": ">=|<=|=|khoang|khac",
      "gia_tri_so": null,
      "gia_tri_so_min": null,
      "gia_tri_so_max": null,
      "loai_du_lieu": "thong_so_ky_thuat|tieu_chuan_chung_chi|vat_tu_thi_cong|yeu_cau_chung",
      "muc_do": "bat_buoc|khong_ro",
      "trich_dan_nguon": "nguyên văn dòng gốc"
    }]
  }]
}]

HẠNG MỤC:
"""

CMP_PROMPT = """NHIỆM VỤ: Dựa trên JSON thông số HSMT và NGỮ CẢNH WEB, tìm SẢN PHẨM ĐẠT 100% rồi đối chiếu TỪNG DÒNG thông số.
Mục tiêu bắt buộc: chỉ chấp nhận model có TẤT CẢ thông số bằng hoặc vượt yêu cầu HSMT. Không thông số nào được kém hơn. Tổng thể phải đạt 100%.
Bỏ qua Windows 11 Pro / Windows 11 Professional / Win 11 Pro khi đối chiếu.
QUY TẮC NGUỒN BẮT BUỘC:
1. Chỉ kết luận model sau khi đã đọc nguồn trong ngữ cảnh web; không dùng suy đoán từ bước trích thông số.
2. Ghi model ĐÚNG PHIÊN BẢN/SUFFIX như trong nguồn (vd "VA2432-H-2" khác "VA2432-h").
3. "nguon" phải là URL CỤ THỂ xuất hiện trong ngữ cảnh; cấm ghi domain chung chung. ƯU TIÊN PDF datasheet/trang
   CHÍNH HÃNG, nhưng CHẤP NHẬN mọi nguồn có trong ngữ cảnh (đại lý/trang tổng hợp) — ghi rõ "nguon_loai".
4. Một dòng chỉ được "Đạt" khi giá trị bằng yêu cầu, "Vượt" khi giá trị tốt hơn yêu cầu. Nếu kém hơn thì loại model.
4c. CHIỀU TOÁN TỬ: "≥ X" nghĩa là model phải LỚN HƠN HOẶC BẰNG X mới đạt; "≤ X" phải NHỎ HƠN HOẶC BẰNG X.
    Đọc đúng dấu trong "thong_so_hsmt", KHÔNG đảo chiều. Vd yêu cầu "≥3m" thì model 3m/4m/5m = Đạt, 2m = Không đạt.
4a. BIỂU THỨC TƯƠNG ĐƯƠNG (coi là BẰNG, không chấm sai): "10KVA/10KW" tức PF=1.0 (kW/kVA); nits = cd/m²;
    1000BASE-T = 1GbE = 10/100/1000; "≥250" thỏa bởi 250 hoặc 300; đổi đơn vị (mm↔cm, GHz↔MHz, Gbps↔Mbps);
    số ắc quy × 12V ≈ điện áp DC (20×12V=240V=±120Vdc); từ đồng nghĩa (RJ45=8P8C, Cổng quang=SFP). Suy luận đơn vị/định nghĩa trước khi chấm.
4b. "VƯỢT" CHỈ hợp lệ khi CÙNG LOẠI/CHUẨN. Số lớn hơn nhưng KHÁC loại KHÔNG phải "Vượt": cổng SFP+ 10G KHÔNG thay được
    cổng SFP 1G/2.5G (khác module); RAM DDR5 khác DDR4 nếu HSMT chỉ định thế hệ; chuẩn nguồn/giao tiếp khác loại → ghi "Không đạt" (loại model), không tự cho là vượt.
5. Giá trị lấy từ BẤT KỲ nguồn nào trong ngữ cảnh đều hợp lệ (miễn có trích dẫn khớp) — nguồn chính hãng xếp trước.
6. Một dòng KHÔNG nguồn nào trong ngữ cảnh có dữ liệu -> loại model khỏi "ung_vien" (không được bịa).
7. "dat_100": true khi 100% dòng là "Đạt"/"Vượt" với trích dẫn khớp nguồn trong ngữ cảnh (bất kỳ loại nguồn nào).
8. Tuyệt đối KHÔNG trả model gần nhất, KHÔNG trả model chưa đạt, KHÔNG trả model có dòng "Không đạt" hoặc "~ Chưa xác minh".
9. BẰNG CHỨNG BẮT BUỘC: mỗi dòng trong "bang" phải kèm "trich_dan" — đoạn NGUYÊN VĂN 5-25 từ COPY ĐÚNG từ ngữ cảnh
   (lấy được từ cả khối [NGUON n] lẫn [KQ TIM]) có chứa giá trị đó. CẤM viết lại/dịch/rút gọn — copy y nguyên ký tự.
   Hệ thống sẽ TỰ ĐỘNG dò lại từng trích dẫn trong ngữ cảnh: trích dẫn không tìm thấy = model bị loại.
   Không tìm được đoạn nguyên văn chứa giá trị → thông số đó chưa có bằng chứng → loại model.
Hãy tìm tối đa 3 model ĐẠT 100%. Nếu không tìm thấy model nào đạt 100%, trả "ung_vien": [] và ghi rõ lý do trong "nhan_xet".
Trả về DUY NHẤT JSON:
{"ung_vien":[{"model":"đúng suffix/phiên bản","hang":"","dat_100":true,"nguon_loai":"Chính hãng|Đại lý/tổng hợp","bang":[{"yeu_cau":"tên tiêu chí","thong_so_hsmt":"giá trị yêu cầu HSMT","gia_tri":"giá trị thực tế của model (theo nguồn)","danh_gia":"Đạt|Vượt","trich_dan":"đoạn nguyên văn copy từ ngữ cảnh"}],"nguon":"URL cụ thể"}],"nhan_xet":"kết luận model nào đạt 100%; nếu không có thì nói rõ lý do"}
"""

DUTY_PROMPT = """Phân tích sâu các NGHĨA VỤ NHÀ THẦU trong văn bản hồ sơ mời thầu (phần ngoài bảng thông số).
Gộp thành 6-9 nhóm. Giữ nguyên các con số quan trọng. Trả về DUY NHẤT JSON:
[{"nhom":"tên nhóm","yeu_cau":["từng yêu cầu cụ thể trong hồ sơ"],
"tai_lieu_can_nop":["tài liệu/chứng từ nhà thầu phải chuẩn bị/nộp"],
"rui_ro_bi_loai":"điểm nào làm sai có thể bị loại E-HSDT hoặc từ chối nhận hàng",
"checklist":["việc cần làm trước khi nộp thầu"]}]
VĂN BẢN:
"""

PROJ_PROMPT = """Trích THÔNG TIN DỰ ÁN/GÓI THẦU từ văn bản hồ sơ. Trả về DUY NHẤT JSON:
{"chu_dau_tu":"","dia_chi":"","ten_goi_thau":"","nguon_von":"","phuong_thuc":"","loai_hop_dong":"",
"thoi_gian_thuc_hien":"","dia_diem":"","khac":["thông tin đáng chú ý khác"]}
VĂN BẢN:
"""


class AIEngine:
    def __init__(self, cfg):
        self.model = cfg.get("model") or DEFAULT_MODEL
        self.base = resolve_base_url(self.model, cfg.get("base_url"))
        self.key = cfg.get("api_key", "")
        self.extract_timeout = int(cfg.get("extract_timeout", 90))
        self.usage = {"in": 0, "out": 0}

    def chat(self, prompt, retries=3, timeout=60):
        body = {
            "model": self.model,
            "temperature": 0.2,
            "messages": [{"role": "user", "content": prompt}],
        }
        last = ""
        for i in range(retries):
            try:
                r = requests.post(
                    f"{self.base}/chat/completions",
                    timeout=timeout,
                    headers={"Authorization": f"Bearer {self.key}"},
                    json=body,
                )
                if r.status_code == 429 or r.status_code >= 500:
                    last = f"HTTP {r.status_code}: {r.text[:200]}"
                    wait = 0
                    try:
                        wait = int(r.headers.get("Retry-After", "0"))
                    except ValueError:
                        pass
                    time.sleep(min(wait or 10 * (i + 1), 65))
                    continue
                if r.status_code >= 400:
                    raise RuntimeError(
                        f"Lỗi API {r.status_code}: {r.text[:300]}\n"
                        f"-> Đang gọi model '{self.model}' tại '{self.base}'. "
                        "Kiểm tra API key / tên model / Base URL trong Cài đặt"
                    )
                d = r.json()
                u = d.get("usage", {})
                self.usage["in"] += u.get("prompt_tokens", 0)
                self.usage["out"] += u.get("completion_tokens", 0)
                return d["choices"][0]["message"]["content"]
            except requests.ReadTimeout:
                last = f"ReadTimeout: endpoint did not return within {timeout}s"
                if i < retries - 1:
                    time.sleep(5 * (i + 1))
            except requests.RequestException as e:
                last = f"{type(e).__name__}: {str(e)[:200]}"
                if i < retries - 1:
                    time.sleep(10 * (i + 1))
        raise RuntimeError(
            f"AI không phản hồi sau {retries} lần thử. Lỗi cuối: {last or 'không rõ'}\n"
            "-> Thường do hết hạn mức, mạng chặn endpoint, hoặc key chưa kích hoạt"
        )

    @staticmethod
    def parse_json(text):
        m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
        raw = m.group(1) if m else text
        s, e = raw.find("["), raw.rfind("]") + 1
        s2, e2 = raw.find("{"), raw.rfind("}") + 1
        if 0 <= s < s2 or e2 <= 0:
            raw = raw[s:e]
        else:
            raw = raw[s2:e2]
        return json.loads(raw)

    def extract_specs_batch(self, items):
        # 3000 ký tự đủ trọn thông số mục dài nhất (báo cháy ~1.900) — không cắt mất dòng cuối
        block = "\n".join(f"- STT {it['stt']} | {it['ten']} | {it['thongso'][:3000]}" for it in items)
        raw = self.chat(SPEC_PROMPT + block, retries=2, timeout=self.extract_timeout)
        try:
            return self.parse_json(raw)
        except json.JSONDecodeError:
            fix_prompt = (
                "Sua JSON sau thanh JSON hop le. Chi tra ve JSON, khong markdown, khong giai thich. "
                "Khong them/bot du lieu, chi sua dau phay, dau ngoac, quote, escape neu can.\n"
                f"JSON_LOI:\n{raw[:12000]}"
            )
            fixed = self.chat(fix_prompt, retries=1, timeout=60)
            return self.parse_json(fixed)

    def identify_batch(self, items):
        return self.extract_specs_batch(items)

    def compare(self, item, spec, search_ctx=""):
        specs = spec.get("thong_so") or []
        spec_block = json.dumps(specs, ensure_ascii=False) if specs else item["thongso"][:1500]
        p = (
            f"Hạng mục: {item['ten']}\n"
            f"Loại thiết bị: {spec.get('loai_thiet_bi', '')}\n"
            f"THÔNG SỐ YÊU CẦU (JSON chuẩn hóa, đã bỏ Windows 11 Pro nếu có): {spec_block}\n"
            f"NGỮ CẢNH WEB (Serper tìm theo thông số + datasheet/link hãng):\n{search_ctx[:24000]}\n"
            + CMP_PROMPT
        )
        return self.parse_json(self.chat(p))

    def recheck_lines(self, item, cand, missing_rows, ctx):
        """Đối chiếu LẠI CHỈ các dòng còn thiếu bằng chứng cho MỘT model (không chạy lại toàn bộ)."""
        lines = json.dumps(
            [{"yeu_cau": r.get("yeu_cau", ""), "thong_so_hsmt": r.get("thong_so_hsmt", "")} for r in missing_rows],
            ensure_ascii=False)
        p = (
            f"Model: {cand.get('model', '')} ({cand.get('hang', '')}) — hạng mục: {item['ten']}\n"
            f"CHỈ đối chiếu lại các dòng SAU (không thêm dòng mới, không đổi model). Mỗi dòng cần giá trị thực tế của "
            f"model + đánh giá (Đạt|Vượt|Không đạt|~ Chưa xác minh) + trích dẫn NGUYÊN VĂN copy từ ngữ cảnh.\n"
            f"Áp dụng: biểu thức tương đương (10KVA/10KW=PF1.0, nits=cd/m²), đúng chiều ≥/≤, Vượt chỉ khi cùng loại.\n"
            f"DÒNG CẦN ĐỐI CHIẾU: {lines}\n"
            f"NGỮ CẢNH BỔ SUNG:\n{ctx[:14000]}\n"
            'Trả về DUY NHẤT JSON: {"bang":[{"yeu_cau":"","thong_so_hsmt":"","gia_tri":"","danh_gia":"","trich_dan":""}]}'
        )
        return self.parse_json(self.chat(p))

    def duties(self, text):
        return self.parse_json(self.chat(DUTY_PROMPT + text[:15000]))

    def project_info(self, text):
        return self.parse_json(self.chat(PROJ_PROMPT + text[:8000]))
