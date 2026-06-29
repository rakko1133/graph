# [23/30] graph_app_mixins/plotting.py の仕様

## 指示（このプロンプトの使い方）

- この仕様だけを読んで、`graph_app_mixins/plotting.py` を **完全な形** で実装し出力すること。
- `pass` だけの空実装、`# TODO`、`...`、「省略」「以下同様」などの要約・手抜きは **一切禁止**。すべてのメソッドを中身まで実装する。
- 出力が長くて途中で切れた場合は、ユーザーが「続き」と言ったら、続きを **最後まで** 出力する（重複や再要約をせず、切れた箇所から継続）。
- 本ファイルは GUI アプリ「グラフ」を構成する 30 ファイル中の 23 番目。`PlotMixin` という **単一クラス** を定義する Mixin モジュールである。

## アプリ全体の前提（このファイルに関係する分のみ）

- Python 3.10+ / GUI は PySide6(Qt6)。ただし Qt は **必ず matplotlib 経由** で取得する。本ファイルでは直接 import せず、後述の `from graph_app_common import *` を通じて `QtCore` / `QtWidgets` を使う。
- Qt6 の列挙は **スコープ付き** で書く。本ファイルで使うのは次の 2 つ:
  - `QtCore.Qt.CursorShape.WaitCursor`（待機カーソル）
  - `QtWidgets.QMessageBox.information` / `QtWidgets.QMessageBox.critical`（メッセージボックス）
- `GraphApp` は 10 個の Mixin ＋ `QtWidgets.QMainWindow` の多重継承で構成される。`PlotMixin` はその 1 つ。
  - **Mixin 規約**: 本クラスは `__init__` を **持たない**。`from graph_app_common import *` で始まる「メソッド束」である。
  - 本クラスのメソッドは `self.datasets` / `self.ax` / `self.fig` / `self.canvas` / 各種ウィジェット（後述）など、`GraphApp.__init__` 側で生成される属性・状態に依存する。これらは本ファイルでは生成せず、`self.` 経由で参照するだけ。
  - `@staticmethod` のメソッドは **装飾ごと本クラス内に置く**（後述の `_field_float` / `_has_nonpositive`）。
- `plotter` は facade モジュール。本ファイルでは `plotter.CHART_INFO` / `plotter.parse_eng` / `plotter.plot_series` / `plotter.decimate_minmax` を使う（実体は `plotting_core` 等にあるが、`plotter.` 名で公開されている前提で参照する）。
- 再描画は **デバウンス（QTimer 単発 `self._redraw_timer`）＋再入防止（`self._drawing`）＋構築/復元中の抑止（`self._suspend_redraw`）＋初回描画済みフラグ（`self._has_drawn`）** で制御する。
- 日本語テキストに `family="monospace"` を **使わない**（□文字化け回避）。本ファイルの注記・プレースホルダはフォント family を指定しない。
- grid の `linewidth` に `None` を渡さない（`plot_series` 側に値を渡す。本ファイルは `grid_width.value()` 等の数値を渡す）。

---

## ファイルの役割・責務

モジュール先頭の docstring は次の趣旨（日本語）にする:

> `PlotMixin`: `GraphApp` から分離した `PlotMixin` 群（挙動は本体と同一）。

責務は「グラフ描画パイプラインそのもの」。具体的には:

1. **再描画スケジューリング**（デバウンス／ライブ更新）。
2. **チャート種別変更時の UI 連動**（ヒント表示・有効/無効切り替え・系列バー再構築）。
3. **系列データ構造の構築**（`self.datasets`（pandas DataFrame 群）から `plotter.plot_series` に渡す `series`/`categories` を組み立てる）。
4. **描画書式 kwargs の一元集約**（画面描画と一括出力で同じ設定を使う）。
5. **メイン描画処理 `draw_graph` / `_draw_graph_body`**（バリデーション、オシロ表示、対数の非正値警告、大容量間引き、busy カーソル、注記、縦横比固定、目盛り間隔、tight_layout、canvas 更新、ステータス表示）。
6. **ズーム時の動的再サンプル**（表示範囲だけ min/max 間引きで再描画）。
7. **プレースホルダ描画**・**ステータス更新**・**figure 軸リセット**などの補助。

このファイル自身は scipy も Qt も直接 import せず、numpy / pandas は **メソッド内で遅延 import** する（モジュール先頭では import しない）。

---

## 依存（import するもの）

- モジュール先頭: `from graph_app_common import *  # noqa: F401,F403` の **1 行のみ**。
  - これにより `QtCore` / `QtWidgets`、`plotter`、`_parse_float`、定数 `DECIMATE_TARGET`（=8000）/ `BUSY_ROWS`（=200000）が名前空間に入る前提。
- 先頭行に `# -*- coding: utf-8 -*-`、その下に docstring。
- `numpy as np` / `pandas as pd`、および `matplotlib.ticker.MultipleLocator` は **使うメソッドの内部で import**（先頭では import しない）。

`self.` 経由で参照する `GraphApp` 側の属性・メソッド（本ファイルでは定義しないが利用する。実装時はそのまま呼ぶ）:

- 状態フラグ: `self._suspend_redraw`, `self._has_drawn`, `self._drawing`, `self._resampling`, `self._dyn`, `self._dyn_cid`
- タイマー: `self._redraw_timer`, `self._resample_timer`
- matplotlib: `self.fig`, `self.ax`, `self.canvas`
- データ: `self.datasets`（`{ファイル名: DataFrame}`）, `self.series_styles`（`{style_key: dict}`）
- ヘルパ（他 Mixin / common 由来）: `self._selected_series_items()`, `self._style_key(fl, col)`, `self._series_label(fl, col)`, `self._x_values(df)`, `self._use_leftmost_x()`, `self._update_x_combo_enabled()`, `self._rebuild_series_bar(ctype)`, `self._effective_x_label()`, `self._effective_y_label()`, `self._peak_markers()`, `self._build_style_artist_map(series, ctype, decimated)`, `self._draw_ds_annotations` が使う `self._ds_annotations` / `self._meas_annotations`
- ウィジェット（後述「参照ウィジェット一覧」）

---

## 公開クラス・メソッド一覧（完全シグネチャ＋挙動）

すべて `class PlotMixin:` のメソッド。順序も下記のとおりにする。

### `def _request_redraw(self, *args):`
- docstring: 「リアルタイム更新ON・描画済みのときだけ、デバウンスして再描画予約。」
- 動作:
  - `self._suspend_redraw` が真、または `self._has_drawn` が偽なら即 `return`。
  - `getattr(self, "live_check", None)` が無い、または `self.live_check.isChecked()` が偽なら `return`。
  - それ以外は `self._redraw_timer.start(180)`（180ms デバウンス）。
- 戻り値なし。`*args` はシグナル接続から呼ばれても引数を捨てるため。

### `def _do_live_redraw(self):`
- `self.datasets` があり、かつ `self._has_drawn` が真なら `self.draw_graph()` を呼ぶ。
- デバウンスタイマー `self._redraw_timer` の `timeout` から呼ばれる想定。

### `def _on_chart_type_change(self, *_):`
- チャート種別コンボ変更時の UI 連動。
- `ctype = self.chart_combo.currentText()`。
- `info = plotter.CHART_INFO.get(ctype, {})`。
- `self.hint_label.setText("➤ " + info.get("hint", ""))`（**先頭は全角矢印「➤」＋半角スペース**）。
- `self._update_x_combo_enabled()` を呼ぶ。
- `self.bins_spin.setEnabled(ctype == "ヒストグラム")`。
- `self.bins_caption.setEnabled(ctype == "ヒストグラム")`。
- `self.pct_check.setEnabled(ctype == "円")`。
- `hasattr(self, "series_bar")` の場合のみ `self._rebuild_series_bar(ctype)`（コメント趣旨: 折れ線/散布図でのみ上部バーを出す）。

### `def _build_series(self, chart_type):`
- 役割: `chart_type` 種別に応じ、`plotter.plot_series` 用の `series`（dict のリスト）と `categories`（カテゴリ軸の値 or `None`）を構築して `return series, categories`。
- `info = plotter.CHART_INFO[chart_type]`（取得するが分岐自体は文字列比較で行う）。
- `items = self._selected_series_items()`。`items` が空なら `raise ValueError("Y軸（値）の系列を選択してください。")`。
- `items` の各要素は **`(fl, col, disp)` の 3 タプル**（ファイル名 / 列名 / 表示名）。
- `xname = self.x_combo.currentText()`。`categories = None`、`series = []`。
- ローカル関数 `def lbl(fl, col, disp, default):` を定義:
  - `st = self.series_styles.get(self._style_key(fl, col)) or {}`
  - `return st.get("label") or default`
- 分岐:
  - **`chart_type in ("棒", "横棒", "積み上げ棒", "円")`**（カテゴリ系・単一ファイル）:
    - `src = items[0][0]`（最初に選んだ系列のファイル）。`df = self.datasets[src]`。
    - `if not self._use_leftmost_x() and xname not in df.columns:` → `raise ValueError(f"X軸の列『{xname}』が『{src}』にありません。")`
    - `categories = self._x_values(df)`。
    - `items` を走査し、`fl != src` の要素は `continue`（=同一ファイルの系列だけ採用）。採用要素は dict を append:
      - `"label": lbl(fl, col, disp, col)`
      - `"y": self.datasets[fl][col].to_numpy()`
      - `"style": self.series_styles.get(self._style_key(fl, col))`
  - **`chart_type in ("折れ線", "散布図")`**（数値X・複数ファイル可）:
    - `items` の各 `(fl, col, disp)`:
      - `df = self.datasets[fl]`、`xv = self._x_values(df)`。
      - `stmap = self.series_styles.get(self._style_key(fl, col)) or {}`
      - `errcol = stmap.get("errcol")`
      - `yerr = df[errcol].to_numpy() if (errcol and errcol in df.columns) else None`
      - append する dict:
        - `"label": self._series_label(fl, col)`
        - `"x": xv`
        - `"y": df[col].to_numpy()`
        - `"style": stmap`
        - `"axis": stmap.get("axis", "primary")`
        - `"kind": stmap.get("kind", "")`
        - `"yerr": yerr`
  - **それ以外**（ヒストグラム / 箱ひげ）:
    - `items` の各 `(fl, col, disp)`:
      - `"label": self._series_label(fl, col)`
      - `"y": self.datasets[fl][col].to_numpy()`
      - `"style": self.series_styles.get(self._style_key(fl, col))`
- 注意: dict のキー名・既定値（`"primary"` / 空文字 `""`）・`yerr` の生成条件を **そのまま** 再現すること。

### `def _scope_dict(self):`
- オシロ（スコープ）表示設定を dict で返す。キーと値:
  - `"enabled": self.scope_check.isChecked()`
  - `"t_per_div": plotter.parse_eng(self.tdiv.currentText(), 1e-3)`
  - `"v_per_div": plotter.parse_eng(self.vdiv.currentText(), 1.0)`
  - `"x_pos": _parse_float(self.xpos.text(), 0.0)`
  - `"y_pos": _parse_float(self.ypos.text(), 0.0)`
  - `"x_divs": self.xdivs.value()`
  - `"y_divs": self.ydivs.value()`
- `parse_eng` は工学接頭辞付き文字列を float に変換（第2引数は既定値）。`t_per_div` の既定 `1e-3`、`v_per_div` の既定 `1.0`。

### `def _fonts(self):`
- フォントサイズ群の dict を返す。キーと値:
  - `"title": self.fs_title.value()`
  - `"label": self.fs_label.value()`
  - `"tick": self.fs_tick.value()`
  - `"legend": self.fs_legend.value()`
  - `"annot": self.fs_annot.value()`

### `def _on_aspect_changed(self, *_):`
- `custom = self.aspect_combo.currentText() == "カスタム"`。
- `self.aspect_w.setEnabled(custom)` / `self.aspect_h.setEnabled(custom)`。
- 最後に `self._request_redraw()`。

### `def _aspect_ratio(self):`
- docstring: 「選択中の縦横比から box aspect（高さ/幅）を返す。自動は None。」
- `t = self.aspect_combo.currentText()`。
- プリセット辞書（**値そのまま**）:
  ```
  presets = {"16:9": (16, 9), "4:3": (4, 3), "3:2": (3, 2), "1:1": (1, 1),
             "9:16（縦）": (9, 16), "A4横": (297, 210), "A4縦": (210, 297)}
  ```
- `t in presets` なら `w, h = presets[t]`。
- `elif t == "カスタム"` なら `w, h = self.aspect_w.value(), self.aspect_h.value()`。
- それ以外（=自動）は `return None`。
- 末尾: `return (h / w) if w else None`（**高さ/幅**。`w` が 0 のときは None でゼロ除算回避）。

### `def _apply_aspect(self):`
- docstring: 「プロット領域の縦横比を固定（None で解除）。第2軸にも適用。画面プレビュー用。」
- `ratio = self._aspect_ratio()`。
- `try:` ブロック内で:
  - `self.ax.set_box_aspect(ratio)`
  - `ax2 = getattr(self.ax, "_twin_secondary", None)`; `ax2 is not None` なら `ax2.set_box_aspect(ratio)`。
- `except Exception: pass`（失敗は握りつぶす）。

### `def _export_figsize(self, base=7.0):`
- docstring: 「出力画像のサイズ(インチ)。選択比率があれば画像そのものをその比率にする。自動なら現在の図サイズ。ratio は高さ/幅。」
- `ratio = self._aspect_ratio()`。
- `ratio` が falsy（None/0）なら `return tuple(self.fig.get_size_inches())`。
- `ratio <= 1.0`（横長）: `return (base, base * ratio)`（幅を `base` に固定）。
- それ以外（縦長）: `return (base / ratio, base)`（高さを `base` に固定）。

### `@staticmethod` `def _field_float(le):`
- docstring: 「QLineEdit を (値 or None, 妥当か) で返す。空欄は (None, True)。」
- `t = le.text().strip()`。空文字なら `return None, True`。
- `try: return float(t), True` / `except ValueError: return None, False`。
- **戻り値は 2 要素タプル `(値 or None, 妥当フラグ bool)`**。

### `def _range_pair(self, le_min, le_max, name, issues):`
- 2 つの QLineEdit から min/max を読み、範囲タプル `(vmin, vmax)` を返す。問題があれば `issues`（リスト）に日本語メッセージを追記。
- `vmin, ok1 = self._field_float(le_min)`、`vmax, ok2 = self._field_float(le_max)`。
- `not ok1` → `issues.append(f"{name}軸 最小値を数値として読めません")`。
- `not ok2` → `issues.append(f"{name}軸 最大値を数値として読めません")`。
- `vmin is not None and vmax is not None and vmin >= vmax` → `issues.append(f"{name}軸 最小≥最大のため範囲指定を無視しました")` し、`return (None, None)`。
- 最後 `return (vmin, vmax)`。
- `name` には `"X"` / `"Y"` が渡る（メッセージは「X軸 最小値…」等）。

### `@staticmethod` `def _has_nonpositive(arrays):`
- 配列群の中に **0 以下の有限値が 1 つでもあれば `True`** を返す（対数軸の警告判定用）。
- メソッド冒頭で `import numpy as np` / `import pandas as pd`。
- `for a in arrays:`：`a is None` は `continue`。
  - `v = pd.to_numeric(pd.Series(a), errors="coerce").to_numpy(dtype=float)`
  - `v = v[np.isfinite(v)]`
  - `if v.size and v.min() <= 0: return True`
- ループ後 `return False`。

### `def _plot_format_kwargs(self):`
- docstring: 「draw_graph と batch_export で共通の描画フォーマット設定を1か所に集約。新しい書式オプションはここに足せば両方（画面描画／一括出力）へ自動反映される。」
- `dict(...)` を返す。**キー名・取得元ウィジェット・既定処理を完全再現**:
  - `bins=self.bins_spin.value()`
  - `grid=self.grid_check.isChecked()`
  - `legend=self.legend_check.isChecked()`
  - `legend_loc=self.legend_loc.currentText()`
  - `xlog=self.xlog.isChecked()`, `ylog=self.ylog.isChecked()`
  - `pct=self.pct_check.isChecked()`
  - `fonts=self._fonts()`
  - `trendline={"type": self.trend_combo.currentText(), "degree": self.trend_degree.value(), "window": self.trend_window.value(), "show_eq": self.trend_eq.isChecked(), "color": getattr(self, "trend_color", "") or ""}`
  - `data_labels=self.data_labels_check.isChecked()`
  - `xscale=_parse_float(self.xscale_edit.text(), 1.0) or 1.0`
  - `yscale=_parse_float(self.yscale_edit.text(), 1.0) or 1.0`
  - `xunit=self.xunit_edit.text().strip()`
  - `yunit=self.yunit_edit.text().strip()`
  - `bg_color=getattr(self, "bg_color", "") or ""`
  - `grid_width=self.grid_width.value()`
  - `frame_width=self.frame_width.value()`
- 注: `xscale`/`yscale` は「`_parse_float(...) or 1.0`」で **0 や None を 1.0 に正規化**。`trend_color`/`bg_color` は属性が無い場合に `""`。

### `def draw_graph(self):`
- 再入防止ラッパ。コメント趣旨（そのまま入れる）: busy 描画中の `processEvents()` からデバウンス再描画が割り込むと軸が中途半端なまま再描画され不正なアーティストが残るため、1 回に直列化する。
- `if getattr(self, "_drawing", False): return`。
- `self._drawing = True`、`try: self._draw_graph_body()`、`finally: self._drawing = False`。

### `def _draw_graph_body(self):`
- メイン描画本体。手順を **この順序で** 実装する:
  1. `if not self.datasets:` → `QtWidgets.QMessageBox.information(self, "情報", "先にファイルを追加してください。")` して `return`。
  2. Y 系列未選択は正常な一時状態。`if not self._selected_series_items():`:
     - `self._draw_placeholder()`
     - `self._rebuild_series_bar(self.chart_combo.currentText())`
     - `self._set_status("Y軸（値）の系列をチェックするとグラフを表示します。")`
     - `return`
  3. `ctype = self.chart_combo.currentText()`。`issues = []`。
  4. `xlim = self._range_pair(self.xmin, self.xmax, "X", issues)`、`ylim = self._range_pair(self.ymin, self.ymax, "Y", issues)`。
  5. `scope = self._scope_dict()`。オシロ有効かつ `ctype in ("折れ線", "散布図")` のとき、`t_per_div`/`v_per_div` が **正の値でなければ**:
     - 条件: `not (scope["t_per_div"] and scope["t_per_div"] > 0 and scope["v_per_div"] and scope["v_per_div"] > 0)`
     - `issues.append("time/div・V/div は正の値が必要（オシロ表示を無効化）")`
     - `scope = dict(scope, enabled=False)`
  6. 再描画前のクリア:
     - `self._clear_dynamic_resample()`
     - `self._reset_figure_axes()`（コメント: スペクトログラム等のカラーバー軸を除去）
     - `self._cursor_pts = []; self._cursor_artists = []`（コメント: 再描画で軸がクリアされる）
     - `self._cursors = []; self._cursor_drag = None; self._cursor_text = None`
  7. **`try:` 大ブロック**（最後の `except Exception as e:` で `QtWidgets.QMessageBox.critical(self, "描画エラー", str(e))`、`# noqa: BLE001`）:
     - `series, categories = self._build_series(ctype)`
     - 対数の非正値警告:
       - `if self.ylog.isChecked() and self._has_nonpositive([s["y"] for s in series]):` → `issues.append("Y対数: 0以下の値は表示されません")`
       - `if (self.xlog.isChecked() and ctype in ("折れ線", "散布図") and self._has_nonpositive([s.get("x") for s in series])):` → `issues.append("X対数: 0以下の値は表示されません")`
     - 間引き判定（折れ線/散布図のみ）:
       - `total = sum(len(s.get("y", [])) for s in series)`
       - `max_points = (DECIMATE_TARGET if (self.decimate_check.isChecked() and ctype in ("折れ線", "散布図") and total > DECIMATE_TARGET) else 0)`
     - busy 判定: `busy = total > BUSY_ROWS`。
       - `if busy:` → `QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)`; `self._set_status(f"描画中…（{total:,} 点）")`; `QtWidgets.QApplication.processEvents()`。
     - 内側 `try:`（`finally:` で busy なら `QtWidgets.QApplication.restoreOverrideCursor()`）:
       - `markers = self._peak_markers() if self.show_peaks_check.isChecked() else None`
       - `sec_label = " / ".join(s["label"] for s in series if s.get("axis") == "secondary")`
       - `plotter.plot_series(...)` を以下の引数で呼ぶ:
         - 位置: `self.ax, series, ctype`
         - キーワード: `categories=categories`, `title=self.title_edit.text()`, `xlabel=self.xlabel_edit.text() or self._effective_x_label()`, `ylabel=self.ylabel_edit.text() or self._effective_y_label()`, `xlim=xlim`, `ylim=ylim`, `scope=scope`, `markers=markers`, `max_points=max_points`, `secondary_label=sec_label`, `**self._plot_format_kwargs()`
       - `self._apply_aspect()`（縦横比固定。自動なら解除）
       - `self._apply_tick_spacing(ctype, scope)`（目盛り間隔）
       - `self._draw_ds_annotations()`（DS 注記）
       - `try: self.fig.tight_layout() except Exception: pass`
       - `self.canvas.draw()`
     - busy の `finally` を抜けた後:
       - `if max_points: self._setup_dynamic_resample(series, ctype, max_points)`
       - `self._rebuild_series_bar(ctype)`
       - カーソル追従用に **近似曲線を除いた** 実描画線を保持:
         - `self._plotted_artists = [(ln.get_label(), ln) for ln in self.ax.get_lines() if "近似" not in str(ln.get_label())]`
       - スタイル即時反映マップ: `self._style_artists = self._build_style_artist_map(series, ctype, bool(max_points))`
       - `self._has_drawn = True`
       - ステータス文字列の組み立て:
         - `msg = f"「{ctype}」を描画しました（系列 {len(series)}）。"`
         - `if max_points: msg += f"（{total:,}点を間引き表示）"`
         - `if issues: msg += "  ⚠ " + " / ".join(issues)`（**先頭は半角スペース2個＋警告絵文字「⚠」**）
         - `self._set_status(msg)`

### `def _apply_tick_spacing(self, ctype, scope):`
- docstring: 「目盛り間隔（メモリ間隔）の手動指定を適用する。空欄や非対応（オシロdiv表示中・対数軸・カテゴリ軸・円）では何もしない。」
- `if ctype == "円": return`。
- `if scope.get("enabled") and ctype in ("折れ線", "散布図"): return`（コメント: オシロ表示中は div 目盛りを優先）。
- メソッド内で `from matplotlib.ticker import MultipleLocator`。
- `dx = _parse_float(self.xtick_edit.text())`、`dy = _parse_float(self.ytick_edit.text())`。
- 目盛り数ガード用のローカル関数 `def _too_many(lo, hi, step):` を定義する。間隔が軸範囲に対して小さすぎると数千本の目盛りを生成し matplotlib が MAXTICKS 警告を連発するため、`abs(hi - lo) / step > 1000` のときは適用を見送る（暴走防止）。`try: return abs(hi - lo) / step > 1000 except (ZeroDivisionError, TypeError): return True`。
- X 目盛り適用条件（**数値X限定**）: `if (dx and dx > 0 and ctype in ("折れ線", "散布図") and self.ax.get_xscale() != "log"):`。この内側で `x0, x1 = self.ax.get_xlim()` を読み、`if not _too_many(x0, x1, dx):` のときだけ `try: self.ax.xaxis.set_major_locator(MultipleLocator(dx)) except Exception: pass`。
- Y 目盛り適用条件: `if dy and dy > 0 and self.ax.get_yscale() != "log":`。この内側で `y0, y1 = self.ax.get_ylim()` を読み、`if not _too_many(y0, y1, dy):` のときだけ `try: self.ax.yaxis.set_major_locator(MultipleLocator(dy)) except Exception: pass`。

### `def _draw_ds_annotations(self):`
- docstring: 「『表示』にチェックした指標をグラフへ注記する。データサイエンス＝左上、オシロ/解析の測定値＝右上に分けて描く。」
- `self._draw_annotation_box(getattr(self, "_ds_annotations", None), "tl")`
- `self._draw_annotation_box(getattr(self, "_meas_annotations", None), "tr")`

### `def _draw_annotation_box(self, anns, corner):`
- docstring: 「注記テキストボックスを指定コーナーに描く（注記フォントサイズを使用）。」
- `if not anns: return`。
- `fs = self.fs_annot.value() if hasattr(self, "fs_annot") else 9`。
- コーナー座標辞書（**値そのまま**）:
  ```
  x, y, ha, va = {"tl": (0.02, 0.98, "left", "top"),
                  "tr": (0.98, 0.98, "right", "top")}[corner]
  ```
- `try:` で `self.ax.text(x, y, "\n".join(anns), transform=self.ax.transAxes, ha=ha, va=va, fontsize=fs, zorder=20, bbox=dict(boxstyle="round", facecolor="white", alpha=0.8, edgecolor="#888"))`、`except Exception: pass`。
- **`family` は指定しない**（日本語の monospace 化け回避）。

### `def _reset_figure_axes(self):`
- docstring: 「メイン軸以外（カラーバー等）を図から取り除く。」
- `for a in list(self.fig.axes):`：`a is not self.ax` のものを `try: a.remove() except Exception: pass`。
- コメント趣旨: 系列選択バーの表示/非表示は `_rebuild_series_bar` が管理するのでここでは触らない。

### `def _clear_dynamic_resample(self):`
- `if self._dyn_cid is not None:`：`try: self.ax.callbacks.disconnect(self._dyn_cid) except Exception: pass`、続けて `self._dyn_cid = None`。
- 末尾で `self._dyn = []`（接続有無に関わらずリセット）。

### `def _setup_dynamic_resample(self, series, ctype, max_points):`
- docstring: 「折れ線（数値X）について、間引き元の全データと描画線を保持し、ズーム時に表示範囲だけ再サンプルできるようにする。」
- `if ctype != "折れ線": return`（散布図は対象外）。
- メソッド内で `import numpy as np` / `import pandas as pd`。
- **単位倍率を描画と揃える**: 描画線は単位換算後（x×xscale・主軸yは×yscale）の座標を持つため、保持する `fx`/`fy` にも同じ倍率を掛けてからソート/保存する。掛け忘れるとズーム間引き時に未換算座標へ戻り、曲線が誤った位置・大きさに飛ぶ。先頭で `xscale = _parse_float(self.xscale_edit.text(), 1.0) or 1.0`、`yscale = _parse_float(self.yscale_edit.text(), 1.0) or 1.0` を読む（0/None は 1.0 に正規化）。
- `lines = self.ax.get_lines()`。
- `for i, s in enumerate(series):`：
  - `if i >= len(lines) or s.get("x") is None: continue`。
  - `fx = pd.to_numeric(pd.Series(s["x"]), errors="coerce").to_numpy(dtype=float)`。
  - `if np.isfinite(fx).mean() < 0.8: continue`（**数値Xのみ対象**＝有限値が 8 割未満なら除外）。
  - `fy = pd.to_numeric(pd.Series(s["y"]), errors="coerce").to_numpy(dtype=float)`。
  - 倍率適用: `if xscale != 1.0: fx = fx * xscale`。`if yscale != 1.0 and s.get("axis") != "secondary": fy = fy * yscale`（**Y 換算は主軸系列のみ**＝描画と同じく第2軸の系列には掛けない）。
  - `order = np.argsort(fx)`（倍率適用後の `fx` でソート）。
  - `self._dyn.append((lines[i], fx[order], fy[order], max_points))`（**X 昇順にソートして保持**）。
- ループ後 `if self._dyn: self._dyn_cid = self.ax.callbacks.connect("xlim_changed", self._on_xlim_changed)`。

### `def _on_xlim_changed(self, _ax):`
- `if self._resampling or not self._dyn: return`。
- `self._resample_timer.start(120)`（120ms デバウンス）。

### `def _do_resample(self):`
- `if not self._dyn: return`。
- メソッド内で `import numpy as np`。
- `x0, x1 = self.ax.get_xlim()`。`if x1 < x0: x0, x1 = x1, x0`（反転していたら入替）。
- `margin = (x1 - x0) * 0.05`（表示幅の 5% を余白に）。
- `self._resampling = True`、`try:` / `finally: self._resampling = False`。
- `try` 内: `for line, fx, fy, mp in self._dyn:`
  - `lo = np.searchsorted(fx, x0 - margin)`、`hi = np.searchsorted(fx, x1 + margin)`。
  - `vx, vy = fx[lo:hi], fy[lo:hi]`。`if vx.size == 0: continue`。
  - `dx, dy = plotter.decimate_minmax(vx, vy, mp)`（min/max 間引き）。
  - `line.set_data(dx, dy)`。
- ループ後 `self.canvas.draw_idle()`。

### `def _draw_placeholder(self):`
- データ未追加/系列未選択時の案内表示。
- `self._reset_figure_axes()`。
- `self.ax.clear()`。
- `self.ax.set_facecolor("white")`; `self.ax.tick_params(colors="black")`。
- `self.ax.text(0.5, 0.5, "『データ』タブでファイルを追加し、\n列を選んで「グラフを描画」", ha="center", va="center", fontsize=12, color="#888", transform=self.ax.transAxes)`（**改行入り日本語テキスト。family 指定なし**）。
- `self.ax.set_xticks([])`; `self.ax.set_yticks([])`。
- `self.canvas.draw()`。

### `def _set_status(self, text):`
- `self.status.showMessage(text)`（ステータスバーに表示）。

---

## 参照ウィジェット一覧（`GraphApp` 側で生成される。本ファイルは参照のみ）

実装時はこれらが存在する前提で `self.<name>` を呼ぶ（生成コードは書かない）:

- コンボ: `chart_combo`, `x_combo`, `legend_loc`, `trend_combo`, `aspect_combo`, `tdiv`, `vdiv`
- ラベル/ヒント: `hint_label`, `bins_caption`
- チェックボックス: `live_check`, `grid_check`, `legend_check`, `xlog`, `ylog`, `pct_check`, `trend_eq`, `data_labels_check`, `decimate_check`, `show_peaks_check`, `scope_check`
- スピン（数値）: `bins_spin`, `trend_degree`, `trend_window`, `grid_width`, `frame_width`, `aspect_w`, `aspect_h`, `xdivs`, `ydivs`, フォント `fs_title`/`fs_label`/`fs_tick`/`fs_legend`/`fs_annot`
- ラインエディット: `title_edit`, `xlabel_edit`, `ylabel_edit`, `xmin`, `xmax`, `ymin`, `ymax`, `xtick_edit`, `ytick_edit`, `xscale_edit`, `yscale_edit`, `xunit_edit`, `yunit_edit`, `xpos`, `ypos`
- ステータスバー: `status`
- 任意属性（`getattr` で防御的に取得）: `trend_color`, `bg_color`, `series_bar`, `live_check`, `fs_annot`, `_ds_annotations`, `_meas_annotations`, `_drawing`

---

## 定数・文字列（正確な値）

本ファイルでハードコードされる日本語・記号・数値（**そのまま** 使う）:

- ヒント接頭辞: `"➤ "`（全角矢印＋半角スペース）。
- チャート種別の判定文字列: `"棒"`, `"横棒"`, `"積み上げ棒"`, `"円"`, `"折れ線"`, `"散布図"`, `"ヒストグラム"`, `"箱ひげ"`（実際の分岐は前述のグループ単位）。
- 縦横比プリセットキー: `"16:9"`, `"4:3"`, `"3:2"`, `"1:1"`, `"9:16（縦）"`, `"A4横"`, `"A4縦"`、カスタム判定 `"カスタム"`。
- プリセット値: `(16,9)`,`(4,3)`,`(3,2)`,`(1,1)`,`(9,16)`,`(297,210)`,`(210,297)`。
- 既定値・係数: デバウンス `180`(redraw) / `120`(resample)、`_export_figsize` の `base=7.0`、注記 `zorder=20` / `alpha=0.8` / `edgecolor="#888"` / `boxstyle="round"` / `facecolor="white"`、プレースホルダ `fontsize=12` / `color="#888"`、注記既定 `fs=9`、`parse_eng` 既定 `1e-3`(t)/`1.0`(v)、再サンプル余白 `0.05`、数値X判定閾値 `0.8`、`MultipleLocator` 判定 `> 0`、目盛り数ガード閾値 `|hi-lo|/step > 1000`。
- メッセージ文言（完全一致で再現）:
  - `"先にファイルを追加してください。"`
  - `"Y軸（値）の系列をチェックするとグラフを表示します。"`
  - `"Y軸（値）の系列を選択してください。"`
  - `f"X軸の列『{xname}』が『{src}』にありません。"`
  - `f"{name}軸 最小値を数値として読めません"` / `f"{name}軸 最大値を数値として読めません"` / `f"{name}軸 最小≥最大のため範囲指定を無視しました"`
  - `"time/div・V/div は正の値が必要（オシロ表示を無効化）"`
  - `"Y対数: 0以下の値は表示されません"` / `"X対数: 0以下の値は表示されません"`
  - `f"描画中…（{total:,} 点）"`
  - `f"「{ctype}」を描画しました（系列 {len(series)}）。"`
  - `f"（{total:,}点を間引き表示）"`
  - 警告区切り: `"  ⚠ " + " / ".join(issues)`
  - プレースホルダ: `"『データ』タブでファイルを追加し、\n列を選んで「グラフを描画」"`
  - ダイアログタイトル: `"情報"` / `"描画エラー"`
- モジュール定数（`graph_app_common` 由来。値の前提）: `DECIMATE_TARGET = 8000`、`BUSY_ROWS = 200000`。

---

## 再現に必須の細部・エッジケース・落とし穴

- **再入直列化**: `draw_graph` は `_drawing` ガードで二重描画を防ぐ。`_draw_graph_body` 内の `processEvents()`（busy 時）からデバウンス再描画が割り込んでも、`_request_redraw`→`_do_live_redraw`→`draw_graph` の経路でブロックされる設計。
- **`series` dict のキー差**: 折れ線/散布図だけ `"x"`/`"axis"`/`"kind"`/`"yerr"` を持つ。棒系・ヒスト/箱ひげは `"y"`/`"label"`/`"style"` のみ。`categories` は棒系のみ非 None。
- **`_use_leftmost_x()` 連動**: 棒系で X 列がデータに無くても `_use_leftmost_x()` が真なら例外を出さない。
- **対数警告の片側性**: X 対数警告は折れ線/散布図のときだけ（カテゴリ軸には X 値が無いため）。
- **間引きは折れ線/散布図のみ**かつ `total > DECIMATE_TARGET`かつ `decimate_check` ON のとき `max_points = DECIMATE_TARGET`、それ以外 `0`。動的再サンプル（`_setup_dynamic_resample`）は **折れ線のみ**有効。
- **数値X判定**: `np.isfinite(fx).mean() < 0.8` の系列は再サンプル対象外。保持データは描画と同じ単位倍率（`fx`×xscale・主軸 `fy`×yscale、第2軸 `fy` には掛けない）を適用してから X 昇順ソート（`argsort`）。掛け忘れるとズーム間引き時に未換算座標へ戻る不整合が起きる。
- **目盛り数ガード**: `_apply_tick_spacing` は軸範囲に対し間隔が小さすぎる指定（`|hi-lo|/step > 1000`）では `MultipleLocator` を適用しない（matplotlib の MAXTICKS 暴走防止）。判定不能（ゼロ除算・型不一致）も適用見送り扱い。
- **近似曲線の除外**: `_plotted_artists` は `get_label()` に `"近似"` を含む線を除外（近似曲線をカーソル追従から外す）。
- **`fonts` dict** のキーは `title/label/tick/legend/annot`。`_plot_format_kwargs` のキー名はすべて `plotter.plot_series` の引数名と一致させる（変更不可）。
- **grid linewidth=None 回避**: 本ファイルは `grid_width=self.grid_width.value()`（数値）を渡すだけ。`None` を渡さない。`linewidth` の最終的なガードは `plotter.plot_series` 側にある前提だが、本ファイルでも `None` を生成しない。
- **monospace 回避**: 注記・プレースホルダ・案内の日本語テキストに `family="monospace"` を **付けない**。フォントサイズのみ指定。
- **Qt6 スコープ列挙**: 待機カーソルは `QtCore.Qt.CursorShape.WaitCursor`（旧 `QtCore.Qt.WaitCursor` 不可）。
- **例外握りつぶしの粒度**: `_apply_aspect`/`_apply_tick_spacing`/`_draw_annotation_box`/`_reset_figure_axes`/`tight_layout`/`_clear_dynamic_resample` の disconnect は **個別に try/except** で握りつぶす。一方 `_draw_graph_body` の本体エラーはユーザーに `QMessageBox.critical` で見せる。
- **busy カーソルの確実な復元**: `restoreOverrideCursor` は内側 `try/finally` の `finally` で必ず呼ぶ。
- **Mixin 規約**: `__init__` を定義しない。`@staticmethod` は `_field_float` と `_has_nonpositive` の 2 つだけ（装飾ごと本クラス内）。
- **遅延 import**: `numpy`/`pandas`/`MultipleLocator` はメソッド内 import。モジュール先頭で import すると規約違反（起動時コスト増）。
- **`f"{total:,}"`**: 桁区切り（カンマ）付きで点数を表示する。
