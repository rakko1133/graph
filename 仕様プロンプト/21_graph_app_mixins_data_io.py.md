# [21/30] graph_app_mixins/data_io.py の仕様

## 指示

- この仕様だけを読んで `graph_app_mixins/data_io.py` を**完全な形**で実装し、ファイル全文を出力すること。
- `pass`・`TODO`・「(省略)」・要約・「元コード参照」などは**一切禁止**。すべてのメソッドを動作する本体まで実装すること。
- 出力が途中で切れた場合は、ユーザーが「続き」と言うので、続きから**最後まで**出し切ること。
- これは全30ファイル中の **21番目**。`GraphApp` を構成する Mixin 群の1つ。

### アプリ全体の前提（このファイルに関係する分）

- Python 3.10+ / GUI は PySide6(Qt6)。**Qt は必ず matplotlib 経由**で取得する。直接 `import PySide6` しない。
  - `from matplotlib.backends.qt_compat import QtCore, QtGui, QtWidgets`
- **Qt6 列挙はスコープ付き**で書く。本ファイルで使うもの:
  - `QtCore.Qt.CursorShape.WaitCursor`
  - `QtCore.Qt.CheckState.Checked` / `QtCore.Qt.CheckState.Unchecked`
  - `QtCore.Qt.ItemDataRole.UserRole`（ただし本ファイルでは共通モジュールの別名 `UserRole` を使う）
  - `QtCore.Qt.ItemFlag.ItemIsUserCheckable` / `QtCore.Qt.ItemFlag.ItemIsEnabled`
  - `QtWidgets.QAbstractItemView.EditTrigger`（`.DoubleClicked` / `.EditKeyPressed` / `.AnyKeyPressed` / `.NoEditTriggers`）
  - `QtWidgets.QMessageBox.StandardButton.Yes`
- `GraphApp` は 10 個の Mixin ＋ `QtWidgets.QMainWindow` の多重継承。`__init__` / `closeEvent` は `GraphApp` 本体に置く。**各 Mixin は `from graph_app_common import *` で始まるメソッド束で、`__init__` を持たない**。`@staticmethod` は装飾ごと担当 Mixin に置く（本ファイルには staticmethod は無い）。
- 日本語に `family="monospace"` を使わない（□化け回避）。本ファイルはフォント指定をしないので直接の関係は薄いが規約として守る。

---

## ファイルの役割・責務

`DataIOMixin` クラス1つだけを定義するモジュール。docstring は次の趣旨:

> `"""DataIOMixin: GraphApp から分離した DataIOMixin 群（挙動は本体と同一）。"""`

責務は **データの入出力とプレビュー表・データ編集まわり**。具体的には:

1. ドラッグ＆ドロップによるファイル読み込み（`dragEnterEvent` / `dropEvent`）。
2. ファイルダイアログからの追加読み込み、再読込、削除、全削除、最近使ったファイル履歴メニュー。
3. 読み込んだ `DataFrame` を `self.datasets` / `self.meta` に登録し、ファイル一覧 `self.file_list` を更新。
4. X軸候補コンボ `self.x_combo` と Y軸候補チェックリスト `self.y_list` の再構築（`_refresh_columns`）。
5. プレビュー表 `self.table` への先頭行表示（`_populate_preview`）。
6. プレビュー表上でのセル直接編集・行追加/削除・列追加・CSV/TSV 保存。

このクラスは他 Mixin が提供するメソッド（`self.draw_graph` / `self._request_redraw` / `self._set_status` / `self._draw_placeholder` / `self._use_leftmost_x` / `self._on_y_selection_changed` / `self._clear_dynamic_resample`）や `GraphApp.__init__` で用意される属性（`self.datasets` 等）に依存する前提で書く（このファイル内では定義しない）。

---

## 依存（import するもの）

ファイル先頭はワイルドカード import 1 行のみ:

```python
# -*- coding: utf-8 -*-
"""DataIOMixin: GraphApp から分離した DataIOMixin 群（挙動は本体と同一）。"""
from graph_app_common import *  # noqa: F401,F403
```

`graph_app_common` から本ファイルで実際に使う名前:
- `os`（`os.path.splitext` / `os.path.dirname` / `os.path.basename` / `os.path.getsize` / `os.path.isfile`）
- `QtCore` / `QtGui` / `QtWidgets`
- `data_loader`（`data_loader.DELIMITER_LABELS` / `data_loader.load_table`）
- `UserRole`（= `QtCore.Qt.ItemDataRole.UserRole`）
- `PREVIEW_ROWS`（= `100`）

メソッド内で**遅延 import** するもの（モジュール先頭では import しない）:
- `_populate_preview` / `_on_cell_edited` 内: `import pandas as pd`
- `_row_add` 内: `import numpy as np`

> 注: `numpy` / `pandas` をトップレベル import しないのは起動を軽くするため。必ずメソッド内ローカル import にすること。

---

## 依存する外部定数・他モジュール API（正確な値）

- `PREVIEW_ROWS = 100`（プレビュー表に表示する先頭行数）。
- `data_loader.DELIMITER_LABELS`（区切り文字 → 表示ラベル の辞書。逆引きに使う）。正確な内容:
  ```python
  {
      ",":  "カンマ ( , )",
      "\t": "タブ ( \\t )",
      ";":  "セミコロン ( ; )",
      "|":  "パイプ ( | )",
  }
  ```
- `data_loader.load_table(path, encoding=None, delimiter=None)` は `(df, used_enc, used_delim)` の3要素タプルを返す。例外を投げ得る。

---

## このファイルが触る `GraphApp` の属性（呼び出し前提・このファイルでは生成しない）

- `self.datasets`: `dict[str(ラベル), pandas.DataFrame]`（挿入順を保持＝Y軸候補の並び順に使う）。
- `self.meta`: `dict[str(ラベル), dict]`。各値は `{"path": str, "enc": str, "delim": str}`。
- `self.series_styles`: `dict`。キーは `"file\tcol"` 形式（タブ区切り）。
- `self.recent_files`: `list[str]`（最近使ったファイルのパス。先頭が最新、最大12件）。
- `self.last_dir`: 直近に開いたディレクトリ（ファイルダイアログの初期位置）。
- UI ウィジェット: `self.file_list`(QListWidget) / `self.x_combo`(QComboBox) / `self.y_list`(QListWidget) / `self.table`(QTableWidget) / `self.enc_combo`(QComboBox) / `self.delim_combo`(QComboBox) / `self.recent_menu`(QMenu) / `self.meas_table` / `self.ds_table`（後二者は `hasattr` で存在チェックして使う）。
- フラグ/状態: `self._has_drawn`(bool) / `self._preview_loading`(bool) / `self._preview_label`(str|None) / `self._meas_annotations`(list) / `self._ds_annotations`(list)。
- 他 Mixin のメソッド: `self.draw_graph()` / `self._request_redraw()` / `self._set_status(msg)` / `self._draw_placeholder()` / `self._use_leftmost_x()` / `self._on_y_selection_changed()` / `self._clear_dynamic_resample()`。

---

## 公開 API（全メソッドの完全シグネチャと挙動）

すべて `class DataIOMixin:` のメソッド。並び順は下記の通り（コメント区切りも含めて再現する）。

### ドラッグ＆ドロップ（コメント区切り `# --- D&D`）

#### `def dragEnterEvent(self, event):`
- `event.mimeData().hasUrls()` が真なら `event.acceptProposedAction()` を呼ぶだけ。偽なら何もしない。

#### `def dropEvent(self, event):`
- `paths = []` を用意。`event.mimeData().urls()` を順に走査し、各 url を `p = url.toLocalFile()`。
- `p` が真かつ `os.path.splitext(p)[1].lower()` が `(".csv", ".tsv", ".txt")` のいずれかなら `paths.append(p)`。
- `paths` が空なら `return`（早期終了）。
- `paths` の各 `p` に対し `self._load_file(p)` を呼ぶ。
- `self.last_dir = os.path.dirname(paths[-1])`。
- `self._refresh_columns()` を呼ぶ。
- `self._has_drawn` が真なら `self.draw_graph()`。

### ファイル読み込み（コメント区切り `# --- ファイル`）

#### `def add_file(self):`
- `QtWidgets.QFileDialog.getOpenFileNames(self, "ファイルを追加（複数選択可）", self.last_dir, "データ (*.csv *.tsv *.txt);;すべて (*.*)")` を呼び、`paths, _` で受ける。
- `paths` の各要素に `self._load_file(p)`。
- `paths` が真（1件以上）なら: `self.last_dir = os.path.dirname(paths[-1])` と `self._refresh_columns()`。
- フィルタ文字列・ダイアログ題名は上記日本語を厳密に再現。

#### `def _load_file(self, path):`
ファイル1個を読み込んで登録する中心メソッド。手順:
1. エンコーディング決定: `enc = self.enc_combo.currentText()`。`enc.startswith("自動")` なら `enc = None`、そうでなければそのまま。
2. 区切り文字決定: `delim = None`。`dt = self.delim_combo.currentText()`。`dt.startswith("自動")` でなければ、`data_loader.DELIMITER_LABELS.items()` を走査し、`lbl == dt` の `ch` を `delim` にして `break`。
3. サイズ判定: `size = os.path.getsize(path) if os.path.isfile(path) else 0`。`busy = size > 5_000_000`（5MB 超で待機表示）。
4. `busy` なら待機カーソル: `QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)` → `self._set_status(f"読み込み中… {os.path.basename(path)}")` → `QtWidgets.QApplication.processEvents()`。
5. `try` 内で `df, used_enc, used_delim = data_loader.load_table(path, encoding=enc, delimiter=delim)`。
   - `except Exception as e:` で `QtWidgets.QMessageBox.critical(self, "読み込みエラー", f"{os.path.basename(path)}\n\n{e}")` を出して `return`。
   - `finally:` で `busy` のとき `QtWidgets.QApplication.restoreOverrideCursor()`。
6. ラベル重複回避: `label = os.path.basename(path)`。`base, i = label, 2`。
   `while label in self.datasets and self.meta.get(label, {}).get("path") != path:` のループで `label = f"{base} ({i})"; i += 1`。
   （＝同名でもパスが違うときだけ `名 (2)`, `名 (3)`… と採番。同じパスなら同名で上書き＝再読込扱い。）
7. 登録: `self.datasets[label] = df`、`self.meta[label] = {"path": path, "enc": used_enc, "delim": used_delim}`。
8. 一覧追加: `if not self._find_file_item(label): self._add_file_item(label)`。
9. `self._push_recent(path)`。
10. ステータス: `self._set_status(f"{label} を読み込み（{len(df)}行 × {len(df.columns)}列, {used_enc}）")`。
- 戻り値なし。文字列リテラル・全角中黒・`×` は厳密に再現。

#### `def _find_file_item(self, label):`
- `self.file_list.count()` ぶん走査し、`self.file_list.item(i).text() == label` の項目を返す。無ければ `None`。

#### `def _add_file_item(self, label):`
- docstring: `"""ファイル一覧へ項目を追加（ホバーで全名を出すツールチップ付き）。"""`
- `it = QtWidgets.QListWidgetItem(label)` → `it.setToolTip(label)` → `self.file_list.addItem(it)`。

#### `def _push_recent(self, path):`
- `path` が既に `self.recent_files` にあれば `remove`。
- `self.recent_files.insert(0, path)`（先頭挿入）。
- `del self.recent_files[12:]`（12件に切り詰め）。
- `self._rebuild_recent_menu()`。

#### `def _rebuild_recent_menu(self):`
- `self.recent_menu.clear()`。
- `self.recent_files` が空なら: `act = self.recent_menu.addAction("（履歴なし）"); act.setEnabled(False)` して `return`。
- そうでなければ各 `p` について `self.recent_menu.addAction(os.path.basename(p), lambda checked=False, q=p: self._open_recent(q))`。
  - **遅延束縛回避のため `q=p` をデフォルト引数で束縛**すること（必須）。`checked=False` も入れる。

#### `def _open_recent(self, path):`
- `os.path.isfile(path)` が偽なら: `QtWidgets.QMessageBox.information(self, "情報", f"ファイルが見つかりません:\n{path}")` を出し、`self.recent_files = [q for q in self.recent_files if q != path]` で除去、`self._rebuild_recent_menu()` して `return`。
- 真なら: `self._load_file(path)` → `self._refresh_columns()` → `self._has_drawn` が真なら `self.draw_graph()`。

#### `def remove_file(self):`
- docstring: `"""選択中のファイルを削除（複数選択していればまとめて削除）。"""`
- `items = self.file_list.selectedItems()`。空かつ `self.file_list.currentItem()` があれば `items = [self.file_list.currentItem()]`。
- `labels = [it.text() for it in items]`。
- `labels` が空なら `QtWidgets.QMessageBox.information(self, "情報", "削除するファイルを選択してください。")` して `return`。
- `len(labels) > 1` なら確認: `ret = QtWidgets.QMessageBox.question(self, "一括削除", f"{len(labels)} 個のファイルを一覧から削除しますか？")`。`ret != QtWidgets.QMessageBox.StandardButton.Yes` なら `return`。
- `self._remove_labels(labels)` → `self._set_status(f"{len(labels)} 個のファイルを削除しました。")`。

#### `def clear_all_files(self):`
- docstring: `"""読み込み済みファイルをすべて削除する。"""`
- `self.datasets` が空なら `QtWidgets.QMessageBox.information(self, "情報", "読み込み済みファイルがありません。")` して `return`。
- 確認: `ret = QtWidgets.QMessageBox.question(self, "全削除", f"読み込み済みの {len(self.datasets)} 個すべてを一覧から削除しますか？")`。`!= ...Yes` なら `return`。
- `n = len(self.datasets)`、`self._remove_labels(list(self.datasets.keys()))`、`self._set_status(f"すべて（{n} 個）のファイルを削除しました。")`。

#### `def _remove_labels(self, labels):`
- docstring: `"""指定ラベルのファイルをデータ・一覧・スタイルから取り除き、表示を更新する。"""`
- `labelset = set(labels)`。
- **先に `self._clear_dynamic_resample()`** を呼ぶ（ズーム再サンプル用の全解像度データ参照を解放＝メモリリーク防止。コメント必須）。
- 各 `label` について `self.datasets.pop(label, None)` と `self.meta.pop(label, None)`。
- 系列スタイル掃除: `for key in [k for k in self.series_styles if k.split("\t", 1)[0] in labelset]: self.series_styles.pop(key, None)`。
  - キーは `"file\tcol"` 形式なので、タブで分割した先頭（ファイル名）が `labelset` に含まれるものを除去。
- 解析注記/表のクリア（古い注記が次の描画に残らないように）:
  - `self._meas_annotations = []`、`self._ds_annotations = []`。
  - `if hasattr(self, "meas_table"): self.meas_table.setRowCount(0)`。
  - `if hasattr(self, "ds_table"): self.ds_table.setRowCount(0)`。
- 一覧から除去（**シグナルブロックして後ろから前へ**走査）:
  - `self.file_list.blockSignals(True)`
  - `for i in range(self.file_list.count() - 1, -1, -1): if self.file_list.item(i).text() in labelset: self.file_list.takeItem(i)`
  - `self.file_list.blockSignals(False)`
- `self._refresh_columns()`。
- 残データがあるか分岐:
  - `if self.datasets:` → `self.file_list.setCurrentRow(0)`（プレビューを残りの先頭へ）。
  - `else:` → `self._preview_label = None`、`self.table.clearContents()`、`self.table.setRowCount(0)`、`self.table.setColumnCount(0)`、`self._draw_placeholder()`。

#### `def reload_current(self):`
- `it = self.file_list.currentItem()`。無ければ `QtWidgets.QMessageBox.information(self, "情報", "ファイルを選択してください。")` して `return`。
- `path = self.meta[it.text()]["path"]`。
- `self.datasets.pop(it.text(), None)`、`self.meta.pop(it.text(), None)`、`self.file_list.takeItem(self.file_list.row(it))`。
- `self._load_file(path)` → `self._refresh_columns()`。
- （＝一旦データと一覧項目を消してから同パスを再読込。`_load_file` 側で同名再採番される。）

#### `def _on_file_selected(self, _row):`
- `it = self.file_list.currentItem()`。
- `it` があり `it.text() in self.datasets` なら:
  - `self._populate_preview(self.datasets[it.text()], label=it.text())`。
  - `meta = self.meta[it.text()]`。
  - エンコーディングコンボを選択ファイルのものに合わせる（**ワンライナーの条件式**）:
    `self.enc_combo.setCurrentText(meta["enc"]) if self.enc_combo.findText(meta["enc"]) >= 0 else None`
    （findText が見つかれば設定、無ければ何もしない。式文として書くこと。）

### 列候補の更新

#### `def _refresh_columns(self):`
X軸候補と Y軸候補を全データセットから再構築する。

- **X軸候補**（全ファイルの列名の和集合、出現順）:
  - `seen, xcols = set(), []`。各 `df in self.datasets.values()` の各列 `c` を、未出なら `seen.add(c); xcols.append(c)`。
  - `cur_x = self.x_combo.currentText()`。
  - `self.x_combo.blockSignals(True)` → `self.x_combo.clear()` → `self.x_combo.addItems(xcols)`。
  - `cur_x in xcols` なら `self.x_combo.setCurrentText(cur_x)`（選択維持）。
  - `self.x_combo.blockSignals(False)`。
- **Y軸候補**（`ファイル | 列`）。選択状態は表示名ではなく**安定した `(ファイル, 列)` 識別子**で保持する（ファイル数で表示名が変わっても消えないように。コメント必須）:
  - `checked = QtCore.Qt.CheckState.Checked`、`unchecked = QtCore.Qt.CheckState.Unchecked`。
  - 既存のチェック済みを採取: `prev = {self.y_list.item(i).data(UserRole) for i in range(self.y_list.count()) if self.y_list.item(i).checkState() == checked}`。
  - `self.y_list.blockSignals(True)`（構築中のチェック変更で何度も再描画しない。コメント必須）→ `self.y_list.clear()`。
  - `multi = len(self.datasets) > 1`。
  - `use_left = self._use_leftmost_x()`。
  - `for label, df in self.datasets.items():` → `for ci, c in enumerate(df.columns):`
    - `if use_left and ci == 0: continue`（先頭列はX軸なのでY軸候補から除外。コメント必須）。
    - `disp = f"{label} | {c}" if multi else c`（複数ファイル時のみ `ラベル | 列` 表記。区切りは ` | `＝半角スペース＋パイプ＋半角スペース）。
    - `item = QtWidgets.QListWidgetItem(disp)`。
    - `item.setData(UserRole, (label, c))`。
    - `item.setFlags(QtCore.Qt.ItemFlag.ItemIsUserCheckable | QtCore.Qt.ItemFlag.ItemIsEnabled)`。
    - `item.setCheckState(checked if (label, c) in prev else unchecked)`（以前チェックされていた `(label,c)` のみ再チェック）。
    - `self.y_list.addItem(item)`。
  - `self.y_list.blockSignals(False)`。
  - `self._on_y_selection_changed()`（スタイル表・解析候補をまとめて更新。コメント必須）。

#### `def _selected_series_items(self):`
- docstring: `"""チェック済みの (file_label, column, display_label) のリスト（並び順保持）。"""`
- `out = []`。`self.y_list` を `i` で走査し、`it = self.y_list.item(i)`。
- `it.checkState() == QtCore.Qt.CheckState.Checked` のとき `fl, col = it.data(UserRole)` を取り、`out.append((fl, col, it.text()))`。
- `out` を返す（3要素タプルのリスト。並び順は y_list の順）。

### プレビュー表

#### `def _populate_preview(self, df, label=None):`
- 先頭で `import pandas as pd`。
- `self._preview_loading = True`（構築中の itemChanged を書き戻さないためのガード。コメント必須）。`try/finally` で囲み、`finally` で `self._preview_loading = False`。
- `try` 本体:
  - `head = df.head(PREVIEW_ROWS)`。
  - `cols = list(df.columns)`。
  - `self.table.clear()`。
  - `self.table.setColumnCount(len(cols))`、`self.table.setRowCount(len(head))`。
  - `self.table.setHorizontalHeaderLabels([str(c) for c in cols])`。
  - 二重ループ `for r in range(len(head)): for c in range(len(cols)):`:
    - `v = head.iat[r, c]`。
    - `self.table.setItem(r, c, QtWidgets.QTableWidgetItem("" if pd.isna(v) else str(v)))`（NaN は空文字、それ以外は str）。
  - `self.table.resizeColumnsToContents()`。
  - `if label is not None: self._preview_label = label`。

### データ編集（コメント区切り `# --- データ編集`）

#### `def _on_edit_toggle(self, on):`
- `ET = QtWidgets.QAbstractItemView.EditTrigger`。
- `self.table.setEditTriggers((ET.DoubleClicked | ET.EditKeyPressed | ET.AnyKeyPressed) if on else ET.NoEditTriggers)`。
- （編集チェックボックス ON で3トリガー有効、OFF で `NoEditTriggers`。）

#### `def _on_cell_edited(self, item):`
- `if self._preview_loading or not getattr(self, "_preview_label", None): return`（構築中や対象未確定なら無視）。
- `import pandas as pd`。
- `df = self.datasets.get(self._preview_label)`。`df is None` なら `return`。
- `r, c = item.row(), item.column()`。`if r >= len(df) or c >= df.shape[1]: return`（範囲外ガード）。
- `col = df.columns[c]`、`text = item.text()`。
- 数値列なら数値化: `if pd.api.types.is_numeric_dtype(df[col]): val = pd.to_numeric(text, errors="coerce")`（不可なら NaN。コメント必須）。`else: val = text`。
- `df.iat[r, c] = val`。
- `self._set_status(f"編集: {self._preview_label} 行{r}「{col}」= {text}")`。
- `self._request_redraw()`。

#### `def _edit_target(self):`
- `lbl = getattr(self, "_preview_label", None)`。
- `if not lbl or lbl not in self.datasets:` → `QtWidgets.QMessageBox.information(self, "情報", "左の一覧でファイルを選択してください。")` して `return None`。
- それ以外は `return lbl`。

#### `def _row_add(self):`
- `import numpy as np`。
- `lbl = self._edit_target()`。`if not lbl: return`。
- `df = self.datasets[lbl]`。
- `df.loc[len(df)] = [np.nan] * df.shape[1]`（末尾に NaN 行を追加）。
- `df.reset_index(drop=True, inplace=True)`。
- `self._populate_preview(df, label=lbl)`。
- `if len(df) > PREVIEW_ROWS: self._set_status(f"行を追加（全{len(df)}行。表示は先頭{PREVIEW_ROWS}行）")`。
- `self._request_redraw()`。

#### `def _row_del(self):`
- `lbl = self._edit_target()`。`if not lbl: return`。
- `rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)`（選択行番号を降順・重複排除）。
- `if not rows: self._set_status("削除する行を選択してください。"); return`。
- `df = self.datasets[lbl]`。
- `df.drop(df.index[rows], inplace=True)`、`df.reset_index(drop=True, inplace=True)`。
- `self._populate_preview(df, label=lbl)`、`self._request_redraw()`。

#### `def _col_add(self):`
- `lbl = self._edit_target()`。`if not lbl: return`。
- `name, ok = QtWidgets.QInputDialog.getText(self, "列追加", "新しい列名:")`。
- `name = (name or "").strip()`。`if not ok or not name: return`。
- `df = self.datasets[lbl]`。
- `if name in df.columns: QtWidgets.QMessageBox.warning(self, "列追加", "同名の列が既にあります。"); return`。
- `df[name] = 0.0`（値 0.0 で初期化）。
- `self._populate_preview(df, label=lbl)`。
- `self._refresh_columns()`（X/Y軸の候補へ反映。コメント必須）。
- `self._set_status(f"列「{name}」を追加（値0.0で初期化）")`。

#### `def _save_csv(self):`
- `lbl = self._edit_target()`。`if not lbl: return`。
- 既定ファイル名: `default = lbl if lbl.lower().endswith((".csv", ".tsv")) else lbl + ".csv"`。
- `path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "CSV/TSVとして保存", default, "CSV (*.csv);;TSV (*.tsv);;全てのファイル (*.*)")`。
- `if not path: return`。
- `try:`
  - `sep = "\t" if path.lower().endswith(".tsv") else ","`。
  - `self.datasets[lbl].to_csv(path, index=False, sep=sep, encoding="utf-8-sig")`（BOM 付き UTF-8、index 無し）。
  - `self._set_status(f"保存しました: {path}（全{len(self.datasets[lbl])}行）")`。
- `except Exception as e:` → `QtWidgets.QMessageBox.critical(self, "保存エラー", str(e))`。

---

## 再現に必須の細部・エッジケース

- **D&D 拡張子フィルタ**は小文字化して `(".csv", ".tsv", ".txt")` のみ受理。一致が0件なら何もしない（早期 return）。
- **大容量ファイル**（5,000,000 バイト超）のみ待機カーソル＋進捗ステータス＋`processEvents()`。閾値リテラルは `5_000_000`。
- **読み込み例外**は `QMessageBox.critical` で `ベース名\n\n例外文` を表示し、その1ファイルはスキップ（return）。`finally` でカーソルを必ず戻す。
- **ラベル採番**: 同名でも**パスが違う場合のみ** `名 (2)`, `名 (3)` …と採番。同一パスの再読込は同名で上書きされる（`while label in self.datasets and meta...path != path`）。
- **最近使ったファイル**は最大12件（`del self.recent_files[12:]`）、先頭が最新。履歴 0 件のときは無効化された `"（履歴なし）"` を1項目だけ表示。
- **recent メニューの lambda は `checked=False, q=p` をデフォルト引数で束縛**（ループ変数の遅延束縛バグ回避）。
- **`_remove_labels` は必ず最初に `self._clear_dynamic_resample()`** を呼ぶ（メモリリーク防止）。
- **series_styles のキーは `"file\tcol"`（タブ区切り）**。削除時は `k.split("\t", 1)[0]` をファイル名として照合。
- ファイル一覧から削除する際は **`blockSignals(True)` で囲み、後ろ→前（逆順）に `takeItem`** する（インデックスずれと選択シグナルの連鎖防止）。
- 全削除後はプレビュー表を完全クリアし（`clearContents` / `setRowCount(0)` / `setColumnCount(0)`）、`_preview_label = None`、`_draw_placeholder()` を呼ぶ。
- **Y軸候補の選択状態は `(ファイル名, 列名)` タプルで `UserRole` に保持**し、再構築後も復元する。表示名（`disp`）では保持しない。
- **`use_left`（最左列を X 軸に使う設定）が真なら各 df の先頭列（ci==0）を Y 候補から除外**。
- 複数ファイル時のみ Y 表示名を `f"{label} | {c}"`（` | ` = 半角スペース・パイプ・半角スペース）にする。単一ファイル時は列名のみ。
- **プレビューは先頭 `PREVIEW_ROWS`（=100）行のみ**。行追加時に総行数が 100 を超えると「表示は先頭100行」と注記。
- **セル編集**: 数値列は `pd.to_numeric(..., errors="coerce")` で NaN フォールバック、非数値列は文字列のまま。`_preview_loading` 中・対象未確定・範囲外は書き戻さない。
- **CSV 保存は `utf-8-sig`（BOM 付き）・`index=False`**。拡張子 `.tsv` ならタブ区切り、それ以外はカンマ。

---

## 関係する落とし穴（必ず守る）

- **Qt6 スコープ付き列挙**を徹底（`CheckState.Checked` / `ItemDataRole.UserRole`（別名 `UserRole`）/ `ItemFlag.*` / `EditTrigger.*` / `CursorShape.WaitCursor` / `StandardButton.Yes`）。古い `QtCore.Qt.Checked` 形式は使わない。
- **Mixin 規約**: このファイルは `class DataIOMixin:` の**メソッド束のみ**。`__init__` を定義しない。`from graph_app_common import *` 以外の import をトップレベルに書かない（`pandas`/`numpy` はメソッド内ローカル import）。
- `data_loader` 等の参照は `graph_app_common` の re-export 経由（facade 規約）。本ファイルで個別モジュールを直接 import し直さない。
- `numpy`/`pandas` の遅延 import を崩さない（起動高速化のため）。
- 日本語ラベルに `monospace` を使わない（本ファイルはフォント未指定だが規約）。
- ファイル一覧操作・y_list/x_combo 再構築では **`blockSignals` を正しく対で**使い、再描画の暴発を防ぐ。
