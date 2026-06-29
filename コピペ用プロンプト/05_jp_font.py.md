# [5/30] ファイル `jp_font.py` を作成

あなたは PySide6 + matplotlib 製のデスクトップアプリ「CSV / TSV / 波形 グラフ・解析ツール」を、複数ファイルに分けて再現しています。
これはその **5 番目** のファイルです（全 30 ファイル）。

## 指示（厳守）
- 下のコードブロックの内容で、ファイル `jp_font.py` を**新規作成**してください。
- **一字一句そのまま・省略なし**で出力すること。`pass` だけの空クラス／`# TODO`／`… 省略 …`／要約・解説への置き換えは**禁止**。
- 出力が途中で切れたら、こちらが「続き」と言うので、**最後の行まで**出力してください。
- 前置き・後書き・他ファイルの説明は不要。**このファイルの完全な中身だけ**を返してください。
- 文字コードは UTF-8。フォルダ付きパス（例 `graph_app_mixins/...`）はその階層に作成してください。

## `jp_font.py` の中身（このまま出力）
```python
"""matplotlib に日本語フォントを設定するユーティリティ。

OS にインストールされている一般的な日本語フォントを優先順に探し、
最初に見つかったものを matplotlib の既定フォントに設定する。
タイトル・軸ラベル・凡例の日本語が文字化け（□□□）しないようにする。
"""

import matplotlib
import matplotlib.font_manager as fm

# 優先順位（上から順に探す）。Windows / macOS / Linux の代表的な日本語フォント。
_CANDIDATES = [
    # Windows
    "Yu Gothic", "Meiryo", "BIZ UDGothic", "MS Gothic", "MS PGothic", "Yu Mincho",
    # macOS
    "Hiragino Sans", "Hiragino Kaku Gothic Pro", "Hiragino Maru Gothic Pro",
    # Linux（インストールされていれば）
    "Noto Sans CJK JP", "IPAexGothic", "IPAGothic", "TakaoGothic", "VL Gothic",
]


def available_japanese_fonts():
    """利用可能な日本語フォント名の一覧を優先順で返す。"""
    installed = {f.name for f in fm.fontManager.ttflist}
    return [name for name in _CANDIDATES if name in installed]


def setup_japanese_font(preferred=None):
    """日本語フォントを matplotlib に設定し、採用したフォント名を返す。

    Parameters
    ----------
    preferred : str | None
        明示的に使いたいフォント名。利用可能ならこれを最優先で採用する。

    Returns
    -------
    str | None
        採用したフォント名。見つからなければ None。
    """
    installed = {f.name for f in fm.fontManager.ttflist}

    order = []
    if preferred:
        order.append(preferred)
    order.extend(_CANDIDATES)

    for name in order:
        if name in installed:
            # sans-serif の先頭に入れておくと未指定箇所でも日本語が出る
            matplotlib.rcParams["font.family"] = "sans-serif"
            current = matplotlib.rcParams.get("font.sans-serif", [])
            matplotlib.rcParams["font.sans-serif"] = [name] + [
                f for f in current if f != name
            ]
            matplotlib.rcParams["axes.unicode_minus"] = False  # マイナス記号の文字化け防止
            return name

    # 日本語フォントが見つからない場合も、最低限マイナス記号の化けだけは防ぐ
    matplotlib.rcParams["axes.unicode_minus"] = False
    return None
```
