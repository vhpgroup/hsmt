# -*- coding: utf-8 -*-
"""Gọi AI qua endpoint OpenAI-compatible (Gemini mặc định). Ép JSON, retry/backoff."""
import json, re, time, requests

DEFAULT_BASE = "https://generativelanguage.googleapis.com/v1beta/openai"
DEFAULT_MODEL = "gemini-2.5-flash"

ID_PROMPT = """Bạn là chuyên gia phân tích hồ sơ mời thầu thiết bị CNTT/điện tại Việt Nam.
Với MỖI hạng mục dưới đây, nhận diện thông số được viết theo sản phẩm thật nào.
Trả về DUY NHẤT một mảng JSON, mỗi phần tử:
{"stt":"...","model":"tên model cụ thể hoặc 'Hàng phổ thông'","hang":"hãng","tin_cay":"Cao|Trung bình|Thấp",
"can_cu":"1-2 câu vì sao (dấu hiệu thông số nào)","khoa_hang":true/false,"goi_y_hang_pho_thong":"nếu là hàng phổ thông, gợi ý 3-4 hãng VN"}
HẠNG MỤC:
"""

CMP_PROMPT = """NHIỆM VỤ: Tách thông số yêu cầu thành TỪNG DÒNG tiêu chí riêng. Tìm model của hãng KHÁC đáp ứng 100% —
nghĩa là MỌI dòng đều "✔ Đạt" hoặc "✔ Vượt" (đối chiếu datasheet trong ngữ cảnh web, không suy đoán).
Chỉ liệt kê tối đa 3 ứng viên, ưu tiên hàng bán tại Việt Nam. Nếu KHÔNG có model nào đạt 100%,
trả về model gần nhất, đánh dấu "✘ Không đạt" đúng dòng thiếu và ghi rõ trong nhan_xet.
Trả về DUY NHẤT JSON:
{"ung_vien":[{"model":"","hang":"","dat_100":true,"bang":[{"yeu_cau":"1 dòng thông số HSMT","gia_tri":"giá trị thực tế của model","danh_gia":"✔ Đạt|✔ Vượt|✘ Không đạt"}],"nguon":"URL/domain datasheet"}],"nhan_xet":"tiêu chí nào khóa hãng, ứng viên nào đạt 100%"}
"""

DUTY_PROMPT = """Phân tích các NGHĨA VỤ NHÀ THẦU trong văn bản hồ sơ mời thầu sau (ngoài bảng thông số).
Trả về DUY NHẤT JSON: [{"nhom":"tên nhóm","noi_dung":["gạch đầu dòng..."]}] — gộp thành 5-8 nhóm (tài liệu chứng minh, CO/CQ, kiểm định, bảo hành, an toàn thi công, ATTT...).
VĂN BẢN:
"""


class AIEngine:
    def __init__(self, cfg):
        self.base = (cfg.get("base_url") or DEFAULT_BASE).rstrip("/")
        self.model = cfg.get("model") or DEFAULT_MODEL
        self.key = cfg.get("api_key", "")
        self.usage = {"in": 0, "out": 0}

    def chat(self, prompt, retries=4):
        body = {"model": self.model, "temperature": 0.2,
                "messages": [{"role": "user", "content": prompt}]}
        for i in range(retries):
            try:
                r = requests.post(f"{self.base}/chat/completions", timeout=90,
                                  headers={"Authorization": f"Bearer {self.key}"}, json=body)
                if r.status_code in (429, 500, 502, 503):
                    time.sleep(6 * (i + 1)); continue
                r.raise_for_status()
                d = r.json()
                u = d.get("usage", {})
                self.usage["in"] += u.get("prompt_tokens", 0)
                self.usage["out"] += u.get("completion_tokens", 0)
                return d["choices"][0]["message"]["content"]
            except requests.RequestException:
                if i == retries - 1:
                    raise
                time.sleep(6 * (i + 1))
        raise RuntimeError("AI không phản hồi sau nhiều lần thử")

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
        p = (f"Hạng mục: {item['ten']}\nThông số yêu cầu: {item['thongso'][:1500]}\n"
             f"Model tham chiếu đã nhận diện: {ident.get('model')} ({ident.get('hang')})\n"
             f"NGỮ CẢNH TRA CỨU WEB:\n{search_ctx[:6000]}\n" + CMP_PROMPT)
        return self.parse_json(self.chat(p))

    def duties(self, text):
        return self.parse_json(self.chat(DUTY_PROMPT + text[:15000]))
