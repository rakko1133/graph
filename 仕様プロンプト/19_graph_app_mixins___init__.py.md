# [19/30] graph_app_mixins/__init__.py の仕様

## 指示

- この仕様書だけを読んで、`graph_app_mixins/__init__.py` を **完全な形** で実装し、ファイル全文を出力してください。
- `pass` だけの空実装、`# TODO`、`...`(省略)、「(以下略)」「元コード参照」などの **要約・省略は一切禁止** です。インポート文・`__all__` の中身は本仕様に書かれた通り **そのまま全部** 書いてください。
- 出力が長くて途中で切れた場合は、続けて「続き」と入力されたら **最後の行まで** 残りを出力してください。
- このファイルは短いパッケージ初期化ファイル（facade / 集約 re-export）ですが、**インポートの並び順・名前・`__all__` の要素と順序を1つも欠かさず** 再現することが要件です。

### アプリ全体の前提（このファイルに関係する分のみ）

- Python 3.10+ / GUI=PySide6(Qt6)。ただし Qt は必ず matplotlib 経由で取得する規約（このファイル自体は Qt を import しない）。
- `GraphApp` は **10 個の Mixin ＋ `QtWidgets.QMainWindow`** の多重継承で構成される。`__init__` / `closeEvent` は `GraphApp` 本体に置き、各 Mixin は `from graph_app_common import *` で始まる **メソッド束** で、`__init__` を持たない。`@staticmethod` は装飾ごと担当 Mixin に置く。
- このファイル `graph_app_mixins/__init__.py` は、その **10 個の Mixin クラスをサブモジュールから集めて再公開する** パッケージの入口（facade 的役割）である。

---

## 1. ファイルの役割 / 責務

`graph_app_mixins` パッケージの初期化モジュール。役割は次の一点に集約される。

- **`GraphApp` を構成する概念別 Mixin 群**（UI 構築・データ入出力・スタイル表・描画・スコープ/カーソル・解析/ピーク・高度ツール・データサイエンス系ツール・バッチ・永続化）を、それぞれの実装サブモジュールから import し、パッケージ名前空間 `graph_app_mixins` の **トップレベルで再公開**する。
- これにより上位の `graph_app.py` 側は

  ```python
  from graph_app_mixins import (
      UIBuildMixin, DataIOMixin, StyleTableMixin, PlotMixin,
      ScopeCursorMixin, AnalysisMixin, AdvancedMixin, DataSciMixin,
      BatchMixin, PersistenceMixin,
  )
  ```

  のように、サブモジュールの物理ファイル名（`ui_build` 等）を意識せず、概念名（`UIBuildMixin` 等）だけで全 Mixin を取得できる。
- ロジック・関数・クラス定義は **一切持たない**。あくまで「サブモジュール → トップレベル」へ名前を引き上げるだけの薄い集約層。

### モジュール docstring

ファイル冒頭（エンコーディング宣言の次の行）に、次の趣旨の 1 行 docstring を置く（文言は原文準拠）。

```
"""GraphApp を構成する概念別 Mixin 群。"""
```

### 先頭行

1 行目は次のエンコーディング宣言コメントとする（原文準拠）。

```
# -*- coding: utf-8 -*-
```

---

## 2. 依存（import するもの）

このファイルは **同一パッケージ内のサブモジュールからの相対 import のみ** を行う。標準ライブラリ・サードパーティ（Qt / numpy / matplotlib 等）の import は **一切行わない**。

相対 import は **次の 10 行を、この順序で** 記述すること（`from .<module> import <ClassName>` の形）。モジュールファイル名（左）と公開クラス名（右）の対応は厳密に守る。

| 行順 | import 文 | 物理モジュール | 公開クラス名 |
|---|---|---|---|
| 1 | `from .ui_build import UIBuildMixin` | `ui_build.py` | `UIBuildMixin` |
| 2 | `from .data_io import DataIOMixin` | `data_io.py` | `DataIOMixin` |
| 3 | `from .style_table import StyleTableMixin` | `style_table.py` | `StyleTableMixin` |
| 4 | `from .plotting import PlotMixin` | `plotting.py` | `PlotMixin` |
| 5 | `from .scope_cursor import ScopeCursorMixin` | `scope_cursor.py` | `ScopeCursorMixin` |
| 6 | `from .analysis_peaks import AnalysisMixin` | `analysis_peaks.py` | `AnalysisMixin` |
| 7 | `from .advanced_tools import AdvancedMixin` | `advanced_tools.py` | `AdvancedMixin` |
| 8 | `from .datasci_tools import DataSciMixin` | `datasci_tools.py` | `DataSciMixin` |
| 9 | `from .batch import BatchMixin` | `batch.py` | `BatchMixin` |
| 10 | `from .persistence import PersistenceMixin` | `persistence.py` | `PersistenceMixin` |

注意点（再現に必須の細部）:

- **モジュール名とクラス名は同名ではない**。例えば `analysis_peaks` モジュールが公開するのは `AnalysisMixin`（`AnalysisPeaksMixin` ではない）。`plotting` → `PlotMixin`（`PlottingMixin` ではない）。`advanced_tools` → `AdvancedMixin`、`datasci_tools` → `DataSciMixin`、`ui_build` → `UIBuildMixin`、`data_io` → `DataIOMixin`、`style_table` → `StyleTableMixin`、`scope_cursor` → `ScopeCursorMixin`、`batch` → `BatchMixin`、`persistence` → `PersistenceMixin`。表の対応を **左右取り違えないこと**。
- import は **必ず相対 import（先頭ドット付き）** で書く。`from ui_build import ...` のような絶対 import にしない。
- これら 10 サブモジュールは、各々の先頭が `from graph_app_common import *` で始まり、`class XxxMixin:` を 1 つだけ定義している前提（このファイルからは中身に触れない）。

---

## 3. 公開 API

このファイルには **関数・クラス・メソッドの定義は存在しない**。公開する API は「再公開された 10 個の Mixin クラス（名前）」と「`__all__` リスト」のみ。

### 3.1 再公開されるシンボル（10 個）

import によって `graph_app_mixins` トップレベルから参照可能になるクラス（すべて他モジュールで定義された Mixin クラスのエイリアス的再公開。本ファイルでの定義は無い）:

1. `UIBuildMixin` — UI 構築（ウィジェット/レイアウト/タブ生成）担当。
2. `DataIOMixin` — データ入出力（CSV 読み込み等）担当。
3. `StyleTableMixin` — スタイル表（系列ごとの色/線種等のテーブル）担当。
4. `PlotMixin` — 描画（再描画・軸設定・デバウンス連携）担当。
5. `ScopeCursorMixin` — スコープ/カーソル（範囲選択・カーソル計測）担当。
6. `AnalysisMixin` — 解析/ピーク検出担当。
7. `AdvancedMixin` — 高度ツール担当。
8. `DataSciMixin` — データサイエンス系ツール担当。
9. `BatchMixin` — バッチ描画（spawn 安全・Qt を import しない側と連携）担当。
10. `PersistenceMixin` — 永続化（設定/状態の保存・復元）担当。

各 Mixin の内部仕様は本ファイルの責務外。ここでは **名前・並び順・存在することのみ** が要件。

### 3.2 `__all__`

モジュール末尾に、再公開する 10 クラス名を列挙した `__all__` リストを定義する。**要素の順序は §2 の import 順と完全一致**させること（`from graph_app_mixins import *` および静的解析・補完で公開 API を明示する目的）。

正確な値（この通りに書く）:

```python
__all__ = [
    "UIBuildMixin",
    "DataIOMixin",
    "StyleTableMixin",
    "PlotMixin",
    "ScopeCursorMixin",
    "AnalysisMixin",
    "AdvancedMixin",
    "DataSciMixin",
    "BatchMixin",
    "PersistenceMixin",
]
```

注意点:

- 要素は **すべて文字列リテラル**（クラスオブジェクトそのものではなく名前の文字列）。
- 10 要素ちょうど。**`DataSciMixin` を含める**（過去版で抜けやすいので注意。`graph_app.py` の `GraphApp` 多重継承にも `DataSciMixin` が含まれる）。
- 並び順: `UIBuildMixin → DataIOMixin → StyleTableMixin → PlotMixin → ScopeCursorMixin → AnalysisMixin → AdvancedMixin → DataSciMixin → BatchMixin → PersistenceMixin`。この順序は `GraphApp` の MRO（メソッド解決順）と一致しており、Mixin 間で同名メソッドが衝突した場合の優先順位に影響しうるため、**並び替えてはならない**。

---

## 4. 定数・データ（正確な値）

このファイルが持つ「データ」は実質的に上記 2 つだけ:

- **10 本の相対 import 文**（§2 の表の通り、上から順）。
- **`__all__` リスト**（§3.2 の通り、10 要素・順序固定）。

その他のモジュール定数・辞書・UI ラベル・日本語文字列は **存在しない**（docstring と先頭コメントを除く）。日本語文字列は docstring の `GraphApp を構成する概念別 Mixin 群。` のみ。

---

## 5. ファイル全体の構造（再現用レイアウト）

上から順に、次の順序で記述する（空行も含めた論理構成）。

1. `# -*- coding: utf-8 -*-`（1 行目、エンコーディング宣言）
2. `"""GraphApp を構成する概念別 Mixin 群。"""`（モジュール docstring、1 行）
3. §2 の 10 本の `from .<module> import <ClassName>` を、表の順番で連続して記述。
4. （空行 1〜2 行を挟む）
5. §3.2 の `__all__ = [ ... ]`（10 要素、import と同順）。

合計でおおよそ 25 行前後の短いファイル。ロジックは無し。

---

## 6. 再現に必須の細部・エッジケース・落とし穴

- **import 順 = `__all__` 順 = `GraphApp` の継承順**。三者を一致させること。順序は MRO に影響するため意味を持つ。`PersistenceMixin` が最後、`QtWidgets.QMainWindow` はさらにその後（ただし QMainWindow の継承は `graph_app.py` 側の責務で、このファイルには出てこない）。
- **モジュール名 ≠ クラス名** の対応ミスに注意（§2 の落とし穴）。特に `analysis_peaks → AnalysisMixin`、`plotting → PlotMixin`、`advanced_tools → AdvancedMixin`、`datasci_tools → DataSciMixin`。
- **相対 import を使う**（先頭ドット必須）。`graph_app_mixins` はパッケージ（`__init__.py` を持つディレクトリ）であり、サブモジュールはパッケージ相対で解決する。
- **このファイルでは Qt を import しない**。Qt6 列挙（`QtCore.Qt.CheckState.Checked` 等）や matplotlib 経由取得の規約は **サブモジュール側** の話で、ここには登場しない。よって Qt 関連のコードを書き足してはいけない。
- **`from graph_app_common import *` はここには書かない**。それは各 Mixin サブモジュール先頭に置く規約であり、`__init__.py` の責務外。
- **`DataSciMixin` の欠落に注意**。10 個揃っているか（特に 8 番目）を必ず確認する。これが欠けると `graph_app.py` の `from graph_app_mixins import (... DataSciMixin ...)` が `ImportError` になり、アプリ全体が起動不能になる。
- **monospace 回避・grid linewidth=None 回避・scipy 遅延 import・デバウンス再描画** 等の他規約は、いずれも **このファイルには直接関係しない**（描画/フォント/解析サブモジュール側の責務）。ここで余計な実装を加えないこと。
- 副作用のある処理（インスタンス化・関数呼び出し・グローバル状態変更）は **一切書かない**。import と `__all__` 定義のみ。
- import に失敗するサブモジュールがあっても、このファイル側で `try/except` してフォールバックする設計には **しない**（10 Mixin は必須依存。欠けたら明示的にエラーで落ちるのが正しい）。
