# -*- coding: utf-8 -*-
"""Gọi AI qua endpoint OpenAI-compatible (Gemini mặc định). Ép JSON, retry/backoff."""
import json, re, time, requests

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

ID_PROMPT = """Bạn là chuyên gia phân tích hồ sơ mời thầu thiết bị CNTT/điện tại Việt Nam.
Với MỖI hạng mục dưới đây, nhận diện thông số được viết theo sản phẩm thật nào.
Trả về DUY NHẤT một mảng JSON, mỗi phần tử:
{"stt":"...","model":"tên model cụ thể hoặc 'Hàng phổ thông'","hang":"hãng","tin_cay":"Cao|Trung bình|Thấp",
"can_cu":"1-2 câu vì sao (dấu hiệu thông số nào)","khoa_hang":true/false,"goi_y_hang_pho_thong":"nếu là hàng phổ thông, gợi ý 3-4 hãng VN",
"thong_so":[{"ten":"tên tiêu chí ngắn","gia_tri":"giá trị yêu cầu (giữ nguyên con số)"}],
"tu_khoa_tim":"chuỗi tìm Google tối ưu: loại thiết bị + 2-3 thông số đặc trưng nhất"}
HẠNG MỤC:
"""

CMP_PROMPT = """NHIỆM VỤ: đối chiếu TỪNG DÒNG thông số yêu cầu (JSON chuẩn hóa ở trên) với các sản phẩm xuất hiện
trong NGỮ CẢNH WEB (kết quả tìm theo thông số + nội dung datasheet/trang hãng đã tải). Chọn tối đa 3 model
(ưu tiên hãng KHÁC hãng tham chiếu, bán tại Việt Nam) và KẾT LUẬN model nào ĐẠT 100% — mọi dòng "✔ Đạt"/"✔ Vượt".
CHỈ dùng giá trị có trong ngữ cảnh/datasheet; thiếu dữ liệu thì ghi "~ Chưa xác minh", TUYỆT ĐỐI không bịa.
Nếu không model nào đạt 100%, trả model gần nhất và đánh dấu "✘ Không đạt" đúng dòng thiếu.
Trả về DUY NHẤT JSON:
{"ung_vien":[{"model":"","hang":"","dat_100":true,"bang":[{"yeu_cau":"1 dòng thông số","gia_tri":"giá trị thực tế của model (theo nguồn)","danh_gia":"✔ Đạt|✔ Vượt|✘ Không đạt|~ Chưa xác minh"}],"nguon":"URL datasheet/trang hãng"}],"nhan_xet":"kết luận model nào đạt 100%, dòng nào là điểm khóa"}
"""

DUTY_PROMPT = """Phân tích SÂU các NGHĨA VỤ NHÀ THẦU trong văn bản hồ sơ mời thầu (phần ngoài bảng thông số).
Gộp thành 6-9 nhóm (tài liệu chứng minh, CO/CQ & giao nhận, kiểm định, bảo hành & hậu mãi, lắp đặt chạy thử,
an toàn thi công & hoàn trả mặt bằng, an toàn thông tin, sở hữu trí tuệ...). GIỮ NGUYÊN các con số quan trọng
(48 giờ, cấp độ 2, mới 100%...). Trả về DUY NHẤT JSON:
[{"nhom":"tên nhóm","yeu_cau":["từng yêu cầu cụ thể trong hồ sơ"],
"tai_lieu_can_nop":["tài liệu/chứng từ nhà thầu phải chuẩn bị/nộp"],
"rui_ro_bi_loai":"điểm nào làm sai có thể bị loại E-HSDT hoặc từ chối nhận hàng",
"checklist":["việc cần làm trước khi nộp thầu"]}]
VĂN BẢN:
"""

PROJ_PROMPT = """Trích THÔNG TIN DỰ ÁN/GÓI THẦU từ văn bản hồ sơ. Trả về DUY NHẤT JSON:
{"chu_dau_tu":"","dia_chi":"","ten_goi_thau":"","nguon_von":"","phuong_thuc":"","loai_hop_dong":"",
"thoi_gian_thuc_hien":"","dia_diem":"","khac":["thông tin đáng chú ý khác (bảo đảm dự thầu, số hạng mục...)"]}
VĂN BẢN:
"""


class AIEngine:
    def __init__(self, cfg):
        self.model = cfg.get("model") or DEFAULT_MODEL
        self.base = resolve_base_url(self.model, cfg.get("base_url"))
        self.key = cfg.get("api_key", "")
        self.usage = {"in": 0, "out": 0}

    def chat(self, prompt, retries=5):
        body = {"model": self.model, "temperature": 0.2,
                "messages": [{"role": "user", "content": prompt}]}
        last = ""
        for i in range(retries):
            try:
                r = requests.post(f"{self.base}/chat/completions", timeout=120,
                                  headers={"Authorization": f"Bearer {self.key}"}, json=body)
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
                    # Lỗi cấu hình (key sai/model sai/URL sai) — báo NGAY, không retry vô ích
                    raise RuntimeError(f"Lỗi API {r.status_code}: {r.text[:300]}\n"
                                       f"→ Đang gọi model '{self.model}' tại '{self.base}'. "
                                       "Kiểm tra API key / tên model / Base URL trong ⚙️ Cài đặt")
                d = r.json()
                u = d.get("usage", {})
                self.usage["in"] += u.get("prompt_tokens", 0)
                self.usage["out"] += u.get("completion_tokens", 0)
                return d["choices"][0]["message"]["content"]
            except requests.RequestException as e:
                last = f"{type(e).__name__}: {str(e)[:200]}"
                if i < retries - 1:
                    time.sleep(10 * (i + 1))
        raise RuntimeError(f"AI không phản hồi sau {retries} lần thử. Lỗi cuối: {last or 'không rõ'}\n"
                           "→ Thường do: hết hạn mức free trong ngày (chờ/đổi model gemini-2.0-flash), mạng chặn googleapis.com, hoặc key chưa kích hoạt")

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

    def identify_batch(self, items):
        block = "\n".join(f"- STT {it['stt']} | {it['ten']} | {it['thongso'][:1200]}" for it in items)
        return self.parse_json(self.chat(ID_PROMPT + block))

    def compare(self, item, ident, search_ctx=""):
        specs = ident.get("thong_so") or []
        spec_block = json.dumps(specs, ensure_ascii=False) if specs else item["thongso"][:1500]
        p = (f"Hạng mục: {item['ten']}\n"
             f"THÔNG SỐ YÊU CẦU (JSON chuẩn hóa): {spec_block}\n"
             f"Model tham chiếu đã nhận diện: {ident.get('model')} ({ident.get('hang')})\n"
             f"NGỮ CẢNH WEB (tìm theo thông số + datasheet):\n{search_ctx[:9000]}\n" + CMP_PROMPT)
        return self.parse_json(self.chat(p))

    def duties(self, text):
        return self.parse_json(self.chat(DUTY_PROMPT + text[:15000]))

    def project_info(self, text):
        return self.parse_json(self.chat(PROJ_PROMPT + text[:8000]))
