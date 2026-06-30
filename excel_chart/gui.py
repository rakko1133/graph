# -*- coding: utf-8 -*-
"""excel_chart の GUI アプリ（PySide6 / Qt）。

「特定の列を選び、特定の書式を整え、ネイティブ Excel グラフとして出力する」専用の
独立 GUI。既存の大きな解析アプリ(graph_app)とは別物で、必要なものだけを流用する:

  * データ読み込み : data_loader.load_table（CSV/TSV/Excel・文字コード/区切り自動判定）
  * 日本語フォント : jp_font.setup_japanese_font（プレビューの文字化け防止）
  * プレビュー描画 : plotter.plot_series（matplotlib で“見た目の意図”を即確認）
  * Excel 出力     : excel_chart.export_excel_chart（com=VBA互換 / openpyxl=Excel不要）

起動:
    python -m excel_chart.gui
    （または excel_chart/起動_Excelグラフ.bat）
"""
import os
import sys

# --- 既存システム（リポジトリ直下）を import できるように ---
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

import numpy as np

from matplotlib.backends.qt_compat import QtCore, QtWidgets
from matplotlib.backends.backend_qtagg import (
    FigureCanvasQTAgg as FigureCanvas,
    NavigationToolbar2QT as NavigationToolbar,
)
from matplotlib.figure import Figure

import data_loader
import jp_font
import plotter

from .spec import ChartSpec, SeriesSpec, CHART_TYPES, LINESTYLES, MARKERS
from .export import export_excel_chart, choose_engine

UserRole = QtCore.Qt.ItemDataRole.UserRole

# UI 表示用（日本語ラベル -> matplotlib 値）。spec.LINESTYLES/MARKERS を逆引きにも使う。
AXES = {"主軸": "primary", "第2軸": "secondary"}
LEGEND_LOCS = ["best", "upper right", "upper left", "lower left", "lower right",
               "right", "center left", "center right", "lower center",
               "upper center", "center"]
ENGINES = {"自動（Excelあれば高品質COM）": "auto",
           "COM（VBA完全互換・要Excel）": "com",
           "openpyxl（Excel不要）": "openpyxl"}


class ExcelChartApp(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.df = None
        self.path = None
        self.styles = {}          # 列名 -> {color,linestyle,linewidth,marker,markersize,axis,errcol}
        self._building = False     # UI 構築中はプレビュー抑制

        self.font_name = jp_font.setup_japanese_font()
        self.setWindowTitle("Excel グラフ出力ツール（Python だけでネイティブ Excel グラフ）")
        self.resize(1180, 760)
        self.setAcceptDrops(True)

        self._build_ui()
        self._set_status("CSV/TSV/Excel ファイルを開く（ドラッグ&ドロップ可）。")

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        root = QtWidgets.QHBoxLayout(central)

        # 左: コントロール（スクロール可）
        left = QtWidgets.QWidget()
        left.setMinimumWidth(440)
        left.setMaximumWidth(520)
        self._build_controls(QtWidgets.QVBoxLayout(left))
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(left)
        root.addWidget(scroll, 0)

        # 右: プレビュー（matplotlib）
        right = QtWidgets.QVBoxLayout()
        self.fig = Figure(figsize=(6, 4.2))
        self.ax = self.fig.add_subplot(111)
        self.canvas = FigureCanvas(self.fig)
        right.addWidget(NavigationToolbar(self.canvas, self))
        right.addWidget(self.canvas, 1)
        note = QtWidgets.QLabel(
            "↑ プレビュー(matplotlib)。実際の出力は編集可能な"
            "ネイティブ Excel グラフです。")
        note.setStyleSheet("color:#666;")
        right.addWidget(note)
        root.addLayout(right, 1)

        self._build_statusbar()

    def _build_controls(self, v):
        # --- ファイル ---
        box = QtWidgets.QGroupBox("1. データ")
        b = QtWidgets.QVBoxLayout(box)
        row = QtWidgets.QHBoxLayout()
        self.open_btn = QtWidgets.QPushButton("ファイルを開く…")
        self.open_btn.clicked.connect(self._open_file)
        row.addWidget(self.open_btn)
        self.file_label = QtWidgets.QLabel("（未選択）")
        self.file_label.setStyleSheet("color:#444;")
        row.addWidget(self.file_label, 1)
        b.addLayout(row)
        v.addWidget(box)

        # --- 列とグラフ種別 ---
        box = QtWidgets.QGroupBox("2. 列とグラフ種別")
        g = QtWidgets.QGridLayout(box)
        g.addWidget(QtWidgets.QLabel("グラフ種別"), 0, 0)
        self.type_combo = QtWidgets.QComboBox()
        self.type_combo.addItems(CHART_TYPES)
        self.type_combo.currentTextChanged.connect(self._on_type_changed)
        g.addWidget(self.type_combo, 0, 1)
        g.addWidget(QtWidgets.QLabel("X 軸の列"), 1, 0)
        self.x_combo = QtWidgets.QComboBox()
        self.x_combo.currentTextChanged.connect(lambda *_: self._update_preview())
        g.addWidget(self.x_combo, 1, 1)
        g.addWidget(QtWidgets.QLabel("Y 軸（値）"), 2, 0, QtCore.Qt.AlignmentFlag.AlignTop)
        self.y_list = QtWidgets.QListWidget()
        self.y_list.setMaximumHeight(130)
        self.y_list.itemChanged.connect(self._on_y_changed)
        g.addWidget(self.y_list, 2, 1)
        v.addWidget(box)

        # --- 系列スタイル ---
        box = QtWidgets.QGroupBox("3. 系列の書式")
        s = QtWidgets.QVBoxLayout(box)
        self.style_table = QtWidgets.QTableWidget(0, 6)
        self.style_table.setHorizontalHeaderLabels(
            ["系列名", "色", "線種", "幅", "マーカー", "軸"])
        self.style_table.horizontalHeader().setStretchLastSection(True)
        self.style_table.verticalHeader().setVisible(False)
        self.style_table.setMaximumHeight(170)
        self.style_table.itemChanged.connect(self._on_style_name_edited)
        s.addWidget(self.style_table)
        v.addWidget(box)

        # --- タイトル・ラベル ---
        box = QtWidgets.QGroupBox("4. タイトル・軸ラベル")
        g = QtWidgets.QGridLayout(box)
        self.title_edit = self._line(g, 0, "タイトル")
        self.xlabel_edit = self._line(g, 1, "X 軸ラベル")
        self.ylabel_edit = self._line(g, 2, "Y 軸ラベル")
        self.sec_edit = self._line(g, 3, "第2軸ラベル")
        v.addWidget(box)

        # --- 軸範囲・スケール ---
        box = QtWidgets.QGroupBox("5. 軸範囲・スケール")
        g = QtWidgets.QGridLayout(box)
        self.xmin = self._line(g, 0, "X 最小"); self.xmax = self._line(g, 0, "X 最大", col=2)
        self.ymin = self._line(g, 1, "Y 最小"); self.ymax = self._line(g, 1, "Y 最大", col=2)
        self.xlog = QtWidgets.QCheckBox("X 対数"); self.ylog = QtWidgets.QCheckBox("Y 対数")
        self.xinv = QtWidgets.QCheckBox("X 反転"); self.yinv = QtWidgets.QCheckBox("Y 反転")
        for i, c in enumerate((self.xlog, self.ylog, self.xinv, self.yinv)):
            c.stateChanged.connect(lambda *_: self._update_preview())
            g.addWidget(c, 2 + i // 2, (i % 2) * 2, 1, 2)
        v.addWidget(box)

        # --- 表示要素 ---
        box = QtWidgets.QGroupBox("6. 表示")
        g = QtWidgets.QGridLayout(box)
        self.legend_chk = QtWidgets.QCheckBox("凡例"); self.legend_chk.setChecked(True)
        self.grid_chk = QtWidgets.QCheckBox("グリッド"); self.grid_chk.setChecked(True)
        self.dlabel_chk = QtWidgets.QCheckBox("データラベル")
        self.pct_chk = QtWidgets.QCheckBox("円: %表示")
        for c in (self.legend_chk, self.grid_chk, self.dlabel_chk, self.pct_chk):
            c.stateChanged.connect(lambda *_: self._update_preview())
        g.addWidget(self.legend_chk, 0, 0); g.addWidget(self.grid_chk, 0, 1)
        g.addWidget(self.dlabel_chk, 1, 0); g.addWidget(self.pct_chk, 1, 1)
        g.addWidget(QtWidgets.QLabel("凡例位置"), 2, 0)
        self.legend_loc = QtWidgets.QComboBox(); self.legend_loc.addItems(LEGEND_LOCS)
        self.legend_loc.currentTextChanged.connect(lambda *_: self._update_preview())
        g.addWidget(self.legend_loc, 2, 1)
        g.addWidget(QtWidgets.QLabel("ヒストのビン数"), 3, 0)
        self.bins_spin = QtWidgets.QSpinBox(); self.bins_spin.setRange(2, 200); self.bins_spin.setValue(10)
        g.addWidget(self.bins_spin, 3, 1)
        v.addWidget(box)

        # --- 出力 ---
        box = QtWidgets.QGroupBox("7. 出力")
        g = QtWidgets.QGridLayout(box)
        g.addWidget(QtWidgets.QLabel("エンジン"), 0, 0)
        self.engine_combo = QtWidgets.QComboBox(); self.engine_combo.addItems(list(ENGINES.keys()))
        g.addWidget(self.engine_combo, 0, 1)
        self.preview_btn = QtWidgets.QPushButton("プレビュー更新")
        self.preview_btn.clicked.connect(self._update_preview)
        g.addWidget(self.preview_btn, 1, 0)
        self.export_btn = QtWidgets.QPushButton("Excel に出力…")
        self.export_btn.setStyleSheet("font-weight:bold;")
        self.export_btn.clicked.connect(self._export)
        g.addWidget(self.export_btn, 1, 1)
        v.addWidget(box)

        v.addStretch(1)

        # タイトル等の編集はフォーカスが外れたタイミングでプレビュー反映
        for e in (self.title_edit, self.xlabel_edit, self.ylabel_edit, self.sec_edit,
                  self.xmin, self.xmax, self.ymin, self.ymax):
            e.editingFinished.connect(self._update_preview)
        self.bins_spin.valueChanged.connect(lambda *_: self._update_preview())

    def _line(self, grid, rowcol, label, col=0):
        """グリッドにラベル＋1行入力を置いて QLineEdit を返す。"""
        grid.addWidget(QtWidgets.QLabel(label), rowcol, col)
        e = QtWidgets.QLineEdit()
        grid.addWidget(e, rowcol, col + 1)
        return e

    def _build_statusbar(self):
        self.status = QtWidgets.QStatusBar()
        self.setStatusBar(self.status)

    def _set_status(self, text):
        self.status.showMessage(text)

    # --------------------------------------------------------------- データ
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        for url in e.mimeData().urls():
            p = url.toLocalFile()
            if p:
                self._load(p)
                break

    def _open_file(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "データファイルを開く", os.path.expanduser("~"),
            "データ (*.csv *.tsv *.xlsx *.xlsm *.xls);;すべて (*.*)")
        if path:
            self._load(path)

    def _load(self, path):
        try:
            df, enc, delim = data_loader.load_table(path)
        except Exception as e:  # noqa: BLE001
            QtWidgets.QMessageBox.critical(self, "読み込みエラー", str(e))
            return
        self.df = df
        self.path = path
        self.styles.clear()
        self.file_label.setText(os.path.basename(path))
        self._populate_columns()
        self._set_status(f"読み込み: {os.path.basename(path)}  "
                         f"（{df.shape[0]}行 × {df.shape[1]}列, {enc}/{delim}）")

    def _populate_columns(self):
        self._building = True
        cols = list(self.df.columns)
        numeric = set(data_loader.numeric_columns(self.df))
        self.x_combo.blockSignals(True)
        self.x_combo.clear(); self.x_combo.addItems(cols)
        self.x_combo.blockSignals(False)
        # Y リスト（数値列を既定でチェック）
        self.y_list.blockSignals(True)
        self.y_list.clear()
        first_checked = False
        for c in cols:
            it = QtWidgets.QListWidgetItem(c)
            it.setFlags(it.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
            on = (c in numeric) and (c != cols[0])   # 先頭列は X 候補なので既定オフ
            it.setCheckState(QtCore.Qt.CheckState.Checked if on
                             else QtCore.Qt.CheckState.Unchecked)
            first_checked = first_checked or on
            self.y_list.addItem(it)
        self.y_list.blockSignals(False)
        # X は先頭列を既定に
        if cols:
            self.x_combo.setCurrentIndex(0)
        self._building = False
        self._rebuild_style_table()
        self._update_preview()

    # ------------------------------------------------------------- 選択・書式
    def _selected_y(self):
        out = []
        for i in range(self.y_list.count()):
            it = self.y_list.item(i)
            if it.checkState() == QtCore.Qt.CheckState.Checked:
                out.append(it.text())
        return out

    def _on_y_changed(self, _item):
        if self._building:
            return
        self._rebuild_style_table()
        self._update_preview()

    def _on_type_changed(self, *_):
        # 円グラフは Y を1つに制限する案内のみ（実害なく先頭採用）
        self._update_preview()

    def _rebuild_style_table(self):
        self._building = True
        ys = self._selected_y()
        self.style_table.setRowCount(len(ys))
        for r, col in enumerate(ys):
            st = self.styles.setdefault(col, {
                "color": None, "linestyle": "-", "linewidth": 1.5,
                "marker": "", "markersize": 4.0, "axis": "primary"})
            # 系列名（編集可）
            name = QtWidgets.QTableWidgetItem(st.get("label") or col)
            name.setData(UserRole, col)
            self.style_table.setItem(r, 0, name)
            # 色ボタン
            btn = QtWidgets.QPushButton(st["color"] or "自動")
            if st["color"]:
                btn.setStyleSheet(f"background:{st['color']};")
            btn.clicked.connect(lambda _=False, c=col, b=btn: self._pick_color(c, b))
            self.style_table.setCellWidget(r, 1, btn)
            # 線種
            ls = QtWidgets.QComboBox(); ls.addItems(list(LINESTYLES.keys()))
            ls.setCurrentText(_key_of(LINESTYLES, st["linestyle"], "実線"))
            ls.currentTextChanged.connect(
                lambda val, c=col: self._set_style(c, "linestyle", LINESTYLES[val]))
            self.style_table.setCellWidget(r, 2, ls)
            # 幅
            w = QtWidgets.QDoubleSpinBox(); w.setRange(0.2, 10); w.setSingleStep(0.5)
            w.setValue(st["linewidth"])
            w.valueChanged.connect(lambda val, c=col: self._set_style(c, "linewidth", val))
            self.style_table.setCellWidget(r, 3, w)
            # マーカー
            mk = QtWidgets.QComboBox(); mk.addItems(list(MARKERS.keys()))
            mk.setCurrentText(_key_of(MARKERS, st["marker"], "なし"))
            mk.currentTextChanged.connect(
                lambda val, c=col: self._set_style(c, "marker", MARKERS[val]))
            self.style_table.setCellWidget(r, 4, mk)
            # 軸
            ax = QtWidgets.QComboBox(); ax.addItems(list(AXES.keys()))
            ax.setCurrentText(_key_of(AXES, st["axis"], "主軸"))
            ax.currentTextChanged.connect(
                lambda val, c=col: self._set_style(c, "axis", AXES[val]))
            self.style_table.setCellWidget(r, 5, ax)
        self.style_table.resizeColumnsToContents()
        self._building = False

    def _on_style_name_edited(self, item):
        if self._building or item.column() != 0:
            return
        col = item.data(UserRole)
        if col is None:
            return
        self.styles.setdefault(col, {})["label"] = item.text().strip() or None
        self._update_preview()

    def _set_style(self, col, attr, value):
        self.styles.setdefault(col, {})[attr] = value
        if not self._building:
            self._update_preview()

    def _pick_color(self, col, btn):
        c = QtWidgets.QColorDialog.getColor(parent=self)
        if c.isValid():
            hexc = c.name()
            self.styles.setdefault(col, {})["color"] = hexc
            btn.setText(hexc); btn.setStyleSheet(f"background:{hexc};")
            self._update_preview()

    # --------------------------------------------------------------- スペック
    def _build_spec(self):
        ys = self._selected_y()
        if not ys:
            return None
        series = []
        for col in ys:
            st = self.styles.get(col, {})
            series.append(SeriesSpec(
                name=st.get("label") or col, y_col=col,
                color=st.get("color"), linestyle=st.get("linestyle", "-"),
                linewidth=float(st.get("linewidth", 1.5)),
                marker=st.get("marker", ""),
                markersize=float(st.get("markersize", 4.0)),
                axis=st.get("axis", "primary")))
        return ChartSpec(
            chart_type=self.type_combo.currentText(),
            x_col=self.x_combo.currentText() or None,
            series=series,
            title=self.title_edit.text(), xlabel=self.xlabel_edit.text(),
            ylabel=self.ylabel_edit.text(), secondary_label=self.sec_edit.text(),
            legend=self.legend_chk.isChecked(), legend_loc=self.legend_loc.currentText(),
            grid=self.grid_chk.isChecked(),
            xmin=_f(self.xmin.text()), xmax=_f(self.xmax.text()),
            ymin=_f(self.ymin.text()), ymax=_f(self.ymax.text()),
            xlog=self.xlog.isChecked(), ylog=self.ylog.isChecked(),
            xinvert=self.xinv.isChecked(), yinvert=self.yinv.isChecked(),
            data_labels=self.dlabel_chk.isChecked(), pct=self.pct_chk.isChecked(),
            bins=self.bins_spin.value())

    # --------------------------------------------------------------- プレビュー
    def _update_preview(self):
        if self._building or self.df is None:
            return
        spec = self._build_spec()
        if spec is None:
            self.ax.clear()
            self.ax.text(0.5, 0.5, "Y 軸（値）の列にチェックを入れてください",
                         ha="center", va="center", transform=self.ax.transAxes,
                         color="#888")
            self.canvas.draw_idle()
            return
        try:
            series, categories = self._preview_series(spec)
            xlim = (spec.xmin, spec.xmax) if (spec.xmin is not None or spec.xmax is not None) else None
            ylim = (spec.ymin, spec.ymax) if (spec.ymin is not None or spec.ymax is not None) else None
            plotter.plot_series(
                self.ax, series, spec.chart_type, categories=categories,
                bins=spec.bins, title=spec.title, xlabel=spec.xlabel,
                ylabel=spec.ylabel, grid=spec.grid, legend=spec.legend,
                legend_loc=spec.legend_loc, xlim=xlim, ylim=ylim,
                xlog=spec.xlog, ylog=spec.ylog, pct=spec.pct,
                data_labels=spec.data_labels, secondary_label=spec.secondary_label,
                xinvert=spec.xinvert, yinvert=spec.yinvert)
            self.fig.tight_layout()
            self.canvas.draw_idle()
            self._set_status("プレビュー更新。問題なければ「Excel に出力」。")
        except Exception as e:  # noqa: BLE001
            self.ax.clear()
            self.ax.text(0.5, 0.5, f"プレビュー不可:\n{e}", ha="center", va="center",
                         transform=self.ax.transAxes, color="#c0392b", wrap=True)
            self.canvas.draw_idle()
            self._set_status(f"プレビュー警告: {e}")

    def _preview_series(self, spec):
        df = self.df
        ct = spec.chart_type
        x = (df[spec.x_col].to_numpy()
             if spec.x_col and spec.x_col in df.columns else None)
        series, categories = [], None

        def style(s):
            return {"color": s.color, "linestyle": s.linestyle,
                    "linewidth": s.linewidth, "marker": s.marker,
                    "markersize": s.markersize, "alpha": 1.0}

        if ct in ("棒", "横棒", "積み上げ棒", "円"):
            categories = x if x is not None else np.arange(len(df))
            for s in spec.series:
                series.append({"label": s.name, "y": df[s.y_col].to_numpy(),
                               "style": style(s), "axis": s.axis, "kind": s.kind})
        elif ct in ("折れ線", "散布図"):
            xv = x if x is not None else np.arange(len(df))
            for s in spec.series:
                yerr = (df[s.errcol].to_numpy() if s.errcol and s.errcol in df.columns
                        else None)
                series.append({"label": s.name, "x": xv, "y": df[s.y_col].to_numpy(),
                               "style": style(s), "axis": s.axis, "kind": s.kind,
                               "yerr": yerr})
        else:  # ヒストグラム
            for s in spec.series:
                series.append({"label": s.name, "y": df[s.y_col].to_numpy(),
                               "style": style(s)})
        return series, categories

    # ----------------------------------------------------------------- 出力
    def _export(self):
        if self.df is None:
            QtWidgets.QMessageBox.information(self, "出力", "先にデータを読み込んでください。")
            return
        spec = self._build_spec()
        if spec is None:
            QtWidgets.QMessageBox.information(self, "出力", "Y 軸（値）の列を1つ以上選んでください。")
            return

        engine = ENGINES[self.engine_combo.currentText()]
        default_name = os.path.splitext(os.path.basename(self.path or "chart"))[0] + "_グラフ.xlsx"
        start = os.path.join(os.path.dirname(self.path or os.path.expanduser("~")), default_name)
        out, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Excel グラフを保存", start,
            "Excel ブック (*.xlsx);;マクロ有効ブック (*.xlsm)")
        if not out:
            return

        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
        try:
            used = choose_engine(engine, out)
            self._set_status(f"出力中…（エンジン: {used}）")
            QtWidgets.QApplication.processEvents()
            path, eng = export_excel_chart(self.df, spec=spec, out_path=out, engine=engine)
        except Exception as e:  # noqa: BLE001
            QtWidgets.QApplication.restoreOverrideCursor()
            QtWidgets.QMessageBox.critical(self, "出力エラー", str(e))
            self._set_status(f"出力エラー: {e}")
            return
        QtWidgets.QApplication.restoreOverrideCursor()
        self._set_status(f"出力しました: {path}  （エンジン: {eng}）")

        msg = QtWidgets.QMessageBox(self)
        msg.setWindowTitle("出力完了")
        msg.setText(f"ネイティブ Excel グラフを出力しました。\n\n{path}\n\nエンジン: {eng}")
        open_btn = msg.addButton("ファイルを開く", QtWidgets.QMessageBox.ButtonRole.AcceptRole)
        msg.addButton("閉じる", QtWidgets.QMessageBox.ButtonRole.RejectRole)
        msg.exec()
        if msg.clickedButton() is open_btn:
            try:
                os.startfile(path)   # Windows
            except Exception:
                pass


def _key_of(mapping, value, default):
    """値 -> キーの逆引き（最初に一致したキー、無ければ default）。"""
    for k, vv in mapping.items():
        if vv == value:
            return k
    return default


def _f(text):
    """軸範囲テキスト -> float（空/不正は None）。'10^-6' 等は plotter 系で解釈。"""
    t = (text or "").strip()
    if not t:
        return None
    try:
        return float(t)
    except ValueError:
        try:
            from plotter_format import parse_eng
            return parse_eng(t, default=None)
        except Exception:
            return None


def main():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    win = ExcelChartApp()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
