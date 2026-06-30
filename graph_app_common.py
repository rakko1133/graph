# -*- coding: utf-8 -*-
"""GraphApp と各 Mixin が共有する import・定数・補助クラス。"""
import os
import re
import sys

from matplotlib.backends.qt_compat import QtCore, QtGui, QtWidgets
from matplotlib.backends.backend_qtagg import (
    FigureCanvasQTAgg as FigureCanvas,
    NavigationToolbar2QT as NavigationToolbar,
)
from matplotlib.figure import Figure

import advanced
import analysis
import applog
import config_io
import data_loader
import datasci
import jp_font
import mathchan
import plotter

PREVIEW_ROWS = 100
UserRole = QtCore.Qt.ItemDataRole.UserRole
DECIMATE_TARGET = 8000   # 折れ線/散布図でこの点数を超えたら間引いて表示
BUSY_ROWS = 200_000      # この行数を超える読み込みは待機カーソルを出す
BATCH_PARALLEL_THRESHOLD = 64   # 一括出力でこの枚数以上なら別プロセス並列を試みる


def _parse_float(text, default=None):
    text = (text or "").strip()
    if text == "":
        return default
    try:
        return float(text)        # 1e-6 / 0.000001 / 1000 などはそのまま
    except ValueError:
        pass
    # 『底^指数』表記も許可: 10^-6 → 1e-6, 2^10 → 1024（^ は累乗）
    m = re.fullmatch(r"([+-]?[\d.]+)\s*\^\s*([+-]?[\d.]+)", text)
    if m:
        try:
            return float(m.group(1)) ** float(m.group(2))
        except (ValueError, OverflowError, ZeroDivisionError):
            return default
    return default


class CheckListWidget(QtWidgets.QListWidget):
    """行のどこをクリックしてもチェックがトグルするリスト。

    チェックボックスの小さな枠だけでなく、行全体が当たり判定になる。
    （Qt 標準のインジケータ自動トグルと二重にならないよう、ここで一括処理）
    """

    def mousePressEvent(self, event):
        item = self.itemAt(event.position().toPoint())
        if item is not None and (item.flags() & QtCore.Qt.ItemFlag.ItemIsUserCheckable):
            checked = item.checkState() == QtCore.Qt.CheckState.Checked
            item.setCheckState(QtCore.Qt.CheckState.Unchecked if checked
                               else QtCore.Qt.CheckState.Checked)
            event.accept()
            return
        super().mousePressEvent(event)


class LazyColumnCombo(QtWidgets.QComboBox):
    """誤差列の選択コンボ。列一覧は初回オープン時に遅延展開する。

    多系列でスタイル表を作り直すとき、各行のコンボへ全列を addItems すると重い
    （多系列で支配的コスト）。最初は『なし』＋現在値だけを持ち、ユーザーが
    ドロップダウンを開いた時に初めて全列を読み込む。"""

    def __init__(self, get_cols, current, parent=None):
        super().__init__(parent)
        self._get_cols = get_cols
        self._loaded = False
        self.addItem("なし")
        if current:
            self.addItem(str(current))
            self.setCurrentText(str(current))

    def showPopup(self):
        if not self._loaded:
            self._loaded = True
            cur = self.currentText()
            self.blockSignals(True)
            self.clear()
            self.addItem("なし")
            for c in self._get_cols():
                s = str(c)
                if s != "なし":
                    self.addItem(s)
            i = self.findText(cur)
            self.setCurrentIndex(i if i >= 0 else 0)
            self.blockSignals(False)
        super().showPopup()

__all__ = [
    "os",
    "sys",
    "QtCore",
    "QtGui",
    "QtWidgets",
    "FigureCanvas",
    "NavigationToolbar",
    "Figure",
    "advanced",
    "analysis",
    "applog",
    "config_io",
    "data_loader",
    "datasci",
    "jp_font",
    "mathchan",
    "plotter",
    "PREVIEW_ROWS",
    "UserRole",
    "DECIMATE_TARGET",
    "BUSY_ROWS",
    "BATCH_PARALLEL_THRESHOLD",
    "_parse_float",
    "CheckListWidget",
    "LazyColumnCombo",
]
