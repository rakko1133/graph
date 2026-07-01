"""グラフ描画ロジック（系列ベース）。

複数ファイル由来の系列をまとめて描画でき、系列ごとに色・線種・線幅・マーカーを
指定できる。軸範囲・対数軸・凡例位置などの編集にも対応。さらにオシロスコープ風の
div グリッド表示（time/div・V/div・位置オフセット）をサポートする。

GUI から独立しているので単体でも利用・テストできる。
"""


import warnings  # noqa: F401

import numpy as np
import pandas as pd  # noqa: F401

from plotter_format import *   # noqa: F401,F403
from plotter_draw import *     # noqa: F401,F403
# plot_series が直接呼ぶ低レベル描画（アンダースコア）を取り込む
from plotter_draw import (_draw_xy, _draw_hist, _draw_box, _draw_bar, _draw_pie,
                          _draw_area, _draw_stack, _draw_violin, _draw_hist2d,
                          _draw_hexbin, _draw_heatmap,
                          _remove_twin, _remove_aux_axes, _apply_scope, _data_labels)


CHART_TYPES = [
    "折れ線",
    "面",
    "積み上げ面",
    "ステップ",
    "ステム",
    "棒",
    "横棒",
    "積み上げ棒",
    "散布図",
    "ヒストグラム",
    "2Dヒストグラム",
    "hexbin",
    "箱ひげ",
    "バイオリン",
    "ヒートマップ",
    "円",
    "ドーナツ",
]


CHART_INFO = {
    "折れ線": {"use_x": True, "multi_y": True, "multi_file": True,
              "hint": "X軸に1列、Y軸に1列以上。複数ファイルの重ね描き可"},
    "面": {"use_x": True, "multi_y": True, "multi_file": True,
          "hint": "X軸に1列、Y軸に1列以上を塗り面で重ね描き。複数ファイル可"},
    "積み上げ面": {"use_x": True, "multi_y": True, "multi_file": True,
                "hint": "X軸に1列、Y軸に複数列を積み上げ（共通Xへ補間）。複数ファイル可"},
    "ステップ": {"use_x": True, "multi_y": True, "multi_file": True,
              "hint": "X軸に1列、Y軸に1列以上を階段状に。複数ファイル可"},
    "ステム": {"use_x": True, "multi_y": True, "multi_file": True,
            "hint": "X軸に1列、Y軸に1列以上を棒（幹）＋点で表示。複数ファイル可"},
    "棒": {"use_x": True, "multi_y": True, "multi_file": False,
          "hint": "X軸にカテゴリ列、Y軸に1列以上（単一ファイル）"},
    "横棒": {"use_x": True, "multi_y": True, "multi_file": False,
            "hint": "X軸にカテゴリ列、Y軸に1列以上（単一ファイル）"},
    "積み上げ棒": {"use_x": True, "multi_y": True, "multi_file": False,
                "hint": "X軸にカテゴリ列、Y軸に2列以上（単一ファイル）"},
    "散布図": {"use_x": True, "multi_y": True, "multi_file": True,
            "hint": "X軸に1列、Y軸に1列以上。複数ファイル可"},
    "ヒストグラム": {"use_x": False, "multi_y": True, "multi_file": True,
                "hint": "Y軸に値の列を1列以上（分布を表示）。複数ファイル可"},
    "2Dヒストグラム": {"use_x": True, "multi_y": False, "multi_file": False,
                  "hint": "X軸・Y軸に数値列を1つずつ（2次元の頻度を色で表示）"},
    "hexbin": {"use_x": True, "multi_y": False, "multi_file": False,
               "hint": "X軸・Y軸に数値列を1つずつ（六角ビンで密度を表示）"},
    "箱ひげ": {"use_x": False, "multi_y": True, "multi_file": True,
            "hint": "Y軸に値の列を1列以上。複数ファイル可"},
    "バイオリン": {"use_x": False, "multi_y": True, "multi_file": True,
              "hint": "Y軸に値の列を1列以上（分布の密度を表示）。複数ファイル可"},
    "ヒートマップ": {"use_x": False, "multi_y": True, "multi_file": True,
                "hint": "選んだ各Y列を1行として濃淡で表示。複数ファイル可"},
    "円": {"use_x": True, "multi_y": False, "multi_file": False,
          "hint": "X軸にラベル列、Y軸に値の列を1つ（単一ファイル）"},
    "ドーナツ": {"use_x": True, "multi_y": False, "multi_file": False,
              "hint": "X軸にラベル列、Y軸に値の列を1つ（中央が空いた円）"},
}


# 円系（軸ラベル・凡例・グリッド・軸範囲を持たない）
_PIE_TYPES = ("円", "ドーナツ")
# XY 折れ線系（第2軸・近似曲線に対応、_draw_xy を通す）
_XY_TYPES = ("折れ線", "散布図", "面", "ステップ", "ステム")
# XY 種別ごとの既定系列 kind（per-series 指定があればそちらを優先）
_XY_DEFAULT_KIND = {"折れ線": "line", "散布図": "scatter", "面": "area",
                    "ステップ": "step", "ステム": "stem"}
# オシロ格子・カーソルを許可する種別
_SCOPE_TYPES = ("折れ線", "散布図")


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
):
    """ax に系列群を描画する。

    series : list of dict
        折れ線/散布図: {label, x, y, style}
        ヒストグラム/箱ひげ: {label, y, style}
        棒/横棒/積み上げ棒: {label, y, style}（categories に X ラベル配列）
        円: {label, y, style}（categories にラベル、y[0] を使用）
    """
    info = CHART_INFO.get(chart_type)
    if info is None:
        raise ValueError(f"未知のグラフ種別です: {chart_type}")
    if not series:
        raise ValueError("Y軸（値）の系列を選択してください。")
    fonts = fonts or {}

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

    ax.clear()
    _remove_twin(ax)               # 前回の第2軸を掃除
    _remove_aux_axes(ax)           # 前回のカラーバー等を掃除
    ax.set_aspect("auto")          # 円グラフの equal を持ち越さない
    ax.set_facecolor(bg_color or "white")   # 背景色（空=白）。オシロは下で上書き
    ax.tick_params(colors="black")  # オシロ表示の目盛り色を既定へ戻す

    ax2 = None
    if chart_type in _XY_TYPES:
        if chart_type != "積み上げ面" and any((sr.get("axis") == "secondary") for sr in series):
            ax2 = ax.twinx()
            ax._twin_secondary = ax2
            if secondary_label:
                ax2.set_ylabel(secondary_label, fontsize=(fonts or {}).get("label", 10))
        _draw_xy(ax, series, line=(chart_type == "折れ線"),
                 max_points=max_points, ax2=ax2, data_labels=data_labels,
                 trendline=trendline, fonts=fonts,
                 default_skind=_XY_DEFAULT_KIND.get(chart_type))
    elif chart_type == "積み上げ面":
        _draw_stack(ax, series)
    elif chart_type == "ヒストグラム":
        _draw_hist(ax, series, bins)
    elif chart_type == "2Dヒストグラム":
        _draw_hist2d(ax, series, bins)
    elif chart_type == "hexbin":
        _draw_hexbin(ax, series, bins)
    elif chart_type == "箱ひげ":
        _draw_box(ax, series)
    elif chart_type == "バイオリン":
        _draw_violin(ax, series)
    elif chart_type == "ヒートマップ":
        _draw_heatmap(ax, series)
    elif chart_type in ("棒", "横棒", "積み上げ棒"):
        if categories is None:
            raise ValueError("X軸（カテゴリ）の列を選択してください。")
        _draw_bar(ax, series, categories,
                  horizontal=(chart_type == "横棒"),
                  stacked=(chart_type == "積み上げ棒"),
                  data_labels=data_labels, fonts=fonts)
    elif chart_type in _PIE_TYPES:
        if categories is None:
            raise ValueError("X軸（ラベル）の列を選択してください。")
        _draw_pie(ax, series[0], categories, pct=pct,
                  donut=(chart_type == "ドーナツ"))

    # --- タイトル・ラベル ---
    if title:
        ax.set_title(title, fontsize=fonts.get("title", 12))
    if chart_type not in _PIE_TYPES:
        xl = (f"{xlabel} [{xunit}]".strip() if xunit else xlabel)
        yl_base = ylabel or ("頻度" if chart_type == "ヒストグラム" else "")
        yl = (f"{yl_base} [{yunit}]".strip() if yunit else yl_base)
        ax.set_xlabel(xl, fontsize=fonts.get("label", 10))
        ax.set_ylabel(yl, fontsize=fonts.get("label", 10))
        ax.tick_params(labelsize=fonts.get("tick", 9))

    # --- 対数軸・軸範囲 ---
    # min/max は片側だけの指定でも反映する（例: min=0 のみ → 左端を0に詰め、
    # 自動の5%余白を消す。両方そろわないと無視する旧仕様が「0でも余白が残る」原因だった）。
    if chart_type not in _PIE_TYPES:
        if xlog:
            ax.set_xscale("log")
        if ylog:
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
    if scope and scope.get("enabled") and chart_type in _SCOPE_TYPES:
        _apply_scope(ax, scope, bg_color=bg_color)
        grid = True

    # --- 凡例・グリッド ---
    if legend and chart_type not in _PIE_TYPES:
        handles, labels = ax.get_legend_handles_labels()
        if ax2 is not None:                       # 第2軸の系列も凡例に統合
            h2, l2 = ax2.get_legend_handles_labels()
            handles = handles + h2
            labels = labels + l2
        if handles:
            ax.legend(handles, labels, loc=legend_loc,
                      fontsize=(fonts.get("legend") or fonts.get("tick", 9)))
    if grid and chart_type not in _PIE_TYPES:
        # grid_width=None は「既定の太さ」。matplotlib は linewidth=None を float(None) に
        # 渡してしまうため、指定があるときだけ linewidth を渡す。
        gkw = {} if grid_width is None else {"linewidth": grid_width}
        ax.grid(True, linestyle="--", alpha=0.4, **gkw)

    # 枠線（spine）の太さ。0 以下なら枠を消す。None なら既定のまま
    if frame_width is not None:
        for sp in ax.spines.values():
            sp.set_linewidth(frame_width)
            sp.set_visible(frame_width > 0)
        if ax2 is not None:
            for sp in ax2.spines.values():
                sp.set_linewidth(frame_width)
                sp.set_visible(frame_width > 0)

    # --- マーカー（ピーク等の注記）---
    if markers:
        for m in markers:
            ax.plot(m["x"], m["y"], m.get("symbol", "v"),
                    color=m.get("color", "red"), markersize=8)
            if m.get("text"):
                ax.annotate(m["text"], (m["x"], m["y"]),
                            textcoords="offset points", xytext=(0, 8),
                            ha="center", color=m.get("color", "red"),
                            fontsize=fonts.get("tick", 9))

    # --- 軸の向き反転（最後に適用。範囲指定・オシロ表示の後でも効く）---
    if chart_type not in _PIE_TYPES:
        if xinvert and not ax.xaxis_inverted():
            ax.invert_xaxis()
        if yinvert and not ax.yaxis_inverted():
            ax.invert_yaxis()
    return ax


def build_series_from_df(df, chart_type, x_col, y_cols):
    """単一 DataFrame から系列リストと categories を作る（後方互換・簡易用途）。"""
    info = CHART_INFO[chart_type]
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
