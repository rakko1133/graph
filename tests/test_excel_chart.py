# -*- coding: utf-8 -*-
"""excel_chart パッケージのテスト（Excel 不要・openpyxl エンジンのみ）。

COM エンジンは実 Excel が要るので CI(Linux) では回さない。ここでは Excel 無しで
動く openpyxl エンジンの正しさと、対応表・スペック組み立て・検証を確認する。

    python -m pytest tests/test_excel_chart.py -v
    python tests/test_excel_chart.py
"""
import os
import sys
import tempfile
import zipfile

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from excel_chart import export_excel_chart, export_from_config, ChartSpec  # noqa: E402
from excel_chart import mapping as M  # noqa: E402


def _df():
    return pd.DataFrame({
        "時刻": list(range(10)),
        "気温": [18 + i for i in range(10)],
        "電力": [100 + 5 * i for i in range(10)],
        "誤差": [1.0] * 10,
        "区分": list("AABBCCDDEE"),
    })


def _chart_xml(path):
    with zipfile.ZipFile(path) as z:
        parts = [n for n in z.namelist() if n.startswith("xl/charts/chart")
                 and n.endswith(".xml")]
        assert parts, f"チャート部品が無い: {path}"
        return z.read(parts[0]).decode("utf-8", "replace")


# ---------------------------------------------------------------- 対応表
def test_color_bgr_byte_order():
    # Excel COM の .RGB は BGR 整数。赤 #FF0000 -> 0x0000FF、青 #0000FF -> 0xFF0000。
    assert M.hex_to_bgr("#FF0000") == 0x0000FF
    assert M.hex_to_bgr("#0000FF") == 0xFF0000
    assert M.hex_to_bgr("#1f77b4") == (0x1F | (0x77 << 8) | (0xB4 << 16))
    assert M.hex_to_bgr(None) is None
    # openpyxl は RRGGBB（# なし大文字）
    assert M.hex_to_rrggbb("#1f77b4") == "1F77B4"
    assert M.hex_to_rrggbb(None) is None


def test_dash_marker_legend_maps():
    assert M.excel_dash("-") == 1 and M.excel_dash("--") == 4
    assert M.excel_dash("None") is None and M.excel_dash("") is None
    assert M.openpyxl_dash(":") == "sysDot"
    assert M.excel_marker("o") == 8 and M.excel_marker("D") == 2
    assert M.openpyxl_marker("^") == "triangle"
    assert M.excel_legend_position("lower right") == -4107   # bottom
    assert M.openpyxl_legend_position("upper left") == "t"


# ---------------------------------------------------------------- スペック
def test_spec_from_columns():
    spec = ChartSpec.from_columns(
        "時刻", ["気温", "電力"], chart_type="折れ線",
        styles={"電力": {"axis": "secondary", "color": "#1f77b4"}})
    assert spec.x_col == "時刻" and len(spec.series) == 2
    assert spec.series[1].axis == "secondary"
    assert spec.used_columns() == {"時刻", "気温", "電力"}


def test_spec_from_app_config():
    cfg = {
        "chart_type": "折れ線", "x_col": "時刻", "x_leftmost": False,
        "selected_y": [["t.csv", "気温"], ["t.csv", "電力"]],
        "title": "T", "ymin": "0", "ymax": "30",
        "styles": {
            "t.csv\t気温": {"color": "#d62728", "marker": "o"},
            "t.csv\t電力": {"axis": "secondary", "linestyle": "--"},
        },
    }
    spec = ChartSpec.from_app_config(cfg)
    assert spec.title == "T" and spec.ymin == 0.0 and spec.ymax == 30.0
    assert [s.y_col for s in spec.series] == ["気温", "電力"]
    assert spec.series[0].color == "#d62728"
    assert spec.series[1].axis == "secondary"


# ---------------------------------------------------------------- 出力（openpyxl）
def test_export_line_secondary_axis(tmp_path=None):
    out = _out(tmp_path, "line.xlsx")
    spec = ChartSpec.from_columns(
        "時刻", ["気温", "電力"], chart_type="折れ線",
        styles={"気温": {"color": "#d62728", "marker": "o", "linestyle": "-"},
                "電力": {"color": "#1f77b4", "axis": "secondary", "linestyle": "--"}},
        title="気温と電力", xlabel="時刻", ylabel="気温", secondary_label="電力")
    path, eng = export_excel_chart(_df(), spec=spec, out_path=out, engine="openpyxl")
    assert eng == "openpyxl" and os.path.exists(path)
    xml = _chart_xml(path)
    assert "scatterChart" in xml                      # 数値Xは散布図系
    assert xml.count("<ser>") == 2                    # 2 系列
    assert 'srgbClr val="D62728"' in xml              # 色が反映
    assert "prstDash" in xml                          # 線種が反映
    assert xml.count("valAx") >= 6                    # 第2軸ぶんの値軸が増える
    assert "気温と電力" in xml                          # タイトル


def test_export_bar(tmp_path=None):
    out = _out(tmp_path, "bar.xlsx")
    path, eng = export_excel_chart(
        _df(), x="区分", y=["気温"], chart_type="棒", out_path=out,
        engine="openpyxl", styles={"気温": {"color": "#2ca02c"}},
        data_labels=True, title="棒")
    xml = _chart_xml(path)
    assert "barChart" in xml and 'srgbClr val="2CA02C"' in xml


def test_export_scatter_and_pie_and_hist(tmp_path=None):
    df = _df()
    for ct, marker_check in [("散布図", "marker"), ("円", "pieChart"),
                             ("ヒストグラム", "barChart")]:
        out = _out(tmp_path, f"{ct}.xlsx")
        path, eng = export_excel_chart(
            df, x="時刻", y=["気温"], chart_type=ct, out_path=out, engine="openpyxl")
        xml = _chart_xml(path)
        assert marker_check in xml, f"{ct}: {marker_check} 見当たらず"


def test_export_from_config_matches(tmp_path=None):
    cfg = {
        "chart_type": "折れ線", "x_col": "時刻",
        "selected_y": [["t.csv", "気温"], ["t.csv", "電力"]],
        "title": "cfg", "secondary_label": "電力",
        "styles": {"t.csv\t気温": {"color": "#d62728"},
                   "t.csv\t電力": {"axis": "secondary"}},
    }
    out = _out(tmp_path, "cfg.xlsx")
    path, eng = export_from_config(_df(), cfg, out_path=out, engine="openpyxl")
    xml = _chart_xml(path)
    assert "cfg" in xml and xml.count("<ser>") == 2 and xml.count("valAx") >= 6


def test_validation_errors(tmp_path=None):
    out = _out(tmp_path, "x.xlsx")
    # 箱ひげは未対応
    try:
        export_excel_chart(_df(), x="時刻", y=["気温"], chart_type="箱ひげ",
                           out_path=out, engine="openpyxl")
        assert False, "箱ひげで例外が出るべき"
    except ValueError:
        pass
    # 存在しない列
    try:
        export_excel_chart(_df(), x="時刻", y=["無い列"], out_path=out, engine="openpyxl")
        assert False, "存在しない列で例外が出るべき"
    except ValueError:
        pass


# ---------------------------------------------------------------- ランナー
def _out(tmp_path, name):
    if tmp_path is not None:
        return str(tmp_path / name)
    d = tempfile.mkdtemp(prefix="excel_chart_test_")
    return os.path.join(d, name)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    ok = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
            ok += 1
        except Exception as e:  # noqa: BLE001
            import traceback
            print(f"FAIL {fn.__name__}: {type(e).__name__}: {e}")
            traceback.print_exc()
    print(f"\n{ok}/{len(fns)} passed")
    raise SystemExit(0 if ok == len(fns) else 1)
