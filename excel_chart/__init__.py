# -*- coding: utf-8 -*-
"""excel_chart: Python だけで「特定列＋特定書式」のネイティブ Excel グラフを作る。

2 つのエンジンが同じ ChartSpec を解釈する:
  * com_engine     … pywin32 で実 Excel を COM 操作（VBA 完全互換・要 Excel/Windows）
  * openpyxl_engine… OOXML を直接生成（Excel 不要・クロスプラットフォーム）

代表的な使い方:
    from excel_chart import export_excel_chart
    export_excel_chart("data.csv", x="t", y=["v1", "v2"],
                       chart_type="折れ線", out_path="out.xlsx")

既存システムからの流用: データ読み込みは data_loader、書式は GUI の設定 JSON
（ChartSpec.from_app_config / export_from_config）をそのまま使える。
"""
from .spec import ChartSpec, SeriesSpec
from .export import export_excel_chart, export_from_config, load_table

__all__ = [
    "ChartSpec", "SeriesSpec",
    "export_excel_chart", "export_from_config", "load_table",
]

__version__ = "0.1.0"
