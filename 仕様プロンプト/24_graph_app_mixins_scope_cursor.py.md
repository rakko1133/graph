# [24/30] graph_app_mixins/scope_cursor.py の仕様

## 指示

- この仕様だけを読んで `graph_app_mixins/scope_cursor.py` を**完全な形**で実装し、ファイル全体を出力してください。
- `pass`・`TODO`・`...`・省略・要約・「以下同様」などは**一切禁止**です。すべてのメソッド本体を完全に書き切ってください。
- 出力が長くて途中で切れた場合は、ユーザーが「続き」と言うので、続きから最後まで漏れなく出力してください。

### アプリ全体の前提（関連分のみ）

- Python 3.10+ / GUI は PySide6 (Qt6)。ただし Qt は必ず matplotlib 経由で取得する（このファイルでは直接 import せず、後述の `graph_app_common` 経由で `QtCore` / `QtWidgets` を使う）。
- Qt6 の列挙はスコープ付き。本ファイルでは `QtCore.Qt.KeyboardModifier.ShiftModifier` を使用する。
- `GraphApp` は 10 個の Mixin ＋ `QtWidgets.QMainWindow` の多重継承。各 Mixin は `from graph_app_common import *` で始まり、`__init__` を持たない**メソッド束**である。`@staticmethod` は装飾ごと担当 Mixin に置く（本ファイルには `@staticmethod` が 1 つある）。
- `plotter` は facade モジュールで、本ファイルからは `plotter.format_eng` / `plotter.parse_eng` を使う。
- 再描画は `_suspend_redraw`（構築/復元中に再描画を抑止するフラグ）を使う。本ファイルでも UI ウィジェットへ値を流し込む間は `self._suspend_redraw = True` にして、最後に `self.draw_graph()` を明示的に呼ぶ。
- matplotlib のテキストに `family="monospace"` を**使わない**（日本語グリフを持たず「位置」「中心」等が □ 文字化けするため）。rcParams の日本語フォントに任せる。

---

## ファイルの役割 / 責務

`ScopeCursorMixin` という 1 クラスを定義する Mixin ファイル。`GraphApp` から「オシロスコープ風のドラッグ操作」と「カーソル測定（2 本の縦線で Δt/ΔV を計測）」の機能を分離したもの。挙動は本体に統合されていた頃と同一。

このクラスが提供する機能は大きく 3 系統:

1. **カーソル測定**: matplotlib のキャンバスにクリックで最大 2 本の縦カーソル（vline ＋ マーカー）を置き、波形に追従させ、2 本そろったら Δt / ΔV / 1/Δt(Hz) を画面上部に表示する。
2. **オシロ風ドラッグ操作**: オシロ表示 ON かつ折れ線/散布図のとき、左ドラッグでパン（位置移動）、右ドラッグ or Shift+ドラッグでスケール（time/div・V/div）変更。
3. **マウスホイールズーム**: オシロ表示時は div を増減、それ以外はカーソル位置を中心に通常ズーム（Shift で X 方向のみ）。

モジュール先頭の docstring は概ね「`ScopeCursorMixin: GraphApp から分離した ScopeCursorMixin 群（挙動は本体と同一）。`」という趣旨。

---

## 依存（import するもの）

- ファイル先頭は `# -*- coding: utf-8 -*-` のエンコーディング宣言。
- `from graph_app_common import *  # noqa: F401,F403` の 1 行のみをモジュール先頭で行う。これにより `QtCore` / `QtWidgets` / `plotter` 等が名前空間に入る。
- `numpy as np` / `pandas as pd` は、必要なメソッドの**内部で遅延 import** する（モジュールトップでは import しない）。
  - `_cursor_track_y` 内: `import numpy as np`
  - `_zoom_pair` 内: `import numpy as np`
  - `auto_scale_scope` 内: `import numpy as np` と `import pandas as pd`

この Mixin は `self.canvas` / `self.ax` / `self.toolbar` / `self.datasets` や多数の UI ウィジェット属性（`self.scope_check`, `self.chart_combo`, `self.tdiv`, `self.vdiv`, `self.xdivs`, `self.ydivs`, `self.xpos`, `self.ypos`, `self.x_combo` など）、状態属性（`self._cursors`, `self._cursor_cid`, `self._cursor_drag`, `self._cursor_text`, `self._cursor_artists`, `self._scope_drag`, `self._scope_ov`, `self._plotted_artists`, `self._has_drawn`, `self._suspend_redraw`）、メソッド（`self._set_status`, `self.draw_graph`, `self._selected_series_items`）に依存する。これらは GraphApp 本体や他 Mixin が用意する前提で、本ファイル内では定義しない。

---

## 公開 API（全メソッドの完全シグネチャと挙動）

クラス定義は `class ScopeCursorMixin:`。メソッドは概ね以下の並び順（セクションコメントを含む）。

### セクションコメント
- カーソル測定群の前に「`# ------------------------------------------------------------ カーソル測定`」相当の区切りコメント。
- オシロドラッグ群の前に「`# ------------------------------------------------------ オシロ ドラッグ操作`」相当の区切りコメント。

---

### `def toggle_cursors(self, on):`
カーソル測定モードの ON/OFF を切り替える。
- `on` が真のとき:
  - `self._cursors = []`（最大 2 本。各要素は `{x, vline, marker}` の辞書）、`self._cursor_drag = None`、`self._cursor_text = None` に初期化。
  - `self._clear_cursor_artists()` を呼んで既存アーティストを消す。
  - 3 つの mpl イベントを接続し、その接続 ID のタプルを `self._cursor_cid` に格納:
    - `"button_press_event"` → `self._on_cursor_press`
    - `"motion_notify_event"` → `self._on_cursor_motion`
    - `"button_release_event"` → `self._on_cursor_release`
  - ステータス表示: `self._set_status("カーソル: クリックで2本設置 → 線をドラッグで微調整（波形に追従）")`
- `on` が偽のとき:
  - `self._cursor_cid` があれば、その各接続 ID を `self.canvas.mpl_disconnect(c)` で切断し、`self._cursor_cid = None`。
  - `self._clear_cursor_artists()` を呼ぶ。
  - `self.canvas.draw_idle()` で再描画。
- 戻り値なし。

### `def _clear_cursor_artists(self):`
カーソル関連の matplotlib アーティストをすべて除去する。
- `self._cursor_artists` の各 `a` について `a.remove()` を試み、例外は握りつぶす（`try/except Exception: pass`）。
- その後 `self._cursor_artists = []`、`self._cursors = []`、`self._cursor_text = None` に戻す。

### `def _cursor_track_y(self, x):`
「最初に描画した線の x における y を補間してカーソルを波形に追従させる」ための補間値を返す。
- `self._plotted_artists` が空なら `0.0` を返す。
- それ以外は `try`:
  - `import numpy as np`
  - `line = self._plotted_artists[0][1]`（`_plotted_artists` は `(なにか, Line2D)` のタプル列で、index 1 が Line オブジェクト）
  - `xd = np.asarray(line.get_xdata(), float)`、`yd = np.asarray(line.get_ydata(), float)`
  - `order = np.argsort(xd)` で x 昇順の並び替えインデックスを得る
  - `return float(np.interp(x, xd[order], yd[order]))`
- `except Exception:` のときは `0.0` を返す。

### `def _add_cursor(self, x):`
x 位置に新しいカーソル（縦線＋マーカー）を 1 本追加。
- `y = self._cursor_track_y(x)`
- 縦線: `vl = self.ax.axvline(x, color="#e6194b", lw=0.9, ls="--")`
- マーカー: `mk, = self.ax.plot([x], [y], "o", color="#e6194b", ms=6)`
- `self._cursors.append({"x": x, "vline": vl, "marker": mk})`
- `self._cursor_artists += [vl, mk]`

### `def _cursor_near(self, event):`
クリック位置に近い既存カーソルの index を返す（無ければ `None`）。
- `self._cursors` を `enumerate` で回し、各 `c` について `try`:
  - `cx_px = self.ax.transData.transform((c["x"], 0))[0]`（データ座標 → ピクセル x）
  - `if abs(event.x - cx_px) < 8:` なら `return i`
  - `except Exception: pass`
- 該当なしなら `return None`。
- しきい値はピクセルで **8**。

### `def _on_cursor_press(self, event):`
カーソルのマウス押下ハンドラ。
- ガード: `event.inaxes is not self.ax` または `event.xdata is None` なら return。
- `near = self._cursor_near(event)`
- `near is not None` のとき（既存カーソルを掴んで微調整）: `self._cursor_drag = near` して return。
- `len(self._cursors) >= 2` なら 3 本目のクリックで計測をリセット: `self._clear_cursor_artists()`。
- `self._add_cursor(event.xdata)` で新カーソル追加。
- `self._update_cursor_readout()`、`self.canvas.draw_idle()`。

### `def _on_cursor_motion(self, event):`
カーソルのドラッグ中ハンドラ。
- ガード: `self._cursor_drag is None` または `event.inaxes is not self.ax` または `event.xdata is None` なら return。
- `c = self._cursors[self._cursor_drag]`
- `c["x"] = event.xdata`
- `c["vline"].set_xdata([event.xdata, event.xdata])`（縦線の x を更新。**リストで両端を同じ値**にする）
- `c["marker"].set_data([event.xdata], [self._cursor_track_y(event.xdata)])`（マーカーを波形に追従）
- `self._update_cursor_readout()`、`self.canvas.draw_idle()`。

### `def _on_cursor_release(self, event):`
マウス離しで `self._cursor_drag = None` にするだけ。

### `def _update_cursor_readout(self):`
2 本そろったとき、Δt / ΔV / 1/Δt を画面上部に表示。
- まず既存の読み出しテキストがあれば消す: `self._cursor_text is not None` なら `self._cursor_text.remove()`（例外は握りつぶす）して `self._cursor_text = None`。
- `len(self._cursors) == 2` のとき:
  - `x1, x2 = self._cursors[0]["x"], self._cursors[1]["x"]`
  - `y1, y2 = self._cursor_track_y(x1), self._cursor_track_y(x2)`
  - `dt, dv = x2 - x1, y2 - y1`
  - `freq = (1.0 / dt) if dt else float("inf")`（dt が 0 のときは inf）
  - 表示文字列（`abs()` を取る点に注意。`plotter.format_eng` で工学表記）:
    - `txt = f"Δt={plotter.format_eng(abs(dt))}  ΔV={plotter.format_eng(abs(dv))}  1/Δt={plotter.format_eng(abs(freq))}Hz"`
    - （Δt と ΔV の間、ΔV と 1/Δt の間は**半角スペース 2 個**ずつ。`1/Δt=...Hz` の末尾に `Hz`。）
  - テキスト配置: `self.ax.text(0.5, 0.98, txt, transform=self.ax.transAxes, ha="center", va="top", color="#e6194b", fontsize=9, bbox=dict(facecolor="white", alpha=0.75, edgecolor="#e6194b"))` を `self._cursor_text` に代入。
  - `self._cursor_artists.append(self._cursor_text)`
  - ステータス: `self._set_status("カーソル  " + txt)`（"カーソル" の後ろは半角スペース 2 個）

---

### `def _scope_active(self):`
オシロのドラッグ操作が有効かを返す（真偽）。すべての AND 条件:
- `self.scope_check.isChecked()`（オシロ表示 ON）
- `self.chart_combo.currentText() in ("折れ線", "散布図")`
- `self._has_drawn`（描画済み）
- `self._cursor_cid is None`（カーソル測定中でない）
- `not getattr(self.toolbar, "mode", "")`（ツールバーのパン/ズームモード非選択）

### `def _scope_overlay(self, text):`
オシロ操作中の緑色オーバーレイテキストを右下に表示。
- 先に `self._remove_scope_overlay()` を呼ぶ。
- コメントとして「`family="monospace"` は日本語グリフを持たず文字化けするので指定しない（rcParams の日本語フォントを使う）」旨を残す。
- `self._scope_ov = self.ax.text(0.99, 0.02, text, transform=self.ax.transAxes, ha="right", va="bottom", color="#7CFC00", fontsize=11, bbox=dict(facecolor="black", alpha=0.65, edgecolor="#7CFC00"))`
  - 色は **`#7CFC00`**（LawnGreen）、`facecolor="black"`、`alpha=0.65`。

### `def _remove_scope_overlay(self):`
- `self._scope_ov is not None` なら `self._scope_ov.remove()`（例外握りつぶし）して `self._scope_ov = None`。

### `def _shift_held(self, event=None):`
Shift 押下を判定。matplotlib の `event.key` はバックエンドによりスクロール時に Shift を取りこぼすため、Qt のキーボード修飾キー状態を優先して見る。
- `try`:
  - `mods = QtWidgets.QApplication.keyboardModifiers()`
  - `if bool(mods & QtCore.Qt.KeyboardModifier.ShiftModifier): return True`
  - `except Exception: pass`
- フォールバック: `return bool(event is not None and event.key and "shift" in str(event.key))`
- 落とし穴: Qt6 列挙はスコープ付きなので `QtCore.Qt.KeyboardModifier.ShiftModifier`（`QtCore.Qt.ShiftModifier` ではない）。

### `def _scope_on_press(self, event):`
オシロドラッグ開始。
- ガード（いずれかで return）: `not self._scope_active()` / `event.inaxes is not self.ax` / `event.button not in (1, 3)` / `event.x is None`。
- `bbox = self.ax.get_window_extent()`
- `self._scope_drag` に辞書を格納:
  - `"button": event.button`
  - `"shift": self._shift_held(event)`
  - `"px": (event.x, event.y)`
  - `"xlim": self.ax.get_xlim()`、`"ylim": self.ax.get_ylim()`
  - `"tdiv": plotter.parse_eng(self.tdiv.currentText(), 1e-3) or 1e-3`
  - `"vdiv": plotter.parse_eng(self.vdiv.currentText(), 1.0) or 1.0`
  - `"w": max(bbox.width, 1.0)`、`"h": max(bbox.height, 1.0)`
  - （`parse_eng(..., default) or default` で 0/None を弾く 2 重ガード。）

### `def _scope_on_motion(self, event):`
オシロドラッグ中。
- `d = self._scope_drag`; `if not d or event.x is None: return`
- `dxpx = event.x - d["px"][0]`、`dypx = event.y - d["px"][1]`（押下点からのピクセル移動量）
- `xd, yd = self.xdivs.value(), self.ydivs.value()`（横/縦 div 数）
- **左ドラッグかつ非 Shift（`d["button"] == 1 and not d["shift"]`）＝ パン（位置移動）**:
  - `x0, x1 = d["xlim"]; y0, y1 = d["ylim"]`
  - `dpx = (x1 - x0) / d["w"]`（ピクセルあたりのデータ幅 X）、`dpy = (y1 - y0) / d["h"]`（同 Y）
  - `nx0, nx1 = x0 - dxpx * dpx, x1 - dxpx * dpx`
  - `ny0, ny1 = y0 - dypx * dpy, y1 - dypx * dpy`
  - `self.ax.set_xlim(nx0, nx1); self.ax.set_ylim(ny0, ny1)`
  - オーバーレイ: `self._scope_overlay(f"位置  X中心={plotter.format_eng((nx0+nx1)/2)}  Y中心={plotter.format_eng((ny0+ny1)/2)}")`
    - 「位置」の後ろは半角スペース 2 個、「X中心=…」と「Y中心=…」の間も半角スペース 2 個。
- **それ以外（右ドラッグ or Shift）＝ スケール（div 変更）**:
  - `xc = (d["xlim"][0] + d["xlim"][1]) / 2`、`yc = (d["ylim"][0] + d["ylim"][1]) / 2`（中心保持）
  - `ntdiv = d["tdiv"] * (2 ** (dxpx / 150.0))`（右へドラッグで time/div 拡大）
  - `nvdiv = d["vdiv"] * (2 ** (-dypx / 150.0))`（上へドラッグで V/div 縮小＝符号反転）
  - `self.ax.set_xlim(xc - xd / 2 * ntdiv, xc + xd / 2 * ntdiv)`
  - `self.ax.set_ylim(yc - yd / 2 * nvdiv, yc + yd / 2 * nvdiv)`
  - オーバーレイ: `self._scope_overlay(f"{plotter.format_eng(ntdiv)}s/div   {plotter.format_eng(nvdiv)}/div")`
    - `…s/div` と `…/div` の間は**半角スペース 3 個**。time 側だけ末尾 `s/div`、V 側は `/div`。
- 最後に `self.canvas.draw_idle()`。
- 係数 **150.0** とズーム基数 **2** はそのまま。

### `def _scope_on_release(self, event):`
オシロドラッグ終了。確定値を UI ウィジェットへ反映して正式再描画。
- `if not self._scope_drag: return`
- `self._scope_drag = None`、`self._remove_scope_overlay()`
- `x0, x1 = self.ax.get_xlim(); y0, y1 = self.ax.get_ylim()`
- `xd, yd = self.xdivs.value(), self.ydivs.value()`
- `self._suspend_redraw = True`（流し込み中の再描画抑止）
- `self.xpos.setText(f"{(x0+x1)/2:.6g}")`、`self.ypos.setText(f"{(y0+y1)/2:.6g}")`（中心。フォーマット `:.6g`）
- `self.tdiv.setCurrentText(plotter.format_eng((x1 - x0) / xd) + "s")`（time/div、末尾 `s`）
- `self.vdiv.setCurrentText(plotter.format_eng((y1 - y0) / yd))`（V/div）
- `self._suspend_redraw = False`
- `self.draw_graph()`（コメント「グラティクル等を正式に再構築」）

### `def _scope_on_scroll(self, event):`
マウスホイール。
- `if event.inaxes is not self.ax: return`
- `if self._scope_active():`（オシロ表示中は div を増減）:
  - `step = 0.8 if event.button == "up" else 1.25`（コメント「up=ズームイン(div小)」）
  - `self._suspend_redraw = True`
  - `if self._shift_held(event):`（Shift で V/div）:
    - `cur = plotter.parse_eng(self.vdiv.currentText(), 1.0) or 1.0`
    - `self.vdiv.setCurrentText(plotter.format_eng(cur * step))`
  - `else:`（time/div）:
    - `cur = plotter.parse_eng(self.tdiv.currentText(), 1e-3) or 1e-3`
    - `self.tdiv.setCurrentText(plotter.format_eng(cur * step) + "s")`
  - `self._suspend_redraw = False`
  - `self.draw_graph()`
  - `return`
- オシロ表示以外でもホイールで拡大縮小（カーソル位置を中心に）: 最後に `self._wheel_zoom(event)` を呼ぶ。

### `def _wheel_zoom(self, event):`
通常グラフのマウスホイール拡大縮小。カーソル位置を中心にズーム。Shift+ホイールは X 方向のみ（横拡大）。
- 無効条件（いずれかで return）:
  - `self._cursor_cid is not None`（カーソル測定中）
  - `getattr(self.toolbar, "mode", "")`（ツールバーのパン/ズーム中）
  - `not getattr(self, "_has_drawn", False)`（未描画）
  - `self.chart_combo.currentText() == "円"`（円グラフ）
- `factor = 0.8 if event.button == "up" else 1.25`（コメント「up=拡大（範囲を狭める）」）
- `x0, x1 = self.ax.get_xlim()`、`y0, y1 = self.ax.get_ylim()`
- `xc = event.xdata if event.xdata is not None else (x0 + x1) / 2.0`
- `yc = event.ydata if event.ydata is not None else (y0 + y1) / 2.0`
- `xlog = self.ax.get_xscale() == "log"`、`ylog = self.ax.get_yscale() == "log"`
- `self.ax.set_xlim(*self._zoom_pair(x0, x1, xc, factor, xlog))`
- `if not self._shift_held(event):`（Shift 押下時は Y 保持＝横方向のみ拡大）:
  - `self.ax.set_ylim(*self._zoom_pair(y0, y1, yc, factor, ylog))`
- `self.canvas.draw_idle()`

### `@staticmethod`
### `def _zoom_pair(lo, hi, center, factor, log=False):`
`[lo, hi]` を `center` 中心に `factor` 倍に拡縮した新範囲を返す（log 軸対応）。**`@staticmethod` 装飾を付ける**（self 引数なし）。
- `import numpy as np`
- `if log and lo > 0 and hi > 0 and center > 0:`（対数空間で計算）:
  - `l0, l1, lc = np.log10(lo), np.log10(hi), np.log10(center)`
  - `return 10.0 ** (lc - (lc - l0) * factor), 10.0 ** (lc + (l1 - lc) * factor)`
- それ以外（線形）:
  - `return center - (center - lo) * factor, center + (hi - center) * factor`
- 戻り値は `(新 lo, 新 hi)` の 2 タプル。

### `def auto_scale_scope(self):`
選択中の全系列が収まるように time/div・V/div・中心を自動設定。
- `import numpy as np`、`import pandas as pd`
- `items = self._selected_series_items()`（選択された Y 系列。各要素は `(fl, col, _)` の 3 タプルで `fl`=ファイル/データセットキー、`col`=列名、3 つ目は未使用）。
- `if not items:` → `QtWidgets.QMessageBox.information(self, "情報", "データタブでY系列を選択してください。")` して return。
- `xname = self.x_combo.currentText()`（X 軸列名）
- `tmins, tmaxs, ymins, ymaxs = [], [], [], []`
- `for fl, col, _ in items:`:
  - `df = self.datasets[fl]`
  - X 生データ: `raw = df[xname].to_numpy() if xname in df.columns else df.iloc[:, 0].to_numpy()`（xname 列が無ければ先頭列）
  - 数値化: `tt = pd.to_numeric(pd.Series(raw), errors="coerce").to_numpy(dtype=float)`
  - `if np.isnan(tt).mean() > 0.5:`（X が半分以上数値化できない＝非数値）→ `tt = np.arange(len(tt), dtype=float)`（インデックスを時間軸に）
  - `yy = pd.to_numeric(pd.Series(df[col].to_numpy()), errors="coerce").to_numpy(dtype=float)`
  - 有限値のみ: `tt, yy = tt[np.isfinite(tt)], yy[np.isfinite(yy)]`
  - `if tt.size: tmins.append(tt.min()); tmaxs.append(tt.max())`
  - `if yy.size: ymins.append(yy.min()); ymaxs.append(yy.max())`
- `if not tmins or not ymins:` → `QtWidgets.QMessageBox.information(self, "情報", "数値データがありません。")` して return。
- `tmin, tmax = min(tmins), max(tmaxs)`、`ymin, ymax = min(ymins), max(ymaxs)`
- `xd, yd = self.xdivs.value(), self.ydivs.value()`
- `tpd = (tmax - tmin) / xd if tmax > tmin else 1e-3`（time/div。range/div 数）
- `vpd = (ymax - ymin) / (yd - 1) if ymax > ymin else 1.0`（V/div。**分母は `yd - 1`**、余白 1 div 分を残す）
- `self._suspend_redraw = True`
- `self.tdiv.setCurrentText(plotter.format_eng(tpd) + "s")`
- `self.vdiv.setCurrentText(plotter.format_eng(vpd))`
- `self.xpos.setText(f"{(tmin+tmax)/2:.4g}")`、`self.ypos.setText(f"{(ymin+ymax)/2:.4g}")`（中心。フォーマット `:.4g`）
- `self.scope_check.setChecked(True)`（オシロ表示を ON にする）
- `self._suspend_redraw = False`
- `self.draw_graph()`

---

## 定数・データ（正確な値）

### 色
- カーソル（縦線・マーカー・読み出し枠線/文字）: `#e6194b`（赤）
- オシロオーバーレイ文字/枠線: `#7CFC00`（緑、LawnGreen）、背景 `black`

### 数値定数
- カーソル近接しきい値: ピクセル `8`
- カーソル縦線: `lw=0.9`, `ls="--"`
- カーソルマーカー: `"o"`, `ms=6`
- カーソル読み出しテキスト: 位置 `(0.5, 0.98)`, `ha="center"`, `va="top"`, `fontsize=9`, bbox `facecolor="white", alpha=0.75, edgecolor="#e6194b"`
- オシロオーバーレイ: 位置 `(0.99, 0.02)`, `ha="right"`, `va="bottom"`, `fontsize=11`, bbox `facecolor="black", alpha=0.65, edgecolor="#7CFC00"`
- ドラッグスケール係数: 除数 `150.0`、基数 `2`
- ホイール step（オシロ）: up → `0.8`、それ以外 → `1.25`
- ホイール factor（通常）: up → `0.8`、それ以外 → `1.25`
- `parse_eng` の既定: `tdiv` 系 `1e-3`、`vdiv` 系 `1.0`
- フォーマット: 中心位置は `_scope_on_release` で `:.6g`、`auto_scale_scope` で `:.4g`
- `auto_scale_scope`: X 非数値判定は `np.isnan(tt).mean() > 0.5`、V/div 分母は `yd - 1`、デフォルト `tpd=1e-3` / `vpd=1.0`

### 文字列（UI ラベル・ステータス・例外・日本語）— 正確にそのまま
- `toggle_cursors` ステータス: `"カーソル: クリックで2本設置 → 線をドラッグで微調整（波形に追従）"`
- カーソル読み出し txt: `f"Δt={plotter.format_eng(abs(dt))}  ΔV={plotter.format_eng(abs(dv))}  1/Δt={plotter.format_eng(abs(freq))}Hz"`
- カーソル読み出しステータス: `"カーソル  " + txt`
- パン時オーバーレイ: `f"位置  X中心={plotter.format_eng((nx0+nx1)/2)}  Y中心={plotter.format_eng((ny0+ny1)/2)}"`
- スケール時オーバーレイ: `f"{plotter.format_eng(ntdiv)}s/div   {plotter.format_eng(nvdiv)}/div"`
- `auto_scale_scope` 情報ダイアログ 1: タイトル `"情報"`, 本文 `"データタブでY系列を選択してください。"`
- `auto_scale_scope` 情報ダイアログ 2: タイトル `"情報"`, 本文 `"数値データがありません。"`
- `tdiv` に流し込む文字列の末尾は常に `"s"`（`format_eng(...) + "s"`）、`vdiv` は単位なし。

### `chart_combo.currentText()` で比較する種別名
- 有効種別: `"折れ線"`, `"散布図"`
- ホイールズーム無効種別: `"円"`

---

## 再現に必須の細部・エッジケース・ガード

- `_cursor_track_y`: `_plotted_artists` が空、または例外時は `0.0` を返す。`_plotted_artists[0][1]` が Line2D。x を昇順ソートしてから `np.interp`。
- `_cursor_near`: しきい値 8px。`transData.transform((x, 0))[0]` でピクセル x を得る。例外は無視して次へ。
- `_on_cursor_press`: 既存カーソル近傍なら掴むだけで return（追加しない）。すでに 2 本ある状態で新規クリックすると `_clear_cursor_artists` でリセットしてから 1 本目を置く（＝計測やり直し）。
- `_on_cursor_motion`: `set_xdata([x, x])` はリスト 2 要素、`set_data([x], [y])` はそれぞれ長さ 1 のリスト。
- `_update_cursor_readout`: 2 本未満のときはテキストを消すだけ（読み出しは作らない）。`dt == 0` のとき `freq = inf`。表示は全部 `abs()`。
- `_scope_active` の 5 条件はすべて満たす必要がある（特に `_cursor_cid is None` でカーソル測定と排他、`toolbar.mode` が空でツールバー操作と排他）。
- `_shift_held`: Qt の `keyboardModifiers()` を優先し、失敗時のみ `event.key` 文字列に `"shift"` が含まれるかでフォールバック。`event` は省略可（`=None`）。
- `_scope_on_press`: `event.button` は **1（左）か 3（右）** のみ受け付ける。`event.x is None` ガードあり。
- パン計算はピクセル移動 × （データ幅 / ウィンドウピクセル幅）。スケール計算は中心固定で `2 ** (±dpx/150)`。Y のスケールは上方向でズームイン（`-dypx`）。
- `_scope_on_release` と `_scope_on_scroll` と `auto_scale_scope` は、UI へ値を流し込む間 `_suspend_redraw = True/False` で挟み、最後に明示的に `draw_graph()` を 1 回呼ぶ（途中の setText/setCurrentText の signal による多重再描画を防ぐ）。
- `_scope_on_scroll`: オシロ時は div 増減して `return`。非オシロ時は `_wheel_zoom` へ委譲。
- `_wheel_zoom`: 円グラフ・未描画・カーソル測定中・ツールバー操作中は何もしない。Shift で X のみ拡大（Y を保持）。
- `_zoom_pair`: log 軸かつ `lo>0 and hi>0 and center>0` のときのみ対数空間で計算。それ以外は線形。`@staticmethod`。
- `auto_scale_scope`: X 列が見つからなければ先頭列（`iloc[:, 0]`）を使う。X が 50% 超 NaN ならインデックス（`np.arange`）を時間軸に代用。V/div の分母は `yd - 1`（縦に 1 div 分の余白を残す設計）。最後に `scope_check` を ON にして再描画。

---

## このファイル特有の落とし穴

- **Qt6 列挙はスコープ付き**: `_shift_held` は必ず `QtCore.Qt.KeyboardModifier.ShiftModifier` を使う（Qt5 流の `QtCore.Qt.ShiftModifier` は不可）。
- **monospace 禁止**: `_scope_overlay` のテキストに `family="monospace"` を指定しない（「位置」「中心」等の日本語が □ 化けする）。rcParams の日本語フォントに任せる。コメントにもその旨を残す。
- **Mixin 規約**: `class ScopeCursorMixin:` は `__init__` を持たない**メソッド束**。`from graph_app_common import *` で始める。状態属性（`_cursors`, `_scope_drag`, `_scope_ov`, `_cursor_cid` など）や UI ウィジェットは GraphApp 本体／他 Mixin が初期化する前提で、ここでは定義しない。
- **`@staticmethod` の所在**: `_zoom_pair` は装飾ごとこの Mixin に置く（self を取らない）。
- **facade 経由**: 工学表記は `plotter.format_eng` / `plotter.parse_eng` を使う（直接ローカル関数を定義しない）。`plotter` は facade で公開名が保たれている。
- **`_suspend_redraw` の対称解除**: True にしたら必ず False に戻す（例外でフラグが立ちっぱなしになると以降の再描画が止まるため、流し込み区間は短く保つ）。本ファイルでは try/finally は使わず直線的に True→処理→False→`draw_graph()` の順。
- **`parse_eng(..., default) or default`**: 戻り値が 0 や None になっても既定値へフォールバックする 2 重ガード。`tdiv` は `1e-3`、`vdiv` は `1.0`。
- **grid linewidth=None 回避**は本ファイルでは直接該当しないが、`draw_graph()` 側の規約として留意。
