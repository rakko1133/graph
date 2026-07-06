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

SERIES_MIME = "application/x-graphapp-series"   # ツリー→グラフD&Dの系列ペイロード


class ExplorerTree(QtWidgets.QTreeWidget):
    """VS Code のエクスプローラー風ツリー（ファイル → 列）。

    VS Code 互換のキーボード操作: F2=名前の変更（renameRequested を発火）、
    Delete=削除（deleteRequested を発火）、文字入力=その名前へジャンプ（Qt標準）。
    描画はインデントガイド線（薄い縦線）付き。

    - 列行（親を持つチェック可能行）: クリック＝チェックのトグル（リリース時に確定）、
      **ドラッグ＝グラフへドロップして系列追加**（PlotJuggler風）。
    - ファイル行: クリック＝選択・展開（標準動作）、ドラッグ＝全列をまとめて追加。
    - 列行かどうかは「親を持つか」で判定する（childCount()==0 だと列ゼロの
      ファイル行まで葉扱いになり選択できなくなる）。
    - ダブルクリックは自前で itemDoubleClicked を発火する: press を消費すると
      Qt 内部の pressedIndex が更新されず標準の判定が成立しないため。
    """

    renameRequested = QtCore.Signal(object)   # F2: 対象アイテム
    deleteRequested = QtCore.Signal()         # Delete: 選択中ファイルの削除要求

    def __init__(self, parent=None):
        super().__init__(parent)
        self._press_item = None
        self._press_pos = None
        self._dragged = False

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key.Key_F2 and self.currentItem() is not None:
            self.renameRequested.emit(self.currentItem())
            event.accept()
            return
        if event.key() == QtCore.Qt.Key.Key_Delete:
            self.deleteRequested.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        # VS Code風のインデントガイド（階層ごとの薄い縦線）
        painter = QtGui.QPainter(self.viewport())
        painter.setPen(QtGui.QColor(128, 128, 128, 60))
        ind = max(self.indentation(), 1)
        idx = self.indexAt(QtCore.QPoint(0, 0))
        limit = self.viewport().height()
        while idx.isValid():
            rect = self.visualRect(idx)
            if rect.top() > limit:
                break
            depth, p = 0, idx.parent()
            while p.isValid():
                depth += 1
                p = p.parent()
            for lv in range(depth):
                x = lv * ind + ind // 2
                painter.drawLine(x, rect.top(), x, rect.bottom())
            idx = self.indexBelow(idx)
        painter.end()

    @staticmethod
    def _is_check_leaf(item):
        """列行（チェックトグル対象）か。UserRole の種別で判定する
        （フォルダ階層があると「親を持つ＝列」の判定は成立しないため）。"""
        if item is None:
            return False
        d = item.data(0, QtCore.Qt.ItemDataRole.UserRole)
        return bool(d and d[0] == "col"
                    and item.flags() & QtCore.Qt.ItemFlag.ItemIsUserCheckable)

    @classmethod
    def _drag_payload(cls, item):
        """ドラッグする (ファイル, 列) 行のリストを 'fl\\tcol' 行テキストで返す。
        列=1行／ファイル=全列／フォルダ=配下の全ファイルの全列。"""
        data = item.data(0, QtCore.Qt.ItemDataRole.UserRole)
        if data and data[0] == "col":
            return f"{data[1]}\t{data[2]}"
        rows = []
        if data and data[0] in ("file", "folder"):
            for j in range(item.childCount()):
                sub = cls._drag_payload(item.child(j))
                if sub:
                    rows.append(sub)
        return "\n".join(rows)

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            item = self.itemAt(event.position().toPoint())
            self._press_item = item
            self._press_pos = event.position().toPoint()
            self._dragged = False
            if self._is_check_leaf(item):
                event.accept()   # トグルはリリース時（ドラッグと区別するため）
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if (self._press_item is not None and not self._dragged
                and event.buttons() & QtCore.Qt.MouseButton.LeftButton
                and (event.position().toPoint() - self._press_pos).manhattanLength()
                >= QtWidgets.QApplication.startDragDistance()):
            payload = self._drag_payload(self._press_item)
            if payload:
                self._dragged = True
                drag = QtGui.QDrag(self)
                mime = QtCore.QMimeData()
                mime.setData(SERIES_MIME, payload.encode("utf-8"))
                mime.setText(self._press_item.text(0))
                drag.setMimeData(mime)
                drag.exec(QtCore.Qt.DropAction.CopyAction)
                self._press_item = None
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        item, dragged = self._press_item, self._dragged
        self._press_item = None
        if (event.button() == QtCore.Qt.MouseButton.LeftButton
                and not dragged and self._is_check_leaf(item)
                and item is self.itemAt(event.position().toPoint())):
            checked = item.checkState(0) == QtCore.Qt.CheckState.Checked
            item.setCheckState(0, QtCore.Qt.CheckState.Unchecked if checked
                               else QtCore.Qt.CheckState.Checked)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            item = self.itemAt(event.position().toPoint())
            if self._is_check_leaf(item):
                self.itemDoubleClicked.emit(item, 0)
                event.accept()
                return
        super().mouseDoubleClickEvent(event)


class CollapsibleBox(QtWidgets.QWidget):
    """見出しクリックで開閉できるセクション。

    右パネルの書式コントロールのような縦に長い設定群を項目ごとにまとめ、
    使わない項目を畳んで目的の設定を探しやすくする。中身のウィジェットは
    畳んでも生きたまま（非表示になるだけ）なので、機能・設定値は変わらない。
    """

    def __init__(self, title, expanded=True, parent=None):
        super().__init__(parent)
        self._btn = QtWidgets.QToolButton()
        self._btn.setText(title)
        self._btn.setCheckable(True)
        self._btn.setChecked(expanded)
        self._btn.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._btn.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding,
                                QtWidgets.QSizePolicy.Policy.Fixed)
        self._btn.setStyleSheet(
            "QToolButton { border:none; font-weight:bold; text-align:left; padding:2px; }")
        self._btn.toggled.connect(self._on_toggled)
        self.body = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        lay.setSpacing(2)
        lay.addWidget(self._btn)
        lay.addWidget(self.body)
        self._on_toggled(expanded)

    def _on_toggled(self, on):
        self._btn.setArrowType(QtCore.Qt.ArrowType.DownArrow if on
                               else QtCore.Qt.ArrowType.RightArrow)
        self.body.setVisible(on)

    def set_content_layout(self, layout):
        layout.setContentsMargins(8, 2, 2, 2)
        self.body.setLayout(layout)

    def is_expanded(self):
        return self._btn.isChecked()

    def set_expanded(self, on):
        self._btn.setChecked(bool(on))


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
    "CollapsibleBox",
    "ExplorerTree",
    "SERIES_MIME",
]
