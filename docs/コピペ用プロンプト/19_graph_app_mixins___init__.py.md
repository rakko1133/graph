# [19/30] ファイル `graph_app_mixins/__init__.py` を作成

あなたは PySide6 + matplotlib 製のデスクトップアプリ「CSV / TSV / 波形 グラフ・解析ツール」を、複数ファイルに分けて再現しています。
これはその **19 番目** のファイルです（全 30 ファイル）。

## 指示（厳守）
- 下のコードブロックの内容で、ファイル `graph_app_mixins/__init__.py` を**新規作成**してください。
- **一字一句そのまま・省略なし**で出力すること。`pass` だけの空クラス／`# TODO`／`… 省略 …`／要約・解説への置き換えは**禁止**。
- 出力が途中で切れたら、こちらが「続き」と言うので、**最後の行まで**出力してください。
- 前置き・後書き・他ファイルの説明は不要。**このファイルの完全な中身だけ**を返してください。
- 文字コードは UTF-8。フォルダ付きパス（例 `graph_app_mixins/...`）はその階層に作成してください。

## `graph_app_mixins/__init__.py` の中身（このまま出力）
```python
# -*- coding: utf-8 -*-
"""GraphApp を構成する概念別 Mixin 群。"""
from .ui_build import UIBuildMixin
from .data_io import DataIOMixin
from .style_table import StyleTableMixin
from .plotting import PlotMixin
from .scope_cursor import ScopeCursorMixin
from .analysis_peaks import AnalysisMixin
from .advanced_tools import AdvancedMixin
from .datasci_tools import DataSciMixin
from .batch import BatchMixin
from .persistence import PersistenceMixin

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
