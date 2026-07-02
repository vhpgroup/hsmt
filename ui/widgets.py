# -*- coding: utf-8 -*-
from PySide6.QtWidgets import QTableWidget, QTableWidgetItem, QHeaderView
from PySide6.QtGui import QColor

ID_HEADERS = ["STT", "Tên hàng hóa", "Thông số kỹ thuật chính (theo E-HSMT)",
              "KẾT QUẢ: Model + Hãng", "Độ tin cậy", "Căn cứ nhận diện", "Nguồn tra cứu"]
CMP_HEADERS = ["STT", "Hạng mục", "Model ứng viên (Hãng)", "Đánh giá tiêu chí", "Kết luận", "Rủi ro khóa hãng"]
COLORS = {"Cao": "#e2f3e6", "Trung bình": "#fdf3d8", "Thấp": "#fde8e8",
          "CAO": "#fde8e8", "TRUNG BÌNH": "#fdf3d8", "THẤP": "#e2f3e6"}


def make_table(headers):
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
    t.horizontalHeader().setStretchLastSection(True)
    t.setWordWrap(True)
    return t


def _item(text, bg=None):
    it = QTableWidgetItem(str(text or ""))
    if bg:
        it.setBackground(QColor(bg))
    return it


def fill_identify(t, results):
    t.setRowCount(0)
    for r in results:
        d = r.get("ident", {})
        row = t.rowCount(); t.insertRow(row)
        model = f"{d.get('model','')} — {d.get('hang','')}".strip(" —")
        if d.get("goi_y_hang_pho_thong"):
            model += f" (gợi ý: {d['goi_y_hang_pho_thong']})"
        vals = [r["stt"], r["ten"], r["thongso"][:300], model, d.get("tin_cay", ""),
                d.get("can_cu", ""), (r.get("so_sanh") or {}).get("nhan_xet", "")[:150]]
        for c, v in enumerate(vals):
            t.setItem(row, c, _item(v, COLORS.get(d.get("tin_cay")) if c == 4 else None))
    t.resizeRowsToContents()


def fill_compare(t, results):
    t.setRowCount(0)
    for r in results:
        ss = r.get("so_sanh")
        if not ss:
            continue
        for u in ss.get("ung_vien", []):
            row = t.rowCount(); t.insertRow(row)
            vals = [r["stt"], r["ten"], f"{u.get('model','')} ({u.get('hang','')})",
                    " ".join(u.get("marks", [])), u.get("ket_luan", ""), r.get("risk", "")]
            for c, v in enumerate(vals):
                t.setItem(row, c, _item(v, COLORS.get(r.get("risk")) if c == 5 else None))
    t.resizeRowsToContents()
