# -*- coding: utf-8 -*-
from PySide6.QtWidgets import QTableWidget, QTableWidgetItem, QHeaderView
from PySide6.QtGui import QColor

ID_HEADERS = ["STT", "Tên hàng hóa", "Thông số kỹ thuật chính (theo E-HSMT)",
              "KẾT QUẢ: Model + Hãng", "Độ tin cậy", "Căn cứ nhận diện", "Nguồn tra cứu"]
CMP_HEADERS = ["STT", "Hạng mục", "Model ứng viên (Hãng)", "Yêu cầu HSMT", "Giá trị của model", "Đánh giá", "Đạt 100%?", "Nguồn"]
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
        uvs = (r.get("so_sanh") or {}).get("ung_vien", [])
        srcs = "; ".join(dict.fromkeys(u.get("nguon", "") for u in uvs if u.get("nguon")))[:250]
        vals = [r["stt"], r["ten"], r["thongso"][:300], model, d.get("tin_cay", ""),
                d.get("can_cu", ""), srcs or (r.get("so_sanh") or {}).get("nhan_xet", "")[:150]]
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
            tag = "ĐẠT 100%" if u.get("dat_100") else "Chưa đạt"
            for b in u.get("bang", []):
                row = t.rowCount(); t.insertRow(row)
                dg = b.get("danh_gia", "")
                bg = "#e2f3e6" if "Đạt" in dg or "Vượt" in dg else "#fde8e8"
                vals = [r["stt"], r["ten"], f"{u.get('model','')} ({u.get('hang','')})",
                        b.get("yeu_cau", ""), b.get("gia_tri", ""), dg, tag, u.get("nguon", "")]
                for c, v in enumerate(vals):
                    t.setItem(row, c, _item(v, bg if c == 5 else ("#e2f3e6" if c == 6 and u.get("dat_100") else None)))
    t.resizeRowsToContents()
