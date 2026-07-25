# -*- coding: utf-8 -*-
from graph_app_common import TabPlugin, register_tab, QtWidgets


class ThresholdTab(TabPlugin):
    key = "threshold"
    title = "5. しきい値"
    order = 50
    min_level = "全部"

    def build(self, app):
        w = QtWidgets.QWidget()
        lay = QtWidgets.QFormLayout(w)

        self.enabled = QtWidgets.QCheckBox("表示する")
        self.enabled.setChecked(True)
        self.enabled.toggled.connect(lambda: app.draw_graph())

        self.thr = QtWidgets.QLineEdit()
        self.thr.setPlaceholderText("例: 0.5")
        self.thr.editingFinished.connect(lambda: app.draw_graph())

        self.style = QtWidgets.QComboBox()
        self.style.addItems(["破線", "点線", "実線"])
        self.style.currentTextChanged.connect(lambda _text: app.draw_graph())

        lay.addRow("しきい値ライン", self.enabled)
        lay.addRow("Y値", self.thr)
        lay.addRow("線種", self.style)

        return w

    def draw_overlay(self, app, ax):
        if not getattr(self, "enabled", None) or not self.enabled.isChecked():
            return

        if not hasattr(ax, "axhline"):
            return

        text = self.thr.text().strip()
        if not text:
            return

        try:
            y = float(text)
        except ValueError:
            return

        style_map = {
            "破線": "--",
            "点線": ":",
            "実線": "-",
        }
        linestyle = style_map.get(self.style.currentText(), "--")

        ax.axhline(y, color="tab:red", linestyle=linestyle)

    def collect_config(self, app):
        return {
            "enabled": self.enabled.isChecked(),
            "thr": self.thr.text(),
            "style": self.style.currentText(),
        }

    def apply_config(self, app, cfg):
        self.enabled.blockSignals(True)
        self.thr.blockSignals(True)
        self.style.blockSignals(True)

        self.enabled.setChecked(bool(cfg.get("enabled", True)))
        self.thr.setText(str(cfg.get("thr", "")))

        style = str(cfg.get("style", "破線"))
        idx = self.style.findText(style)
        if idx >= 0:
            self.style.setCurrentIndex(idx)

        self.enabled.blockSignals(False)
        self.thr.blockSignals(False)
        self.style.blockSignals(False)


register_tab(ThresholdTab())
