# -*- coding: utf-8 -*-
"""matplotlib / 日本語スタイル値 → Excel(COM・openpyxl) 値への対応表。

既存アプリ（plotter.LINESTYLES / MARKERS / DEFAULT_STYLE）が使う matplotlib 流の
値（"-" "--" "o" "s" "#1f77b4" など）を、そのまま Excel ネイティブグラフの
プロパティへ翻訳する。COM 側は VBA と同じ enum 値（整数）、openpyxl 側は
OOXML の文字列を返す。GUI には一切依存しない純粋関数群。
"""

# --- matplotlib linestyle -> (msoLineDashStyle int, openpyxl prstDash) ---
# msoLineSolid=1, msoLineSquareDot=2, msoLineRoundDot=3, msoLineDash=4,
# msoLineDashDot=5。「なし」は線を非表示にするので None を返す。
LINE_DASH = {
    "-":    (1, "solid"),
    "--":   (4, "dash"),
    "-.":   (5, "dashDot"),
    ":":    (3, "sysDot"),
    "None": (None, None),
    "":     (None, None),
}

# --- matplotlib marker -> (xlMarkerStyle int, openpyxl symbol) ---
# xlMarkerStyleNone=-4142, Square=1, Diamond=2, Triangle=3, Circle=8, Plus=9,
# X=-4168, Dot=-4118
MARKER = {
    "":  (-4142, "none"),
    "o": (8, "circle"),
    "s": (1, "square"),
    "^": (3, "triangle"),
    "D": (2, "diamond"),
    "d": (2, "diamond"),
    "x": (-4168, "x"),
    "+": (9, "plus"),
    ".": (-4118, "dot"),
    "*": (-4118, "star"),
    "v": (3, "triangle"),
}


def excel_marker(marker):
    """matplotlib マーカー -> xlMarkerStyle 整数（不明は丸）。"""
    return MARKER.get(marker or "", (8, "circle"))[0]


def openpyxl_marker(marker):
    """matplotlib マーカー -> openpyxl symbol 文字列（不明は circle）。"""
    return MARKER.get(marker or "", (8, "circle"))[1]


def excel_dash(linestyle):
    """matplotlib 線種 -> (msoLineDashStyle int or None)。None は『線なし』。"""
    return LINE_DASH.get(linestyle, (1, "solid"))[0]


def openpyxl_dash(linestyle):
    """matplotlib 線種 -> (openpyxl prstDash or None)。None は『線なし』。"""
    return LINE_DASH.get(linestyle, (1, "solid"))[1]


# --- 凡例位置 ---------------------------------------------------------------
def excel_legend_position(loc):
    """matplotlib legend loc -> xlLegendPosition 整数。

    Excel の凡例位置は上下左右＋右上隅のみ。matplotlib の細かい loc は
    最寄りの方角へ丸める（best/center/右系はすべて右）。
    """
    loc = (loc or "best").lower()
    if "bottom" in loc or "lower" in loc:
        return -4107   # xlLegendPositionBottom
    if "top" in loc or "upper" in loc:
        return -4160   # xlLegendPositionTop
    if "left" in loc:
        return -4131   # xlLegendPositionLeft
    return -4152       # xlLegendPositionRight


def openpyxl_legend_position(loc):
    """matplotlib legend loc -> openpyxl legend.position ('r'/'l'/'t'/'b')。"""
    loc = (loc or "best").lower()
    if "bottom" in loc or "lower" in loc:
        return "b"
    if "top" in loc or "upper" in loc:
        return "t"
    if "left" in loc:
        return "l"
    return "r"


# --- 色 --------------------------------------------------------------------
def _parse_hex(color):
    """'#RRGGBB' / '#RGB' / 既知の色名 -> (R, G, B) tuple。不正/None は None。"""
    if not color:
        return None
    s = str(color).strip()
    if s.startswith("#"):
        s = s[1:]
    if len(s) == 3:
        s = "".join(ch * 2 for ch in s)
    if len(s) != 6:
        # 色名（'red' 等）は matplotlib があれば解決、無ければ諦める
        try:
            from matplotlib.colors import to_hex
            s = to_hex(color)[1:]
        except Exception:
            return None
    try:
        return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
    except ValueError:
        return None


def hex_to_bgr(color):
    """'#RRGGBB' -> Excel COM の .RGB が要求する整数 0x00BBGGRR(BGR)。

    重要: Excel/VBA の RGB は web の 0xRRGGBB ではなく BGR バイト順。
    例えば赤 #FF0000 は 0x0000FF を返す。None/不正色は None。
    """
    rgb = _parse_hex(color)
    if rgb is None:
        return None
    r, g, b = rgb
    return r | (g << 8) | (b << 16)


def hex_to_rrggbb(color):
    """'#RRGGBB' -> openpyxl が要求する 'RRGGBB'（# なし大文字）。None は None。"""
    rgb = _parse_hex(color)
    if rgb is None:
        return None
    return "%02X%02X%02X" % rgb


# --- Excel(XlChartType) / openpyxl チャート種別 ------------------------------
# XlChartType 整数
XL = {
    "line":            4,      # xlLine
    "line_markers":    65,     # xlLineMarkers
    "xy_lines":        74,     # xlXYScatterLines（数値Xの折れ線に最適）
    "xy_lines_nomark": 75,     # xlXYScatterLinesNoMarkers
    "xy_scatter":      -4169,  # xlXYScatter（散布図・マーカーのみ）
    "column":          51,     # xlColumnClustered
    "column_stacked":  52,     # xlColumnStacked
    "bar":             57,     # xlBarClustered（横棒）
    "bar_stacked":     58,     # xlBarStacked
    "pie":             5,      # xlPie
}

# 軸・スケール等の XL 定数
XL_CATEGORY = 1
XL_VALUE = 2
XL_PRIMARY = 1
XL_SECONDARY = 2
XL_SCALE_LINEAR = -4132        # xlLinear
XL_SCALE_LOG = -4133           # xlLogarithmic
