# [22/30] graph_app_mixins/style_table.py の仕様

## 指示（必須・厳守）

- **この仕様だけを読んで `graph_app_mixins/style_table.py` を完全な形で実装し、ファイル全体を出力すること。**
- `pass` / `TODO` / 「…」/ 省略 / 要約 / 「元コード参照」は**一切禁止**。すべてのメソッドを実体のあるコードで完成させること。
- 出力が長くて途中で切れた場合は、ユーザーが「続き」と言うので、**残りを最後まで**出力すること（重複なく接続できる形で）。
- 本ファイルは `class StyleTableMixin:` という**1つの Mixin クラスのみ**を定義する。`__init__` は持たない（GraphApp 本体が持つ）。`@staticmethod` は装飾ごとこの Mixin に置く。

### アプリ全体の前提（このファイルに関係する分のみ）

- Python 3.10+ / GUI=PySide6(Qt6)。Qt は必ず matplotlib 経由で取得する（このファイル自身は import 文を持たず、先頭の `from graph_app_common import *` で `QtCore`/`QtGui`/`QtWidgets`、`plotter`、`os`、`UserRole`、`LazyColumnCombo` 等をまとめて取り込む）。
- Qt6 列挙は**スコープ付き**で書く（例: `QtCore.Qt.CheckState.Checked` / `QtCore.Qt.CheckState.Unchecked` / `QtCore.Qt.ItemDataRole.UserRole` / `QtCore.Qt.ItemFlag.ItemIsEditable`）。
- GraphApp は複数 Mixin ＋ `QtWidgets.QMainWindow` の多重継承。各 Mixin は `from graph_app_common import *` で始まるメソッド束で、`__init__` を持たない。`self.xxx` 属性・他 Mixin のメソッド（`self.draw_graph()`、`self._request_redraw()`、`self._selected_series_items()`、`self._refresh_columns()`、`self._rebuild_series_bar()`、`self._rebuild_style_table()`、`self._fonts()`、`self._draw_placeholder()` 等）は実行時に解決される前提でよい。
- 再描画はデバウンス（`QTimer` 単発 = `self._redraw_timer`）＋再入防止（`self._drawing`）＋構築/復元中の抑制フラグ（`self._suspend_redraw`）＋初回描画済みフラグ（`self._has_drawn`）で制御する。
- 日本語に `family="monospace"` を使わない（□化け回避）。グリッドの `linewidth` に `None` を渡さない（このファイルでは直接扱わないが、凡例フォントは `f.get("legend") or f.get("tick", 9)` のように `None` 回避で取る）。

---

## ファイルの役割 / 責務

`StyleTableMixin` は GraphApp から分離された Mixin で、docstring は
`"""StyleTableMixin: GraphApp から分離した StyleTableMixin 群（挙動は本体と同一）。"""`。

担当する責務は次のとおり：

1. **X軸の選択ロジック**（「一番左の列をX軸」トグル、X名コンボの有効/無効、X値の取り出し、既定X軸ラベル）。
2. **Y系列の選択操作**（チェックの一括設定・全選択/全解除・反転・ソロ表示・非表示・ダブルクリックで単独表示・右クリックメニュー）と、選択変更に伴う再構築のオーケストレーション。
3. **既定の軸ラベル生成**（系列名から Y軸ラベルを自動生成する `_auto_y_label`、主軸系列だけから作る `_effective_y_label`）と**凡例ラベル生成**（`_series_label`、`_file_display_name`）。
4. **系列スタイル表（`self.style_table` = `QTableWidget`）の差分構築**（`_rebuild_style_table` / `_build_style_row`）と、各セルウィジェットからのスタイル変更ハンドリング（`_set_style`）。
5. **色選択ダイアログ**（系列色・背景色・近似曲線色のピック/リセット）。
6. **スタイル変更の高速パス**（全再描画せずに該当 `Line2D` アーティストへ直接反映する `_try_style_fastpath` / `_build_style_artist_map` / `_rebuild_legend_inplace`）。

---

## 依存（import するもの）

ファイル先頭はこの1行のみ：

```python
# -*- coding: utf-8 -*-
"""StyleTableMixin: GraphApp から分離した StyleTableMixin 群（挙動は本体と同一）。"""
from graph_app_common import *  # noqa: F401,F403
```

`from graph_app_common import *` 経由で利用する主なもの：

- `QtCore` / `QtGui` / `QtWidgets`（matplotlib 経由の Qt）。
- `plotter`（facade。`plotter.CHART_INFO`、`plotter.DEFAULT_STYLE`、`plotter.LINESTYLES`、`plotter.MARKERS`、`plotter.SERIES_AXES`、`plotter.SERIES_KINDS` を参照）。
- `UserRole`（= `QtCore.Qt.ItemDataRole.UserRole`）。
- `LazyColumnCombo`（誤差列コンボ。列一覧を初回ポップアップ時に遅延展開する `QComboBox` サブクラス。`LazyColumnCombo(get_cols, current, parent=None)` の形で生成）。
- `os`（`os.path.splitext` を使用）。
- `matplotlib.lines.Line2D` は `_build_style_artist_map` 内で**関数ローカルに遅延 import**する（`from matplotlib.lines import Line2D`）。

参照する `plotter` 側の定数（**正確な値**。`plotter.py` / `plotter_draw.py` 由来）：

```python
DEFAULT_STYLE = {"color": None, "linestyle": "-", "linewidth": 1.5,
                 "marker": "", "markersize": 4.0, "alpha": 1.0}
LINESTYLES = {"実線": "-", "破線": "--", "一点鎖線": "-.", "点線": ":", "なし": "None"}
MARKERS = {"なし": "", "丸": "o", "四角": "s", "三角": "^", "菱形": "D",
           "× ": "x", "＋": "+", "点": "."}   # 「× 」は末尾に半角スペースを含む
SERIES_KINDS = {"自動": "", "折れ線": "line", "棒": "bar", "面": "area", "散布図": "scatter"}
SERIES_AXES = {"主軸": "primary", "第2軸": "secondary"}
# CHART_INFO[種別] は {"use_x": bool, "multi_y": bool, "multi_file": bool, "hint": str}
```

---

## モジュール／クラス定数

クラス本体に置く定数：

- `_STYLE_VISUAL = frozenset({"color", "linewidth", "linestyle", "marker", "markersize"})`
  - 「全再描画せずに該当アーティストへ直接反映できる」純視覚スタイル属性の集合。`_try_style_fastpath` の対象判定に使う。`_set_style` 本体より後（`_pick_*` の後あたり、`_set_style` の直前）に、コメント `# 純視覚スタイル（全再描画せず該当アーティストへ直接反映できるもの）` を付けて定義する。

---

## 公開 API（全メソッドの完全シグネチャと挙動）

以下、定義順に列挙する。すべて `StyleTableMixin` のメソッド。`@staticmethod` のものは明記する。

### X 軸関連

#### `def _on_x_changed(self, *_):`
- X名コンボ変更時のハンドラ。`self._request_redraw()` を呼ぶだけ。

#### `def _on_xleft_toggled(self, on):`
- 「一番左の列をX軸」チェックのトグルハンドラ。docstring 趣旨:『一番左の列をX軸』ON時は名前コンボを無効化し、先頭列をY候補から除外/復帰。
- 処理順:
  1. `self._refresh_columns()`（Y軸候補を作り直し＝先頭列の除外/復帰＋再描画予約。別 Mixin 提供）。
  2. `self._update_x_combo_enabled()`（有効/無効の確定は**最後**に行う）。

#### `def _update_x_combo_enabled(self):`
- X名コンボの有効状態を、グラフ種別と「一番左の列をX軸」から決める。
- `info = plotter.CHART_INFO.get(self.chart_combo.currentText(), {})`
- `self.x_combo.setEnabled(info.get("use_x", True) and not self._use_leftmost_x())`
  - すなわち「種別が X を使う（既定 True）」かつ「左端X指定が OFF」のときのみ有効。

#### `def _use_leftmost_x(self):`
- 「一番左の列をX軸」が有効か。`return bool(getattr(self, "xleft_check", None) and self.xleft_check.isChecked())`
- `xleft_check` 未構築でも安全に `False` を返す（`getattr` で防御）。

#### `def _x_values(self, df):`
- X軸データ列を `numpy` 配列で返す。
  - `self._use_leftmost_x()` が真 → `df.iloc[:, 0].to_numpy()`（位置0の列）。
  - 偽 → `xname = self.x_combo.currentText()`。`xname in df.columns` なら `df[xname].to_numpy()`、なければ `df.iloc[:, 0].to_numpy()`（先頭列にフォールバック）。

#### `def _effective_x_label(self):`
- 既定のX軸ラベルを返す。
  - 左端X ON のとき:
    - `items = self._selected_series_items()`。
    - `items` があれば `df = self.datasets.get(items[0][0])`（先頭系列のファイル名で DataFrame を取得）。`df is not None and len(df.columns)` なら `return str(df.columns[0])`（先頭列名）。
    - それ以外は `return ""`。
  - 左端X OFF のとき: `return self.x_combo.currentText()`。

### Y 軸ラベル / 凡例ラベル

#### `@staticmethod`
#### `def _auto_y_label(names, ctype):`
- 系列名リスト `names` と種別 `ctype` から Y軸の既定ラベルを生成。**static**。
- アルゴリズム:
  1. `ctype == "ヒストグラム"` のとき → `return ""`（Y軸は頻度なのでラベル空）。
  2. `uniq = list(dict.fromkeys(n for n in names if n))`（空文字を除き、出現順を保って重複排除）。
  3. `uniq` が空 → `return ""`。
  4. `len(uniq) == 1` → `return uniq[0]`。
  5. 複数: `joined = " / ".join(uniq)`。`len(joined) <= 40` なら `joined`、超えるなら `f"{uniq[0]} ほか{len(uniq) - 1}系列"`。
- 注意: 区切りは半角スペース＋スラッシュ＋半角スペース `" / "`。閾値は **40**。長い場合の文言は `"{先頭名} ほか{N}系列"`（N = `len(uniq) - 1`）。

#### `def _file_display_name(self, fl):`
- ファイル名表示。「拡張子」トグル（`self.show_ext_check`）がオフなら拡張子を除く。
  - `hasattr(self, "show_ext_check") and not self.show_ext_check.isChecked()` のとき → `os.path.splitext(fl)[0]`。
  - それ以外 → `fl` をそのまま。

#### `def _series_label(self, fl, col):`
- 凡例に使う系列ラベル。優先順位: ユーザー上書きラベル ＞ ファイル名表示オプション。
  - `st = self.series_styles.get(self._style_key(fl, col)) or {}`。
  - `st.get("label")` があれば `return st["label"]`。
  - `multi = len(self.datasets) > 1`。
  - `show_fn = (not hasattr(self, "show_filename_check")) or self.show_filename_check.isChecked()`（属性未構築なら True 扱い）。
  - `multi and show_fn` のとき → `return f"{self._file_display_name(fl)} | {col}"`（区切りは半角スペース＋縦棒＋半角スペース ` | `）。
  - それ以外（単一ファイル、または『凡例にファイル名』オフ）→ `return col`（列名のみ）。

#### `def _effective_y_label(self):`
- 既定のY軸ラベル（Y軸名欄が空のとき使用）。主軸の選択系列の「列名」から作る。
- アルゴリズム:
  - `names = []`。
  - `for fl, col, disp in self._selected_series_items():`
    - `st = self.series_styles.get(self._style_key(fl, col)) or {}`。
    - `st.get("axis", "primary") == "secondary"` の系列は**スキップ**（第2軸は右側ラベルになるため除外）。
    - `names.append(st.get("label") or col)`（ユーザーラベルがあればそれ、無ければ列名）。
  - `return self._auto_y_label(names, self.chart_combo.currentText())`。
- 注意: ファイル名は含めず列名ベース。同じ列名が並べば `_auto_y_label` 内の重複排除で 1 つにまとまる。

### Y チェック操作

#### `def _on_y_check_changed(self, _item):`
- Yリスト（`self.y_list`）のチェック変更シグナルハンドラ。
- `self._suspend_redraw` が真なら即 `return`（構築/復元中は無反応）。そうでなければ `self._on_y_selection_changed()`。

#### `def _set_all_checks(self, func):`
- `func(item) -> bool` で各行のチェック状態を一括設定し、まとめて更新。
- 実装:
  - `ck = QtCore.Qt.CheckState.Checked` / `un = QtCore.Qt.CheckState.Unchecked`。
  - `self.y_list.blockSignals(True)`（一括変更中のシグナル抑制）。
  - `for i in range(self.y_list.count()):` → `it = self.y_list.item(i)`、`it.setCheckState(ck if func(it) else un)`。
  - `self.y_list.blockSignals(False)`。
  - 最後に `self._on_y_selection_changed()` を 1 回呼ぶ（まとめて反映）。

#### `def _check_all_y(self, checked):`
- 全行を `checked`（bool）に設定。`self._set_all_checks(lambda it: checked)`。

#### `def _invert_y(self):`
- 各行のチェックを反転。`ck = QtCore.Qt.CheckState.Checked`、`self._set_all_checks(lambda it: it.checkState() != ck)`。

#### `def _on_y_double_clicked(self, item):`
- Y行ダブルクリック → その系列だけにして描画。
- `self._set_all_checks(lambda it: it is item)`（同一性 `is` 比較）。続けて `self.draw_graph()`（デバウンスではなく即描画）。

#### `def _maybe_draw(self):`
- `if self.datasets: self.draw_graph()`（データがあるときのみ即描画）。

### Y リスト右クリックメニュー / ソロ・非表示

#### `def _series_menu(self, item):`
- 系列の表示/非表示メニュー（Yリスト・上部系列バー共通）を構築して返す（`QtWidgets.QMenu`）。
- `menu = QtWidgets.QMenu(self)`。
- `item is not None` のとき、次の順でアクション追加 → 区切り線:
  - `"この系列だけ表示"` → `lambda: self._solo_series(item)`
  - `"この系列を非表示"` → `lambda: self._hide_series(item)`
  - `menu.addSeparator()`
- 続けて常に:
  - `"すべて表示"` → `lambda: (self._check_all_y(True), self._maybe_draw())`
  - `"すべて非表示"` → `lambda: (self._check_all_y(False), self._maybe_draw())`
- `return menu`。
- ラベル文言は上記の正確な日本語文字列。

#### `def _y_list_menu(self, pos):`
- Yリスト右クリックの表示メニュー。
- `item = self.y_list.itemAt(pos)`。
- `self._series_menu(item).exec(self.y_list.viewport().mapToGlobal(pos))`（ビューポート座標→グローバル変換して `exec`）。

#### `def _solo_series(self, item):`
- 指定系列だけ表示（他をすべて非表示）。`self._set_all_checks(lambda it: it is item)` → `self._maybe_draw()`。

#### `def _hide_series(self, item):`
- 指定系列を非表示にする（他はそのまま）。`item.setCheckState(QtCore.Qt.CheckState.Unchecked)` → `self._maybe_draw()`。

### スタイル表のラベル編集

#### `def _on_style_label_edited(self, item):`
- スタイル表の系列名（凡例ラベル）編集を保存して再描画。
- ガード:
  - `if self._suspend_redraw or item.column() != 0: return`（抑制中、または 0 列目以外なら何もしない。系列名は列 0）。
  - `key = item.data(UserRole)`。`if not key: return`（キー未設定の行は無視）。
- `text = item.text().strip()`。
- `st = self.series_styles.setdefault(key, dict(plotter.DEFAULT_STYLE))`。
- `st["label"] = text or None`（空文字なら `None` に正規化＝自動ラベルへ戻す）。
- `self._request_redraw()`。

### 選択変更のオーケストレーション

セクションコメント `# ------------------------------------------------------------ 系列スタイル` を置く。

#### `def _on_y_selection_changed(self):`
- Y選択が変わったときの中心ハンドラ。順に:
  1. `self._rebuild_style_table()`（スタイル表を差分再構築）。
  2. `self._rebuild_series_bar()`（上部の系列選択バーも同期。別 Mixin 提供）。
  3. `self._update_analysis_targets()`。
  4. `self._request_redraw()`。

#### `def _update_analysis_targets(self):`
- 解析系タブの系列コンボを選択系列名で更新。
- `names = [d for _, _, d in self._selected_series_items()]`（表示名のリスト）。
- `combos = [self.analysis_target]`（基本タブの対象コンボは常に対象）。
- 「構築済みなら」追加対象とする属性名（**この順序・名前を厳守**）:
  - `for attr in ("phase_target2", "math_a", "math_b", "ds_target"):` → `if hasattr(self, attr): combos.append(getattr(self, attr))`。
  - `if hasattr(self, "proto_ch"): combos.extend(self.proto_ch)`（`proto_ch` はコンボの**リスト**）。
- 各 `cb` について:
  - `cur = cb.currentText()`（現在値を退避）。
  - `cb.blockSignals(True)` → `cb.clear()` → `cb.addItems(names)`。
  - `idx = cb.findText(cur)`。`idx >= 0` なら `cb.setCurrentIndex(idx)`（同名が残っていれば選択を復元）。
  - `cb.blockSignals(False)`。

### スタイルキー

#### `@staticmethod`
#### `def _style_key(fl, col):`
- スタイルを安定キー（ファイル, 列）で保持。表示名の変化に影響されない。
- `return f"{fl}\t{col}"`（**TAB 区切り**。ファイル名＋`\t`＋列名）。**static**。

### スタイル表の差分構築

#### `def _rebuild_style_table(self):`
- 差分更新で `self.style_table`（`QTableWidget`）を再構築。先頭から一致する行は触らず、最初に異なる行以降だけ作り直す（多系列で 1 系列だけ増減したときの全行再生成を避ける高速化）。
- アルゴリズム:
  1. `items = self._selected_series_items()`（`(fl, col, disp)` のリスト）。
  2. `new_keys = [self._style_key(fl, col) for fl, col, _ in items]`。
  3. `old_keys = [ (self.style_table.item(r, 0).data(UserRole) if self.style_table.item(r, 0) else None) for r in range(self.style_table.rowCount()) ]`（各行 0 列目の `UserRole` に保持したキー。アイテム無しは `None`）。
  4. `if new_keys == old_keys: return`（変化なしなら何もしない）。
  5. 先頭一致数を求める: `i = 0`、`m = min(len(new_keys), len(old_keys))`、`while i < m and new_keys[i] == old_keys[i]: i += 1`。
  6. `prev_suspend = self._suspend_redraw`、`self._suspend_redraw = True`（構築中の signal で再描画/上書きしない）。
  7. `vbar = self.style_table.verticalScrollBar().value()`（縦スクロール位置を退避）。
  8. `self.style_table.setUpdatesEnabled(False)`。
  9. `self.style_table.setRowCount(len(items))`（末尾の増減を反映。行数を新数に合わせる）。
  10. `for r in range(i, len(items)):` → `fl, col, disp = items[r]`、`self._build_style_row(r, fl, col, disp)`（**最初の不一致 `i` から末尾まで**だけ作り直す）。
  11. `self.style_table.setUpdatesEnabled(True)`。
  12. `self.style_table.verticalScrollBar().setValue(vbar)`（スクロール位置を復元）。
  13. `self._suspend_redraw = prev_suspend`（抑制フラグを元へ戻す）。

#### `def _build_style_row(self, r, fl, col, disp):`
- スタイル表の 1 行（**列 0〜8 の 9 列**）を作る。docstring 趣旨:「スタイル表の1行（系列名/色/線種/幅/マーカー/軸/種別/誤差列）を作る。」
- `key = self._style_key(fl, col)`。
- `st = self.series_styles.setdefault(key, dict(plotter.DEFAULT_STYLE))`（既定スタイルのコピーで初期化）。
- **列 0: 系列名（編集可能・凡例ラベル上書き）**
  - `name_item = QtWidgets.QTableWidgetItem(st.get("label") or disp)`（ユーザーラベルがあればそれ、無ければ表示名 `disp`）。
  - `name_item.setData(UserRole, key)`（キーを保持）。
  - `name_item.setFlags(name_item.flags() | QtCore.Qt.ItemFlag.ItemIsEditable)`（編集可能化）。
  - `self.style_table.setItem(r, 0, name_item)`。
- **列 1: 色ボタン**（`QPushButton`、セルウィジェット）
  - `btn = QtWidgets.QPushButton(st.get("color") or "自動")`（色未設定なら表示は「自動」）。
  - `if st.get("color"): btn.setStyleSheet(f"background:{st['color']};")`（設定済みなら背景色を反映）。
  - `btn.clicked.connect(lambda _=False, k=key, b=btn: self._pick_color(k, b))`（**デフォルト引数で key/btn を束縛**。ループ変数キャプチャ事故を避ける）。
  - `self.style_table.setCellWidget(r, 1, btn)`。
- **列 2: 線種コンボ**（`QComboBox`）
  - `cb = QtWidgets.QComboBox(); cb.addItems(list(plotter.LINESTYLES.keys()))`（項目: 実線/破線/一点鎖線/点線/なし）。
  - 現在値の逆引き: `cur_ls = next((k2 for k2, vv in plotter.LINESTYLES.items() if vv == st["linestyle"]), "実線")`（一致無しは「実線」）。
  - `cb.setCurrentText(cur_ls)`。
  - `cb.currentTextChanged.connect(lambda v, k=key: self._set_style(k, "linestyle", plotter.LINESTYLES[v]))`（表示名→matplotlib 値へ変換して保存）。
  - `self.style_table.setCellWidget(r, 2, cb)`。
- **列 3: 線幅スピン**（`QDoubleSpinBox`）
  - `sp = QtWidgets.QDoubleSpinBox(); sp.setRange(0.2, 10); sp.setSingleStep(0.5); sp.setValue(st["linewidth"])`。
  - `sp.valueChanged.connect(lambda v, k=key: self._set_style(k, "linewidth", v))`。
  - `self.style_table.setCellWidget(r, 3, sp)`。
- **列 4: マーカーコンボ**（`QComboBox`）
  - `mb = QtWidgets.QComboBox(); mb.addItems(list(plotter.MARKERS.keys()))`（項目: なし/丸/四角/三角/菱形/「× 」/＋/点）。
  - `cur_mk = next((k2 for k2, vv in plotter.MARKERS.items() if vv == st["marker"]), "なし")`。
  - `mb.setCurrentText(cur_mk)`。
  - `mb.currentTextChanged.connect(lambda v, k=key: self._set_style(k, "marker", plotter.MARKERS[v]))`。
  - `self.style_table.setCellWidget(r, 4, mb)`。
- **列 5: マーカーサイズスピン**（`QDoubleSpinBox`）
  - `msp = QtWidgets.QDoubleSpinBox(); msp.setRange(1, 50); msp.setSingleStep(1); msp.setDecimals(1)`。
  - `msp.setValue(st.get("markersize", 4.0))`（既定 4.0）。
  - `msp.setToolTip("マーカーの大きさ（マーカーを「なし」以外にすると反映）")`（**この正確なツールチップ文言**）。
  - `msp.valueChanged.connect(lambda v, k=key: self._set_style(k, "markersize", v))`。
  - `self.style_table.setCellWidget(r, 5, msp)`。
- **列 6: 軸コンボ（主/第2）**（`QComboBox`、折れ線/散布図で有効）
  - `axb = QtWidgets.QComboBox(); axb.addItems(list(plotter.SERIES_AXES.keys()))`（項目: 主軸/第2軸）。
  - `axb.setCurrentText(next((k2 for k2, vv in plotter.SERIES_AXES.items() if vv == st.get("axis", "primary")), "主軸"))`。
  - `axb.currentTextChanged.connect(lambda v, k=key: self._set_style(k, "axis", plotter.SERIES_AXES[v]))`。
  - `self.style_table.setCellWidget(r, 6, axb)`。
- **列 7: 種別コンボ（複合グラフ用）**（`QComboBox`）
  - `kb = QtWidgets.QComboBox(); kb.addItems(list(plotter.SERIES_KINDS.keys()))`（項目: 自動/折れ線/棒/面/散布図。値は ""/line/bar/area/scatter）。
  - `kb.setCurrentText(next((k2 for k2, vv in plotter.SERIES_KINDS.items() if vv == st.get("kind", "")), "自動"))`。
  - `kb.currentTextChanged.connect(lambda v, k=key: self._set_style(k, "kind", plotter.SERIES_KINDS[v]))`。
  - `self.style_table.setCellWidget(r, 7, kb)`。
- **列 8: 誤差列コンボ（エラーバー）**（`LazyColumnCombo`）
  - `cur_e = st.get("errcol")`。
  - `eb = LazyColumnCombo((lambda fl=fl: list(self.datasets[fl].columns) if fl in self.datasets else []), cur_e if cur_e is not None else None)`
    - 第1引数は「列名リストを返すプロバイダ関数」。**`fl` をデフォルト引数で束縛**して `self.datasets[fl]` の列を返す（存在しなければ空リスト）。
    - 第2引数は現在値（`None` ならなし）。
  - `eb.currentTextChanged.connect(lambda v, k=key: self._set_style(k, "errcol", None if v == "なし" else v))`（表示「なし」は `None` に正規化）。
  - `self.style_table.setCellWidget(r, 8, eb)`。

**列番号の対応表（厳守）:** 0=系列名 / 1=色 / 2=線種 / 3=線幅 / 4=マーカー / 5=マーカーサイズ / 6=軸 / 7=種別 / 8=誤差列。

### 色選択ダイアログ

#### `def _pick_color(self, skey, btn):`
- 系列色をカラーダイアログで選ぶ。
- `col = QtWidgets.QColorDialog.getColor(parent=self)`。
- `if col.isValid():`（キャンセル時は何もしない）
  - `hexc = col.name()`（`#rrggbb`）。
  - `self._set_style(skey, "color", hexc)`。
  - `btn.setText(hexc); btn.setStyleSheet(f"background:{hexc};")`（ボタン表示と背景色を更新）。

#### `def _pick_bg_color(self):`
- プロット領域の背景色を選ぶ（オシロ表示の濃色固定も上書き可能）。
- `col = QtWidgets.QColorDialog.getColor(parent=self)`。
- `if col.isValid():`
  - `self.bg_color = col.name()`。
  - `self.bg_btn.setText("背景色: " + self.bg_color)`（文言 `"背景色: " + 値`）。
  - `self.bg_btn.setStyleSheet(f"background:{self.bg_color};")`。
  - `self._request_redraw()`。

#### `def _reset_bg_color(self):`
- 背景色を自動（通常=白・オシロ=濃色）に戻す。
- `self.bg_color = ""` / `self.bg_btn.setText("背景色: 自動")` / `self.bg_btn.setStyleSheet("")` / `self._request_redraw()`。

#### `def _pick_trend_color(self):`
- 近似曲線の色を選ぶ（空=自動: 各系列と同じ色）。
- `col = QtWidgets.QColorDialog.getColor(parent=self)`。
- `if col.isValid():`
  - `self.trend_color = col.name()`。
  - `self.trend_color_btn.setText("色: " + self.trend_color)`（文言 `"色: " + 値`）。
  - `self.trend_color_btn.setStyleSheet(f"background:{self.trend_color};")`。
  - `self._request_redraw()`。

#### `def _reset_trend_color(self):`
- 近似曲線の色を自動（系列と同じ色）に戻す。
- `self.trend_color = ""` / `self.trend_color_btn.setText("色: 自動")` / `self.trend_color_btn.setStyleSheet("")` / `self._request_redraw()`。

### スタイル設定 / 高速パス

`_pick_*` の後、`_set_style` の直前に定数 `_STYLE_VISUAL`（前述）をコメント付きで置く。

#### `def _set_style(self, skey, attr, value):`
- 系列スタイルを保存し、可能なら高速反映する。
- `self.series_styles.setdefault(skey, dict(plotter.DEFAULT_STYLE))[attr] = value`（既定で初期化してから値を上書き）。
- `if not self._try_style_fastpath(skey, attr, value): self._request_redraw()`
  - 高速パスが成功（True）なら何もしない。少しでも不確実（False）なら従来どおりデバウンス全再描画にフォールバック。

#### `def _build_style_artist_map(self, series, ctype, decimated):`
- `skey -> Line2D` の対応辞書を作る。スタイルのみ変更を即時反映できる「単純な折れ線」だけを対象にする。散布図/誤差バー/棒・面/間引き/混在があれば**空 dict** を返し、全再描画にフォールバックさせる。
- アルゴリズム:
  1. `m = {}`。
  2. `if ctype != "折れ線" or decimated: return m`（折れ線以外、または間引き中は対象外）。
  3. `items = self._selected_series_items()`。`if len(items) != len(series): return m`（対応が取れない）。
  4. `for sr in series:`（1 つでも非・単純線があれば諦める＝安全側）
     - `if (sr.get("kind") or "") not in ("", "line") or sr.get("yerr") is not None: return m`（種別が空/line 以外、または誤差バー付きは除外）。
  5. `from matplotlib.lines import Line2D`（**関数ローカル遅延 import**）。
  6. 内部関数 `def _data_lines(axx):` を定義:
     - データ系列の線だけを順序どおり抽出。近似曲線（ラベルに「近似」を含む）やピークマーカー等の自動ラベル線（ラベルが `"_"` 始まり＝未指定）は除外。
     - `return [ln for ln in axx.get_lines() if isinstance(ln, Line2D) and not str(ln.get_label()).startswith("_") and "近似" not in str(ln.get_label())]`。
  7. `ax = self.ax`、`ax2 = getattr(ax, "_twin_secondary", None)`。
  8. `prim = _data_lines(ax)`、`sec = _data_lines(ax2) if ax2 is not None else []`。
  9. `prim_items = [it for it, sr in zip(items, series) if sr.get("axis") != "secondary"]`。
  10. `sec_items = [it for it, sr in zip(items, series) if sr.get("axis") == "secondary"]`。
  11. `if len(prim_items) != len(prim) or len(sec_items) != len(sec): return m`（本数不一致＝対応不能なら諦める）。
  12. `for (fl, col, _disp), ln in zip(prim_items, prim): m[self._style_key(fl, col)] = ln`。
  13. `for (fl, col, _disp), ln in zip(sec_items, sec): m[self._style_key(fl, col)] = ln`。
  14. `return m`。

#### `def _try_style_fastpath(self, skey, attr, value):`
- 純視覚スタイルの変更を全再描画せず該当 `Line2D` へ反映できれば反映して `True`。少しでも不確実なら `False`（呼び出し側が通常の全再描画を行う）。
- 早期 `return False` するガード（**この順序**）:
  1. `if attr not in self._STYLE_VISUAL: return False`。
  2. `if self._suspend_redraw or not self._has_drawn: return False`（抑制中、または未描画）。
  3. `if not getattr(self, "live_check", None) or not self.live_check.isChecked(): return False`（ライブ反映がオフ/未構築）。
  4. `if self._redraw_timer.isActive(): return False`（全再描画が予約済み → そちらに任せる）。
  5. `if self.chart_combo.currentText() != "折れ線": return False`。
  6. `if attr == "color" and not value: return False`（色を自動へ戻す等は全再描画に任せる）。
  7. `ln = self._style_artists.get(skey)`。`if ln is None or ln.axes is None: return False`（対応 `Line2D` が無い/外れている）。
- 反映本体（`try` で囲み、例外時は `return False`）:
  - `attr == "color"` → `ln.set_color(value)`
  - `attr == "linewidth"` → `ln.set_linewidth(float(value))`
  - `attr == "linestyle"` → `ln.set_linestyle(value)`
  - `attr == "marker"` → `ln.set_marker(value or "")`（空文字フォールバック）
  - `attr == "markersize"` → `ln.set_markersize(float(value))`
  - `except Exception:`（`# noqa: BLE001`）→ `return False`（予期せぬ値）。
- 反映後の追従処理:
  - `if attr == "color":`
    - `if self.legend_check.isChecked(): self._rebuild_legend_inplace()`（凡例スウォッチの色更新）。
    - `self._rebuild_series_bar(self.chart_combo.currentText())`（上部バーの色更新）。
  - `self.canvas.draw_idle()`（軽量再描画）。
  - `return True`。
- 補足: `self._style_artists` は `_build_style_artist_map` の戻り値が描画時に格納されている前提の辞書（このファイルでは参照のみ）。

#### `def _rebuild_legend_inplace(self):`
- 色変更後、凡例を `plot_series` と同じ loc/フォントで作り直してスウォッチを更新。
- `ax = self.ax`。`handles, labels = ax.get_legend_handles_labels()`。
- `ax2 = getattr(ax, "_twin_secondary", None)`。`if ax2 is not None:` → `h2, l2 = ax2.get_legend_handles_labels()`、`handles = handles + h2; labels = labels + l2`（第2軸のハンドルも結合）。
- `if handles:`
  - `f = self._fonts()`（フォント辞書）。
  - `ax.legend(handles, labels, loc=self.legend_loc.currentText(), fontsize=(f.get("legend") or f.get("tick", 9)))`
    - **`None` 回避**: `f.get("legend")` が `None`/未設定なら `f.get("tick", 9)` を使う。直接 `f.get("legend")` を `fontsize` に渡さない。

---

## 再現に必須の細部・エッジケース・落とし穴

- **Qt6 スコープ付き列挙の厳守**: `QtCore.Qt.CheckState.Checked` / `QtCore.Qt.CheckState.Unchecked` / `QtCore.Qt.ItemFlag.ItemIsEditable` / `UserRole`（= `QtCore.Qt.ItemDataRole.UserRole`）。素の `QtCore.Qt.Checked` 等は使わない。
- **Mixin 規約**: `__init__` を定義しない。`from graph_app_common import *` 以外の import をモジュールトップに書かない（`Line2D` は関数内で遅延 import）。
- **`@staticmethod` は 2 箇所**: `_auto_y_label(names, ctype)` と `_style_key(fl, col)`。装飾子ごとこの Mixin に置く（`self` 引数なし）。
- **ラムダのループ変数束縛**: 各セルウィジェットの `connect` では必ず `k=key`（必要に応じて `b=btn` / `fl=fl`）をデフォルト引数で束縛する。束縛し忘れると、後の行のキーで上書きされる典型バグになる。
- **スタイルキーは TAB 区切り** `f"{fl}\t{col}"`。表示名（凡例ラベル）変更に依存しない安定キー。
- **`series_styles` の値は `plotter.DEFAULT_STYLE` のコピー**（`dict(plotter.DEFAULT_STYLE)`）。直接 `DEFAULT_STYLE` を共有しない。`label`/`axis`/`kind`/`errcol`/`markersize` などが追加保持されうる。
- **正規化ルール**: ラベル空文字→`None`、誤差列「なし」→`None`、マーカー値の空→`""`。これらは「自動/なし」を表現する。
- **差分構築の肝**: `new_keys == old_keys` なら即 return（無駄な再構築をしない）。先頭一致 `i` を求め、`i` 以降のみ `_build_style_row` で作り直す。`setRowCount` で末尾増減を反映し、スクロール位置を退避/復元する。構築中は `self._suspend_redraw` を一時的に True にし、終了時に**元の値**（`prev_suspend`）へ戻す（無条件 False にしない）。
- **高速パスの安全側設計**: 不確実な要素が 1 つでもあれば `False` を返して全再描画にフォールバック（散布図/誤差バー/種別混在/間引き/未描画/タイマー予約/対応アーティスト不在/例外）。`color` を空に戻すケースも全再描画へ回す。
- **`_data_lines` の除外条件**: ラベルが `"_"` 始まり（matplotlib の `_child*` 等・自動ラベル）と、ラベルに `"近似"` を含む線（近似曲線）を除外。残った線をプロット順で対応付ける。
- **第2軸の扱い**: `ax._twin_secondary` 属性（無ければ `None`）で副軸を取得。ラベル生成（`_effective_y_label`）では `axis == "secondary"` を除外、アーティストマップと凡例再構築では副軸の線/ハンドルも結合する。
- **凡例フォントの `None` 回避**: `f.get("legend") or f.get("tick", 9)`。`grid` の `linewidth` 同様、`None` を直接渡してクラッシュさせない流儀。
- **facade**: `plotter` は facade。`plotter.CHART_INFO` / `plotter.LINESTYLES` / `plotter.MARKERS` / `plotter.SERIES_AXES` / `plotter.SERIES_KINDS` / `plotter.DEFAULT_STYLE` を公開名のまま参照する。
- **monospace 回避**: このファイルでフォント family を指定する箇所は無いが、`fontsize` のみ扱う（日本語に monospace を使わない方針に沿う）。
- **`_selected_series_items()` の戻り**: `(ファイル名, 列名, 表示名)` の 3 要素タプルのリスト（別 Mixin 提供）。本ファイルは多くの箇所でこれを基準に列挙・対応付けする。

---

## このファイルが参照する（が定義しない）外部メンバ（実装時の前提）

- 属性: `self.chart_combo` / `self.x_combo` / `self.xleft_check` / `self.show_ext_check` / `self.show_filename_check` / `self.y_list` / `self.style_table` / `self.datasets` / `self.series_styles` / `self.analysis_target` / `self.bg_color` / `self.bg_btn` / `self.trend_color` / `self.trend_color_btn` / `self.live_check` / `self.legend_check` / `self.legend_loc` / `self.ax` / `self.canvas` / `self._suspend_redraw` / `self._has_drawn` / `self._redraw_timer` / `self._style_artists` / （任意）`self.phase_target2` / `self.math_a` / `self.math_b` / `self.ds_target` / `self.proto_ch`。
- メソッド（他 Mixin/本体）: `self.draw_graph()` / `self._request_redraw()` / `self._refresh_columns()` / `self._selected_series_items()` / `self._rebuild_series_bar(...)` / `self._fonts()` / `self._draw_placeholder()`。

実装時はこれらを定義し直さず、`self.` 経由で利用する前提でコードを書くこと。
