# [25/30] graph_app_mixins/analysis_peaks.py の仕様

## 指示（最重要・必読）

- この仕様だけを読んで、`graph_app_mixins/analysis_peaks.py` を **完全な形** で実装し、ファイル全体を出力してください。
- `pass`・`TODO`・`...`・「省略」・「以下同様」・要約・部分実装は **一切禁止** です。すべてのメソッド本体を最後まで書き切ってください。
- 出力が途中で切れた場合は、こちらが「続き」と言うので、**続きから最後まで** 出してください（重複や再要約はしない）。
- 提示するシグネチャ・定数値・UIラベル文字列・数式・係数・辞書キー名・テーブル列番号・書式指定子は **そのままの値** で実装してください（これらは「仕様データ」です）。

### アプリ全体の前提（このファイルに関係する分のみ）

- Python 3.10+ / GUI=PySide6(Qt6)。Qt は必ず matplotlib 経由で取得する（直接 `import PySide6` しない）。本ファイルでは `from graph_app_common import *` を通じて `QtWidgets` 等が供給される。
- Qt6 の列挙は **スコープ付き** で書く。本ファイルで使うもの: `QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers`。
- `GraphApp` は 10 個の Mixin ＋ `QtWidgets.QMainWindow` の多重継承。`__init__` / `closeEvent` は本体に置く。**各 Mixin は `from graph_app_common import *` で始まるメソッド束で、`__init__` を持たない**。`@staticmethod` は装飾ごと担当 Mixin に置く（このファイルには static メソッドは無い）。
- `analysis`（`analysis.py` ファサード）と `plotter`（`plotter.py` ファサード）は `graph_app_common` 経由で参照できる名前。`os` も同様に供給される。
- 日本語に `family="monospace"` を使わない（□化け回避）。本ファイルでは matplotlib のテキスト直書きは無く、描画は `plotter.plot_series` 経由なので monospace は登場しない。
- `grid` の linewidth に `None` を渡さない規約があるが、本ファイルでは `grid=True` を渡すのみ（linewidth は扱わない）。

---

## 1. ファイルの役割 / 責務

- 1行 docstring（モジュール先頭）: `"""AnalysisMixin: GraphApp から分離した AnalysisMixin 群（挙動は本体と同一）。"""`
- このファイルは **解析タブの中核ロジック** を担う `AnalysisMixin` クラスを定義する。責務は次の通り:
  1. 選択系列から解析用の `(t, y)` を取り出す（時間軸の数値化・「表示範囲のみ測定」対応）。
  2. ピーク検出してグラフ上のマーカー定義を返す。
  3. 単一系列の解析（ピーク表・測定表の更新、注記チェックボックス生成）。
  4. 測定値の注記表示のオン/オフをグラフへ反映。
  5. 選択全系列の FFT スペクトルを1枚に重ね描き。
  6. 全系列の一括解析を別ウィンドウ（2つの表＋CSV保存）で表示。
- 実体の数値計算は `analysis` ファサードに委譲し、本クラスは「データ取り出し・UI 反映・描画指示」に徹する。

---

## 2. 依存（import するもの）

- モジュール冒頭は **1行のみ**: `from graph_app_common import *  # noqa: F401,F403`
  - これにより `QtWidgets` / `analysis` / `plotter` / `os` が供給される。
- メソッド内 **遅延 import**（関数ローカル）で使うもの:
  - `_xy_for`: `import numpy as np`, `import pandas as pd`
  - `run_analysis`: `import numpy as np`
  - `show_fft`: `import numpy as np`
  - `analyze_all_series`: `import numpy as np`
  - `_save_analysis_csv`: `import csv`
- `self.*` で前提とする属性・ウィジェット（他 Mixin / 本体が用意する。本ファイルでは生成しない）:
  - データ: `self.datasets`（`{ファイル名: DataFrame}`）, `self.last_dir`
  - メソッド: `self._selected_series_items()`（`(fl, col, disp)` のリストを返す）, `self._style_key(fl, col)`, `self.draw_graph()`, `self._reset_figure_axes()`, `self._apply_aspect()`, `self._fonts()`, `self._set_status(msg)`, `self._has_drawn`
  - matplotlib: `self.ax`, `self.fig`, `self.canvas`
  - ウィジェット: `self.x_combo`, `self.window_meas_check`, `self.analysis_target`, `self.chart_combo`, `self.npeaks`, `self.smooth_spin`, `self.peak_table`, `self.meas_table`, `self.show_peaks_check`, `self.series_styles`
  - 任意属性（`hasattr` で確認）: `self.fft_window`, `self.fft_db`
  - 動的に作る属性: `self._meas_annotations`, `self._analysis_window`

---

## 3. 公開 API（クラスとメソッド：完全シグネチャ＋挙動）

クラス定義: `class AnalysisMixin:`（基底なし。Mixin 規約により `__init__` は持たない）。
クラス内コメント見出し（任意・原典どおり）: `# ------------------------------------------------------------ 解析`、および一括解析の前に `# -------------------------------------------------- 全系列の一括解析（別ウィンドウ・CSV保存）`。

### 3.1 `def _xy_for(self, fl, col):`

- docstring（複数行）:
  ```
  指定系列(fl,col)の (t, y) を返す。時間軸は数値化（非数値ならインデックス）。
  「表示範囲のみ測定」ONなら画面のX範囲に絞る。
  ```
- 役割: 1系列の `(t, y)`（ともに `float` の numpy 配列）を返す。
- アルゴリズム:
  1. `df = self.datasets[fl]`。
  2. `xname = self.x_combo.currentText()`。
  3. `raw`: `xname` が `df.columns` にあれば `df[xname].to_numpy()`、無ければ `df.iloc[:, 0].to_numpy()`（先頭列フォールバック）。
  4. `t = pd.to_numeric(pd.Series(raw), errors="coerce").to_numpy(dtype=float)`。
  5. **非数値X判定**: `if np.isnan(t).mean() > 0.5:` のとき `t = np.arange(len(t), dtype=float)`（NaN が過半数ならインデックスを時間軸とみなす）。
  6. `y = pd.to_numeric(pd.Series(df[col].to_numpy()), errors="coerce").to_numpy(dtype=float)`。
  7. **表示範囲のみ測定**: `if self.window_meas_check.isChecked() and self._has_drawn:` のとき
     - `x0, x1 = self.ax.get_xlim()`、`if x1 < x0: x0, x1 = x1, x0`（反転軸に対応）。
     - `mask = (t >= x0) & (t <= x1)`。
     - `if int(mask.sum()) >= 3:` のときだけ `t, y = t[mask], y[mask]`（点が3未満なら絞り込まない＝ガード）。
  8. `return t, y`。

### 3.2 `def _analysis_xy(self):`

- docstring: `"""解析対象（解析対象コンボで選んだ1系列）の (t, y, label) を返す。"""`
- 役割: 解析対象コンボ `self.analysis_target.currentText()` に一致する1系列の `(t, y, label)` を返す。
- 処理: `disp = self.analysis_target.currentText()`。`for fl, col, d in self._selected_series_items():` を回し、`if d == disp:` なら `t, y = self._xy_for(fl, col)` して `return t, y, d`。
- 見つからなければ `return None, None, None`。

### 3.3 `def _peak_markers(self):`

- 役割: 折れ線/散布図のときだけ、解析対象系列のピークをグラフ用マーカー辞書のリストにして返す（描画ロジックから呼ばれる想定）。
- 処理:
  1. `if self.chart_combo.currentText() not in ("折れ線", "散布図"): return None`（対象グラフ種以外は何もしない）。
  2. `t, y, _ = self._analysis_xy()`。`if t is None: return None`。
  3. `try: peaks = analysis.find_signal_peaks(y, t=t, n=self.npeaks.value(), smooth=self.smooth_spin.value())` / `except Exception: return None`（計算失敗時は静かに None）。
  4. 返り値（リスト内包）: ピーク `p` のうち `p["time"] is not None` のものだけ、各々
     ```python
     {"x": p["time"], "y": p["value"], "text": f"第{p['rank']}", "color": "#ff3030"}
     ```
     - マーカー色は固定 `"#ff3030"`、ラベルは `f"第{p['rank']}"`。

### 3.4 `def run_analysis(self):`

- 役割: 解析対象1系列を解析し、ピーク表・測定表を更新する（解析ボタンのハンドラ）。
- 処理:
  1. `t, y, label = self._analysis_xy()`。`if t is None:` なら情報メッセージ `QtWidgets.QMessageBox.information(self, "情報", "解析対象の系列を選択してください。")` を出して `return`。
  2. `import numpy as np`、`y = np.asarray(y, float)`。
  3. `res = analysis.analyze(t, y, n_peaks=self.npeaks.value(), smooth=self.smooth_spin.value())`。`res` は `{"peaks": [...], "measurements": [...], ...}` 形。
  4. **ピーク表更新** `self.peak_table`（列構成: 0=順位 / 1=時刻 / 2=値）:
     - `self.peak_table.setRowCount(len(res["peaks"]))`。
     - 各 `p` について（`enumerate` の `r`）:
       - 列0: `QtWidgets.QTableWidgetItem(f"第{p['rank']}")`。
       - 列1（時刻）: `tv = "-" if p["time"] is None else f"{p['time']*1e3:.4g} ms"`（秒→ms に `*1e3`、書式 `:.4g`、単位 ` ms`、None は `"-"`）。`setItem(r, 1, QTableWidgetItem(tv))`。
       - 列2（値）: `f"{p['value']:.4g}"`。
  5. **測定表更新** `self.meas_table`（列構成: 0=項目名 / 1=値＋単位 / 2=注記チェックボックス）:
     - `rows = res["measurements"]`。
     - `had_ann = bool(getattr(self, "_meas_annotations", None))`（前回注記があったか）。
     - `self._meas_annotations = []`（新規解析で前回注記をリセット）。
     - `self.meas_table.setRowCount(len(rows))`。
     - 各 `m` について（`r`）:
       - `val = m["value"]`、`txt = "-" if val is None else f"{val:.6g} {m['unit']}"`（書式 `:.6g`＋空白＋単位、None は `"-"`）。
       - 列0: `QTableWidgetItem(m["name"])`、列1: `QTableWidgetItem(txt)`。
       - 列2: `cb = QtWidgets.QCheckBox()` を生成し、`cb.setToolTip("チェックすると、この測定値をグラフ上に注記表示します。")`、`cb.toggled.connect(self._refresh_meas_annotations)`、`self.meas_table.setCellWidget(r, 2, cb)`。
  6. **再描画判定**: `if self.show_peaks_check.isChecked() or had_ann: self.draw_graph()`（ピーク表示中、または前回注記を消す必要があるときだけ再描画）。
  7. `self._set_status(f"解析しました: {label}")`。

### 3.5 `def _refresh_meas_annotations(self, *_):`

- docstring: `"""測定値表で『表示』にチェックした行を集めてグラフへ注記表示する。"""`
- 引数 `*_` は可変長で捨てる（`toggled(bool)` シグナルから呼ばれるため）。
- 処理:
  1. `anns = []`。
  2. `for r in range(self.meas_table.rowCount()):` で各行をスキャン。
     - `cb = self.meas_table.cellWidget(r, 2)`。`if cb is not None and cb.isChecked():` のとき:
       - `k = self.meas_table.item(r, 0)`、`val = self.meas_table.item(r, 1)`。
       - `if k is not None and val is not None:` のとき `anns.append(f"{k.text()} = {val.text()}")`（注記文字列は `項目名 = 値表示`）。
  3. `self._meas_annotations = anns`。
  4. `if self.datasets: self.draw_graph()`（データがあれば、特殊表示直後でも通常グラフへ再描画して反映）。

### 3.6 `def show_fft(self):`

- docstring: `"""選択中の全系列のFFTスペクトルを1枚に重ね描き（系列ごとに色分け・凡例）。"""`
- 処理:
  1. `items = self._selected_series_items()`。`if not items:` → `QtWidgets.QMessageBox.information(self, "情報", "解析する系列を選択してください。")` して `return`。
  2. `import numpy as np`。
  3. **窓関数**: `win = self.fft_window.currentText() if hasattr(self, "fft_window") else "hann"`（既定 `"hann"`）。
  4. **dB 表示判定**: `use_db = hasattr(self, "fft_db") and self.fft_db.isChecked()`。
  5. **Y ラベル**: `ylab = "振幅 [dBV]" if use_db else "振幅"`。
  6. `series, markers, drawn = [], [], 0`。
  7. `for idx, (fl, col, disp) in enumerate(items):`
     - `t, y = self._xy_for(fl, col)`。`if t is None or len(np.asarray(y)) < 4: continue`（点が4未満はスキップ）。
     - `freqs, amp = analysis.fft_spectrum(t, np.asarray(y, float), window=win)`。`if freqs is None: continue`。
     - **色決定**:
       ```python
       color = (self.series_styles.get(self._style_key(fl, col)) or {}).get("color") \
           or f"C{idx % 10}"
       ```
       系列の指定色があれば使い、無ければ既定カラーサイクル `C0`〜`C9`（`idx % 10`）。
     - `disp_amp = analysis.to_db(amp) if use_db else amp`。
     - `series.append({"label": f"FFT: {disp}", "x": freqs, "y": disp_amp, "style": {"color": color, "linewidth": 1.0}})`（線幅 1.0 固定）。
     - **スペクトルピーク**: `for p in analysis.find_spectral_peaks(t, np.asarray(y, float), n=self.npeaks.value()):`
       - `yv = analysis.to_db(np.array([p["amplitude"]]))[0] if use_db else p["amplitude"]`。
       - `markers.append({"x": p["frequency"], "y": yv, "text": f"{p['frequency']:.0f}Hz", "color": color})`（ラベル例 `1000Hz`、書式 `:.0f` ＋ `Hz`、色は系列色と同じ）。
     - `drawn += 1`。
  8. `if drawn == 0:` → `QtWidgets.QMessageBox.warning(self, "FFT", "FFT を計算できませんでした。")` して `return`。
  9. **描画**:
     - `self._reset_figure_axes()`。
     - ```python
       plotter.plot_series(
           self.ax, series, "折れ線",
           title=f"FFTスペクトル（{win}窓・{drawn}系列）", xlabel="周波数 [Hz]", ylabel=ylab,
           grid=True, legend=(drawn > 1), markers=markers, fonts=self._fonts())
       ```
       - グラフ種は固定 `"折れ線"`、タイトルは `f"FFTスペクトル（{win}窓・{drawn}系列）"`、X ラベル `"周波数 [Hz]"`、Y ラベルは前述 `ylab`、`grid=True`、凡例は **2系列以上のときだけ** (`legend=(drawn > 1)`)、`markers` とフォントを渡す。
     - `self._apply_aspect()`（縦横比設定を FFT 表示にも適用）。
     - `try: self.fig.tight_layout() / except Exception: pass`（tight_layout 失敗は握りつぶす）。
     - `self.canvas.draw()`。
  10. `self._set_status(f"FFT表示: {drawn}系列を重ね描き")`。

### 3.7 `def analyze_all_series(self):`

- docstring: `"""選択中の全系列のピーク＋測定を計算し、別ウィンドウ（表＋CSV保存）で表示する。"""`
- 処理:
  1. `items = self._selected_series_items()`。`if not items:` → 情報メッセージ `"解析する系列を選択してください。"` → `return`。
  2. `import numpy as np`、`peak_rows, meas_rows = [], []`。
  3. `for fl, col, disp in items:`
     - `t, y = self._xy_for(fl, col)`。`if t is None or len(np.asarray(y)) < 2: continue`（点が2未満はスキップ）。
     - `r = analysis.analyze(t, np.asarray(y, float), n_peaks=self.npeaks.value(), smooth=self.smooth_spin.value())`。
     - `for p in r["peaks"]:` → `tv = None if p["time"] is None else p["time"] * 1e3`、`peak_rows.append((disp, f"第{p['rank']}", tv, p["value"]))`（タプル: 系列名 / 順位文字列 / 時刻[ms]またはNone / 値）。
     - `for m in r["measurements"]:` → `meas_rows.append((disp, m["name"], m["value"], m["unit"]))`（タプル: 系列名 / 項目名 / 値 / 単位）。
  4. `if not peak_rows and not meas_rows:` → 情報メッセージ `"解析できる系列がありません。"` → `return`。
  5. `self._show_analysis_window(peak_rows, meas_rows)`。

### 3.8 `def _show_analysis_window(self, peak_rows, meas_rows):`

- docstring: `"""系列ごとのピーク・測定を2つの表で別ウィンドウ表示。CSV保存ボタン付き。"""`
- GUI 構築:
  1. `dlg = QtWidgets.QDialog(self)`、`dlg.setWindowTitle("全系列の解析結果")`、`dlg.resize(760, 600)`。
  2. `lay = QtWidgets.QVBoxLayout(dlg)`。
  3. `no_edit = QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers`（編集不可トリガ。**Qt6 スコープ付き列挙**）。
  4. **ピーク表セクション**:
     - `lay.addWidget(QtWidgets.QLabel("■ ピーク（系列ごと）"))`。
     - `pk = QtWidgets.QTableWidget(len(peak_rows), 4)`、`pk.setHorizontalHeaderLabels(["系列", "順位", "時刻", "値"])`、`pk.setEditTriggers(no_edit)`。
     - `for r, (s, rank, tv, val) in enumerate(peak_rows):`
       - 列0: `QTableWidgetItem(str(s))`、列1: `QTableWidgetItem(str(rank))`。
       - 列2: `QTableWidgetItem("-" if tv is None else f"{tv:.4g} ms")`（時刻、書式 `:.4g` ＋ ` ms`、None は `"-"`）。
       - 列3: `QTableWidgetItem(f"{val:.6g}")`（値、書式 `:.6g`）。
     - `pk.resizeColumnsToContents()`、`lay.addWidget(pk)`。
  5. **測定表セクション**:
     - `lay.addWidget(QtWidgets.QLabel("■ 測定（系列ごと）"))`。
     - `ms = QtWidgets.QTableWidget(len(meas_rows), 4)`、`ms.setHorizontalHeaderLabels(["系列", "項目", "値", "単位"])`、`ms.setEditTriggers(no_edit)`。
     - `for r, (s, name, val, unit) in enumerate(meas_rows):`
       - 列0: `str(s)`、列1: `str(name)`。
       - 列2: `"-" if val is None else f"{val:.6g}"`（None は `"-"`、それ以外 `:.6g`）。
       - 列3: `str(unit)`。
     - `ms.resizeColumnsToContents()`、`lay.addWidget(ms, 1)`（stretch=1 で測定表を伸縮側にする）。
  6. **ボタン行**:
     - `brow = QtWidgets.QHBoxLayout()`。
     - `b_save = QtWidgets.QPushButton("CSVで保存…")`、`b_save.clicked.connect(lambda: self._save_analysis_csv(peak_rows, meas_rows))`。
     - `b_close = QtWidgets.QPushButton("閉じる")`、`b_close.clicked.connect(dlg.close)`。
     - `brow.addStretch(1); brow.addWidget(b_save); brow.addWidget(b_close)`（左にスペーサ→保存→閉じる、の順）。
     - `lay.addLayout(brow)`。
  7. `self._analysis_window = dlg`（**参照保持**: GC で即閉じしないよう属性に持つ）。
  8. `dlg.show()`（モードレス表示。`exec()` ではない）。

### 3.9 `def _save_analysis_csv(self, peak_rows, meas_rows):`

- 役割: 解析結果を CSV（UTF-8 BOM）に保存する。
- 処理:
  1. `path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "解析結果をCSVで保存", self.last_dir, "CSV (*.csv)")`。`if not path: return`（キャンセル）。
  2. `import csv`。
  3. `try:` ブロック内で `with open(path, "w", newline="", encoding="utf-8-sig") as f:`（**`newline=""` ＋ `utf-8-sig`** が必須。Excel 文字化け回避＋改行重複回避）:
     - `w = csv.writer(f)`。
     - `w.writerow(["# ピーク"])`。
     - `w.writerow(["系列", "順位", "時刻[ms]", "値"])`（ヘッダ。時刻列名は `時刻[ms]`）。
     - `for s, rank, tv, val in peak_rows:` → `w.writerow([s, rank, "" if tv is None else f"{tv:.6g}", f"{val:.6g}"])`（None は空文字、それ以外 `:.6g`）。
     - `w.writerow([])`（空行）。
     - `w.writerow(["# 測定"])`。
     - `w.writerow(["系列", "項目", "値", "単位"])`。
     - `for s, name, val, unit in meas_rows:` → `w.writerow([s, name, "" if val is None else f"{val:.6g}", unit])`。
  4. 成功後: `self.last_dir = os.path.dirname(path)`、`self._set_status(f"解析結果を保存しました: {path}")`。
  5. `except Exception as e:  # noqa: BLE001` → `QtWidgets.QMessageBox.critical(self, "保存エラー", str(e))`。

---

## 4. 委譲先 `analysis` ファサードの関数（前提）

本ファイルは値計算をすべて `analysis` に委譲する。実装はしないが、呼び出し契約（戻り値の形）を満たすこと:

- `analysis.find_signal_peaks(y, t=None, n=5, smooth=...)` → ピーク辞書のリスト。各要素は少なくとも `"time"`(秒, None あり) / `"value"` / `"rank"` を持つ。
- `analysis.analyze(t, y, n_peaks=..., smooth=...)` → `{"peaks": [...同上...], "measurements": [...], ...}`。`measurements` の各要素は `"name"` / `"value"`(None あり) / `"unit"` を持つ。
- `analysis.fft_spectrum(t, y, window=...)` → `(freqs, amp)`。計算不能時は `freqs is None`。
- `analysis.to_db(amp, ...)` → dB 変換した配列。
- `analysis.find_spectral_peaks(t, y, n=...)` → 各要素が `"frequency"` / `"amplitude"` を持つ辞書のリスト。
- `plotter.plot_series(ax, series, kind, *, title, xlabel, ylabel, grid, legend, markers, fonts)` に上記 `series`/`markers` 形を渡す。

---

## 5. 再現に必須の細部・エッジケース・落とし穴

- **時刻の単位換算**: ピーク時刻は秒で来るので、表示・保存では `*1e3` で ms にする。表示書式は `:.4g`（表 / 別窓ピーク表）、CSV は `:.6g`。値は表が `:.4g`（メイン peak_table 列2）/別窓と CSV は `:.6g`。測定値は表 `:.6g` ＋単位。これらの書式・係数を取り違えないこと。
- **None の表示規約**: 表セルでは `"-"`、CSV セルでは空文字 `""`。
- **「表示範囲のみ測定」のガード**: 絞り込み後の点数が 3 未満（`int(mask.sum()) >= 3` が偽）のときは絞り込みを **行わない**。また `self._has_drawn` が真でないと適用しない。反転軸（`x1 < x0`）はスワップして対応。
- **非数値 X 判定**: `np.isnan(t).mean() > 0.5`（NaN が過半数）ならインデックス時間軸に切替。
- **スキップ閾値の違い**: `show_fft` は `len(y) < 4` でスキップ、`analyze_all_series` は `len(y) < 2` でスキップ。混同しない。
- **凡例条件**: FFT の凡例は **2系列以上のときのみ** (`drawn > 1`)。
- **色フォールバック**: `(self.series_styles.get(self._style_key(fl, col)) or {}).get("color") or f"C{idx % 10}"`。`series_styles` に該当キーが無い/値が None の両方を `or {}` で吸収し、最終的に `C0`〜`C9` を循環。
- **`_meas_annotations` のライフサイクル**: `run_analysis` で必ず空リストに初期化（前回注記の消去）。`getattr(self, "_meas_annotations", None)` で前回有無を判定してから再描画要否を決める。`_refresh_meas_annotations` で集計し直す。
- **再描画の最小化**: `run_analysis` はピーク表示中か前回注記ありのときのみ `draw_graph()`。`_refresh_meas_annotations` は `self.datasets` が空でなければ `draw_graph()`。
- **Qt6 スコープ列挙**: `QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers`（`QAbstractItemView.NoEditTriggers` の旧形は不可）。
- **ダイアログの参照保持**: `self._analysis_window = dlg` を必ず行い、`dlg.show()`（モードレス）で表示。これを忘れると GC で即閉じする。
- **CSV のエンコーディング**: `encoding="utf-8-sig"`（BOM 付き）＋ `newline=""`。両方必須。
- **例外方針**: `_peak_markers` と FFT の `freqs is None` は静かにスキップ/None。`fig.tight_layout()` 失敗は `try/except: pass`。CSV 保存失敗は `QMessageBox.critical` で通知。
- **Mixin 規約**: クラスは `__init__` を持たず、`self.*` の各属性・ウィジェットは他 Mixin / 本体が用意済みである前提。本ファイルでウィジェット生成するのは `_show_analysis_window`（ダイアログ）と `run_analysis` 内の `QCheckBox` のみ。
- **遅延 import**: `numpy`/`pandas`/`csv` はすべてメソッド内で import（起動高速化・モジュール先頭では import しない）。
