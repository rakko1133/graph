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
