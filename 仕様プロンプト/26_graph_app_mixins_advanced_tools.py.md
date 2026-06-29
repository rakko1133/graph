# [26/30] graph_app_mixins/advanced_tools.py の仕様

## 指示

- この仕様だけを読んで `graph_app_mixins/advanced_tools.py` を **完全な形** で実装し、ファイル全体を出力してください。
- `pass` のみ・`TODO`・「省略」・「以下同様」・要約・ダミー実装は **禁止** です。すべてのメソッド本体を実際に動作する形で書ききってください。
- 出力が長く途中で切れた場合は、続けて「続き」と言われたら **最後の行まで** 続きを出力してください。

### アプリ全体の前提（このファイルに関係する分）

- Python 3.10+ / GUI は PySide6 (Qt6)。Qt は必ず matplotlib 経由で取得する（`from matplotlib.backends.qt_compat import QtCore, QtGui, QtWidgets` 等）。このファイルでは `QtWidgets` のみ直接使用する。
- Qt6 の列挙はスコープ付き。本ファイルでは `QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers` を使用する（`NoEditTriggers` を裸で書かない）。
- `GraphApp` は 10 個の Mixin ＋ `QtWidgets.QMainWindow` の多重継承。`__init__` / `closeEvent` は本体に置く。**各 Mixin は `from graph_app_common import *` で始まり、`__init__` を持たないメソッド束**。本ファイル `AdvancedMixin` もこの規約に従う。
- 共通モジュールは `graph_app_common` を `import *` することで `QtWidgets` / `np`(numpy 系の名前) / `plotter` / `analysis` / `advanced` / `mathchan` などが名前空間に入る前提。ただし本ファイルは各メソッド内で都度 `import numpy as np` / `import pandas as pd` を行う（遅延 import 方針）。
- `plotter.py` / `analysis.py` は facade（実体を再公開）。`plotter.parse_eng` / `plotter.format_eng`、`analysis.*`、`advanced.*`、`mathchan.*` はそれぞれのモジュールの公開関数を呼ぶ。
- 日本語ラベルに `family="monospace"` を使わない（□化け回避）。本ファイルは matplotlib のテキストへフォント family を明示指定しない（既定の日本語フォント設定に従う）。
- `grid` の linewidth に `None` を渡さない。本ファイルの `grid` 呼び出しは `linewidth` を渡さず `alpha` のみ指定する。

---

## 1. ファイルの役割・責務

`AdvancedMixin` は `GraphApp` から分離した「高度解析・演算系」のメソッド束。docstring の趣旨は **「GraphApp から分離した AdvancedMixin 群（挙動は本体と同一）」**。

担当する機能は次の通り:

- **数学チャンネル**: 既存系列に単項/二項演算を適用して新しいデータセット（系列）を生成。
- **任意数式チャンネル**: A, B, VAR1, VAR2, t と許可関数からなる数式で新系列を生成（AST 安全評価）。
- **パラメータ統計ウィンドウ**: サイクル統計表＋測定値どうしの四則演算を別ダイアログで表示。
- **FFT/スペクトル指標**: THD・SNR・SINAD・ENOB・SFDR・占有帯域幅・チャネル電力・高調波探索をテーブルへ。
- **スペクトログラム表示**（pcolormesh ＋ カラーバー）。
- **マスクテスト**（上下限の合否＋違反点重畳）。
- **アイダイアグラム**（位相折りたたみ散布＋アイ測定）。
- **ジッタ（TIE）**測定。
- **サイクル統計 / 周波数トレンド**表示。
- **位相差/遅延**（2系列）。
- **プロトコルデコード**（UART / I2C / SPI）とテーブル表示、プロトコル切替に伴う UI 更新。

このファイルは UI ハンドラ層であり、数値計算の実体は `mathchan` / `analysis` / `advanced` に委譲する。Figure/Axes・各種ウィジェット（コンボ・テーブル・ラベル等）は他 Mixin（UI 構築側）が `self.*` として既に生成済みである前提で参照する。

---

## 2. 依存（import するもの）

ファイル先頭（モジュールレベル）:

```python
# -*- coding: utf-8 -*-
"""AdvancedMixin: GraphApp から分離した AdvancedMixin 群（挙動は本体と同一）。"""
from graph_app_common import *  # noqa: F401,F403
```

これにより `QtWidgets`, `plotter`, `analysis`, `advanced`, `mathchan` が参照可能になる前提。各メソッド内で必要に応じ `import numpy as np` / `import pandas as pd` を局所 import する（遅延 import）。`# noqa: BLE001` を広い `except Exception` に付すスタイルを踏襲する。

### 参照する他モジュールの API（呼び出し側として必要な情報のみ）

- `mathchan.BINARY_OPS` … リスト `["A+B", "A-B", "A×B", "A÷B"]`。
- `mathchan.binary(xa, ya, xb, yb, op) -> (x, r)`。
- `mathchan.unary(x, y, op, param=None) -> (x, r)`。
- `mathchan.eval_expr(expr, variables) -> ndarray/scalar`（AST 安全評価。`variables` は `name->値` の dict）。
- `plotter.parse_eng(text, default) -> float|None`（工学表記をパース。`text` 空や不正なら `default`）。
- `plotter.format_eng(value) -> str`（工学表記の文字列化）。
- `analysis.cycle_statistics(t, y) -> dict[str, dict]`（各パラメータ名 -> `{"mean","max","min","std","count"}`）。
- `analysis.measurements(t, y) -> list[dict]`（各要素 `{"name":..., "value":...}`）。
- `analysis.spectrum_metrics(t, y, window=...) -> dict`（キー: `f0, THD_pct, THD_dB, SNR_dB, SINAD_dB, ENOB_bits, SFDR_dB`）。
- `analysis.occupied_bandwidth(t, y, window=...) -> float|None`。
- `analysis.channel_power(t, y, window=...) -> float|None`。
- `analysis.harmonic_search(t, y, n_harm=5, window=...) -> list[dict]`（各要素 `{"harmonic":int, "frequency":float}`）。
- `analysis.spectrogram(t, y, window=...) -> (f, tt, S)`（`S is None` なら計算不可）。
- `analysis.cycle_measurements(t, y) -> dict`（キー: `freq, vpp, cycle_time` など。値は配列）。
- `analysis.measurement_stats(arr) -> dict`（`{"count","mean","std","min","max"}`）。
- `analysis.phase_delay(t1, y1, y2) -> (delay, phase)`（`delay is None` なら計算不可、`phase` は度 or None）。
- `advanced.mask_test(t, y, upper=None, lower=None) -> dict`（キー: `passed(bool), violations(int), violation_times, mask`）。
- `advanced.eye_diagram(t, y, symbol_period, n_ui=2) -> (phase, yy)`。
- `advanced.eye_measurements(t, y, symbol_period) -> dict|None`（キー: `level1, level0, eye_amplitude, eye_height, eye_width, q_factor, extinction_ratio_db, jitter_pp`）。
- `advanced.jitter_tie(t, y) -> dict|None`（キー: `rms, pp, freq, edges`）。
- `advanced.decode_uart(t, y, baud=...) -> list[dict]`（各要素 `{"time","hex","char","ok"}`）。
- `advanced.decode_i2c(t, scl, sda) -> list[dict]`（各要素 `{"time","type"...}`。`type` が `"START"/"STOP"` か data。data は `hex`, 任意で `rw`, `ack`）。
- `advanced.decode_spi(t, sck, mosi, cs=None) -> list[dict]`（各要素 `{"time","hex"}`）。

参照する `self.*` 属性（他 Mixin が生成・保持）:

- データ系: `self.datasets`（dict: ラベル -> DataFrame）, `self.meta`（dict）, `self.x_combo`。
- 数学チャンネル UI: `self.math_op`, `self.math_a`, `self.math_b`, `self.math_b_label`, `self.math_param`, `self.math_param_label`, `self.math_expr`, `self.math_var1`, `self.math_var2`。
- FFT/マスク/アイ UI: `self.fft_window`, `self.fft_metrics`(テーブル), `self.mask_upper`, `self.mask_lower`, `self.adv_result`(ラベル), `self.eye_rate`。
- 位相: `self.phase_target2`。
- プロトコル: `self.proto_combo`, `self.proto_ch`(リスト長3), `self.proto_ch_labels`(リスト長3), `self.proto_baud`, `self.proto_table`(4列)。
- 描画系: `self.fig`, `self.ax`, `self.canvas`, `self._has_drawn`。
- メソッド: `self._selected_series_items()`, `self._analysis_xy()`, `self._add_file_item(label)`, `self._refresh_columns()`, `self._set_status(msg)`, `self._reset_figure_axes()`, `self._apply_aspect()`, `self.draw_graph()`。

---

## 3. 公開 API（全メソッドの完全シグネチャと挙動）

すべて `class AdvancedMixin:` 内のインスタンスメソッド。並び順は下記の通り（実ソースの順序を保つこと）。クラス先頭にコメント行 `# ------------------------------------------------------------ 高度解析` を置く。

### 3.1 `def _xy_by_disp(self, disp):`

docstring: `"""選択中系列の表示名から (t, y) を取得（時間軸は数値化）。"""`

- 局所 import: numpy, pandas。
- `self._selected_series_items()` を `for fl, col, d in ...` で走査し、`d == disp` の最初の一致を採用。
- 一致時:
  - `df = self.datasets[fl]`。
  - `xname = self.x_combo.currentText()`。
  - `raw = df[xname].to_numpy() if xname in df.columns else df.iloc[:, 0].to_numpy()`（X 列名が無ければ先頭列）。
  - `t = pd.to_numeric(pd.Series(raw), errors="coerce").to_numpy(dtype=float)`。
  - **NaN 率が 0.5 超なら** `t = np.arange(len(t), dtype=float)`（非数値軸はインデックス化）。判定は `np.isnan(t).mean() > 0.5`。
  - `y = pd.to_numeric(pd.Series(df[col].to_numpy()), errors="coerce").to_numpy(dtype=float)`。
  - `return t, y`。
- 不一致のまま走査終了で `return None, None`。

### 3.2 `def _on_math_op_change(self, op):`

- `binary = op in mathchan.BINARY_OPS`。
- `self.math_b.setEnabled(binary)`、`self.math_b_label.setEnabled(binary)`。
- `needs_param = op in ("移動平均", "ローパス(RC)", "ローパス(Butterworth)", "ハイパス(Butterworth)")`（この4文字列が **正確** にパラメータ必要演算）。
- `self.math_param.setEnabled(needs_param)`、`self.math_param_label.setEnabled(needs_param)`。

### 3.3 `def create_math_channel(self):`

- 局所 import numpy。
- `op = self.math_op.currentText()`。
- `ta, ya = self._xy_by_disp(self.math_a.currentText())`。
- `ta is None` なら情報ダイアログ「演算対象Aをデータタブで選択してください。」を出して return（タイトル「情報」）。
- `try:` ブロック:
  - `op in mathchan.BINARY_OPS` の場合: B 系列を取得 `tb, yb = self._xy_by_disp(self.math_b.currentText())`。`tb is None` なら情報「演算対象Bを選択してください。」で return。`x, r = mathchan.binary(ta, ya, tb, yb, op)`。
  - else（単項）: `param = plotter.parse_eng(self.math_param.text(), None)`、`x, r = mathchan.unary(ta, ya, op, param)`。
- `except Exception as e:` → critical ダイアログ（タイトル「演算エラー」, 本文 `str(e)`）で return。
- pandas を局所 import。
- `col = f"{op}"`、`label = f"Math: {op}"`。
- **重複ラベル回避**: `base, i = label, 2`、`while label in self.datasets: label = f"{base} ({i})"; i += 1`。
- `self.datasets[label] = pd.DataFrame({"時間[s]": x, col: r})`。
- `self.meta[label] = {"path": label, "enc": "-", "delim": "-"}`。
- `self._add_file_item(label)`、`self._refresh_columns()`。
- `self._set_status(f"数学チャンネルを作成: {label} ▸ {col}")`（区切り記号は半角矢印 `▸`）。

### 3.4 `def create_math_expr(self):`

docstring: `"""任意数式（A,B,VAR1,VAR2,t と許可関数）で新チャンネルを作成。"""`

- 局所 import numpy, pandas。
- `expr = self.math_expr.text().strip()`。空なら情報「数式を入力してください。」で return。
- `ta, ya = self._xy_by_disp(self.math_a.currentText())`。`ta is None` なら情報「変数Aの系列をデータタブで選択してください。」で return。
- `variables` 構築（**キー名・既定値が重要**）:
  - `"A": ya`
  - `"t": ta`
  - `"VAR1": plotter.parse_eng(self.math_var1.text(), 0.0) or 0.0`
  - `"VAR2": plotter.parse_eng(self.math_var2.text(), 0.0) or 0.0`
- B 系列も取得し、両方非 None なら `variables["B"]` を設定。長さが ya と等しければそのまま、違えば `np.interp(ta, tb, yb)` で A 軸へ補間: `variables["B"] = yb if len(yb) == len(ya) else np.interp(ta, tb, yb)`。
- `try:`:
  - `r = mathchan.eval_expr(expr, variables)`。
  - `r = np.broadcast_to(np.asarray(r, dtype=float), ya.shape).astype(float)`（スカラ結果でも ya 形状へブロードキャスト）。
- `except Exception as e:` → critical「数式エラー」, `str(e)` で return。
- `label = f"Expr: {expr[:24]}"`（式先頭24文字をラベルに）。重複回避は 3.3 と同じ手順（`base, i = label, 2` / while）。
- `self.datasets[label] = pd.DataFrame({"時間[s]": ta, "結果": r})`。
- `self.meta[label] = {"path": label, "enc": "-", "delim": "-"}`。
- `self._add_file_item(label)`、`self._refresh_columns()`。
- `self._set_status(f"数式チャンネルを作成: {label}")`。

### 3.5 `def show_param_stats(self):`

docstring: `"""解析対象チャンネルのサイクル統計表＋パラメータ間演算を別ウィンドウで表示。"""`

- 局所 import numpy。
- `t, y, label = self._analysis_xy()`。`t is None` なら情報「解析対象の系列を選択してください。」で return。
- `yv = np.asarray(y, float)`。
- `self._show_param_stats_window(label, analysis.cycle_statistics(t, yv), analysis.measurements(t, yv))`。

### 3.6 `def _show_param_stats_window(self, label, stats, meas):`

別 `QtWidgets.QDialog` を構築・表示。詳細:

- `dlg = QtWidgets.QDialog(self)`、`dlg.setWindowTitle(f"パラメータ統計: {label}")`、`dlg.resize(700, 560)`。
- `lay = QtWidgets.QVBoxLayout(dlg)`。
- `no_edit = QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers`（Qt6 スコープ付き列挙）。
- ラベル追加: `QtWidgets.QLabel("■ サイクル統計（周期ごとに測り、平均/最大/最小/σ で集計）")`。
- テーブル: `tb = QtWidgets.QTableWidget(len(stats), 6)`、`tb.setEditTriggers(no_edit)`。
  - 横ヘッダ: `["パラメータ", "平均", "最大", "最小", "σ", "数"]`。
  - 各行 `for r, (pname, s) in enumerate(stats.items()):`
    - 列0: `str(pname)`。
    - 列1..4: キー順 `["mean", "max", "min", "std"]` を `enumerate(..., start=1)`。値 `v = s.get(k)`。`"-" if v is None else f"{v:.5g}"`。
    - 列5: `str(s.get("count", 0))`。
  - `tb.resizeColumnsToContents()`、`lay.addWidget(tb)`。
- ラベル追加: `QtWidgets.QLabel("■ パラメータ間演算（測定値どうしを四則）")`。
- `vals = {m["name"]: m["value"] for m in meas if m["value"] is not None}`、`names = list(vals.keys())`。
- 行レイアウト `prow = QtWidgets.QHBoxLayout()`:
  - `ca = QtWidgets.QComboBox(); ca.addItems(names)`。
  - `op = QtWidgets.QComboBox(); op.addItems(["+", "-", "×", "÷"])`（演算子は全角 ×/÷）。
  - `cb = QtWidgets.QComboBox(); cb.addItems(names)`。
  - `out = QtWidgets.QLabel("= ?")`。
- ネスト関数 `def compute():`
  - `a = vals.get(ca.currentText()); b = vals.get(cb.currentText())`、`o = op.currentText()`。
  - `try:` 辞書ディスパッチ `{"+": a+b, "-": a-b, "×": a*b, "÷": (a/b if b else float("nan"))}[o]`、`out.setText(f"= {r:.6g}")`。
  - `except Exception:` → `out.setText("= -")`。
- `bcalc = QtWidgets.QPushButton("計算"); bcalc.clicked.connect(compute)`。
- prow へ `ca, op, cb, bcalc, out` を addWidget（out は stretch=1: `prow.addWidget(out, 1)`）。`lay.addLayout(prow)`。
- `bclose = QtWidgets.QPushButton("閉じる"); bclose.clicked.connect(dlg.close)`、`lay.addWidget(bclose)`。
- `self._param_stats_window = dlg`（GC 回避のため属性保持）、`dlg.show()`（モードレス）。

### 3.7 `def compute_fft_metrics(self):`

- 局所 import numpy。`t, y, label = self._analysis_xy()`。`t is None` なら情報「解析対象の系列を選択してください。」で return。
- `win = self.fft_window.currentText()`、`yv = np.asarray(y, float)`。
- `m = analysis.spectrum_metrics(t, yv, window=win)`。
- `rows` を **この順序・この表示名・この単位** で構築:
  1. `("基本波 f0", m.get("f0"), "Hz")`
  2. `("THD", m.get("THD_pct"), "%")`
  3. `("THD", m.get("THD_dB"), "dB")`
  4. `("SNR", m.get("SNR_dB"), "dB")`
  5. `("SINAD", m.get("SINAD_dB"), "dB")`
  6. `("ENOB", m.get("ENOB_bits"), "bit")`
  7. `("SFDR", m.get("SFDR_dB"), "dB")`
  8. `("占有帯域幅(99%)", analysis.occupied_bandwidth(t, yv, window=win), "Hz")`
  9. `("チャネル電力(全)", analysis.channel_power(t, yv, window=win), "V²")`（単位は全角上付き `V²`）
- 続けて高調波: `for h in analysis.harmonic_search(t, yv, n_harm=5, window=win): rows.append((f"第{h['harmonic']}高調波", h["frequency"], "Hz"))`。
- テーブル更新: `self.fft_metrics.setRowCount(len(rows))`。各行 `for r, (name, val, unit) in enumerate(rows):`
  - 列0: `QTableWidgetItem(name)`。
  - 列1: `txt = "-" if val is None else f"{val:.4g} {unit}"`（値と単位を空白区切り）。
- `self._set_status(f"スペクトル指標を計算: {label}")`。

### 3.8 `def show_spectrogram(self):`

- 局所 import numpy。`_analysis_xy` ガード（情報メッセージ同文）。
- `f, tt, S = analysis.spectrogram(t, np.asarray(y, float), window=self.fft_window.currentText())`。
- `S is None` なら warning（タイトル「スペクトログラム」, 本文「計算できませんでした。」）で return。
- `self._reset_figure_axes()`、`self.ax.clear()`。
- `self.ax.set_facecolor("white")`、`self.ax.tick_params(colors="black")`。
- `mesh = self.ax.pcolormesh(tt, f, S, shading="auto", cmap="viridis")`。
- 軸ラベル: xlabel `"時間 [s]"`, ylabel `"周波数 [Hz]"`, title `f"スペクトログラム: {label}"`。
- カラーバー: `try: self.fig.colorbar(mesh, ax=self.ax, label="dB") except Exception: pass`。
- `self._apply_aspect()`（コメント「縦横比の設定をスペクトログラムにも適用」）。
- `try: self.fig.tight_layout() except Exception: pass`。
- `self.canvas.draw()`。
- `self._has_drawn = False`（コメント「カラーバー付き特殊表示。次のdrawで作り直す」）。
- `self._set_status(f"スペクトログラム表示: {label}")`。

### 3.9 `def run_mask_test(self):`

- 局所 import numpy。`_analysis_xy` ガード（同文）。
- `up = plotter.parse_eng(self.mask_upper.text(), None)`、`lo = plotter.parse_eng(self.mask_lower.text(), None)`。
- `up is None and lo is None` なら情報「上限または下限を入力してください。」で return。
- `res = advanced.mask_test(t, np.asarray(y, float), upper=up, lower=lo)`。
- `self.draw_graph()`（通常グラフを描いた上にマスクを重畳）。
- `up is not None` なら `self.ax.axhline(up, color="#d00", ls="--", lw=0.8)`。`lo` も同様（同色・同スタイル）。
- `res["violations"]` が真なら違反点を重畳: `vt = res["violation_times"]`、`yv = np.asarray(y, float)[res["mask"]]`、`self.ax.plot(vt, yv, ".", color="#d00", ms=3)`。
- `self.canvas.draw()`。
- `verdict = "PASS ✅" if res["passed"] else f"FAIL ❌（{res['violations']}点 超過）"`（絵文字 ✅ / ❌、全角括弧）。
- `self.adv_result.setText(f"マスク判定: {verdict}")`、`self._set_status(f"マスク判定 {label}: {verdict}")`。

### 3.10 `def show_eye_diagram(self):`

- 局所 import numpy。`_analysis_xy` ガード（同文）。
- `val = plotter.parse_eng(self.eye_rate.text(), 1e6)`。
- シンボル周期の解釈（コメント「シンボルレート[Hz] と解釈（>1 ならレート、<1 なら周期[s]とみなす）」）:
  `sym_period = (1.0 / val) if val and val > 1 else (val or 1e-6)`。
- `phase, yy = advanced.eye_diagram(t, np.asarray(y, float), sym_period, n_ui=2)`。
- `self._reset_figure_axes()`、`self.ax.clear()`、facecolor white・tick black。
- 散布: `self.ax.plot(phase * 1e6, yy, ".", ms=0.5, alpha=0.3, color="#1f77b4")`（横軸はマイクロ秒に換算）。
- xlabel `"UI内時間 [µs]"`（µ はマイクロ記号）、ylabel `"電圧"`、title `f"アイダイアグラム: {label}"`。
- `self.ax.grid(True, alpha=0.3)`（**linewidth は渡さない**）。
- `em = advanced.eye_measurements(t, np.asarray(y, float), sym_period)`。
- `em` が真なら:
  - `self.ax.axhline(em["level1"], color="#2ca02c", ls=":", lw=0.9)` と `em["level0"]` 同様（緑点線）。
  - ネスト関数 `def _g(k): v = em.get(k); return float("nan") if v is None else v`。
  - `self.adv_result.setText(...)` を次の **書式・順序** で:
    `"アイ測定: 振幅={:.4g} 高さ={:.4g} 幅={:.4g}µs Q={:.3g} ER={:.3g}dB ジッタpp={:.3g}ns".format(_g("eye_amplitude"), _g("eye_height"), _g("eye_width") * 1e6, _g("q_factor"), _g("extinction_ratio_db"), _g("jitter_pp") * 1e9)`
    （幅は ×1e6 で µs、ジッタは ×1e9 で ns 表示）。
- `try: self.fig.tight_layout() except Exception: pass`、`self.canvas.draw()`、`self._has_drawn = False`。
- `self._set_status(f"アイダイアグラム表示: {label}")`。

### 3.11 `def run_jitter(self):`

- 局所 import numpy。`_analysis_xy` ガード（同文）。
- `jr = advanced.jitter_tie(t, np.asarray(y, float))`。
- `not jr` なら warning（タイトル「ジッタ」, 本文「エッジが不足し計算できませんでした。」）で return。
- メッセージ（複数行連結。`plotter.format_eng` で工学表記）:
  `f"ジッタ: RMS={plotter.format_eng(jr['rms'])}s  pp={plotter.format_eng(jr['pp'])}s  クロック≈{plotter.format_eng(jr['freq'])}Hz  エッジ{jr['edges']}本"`
  （区切りは半角スペース2個。`≈` 使用）。
- `self.adv_result.setText(msg)`、`self._set_status(msg)`。

### 3.12 `def show_cycle_stats(self):`

- 局所 import numpy。`_analysis_xy` ガード（同文）。
- `cm = analysis.cycle_measurements(t, np.asarray(y, float))`。
- `fs = analysis.measurement_stats(cm["freq"])`、`amps = analysis.measurement_stats(cm["vpp"])`。
- `lines = []`。
- `fs["count"]` が真なら:
  `f"周波数: 平均{plotter.format_eng(fs['mean'])}Hz σ={plotter.format_eng(fs['std'])} min{plotter.format_eng(fs['min'])}〜max{plotter.format_eng(fs['max'])} ({fs['count']}サイクル)"` を追加（`〜` は全角波ダッシュ）。
- `amps["count"]` が真なら:
  `f"Vpp: 平均{amps['mean']:.4g} σ={amps['std']:.3g} min{amps['min']:.4g}〜max{amps['max']:.4g}"` を追加。
- `self.adv_result.setText("　".join(lines) or "サイクルを検出できませんでした。")`（**結合区切りは全角スペース `　`**）。
- `self._set_status(f"サイクル統計: {label}")`。

### 3.13 `def show_trend(self):`

- 局所 import numpy。`_analysis_xy` ガード（同文）。
- `cm = analysis.cycle_measurements(t, np.asarray(y, float))`。
- `len(cm["cycle_time"]) < 2` なら warning（タイトル「トレンド」, 本文「サイクルが不足しています。」）で return。
- `self._reset_figure_axes()`、`self.ax.clear()`、facecolor white・tick black。
- `self.ax.plot(cm["cycle_time"], cm["freq"], "-o", ms=3, color="#1f77b4")`。
- xlabel `"時間 [s]"`, ylabel `"周波数 [Hz]"`, title `f"周波数トレンド（サイクルごと）: {label}"`。
- `self.ax.grid(True, alpha=0.3)`。
- `try: self.fig.tight_layout() except Exception: pass`、`self.canvas.draw()`、`self._has_drawn = False`。
- `self._set_status(f"トレンド表示: {label}")`。

### 3.14 `def show_phase(self):`

- 局所 import numpy。
- `t1, y1, l1 = self._analysis_xy()`。`t2, y2 = self._xy_by_disp(self.phase_target2.currentText())`。
- `t1 is None or t2 is None` なら情報「解析対象と対象2を選択してください。」で return。
- `delay, phase = analysis.phase_delay(t1, np.asarray(y1, float), np.asarray(y2, float))`。
- `delay is None` なら warning（タイトル「位相差」, 本文「計算できませんでした。」）で return。
- `ph = "-" if phase is None else f"{phase:.1f}°"`（度記号 `°`）。
- `msg = f"位相差/遅延（{l1} vs {self.phase_target2.currentText()}）: 遅延={plotter.format_eng(delay)}s  位相={ph}"`。
- `self.adv_result.setText(msg)`、`self._set_status(msg)`。

### 3.15 `def _on_proto_change(self, proto):`

- 設定辞書 `cfg = {...}[proto]`（**この内容を正確に**）:
  - `"UART": (["信号線", "", ""], "ボーレート", "115200")`
  - `"I2C": (["SCL", "SDA", ""], "不使用", "")`
  - `"SPI": (["SCK", "MOSI", "CS(任意)"], "不使用", "")`
- `labels, baud_lbl, baud_val = cfg`。
- `for i in range(3):` 各チャンネル:
  - `show = labels[i] != ""`。
  - `self.proto_ch_labels[i].setText(labels[i])`、`self.proto_ch_labels[i].setVisible(show)`、`self.proto_ch[i].setVisible(show)`（空ラベルのチャンネルは非表示）。
- `self.proto_baud.setEnabled(proto == "UART")`（UART のみボーレート有効）。
- `if baud_val: self.proto_baud.setText(baud_val)`。

### 3.16 `def decode_protocol(self):`

- 局所 import numpy。
- `proto = self.proto_combo.currentText()`。
- `t1, y1 = self._xy_by_disp(self.proto_ch[0].currentText())`。`t1 is None` なら情報「Ch1（信号線）をデータタブで選択してください。」で return。
- `try:` プロトコル別分岐:
  - **UART**: `baud = plotter.parse_eng(self.proto_baud.text(), 115200)`、`ev = advanced.decode_uart(t1, np.asarray(y1, float), baud=baud)`。
    `rows = [(e["time"], "data", e["hex"], (e["char"] + ("" if e["ok"] else " ⚠")).strip()) for e in ev]`（パリティ等 NG なら char 末尾に ` ⚠` を付け strip）。
  - **I2C**: `t2, y2 = self._xy_by_disp(self.proto_ch[1].currentText())`。`t2 is None` なら情報「SDA(Ch2)も選択してください。」で return。`ev = advanced.decode_i2c(t1, np.asarray(y1, float), np.asarray(y2, float))`。
    `rows = []`。各 `e`:
    - `e["type"] in ("START", "STOP")` → `rows.append((e["time"], e["type"], "", ""))`。
    - else → `rows.append((e["time"], e["type"], e["hex"], f"{e.get('rw','')} {e.get('ack','')}".strip()))`。
  - **else（SPI）**: `t2, y2 = self._xy_by_disp(self.proto_ch[1].currentText())`。`t2 is None` なら情報「MOSI(Ch2)も選択してください。」で return。
    CS 任意: `cs = None`。`if self.proto_ch[2].currentText():` → `_, cs = self._xy_by_disp(self.proto_ch[2].currentText())`、`cs = np.asarray(cs, float) if cs is not None else None`。
    `ev = advanced.decode_spi(t1, np.asarray(y1, float), np.asarray(y2, float), cs=cs)`。
    `rows = [(e["time"], "data", e["hex"], "") for e in ev]`。
- `except Exception as e:` → critical（タイトル「解読エラー」, 本文 `str(e)`）で return。
- テーブル更新: `self.proto_table.setRowCount(len(rows))`。各 `for r, (tm, kind, hexv, note) in enumerate(rows):`
  - 列0: `f"{tm*1e3:.4g} ms"`（時刻を ms 表示）。
  - 列1: `str(kind)`。
  - 列2: `str(hexv)`。
  - 列3: `str(note)`。
- `self._set_status(f"{proto} 解読: {len(rows)} 件")`。

---

## 4. 定数・データ・UI 文字列（正確な値）

- 単項でパラメータが必要な演算名（`_on_math_op_change`）: `("移動平均", "ローパス(RC)", "ローパス(Butterworth)", "ハイパス(Butterworth)")`。
- パラメータ統計テーブルのヘッダ: `["パラメータ", "平均", "最大", "最小", "σ", "数"]`、列数 6。統計キー順 `["mean", "max", "min", "std"]`、count は `s.get("count", 0)`。書式 `{:.5g}`。
- パラメータ間演算の演算子: `["+", "-", "×", "÷"]`。割り算は分母 0 で `float("nan")`。結果書式 `{:.6g}`。
- FFT 指標テーブルの行（順序・表示名・値キー・単位）は 3.7 の 1〜9 ＋高調波。値書式 `{:.4g}`、None は `"-"`。
- スペクトログラム配色 `cmap="viridis"`、`shading="auto"`、カラーバー label `"dB"`、軸ラベル `"時間 [s]"` / `"周波数 [Hz]"`。
- マスク線色・点色 `#d00`（破線 `--`, lw 0.8）、違反点 `ms=3`。判定文字列 `"PASS ✅"` / `f"FAIL ❌（{n}点 超過）"`。
- アイ: 散布色 `#1f77b4`(ms 0.5, alpha 0.3)、レベル線色 `#2ca02c`(`:`, lw 0.9)。測定書式は 3.10 のフォーマット文字列。
- トレンド/サイクル系の系列色 `#1f77b4`。
- プロトコル設定辞書（`_on_proto_change`）は 3.15 の通り。既定ボーレート文字列 `"115200"`、`decode_uart` の `parse_eng` 既定 `115200`。
- プロトコルテーブルは 4 列（時刻 ms / 種別 / hex / 注記）。時刻書式 `{:.4g} ms`。
- ステータス・ダイアログの日本語文言はすべて本仕様に書いた **そのままの文字列**（句読点・記号・絵文字含む）を使う。
- 数値書式の使い分け: 統計 `.5g` / 演算結果 `.6g` / FFT・Vpp・アイ振幅等 `.4g` / σ・Q・ER `.3g` / 位相 `.1f`。

---

## 5. 再現に必須の細部・落とし穴

- **Mixin 規約**: クラスに `__init__` を持たせない。`from graph_app_common import *` を冒頭に置き、`QtWidgets`/`plotter`/`analysis`/`advanced`/`mathchan` をそこから得る。numpy/pandas は各メソッド内で都度 import（遅延）。
- **Qt6 スコープ付き列挙**: `_show_param_stats_window` の `no_edit` は必ず `QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers`。裸の `NoEditTriggers` は不可。
- **grid に linewidth=None を渡さない**: `grid(True, alpha=0.3)` のみ（linewidth は省く）。`float(None)` クラッシュ回避。
- **monospace 不使用**: matplotlib のラベル/タイトルに `family="monospace"` を付けない（日本語□化け回避）。本ファイルは family 指定なし。
- **カラーバー/特殊描画後は `self._has_drawn = False`**: スペクトログラム・アイ・トレンドで描画した後に必ずセット（次回 `draw_graph` で Figure を作り直させるため）。
- **重複ラベル回避ループ**: `create_math_channel` / `create_math_expr` の `while label in self.datasets:` を必ず実装（`{base} (2)`, `(3)`...）。
- **新規データセット作成時の3点セット**: `self.datasets[label]=DataFrame(...)`、`self.meta[label]={"path":label,"enc":"-","delim":"-"}`、`self._add_file_item(label)` ＋ `self._refresh_columns()` を必ず行う。
- **`_xy_by_disp` の NaN 軸フォールバック**: `np.isnan(t).mean() > 0.5` で `np.arange` 化。X 列名が無いときは `df.iloc[:, 0]`。
- **B 系列の補間**: `create_math_expr` で B 長が A と異なれば `np.interp(ta, tb, yb)`。
- **数式結果のブロードキャスト**: `np.broadcast_to(np.asarray(r, float), ya.shape).astype(float)`（スカラ式でも系列長へ）。
- **`eye_rate` の解釈**: 値 >1 はレート(Hz)→周期は逆数、≤1 は周期(s)、0/None は `1e-6`。
- **例外時メッセージボックスの種別**: 入力不足は `information`（タイトル「情報」）、計算不能は `warning`、演算/数式/解読の失敗は `critical`。タイトル文字列は各メソッド記載のもの。
- **`_on_proto_change` の可視制御**: 空ラベル（I2C/SPI の Ch3 や UART の Ch2/3）は対応するラベルとコンボを `setVisible(False)`。ボーレートは UART のみ enable。
- **テーブル列番号**: パラメータ統計 6 列（0..5）、FFT 指標 2 列（0/1）、プロトコル 4 列（0..3）。インデックスを取り違えないこと。
- **facade 経由呼び出し**: 計算は必ず `analysis.*` / `advanced.*` / `mathchan.*` / `plotter.*` を呼ぶ（自前で再実装しない）。公開名はそのまま。
- **`_param_stats_window` の保持**: モードレスダイアログが即 GC されないよう `self._param_stats_window = dlg` を残す。
