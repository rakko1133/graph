# [28/30] graph_app_mixins/batch.py の仕様

## 指示

- この仕様だけを読んで `graph_app_mixins/batch.py` を**完全な形**で実装し、ファイル全文を出力すること。
- `pass`・`TODO`・「以下省略」・要約・ダミー実装は**禁止**。すべてのメソッド本体を実際に動作するコードとして書ききること。
- 出力がトークン上限で切れた場合は、続けて「続き」と入力されたら**続きから最後まで**出力すること。
- シグネチャ・定数値・UIラベル文字列・日本語メッセージは**この仕様に書いてある通り正確に**再現すること。

### アプリ全体の前提（このファイルに関係する分）

- Python 3.10+ / GUI=PySide6(Qt6)。Qt は必ず matplotlib 経由で取得する。本ファイルは `from graph_app_common import *` 経由で `QtCore` / `QtGui` / `QtWidgets`・`os`・各定数を受け取る（このファイル自身は明示 import を持たない）。
- Qt6 列挙はスコープ付き（例: `QtWidgets.QDialogButtonBox.StandardButton.Ok` / `QtWidgets.QDialog.DialogCode.Accepted` / `QtCore.Qt.CursorShape.WaitCursor`）。
- `GraphApp` は 10 個の Mixin ＋ `QtWidgets.QMainWindow` の多重継承。`__init__`/`closeEvent` は本体に置く。**各 Mixin は `from graph_app_common import *` で始まり `__init__` を持たない**メソッド束。`@staticmethod` は装飾ごと担当 Mixin に置く。
- 実プロセス並列の描画ワーカー `batch_render.py` は **Qt を import しない**（spawn 安全）。本ファイルからは関数呼び出し時にだけ `import batch_render` する。
- 数式/フォント/grid 等の細部（`grid linewidth=None` を渡さない、日本語に `monospace` 不使用）は他 Mixin と `batch_render` 側の責務で、本ファイルでは直接扱わない。

---

## ファイルの役割 / 責務

`BatchMixin`。`GraphApp` から分離した「画像の保存・コピー・一括出力」担当の Mixin。docstring は次の趣旨:

> `"""BatchMixin: GraphApp から分離した BatchMixin 群（挙動は本体と同一）。"""`

責務は 3 系統:

1. **現在表示中グラフの保存**（`_save_current_figure` / `save_figure`）。
2. **現在グラフのクリップボードコピー**（`copy_figure`）。
3. **一括出力**：読み込んだ各データファイルを、現在の書式設定で 1 枚ずつ描画してフォルダへまとめて保存（`_build_series_for_file` / `_batch_options_dialog` / `batch_export` ＋ ヘルパ `_safe_filename`）。一括出力の実描画は外部の `batch_render` モジュール（Qt 非依存）へ委譲し、枚数が多いときだけ別プロセス並列、失敗時は逐次へフォールバックする。

`GraphApp` 本体や他 Mixin が提供する属性・メソッド（`self.fig` / `self.ax` / `self.canvas` / `self.datasets` / 各種ウィジェット / `self._aspect_ratio` 等）に依存する。これらは本ファイルでは定義しない（前提として存在する）。

---

## 依存（import するもの）

```python
# -*- coding: utf-8 -*-
"""BatchMixin: GraphApp から分離した BatchMixin 群（挙動は本体と同一）。"""
from graph_app_common import *  # noqa: F401,F403
```

- これ以外のモジュールレベル import は持たない。`io` / `re` / `batch_render` / `concurrent.futures` は**各メソッド内で遅延 import** する（後述）。
- `os`・`QtCore`・`QtGui`・`QtWidgets`・定数 `DECIMATE_TARGET`・`BATCH_PARALLEL_THRESHOLD` は `from graph_app_common import *` 経由で利用可能。

このファイルで使う graph_app_common 由来の定数（参考値）:
- `DECIMATE_TARGET = 8000`（折れ線/散布図でこの点数を超えたら間引いて表示）
- `BATCH_PARALLEL_THRESHOLD = 64`（一括出力でこの枚数以上なら別プロセス並列を試みる）

---

## クラス構造

```python
class BatchMixin:
    ...
```

メソッドの定義順（コメント帯付き）:

1. `# ------------------------------------------------------------ 補助`
   - `_save_current_figure(self, target, dpi, transparent, fmt=None)`
   - `save_figure(self)`
   - `copy_figure(self)`
2. `# ------------------------------------------------------------ 一括出力`
   - `@staticmethod _safe_filename(name)`
   - `_build_series_for_file(self, label, x_name, y_names, chart_type, style_by_col)`
   - `_batch_options_dialog(self)`
   - `batch_export(self)`

---

## 公開 API（完全シグネチャ＋振る舞い）

### `def _save_current_figure(self, target, dpi, transparent, fmt=None):`

現在のグラフ（`self.fig`）を `target` に保存する。`target` はパス文字列でもファイルライクオブジェクト（`io.BytesIO`）でもよい。`fmt` は matplotlib の `format`（例 `"png"`）。戻り値なし。

アルゴリズム:

1. `ratio = self._aspect_ratio()` を取得。
2. **`ratio` が偽（縦横比指定なし）の場合**: 従来どおり tight 保存して return。
   ```python
   self.fig.savefig(target, dpi=dpi, bbox_inches="tight",
                    transparent=transparent, format=fmt)
   return
   ```
3. **`ratio` が真（縦横比指定あり）の場合**: 画像そのものをその比率にする。bbox トリミングはしない。
   - `orig = self.fig.get_size_inches()` で現在サイズを退避。
   - `try:` 節で:
     - `self.fig.set_size_inches(self._export_figsize())`
     - `self.ax.set_box_aspect(None)`（図いっぱいに描くため枠固定を一時解除）
     - `ax2 = getattr(self.ax, "_twin_secondary", None)`。`ax2 is not None` なら `ax2.set_box_aspect(None)`。
     - `try: self.fig.tight_layout()` / `except Exception: pass`。
     - `self.fig.savefig(target, dpi=dpi, transparent=transparent, format=fmt)`（**`bbox_inches` は渡さない**）。
   - `finally:` 節で画面表示用に必ず元に戻す:
     - `self.fig.set_size_inches(orig)`
     - `self._apply_aspect()`
     - `try: self.fig.tight_layout()` / `except Exception: pass`
     - `self.canvas.draw_idle()`

エッジケース: `tight_layout()` は 2 箇所とも例外を握りつぶす（失敗しても保存・復元を続行）。`finally` により例外発生時でも図サイズと比率は確実に復元される。

依存する他メソッド: `self._aspect_ratio()`, `self._export_figsize()`, `self._apply_aspect()`。

### `def save_figure(self):`

「グラフ画像を保存」ダイアログを出して保存する。戻り値なし。

1. `QtWidgets.QFileDialog.getSaveFileName(...)` を次の引数で呼ぶ:
   - 親: `self`
   - タイトル: `"グラフ画像を保存"`
   - 既定パス: `os.path.join(self.last_dir, "graph.png")`
   - フィルタ: `"PNG (*.png);;JPEG (*.jpg);;PDF (*.pdf);;SVG (*.svg);;EPS (*.eps)"`
   - 戻り値は `(path, _)` で受ける。
2. `if not path: return`（キャンセル時）。
3. `try:` 節:
   - `dpi = self.dpi_spin.value()`
   - `transparent = self.transparent_check.isChecked()`
   - `self._save_current_figure(path, dpi, transparent)`（`fmt` は渡さず拡張子任せ）
   - `self.last_dir = os.path.dirname(path)`
   - ステータス更新: `self._set_status(f"保存しました: {path}（{dpi} DPI{'・背景透過' if transparent else ''}）")`
     - 透過 ON のときだけ `・背景透過` を付ける。
4. `except Exception as e:  # noqa: BLE001` → `QtWidgets.QMessageBox.critical(self, "保存エラー", str(e))`。

### `def copy_figure(self):`

docstring: `"""現在のグラフを画像としてクリップボードにコピーする。"""`。戻り値なし。

1. メソッド先頭で `import io`。
2. `try:` 節:
   - `buf = io.BytesIO()`
   - `self._save_current_figure(buf, self.dpi_spin.value(), self.transparent_check.isChecked(), fmt="png")`（**`fmt="png"` を明示**。BytesIO は拡張子を持たないため）。
   - `buf.seek(0)`
   - `img = QtGui.QImage.fromData(buf.getvalue(), "PNG")`
   - `if img.isNull(): raise RuntimeError("画像の生成に失敗しました。")`
   - `QtWidgets.QApplication.clipboard().setImage(img)`
   - `self._set_status("グラフをクリップボードにコピーしました。")`
3. `except Exception as e:  # noqa: BLE001` → `QtWidgets.QMessageBox.critical(self, "コピーエラー", str(e))`。

### `@staticmethod` / `def _safe_filename(name):`

ファイル名に使えない文字を `_` に潰す静的メソッド。

```python
@staticmethod
def _safe_filename(name):
    import re
    return re.sub(r'[\\/:*?"<>|]+', "_", str(name)).strip() or "graph"
```

- 正規表現: `r'[\\/:*?"<>|]+'`（バックスラッシュ・スラッシュ・コロン・アスタリスク・疑問符・ダブルクォート・不等号・パイプの 1 文字以上連続）を `"_"` に置換。
- `str(name)` で文字列化 → 置換 → `.strip()`。結果が空なら `"graph"` を返す（`or "graph"`）。
- `re` はメソッド内で遅延 import。**`@staticmethod` 装飾はこの担当 Mixin に置く**（Mixin 規約）。

### `def _build_series_for_file(self, label, x_name, y_names, chart_type, style_by_col):`

docstring の趣旨:

> 1ファイルから、指定した列名テンプレートで系列を作る（一括出力用）。『一番左の列をX軸』ONなら、各ファイルの先頭列を位置でX軸に使う。

戻り値: タプル `(series, categories)`。`series` は dict のリスト、`categories` は X 値配列または `None`。

アルゴリズム:

1. `df = self.datasets[label]`（pandas DataFrame）。
2. `series, categories = [], None`。
3. `leftmost = self._use_leftmost_x()`（bool）。
4. X 値 `xv` の決定:
   ```python
   xv = (df.iloc[:, 0].to_numpy() if leftmost
         else (df[x_name].to_numpy() if x_name in df.columns else df.iloc[:, 0].to_numpy()))
   ```
   - `leftmost` ON なら先頭列。OFF なら `x_name` 列があればそれ、なければ先頭列にフォールバック。
5. **`chart_type in ("棒", "横棒", "積み上げ棒", "円")` の場合**:
   - `categories = xv`。
   - 各 `c in y_names` について `series.append({"label": c, "y": df[c].to_numpy(), "style": style_by_col.get(c)})`。
6. **`chart_type in ("折れ線", "散布図")` の場合**:
   - 各 `c in y_names` について:
     - `st = style_by_col.get(c) or {}`
     - `errcol = st.get("errcol")`
     - `yerr = df[errcol].to_numpy() if (errcol and errcol in df.columns) else None`
     - `series.append({"label": c, "x": xv, "y": df[c].to_numpy(), "style": st, "axis": st.get("axis", "primary"), "kind": st.get("kind", ""), "yerr": yerr})`
7. **それ以外（ヒストグラム / 箱ひげ）**（`else:`）:
   - 各 `c in y_names` について `series.append({"label": c, "y": df[c].to_numpy(), "style": style_by_col.get(c)})`。
8. `return series, categories`。

系列 dict のキー名は**正確に**: 共通 `"label"`/`"y"`/`"style"`、折れ線・散布図のみ追加で `"x"`/`"axis"`/`"kind"`/`"yerr"`。`"style"` は棒系・ヒスト系では `style_by_col.get(c)`（生の値、`None` あり）、折れ線・散布図では `st`（`None` を `{}` に正規化したもの）。

### `def _batch_options_dialog(self):`

docstring の趣旨: 一括出力の調整（タイトル・形式・DPI・透過）。OK で dict、キャンセルで `None`。

`QtWidgets.QDialog` を組み、`QtWidgets.QFormLayout` で配置する。

構築手順（順序厳守）:

1. `dlg = QtWidgets.QDialog(self)`、`dlg.setWindowTitle("一括画像保存の設定")`。
2. `form = QtWidgets.QFormLayout(dlg)`。
3. 説明ラベル `info`:
   - テキスト（改行 `\n` 込み、正確に）:
     ```
     各ファイルを現在のグラフ設定で1枚ずつ保存します。
     軸名・凡例・近似曲線・縦横比などは右の書式パネルの値を使います。
     ```
     （Python では `"各ファイルを現在のグラフ設定で1枚ずつ保存します。\n軸名・凡例・近似曲線・縦横比などは右の書式パネルの値を使います。"`）
   - `info.setStyleSheet("color:#666;")`
   - `form.addRow(info)`（ラベル無しの単独行）。
4. `title_edit = QtWidgets.QLineEdit(self.title_edit.text() or "{name}")`
   - `title_edit.setToolTip("グラフタイトル。{name} はファイル名（拡張子なし）に置き換わります。")`
   - `form.addRow("グラフタイトル", title_edit)`
5. `fmt_combo = QtWidgets.QComboBox()`; `fmt_combo.addItems(["png", "jpg", "pdf", "svg"])`
   - `form.addRow("出力形式", fmt_combo)`
6. `dpi_spin = QtWidgets.QSpinBox()`; `dpi_spin.setRange(50, 1200)`; `dpi_spin.setSingleStep(50)`; `dpi_spin.setValue(self.dpi_spin.value())`
   - `form.addRow("解像度 DPI", dpi_spin)`
7. `trans = QtWidgets.QCheckBox()`; `trans.setChecked(self.transparent_check.isChecked())`
   - `form.addRow("背景透過", trans)`
8. ボタンボックス:
   ```python
   bb = QtWidgets.QDialogButtonBox(
       QtWidgets.QDialogButtonBox.StandardButton.Ok
       | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
   bb.button(QtWidgets.QDialogButtonBox.StandardButton.Ok).setText("フォルダを選んで保存...")
   bb.accepted.connect(dlg.accept); bb.rejected.connect(dlg.reject)
   form.addRow(bb)
   ```
   - **OK ボタンのラベルは `"フォルダを選んで保存..."` に差し替える**（末尾は ASCII の `...` 3 ドット）。
9. 実行と返却:
   ```python
   if dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted:
       return None
   title = title_edit.text().strip() or "{name}"
   return {"title": title, "fmt": fmt_combo.currentText(),
           "dpi": dpi_spin.value(), "transparent": trans.isChecked()}
   ```
   - 返す dict のキー名: `"title"` / `"fmt"` / `"dpi"` / `"transparent"`（**正確に**）。
   - `title` が空文字なら `"{name}"` にフォールバック。

UI まとめ（フォーム行の並び）:
| 行 | ラベル | ウィジェット | 既定値 |
|---|---|---|---|
| 1 | （無し） | 説明ラベル `info`（色 `#666`） | — |
| 2 | グラフタイトル | `QLineEdit` | `self.title_edit.text()` か `{name}` |
| 3 | 出力形式 | `QComboBox`（png/jpg/pdf/svg） | `png`（先頭） |
| 4 | 解像度 DPI | `QSpinBox`（50〜1200, step 50） | `self.dpi_spin.value()` |
| 5 | 背景透過 | `QCheckBox` | `self.transparent_check.isChecked()` |
| 6 | （無し） | `QDialogButtonBox`（OK/Cancel） | OK ラベル＝「フォルダを選んで保存...」 |

### `def batch_export(self):`

docstring: `"""読み込んだ各ファイルを、現在の設定で個別に描画してファイル名ごとに一括保存する。"""`。戻り値なし。

全体フロー:

**(A) 事前ガード・テンプレート列の収集**

1. `if not self.datasets:` → `QtWidgets.QMessageBox.information(self, "情報", "先にファイルを追加してください。")` して return。
2. `ctype = self.chart_combo.currentText()`。
3. 選択中 Y 系列の「列名」テンプレートとスタイルを順序保持・重複除去で集める:
   ```python
   y_names, style_by_col = [], {}
   for fl, col, disp in self._selected_series_items():
       if col not in y_names:
           y_names.append(col)
       style_by_col.setdefault(col, self.series_styles.get(self._style_key(fl, col)))
   ```
   - `self._selected_series_items()` は `(ファイルラベル, 列名, 表示名)` のタプルを yield/return する想定。
   - `style_by_col` は列名→スタイル dict（`self.series_styles` から `self._style_key(fl, col)` で引く。最初に出た fl のスタイルを `setdefault` で採用）。
4. Y 軸ラベルの自動生成（主軸の列名から、画面描画と同じ規則）:
   ```python
   prim_y = [c for c in y_names
             if (style_by_col.get(c) or {}).get("axis", "primary") != "secondary"]
   auto_ylabel = self.ylabel_edit.text() or self._auto_y_label(prim_y, ctype)
   ```
   - `axis` が `"secondary"` でない列だけ主軸扱い。`ylabel_edit` が空なら `_auto_y_label` で生成。
5. `if not y_names:` → 情報ダイアログを出して return:
   - タイトル `"情報"`、本文（`\n` 込み、正確に）:
     ```
     Y軸（値）の系列を1つ以上選んでください。
     その列名を各ファイルに適用し、ファイルごとに1枚ずつ出力します。
     ```
6. `x_name = self.x_combo.currentText()`。

**(B) オプションダイアログ・出力先選択**

7. `opts = self._batch_options_dialog()`。`if opts is None: return`（キャンセル）。
8. `out_dir = QtWidgets.QFileDialog.getExistingDirectory(self, "一括出力フォルダを選択", self.last_dir)`。`if not out_dir: return`。

**(C) 共通パラメータの確定**

9. `dpi = opts["dpi"]` / `transparent = opts["transparent"]` / `title_tpl = opts["title"]` / `ext = opts["fmt"]`。
10. `ratio = self._aspect_ratio()`。
11. `fmt = self._plot_format_kwargs()`（共通フォーマット: bins/grid/凡例/対数/近似/ラベル等の dict）。
    - 注意: ここでの変数名 `fmt` は `_plot_format_kwargs()` の戻り値（描画オプション dict）であり、`ext`（拡張子）とは別物。
12. 縦横比に応じた図サイズ/トリミング方針:
    ```python
    if ratio:
        figsize = self._export_figsize()
        tight = False
    else:
        figsize = self.fig.get_size_inches()
        tight = True
    ```
    - 比率指定ありなら図サイズで決め `tight=False`（bbox トリミングしない）。なしなら現在の図サイズで `tight=True`。
13. 軸範囲とデシメーション:
    ```python
    issues = []
    xlim = self._range_pair(self.xmin, self.xmax, "X", issues)
    ylim = self._range_pair(self.ymin, self.ymax, "Y", issues)
    max_points = (DECIMATE_TARGET if (self.decimate_check.isChecked()
                  and ctype in ("折れ線", "散布図")) else 0)
    ```
    - `_range_pair` は `(min, max)` を解析してタプルか `None` を返し、問題があれば `issues` に積む想定（`issues` は本メソッド内では収集のみで明示利用はしない）。
    - `max_points` は間引き ON かつ折れ線/散布図なら `DECIMATE_TARGET`、それ以外 `0`。

**(D) 各ファイルのタスク（picklable な dict）構築**

ファイル名の重複解決は順序依存なのでここで逐次に確定し、各タスクに最終パスを持たせる。

```python
tasks, skipped, used = [], [], set()
for label, df in self.datasets.items():
    cols = [c for c in y_names if c in df.columns]
    if not cols:
        skipped.append(f"{label}（対象列なし）")
        continue
    try:
        series, categories = self._build_series_for_file(
            label, x_name, cols, ctype, style_by_col)
    except Exception as e:  # noqa: BLE001
        skipped.append(f"{label}（{e}）")
        continue
    stem = os.path.splitext(label)[0]
    sec_label = " / ".join(s["label"] for s in series
                           if s.get("axis") == "secondary")
    xlab = self.xlabel_edit.text() or (
        str(df.columns[0]) if self._use_leftmost_x() else x_name)
    base = self._safe_filename(stem)
    name, k = base, 2
    while name in used:
        name = f"{base}_{k}"; k += 1
    used.add(name)
    tasks.append({
        "series": series, "categories": categories, "ctype": ctype,
        "title": title_tpl.replace("{name}", stem),
        "xlabel": xlab, "ylabel": auto_ylabel,
        "xlim": xlim, "ylim": ylim, "sec_label": sec_label,
        "max_points": max_points, "fmt": fmt, "ratio": None,
        "figsize": tuple(figsize), "tight": tight,
        "dpi": dpi, "transparent": transparent,
        "path": os.path.join(out_dir, f"{name}.{ext}"),
        "font_name": getattr(self, "font_name", None),
    })
```

細部:
- `cols` は `y_names` のうち**その df に実在する列**だけ（順序は `y_names` 準拠）。空なら `"{label}（対象列なし）"` を `skipped` に積んで continue。
- 系列構築失敗時は `"{label}（{e}）"` を `skipped` に積んで continue。
- `stem`：ラベルから拡張子を除いた幹。
- `sec_label`：`axis == "secondary"` の系列ラベルを `" / "` で連結（第 2 軸の軸名用）。
- `xlab`：`xlabel_edit` が空なら、`leftmost` ON 時は先頭列名 `str(df.columns[0])`、OFF 時は `x_name`。
- ファイル名重複解決：`base` が `used` に在れば `base_2`, `base_3`, … と `k` を 2 から増やしていく。
- **`title` は `title_tpl` の `{name}` を `stem` に `.replace` で置換**（`stem` は拡張子なしファイル名）。
- タスク dict のキー名は**正確に**（`batch_render.render_one` が読む）: `series`, `categories`, `ctype`, `title`, `xlabel`, `ylabel`, `xlim`, `ylim`, `sec_label`, `max_points`, `fmt`, `ratio`(常に `None`), `figsize`(tuple), `tight`, `dpi`, `transparent`, `path`, `font_name`。
- `"ratio": None` は**常に None**（比率は figsize 側で表現済み）。`"figsize"` は `tuple(figsize)`（pickle 安全な tuple 化）。
- `"font_name": getattr(self, "font_name", None)`（属性が無くても `None`）。

**(E) 描画実行（並列／逐次フォールバック）**

```python
import batch_render
saved = []
QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
try:
    use_pool = len(tasks) >= BATCH_PARALLEL_THRESHOLD
    if use_pool:
        try:
            import concurrent.futures as _cf
            workers = min(8, (os.cpu_count() or 1))
            with _cf.ProcessPoolExecutor(max_workers=workers) as ex:
                futs = {ex.submit(batch_render.render_one, t): t for t in tasks}
                for fut in _cf.as_completed(futs):
                    try:
                        saved.append(fut.result())
                    except Exception as e:  # noqa: BLE001
                        skipped.append(
                            f"{os.path.basename(futs[fut]['path'])}（{e}）")
                    QtWidgets.QApplication.processEvents()
        except Exception as e:  # noqa: BLE001  プール作成失敗/壊れ→逐次へ
            self._set_status(f"並列出力に失敗、逐次に切替: {e}")
            use_pool = False
            saved = []        # 部分結果は破棄し、逐次で全件作り直す
    if not use_pool:
        saved, seq_skipped = batch_render.render_sequential(tasks)
        skipped.extend(seq_skipped)
        QtWidgets.QApplication.processEvents()
finally:
    QtWidgets.QApplication.restoreOverrideCursor()
```

細部・エッジケース:
- `import batch_render` は**ここで初めて行う**（Qt 非依存ワーカー。spawn 安全）。
- 待機カーソル `QtCore.Qt.CursorShape.WaitCursor` を `setOverrideCursor` で出し、`finally` で必ず `restoreOverrideCursor()`。
- **並列判定**: `len(tasks) >= BATCH_PARALLEL_THRESHOLD`（=64 以上）のときだけプールを試す（少数では spawn/pickle/フォント設定の固定費で逆効果）。
- ワーカー数: `min(8, (os.cpu_count() or 1))`（最大 8、`cpu_count()` が `None` なら 1）。
- `concurrent.futures` は `_cf` として遅延 import。`ProcessPoolExecutor(max_workers=workers)`。
- `futs`：`{future: task}` の dict。`as_completed` で完了順に `fut.result()` を `saved` に積む。各タスク失敗は `"{os.path.basename(futs[fut]['path'])}（{e}）"` を `skipped` に積む（全体は止めない）。
- 各完了ごとに `QtWidgets.QApplication.processEvents()`（UI 応答性維持）。
- **プール自体の作成失敗/破損**は外側 `except` で捕捉 → ステータス `f"並列出力に失敗、逐次に切替: {e}"`、`use_pool = False`、`saved = []`（部分結果は破棄し逐次で全件作り直す）。
- **逐次フォールバック**（`if not use_pool:`、初めから少数の場合も含む）: `saved, seq_skipped = batch_render.render_sequential(tasks)` で全件描画。`skipped.extend(seq_skipped)`。`processEvents()`。
- `batch_render` 側 API（参考）: `render_one(task)` は 1 タスクを描画し保存パスを返す。`render_sequential(tasks)` は `(saved_list, skipped_list)` を返す。

**(F) 後処理・結果通知**

```python
self.last_dir = out_dir
msg = f"一括出力: {len(saved)} 件を保存しました。\n{out_dir}"
if skipped:
    head = " / ".join(str(s) for s in skipped[:5])
    msg += f"\n\nスキップ {len(skipped)} 件: {head}" + (" ほか" if len(skipped) > 5 else "")
QtWidgets.QMessageBox.information(self, "一括出力", msg)
self._set_status(f"一括出力: {len(saved)} 件保存（{out_dir}）")
```

細部:
- `self.last_dir = out_dir`。
- メッセージ本文: `f"一括出力: {len(saved)} 件を保存しました。\n{out_dir}"`。
- スキップがあれば、先頭 5 件を `" / "` で連結して `f"\n\nスキップ {len(skipped)} 件: {head}"` を追記。5 件超なら末尾に `" ほか"`（先頭スペース付き）。
- 完了ダイアログ: `QtWidgets.QMessageBox.information(self, "一括出力", msg)`。
- ステータス: `self._set_status(f"一括出力: {len(saved)} 件保存（{out_dir}）")`。

---

## 依存する外部メソッド/属性（このファイルでは定義しない・前提）

- 図関連: `self.fig`, `self.ax`, `self.canvas`, `self._aspect_ratio()`, `self._export_figsize()`, `self._apply_aspect()`。
- ウィジェット: `self.dpi_spin`, `self.transparent_check`, `self.title_edit`, `self.xlabel_edit`, `self.ylabel_edit`, `self.x_combo`, `self.chart_combo`, `self.decimate_check`, `self.xmin/xmax/ymin/ymax`。
- データ/状態: `self.datasets`（`{label: DataFrame}` の順序付き dict）, `self.series_styles`, `self.last_dir`, `self.font_name`（無い場合あり）。
- ロジック: `self._use_leftmost_x()`, `self._selected_series_items()`, `self._style_key(fl, col)`, `self._auto_y_label(prim_y, ctype)`, `self._range_pair(min, max, axis_name, issues)`, `self._plot_format_kwargs()`, `self._set_status(text)`。
- 外部モジュール: `batch_render`（`render_one`, `render_sequential`）。

---

## 定数・固定値・日本語文字列（正確値）

- チャート種別の分岐に使う文字列リテラル: `"棒"`, `"横棒"`, `"積み上げ棒"`, `"円"`（→ categories 系）／`"折れ線"`, `"散布図"`（→ x/yerr/axis 付き系列）／それ以外は「ヒストグラム/箱ひげ」扱い。
- `_safe_filename` 正規表現: `r'[\\/:*?"<>|]+'` → `"_"`、空なら `"graph"`。
- 保存ダイアログのフィルタ: `"PNG (*.png);;JPEG (*.jpg);;PDF (*.pdf);;SVG (*.svg);;EPS (*.eps)"`。
- 既定保存名: `"graph.png"`。
- `_batch_options_dialog` の `fmt_combo` 項目: `["png", "jpg", "pdf", "svg"]`。
- DPI スピン: range `50〜1200`、step `50`。
- ダイアログタイトル類: `"グラフ画像を保存"`, `"一括画像保存の設定"`, `"一括出力フォルダを選択"`, `"保存エラー"`, `"コピーエラー"`, `"情報"`, `"一括出力"`。
- ツールチップ: `"グラフタイトル。{name} はファイル名（拡張子なし）に置き換わります。"`。
- info ラベル文言（2 行）と `"color:#666;"`、OK ボタン文言 `"フォルダを選んで保存..."` は上記参照。
- ステータス/メッセージ文言は上記各メソッドの記述どおり（全角括弧 `（）`・読点・改行位置まで一致させる）。
- `BATCH_PARALLEL_THRESHOLD = 64`（並列しきい値）、`DECIMATE_TARGET = 8000`（間引きしきい値）。ワーカー数上限 `8`。

---

## 落とし穴（再現時に必ず守る）

- **Mixin 規約**: 本ファイルは `from graph_app_common import *` で始まり、`class BatchMixin:` のメソッド束のみ。`__init__` を持たない。`Qt*` 等は import * 経由で得る。
- **`@staticmethod` の置き場所**: `_safe_filename` は装飾 `@staticmethod` ごとこの Mixin に置く。`self` を取らない。
- **Qt6 スコープ付き列挙**: `QtWidgets.QDialogButtonBox.StandardButton.Ok/Cancel`, `QtWidgets.QDialog.DialogCode.Accepted`, `QtCore.Qt.CursorShape.WaitCursor` を必ずフルパスで。短縮形（`QtCore.Qt.WaitCursor` 等）は使わない。
- **spawn 安全**: `batch_render` は Qt を import しない別モジュール。本ファイルからは関数呼び出し直前に `import batch_render`。タスク dict は picklable に保つ（`figsize` は `tuple(...)`、`ratio` は `None`、Qt オブジェクトを入れない）。
- **比率指定時は bbox トリミングしない**: `_save_current_figure` で `ratio` ありのときは `bbox_inches` を渡さず figsize で比率を作る。終了後 `finally` で `set_size_inches(orig)` → `_apply_aspect()` → `tight_layout()` → `draw_idle()` で必ず画面表示を復元。
- **カーソル復元**: 一括出力中の override カーソルは `finally` で必ず `restoreOverrideCursor()`。
- **並列失敗の握り潰し**: プール作成失敗時は `saved=[]` にリセットして逐次で全件作り直す（部分結果を残さない）。各タスク失敗は `skipped` に積んで全体は止めない。
- **`fmt` 変数の二義性に注意**: `batch_export` 内の `fmt = self._plot_format_kwargs()`（描画オプション dict）と、出力拡張子 `ext`／`_save_current_figure(..., fmt=...)`（画像フォーマット名）は別物。取り違えない。
- **`copy_figure` は `fmt="png"` 必須**: BytesIO は拡張子を持たないため明示しないと保存形式が決まらない。
- **デシメーション条件**: `decimate_check` ON かつ `ctype in ("折れ線","散布図")` のときだけ `DECIMATE_TARGET`、それ以外 `0`。
- **タスク dict のキー名**は `batch_render.render_one` と一字一句一致させる（`series/categories/ctype/title/xlabel/ylabel/xlim/ylim/sec_label/max_points/fmt/ratio/figsize/tight/dpi/transparent/path/font_name`）。
