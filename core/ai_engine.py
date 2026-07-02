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


SPEC_PROMPT = """Bạn là chuyên gia phân tích hồ sơ mời thầu thiết bị CNTT/điện tại Việt Nam.
Với MỖI hạng mục dưới đây, CHỈ trích và chuẩn hóa thông số kỹ thuật HSMT thành JSON.
Không đoán model/hãng ở bước này. Không kết luận khóa hãng ở bước này.
Bỏ qua mọi yêu cầu hệ điều hành Windows 11 Pro / Windows 11 Professional / Win 11 Pro vì nhà bán hàng thường không ghi thông số này trong datasheet sản phẩm.
Trả về DUY NHẤT một mảng JSON, mỗi phần tử:
{"stt":"...","loai_thiet_bi":"loại thiết bị ngắn gọn","tin_cay":"Cao|Trung bình|Thấp",
"can_cu":"1-2 câu mô tả các dấu hiệu kỹ thuật chính đã trích",
"thong_so":[{"ten":"tên tiêu chí ngắn","gia_tri":"giá trị yêu cầu (giữ nguyên con số/đơn vị)"}],
"tu_khoa_tim":"chuỗi tìm Google tối ưu: loại thiết bị + 3-5 thông số đặc trưng nhất, không kèm Windows 11 Pro, không kèm model/hãng nếu HSMT không nêu rõ"}
HẠNG MỤC:
"""

CMP_PROMPT = """NHIỆM VỤ: Dựa trên JSON thông số HSMT và NGỮ CẢNH WEB, tìm SẢN PHẨM ĐẠT 100% rồi đối chiếu TỪNG DÒNG thông số.
Mục tiêu bắt buộc: chỉ chấp nhận model có TẤT CẢ thông số bằng hoặc vượt yêu cầu HSMT. Không thông số nào được kém hơn. Tổng thể phải đạt 100%.
Bỏ qua Windows 11 Pro / Windows 11 Professional / Win 11 Pro khi đối chiếu.
QUY TẮC NGUỒN BẮT BUỘC:
1. Chỉ kết luận model sau khi đã đọc nguồn trong ngữ cảnh web; không dùng suy đoán từ bước trích thông số.
2. Ghi model ĐÚNG PHIÊN BẢN/SUFFIX như trong nguồn (vd "VA2432-H-2" khác "VA2432-h").
3. "nguon" phải là URL CỤ THỂ xuất hiện trong ngữ cảnh, ưu tiên PDF datasheet/trang CHÍNH HÃNG; cấm ghi domain chung chung.
4. Một dòng chỉ được "Đạt" khi giá trị bằng yêu cầu, "Vượt" khi giá trị tốt hơn yêu cầu. Nếu kém hơn thì loại model.
5. Số liệu chỉ có ở trang tổng hợp/đại lý -> không đủ điều kiện đạt 100%, loại model khỏi "ung_vien".
6. Thiếu dữ liệu hoặc chưa xác minh bằng nguồn chính hãng -> không đủ điều kiện đạt 100%, loại model khỏi "ung_vien".
7. "dat_100": true CHỈ khi 100% dòng là "Đạt" hoặc "Vượt" với nguồn chính hãng của đúng model/phiên bản.
8. Tuyệt đối KHÔNG trả model gần nhất, KHÔNG trả model chưa đạt, KHÔNG trả model có dòng "Không đạt" hoặc "~ Chưa xác minh".
Hãy tìm tối đa 3 model ĐẠT 100%. Nếu không tìm thấy model nào đạt 100%, trả "ung_vien": [] và ghi rõ lý do trong "nhan_xet".
Trả về DUY NHẤT JSON:
{"ung_vien":[{"model":"đúng suffix/phiên bản","hang":"","dat_100":true,"bang":[{"yeu_cau":"tên tiêu chí","thong_so_hsmt":"giá trị yêu cầu HSMT","gia_tri":"giá trị thực tế của model (theo nguồn)","danh_gia":"Đạt|Vượt"}],"nguon":"URL cụ thể"}],"nhan_xet":"kết luận model nào đạt 100%; nếu không có thì nói rõ chưa tìm thấy model đạt 100% với nguồn chính hãng"}
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
        self.usage = {"in": 0, "out": 0}

    def chat(self, prompt, retries=5):
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
                    timeout=120,
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
        block = "\n".join(f"- STT {it['stt']} | {it['ten']} | {it['thongso'][:1200]}" for it in items)
        return self.parse_json(self.chat(SPEC_PROMPT + block))

    def identify_batch(self, items):
        return self.extract_specs_batch(items)

    def compare(self, item, spec, search_ctx=""):
        specs = spec.get("thong_so") or []
        spec_block = json.dumps(specs, ensure_ascii=False) if specs else item["thongso"][:1500]
        p = (
            f"Hạng mục: {item['ten']}\n"
            f"Loại thiết bị: {spec.get('loai_thiet_bi', '')}\n"
            f"THÔNG SỐ YÊU CẦU (JSON chuẩn hóa, đã bỏ Windows 11 Pro nếu có): {spec_block}\n"
            f"NGỮ CẢNH WEB (Serper tìm theo thông số + datasheet/link hãng):\n{search_ctx[:9000]}\n"
            + CMP_PROMPT
        )
        return self.parse_json(self.chat(p))

    def duties(self, text):
        return self.parse_json(self.chat(DUTY_PROMPT + text[:15000]))

    def project_info(self, text):
        return self.parse_json(self.chat(PROJ_PROMPT + text[:8000]))
