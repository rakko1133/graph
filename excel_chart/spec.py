# -*- coding: utf-8 -*-
"""グラフ書式の中立表現 ChartSpec と、その組み立て。

GUI（PySide6）にも matplotlib にも Excel エンジンにも依存しない純粋なデータ構造。
ここを境界にして「どんな書式か」を 1 つの dict/データクラスへ正規化し、
COM / openpyxl いずれのエンジンも同じ ChartSpec を解釈して描く。

書式の供給元は 2 通り:
  * from_columns(...)  : CLI / コードから列と種別を直接指定
  * from_app_config(cfg): 既存 GUI が保存した設定 JSON（_collect_config 形式）を流用
"""
from dataclasses import dataclass, field
from typing import List, Optional


# 既存アプリの既定スタイル（plotter.DEFAULT_STYLE）と同値。アプリ非導入でも動くよう自前で持つ。
DEFAULT_STYLE = {
    "color": None, "linestyle": "-", "linewidth": 1.5,
    "marker": "", "markersize": 4.0, "alpha": 1.0,
}

# 既存アプリの日本語ラベル -> matplotlib 値（plotter.LINESTYLES / MARKERS と同じ）。
LINESTYLES = {"実線": "-", "破線": "--", "一点鎖線": "-.", "点線": ":", "なし": "None"}
MARKERS = {"なし": "", "丸": "o", "四角": "s", "三角": "^", "菱形": "D",
           "×": "x", "× ": "x", "＋": "+", "点": "."}

CHART_TYPES = ["折れ線", "棒", "横棒", "積み上げ棒", "散布図", "円", "ヒストグラム"]


@dataclass
class SeriesSpec:
    """1 系列ぶんの書式。値（y_col）は DataFrame の列名で参照する。"""
    name: str                      # 凡例に出す系列名
    y_col: str                     # 値の列名
    color: Optional[str] = None    # "#RRGGBB" or None(自動)
    linestyle: str = "-"           # matplotlib 線種（"-","--","-.",":","None"）
    linewidth: float = 1.5
    marker: str = ""               # matplotlib マーカー（"","o","s","^","D","x","+","."）
    markersize: float = 4.0
    axis: str = "primary"          # "primary" | "secondary"
    kind: str = ""                 # "" | "line" | "bar" | "area" | "scatter"（複合グラフ用）
    errcol: Optional[str] = None   # エラーバーに使う列名（任意）


@dataclass
class ChartSpec:
    """グラフ 1 枚ぶんの完全な書式。"""
    chart_type: str = "折れ線"
    x_col: Optional[str] = None
    series: List[SeriesSpec] = field(default_factory=list)
    title: str = ""
    xlabel: str = ""
    ylabel: str = ""
    secondary_label: str = ""
    legend: bool = True
    legend_loc: str = "best"
    grid: bool = True
    xmin: Optional[float] = None
    xmax: Optional[float] = None
    ymin: Optional[float] = None
    ymax: Optional[float] = None
    xlog: bool = False
    ylog: bool = False
    xinvert: bool = False
    yinvert: bool = False
    data_labels: bool = False
    pct: bool = False               # 円グラフでパーセント表示
    bins: int = 10                  # ヒストグラムのビン数
    # チャートオブジェクトのサイズ（ポイント）
    width: float = 480.0
    height: float = 300.0

    # ---------------------------------------------------------------- 構築
    @classmethod
    def from_columns(cls, x_col, y_cols, chart_type="折れ線", *,
                     styles=None, names=None, **kwargs):
        """列名から最小限の指定で組み立てる（CLI / コード用）。

        styles: {y_col: style_dict} で系列ごとの見た目を上書き可能。
        names : {y_col: 表示名}。
        kwargs: ChartSpec の他フィールド（title, ylabel, ymin ... ）。
        """
        styles = styles or {}
        names = names or {}
        series = []
        for col in y_cols:
            st = dict(DEFAULT_STYLE)
            st.update(styles.get(col) or {})
            series.append(SeriesSpec(
                name=names.get(col, col), y_col=col,
                color=st.get("color"), linestyle=st.get("linestyle", "-"),
                linewidth=float(st.get("linewidth", 1.5)),
                marker=st.get("marker", ""),
                markersize=float(st.get("markersize", 4.0)),
                axis=st.get("axis", "primary"), kind=st.get("kind", ""),
                errcol=st.get("errcol"),
            ))
        return cls(chart_type=chart_type, x_col=x_col, series=series, **kwargs)

    @classmethod
    def from_app_config(cls, cfg, *, only_file=None):
        """既存 GUI の設定 JSON（_collect_config 形式 / プリセット）から組み立てる。

        単一データファイルでの利用を想定。複数ファイルのときは only_file に
        対象ファイル名（meta のキー）を渡すとその系列だけ採用する。
        """
        styles = cfg.get("styles", {}) or {}
        # selected_y: [[file, col], ...] ／ 無ければ styles のキーから推定
        sel = cfg.get("selected_y") or []
        if not sel:
            sel = [k.split("\t", 1) for k in styles.keys() if "\t" in k]

        series = []
        for pair in sel:
            if not (isinstance(pair, (list, tuple)) and len(pair) == 2):
                continue
            fl, col = pair[0], pair[1]
            if only_file is not None and fl != only_file:
                continue
            st = dict(DEFAULT_STYLE)
            st.update(styles.get(f"{fl}\t{col}") or {})
            series.append(SeriesSpec(
                name=st.get("label") or col, y_col=col,
                color=st.get("color"), linestyle=st.get("linestyle", "-"),
                linewidth=float(st.get("linewidth", 1.5)),
                marker=st.get("marker", ""),
                markersize=float(st.get("markersize", 4.0)),
                axis=st.get("axis", "primary"), kind=st.get("kind", ""),
                errcol=st.get("errcol"),
            ))

        return cls(
            chart_type=cfg.get("chart_type", "折れ線"),
            x_col=(None if cfg.get("x_leftmost") else (cfg.get("x_col") or None)),
            series=series,
            title=cfg.get("title", ""),
            xlabel=cfg.get("xlabel", ""), ylabel=cfg.get("ylabel", ""),
            secondary_label=cfg.get("secondary_label", ""),
            legend=bool(cfg.get("legend", True)),
            legend_loc=cfg.get("legend_loc", "best"),
            grid=bool(cfg.get("grid", True)),
            xmin=_num(cfg.get("xmin")), xmax=_num(cfg.get("xmax")),
            ymin=_num(cfg.get("ymin")), ymax=_num(cfg.get("ymax")),
            xlog=bool(cfg.get("xlog", False)), ylog=bool(cfg.get("ylog", False)),
            xinvert=bool(cfg.get("xinvert", False)),
            yinvert=bool(cfg.get("yinvert", False)),
            data_labels=bool(cfg.get("data_labels", False)),
            pct=bool(cfg.get("pct", False)),
            bins=int(cfg.get("bins", 10) or 10),
        )

    # ---------------------------------------------------------------- 補助
    def used_columns(self):
        """このスペックが参照する列名の集合（X・値・誤差）。データ抽出に使う。"""
        cols = set()
        if self.x_col:
            cols.add(self.x_col)
        for s in self.series:
            cols.add(s.y_col)
            if s.errcol:
                cols.add(s.errcol)
        return cols


def _num(text):
    """設定 JSON 中の数値テキスト（'1' '1ms' '' None）を float へ。空/不正は None。

    工学接頭辞（1ms 等）は既存アプリの parse_eng があれば使い、無ければ float。
    """
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return float(text)
    s = str(text).strip()
    if not s:
        return None
    try:
        from plotter_format import parse_eng
        v = parse_eng(s, default=None)
        return None if v is None else float(v)
    except Exception:
        try:
            return float(s)
        except ValueError:
            return None
