# [13/30] ファイル `analysis.py` を作成

あなたは PySide6 + matplotlib 製のデスクトップアプリ「CSV / TSV / 波形 グラフ・解析ツール」を、複数ファイルに分けて再現しています。
これはその **13 番目** のファイルです（全 30 ファイル）。

## 指示（厳守）
- 下のコードブロックの内容で、ファイル `analysis.py` を**新規作成**してください。
- **一字一句そのまま・省略なし**で出力すること。`pass` だけの空クラス／`# TODO`／`… 省略 …`／要約・解説への置き換えは**禁止**。
- 出力が途中で切れたら、こちらが「続き」と言うので、**最後の行まで**出力してください。
- 前置き・後書き・他ファイルの説明は不要。**このファイルの完全な中身だけ**を返してください。
- 文字コードは UTF-8。フォルダ付きパス（例 `graph_app_mixins/...`）はその階層に作成してください。

## `analysis.py` の中身（このまま出力）
```python
# -*- coding: utf-8 -*-
"""オシロスコープ相当のデータ解析モジュール（ファサード）。

実体は analysis_common / analysis_spectrum / analysis_measure に分割。
従来どおり analysis.X で全関数にアクセスできるよう再エクスポートする。
GUI から独立しているので単体でも利用・テストできる。
"""
from analysis_common import *       # noqa: F401,F403
from analysis_spectrum import *     # noqa: F401,F403
from analysis_measure import *      # noqa: F401,F403
# 後方互換：アンダースコア付きの内部関数も analysis.X で参照可能にする
from analysis_common import (_simple_peaks, _zero_crossing_period, _edge_time,
                             _window, _mid_crossings, _trapz, _HAVE_SCIPY)
```
