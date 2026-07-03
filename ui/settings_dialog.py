# -*- coding: utf-8 -*-
from PySide6.QtWidgets import (QDialog, QFormLayout, QLineEdit, QComboBox, QSpinBox,
                               QDialogButtonBox, QCheckBox, QPushButton, QHBoxLayout, QWidget)
from core import cache
from core.ai_engine import MODEL_BASES, resolve_base_url


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("⚙️ Cài đặt")
        self.setMinimumWidth(430)
        cfg = cache.load_config()
        f = QFormLayout(self)
        self.base = QLineEdit(cfg.get("base_url", "https://generativelanguage.googleapis.com/v1beta/openai"))
        self.model = QComboBox()
        self.model.addItems(["gemini-2.5-flash", "gpt-4.1-mini"])
        current_model = cfg.get("model", "gemini-2.5-flash")
        if current_model not in MODEL_BASES:
            self.model.addItem(current_model)
        self.model.setCurrentText(current_model)
        self.model.currentTextChanged.connect(self.on_model_changed)
        self.base.setText(resolve_base_url(current_model, self.base.text()))
        self.key = QLineEdit(cfg.get("api_key", "")); self.key.setEchoMode(QLineEdit.Password)
        self.sprov = QComboBox(); self.sprov.addItems(["serper", "exa", "tavily", "off"])
        self.sprov.setCurrentText(cfg.get("search_provider", "serper"))
        self.skey = QLineEdit(cfg.get("search_key", "")); self.skey.setEchoMode(QLineEdit.Password)
        self.cmp = QCheckBox("Tìm sản phẩm tương đương — tra web MỌI hạng mục (yêu cầu đạt 100%)")
        self.cmp.setChecked(cfg.get("compare", True))
        self.fp = QCheckBox("Tự tải trang top kết quả cho AI đọc sâu"); self.fp.setChecked(cfg.get("fetch_pages", True))
        self.ttl = QSpinBox(); self.ttl.setRange(1, 365); self.ttl.setValue(int(cfg.get("ttl_days", 30)))
        self.rpq = QSpinBox(); self.rpq.setRange(3, 15); self.rpq.setValue(int(cfg.get("results_per_query", 8)))
        self.mds = QSpinBox(); self.mds.setRange(1, 10); self.mds.setValue(int(cfg.get("max_deep_sources", 5)))
        f.addRow("Base URL (OpenAI-compatible):", self.base)
        f.addRow("Model:", self.model)
        f.addRow("API Key (AI):", self.key)
        f.addRow("Web search:", self.sprov)
        f.addRow("Search API Key:", self.skey)
        f.addRow(self.cmp); f.addRow(self.fp)
        f.addRow("Số kết quả/truy vấn (độ sâu):", self.rpq)
        f.addRow("Số nguồn đọc sâu tối đa:", self.mds)
        f.addRow("Hạn cache (ngày):", self.ttl)
        btn_clear = QPushButton("🗑 Xóa cache")
        btn_clear.clicked.connect(lambda: (cache.clear(), btn_clear.setText("Đã xóa ✓")))
        w = QWidget(); h = QHBoxLayout(w); h.setContentsMargins(0, 0, 0, 0); h.addWidget(btn_clear); h.addStretch()
        f.addRow(w)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.save); bb.rejected.connect(self.reject)
        f.addRow(bb)

    def save(self):
        model = self.model.currentText().strip()
        cache.save_config({"base_url": resolve_base_url(model, self.base.text()), "model": model,
                           "api_key": self.key.text().strip(), "search_provider": self.sprov.currentText(),
                           "search_key": self.skey.text().strip(), "compare": self.cmp.isChecked(),
                           "fetch_pages": self.fp.isChecked(), "ttl_days": self.ttl.value(),
                           "results_per_query": self.rpq.value(), "max_deep_sources": self.mds.value()})
        self.accept()

    def on_model_changed(self, model):
        self.base.setText(resolve_base_url(model, self.base.text()))
