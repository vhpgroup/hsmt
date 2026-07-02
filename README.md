# 🔍 HSMT — Trợ Lý Phân Tích Hồ Sơ Mời Thầu

App desktop Windows: import hồ sơ (.docx/.pdf) → AI nhận diện **Hãng/Model** từng hạng mục theo thông số kỹ thuật → tra cứu web tìm **sản phẩm tương đương** → phân tích **nghĩa vụ nhà thầu** → xuất báo cáo **Word / PDF / Excel**.

## Chạy bằng Python (khuyến nghị khi dev)
```bash
pip install -r requirements.txt
python main.py
```
Yêu cầu Python 3.10+ (tick "Add to PATH" khi cài).

## Cấu hình (⚙️ Cài đặt trong app)
| Mục | Giá trị mặc định |
|---|---|
| Base URL | `https://generativelanguage.googleapis.com/v1beta/openai` (Gemini OpenAI-compatible) |
| Model | `gemini-2.5-flash` (bậc free — lấy key tại **Google AI Studio**) |
| Web search | **Serper.dev** (2.500 lượt đầu miễn phí) hoặc Tavily / tắt |

Key lưu cục bộ tại `%APPDATA%\hsmt\config.json`. Cache kết quả AI + search theo **hash nội dung thông số** (SQLite) — chạy lại cùng hồ sơ **không tốn lại credit**; chỉnh TTL/xóa cache trong Cài đặt.

## Build file .exe
- **Tự build:** chạy `build.bat` → `dist\HSMT-Analyzer.exe`
- **GitHub Actions:** mỗi lần push lên `main`, workflow tự build — tải file exe ở tab **Actions → artifact `HSMT-Analyzer-win64`**

## Cấu trúc
```
main.py            # Khởi động app (PySide6, 2 tab)
core/extractor.py  # Đọc DOCX/PDF, bóc bảng
core/preprocess.py # Làm sạch, gộp dòng, chuẩn hóa + khóa cache
core/ai_engine.py  # Gọi AI OpenAI-compatible, ép JSON, retry/backoff
core/search.py     # Serper/Tavily + tải trang top kết quả
core/analyzer.py   # Điều phối: cache → nhận diện → so sánh → rủi ro khóa hãng
core/cache.py      # SQLite cache + config + project JSON
core/exporter.py   # Xuất Word/PDF/Excel + HTML xem trước
ui/                # main_window, settings_dialog, widgets
```

## Luồng chạy
Import → trích văn bản + bảng → chuẩn hóa hạng mục → AI nhận diện theo lô (retry khi 429) → Serper tra model gốc + tương đương (kèm nội dung trang) → bảng kết quả 7 cột + bảng so sánh ✓/✗/~ → xem trước → xuất báo cáo.

> ⚠️ Kết quả AI/web chỉ mang tính tham khảo — kiểm chứng datasheet chính hãng trước khi chào thầu.
