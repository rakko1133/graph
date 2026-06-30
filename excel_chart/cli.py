# -*- coding: utf-8 -*-
"""コマンドラインインターフェース。

例:
  # 折れ線（X=時刻, Y=気温・電力）を VBA互換のネイティブ Excel グラフで出力
  python -m excel_chart サンプルデータ/Excel編集デモ.csv ^
      --x "時刻[h]" --y "気温[℃]" "電力[kW]" --type 折れ線 ^
      --title 気温と電力 --out 出力.xlsx

  # GUI で作った設定 JSON の書式をそのまま流用
  python -m excel_chart data.csv --config graph_config.json --out 出力.xlsx

  # Excel 無し環境（CI 等）でフォールバック
  python -m excel_chart data.csv --x t --y v --engine openpyxl --out out.xlsx
"""
import argparse
import json
import sys

from .export import export_excel_chart, export_from_config
from .spec import ChartSpec


def build_parser():
    p = argparse.ArgumentParser(
        prog="excel_chart",
        description="特定列＋特定書式から、Pythonだけでネイティブ Excel グラフを生成する"
                    "（COM=VBA互換 / openpyxl=Excel不要）。")
    p.add_argument("data", help="CSV / TSV / Excel ファイルのパス")
    p.add_argument("--out", "-o", default="chart.xlsx",
                   help="出力ファイル（.xlsx / .xlsm）。既定 chart.xlsx")
    p.add_argument("--engine", choices=["auto", "com", "openpyxl"], default="auto",
                   help="auto(既定)/com(VBA互換・要Excel)/openpyxl(Excel不要)")
    p.add_argument("--config", help="GUI の設定 JSON（_collect_config 形式/プリセット）")
    p.add_argument("--only-file", help="設定が複数ファイル由来のとき対象ファイル名")

    p.add_argument("--x", help="X 軸の列名（省略可）")
    p.add_argument("--y", nargs="+", help="値（Y）の列名（1 つ以上）")
    p.add_argument("--type", "-t", default="折れ線",
                   help="グラフ種別: 折れ線/棒/横棒/積み上げ棒/散布図/円/ヒストグラム")
    p.add_argument("--title", default="")
    p.add_argument("--xlabel", default="")
    p.add_argument("--ylabel", default="")
    p.add_argument("--secondary-label", default="")
    p.add_argument("--colors", nargs="*", help="系列の色 #RRGGBB を Y と同順で")
    p.add_argument("--secondary", nargs="*", help="第2軸にする Y 列名")
    p.add_argument("--no-legend", action="store_true")
    p.add_argument("--no-grid", action="store_true")
    p.add_argument("--legend-loc", default="best")
    p.add_argument("--xmin", type=float); p.add_argument("--xmax", type=float)
    p.add_argument("--ymin", type=float); p.add_argument("--ymax", type=float)
    p.add_argument("--xlog", action="store_true"); p.add_argument("--ylog", action="store_true")
    p.add_argument("--xinvert", action="store_true"); p.add_argument("--yinvert", action="store_true")
    p.add_argument("--data-labels", action="store_true")
    p.add_argument("--bins", type=int, default=10, help="ヒストグラムのビン数")
    p.add_argument("--visible", action="store_true", help="COM 実行時に Excel を表示")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)

    if args.config:
        with open(args.config, encoding="utf-8") as f:
            cfg = json.load(f)
        path, eng = export_from_config(
            args.data, cfg, out_path=args.out, engine=args.engine,
            only_file=args.only_file, visible=args.visible)
        print(f"出力しました: {path}  (エンジン: {eng})")
        return 0

    if not args.y:
        print("エラー: --y で値の列を 1 つ以上指定するか、--config を使ってください。",
              file=sys.stderr)
        return 2

    # 色・第2軸を系列スタイルへ反映
    styles = {}
    if args.colors:
        for col, c in zip(args.y, args.colors):
            styles.setdefault(col, {})["color"] = c
    for col in (args.secondary or []):
        styles.setdefault(col, {})["axis"] = "secondary"

    spec = ChartSpec.from_columns(
        args.x, args.y, chart_type=args.type, styles=styles,
        title=args.title, xlabel=args.xlabel, ylabel=args.ylabel,
        secondary_label=args.secondary_label,
        legend=not args.no_legend, grid=not args.no_grid,
        legend_loc=args.legend_loc,
        xmin=args.xmin, xmax=args.xmax, ymin=args.ymin, ymax=args.ymax,
        xlog=args.xlog, ylog=args.ylog, xinvert=args.xinvert, yinvert=args.yinvert,
        data_labels=args.data_labels, bins=args.bins)

    path, eng = export_excel_chart(
        args.data, spec=spec, out_path=args.out, engine=args.engine,
        visible=args.visible)
    print(f"出力しました: {path}  (エンジン: {eng})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
