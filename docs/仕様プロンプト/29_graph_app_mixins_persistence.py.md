# [29/30] graph_app_mixins/persistence.py の仕様

## 指示

- この仕様だけを読んで `graph_app_mixins/persistence.py` を**完全な形**で実装し、ファイル全体を出力してください。
- `pass`・`TODO`・省略・要約・「ここは元コード参照」等は**一切禁止**です。すべてのメソッドを実際に動作する本体まで書ききってください。
- 出力が長くて途中で切れた場合は、ユーザーが「続き」と言ったら**最後まで**続きを出力してください。

### アプリ全体の前提（関連分のみ）

- Python 3.10+ / GUI=PySide6(Qt6)。Qt は必ず matplotlib 経由で取得する（`from matplotlib.backends.qt_compat import QtCore, QtGui, QtWidgets` など）。本ファイルでは `QtWidgets`（メッセージボックス・ファイルダイアログ）と `QtCore`（チェック状態の列挙）を使う。
- Qt6 の列挙は**スコープ付き**で書く。本ファイルでは `QtCore.Qt.CheckState.Checked` / `QtCore.Qt.CheckState.Unchecked` を使用。アイテムの識別子取得には共通名 `UserRole`（＝ `QtCore.Qt.ItemDataRole.UserRole`）を使う。
- `GraphApp` は 10 個の Mixin ＋ `QtWidgets.QMainWindow` の多重継承で構成され、`__init__` / `closeEvent` は本体側にある。各 Mixin は `from graph_app_common import *` で始まるメソッド束で、**`__init__` を持たない**。本ファイルの `PersistenceMixin` もそのひとつ。
- `plotter.py` は facade。本ファイルからは `plotter.format_eng(...)` を呼ぶ（工学接頭辞付き数値整形）。
- 設定の保存・読込・自動セッションは `config_io`（Qt 非依存の純粋ユーティリティ）に委譲する。
- 復元中は連鎖再描画を抑制するため `self._suspend_redraw` を立てる（構築・復元中フラグ）。

---

## ファイルの役割 / 責務

モジュール先頭の docstring（趣旨をそのまま）:

```
"""PersistenceMixin: GraphApp から分離した PersistenceMixin 群（挙動は本体と同一）。"""
```

責務:

- **ヘルプ／バージョン情報ダイアログ**の表示（`show_help` / `show_about`）。
- 現在の UI 状態をまるごと 1 個の `dict` に**収集**する（`_collect_config`）。これがアプリの「設定」の正本。
- 設定 dict を UI 各ウィジェットへ**適用（復元）**する（`_apply_config` / `_apply_config_inner`）。復元中は再描画を抑制。
- 設定ファイルの**保存ダイアログ／読込ダイアログ**（`save_config_dialog` / `load_config_dialog`）。
- 起動時の**前回セッション自動復元**（`_try_restore_session`）。

設計方針: UI ⇔ dict の往復は完全に対称（`_collect_config` で書き出したキーを `_apply_config_inner` がすべて読み戻す）。復元は堅牢に行い、欠損キーはすべて既定値でフォールバックする（`cfg.get(key, default)`）。Y 系列の選択状態は不安定なインデックスではなく**安定した (ファイル, 列) 識別子**で照合する。

---

## 依存（import するもの）

ファイル冒頭（docstring の直後）で、ワイルドカード import 一行のみ:

```python
from graph_app_common import *  # noqa: F401,F403
```

ここから `QtWidgets` / `QtCore` / `os` / `UserRole` / `plotter` / `config_io` などが供給される前提。**個別の import を追加してはならない。**

---

## クラス構造

```python
class PersistenceMixin:
    ...
```

- `__init__` を**持たない**（Mixin 規約）。`self` は `GraphApp`（QMainWindow＋各 Mixin）のインスタンスを指し、他 Mixin が用意したウィジェット属性・ヘルパーを自由に参照する。
- メソッドはインスタンスメソッドのみ（`@staticmethod` は無し）。

---

## 公開 API（メソッド一覧と詳細）

### `def show_help(self):`

- `QtWidgets.QMessageBox.information(self, "使い方", <本文>)` を表示する。
- 本文は以下の文字列を**そのまま**（改行 `\n` 含め完全一致で）連結したもの:

```
【基本の流れ】
1. 『データ』タブで「ファイル追加」（ドラッグ&ドロップ可）
2. X軸の列を選び、Y軸（値）は描きたい系列にチェック（行クリックでON/OFF・全選択ボタンあり）
3. 「グラフを描画」(F5)。『リアルタイム更新』ONなら設定変更が即反映
4. 右端の『グラフ書式調整』パネルで種別・色・軸範囲・系列スタイルなどを編集
5. 波形は『オシロ/解析』タブで「解析実行」「FFT表示」「オシロスコープ表示」

【出力】右端パネルの画像出力、またはメニュー「ファイル」から保存／コピー
【グラフ種別と列】棒/円は1ファイル、折れ線/散布図は複数ファイル重ね描き可
```

（注: 「2.」行の末尾と「5.」行の末尾の直後に空行 `\n\n` が入る。実装では `"…"` の文字列連結で組み立てる。）

### `def show_about(self):`

- `QtWidgets.QMessageBox.about(self, "バージョン情報", <本文>)` を表示する。
- 本文（最後の行は f-string）:

```
CSV / TSV / 波形 グラフ・解析ツール
PySide6 + matplotlib 製
日本語フォント: {self.font_name or '未検出'}
```

- 最終行は `f"日本語フォント: {self.font_name or '未検出'}"`。`self.font_name` が falsy なら `未検出` と表示。

### `def _collect_config(self):`

現在の UI 状態を `dict` にして返す。**キーと値の対応は以下を完全一致で**（並び順もこの通り）:

| キー | 値の式 |
|---|---|
| `"files"` | `[self.meta[l]["path"] for l in self.datasets]` |
| `"x_col"` | `self.x_combo.currentText()` |
| `"x_leftmost"` | `self.xleft_check.isChecked()` |
| `"selected_y"` | `[[fl, col] for fl, col, _ in self._selected_series_items()]` |
| `"chart_type"` | `self.chart_combo.currentText()` |
| `"title"` | `self.title_edit.text()` |
| `"xlabel"` | `self.xlabel_edit.text()` |
| `"ylabel"` | `self.ylabel_edit.text()` |
| `"fonts"` | `self._fonts()` |
| `"grid"` | `self.grid_check.isChecked()` |
| `"legend"` | `self.legend_check.isChecked()` |
| `"legend_loc"` | `self.legend_loc.currentText()` |
| `"show_filename"` | `self.show_filename_check.isChecked()` |
| `"show_ext"` | `self.show_ext_check.isChecked()` |
| `"frame_width"` | `self.frame_width.value()` |
| `"grid_width"` | `self.grid_width.value()` |
| `"xmin"` | `self.xmin.text()` |
| `"xmax"` | `self.xmax.text()` |
| `"ymin"` | `self.ymin.text()` |
| `"ymax"` | `self.ymax.text()` |
| `"xtick"` | `self.xtick_edit.text()` |
| `"ytick"` | `self.ytick_edit.text()` |
| `"xunit"` | `self.xunit_edit.text()` |
| `"yunit"` | `self.yunit_edit.text()` |
| `"xscale"` | `self.xscale_edit.text()` |
| `"yscale"` | `self.yscale_edit.text()` |
| `"xlog"` | `self.xlog.isChecked()` |
| `"ylog"` | `self.ylog.isChecked()` |
| `"bins"` | `self.bins_spin.value()` |
| `"pct"` | `self.pct_check.isChecked()` |
| `"trend"` | `self.trend_combo.currentText()` |
| `"trend_degree"` | `self.trend_degree.value()` |
| `"trend_window"` | `self.trend_window.value()` |
| `"trend_eq"` | `self.trend_eq.isChecked()` |
| `"trend_color"` | `getattr(self, "trend_color", "")` |
| `"data_labels"` | `self.data_labels_check.isChecked()` |
| `"aspect"` | `self.aspect_combo.currentText()` |
| `"aspect_w"` | `self.aspect_w.value()` |
| `"aspect_h"` | `self.aspect_h.value()` |
| `"bg_color"` | `getattr(self, "bg_color", "")` |
| `"export_dpi"` | `self.dpi_spin.value()` |
| `"transparent"` | `self.transparent_check.isChecked()` |
| `"recent_files"` | `self.recent_files` |
| `"styles"` | `self.series_styles` |
| `"scope"` | `self._scope_dict()` |
| `"npeaks"` | `self.npeaks.value()` |

注記:
- `"selected_y"` は `_selected_series_items()` が返す `(ファイル, 列, ?)` の 3 要素タプル列から先頭 2 要素のみを `[fl, col]` の**リスト**として並べる（JSON ラウンドトリップでタプルがリスト化されることを前提に、復元側でも list/tuple 両対応で照合する）。
- `"trend_color"` / `"bg_color"` は属性が未設定でも落ちないよう `getattr(..., "")`。
- `"fonts"` / `"scope"` は他 Mixin のヘルパー（`_fonts()` は plotting Mixin、`_scope_dict()` は plotting Mixin、`_selected_series_items()` は data_io Mixin）に委譲。

### `def _apply_config(self, cfg, load_files=True):`

`_apply_config_inner` の**ラッパー**。復元中の連鎖再描画を抑制する:

```
prev_suspend = self._suspend_redraw
self._suspend_redraw = True            # 復元中の連鎖再描画を抑制
try:
    self._apply_config_inner(cfg, load_files)
finally:
    self._suspend_redraw = prev_suspend
```

- `try/finally` で必ず元の `_suspend_redraw` 値に戻す（ネスト呼び出しに耐える）。

### `def _apply_config_inner(self, cfg, load_files=True):`

`cfg`（設定 dict）を UI 各所へ適用する。**処理順序が重要**なので以下の順で実装する。すべて `cfg.get(key, default)` で欠損フォールバックする。

1. **recent_files の復元**: `rec = cfg.get("recent_files")`。`isinstance(rec, list)` のときのみ、`str` 要素だけを抽出し先頭 **12 件**に切り詰めて `self.recent_files` に代入 → `self._rebuild_recent_menu()`。
   ```
   self.recent_files = [p for p in rec if isinstance(p, str)][:12]
   ```
2. **ファイル読込**（`load_files` が真のときのみ）: `cfg.get("files", [])` の各 `p` について `os.path.isfile(p)` が真なら `self._load_file(p)`。ループ後に `self._refresh_columns()`。
3. **X 軸列の選択**: `cfg.get("x_col")` が真なら `self.x_combo.findText(cfg["x_col"])`、見つかれば（`>= 0`）`setCurrentIndex`。
4. `self.xleft_check.setChecked(bool(cfg.get("x_leftmost", False)))`。
5. **再度** `self._refresh_columns()` を呼ぶ（X 設定変更後に列リストを再構築）。
6. **Y 選択の復元**（安定識別子で照合）:
   - `want = set()` を作り、`cfg.get("selected_y", [])` の各要素 `p` について、`isinstance(p, (list, tuple)) and len(p) == 2` なら `want.add((p[0], p[1]))`（タプル化）。
   - `self.y_list.blockSignals(True)` の間に、`self.y_list.count()` 個のアイテムを走査:
     - `it = self.y_list.item(i)`
     - `it.setCheckState(QtCore.Qt.CheckState.Checked if it.data(UserRole) in want else QtCore.Qt.CheckState.Unchecked)`
   - 走査後に `self.y_list.blockSignals(False)`。
   - **落とし穴**: `it.data(UserRole)` は data_io 側で `(ファイル, 列)` のタプルがセットされている前提。`want` もタプルにそろえること（list のままだと一致しない）。
7. **系列スタイルのマージ**: `self.series_styles.update(cfg.get("styles", {}) or {})`（`None` でも空 dict にフォールバック）。
8. 以降、各ウィジェットへ値を流し込む（**既定値はすべて以下の通り**）:

| 適用先 | 式（既定値含む） |
|---|---|
| `chart_combo` | `setCurrentText(cfg.get("chart_type", "折れ線"))` |
| `title_edit` | `setText(cfg.get("title", ""))` |
| `xlabel_edit` | `setText(cfg.get("xlabel", ""))` |
| `ylabel_edit` | `setText(cfg.get("ylabel", ""))` |
| フォント `f = cfg.get("fonts", {})` | 下記参照 |
| `fs_title` | `setValue(f.get("title", 12))` |
| `fs_label` | `setValue(f.get("label", 10))` |
| `fs_tick` | `setValue(f.get("tick", 9))` |
| `fs_legend` | `setValue(f.get("legend", 9))` |
| `fs_annot` | `setValue(f.get("annot", 9))` |
| `grid_check` | `setChecked(cfg.get("grid", True))` |
| `legend_check` | `setChecked(cfg.get("legend", True))` |
| `legend_loc` | `setCurrentText(cfg.get("legend_loc", "best"))` |
| `show_filename_check` | `setChecked(cfg.get("show_filename", True))` |
| `show_ext_check` | `setChecked(cfg.get("show_ext", True))` |
| `frame_width` | `setValue(cfg.get("frame_width", 0.8))` |
| `grid_width` | `setValue(cfg.get("grid_width", 0.8))` |
| `xmin` | `setText(cfg.get("xmin", ""))` |
| `xmax` | `setText(cfg.get("xmax", ""))` |
| `ymin` | `setText(cfg.get("ymin", ""))` |
| `ymax` | `setText(cfg.get("ymax", ""))` |
| `xtick_edit` | `setText(cfg.get("xtick", ""))` |
| `ytick_edit` | `setText(cfg.get("ytick", ""))` |
| `xunit_edit` | `setText(cfg.get("xunit", ""))` |
| `yunit_edit` | `setText(cfg.get("yunit", ""))` |
| `xscale_edit` | `setText(cfg.get("xscale", "1"))` |
| `yscale_edit` | `setText(cfg.get("yscale", "1"))` |
| `xlog` | `setChecked(cfg.get("xlog", False))` |
| `ylog` | `setChecked(cfg.get("ylog", False))` |
| `bins_spin` | `setValue(cfg.get("bins", 30))` |
| `pct_check` | `setChecked(cfg.get("pct", True))` |
| `trend_combo` | `setCurrentText(cfg.get("trend", "なし"))` |
| `trend_degree` | `setValue(cfg.get("trend_degree", 2))` |
| `trend_window` | `setValue(cfg.get("trend_window", 5))` |
| `trend_eq` | `setChecked(cfg.get("trend_eq", True))` |

9. **トレンド色の復元**: `tc = cfg.get("trend_color", "")`。
   - `tc` が真なら: `self.trend_color = tc` / `self.trend_color_btn.setText("色: " + tc)` / `self.trend_color_btn.setStyleSheet(f"background:{tc};")`。
   - 偽なら: `self._reset_trend_color()` を呼ぶ。
10. `data_labels_check.setChecked(cfg.get("data_labels", False))`。
11. **アスペクト比**（**順序に注意** — w/h を先に設定してから combo を設定する）:
    - `self.aspect_w.setValue(int(cfg.get("aspect_w", 16)))`
    - `self.aspect_h.setValue(int(cfg.get("aspect_h", 9)))`
    - `self.aspect_combo.setCurrentText(cfg.get("aspect", "自動（画面に合わせる）"))`
    - 既定アスペクト文字列は **`"自動（画面に合わせる）"`**（全角丸括弧）。`aspect_w` / `aspect_h` は `int(...)` でキャスト。
12. **背景色の復元**: `bgc = cfg.get("bg_color", "")`。
    - 真なら: `self.bg_color = bgc` / `self.bg_btn.setText("背景色: " + bgc)` / `self.bg_btn.setStyleSheet(f"background:{bgc};")`。
    - 偽なら: `self._reset_bg_color()`。
13. `dpi_spin.setValue(cfg.get("export_dpi", 150))` / `transparent_check.setChecked(cfg.get("transparent", False))`。
14. **オシロスコープ設定の復元**: `sc = cfg.get("scope", {})`。
    - `self.scope_check.setChecked(sc.get("enabled", False))`
    - `self.tdiv.setCurrentText(plotter.format_eng(sc.get("t_per_div") or 1e-3) + "s")`
    - `self.vdiv.setCurrentText(plotter.format_eng(sc.get("v_per_div") or 0.5))`
    - `self.xpos.setText(str(sc.get("x_pos", 0)))` / `self.ypos.setText(str(sc.get("y_pos", 0)))`
    - `self.xdivs.setValue(sc.get("x_divs", 10))` / `self.ydivs.setValue(sc.get("y_divs", 8))`
    - 注: `t_per_div` 既定は `1e-3`、`v_per_div` 既定は `0.5`。`or` 演算子で `None`/`0` を既定に置換し、`plotter.format_eng(...)` で工学表記の文字列にしてから `tdiv` には `"s"`、`vdiv` にはそのまま追加。
15. `self.npeaks.setValue(cfg.get("npeaks", 5))`。
16. 最後に **`self._rebuild_style_table()`** → **`self._on_chart_type_change()`** をこの順で呼ぶ（スタイル表の再構築と種別依存 UI の整合）。

### `def save_config_dialog(self):`

- `QtWidgets.QFileDialog.getSaveFileName(self, "設定を保存", os.path.join(self.last_dir, "graph_config.json"), "JSON (*.json)")` で保存先 `path` を取得（戻り値タプルの 2 番目は `_` で捨てる）。
- `path` が空なら `return`。
- `try` 内で `config_io.save_config(self._collect_config(), path)` → `self._set_status(f"設定を保存: {path}")`。
- 例外時（`except Exception as e:  # noqa: BLE001`）は `QtWidgets.QMessageBox.critical(self, "保存エラー", str(e))`。

### `def load_config_dialog(self):`

- `QtWidgets.QFileDialog.getOpenFileName(self, "設定を読み込み", self.last_dir, "JSON (*.json)")` で `path` を取得。
- `path` が空なら `return`。
- `cfg = config_io.load_config(path)`。`cfg` が falsy なら `QtWidgets.QMessageBox.warning(self, "読込エラー", "設定を読み込めませんでした。")` して `return`。
- そうでなければ `self._apply_config(cfg)` → `self.draw_graph()` → `self._set_status(f"設定を読み込み: {path}")`。

### `def _try_restore_session(self):`

- `cfg = config_io.load_last_session()`。
- `cfg` が falsy または `cfg.get("files")` が falsy なら **`return False`**。
- `try` 内: `self._apply_config(cfg)` → `self.datasets` が真なら `self.draw_graph()` → `self._set_status("前回のセッションを復元しました。")` → `return True`。
- `except Exception:` では `return False`（起動を妨げないため、失敗は握りつぶす）。

---

## 定数・固定文字列（正確な値）

復元時の既定値・ラベル文字列を**そのまま**使うこと（再現に必須）:

- recent_files 切り詰め上限: **12**。
- フォントサイズ既定: `title=12`, `label=10`, `tick=9`, `legend=9`, `annot=9`。
- `frame_width` / `grid_width` 既定: `0.8`。
- `xunit` / `yunit`（単位ラベル）既定: `""`、`xscale` / `yscale`（換算倍率）既定: `"1"`。
- `bins` 既定: `30`、`pct` 既定: `True`。
- `trend` 既定: `"なし"`、`trend_degree=2`、`trend_window=5`、`trend_eq=True`。
- `chart_type` 既定: `"折れ線"`、`legend_loc` 既定: `"best"`。
- `aspect` 既定: `"自動（画面に合わせる）"`、`aspect_w=16`、`aspect_h=9`。
- `export_dpi` 既定: `150`、`transparent` 既定: `False`。
- scope 既定: `t_per_div=1e-3`、`v_per_div=0.5`、`x_pos=0`、`y_pos=0`、`x_divs=10`、`y_divs=8`、`enabled=False`。
- `npeaks` 既定: `5`。
- ボタンラベル: トレンド色 `"色: " + tc`、背景色 `"背景色: " + bgc`。スタイルシートは `f"background:{色};"`。
- `tdiv` の単位サフィックス: `"s"`（`format_eng` 出力の後ろに付ける）。`vdiv` は無単位。
- ダイアログタイトル文字列: `"使い方"`, `"バージョン情報"`, `"設定を保存"`, `"設定を読み込み"`, `"保存エラー"`, `"読込エラー"`。
- ステータス文言: `f"設定を保存: {path}"`, `f"設定を読み込み: {path}"`, `"前回のセッションを復元しました。"`。
- 既定保存ファイル名: `"graph_config.json"`、ファイルフィルタ: `"JSON (*.json)"`。

---

## 再現に必須の細部・エッジケース

- **対称性**: `_collect_config` のキー集合と `_apply_config_inner` の `cfg.get(...)` キー集合は完全に対応している。新たなキーを足す/消すときは両方を同時に更新する。
- **`_suspend_redraw` のネスト退避**: `_apply_config` は元の値を `prev_suspend` に退避し `finally` で戻す。直書きで `False` に戻してはならない（ネスト時に外側の抑制を壊す）。
- **Y 選択の識別子照合**: インデックスや表示名ではなく `(ファイル, 列)` のタプルで照合。JSON 経由でリスト化されるため、収集側は `[fl, col]`、復元側は `tuple` 化して `set` で照合。`blockSignals(True/False)` で囲み、チェック変更による連鎖シグナルを抑制する。
- **`_refresh_columns()` を 2 回呼ぶ**: 1 回目はファイル読込直後（`load_files` 時）、2 回目は X 軸関連設定（`x_col` / `xleft_check`）反映後。これにより Y リストが最新の列で再構築されてから Y 選択復元が走る。順序を変えると選択が当たらない。
- **`getattr` ガード**: `trend_color` / `bg_color` は属性が無い段階でも収集できるよう `getattr(self, ..., "")`。
- **`styles` の `None` フォールバック**: `cfg.get("styles", {}) or {}`（`None` 保存値でも `.update()` が落ちない）。
- **scope の `or` 既定**: `sc.get("t_per_div") or 1e-3` は値が `None`/`0`/欠損のとき既定に置換する（`0` も置換される点に注意）。
- **セッション復元の失敗握りつぶし**: `_try_restore_session` は例外で `False` を返すのみ。アプリ起動を絶対に止めない。
- **末尾呼び出し順**: `_apply_config_inner` の最後は必ず `_rebuild_style_table()` → `_on_chart_type_change()`。これが種別に応じた UI 有効化/無効化とスタイル表の再生成を担う。

---

## 関係する落とし穴（このファイル特有）

- **Qt6 スコープ付き列挙**: チェック状態は `QtCore.Qt.CheckState.Checked` / `QtCore.Qt.CheckState.Unchecked`（旧 `QtCore.Qt.Checked` は不可）。`UserRole` は共通名（= `QtCore.Qt.ItemDataRole.UserRole`）を使う。
- **Mixin 規約**: 本クラスは `__init__` を持たない。`self.x_combo` などのウィジェットは他 Mixin の構築メソッドで生成済みである前提で参照する。
- **facade 経由呼び出し**: 数値整形は必ず `plotter.format_eng(...)`（直接 import しない）。設定 IO は `config_io.save_config` / `config_io.load_config` / `config_io.load_last_session`。
- **monospace 不使用**: 本ファイルは日本語ラベルを多く含むが、`family="monospace"` を指定する箇所は無い（指定しないこと）。
- **grid linewidth=None 回避**: 本ファイルでは grid 幅を `cfg.get("grid_width", 0.8)` で必ず数値にして `grid_width` スピンボックスへ流す。描画側で `None` を `float()` に渡さない設計に整合させる（既定 `0.8` を欠かさないこと）。
- **`from graph_app_common import *` のみ**で必要シンボル（`QtWidgets`/`QtCore`/`os`/`UserRole`/`plotter`/`config_io`）が供給される。個別 import を足さない。
