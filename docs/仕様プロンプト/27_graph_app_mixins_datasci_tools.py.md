# [27/30] graph_app_mixins/datasci_tools.py の仕様

## 指示

- この仕様だけを読んで、`graph_app_mixins/datasci_tools.py` を**完全な形**で実装し、ファイル全文を出力してください。
- `pass` のみの本体・`TODO`・`...`・「省略」・「要約」・「以下同様」などは**一切禁止**です。すべてのメソッドを動作する形で実装してください。
- 出力が途中で切れた場合は、こちらが「続き」と入力するので、**最後まで分割して出し切って**ください（コードブロックを閉じ直し、続きから再開する）。
- 本ファイルは全 30 ファイルの一部であり、`GraphApp` を構成する Mixin の 1 つ（データサイエンスタブ担当）です。

### アプリ全体の前提（本ファイルに関係する分）

- Python 3.10+ / GUI=PySide6(Qt6)。ただし Qt は**必ず matplotlib 経由**で取得する。本ファイル内では直接 import せず、`from graph_app_common import *` で取り込まれる `QtCore` / `QtGui` / `QtWidgets` を使う。
- Qt6 列挙は**スコープ付き**で書く（例: `QtCore.Qt.AlignmentFlag.AlignCenter`、`QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers` 等）。
- `GraphApp` は 10 個の Mixin ＋ `QtWidgets.QMainWindow` の多重継承。`__init__` / `closeEvent` は `GraphApp` 本体にあり、**各 Mixin は `__init__` を持たない**メソッド束である。`@staticmethod` は装飾ごと担当 Mixin に置く。
- 本ファイルは GUI 依存。計算実体は GUI 非依存の `datasci` モジュール（同梱の `datasci.py`）にあり、本ファイルは「取得 → 計算 → 表示」の橋渡しに徹する。
- 日本語表示に `family="monospace"` は使わない（□化け回避）。本ファイル自体はフォント設定をしないが、注記やラベルに monospace を持ち込まないこと。
- 再描画は `self.draw_graph()` 経由（デバウンス・再入防止は呼び先が担当）。本ファイルは描画タイミングのガード（`_has_drawn` / `datasets` の有無）を確認してから `draw_graph()` を呼ぶ。

---

## 1. ファイルの役割 / 責務

`DataSciMixin`（単一クラス）を定義する。GUI の「データサイエンス」タブの解析アクションを実装するメソッド束である。

docstring の趣旨（モジュール先頭の三重引用符に記載すること）:

```
DataSciMixin: 「データサイエンス」タブの解析アクション。

選択中のY系列に対し、線形回帰（線形性）・記述統計・相関・正規性検定などを計算して表で表示する。
実体の計算は datasci モジュール（GUI 非依存）に置き、ここは取得→計算→表示の橋渡しに徹する。
```

具体的な責務:

1. データサイエンスタブの「対象」コンボから選択中の系列を取得し `(表示名, x, y)` を返す。
2. 結果テーブル（`項目 / 値 / 表示` の 3 列）への表示。各行に「表示」チェックボックスを付け、チェックした行をグラフ上に注記として重ねる。
3. 線形回帰・記述統計・正規性検定の各アクションボタンに対応するハンドラ。
4. 選択中の複数系列に対する相関行列の計算と、色付き表ダイアログでの表示。

---

## 2. 依存（import するもの）

ファイル先頭は次の 1 行のみ（他の import は書かない）:

```python
from graph_app_common import *  # noqa: F401,F403
```

これにより少なくとも以下が利用可能になる前提:

- `QtCore` / `QtGui` / `QtWidgets`（matplotlib 経由で取得済み）。
- `datasci` モジュール（`datasci.linear_regression` / `datasci.describe` / `datasci.normality` / `datasci.correlation` / `datasci.correlation_matrix` を呼ぶ）。

本ファイルからは `import numpy` 等を直接書かない（数値計算は `datasci` 側に委譲）。`float()` 等の組み込みのみ使用する。

### 他 Mixin / 本体が提供する前提のメンバ（self 経由で参照。本ファイルでは定義しない）

- `self.ds_target`（`QComboBox`）: 対象Y系列の表示名コンボ。
- `self.ds_table`（`QTableWidget`、列構成 `["項目", "値", "表示"]`、列0/1/2）。
- `self.ds_title`（太字 `QLabel`、結果見出し）。
- `self.ds_fit_check`（`QCheckBox`「回帰直線をグラフに重ねる」）。
- `self.trend_combo`（近似曲線種別コンボ。`"線形"` をセットすると回帰直線を重ねられる）。
- `self.datasets`（読み込み済みデータの有無を表す truthy/falsy なコレクション）。
- `self._has_drawn`（bool、初回描画済みか。`getattr` で安全参照する）。
- `self._xy_by_disp(disp)`（`AdvancedMixin` 提供。表示名から `(t, y)` を返す。取得不可なら `t` が `None`）。
- `self._selected_series_items()`（`DataIOMixin` 提供。チェック済みの `(file_label, column, display_label)` リストを並び順保持で返す）。
- `self.draw_graph()`（再描画）。

注記の受け渡し用に `self._ds_annotations`（`list[str]`）を本ファイルが設定する。グラフ描画側（plotter）はこの属性を読んで注記を描く前提。`getattr(self, "_ds_annotations", None)` で安全に初期/未設定を判定する。

---

## 3. クラス定義と公開 API（完全なシグネチャ）

クラス名: `DataSciMixin`（基底クラスなし、`class DataSciMixin:`）。コメント区切り（`# ---- 共通: 解析対象 (t, y) の取得 ----` のような区切り）を付けてもよいが必須ではない。メソッドの定義順は下記の通り。

### 3.1 `def _ds_xy(self):`

データサイエンスタブの対象コンボから `(disp, x, y)` を取得するヘルパ。

アルゴリズム:

1. `disp = self.ds_target.currentText()`。
2. `disp` が空文字（falsy）なら、`QtWidgets.QMessageBox.information(self, "情報", "データタブでY系列を選択してください。")` を表示し、`return None, None, None`。
3. `t, y = self._xy_by_disp(disp)` を呼ぶ（同一クラス＝`GraphApp` インスタンスのメソッドとして `AdvancedMixin` と共用）。
4. `t is None` なら、`QtWidgets.QMessageBox.information(self, "情報", "対象の数値データが取得できません。")` を表示し、`return None, None, None`。
5. 正常時は `return disp, t, y`。

戻り値の形: 3 要素タプル `(disp:str|None, x|None, y|None)`。エラー時は 3 つとも `None`。

### 3.2 `def _ds_show(self, title, rows):`

`rows = [(項目, 値文字列), ...]` を結果テーブルに表示する。各行に「表示」チェックを付ける。

アルゴリズム:

1. `had = bool(getattr(self, "_ds_annotations", None))`（**先に**前回注記の有無を控える）。
2. `self._ds_annotations = []`（新しい解析を表示したら前回の注記はリセット）。
3. `self.ds_title.setText(title)`。
4. `self.ds_table.setRowCount(len(rows))`。
5. `for r, (k, v) in enumerate(rows):` で各行を構築:
   - 列0: `self.ds_table.setItem(r, 0, QtWidgets.QTableWidgetItem(str(k)))`。
   - 列1: `self.ds_table.setItem(r, 1, QtWidgets.QTableWidgetItem(str(v)))`。
   - 列2: `cb = QtWidgets.QCheckBox()`。ツールチップを `"チェックすると、この項目の値をグラフ上に注記表示します。"` に設定。`cb.toggled.connect(self._refresh_ds_annotations)` を接続。`self.ds_table.setCellWidget(r, 2, cb)`。
6. 末尾ガード: `if had and getattr(self, "_has_drawn", False):` のとき `self.draw_graph()` を呼ぶ（**前回の注記を消すため**の再描画）。

重要な細部:
- `had` の判定は `_ds_annotations` を空に上書きする**前**に取ること（順序が重要）。
- セルウィジェットは列番号 **2** に置く（テーブルは 3 列固定）。

### 3.3 `def _refresh_ds_annotations(self, *_):`

「表示」にチェックされた行を集めてグラフへ注記表示する（チェックボックスの `toggled` シグナルから呼ばれるので可変長 `*_` で余分な bool 引数を捨てる）。

アルゴリズム:

1. `anns = []`。
2. `for r in range(self.ds_table.rowCount()):`
   - `cb = self.ds_table.cellWidget(r, 2)`。
   - `if cb is not None and cb.isChecked():`
     - `k = self.ds_table.item(r, 0)`、`v = self.ds_table.item(r, 1)`。
     - `if k is not None and v is not None:` → `anns.append(f"{k.text()} = {v.text()}")`。
3. `self._ds_annotations = anns`。
4. `if self.datasets:`（特殊表示直後でも通常グラフへ再描画して反映） → `self.draw_graph()`。

注記文字列の書式は **`"<項目> = <値>"`**（半角イコールの前後にスペース 1 つ）。`_ds_annotations` は `list[str]`。

### 3.4 `@staticmethod` `def _fmt(v):`

値を表示用文字列に整形する静的メソッド（**`@staticmethod` 装飾を必ず付ける**）。

分岐（この順序を厳守）:

1. `v is None` → `"—"`（全角ダッシュ U+2014、いわゆる em dash。`—` の 1 文字）。
2. `isinstance(v, bool)` → `True` なら `"はい"`、`False` なら `"いいえ"`。**bool 判定は int 判定より前**に置くこと（Python では `bool` は `int` のサブクラスなので順序が逆だと真偽値が数値扱いになる）。
3. `isinstance(v, int)` → `str(v)`。
4. それ以外: `try: return f"{float(v):.6g}"` / `except (TypeError, ValueError): return str(v)`。

戻り値: `str`。浮動小数は有効数字 6 桁の `g` 書式（`f"{float(v):.6g}"`）。

### 3.5 `def run_regression(self):`

線形回帰（線形性評価）アクション。

アルゴリズム:

1. `disp, t, y = self._ds_xy()`。`if t is None: return`。
2. `d = datasci.linear_regression(t, y)`。`if not d:` → `QtWidgets.QMessageBox.information(self, "情報", "回帰に十分なデータがありません。")` して `return`。
3. `f = self._fmt`。
4. `rows` を**この順序・このラベルで**構築（各値は `f(d[キー])`）:

   | 表示ラベル | 取り出すキー |
   |---|---|
   | `点数 n` | `d["n"]` |
   | `傾き slope` | `d["slope"]` |
   | `切片 intercept` | `d["intercept"]` |
   | `相関 r (ピアソン)` | `d["r"]` |
   | `決定係数 R²` | `d["r2"]` |
   | `p値 (傾き=0)` | `d["p_value"]` |
   | `傾きの標準誤差` | `d["std_err"]` |
   | `RMSE (残差)` | `d["rmse"]` |
   | `直線性誤差 [%FS]` | `d["linearity_error_pct"]` |

   （`R²` は U+00B2 上付き 2、`[%FS]` は半角）。

5. スピアマン相関を追加: `sp = datasci.correlation(t, y, "spearman")`。`if sp:` のとき `rows.append(("相関 (スピアマン)", f(sp["r"])))`。
6. `self._ds_show(f"線形回帰: {disp}（Y vs X）", rows)`（見出しの `（Y vs X）` は全角丸括弧）。
7. `if self.ds_fit_check.isChecked():` のとき:
   - `self.trend_combo.setCurrentText("線形")`（既存の近似曲線(線形)機能でグラフに直線を重ねる）。
   - `self.draw_graph()`。

### 3.6 `def show_describe(self):`

記述統計アクション。

アルゴリズム:

1. `disp, t, y = self._ds_xy()`。`if t is None: return`。
2. `d = datasci.describe(y)`。`if not d:` → `QtWidgets.QMessageBox.information(self, "情報", "数値データがありません。")` して `return`。
3. `f = self._fmt`。
4. `order` を**この順序の `(ラベル, dict キー)` のリスト**で定義:

   ```
   ("件数", "count"), ("平均", "mean"), ("中央値", "median"),
   ("標準偏差 σ", "std"), ("分散", "var"), ("最小", "min"), ("最大", "max"),
   ("範囲", "range"), ("変動係数 CV", "cv"), ("歪度 skew", "skew"),
   ("尖度 kurtosis", "kurtosis"), ("第1四分位 Q1", "p25"),
   ("中央 Q2", "p50"), ("第3四分位 Q3", "p75"), ("四分位範囲 IQR", "iqr"),
   ```

   （`σ` は U+03C3 ギリシャ小文字シグマ）。

5. `self._ds_show(f"記述統計: {disp}", [(lbl, f(d.get(k))) for lbl, k in order])`。

   重要: 値の取り出しは `d.get(k)`（**キー欠如に強い** `.get`。`describe` が返さないキーは `None` → `_fmt` で `"—"`）。

### 3.7 `def run_normality(self):`

正規性検定（Shapiro-Wilk）アクション。

アルゴリズム:

1. `disp, t, y = self._ds_xy()`。`if t is None: return`。
2. `d = datasci.normality(y)`。`if not d:` のとき次の文言で情報表示して `return`:
   - `QtWidgets.QMessageBox.information(self, "情報", "正規性検定には scipy が必要です（または点数不足）。")`（複数行に分けて書いてよい）。
3. `f = self._fmt`。
4. `rows`:

   ```
   ("W統計量", f(d["W"])),
   ("p値", f(d["p_value"])),
   ("5%有意で正規とみなせる", f(d["normal_5pct"])),
   ```

   （`normal_5pct` は bool なので `_fmt` で `"はい"/"いいえ"` になる）。

5. `self._ds_show(f"正規性検定 (Shapiro-Wilk): {disp}", rows)`。

### 3.8 `def show_corr_matrix(self):`

選択中の全Y系列どうしの相関行列を計算してダイアログ表示。

アルゴリズム:

1. `items = self._selected_series_items()`。
2. `if len(items) < 2:` → `QtWidgets.QMessageBox.information(self, "情報", "相関行列には2系列以上をデータタブで選択してください。")` して `return`。
3. `named = []`。`for fl, col, disp in items:`（タプルは `(file_label, column, display_label)` の 3 要素を分解）:
   - `t, y = self._xy_by_disp(disp)`。
   - `if y is not None:` → `named.append((disp, y))`。
4. `names, mat = datasci.correlation_matrix(named, "pearson")`。
5. `if mat is None:` → `QtWidgets.QMessageBox.information(self, "情報", "相関行列を計算できませんでした。")` して `return`。
6. `self._show_corr_window(names, mat)`。

### 3.9 `def _show_corr_window(self, names, mat):`

相関行列を色付き表ダイアログで表示する。

アルゴリズム / ウィジェット構築:

1. `dlg = QtWidgets.QDialog(self)`。`dlg.setWindowTitle("相関行列（ピアソン）")`（全角丸括弧）。
2. サイズ: `dlg.resize(min(120 + 90 * len(names), 900), min(120 + 30 * len(names), 700))`。
   - 幅 = `min(120 + 90*N, 900)`、高さ = `min(120 + 30*N, 700)`（`N = len(names)`）。
3. `lay = QtWidgets.QVBoxLayout(dlg)`。
4. `n = len(names)`。`tbl = QtWidgets.QTableWidget(n, n)`（n 行 n 列）。
5. `tbl.setHorizontalHeaderLabels(names)`、`tbl.setVerticalHeaderLabels(names)`。
6. 二重ループ `for i in range(n): for j in range(n):`
   - `v = float(mat[i, j])`（`mat` は ndarray。`mat[i, j]` の 2 軸インデックスで参照）。
   - `it = QtWidgets.QTableWidgetItem(f"{v:.3f}")`（小数 3 桁固定）。
   - `it.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)`（**スコープ付き列挙**）。
   - 色付け（相関の強さで着色。正=赤、負=青）:
     - `a = max(0.0, min(1.0, abs(v)))`（強度 0〜1 にクランプ）。
     - `if v >= 0:` → `it.setBackground(QtGui.QColor(255, int(255 * (1 - a)), int(255 * (1 - a))))`（赤を残し緑青を弱める）。
     - `else:` → `it.setBackground(QtGui.QColor(int(255 * (1 - a)), int(255 * (1 - a)), 255))`（青を残し赤緑を弱める）。
   - `tbl.setItem(i, j, it)`。
7. `lay.addWidget(tbl)`。
8. `btn = QtWidgets.QPushButton("閉じる")`。`btn.clicked.connect(dlg.accept)`。`lay.addWidget(btn)`。
9. `dlg.exec()`（モーダル表示。Qt6 では `exec()`。`exec_()` は使わない）。

色付けの意味: `abs(v)` が大きい（相関が強い）ほど色が濃くなる（`1 - a` が小さくなり、補色チャンネルが 0 に近づくため）。`v = 0` のとき白（255,255,255）。`v = +1` のとき純赤（255,0,0）、`v = -1` のとき純青（0,0,255）。

---

## 4. 定数・データ・UI 文字列（正確な値）

### 4.1 メッセージボックス文言（`QtWidgets.QMessageBox.information(self, タイトル, 本文)`）

すべてタイトルは `"情報"`。本文一覧:

- 対象未選択: `"データタブでY系列を選択してください。"`
- 数値取得不可: `"対象の数値データが取得できません。"`
- 回帰データ不足: `"回帰に十分なデータがありません。"`
- 記述統計データなし: `"数値データがありません。"`
- 正規性検定不可: `"正規性検定には scipy が必要です（または点数不足）。"`
- 相関行列 2 系列未満: `"相関行列には2系列以上をデータタブで選択してください。"`
- 相関行列計算不可: `"相関行列を計算できませんでした。"`

### 4.2 結果見出し（`ds_title` にセットする文字列）

- 線形回帰: `f"線形回帰: {disp}（Y vs X）"`
- 記述統計: `f"記述統計: {disp}"`
- 正規性: `f"正規性検定 (Shapiro-Wilk): {disp}"`

### 4.3 チェックボックスのツールチップ

- 結果テーブルの各行: `"チェックすると、この項目の値をグラフ上に注記表示します。"`

### 4.4 回帰結果テーブルのラベル順（再掲、厳守）

`点数 n` / `傾き slope` / `切片 intercept` / `相関 r (ピアソン)` / `決定係数 R²` / `p値 (傾き=0)` / `傾きの標準誤差` / `RMSE (残差)` / `直線性誤差 [%FS]` / （条件付き）`相関 (スピアマン)`。

### 4.5 記述統計の `order`（再掲、厳守）

`件数/count`, `平均/mean`, `中央値/median`, `標準偏差 σ/std`, `分散/var`, `最小/min`, `最大/max`, `範囲/range`, `変動係数 CV/cv`, `歪度 skew/skew`, `尖度 kurtosis/kurtosis`, `第1四分位 Q1/p25`, `中央 Q2/p50`, `第3四分位 Q3/p75`, `四分位範囲 IQR/iqr`。

### 4.6 `datasci` モジュールが返す dict のキー（呼び出し側として知っておく契約）

- `linear_regression(x, y)` → `{"n","slope","intercept","r","r2","p_value","std_err","rmse","linearity_error_pct"}`（scipy 無時は `p_value`/`std_err` が `None`、データ <2 点なら空 dict）。
- `describe(y)` → `count,mean,median,std,var,min,max,range,cv,p25,p50,p75,iqr,skew,kurtosis`（空配列なら空 dict）。`cv` は平均0で `None`。
- `correlation(x, y, method)` → `{"r","p_value"}`（点数 <2 で `None`、scipy 無時 `p_value` が `None`）。
- `correlation_matrix(named_series, method)` → `(names:list[str], mat:ndarray|None)`。
- `normality(y)` → `{"W","p_value","normal_5pct"}`（scipy 無 or 点数 <3 で空 dict）。

本ファイルはこれらを直接計算しないが、キー名はそのまま参照するため一致が必須。

---

## 5. 再現に必須の細部・エッジケース・ガード

- **`_fmt` の分岐順**: `None` → `bool` → `int` → `float`。bool を int より先に判定しないと `True`/`False` が `"1"`/`"0"` になってしまう（必ず bool 判定を先に）。
- **`_ds_show` の `had` 取得タイミング**: `_ds_annotations` を `[]` に上書きする**前**に `had` を取る。`had and _has_drawn` のときだけ `draw_graph()` を呼んで前回注記を消す（毎回描画しない＝無駄な再描画を避ける）。
- `_has_drawn` は `getattr(self, "_has_drawn", False)` で安全参照（未初期化でも落ちない）。
- `_ds_annotations` も `getattr(self, "_ds_annotations", None)` で安全参照（初回 `None`）。
- 注記文字列の書式は `f"{k.text()} = {v.text()}"`（イコール前後に半角スペース）。
- `_refresh_ds_annotations` は `*_` で余分な引数を受ける（`toggled(bool)` から接続されるため）。
- `show_describe` の値取り出しは `d.get(k)`（欠如キーに耐える）。他（回帰・正規性）は `d["..."]` 直接アクセスでよい（`datasci` が必ず全キーを返すため）。ただしキー名のタイプミスに注意。
- 相関行列セルの数値書式は `f"{v:.3f}"`、回帰/記述/正規性の値は `_fmt`（`.6g`）。書式が用途で異なる点に注意。
- `_show_corr_window` の `mat[i, j]` は ndarray の 2 軸インデックス。`mat[i][j]` でも動くが ndarray 前提で `mat[i, j]` と書く。
- ダイアログは `dlg.exec()`（Qt6）でモーダル表示。
- テーブル列番号: 0=項目, 1=値, 2=表示（チェックボックスのセルウィジェット）。

---

## 6. 本ファイルに関係する落とし穴

- **Qt6 スコープ付き列挙**: `QtCore.Qt.AlignmentFlag.AlignCenter` のように完全修飾で書く。`QtCore.Qt.AlignCenter`（Qt5 流）は不可。
- **Mixin 規約**: 本ファイルは `class DataSciMixin:` のメソッド束のみ。`__init__` を**書かない**。`from graph_app_common import *` 以外の import を増やさない。`@staticmethod`（`_fmt`）は装飾ごとこの Mixin に置く。
- **matplotlib 経由の Qt**: `QtWidgets` 等は `graph_app_common` 経由。本ファイルで `from PySide6 import ...` のように直接 import しない。
- **monospace 回避**: 注記・ラベル・テーブル項目に `family="monospace"` を指定しない（日本語が□化けする）。本ファイルはフォント指定をしないこと。
- **bool 判定順**（`_fmt`）: 既述。Python の `bool` は `int` サブクラスなので順序ミスで真偽値が数値化する。
- **再描画の無駄打ち回避**: `_ds_show` 末尾で `had and _has_drawn` を満たすときだけ再描画する（条件ガードを外すと毎回描き直して重くなる）。
- `datasci` 側のキー名・戻り値契約に依存。キー名を 1 文字でも変えると `KeyError` または `"—"` 表示になる。
- 相関行列ダイアログのサイズ計算は `min(..., 900)` / `min(..., 700)` で上限クランプ（系列が多くてもウィンドウが画面を超えない）。

---

## 7. 完成形の構造まとめ（実装ガイド）

```
# -*- coding: utf-8 -*-
"""...(上記 docstring)..."""
from graph_app_common import *  # noqa: F401,F403


class DataSciMixin:
    def _ds_xy(self): ...
    def _ds_show(self, title, rows): ...
    def _refresh_ds_annotations(self, *_): ...
    @staticmethod
    def _fmt(v): ...
    def run_regression(self): ...
    def show_describe(self): ...
    def run_normality(self): ...
    def show_corr_matrix(self): ...
    def _show_corr_window(self, names, mat): ...
```

各メソッドは上記 §3 の通り、`pass` や省略なしで完全に実装すること。
