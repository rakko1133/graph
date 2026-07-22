# -*- coding: utf-8 -*-
"""GraphApp と各 Mixin が共有する import・定数・補助クラス。"""
import os
import re
import string
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
ASYNC_LOAD_BYTES = 4_000_000   # 合計がこれを超える読み込みはワーカースレッドへ回す
ASYNC_LOAD_COUNT = 8           # 枚数がこれを超える読み込みもワーカースレッドへ回す
SERIES_BAR_MAX = 60      # 系列バーに並べるチェックボックスの上限（超過分は一覧から選ぶ）
HEAVY_SERIES = 60        # これを超える系列数の描画は時間がかかるので確認を挟む
MESSAGE_LOG_MAX = 500    # メッセージ履歴の保持件数
NOTIFY_MS = 8000         # 通知バーの自動消灯までの時間（ミリ秒）


def _parse_float(text, default=None):
    text = (text or "").strip()
    if text == "":
        return default
    try:
        return float(text)        # 1e-6 / 0.000001 / 1000 などはそのまま
    except ValueError:
        pass                      # 失敗ではなく分岐（下の『底^指数』表記へ）
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

    def title(self):
        return self._btn.text()


# --------------------------------------------------------------- 配色（テーマ追従）
def _mix(c1, c2, ratio):
    """2色を ratio（0=c1, 1=c2）で混ぜる。"""
    r = max(0.0, min(1.0, float(ratio)))
    return QtGui.QColor(
        round(c1.red() * (1 - r) + c2.red() * r),
        round(c1.green() * (1 - r) + c2.green() * r),
        round(c1.blue() * (1 - r) + c2.blue() * r))


def palette_tokens(pal=None):
    """現在のパレットから QSS 用の色トークンを作る。

    QSS に色を直書きすると、OS がダークテーマのとき「白背景に白文字」に
    なって読めなくなる。背景・文字・境界線をすべてパレットから導出すれば、
    ライト／ダークのどちらでもコントラストが保たれる。
    """
    if pal is None:
        app = QtWidgets.QApplication.instance()
        pal = app.palette() if app is not None else QtGui.QPalette()
    role = QtGui.QPalette.ColorRole
    win = pal.color(role.Window)
    base = pal.color(role.Base)
    text = pal.color(role.WindowText)
    button = pal.color(role.Button)
    accent = pal.color(role.Highlight)
    accent_text = pal.color(role.HighlightedText)
    dark = win.lightness() < 128
    return {
        "bg": win.name(),
        "fg": text.name(),
        "base": base.name(),
        "button": _mix(button, base, 0.35 if not dark else 0.15).name(),
        "button_hover": _mix(button, accent, 0.25).name(),
        "button_down": _mix(button, accent, 0.45).name(),
        "accent": accent.name(),
        "accent_fg": accent_text.name(),
        "accent_soft": _mix(win, accent, 0.22).name(),
        "border": _mix(win, text, 0.32).name(),
        "border_soft": _mix(win, text, 0.18).name(),
        "title_bg": _mix(win, text, 0.07).name(),
        "muted": _mix(win, text, 0.55).name(),
        "info_bg": _mix(win, QtGui.QColor("#1e88e5"), 0.18).name(),
        "warn_bg": _mix(win, QtGui.QColor("#f9a825"), 0.24).name(),
        "error_bg": _mix(win, QtGui.QColor("#e53935"), 0.22).name(),
        "info_fg": _mix(text, QtGui.QColor("#1565c0"), 0.0 if dark else 0.7).name(),
        "warn_fg": _mix(text, QtGui.QColor("#8d6e00"), 0.0 if dark else 0.7).name(),
        "error_fg": _mix(text, QtGui.QColor("#b71c1c"), 0.0 if dark else 0.7).name(),
    }


def is_dark_theme(pal=None):
    """現在のパレットがダーク配色か。"""
    if pal is None:
        app = QtWidgets.QApplication.instance()
        pal = app.palette() if app is not None else QtGui.QPalette()
    return pal.color(QtGui.QPalette.ColorRole.Window).lightness() < 128


def render_qss(template, tokens=None):
    """`$bg` 形式のトークンを含む QSS テンプレートを実際の色へ展開する。

    QSS は `{}` を多用するので str.format ではなく string.Template を使う。"""
    return string.Template(template).safe_substitute(tokens or palette_tokens())


# --------------------------------------------------------------- 通知バー
class NotificationBar(QtWidgets.QFrame):
    """画面内に出す非モーダルの通知バー。

    「読み込みました」「先に系列を選んでください」程度の告知でモーダル
    ダイアログを出すと、そのたびに操作が止まって OK を押させられる。
    このバーは操作を止めず、一定時間で自動的に消える。重要なもの
    （エラー）は自動で消さず、閉じるまで残す。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("notify_bar")
        self.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(8, 4, 4, 4)
        lay.setSpacing(6)
        self._icon = QtWidgets.QLabel()
        self._icon.setAccessibleName("通知の種類")
        lay.addWidget(self._icon)
        self._text = QtWidgets.QLabel()
        self._text.setWordWrap(True)
        self._text.setTextInteractionFlags(
            QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        self._text.setAccessibleName("通知メッセージ")
        lay.addWidget(self._text, 1)
        self._detail_btn = QtWidgets.QToolButton()
        self._detail_btn.setText("詳細")
        self._detail_btn.setToolTip("メッセージの詳細を表示します")
        self._detail_btn.clicked.connect(self._show_detail)
        self._detail_btn.setVisible(False)
        lay.addWidget(self._detail_btn)
        close = QtWidgets.QToolButton()
        close.setText("✕")
        close.setToolTip("この通知を閉じます")
        close.setAccessibleName("通知を閉じる")
        close.clicked.connect(self.dismiss)
        lay.addWidget(close)
        self._detail = ""
        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.dismiss)
        self.setVisible(False)

    def show_message(self, text, level="info", detail="", timeout_ms=NOTIFY_MS):
        icons = {"info": "ℹ", "warn": "⚠", "error": "✖", "ok": "✔"}
        tok = palette_tokens()
        colors = {"info": ("info_bg", "info_fg"), "ok": ("info_bg", "info_fg"),
                  "warn": ("warn_bg", "warn_fg"), "error": ("error_bg", "error_fg")}
        bg, fg = colors.get(level, colors["info"])
        self.setStyleSheet(
            f"#notify_bar {{ background:{tok[bg]}; border:1px solid {tok['border_soft']};"
            f" border-radius:3px; }}"
            f"#notify_bar QLabel {{ color:{tok[fg]}; }}")
        self._icon.setText(icons.get(level, "ℹ"))
        self._text.setText(str(text))
        self._detail = str(detail or "")
        self._detail_btn.setVisible(bool(self._detail))
        self.setVisible(True)
        self._timer.stop()
        if level != "error" and timeout_ms:      # エラーは自分で閉じるまで残す
            self._timer.start(int(timeout_ms))

    def dismiss(self):
        self._timer.stop()
        self.setVisible(False)

    def current_text(self):
        return self._text.text()

    def _show_detail(self):
        QtWidgets.QMessageBox.information(self, "詳細", self._detail or self._text.text())


class ProgressStrip(QtWidgets.QFrame):
    """非モーダルの進捗表示（ラベル＋バー＋キャンセル）。

    モーダルの QProgressDialog と違い、進捗中も他のパネルを見たり
    ウィンドウを動かしたりできる。"""

    canceled = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(8, 2, 8, 2)
        lay.setSpacing(6)
        self._label = QtWidgets.QLabel("")
        self._label.setAccessibleName("処理の状況")
        lay.addWidget(self._label)
        self._bar = QtWidgets.QProgressBar()
        self._bar.setAccessibleName("進捗")
        self._bar.setMaximumHeight(14)
        lay.addWidget(self._bar, 1)
        self._cancel = QtWidgets.QPushButton("キャンセル")
        self._cancel.setToolTip("実行中の処理を中止します")
        self._cancel.clicked.connect(self.canceled.emit)
        lay.addWidget(self._cancel)
        self.setVisible(False)

    def start(self, text, total):
        self._label.setText(text)
        self._bar.setRange(0, max(1, int(total)))
        self._bar.setValue(0)
        self._cancel.setEnabled(True)
        self.setVisible(True)

    def update(self, value, text=None):
        self._bar.setValue(int(value))
        if text is not None:
            self._label.setText(text)

    def finish(self):
        self.setVisible(False)


# --------------------------------------------------------------- 読み込みワーカー
class TableLoadThread(QtCore.QThread):
    """`data_loader.load_table` を GUI スレッドの外で実行するワーカー。

    50万点級の CSV をイベントループ上で読むとウィンドウが固まり、Windows に
    「応答なし」と判定される。読み込みは Qt に触らない純粋な処理なので、
    ここで実行して結果だけをシグナルで GUI スレッドへ返す。
    """

    one_done = QtCore.Signal(int, object, str)   # 添字, (df, enc, delim) か None, エラー文
    progressed = QtCore.Signal(int, str)         # 完了数, 次に読むファイル名

    def __init__(self, jobs, parent=None):
        super().__init__(parent)
        self.jobs = list(jobs)
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def is_canceled(self):
        return self._cancel

    def run(self):
        for i, job in enumerate(self.jobs):
            if self._cancel:
                break
            self.progressed.emit(i, os.path.basename(job["path"]))
            try:
                res = data_loader.load_table(
                    job["path"], encoding=job.get("enc"),
                    delimiter=job.get("delim"), sheet=job.get("sheet"))
                self.one_done.emit(i, res, "")
            except Exception as e:  # noqa: BLE001  読み込み失敗は1件ずつ通知して続行
                self.one_done.emit(i, None, str(e))


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
    "ASYNC_LOAD_BYTES",
    "ASYNC_LOAD_COUNT",
    "SERIES_BAR_MAX",
    "HEAVY_SERIES",
    "MESSAGE_LOG_MAX",
    "NOTIFY_MS",
    "_parse_float",
    "CheckListWidget",
    "LazyColumnCombo",
    "CollapsibleBox",
    "ExplorerTree",
    "SERIES_MIME",
    "palette_tokens",
    "is_dark_theme",
    "render_qss",
    "NotificationBar",
    "ProgressStrip",
    "TableLoadThread",
]
