"""グラフ描画ロジック（系列ベース）。

複数ファイル由来の系列をまとめて描画でき、系列ごとに色・線種・線幅・マーカーを
指定できる。軸範囲・対数軸・凡例位置などの編集にも対応。さらにオシロスコープ風の
div グリッド表示（time/div・V/div・位置オフセット）をサポートする。

GUI から独立しているので単体でも利用・テストできる。
"""


import warnings  # noqa: F401
from functools import partial

import numpy as np
import pandas as pd  # noqa: F401

from plotter_format import *   # noqa: F401,F403
from plotter_draw import *     # noqa: F401,F403
# plot_series が直接呼ぶ低レベル描画（アンダースコア）を取り込む
from plotter_draw import (_draw_xy, _draw_hist, _draw_box, _draw_bar, _draw_pie,
                          _draw_area, _draw_stack, _draw_violin, _draw_hist2d,
                          _draw_hexbin, _draw_heatmap, _draw_3d,
                          _remove_twin, _remove_aux_axes, _apply_scope, _data_labels)


# ---------------------------------------------------------------------------
# グラフ種別レジストリ（拡張点②）
#
# 各グラフ種別は ChartType として登録表 _CHART_SPECS に入る。本体 plot_series は
# 「種別名 → ChartType」を引くだけで分岐し、種別固有の 2D 描画は spec.draw に委譲
# する。register_chart_type() を呼べば plot_series を一切変更せずに新しい種別を
# 追加できる。外部が従来参照してきた CHART_TYPES / CHART_INFO / _PIE_TYPES などの
# 名前は、登録表から導出した「ビュー」として維持する（後方互換。登録のたびに再構築
# するので、後から足した種別も GUI 側の判定にそのまま反映される）。
# ---------------------------------------------------------------------------


class _DrawCtx:
    """種別ごとの描画関数へ渡す描画パラメータ束。"""
    __slots__ = ("categories", "bins", "fonts", "data_labels", "trendline",
                 "max_points", "secondary_label", "zlabel", "pct")

    def __init__(self, *, categories=None, bins=10, fonts=None, data_labels=False,
                 trendline=None, max_points=0, secondary_label="", zlabel="",
                 pct=False):
        self.categories = categories
        self.bins = bins
        self.fonts = fonts or {}
        self.data_labels = data_labels
        self.trendline = trendline
        self.max_points = max_points
        self.secondary_label = secondary_label
        self.zlabel = zlabel
        self.pct = pct


class ChartType:
    """1つのグラフ種別の定義。

    name            : 表示名（CHART_TYPES に並ぶキー）
    info            : use_x / multi_y / multi_file / dim3 / hint を持つメタ情報
    draw            : draw(ax, series, ctx, spec) -> ax2 もしくは None。2D描画の本体。
                      3D描画（threed 指定・『常に3D』種別）は plot_series が _draw_3d
                      を呼ぶため、ここは通らない。
    is_pie          : 円系（軸ラベル・凡例・グリッド・軸範囲を持たない）
    is_xy           : XY 折れ線系（第2軸・近似曲線に対応、_draw_xy を通す）
    default_kind    : XY 種別の既定系列 kind（per-series 指定があればそちらを優先）
    line            : _draw_xy の line フラグ（折れ線のみ True）
    scope_ok        : オシロ格子・カーソルを許可する種別
    swap_ok         : X↔Y 入れ替えが意味を持つ種別
    y_default_label : Y ラベル未指定時の既定（ヒストグラムの「頻度」など）
    """

    def __init__(self, name, *, info, draw, is_pie=False, is_xy=False,
                 default_kind=None, line=False, scope_ok=False, swap_ok=False,
                 y_default_label=""):
        self.name = name
        self.info = dict(info)
        self.draw = draw
        self.is_pie = is_pie
        self.is_xy = is_xy
        self.default_kind = default_kind
        self.line = line
        self.scope_ok = scope_ok
        self.swap_ok = swap_ok
        self.y_default_label = y_default_label

    @property
    def always_3d(self):
        """チェックに関わらず常に3Dで描く種別か（曲面など）。"""
        return self.info.get("dim3") == "always"


_CHART_ORDER = []          # 表示順（CHART_TYPES の並びと一致）
_CHART_SPECS = {}          # name -> ChartType

# 後方互換ビュー（register のたびに _rebuild_chart_views で作り直す）
CHART_TYPES = []
CHART_INFO = {}
_PIE_TYPES = ()
_XY_TYPES = ()
_XY_DEFAULT_KIND = {}
_SCOPE_TYPES = ()
_SWAP_TYPES = ()


def register_chart_type(spec, *, index=None):
    """グラフ種別を登録表に加える（本体を変更しない拡張点）。

    同名は表示位置を保って後勝ちで差し替える。新規は index 位置（省略時は末尾）へ。"""
    name = spec.name
    if name not in _CHART_SPECS:
        if index is None:
            _CHART_ORDER.append(name)
        else:
            _CHART_ORDER.insert(index, name)
    _CHART_SPECS[name] = spec
    _rebuild_chart_views()
    return spec


def get_chart_type(name):
    """登録済み ChartType を返す（未登録なら None）。"""
    return _CHART_SPECS.get(name)


def chart_types():
    """登録済み種別名を表示順で返す。"""
    return list(_CHART_ORDER)


def _rebuild_chart_views():
    """外部参照用の派生ビュー（CHART_TYPES 等）を登録表から作り直す。"""
    global CHART_TYPES, CHART_INFO, _PIE_TYPES, _XY_TYPES
    global _XY_DEFAULT_KIND, _SCOPE_TYPES, _SWAP_TYPES
    CHART_TYPES = list(_CHART_ORDER)
    CHART_INFO = {n: _CHART_SPECS[n].info for n in _CHART_ORDER}
    _PIE_TYPES = tuple(n for n in _CHART_ORDER if _CHART_SPECS[n].is_pie)
    _XY_TYPES = tuple(n for n in _CHART_ORDER if _CHART_SPECS[n].is_xy)
    _XY_DEFAULT_KIND = {n: _CHART_SPECS[n].default_kind for n in _CHART_ORDER
                        if _CHART_SPECS[n].is_xy and _CHART_SPECS[n].default_kind}
    _SCOPE_TYPES = tuple(n for n in _CHART_ORDER if _CHART_SPECS[n].scope_ok)
    _SWAP_TYPES = tuple(n for n in _CHART_ORDER if _CHART_SPECS[n].swap_ok)


# --- 種別ごとの 2D 描画関数: draw(ax, series, ctx, spec) -> ax2 もしくは None ---

def _draw_chart_xy(ax, series, ctx, spec):
    ax2 = None
    if any((sr.get("axis") == "secondary") for sr in series):
        ax2 = ax.twinx()
        ax._twin_secondary = ax2
        if ctx.secondary_label:
            ax2.set_ylabel(ctx.secondary_label, fontsize=ctx.fonts.get("label", 10))
    _draw_xy(ax, series, line=spec.line, max_points=ctx.max_points, ax2=ax2,
             data_labels=ctx.data_labels, trendline=ctx.trendline, fonts=ctx.fonts,
             default_skind=spec.default_kind)
    return ax2


def _draw_chart_stack(ax, series, ctx, spec):
    _draw_stack(ax, series)


def _draw_chart_hist(ax, series, ctx, spec):
    _draw_hist(ax, series, ctx.bins)


def _draw_chart_hist2d(ax, series, ctx, spec):
    _draw_hist2d(ax, series, ctx.bins)


def _draw_chart_hexbin(ax, series, ctx, spec):
    _draw_hexbin(ax, series, ctx.bins)


def _draw_chart_box(ax, series, ctx, spec):
    _draw_box(ax, series)


def _draw_chart_violin(ax, series, ctx, spec):
    _draw_violin(ax, series)


def _draw_chart_heatmap(ax, series, ctx, spec):
    _draw_heatmap(ax, series)


def _draw_chart_bar(ax, series, ctx, spec, *, horizontal=False, stacked=False):
    if ctx.categories is None:
        raise ValueError("X軸（カテゴリ）の列を選択してください。")
    _draw_bar(ax, series, ctx.categories, horizontal=horizontal, stacked=stacked,
              data_labels=ctx.data_labels, fonts=ctx.fonts)


def _draw_chart_pie(ax, series, ctx, spec, *, donut=False):
    if ctx.categories is None:
        raise ValueError("X軸（ラベル）の列を選択してください。")
    _draw_pie(ax, series[0], ctx.categories, pct=ctx.pct, donut=donut)


def _draw_chart_surface(ax, series, ctx, spec):
    # 曲面は『常に3D』のため plot_series が _draw_3d を呼ぶ。2D 経路は通らない。
    return None


# 旧バージョンの『3D…』種別名 → 新しい2D種別名（3Dフラグは別途ON）
_OLD_3D_ALIASES = {"3D散布図": "散布図", "3D折れ線": "折れ線",
                   "3D棒": "棒", "3D曲面": "曲面"}


def always_3d(chart_type):
    """常に3Dで描く種別か（曲面など。チェックに関わらず3D）。"""
    spec = get_chart_type(chart_type)
    return bool(spec and spec.info.get("dim3") == "always")


def migrate_chart_type(name):
    """旧『3D…』種別名を (新種別名, 3Dフラグ) に変換する。

    旧名なら (2D種別名, True)。それ以外は (そのまま, None＝3Dフラグは触らない)。"""
    if name in _OLD_3D_ALIASES:
        return _OLD_3D_ALIASES[name], True
    return name, None


def _register_builtin_charts():
    """組み込み18種別を登録表へ入れる（本体の既定挙動）。"""
    reg = register_chart_type
    reg(ChartType(
        "折れ線",
        info={"use_x": True, "multi_y": True, "multi_file": True, "dim3": "optional",
              "hint": "X軸に1列、Y軸に1列以上。複数ファイルの重ね描き可（『3D表示』でZ軸を使う3D線に）"},
        draw=_draw_chart_xy, is_xy=True, default_kind="line", line=True,
        scope_ok=True, swap_ok=True))
    reg(ChartType(
        "面",
        info={"use_x": True, "multi_y": True, "multi_file": True,
              "hint": "X軸に1列、Y軸に1列以上を塗り面で重ね描き。複数ファイル可"},
        draw=_draw_chart_xy, is_xy=True, default_kind="area", swap_ok=True))
    reg(ChartType(
        "積み上げ面",
        info={"use_x": True, "multi_y": True, "multi_file": True,
              "hint": "X軸に1列、Y軸に複数列を積み上げ（共通Xへ補間）。複数ファイル可"},
        draw=_draw_chart_stack, swap_ok=True))
    reg(ChartType(
        "ステップ",
        info={"use_x": True, "multi_y": True, "multi_file": True,
              "hint": "X軸に1列、Y軸に1列以上を階段状に。複数ファイル可"},
        draw=_draw_chart_xy, is_xy=True, default_kind="step", swap_ok=True))
    reg(ChartType(
        "ステム",
        info={"use_x": True, "multi_y": True, "multi_file": True,
              "hint": "X軸に1列、Y軸に1列以上を棒（幹）＋点で表示。複数ファイル可"},
        draw=_draw_chart_xy, is_xy=True, default_kind="stem", swap_ok=True))
    reg(ChartType(
        "棒",
        info={"use_x": True, "multi_y": True, "multi_file": False, "dim3": "optional",
              "hint": "X軸にカテゴリ列、Y軸に1列以上（単一ファイル）。『3D表示』で(X,Y)にZ高さの3D棒に"},
        draw=_draw_chart_bar))
    reg(ChartType(
        "横棒",
        info={"use_x": True, "multi_y": True, "multi_file": False,
              "hint": "X軸にカテゴリ列、Y軸に1列以上（単一ファイル）"},
        draw=partial(_draw_chart_bar, horizontal=True)))
    reg(ChartType(
        "積み上げ棒",
        info={"use_x": True, "multi_y": True, "multi_file": False,
              "hint": "X軸にカテゴリ列、Y軸に2列以上（単一ファイル）"},
        draw=partial(_draw_chart_bar, stacked=True)))
    reg(ChartType(
        "散布図",
        info={"use_x": True, "multi_y": True, "multi_file": True, "dim3": "optional",
              "hint": "X軸に1列、Y軸に1列以上。複数ファイル可（『3D表示』でZ軸を使う3D散布図に）"},
        draw=_draw_chart_xy, is_xy=True, default_kind="scatter",
        scope_ok=True, swap_ok=True))
    reg(ChartType(
        "ヒストグラム",
        info={"use_x": False, "multi_y": True, "multi_file": True,
              "hint": "Y軸に値の列を1列以上（分布を表示）。複数ファイル可"},
        draw=_draw_chart_hist, y_default_label="頻度"))
    reg(ChartType(
        "2Dヒストグラム",
        info={"use_x": True, "multi_y": False, "multi_file": False,
              "hint": "X軸・Y軸に数値列を1つずつ（2次元の頻度を色で表示）"},
        draw=_draw_chart_hist2d, swap_ok=True))
    reg(ChartType(
        "hexbin",
        info={"use_x": True, "multi_y": False, "multi_file": False,
              "hint": "X軸・Y軸に数値列を1つずつ（六角ビンで密度を表示）"},
        draw=_draw_chart_hexbin, swap_ok=True))
    reg(ChartType(
        "箱ひげ",
        info={"use_x": False, "multi_y": True, "multi_file": True,
              "hint": "Y軸に値の列を1列以上。複数ファイル可"},
        draw=_draw_chart_box))
    reg(ChartType(
        "バイオリン",
        info={"use_x": False, "multi_y": True, "multi_file": True,
              "hint": "Y軸に値の列を1列以上（分布の密度を表示）。複数ファイル可"},
        draw=_draw_chart_violin))
    reg(ChartType(
        "ヒートマップ",
        info={"use_x": False, "multi_y": True, "multi_file": True,
              "hint": "選んだ各Y列を1行として濃淡で表示。複数ファイル可"},
        draw=_draw_chart_heatmap))
    reg(ChartType(
        "円",
        info={"use_x": True, "multi_y": False, "multi_file": False,
              "hint": "X軸にラベル列、Y軸に値の列を1つ（単一ファイル）"},
        draw=_draw_chart_pie, is_pie=True))
    reg(ChartType(
        "ドーナツ",
        info={"use_x": True, "multi_y": False, "multi_file": False,
              "hint": "X軸にラベル列、Y軸に値の列を1つ（中央が空いた円）"},
        draw=partial(_draw_chart_pie, donut=True), is_pie=True))
    reg(ChartType(
        "曲面",
        info={"use_x": True, "multi_y": False, "multi_file": False, "dim3": "always",
              "hint": "X軸・Y軸・Z軸に1列ずつ（散らばった点から曲面を生成・常に3D。ドラッグで回転）"},
        draw=_draw_chart_surface))


_register_builtin_charts()


LINESTYLES = {"実線": "-", "破線": "--", "一点鎖線": "-.", "点線": ":", "なし": "None"}


MARKERS = {"なし": "", "丸": "o", "四角": "s", "三角": "^", "菱形": "D",
           "× ": "x", "＋": "+", "点": "."}


LEGEND_LOCS = ["best", "upper right", "upper left", "lower left",
               "lower right", "right", "center left", "center right",
               "lower center", "upper center", "center"]


TRENDLINES = ["なし", "線形", "多項式", "指数", "対数", "移動平均",
              "ガウシアン", "ローレンツ", "シグモイド"]


SERIES_KINDS = {"自動": "", "折れ線": "line", "棒": "bar", "面": "area",
                "散布図": "scatter"}


SERIES_AXES = {"主軸": "primary", "第2軸": "secondary"}


def plot_series(
    ax,
    series,
    chart_type,
    *,
    categories=None,
    bins=10,
    title="",
    xlabel="",
    ylabel="",
    grid=True,
    legend=True,
    legend_loc="best",
    xlim=None,
    ylim=None,
    xlog=False,
    ylog=False,
    pct=False,
    fonts=None,
    scope=None,
    markers=None,
    max_points=0,
    trendline=None,
    data_labels=False,
    secondary_label="",
    xscale=1.0,
    yscale=1.0,
    xunit="",
    yunit="",
    bg_color="",
    grid_width=None,
    frame_width=None,
    xinvert=False,
    yinvert=False,
    zlabel="",
    view_init=None,
    threed=False,
    swap_xy=False,
):
    """ax に系列群を描画する。

    series : list of dict
        折れ線/散布図: {label, x, y, style}
        ヒストグラム/箱ひげ: {label, y, style}
        棒/横棒/積み上げ棒: {label, y, style}（categories に X ラベル配列）
        円: {label, y, style}（categories にラベル、y[0] を使用）
    """
    spec = get_chart_type(chart_type)
    if spec is None:
        raise ValueError(f"未知のグラフ種別です: {chart_type}")
    if not series:
        raise ValueError("Y軸（値）の系列を選択してください。")
    fonts = fonts or {}

    # --- X↔Y 入れ替え（2Dの xy 種別のみ）---
    # データと、X/Y に紐づく設定（ラベル・単位・範囲・対数・倍率・向き反転）を丸ごと交換。
    # ＝ユーザーが「X」に設定した内容は、その列と一緒にY軸側へ移る（直感的な転置）。
    if swap_xy and spec.swap_ok:
        xlabel, ylabel = ylabel, xlabel
        xunit, yunit = yunit, xunit
        xlim, ylim = ylim, xlim
        xlog, ylog = ylog, xlog
        xscale, yscale = yscale, xscale
        xinvert, yinvert = yinvert, xinvert
        swapped = []
        for sr in series:
            if sr.get("x") is not None and sr.get("y") is not None:
                sr = dict(sr)
                sr["x"], sr["y"] = sr["y"], sr["x"]
                sr.pop("yerr", None)      # 入れ替え後は縦誤差の意味が変わるため落とす
            swapped.append(sr)
        series = swapped

    # --- 単位換算: 軸の数値を変換（数値=倍率／x を使った式も可。X=全系列、Y=主軸のみ）。
    #     系列dictは描画ごとに作り直されるが、念のためコピーしてから変換する。
    from mathchan import axis_scale

    def _needs(spec):
        return not (spec is None or spec == 1.0
                    or (isinstance(spec, str) and spec.strip() in ("", "1")))

    if _needs(xscale) or _needs(yscale):
        scaled = []
        for sr in series:
            sr = dict(sr)
            if _needs(xscale) and sr.get("x") is not None:
                sr["x"] = axis_scale(sr["x"], xscale)
            if _needs(yscale) and sr.get("axis") != "secondary" and sr.get("y") is not None:
                yb = np.asarray(sr["y"], dtype=float)
                sr["y"] = axis_scale(yb, yscale)
                if sr.get("yerr") is not None:
                    # 誤差も y と同じ変換にかける（変換後の y±誤差 の幅の半分）。
                    # 数値/累乗/式のいずれでも整合し、生スケールのまま残らない。
                    e = np.asarray(sr["yerr"], dtype=float)
                    hi = axis_scale(yb + e, yscale)
                    lo = axis_scale(yb - e, yscale)
                    sr["yerr"] = np.abs(hi - lo) / 2.0
            scaled.append(sr)
        series = scaled

    # 3Dで描くかは呼び出し側の明示フラグで決める（表示名では判断しない）。
    # 曲面など『常に3D』の種別はフラグが無くても3Dにする。
    is3d = bool(threed) or spec.always_3d

    ax.clear()
    _remove_twin(ax)               # 前回の第2軸を掃除
    _remove_aux_axes(ax)           # 前回のカラーバー等を掃除
    if not is3d:                   # 3D軸の set_aspect はスカラー不可なので触らない
        ax.set_aspect("auto")      # 円グラフの equal を持ち越さない
    ax.set_facecolor(bg_color or "white")   # 背景色（空=白）。オシロは下で上書き
    ax.tick_params(colors="black")  # オシロ表示の目盛り色を既定へ戻す

    # 種別固有の描画は登録表の spec.draw へ委譲する。
    # 3D（threed 指定・常に3D種別）は種別によらず _draw_3d へ回す（従来どおり）。
    ax2 = None
    if is3d:
        _draw_3d(ax, series, chart_type, fonts=fonts, data_labels=data_labels,
                 zlabel=zlabel)
    else:
        ctx = _DrawCtx(categories=categories, bins=bins, fonts=fonts,
                       data_labels=data_labels, trendline=trendline,
                       max_points=max_points, secondary_label=secondary_label,
                       zlabel=zlabel, pct=pct)
        ax2 = spec.draw(ax, series, ctx, spec)

    # --- タイトル・ラベル ---
    if title:
        ax.set_title(title, fontsize=fonts.get("title", 12))
    if not spec.is_pie:
        xl = (f"{xlabel} [{xunit}]".strip() if xunit else xlabel)
        yl_base = ylabel or spec.y_default_label
        yl = (f"{yl_base} [{yunit}]".strip() if yunit else yl_base)
        ax.set_xlabel(xl, fontsize=fonts.get("label", 10))
        ax.set_ylabel(yl, fontsize=fonts.get("label", 10))
        ax.tick_params(labelsize=fonts.get("tick", 9))
        if is3d and zlabel:        # 3D の奥行き軸ラベル
            ax.set_zlabel(zlabel, fontsize=fonts.get("label", 10))

    # --- 対数軸・軸範囲 ---
    # min/max は片側だけの指定でも反映する（例: min=0 のみ → 左端を0に詰め、
    # 自動の5%余白を消す。両方そろわないと無視する旧仕様が「0でも余白が残る」原因だった）。
    if not spec.is_pie:
        if xlog and not is3d:      # 3D軸は対数スケール非対応
            ax.set_xscale("log")
        if ylog and not is3d:
            ax.set_yscale("log")
        if xlim:
            if xlim[0] is not None:
                ax.set_xlim(left=xlim[0])
            if xlim[1] is not None:
                ax.set_xlim(right=xlim[1])
        if ylim:
            if ylim[0] is not None:
                ax.set_ylim(bottom=ylim[0])
            if ylim[1] is not None:
                ax.set_ylim(top=ylim[1])

    # --- オシロスコープ表示（折れ線/散布図のみ）---
    if scope and scope.get("enabled") and spec.scope_ok:
        _apply_scope(ax, scope, bg_color=bg_color)
        grid = True

    # --- 凡例・グリッド ---
    if legend and not spec.is_pie:
        handles, labels = ax.get_legend_handles_labels()
        if ax2 is not None:                       # 第2軸の系列も凡例に統合
            h2, l2 = ax2.get_legend_handles_labels()
            handles = handles + h2
            labels = labels + l2
        if handles:
            ax.legend(handles, labels, loc=legend_loc,
                      fontsize=(fonts.get("legend") or fonts.get("tick", 9)))
    if grid and not spec.is_pie:
        if is3d:
            ax.grid(True)          # 3D は linestyle/alpha を受け付けないので簡素に
        else:
            # grid_width=None は「既定の太さ」。matplotlib は linewidth=None を float(None) に
            # 渡してしまうため、指定があるときだけ linewidth を渡す。
            gkw = {} if grid_width is None else {"linewidth": grid_width}
            ax.grid(True, linestyle="--", alpha=0.4, **gkw)

    # 枠線（spine）の太さ。0 以下なら枠を消す。None なら既定のまま（3D軸に spine は無い）
    if frame_width is not None and not is3d:
        for sp in ax.spines.values():
            sp.set_linewidth(frame_width)
            sp.set_visible(frame_width > 0)
        if ax2 is not None:
            for sp in ax2.spines.values():
                sp.set_linewidth(frame_width)
                sp.set_visible(frame_width > 0)

    # --- マーカー（ピーク等の注記。3Dは2D座標の注記が合わないので出さない）---
    if markers and not is3d:
        for m in markers:
            ax.plot(m["x"], m["y"], m.get("symbol", "v"),
                    color=m.get("color", "red"), markersize=8)
            if m.get("text"):
                ax.annotate(m["text"], (m["x"], m["y"]),
                            textcoords="offset points", xytext=(0, 8),
                            ha="center", color=m.get("color", "red"),
                            fontsize=fonts.get("tick", 9))

    # --- 3D の視点角度（仰角・方位）---
    if is3d and view_init is not None:
        try:
            ax.view_init(elev=view_init[0], azim=view_init[1])
        except Exception:
            pass

    # --- 軸の向き反転（最後に適用。範囲指定・オシロ表示の後でも効く）---
    if not spec.is_pie and not is3d:
        if xinvert and not ax.xaxis_inverted():
            ax.invert_xaxis()
        if yinvert and not ax.yaxis_inverted():
            ax.invert_yaxis()
    return ax


def build_series_from_df(df, chart_type, x_col, y_cols):
    """単一 DataFrame から系列リストと categories を作る（後方互換・簡易用途）。"""
    y_cols = list(y_cols or [])
    categories = None
    series = []
    if chart_type in ("棒", "横棒", "積み上げ棒", "円"):
        categories = df[x_col].to_numpy()
        for c in y_cols:
            series.append({"label": c, "y": df[c].to_numpy()})
    elif chart_type in ("折れ線", "散布図"):
        xv = df[x_col].to_numpy()
        for c in y_cols:
            series.append({"label": c, "x": xv, "y": df[c].to_numpy()})
    else:  # ヒストグラム / 箱ひげ
        for c in y_cols:
            series.append({"label": c, "y": df[c].to_numpy()})
    return series, categories


def plot(ax, df, chart_type, x_col=None, y_cols=None, *, bins=10, title="",
         xlabel="", ylabel="", grid=True, legend=True, pct=False):
    """単一 DataFrame 版の簡易インターフェース（テスト・後方互換用）。"""
    info = CHART_INFO.get(chart_type)
    if info is None:
        raise ValueError(f"未知のグラフ種別です: {chart_type}")
    if info["use_x"] and not x_col:
        raise ValueError("X軸の列を選択してください。")
    if not y_cols:
        raise ValueError("Y軸（値）の列を選択してください。")
    series, categories = build_series_from_df(df, chart_type, x_col, y_cols)
    return plot_series(ax, series, chart_type, categories=categories, bins=bins,
                       title=title, xlabel=xlabel or (x_col or ""), ylabel=ylabel,
                       grid=grid, legend=legend, pct=pct)
