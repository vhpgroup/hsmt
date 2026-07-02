# -*- coding: utf-8 -*-
import re

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableWidget, QTableWidgetItem

ID_HEADERS = [
    "STT",
    "Tên hàng hóa",
    "Thông số kỹ thuật chính (theo E-HSMT)",
    "KẾT QUẢ: Model + Hãng",
    "Độ tin cậy",
    "Căn cứ / JSON thông số",
    "Nguồn tra cứu",
]
CMP_HEADERS = [
    "STT",
    "Hạng mục",
    "Model ứng viên (Hãng)",
    "Yêu cầu HSMT",
    "Thông số HSMT",
    "Giá trị của model",
    "Đánh giá",
    "Đạt 100%?",
    "Nguồn",
]

ID_WIDTHS = [56, 180, 520, 260, 110, 430, 420]
CMP_WIDTHS = [56, 180, 260, 220, 240, 260, 120, 110, 420]


def make_table(headers):
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.setWordWrap(True)
    t.setAlternatingRowColors(False)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
    t.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
    t.verticalHeader().setVisible(False)

    header = t.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.Interactive)
    header.setStretchLastSection(False)
    header.setMinimumSectionSize(56)
    header.setDefaultAlignment(Qt.AlignCenter)

    widths = ID_WIDTHS if len(headers) == len(ID_HEADERS) else CMP_WIDTHS
    for idx, width in enumerate(widths):
        t.setColumnWidth(idx, width)

    t.setStyleSheet("""
        QTableWidget {
            background-color: #2b2b2b;
            alternate-background-color: #2b2b2b;
            color: #ffffff;
            gridline-color: #1f1f1f;
        }
        QTableWidget::item:selected {
            background-color: #3a3a3a;
            color: #ffffff;
        }
        QHeaderView::section {
            background-color: #3a3a3a;
            color: #ffffff;
            padding: 4px 6px;
        }
    """)
    return t


def _item(text, bg=None):
    it = QTableWidgetItem(str(text or ""))
    it.setTextAlignment(Qt.AlignLeft | Qt.AlignTop)
    it.setToolTip(str(text or ""))
    if bg:
        it.setBackground(QColor(bg))
        it.setForeground(QColor("#1f2933"))
    return it


def _clean_lines(text):
    text = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace(" .", "\n.").replace(". ", "\n")
    text = text.replace("•", "\n").replace("·", "\n")
    text = text.replace(" - ", "\n").replace("; ", "\n")
    text = re.sub(r"\s+(?=\d+\/\s*)", "\n", text)
    text = re.sub(r"\s+(?=[A-ZÀ-ỸĐ][^:\n]{2,45}:)", "\n", text)
    lines = []
    for raw in text.split("\n"):
        line = raw.strip(" \t-•")
        if line:
            lines.append(line)
    return lines


def _original_text(text):
    return str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()


def _spec_summary(spec):
    rows = spec.get("thong_so") or []
    lines = []
    for s in rows:
        raw = s.get("nguyen_van")
        if raw:
            lines.append(f"• {raw}")
        else:
            lines.append(f"• {s.get('ten', '')}: {s.get('gia_tri', '')}")
    return "\n".join(lines)


def _best_model(row):
    candidates = (row.get("so_sanh") or {}).get("ung_vien", [])
    if not candidates:
        if row.get("so_sanh"):
            return "Không tìm thấy model đạt 100%"
        return "Đã chuẩn hóa thông số, chờ Serper + AI đối chiếu"
    best = candidates[0]
    return f"{best.get('model', '')} - {best.get('hang', '')} (ĐẠT 100%)".strip()


def fill_identify(t, results):
    t.setRowCount(0)
    for r in results:
        d = r.get("ident", {})
        row = t.rowCount()
        t.insertRow(row)
        uvs = (r.get("so_sanh") or {}).get("ung_vien", [])
        srcs = "; ".join(dict.fromkeys(u.get("nguon", "") for u in uvs if u.get("nguon")))[:250]
        vals = [
            r["stt"],
            r["ten"],
            _original_text(r["thongso"]),
            _best_model(r),
            d.get("tin_cay", ""),
            d.get("can_cu", "") + ("\n" + _spec_summary(d) if _spec_summary(d) else ""),
            srcs or (r.get("so_sanh") or {}).get("nhan_xet", "")[:250],
        ]
        for c, v in enumerate(vals):
            t.setItem(row, c, _item(v))
    t.resizeRowsToContents()


def fill_compare(t, results):
    t.setRowCount(0)
    for r in results:
        ss = r.get("so_sanh")
        if not ss:
            continue
        for u in ss.get("ung_vien", []):
            if not u.get("dat_100"):
                continue
            for b in u.get("bang", []):
                row = t.rowCount()
                t.insertRow(row)
                vals = [
                    r["stt"],
                    r["ten"],
                    f"{u.get('model', '')} ({u.get('hang', '')})",
                    b.get("yeu_cau", ""),
                    b.get("thong_so_hsmt", ""),
                    b.get("gia_tri", ""),
                    b.get("danh_gia", ""),
                    "ĐẠT 100%",
                    u.get("nguon", ""),
                ]
                for c, v in enumerate(vals):
                    t.setItem(row, c, _item(v))
    t.resizeRowsToContents()
