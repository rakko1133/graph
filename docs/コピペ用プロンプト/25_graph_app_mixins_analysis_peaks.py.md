# [25/30] ファイル `graph_app_mixins/analysis_peaks.py` を作成

あなたは PySide6 + matplotlib 製のデスクトップアプリ「CSV / TSV / 波形 グラフ・解析ツール」を、複数ファイルに分けて再現しています。
これはその **25 番目** のファイルです（全 30 ファイル）。

## 指示（厳守）
- 下のコードブロックの内容で、ファイル `graph_app_mixins/analysis_peaks.py` を**新規作成**してください。
- **一字一句そのまま・省略なし**で出力すること。`pass` だけの空クラス／`# TODO`／`… 省略 …`／要約・解説への置き換えは**禁止**。
- 出力が途中で切れたら、こちらが「続き」と言うので、**最後の行まで**出力してください。
- 前置き・後書き・他ファイルの説明は不要。**このファイルの完全な中身だけ**を返してください。
- 文字コードは UTF-8。フォルダ付きパス（例 `graph_app_mixins/...`）はその階層に作成してください。

## `graph_app_mixins/analysis_peaks.py` の中身（このまま出力）
```python
# -*- coding: utf-8 -*-
"""AnalysisMixin: GraphApp から分離した AnalysisMixin 群（挙動は本体と同一）。"""
from graph_app_common import *  # noqa: F401,F403


class AnalysisMixin:
    # ------------------------------------------------------------ 解析
    def _xy_for(self, fl, col):
        """指定系列(fl,col)の (t, y) を返す。時間軸は数値化（非数値ならインデックス）。
        「表示範囲のみ測定」ONなら画面のX範囲に絞る。"""
        import numpy as np
        import pandas as pd
        df = self.datasets[fl]
        xname = self.x_combo.currentText()
        raw = df[xname].to_numpy() if xname in df.columns else df.iloc[:, 0].to_numpy()
        t = pd.to_numeric(pd.Series(raw), errors="coerce").to_numpy(dtype=float)
        if np.isnan(t).mean() > 0.5:  # 非数値Xはインデックスを時間軸とみなす
            t = np.arange(len(t), dtype=float)
        y = pd.to_numeric(pd.Series(df[col].to_numpy()), errors="coerce").to_numpy(dtype=float)
        if self.window_meas_check.isChecked() and self._has_drawn:
            x0, x1 = self.ax.get_xlim()
            if x1 < x0:
                x0, x1 = x1, x0
            mask = (t >= x0) & (t <= x1)
            if int(mask.sum()) >= 3:
                t, y = t[mask], y[mask]
        return t, y

    def _analysis_xy(self):
        """解析対象（解析対象コンボで選んだ1系列）の (t, y, label) を返す。"""
        disp = self.analysis_target.currentText()
        for fl, col, d in self._selected_series_items():
            if d == disp:
                t, y = self._xy_for(fl, col)
                return t, y, d
        return None, None, None

    def _peak_markers(self):
        if self.chart_combo.currentText() not in ("折れ線", "散布図"):
            return None
        t, y, _ = self._analysis_xy()
        if t is None:
            return None
        try:
            peaks = analysis.find_signal_peaks(y, t=t, n=self.npeaks.value(),
                                               smooth=self.smooth_spin.value())
        except Exception:
            return None
        return [{"x": p["time"], "y": p["value"], "text": f"第{p['rank']}",
                 "color": "#ff3030"} for p in peaks if p["time"] is not None]

    def run_analysis(self):
        t, y, label = self._analysis_xy()
        if t is None:
            QtWidgets.QMessageBox.information(self, "情報", "解析対象の系列を選択してください。")
            return
        import numpy as np
        y = np.asarray(y, float)
        res = analysis.analyze(t, y, n_peaks=self.npeaks.value(),
                               smooth=self.smooth_spin.value())

        self.peak_table.setRowCount(len(res["peaks"]))
        for r, p in enumerate(res["peaks"]):
            self.peak_table.setItem(r, 0, QtWidgets.QTableWidgetItem(f"第{p['rank']}"))
            tv = "-" if p["time"] is None else f"{p['time']*1e3:.4g} ms"
            self.peak_table.setItem(r, 1, QtWidgets.QTableWidgetItem(tv))
            self.peak_table.setItem(r, 2, QtWidgets.QTableWidgetItem(f"{p['value']:.4g}"))

        rows = res["measurements"]
        had_ann = bool(getattr(self, "_meas_annotations", None))
        self._meas_annotations = []   # 新しい解析を表示したら前回の注記はリセット
        self.meas_table.setRowCount(len(rows))
        for r, m in enumerate(rows):
            val = m["value"]
            txt = "-" if val is None else f"{val:.6g} {m['unit']}"
            self.meas_table.setItem(r, 0, QtWidgets.QTableWidgetItem(m["name"]))
            self.meas_table.setItem(r, 1, QtWidgets.QTableWidgetItem(txt))
            cb = QtWidgets.QCheckBox()
            cb.setToolTip("チェックすると、この測定値をグラフ上に注記表示します。")
            cb.toggled.connect(self._refresh_meas_annotations)
            self.meas_table.setCellWidget(r, 2, cb)

        if self.show_peaks_check.isChecked() or had_ann:
            self.draw_graph()   # ピーク表示中、または前回の注記を消すため
        self._set_status(f"解析しました: {label}")

    def _refresh_meas_annotations(self, *_):
        """測定値表で『表示』にチェックした行を集めてグラフへ注記表示する。"""
        anns = []
        for r in range(self.meas_table.rowCount()):
            cb = self.meas_table.cellWidget(r, 2)
            if cb is not None and cb.isChecked():
                k = self.meas_table.item(r, 0)
                val = self.meas_table.item(r, 1)
                if k is not None and val is not None:
                    anns.append(f"{k.text()} = {val.text()}")
        self._meas_annotations = anns
        if self.datasets:   # 特殊表示(スペクトログラム等)直後でも通常グラフへ再描画して反映
            self.draw_graph()

    def show_fft(self):
        """選択中の全系列のFFTスペクトルを1枚に重ね描き（系列ごとに色分け・凡例）。"""
        items = self._selected_series_items()
        if not items:
            QtWidgets.QMessageBox.information(self, "情報", "解析する系列を選択してください。")
            return
        import numpy as np
        win = self.fft_window.currentText() if hasattr(self, "fft_window") else "hann"
        use_db = hasattr(self, "fft_db") and self.fft_db.isChecked()
        ylab = "振幅 [dBV]" if use_db else "振幅"
        series, markers, drawn = [], [], 0
        for idx, (fl, col, disp) in enumerate(items):
            t, y = self._xy_for(fl, col)
            if t is None or len(np.asarray(y)) < 4:
                continue
            freqs, amp = analysis.fft_spectrum(t, np.asarray(y, float), window=win)
            if freqs is None:
                continue
            color = (self.series_styles.get(self._style_key(fl, col)) or {}).get("color") \
                or f"C{idx % 10}"        # 系列の指定色、無ければ既定カラーサイクル
            disp_amp = analysis.to_db(amp) if use_db else amp
            series.append({"label": f"FFT: {disp}", "x": freqs, "y": disp_amp,
                           "style": {"color": color, "linewidth": 1.0}})
            for p in analysis.find_spectral_peaks(t, np.asarray(y, float), n=self.npeaks.value()):
                yv = analysis.to_db(np.array([p["amplitude"]]))[0] if use_db else p["amplitude"]
                markers.append({"x": p["frequency"], "y": yv,
                                "text": f"{p['frequency']:.0f}Hz", "color": color})
            drawn += 1
        if drawn == 0:
            QtWidgets.QMessageBox.warning(self, "FFT", "FFT を計算できませんでした。")
            return
        self._reset_figure_axes()
        plotter.plot_series(
            self.ax, series, "折れ線",
            title=f"FFTスペクトル（{win}窓・{drawn}系列）", xlabel="周波数 [Hz]", ylabel=ylab,
            grid=True, legend=(drawn > 1), markers=markers, fonts=self._fonts())
        self._apply_aspect()   # 縦横比の設定をFFT表示にも適用（自動なら解除）
        try:
            self.fig.tight_layout()
        except Exception:
            pass
        self.canvas.draw()
        self._set_status(f"FFT表示: {drawn}系列を重ね描き")

    # -------------------------------------------------- 全系列の一括解析（別ウィンドウ・CSV保存）
    def analyze_all_series(self):
        """選択中の全系列のピーク＋測定を計算し、別ウィンドウ（表＋CSV保存）で表示する。"""
        items = self._selected_series_items()
        if not items:
            QtWidgets.QMessageBox.information(self, "情報", "解析する系列を選択してください。")
            return
        import numpy as np
        peak_rows, meas_rows = [], []
        for fl, col, disp in items:
            t, y = self._xy_for(fl, col)
            if t is None or len(np.asarray(y)) < 2:
                continue
            r = analysis.analyze(t, np.asarray(y, float),
                                 n_peaks=self.npeaks.value(), smooth=self.smooth_spin.value())
            for p in r["peaks"]:
                tv = None if p["time"] is None else p["time"] * 1e3
                peak_rows.append((disp, f"第{p['rank']}", tv, p["value"]))
            for m in r["measurements"]:
                meas_rows.append((disp, m["name"], m["value"], m["unit"]))
        if not peak_rows and not meas_rows:
            QtWidgets.QMessageBox.information(self, "情報", "解析できる系列がありません。")
            return
        self._show_analysis_window(peak_rows, meas_rows)

    def _show_analysis_window(self, peak_rows, meas_rows):
        """系列ごとのピーク・測定を2つの表で別ウィンドウ表示。CSV保存ボタン付き。"""
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("全系列の解析結果")
        dlg.resize(760, 600)
        lay = QtWidgets.QVBoxLayout(dlg)
        no_edit = QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers

        lay.addWidget(QtWidgets.QLabel("■ ピーク（系列ごと）"))
        pk = QtWidgets.QTableWidget(len(peak_rows), 4)
        pk.setHorizontalHeaderLabels(["系列", "順位", "時刻", "値"])
        pk.setEditTriggers(no_edit)
        for r, (s, rank, tv, val) in enumerate(peak_rows):
            pk.setItem(r, 0, QtWidgets.QTableWidgetItem(str(s)))
            pk.setItem(r, 1, QtWidgets.QTableWidgetItem(str(rank)))
            pk.setItem(r, 2, QtWidgets.QTableWidgetItem("-" if tv is None else f"{tv:.4g} ms"))
            pk.setItem(r, 3, QtWidgets.QTableWidgetItem(f"{val:.6g}"))
        pk.resizeColumnsToContents()
        lay.addWidget(pk)

        lay.addWidget(QtWidgets.QLabel("■ 測定（系列ごと）"))
        ms = QtWidgets.QTableWidget(len(meas_rows), 4)
        ms.setHorizontalHeaderLabels(["系列", "項目", "値", "単位"])
        ms.setEditTriggers(no_edit)
        for r, (s, name, val, unit) in enumerate(meas_rows):
            ms.setItem(r, 0, QtWidgets.QTableWidgetItem(str(s)))
            ms.setItem(r, 1, QtWidgets.QTableWidgetItem(str(name)))
            ms.setItem(r, 2, QtWidgets.QTableWidgetItem("-" if val is None else f"{val:.6g}"))
            ms.setItem(r, 3, QtWidgets.QTableWidgetItem(str(unit)))
        ms.resizeColumnsToContents()
        lay.addWidget(ms, 1)

        brow = QtWidgets.QHBoxLayout()
        b_save = QtWidgets.QPushButton("CSVで保存…")
        b_save.clicked.connect(lambda: self._save_analysis_csv(peak_rows, meas_rows))
        b_close = QtWidgets.QPushButton("閉じる")
        b_close.clicked.connect(dlg.close)
        brow.addStretch(1); brow.addWidget(b_save); brow.addWidget(b_close)
        lay.addLayout(brow)
        self._analysis_window = dlg   # 参照保持（GCで即閉じしないように）
        dlg.show()

    def _save_analysis_csv(self, peak_rows, meas_rows):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "解析結果をCSVで保存", self.last_dir, "CSV (*.csv)")
        if not path:
            return
        import csv
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                w.writerow(["# ピーク"])
                w.writerow(["系列", "順位", "時刻[ms]", "値"])
                for s, rank, tv, val in peak_rows:
                    w.writerow([s, rank, "" if tv is None else f"{tv:.6g}", f"{val:.6g}"])
                w.writerow([])
                w.writerow(["# 測定"])
                w.writerow(["系列", "項目", "値", "単位"])
                for s, name, val, unit in meas_rows:
                    w.writerow([s, name, "" if val is None else f"{val:.6g}", unit])
            self.last_dir = os.path.dirname(path)
            self._set_status(f"解析結果を保存しました: {path}")
        except Exception as e:  # noqa: BLE001
            QtWidgets.QMessageBox.critical(self, "保存エラー", str(e))
```
