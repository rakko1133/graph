# [18/30] graph_app_common.py の仕様

## 指示

- この仕様だけを読んで `graph_app_common.py` を **完全な形** で実装し、ファイル全体を出力すること。
- `pass` のみ・`TODO`・`...`（省略）・「以下同様」等の **要約や省略は一切禁止**。すべての関数・クラス・メソッド・定数・`__all__` を実コードとして書き切ること。
- 出力が長くて途中で切れた場合は、ユーザーが「続き」と言ったら **残りを最後まで** 出力すること（重複なく続きから）。

### アプリ全体の前提（このファイルに関係する分のみ）

- Python 3.10+ / GUI は PySide6（Qt6）。ただし Qt は **必ず matplotlib 経由** で取得する。本ファイルがその取得の中心であり、`from matplotlib.backends.qt_compat import QtCore, QtGui, QtWidgets` 等で受けて再公開する。
- Qt6 の列挙は **スコープ付き**（例: `QtCore.Qt.CheckState.Checked` / `QtCore.Qt.ItemDataRole.UserRole` / `QtCore.Qt.ItemFlag.ItemIsUserCheckable`）。本ファイルでもこの形を厳守する。
- `GraphApp` は 10 個の Mixin と `QtWidgets.QMainWindow` の多重継承で構成され、各 Mixin は **このファイルの先頭で `from graph_app_common import *`** を書いて共通 import・定数・補助クラスを取り込む。したがって本ファイルの `__all__` が「各 Mixin から見える共通名前空間」を決定する **唯一の定義元** である。
- 日本語に `family="monospace"` を使うと豆腐（□）化けするため使わない、`jp_font` で日本語フォント設定を行う、`grid` の `linewidth` に `None` を渡さない、等の規約はアプリ全体のもの。本ファイル自体はそれらの実装を持たないが、`jp_font` を再公開する役割を担う。

---

## 1. ファイルの役割 / 責務

`graph_app_common.py` は、`GraphApp` 本体と分割された各 Mixin が **共有する import・モジュール定数・補助クラス・補助関数を 1 箇所に集約** し、それらを `from graph_app_common import *` で一括取り込みできるようにするための共通モジュールである。

docstring（モジュール先頭）は次の 1 行：

```
"""GraphApp と各 Mixin が共有する import・定数・補助クラス。"""
```

ファイル先頭行は `# -*- coding: utf-8 -*-`（エンコーディング宣言）。

責務は次の 4 つ：

1. **Qt / matplotlib の共通 import を 1 回だけ行い再公開する**（各 Mixin が個別に import しないで済むようにする）。
2. **アプリ内の自作モジュール（`advanced` 等 8 個）を import して再公開する**。
3. **モジュール定数**（`PREVIEW_ROWS` 等）を定義する。
4. **補助関数 `_parse_float` と補助クラス `CheckListWidget` / `LazyColumnCombo` を提供する**。

最後に `__all__` でこれらの公開名を明示し、`import *` の対象を厳密に制御する。

---

## 2. 依存（import するもの）

標準ライブラリ：

```python
import os
import sys
```

matplotlib 経由の Qt とキャンバス類（**この順・この別名で**）：

```python
from matplotlib.backends.qt_compat import QtCore, QtGui, QtWidgets
from matplotlib.backends.backend_qtagg import (
    FigureCanvasQTAgg as FigureCanvas,
    NavigationToolbar2QT as NavigationToolbar,
)
from matplotlib.figure import Figure
```

アプリ内の自作モジュール（**アルファベット順、各 1 行**）：

```python
import advanced
import analysis
import config_io
import data_loader
import datasci
import jp_font
import mathchan
import plotter
```

注意：
- `analysis` / `plotter` は別ファイルで facade（実体の `import *` ＋アンダースコア名の明示 import による再公開）になっているが、本ファイルからは **モジュールとして普通に import するだけ** でよい。
- `scipy` の遅延 import は `datasci` / `analysis` 側の責務であり、本ファイルでは扱わない。
- 本ファイルには matplotlib の `pyplot` や `numpy` の import は **無い**（必要なら利用側が持つ）。

---

## 3. モジュール定数（正確な値そのまま）

| 名前 | 値 | 意味（コメントの趣旨） |
|---|---|---|
| `PREVIEW_ROWS` | `100` | プレビュー表示の行数上限。 |
| `UserRole` | `QtCore.Qt.ItemDataRole.UserRole` | Qt のユーザーデータロールを短い別名で再公開（スコープ付き列挙からエイリアス）。 |
| `DECIMATE_TARGET` | `8000` | 折れ線/散布図でこの点数を超えたら間引いて表示。 |
| `BUSY_ROWS` | `200_000` | この行数を超える読み込みは待機カーソルを出す。 |
| `BATCH_PARALLEL_THRESHOLD` | `64` | 一括出力でこの枚数以上なら別プロセス並列を試みる。 |

各行末コメント（再現時にそのまま付けること）：
- `DECIMATE_TARGET = 8000   # 折れ線/散布図でこの点数を超えたら間引いて表示`
- `BUSY_ROWS = 200_000      # この行数を超える読み込みは待機カーソルを出す`
- `BATCH_PARALLEL_THRESHOLD = 64   # 一括出力でこの枚数以上なら別プロセス並列を試みる`

`PREVIEW_ROWS` と `UserRole` にはコメントは付かない。`UserRole` は **`QtCore` の import 後** に定義する（参照順に注意）。

---

## 4. 公開 API（完全シグネチャと挙動）

### 4.1 関数 `_parse_float`

```python
def _parse_float(text, default=None):
```

- 役割：文字列入力を `float` に変換する。空欄や変換失敗時は `default` を返す堅牢パーサ。
- アルゴリズム：
  1. `text = (text or "").strip()` ＝ `None` 安全化してから前後空白を除去。
  2. `text == ""` なら `default` を返す。
  3. `try: return float(text)` を試みる。
  4. `except ValueError: return default`。
- 戻り値：`float`（成功時）または `default`（既定 `None`）。
- エッジケース：`None` を渡しても落ちない（`text or ""` で吸収）。`"  3.5 "` → `3.5`。`"abc"` → `default`。`""` / `"   "` → `default`。

### 4.2 クラス `CheckListWidget`（`QtWidgets.QListWidget` を継承）

docstring（趣旨をそのまま）：

```
"""行のどこをクリックしてもチェックがトグルするリスト。

チェックボックスの小さな枠だけでなく、行全体が当たり判定になる。
（Qt 標準のインジケータ自動トグルと二重にならないよう、ここで一括処理）
"""
```

- 役割：チェックボックス付きリストで、**行のどこをクリックしてもチェック状態がトグル** する `QListWidget`。標準ではインジケータの小さな枠しか反応しないのを、行全体に拡張する。
- `__init__` は **定義しない**（`QListWidget` の既定を使う）。
- メソッド：

```python
def mousePressEvent(self, event):
```

挙動（順序厳守）：
1. `item = self.itemAt(event.position().toPoint())` でクリック位置のアイテムを取得（Qt6 では `event.position()` が `QPointF` なので `.toPoint()` が必須）。
2. `item is not None` **かつ** `item.flags() & QtCore.Qt.ItemFlag.ItemIsUserCheckable`（ユーザーチェック可能フラグが立っている）場合：
   - `checked = item.checkState() == QtCore.Qt.CheckState.Checked` で現在状態を判定。
   - `item.setCheckState(...)` で反転：`checked` が真なら `QtCore.Qt.CheckState.Unchecked`、偽なら `QtCore.Qt.CheckState.Checked`。
   - `event.accept()` してから `return`（**`super()` を呼ばない**。Qt 標準のインジケータ自動トグルと二重にトグルさせないため）。
3. 上記条件に合致しない（アイテム外クリック等）なら `super().mousePressEvent(event)` に委譲。

落とし穴：手順 2 で `super()` を呼んでしまうと、標準のインジケータトグルと本クラスのトグルが重なって状態が打ち消し合う。必ず `accept()`＋`return` で止める。Qt6 列挙はすべてスコープ付き（`ItemFlag.ItemIsUserCheckable` / `CheckState.Checked` / `CheckState.Unchecked`）。

### 4.3 クラス `LazyColumnCombo`（`QtWidgets.QComboBox` を継承）

docstring（趣旨をそのまま）：

```
"""誤差列の選択コンボ。列一覧は初回オープン時に遅延展開する。

多系列でスタイル表を作り直すとき、各行のコンボへ全列を addItems すると重い
（多系列で支配的コスト）。最初は『なし』＋現在値だけを持ち、ユーザーが
ドロップダウンを開いた時に初めて全列を読み込む。"""
```

- 役割：誤差列（エラーバー用の列）を選ぶコンボボックス。スタイル表の各行に置くため、**生成コストを抑える遅延ロード** を実装する。多系列のとき各コンボへ全列を `addItems` するのが支配的コストなので、初期状態は最小限にしておき、ユーザーがドロップダウンを開いた瞬間に初めて全列を読み込む。

シグネチャ：

```python
def __init__(self, get_cols, current, parent=None):
```

`__init__` 挙動：
1. `super().__init__(parent)`。
2. `self._get_cols = get_cols`（列名一覧を返す **コールバック**。呼び出すと iterable を返す想定）。
3. `self._loaded = False`（まだ全列を読み込んでいないフラグ）。
4. `self.addItem("なし")`（先頭は常に文字列 `"なし"`）。
5. `if current:` 真なら `self.addItem(str(current))` し `self.setCurrentText(str(current))`（現在値だけは即座に表示できるよう先に入れる）。

メソッド：

```python
def showPopup(self):
```

挙動（初回オープン時のみ全列展開）：
1. `if not self._loaded:` のとき：
   - `self._loaded = True`（再展開を防ぐ）。
   - `cur = self.currentText()`（展開前の現在選択テキストを退避）。
   - `self.blockSignals(True)`（再構築中のシグナル抑制）。
   - `self.clear()` で一旦全消去。
   - `self.addItem("なし")` を先頭に再追加。
   - `for c in self._get_cols():` で全列を回し、`s = str(c)` にして **`s != "なし"` のものだけ** `self.addItem(s)`（`"なし"` の重複追加を避ける）。
   - `i = self.findText(cur)` で退避した現在値の位置を探し、`self.setCurrentIndex(i if i >= 0 else 0)`（見つからなければ先頭＝「なし」）。
   - `self.blockSignals(False)`。
2. 最後に必ず `super().showPopup()` を呼ぶ（ガード外でも毎回呼ぶ＝ポップアップ自体は常に開く）。

落とし穴 / 細部：
- `"なし"` という日本語ラベルは **正確にこの 2 文字**。先頭固定の「未選択」を表す。
- `get_cols` はコールバック（関数）。`__init__` 時点では呼ばず、`showPopup` 初回でのみ評価する（遅延の肝）。
- `blockSignals` で囲うことで、`clear()`/`addItem` の途中で `currentIndexChanged` 等が飛んで描画更新が誘発されるのを防ぐ。
- 2 回目以降の `showPopup` は `_loaded` が `True` なのでスキップして即 `super().showPopup()`。

---

## 5. `__all__`（再公開する公開名）

`import *` で各 Mixin に渡る名前を **この順で正確に** 列挙する。各 Mixin はこの `__all__` を通じて共通名を受け取るため、**1 つでも欠けると Mixin 側が `NameError` になる**。

```python
__all__ = [
    "os",
    "sys",
    "QtCore",
    "QtGui",
    "QtWidgets",
    "FigureCanvas",
    "NavigationToolbar",
    "Figure",
    "advanced",
    "analysis",
    "config_io",
    "data_loader",
    "datasci",
    "jp_font",
    "mathchan",
    "plotter",
    "PREVIEW_ROWS",
    "UserRole",
    "DECIMATE_TARGET",
    "BUSY_ROWS",
    "BATCH_PARALLEL_THRESHOLD",
    "_parse_float",
    "CheckListWidget",
    "LazyColumnCombo",
]
```

注意：
- 通常 `import *` はアンダースコア始まりの名前を取り込まないが、ここでは `__all__` に明示しているので **`_parse_float` も再公開される**（Mixin から `_parse_float(...)` をそのまま呼べる）。
- import した自作モジュール 8 個（`advanced`/`analysis`/`config_io`/`data_loader`/`datasci`/`jp_font`/`mathchan`/`plotter`）も全て列挙されており、Mixin はこれら経由で実機能にアクセスする。
- `__all__` はファイル末尾（`LazyColumnCombo` 定義の後）に置く。

---

## 6. 当該ファイル固有の落とし穴まとめ（再現チェックリスト）

1. **Qt は matplotlib 経由で取得**：`from matplotlib.backends.qt_compat import ...` を使う。直接 `from PySide6 import ...` しない（バックエンド整合のため）。
2. **Qt6 スコープ付き列挙**：`QtCore.Qt.ItemDataRole.UserRole` / `QtCore.Qt.ItemFlag.ItemIsUserCheckable` / `QtCore.Qt.CheckState.Checked` / `...Unchecked`。フラットな旧形式（`QtCore.Qt.UserRole` 等）は不可。
3. **`CheckListWidget.mousePressEvent` で `super()` を呼ばずに `accept()`＋`return`** する分岐がある（二重トグル防止）。アイテム外クリックのときだけ `super()` に委譲。
4. **`event.position().toPoint()`**：Qt6 では `position()` が `QPointF` を返すため `itemAt` に渡す前に `.toPoint()` で `QPoint` 化する。
5. **`LazyColumnCombo` は遅延ロード**：`get_cols` は `showPopup` 初回でのみ呼ぶ。`blockSignals` で囲み、`"なし"` 重複を避け、現在値を `findText` で復元（見つからなければ index 0）。
6. **`"なし"` は日本語ラベル**で `monospace` 等のフォント指定はしない（豆腐化け回避はアプリ規約だが、ここでは文字列を正確に保つこと）。
7. **`_parse_float` の `None` 安全化**：`(text or "").strip()` を必ず通す。
8. **`__all__` の網羅性**：上記 24 名すべてを列挙。Mixin の `from graph_app_common import *` がこの定義に依存する。
9. このファイルには `__init__` を持つ `GraphApp` 本体や Mixin 本体は **含まれない**（共通基盤のみ）。再描画デバウンスや AST 安全評価などの実装も **ここには書かない**。
