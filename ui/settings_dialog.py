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
        self.smode = QComboBox()
        self.smode.addItems(["single", "hybrid"])
        self.smode.setCurrentText(cfg.get("search_mode", "single"))
        legacy_search_key = cfg.get("search_key", "")
        self.serper_key = QLineEdit(cfg.get("serper_key", legacy_search_key if cfg.get("search_provider") == "serper" else ""))
        self.serper_key.setEchoMode(QLineEdit.Password)
        self.exa_key = QLineEdit(cfg.get("exa_key", legacy_search_key if cfg.get("search_provider") == "exa" else ""))
        self.exa_key.setEchoMode(QLineEdit.Password)
        self.tavily_key = QLineEdit(cfg.get("tavily_key", legacy_search_key if cfg.get("search_provider") == "tavily" else ""))
        self.tavily_key.setEchoMode(QLineEdit.Password)
        self.cmp = QCheckBox("Tìm sản phẩm tương đương — tra web MỌI hạng mục (yêu cầu đạt 100%)")
        self.cmp.setChecked(cfg.get("compare", True))
        self.fp = QCheckBox("Tự tải trang top kết quả cho AI đọc sâu"); self.fp.setChecked(cfg.get("fetch_pages", True))
        self.ttl = QSpinBox(); self.ttl.setRange(1, 365); self.ttl.setValue(int(cfg.get("ttl_days", 30)))
        self.extract_timeout = QSpinBox()
        self.extract_timeout.setRange(30, 300)
        self.extract_timeout.setValue(int(cfg.get("extract_timeout", 90)))
        self.rpq = QSpinBox(); self.rpq.setRange(3, 15); self.rpq.setValue(int(cfg.get("results_per_query", 8)))
        self.mds = QSpinBox(); self.mds.setRange(1, 10); self.mds.setValue(int(cfg.get("max_deep_sources", 5)))
        f.addRow("Base URL (OpenAI-compatible):", self.base)
        f.addRow("Model:", self.model)
        f.addRow("API Key (AI):", self.key)
        f.addRow("Web search:", self.sprov)
        f.addRow("Chế độ tìm kiếm:", self.smode)
        f.addRow("Serper API Key:", self.serper_key)
        f.addRow("Exa API Key:", self.exa_key)
        f.addRow("Tavily API Key:", self.tavily_key)
        f.addRow(self.cmp); f.addRow(self.fp)
        f.addRow("AI extract timeout (giay):", self.extract_timeout)
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
                           "search_mode": self.smode.currentText(),
                           "search_key": self._selected_search_key(),
                           "serper_key": self.serper_key.text().strip(),
                           "exa_key": self.exa_key.text().strip(),
                           "tavily_key": self.tavily_key.text().strip(),
                           "compare": self.cmp.isChecked(),
                           "extract_timeout": self.extract_timeout.value(),
                           "fetch_pages": self.fp.isChecked(), "ttl_days": self.ttl.value(),
                           "results_per_query": self.rpq.value(), "max_deep_sources": self.mds.value()})
        self.accept()

    def on_model_changed(self, model):
        self.base.setText(resolve_base_url(model, self.base.text()))

    def _selected_search_key(self):
        provider = self.sprov.currentText()
        if provider == "serper":
            return self.serper_key.text().strip()
        if provider == "exa":
            return self.exa_key.text().strip()
        if provider == "tavily":
            return self.tavily_key.text().strip()
        return ""
