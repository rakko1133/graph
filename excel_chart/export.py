# -*- coding: utf-8 -*-
"""高水準 API: データ読込 → ChartSpec → エンジン選択 → Excel グラフ出力。

データ読み込みは既存システムの data_loader をそのまま流用する（CSV/TSV/Excel・
文字コード/区切り自動判定）。data_loader が import できない環境（パッケージを
単体配布した場合）では pandas で素朴に読む簡易フォールバックを使う。
"""
import os
import sys

import pandas as pd

from .spec import ChartSpec
from . import com_engine, openpyxl_engine


def _ensure_repo_on_path():
    """data_loader / plotter_format を import できるよう、リポジトリ直下を sys.path へ。"""
    here = os.path.dirname(os.path.abspath(__file__))
    repo = os.path.dirname(here)
    if repo not in sys.path:
        sys.path.insert(0, repo)


def load_table(path):
    """既存 data_loader.load_table を流用。無ければ pandas の簡易読み込み。"""
    _ensure_repo_on_path()
    try:
        import data_loader
        df, _enc, _delim = data_loader.load_table(path)
        return df
    except Exception:
        ext = os.path.splitext(path)[1].lower()
        if ext in (".xlsx", ".xlsm", ".xls"):
            return pd.read_excel(path)
        # CSV/TSV: 文字コードを順に試す
        for enc in ("utf-8-sig", "cp932", "utf-8", "latin-1"):
            try:
                sep = "\t" if ext == ".tsv" else None
                return pd.read_csv(path, sep=sep, engine="python", encoding=enc)
            except Exception:
                continue
        raise


def choose_engine(engine, out_path):
    """'auto'|'com'|'openpyxl' から実際に使うエンジン名を決める。

    auto: Excel(COM) が使えれば com、無理なら openpyxl。
    .xlsm 出力やマクロ実行は COM のみ。
    """
    if engine in ("com", "openpyxl"):
        return engine
    # auto
    if os.path.splitext(out_path)[1].lower() == ".xlsm":
        return "com"
    if com_engine.available() and _excel_installed():
        return "com"
    return "openpyxl"


def _excel_installed():
    """Excel が COM 起動できそうか軽く判定（Windows のレジストリ CLSID 確認）。"""
    if os.name != "nt":
        return False
    try:
        import winreg
        winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "Excel.Application")
        return True
    except Exception:
        return False


def export_excel_chart(data, spec=None, out_path="chart.xlsx", *,
                       engine="auto", visible=False,
                       x=None, y=None, chart_type="折れ線", **spec_kwargs):
    """データと書式から Excel グラフを書き出す中心関数。

    data : DataFrame / CSV・TSV・Excel のパス
    spec : ChartSpec。None のとき x/y/chart_type/**spec_kwargs から組み立てる
    out_path : 出力 .xlsx（または .xlsm）
    engine : 'auto'（既定）/'com'（VBA互換・要Excel）/'openpyxl'（Excel不要）
    visible: COM 実行時に Excel を可視化（デバッグ用）
    戻り値: (保存パス, 使用エンジン名)
    """
    df = data if isinstance(data, pd.DataFrame) else load_table(data)

    if spec is None:
        ys = y if isinstance(y, (list, tuple)) else ([y] if y else [])
        if not ys:
            raise ValueError("y（値の列）を 1 つ以上指定してください。")
        spec = ChartSpec.from_columns(x, list(ys), chart_type=chart_type, **spec_kwargs)

    _validate(spec, df)

    eng = choose_engine(engine, out_path)
    if eng == "com":
        path = com_engine.write(spec, df, out_path, visible=visible)
    else:
        path = openpyxl_engine.write(spec, df, out_path)
    return path, eng


def export_from_config(data, config, out_path="chart.xlsx", *,
                       engine="auto", only_file=None, visible=False):
    """既存 GUI の設定 JSON（_collect_config 形式 / プリセット）を書式に使う。"""
    spec = ChartSpec.from_app_config(config, only_file=only_file)
    return export_excel_chart(data, spec=spec, out_path=out_path,
                              engine=engine, visible=visible)


def _validate(spec, df):
    """列の存在と種別を検証して分かりやすいエラーにする。"""
    if spec.chart_type == "箱ひげ":
        raise ValueError(
            "箱ひげ図はネイティブ Excel グラフでは未対応です（COM/openpyxl とも）。"
            "箱ひげは既存 GUI（matplotlib）で画像出力してください。")
    if not spec.series:
        raise ValueError("系列（値の列）が空です。")
    missing = [s.y_col for s in spec.series if s.y_col not in df.columns]
    if missing:
        raise ValueError(f"指定の値列がデータにありません: {missing} / "
                         f"利用可能な列: {list(df.columns)}")
    if spec.x_col and spec.x_col not in df.columns:
        raise ValueError(f"X 列 '{spec.x_col}' がデータにありません: "
                         f"{list(df.columns)}")
