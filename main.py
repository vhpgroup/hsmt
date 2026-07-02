# -*- coding: utf-8 -*-
"""Trợ Lý Phân Tích Hồ Sơ Thầu — import hồ sơ, AI nhận diện hãng/model, so sánh tương đương, xuất báo cáo."""
import sys
from PySide6.QtWidgets import QApplication
from ui.main_window import MainWindow

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    w = MainWindow()
    w.show()
    sys.exit(app.exec())
