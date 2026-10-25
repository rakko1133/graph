# -*- coding: utf-8 -*-
"""単一ファイル版（graph_onefile.py）がビルドでき、import して主要シンボルが揃うか検証。"""
import importlib
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))


def test_build_and_import_onefile():
    build_onefile = importlib.import_module("build_onefile")
    build_onefile.build()                                  # graph_onefile.py を生成
    assert os.path.isfile(os.path.join(ROOT, "graph_onefile.py"))
    G = importlib.import_module("graph_onefile")            # 結合ファイルを読み込む
    for sym in ("GraphApp", "plot_series", "CHART_TYPES", "fft_spectrum",
                "linear_regression", "binary", "eval_expr", "setup_logging"):
        assert hasattr(G, sym), f"単一ファイルに {sym} が無い"


def test_onefile_embeds_code_export():
    """単一ファイル版に code_export が同梱され、設定からのコード生成が単体で使えること。

    code_export は平坦化せず「本物のモジュール」として埋め込むので、_install_module で
    独立名前空間に取り出して使える（_num などの同名ヘルパが他モジュールと衝突しない）。
    """
    build_onefile = importlib.import_module("build_onefile")
    build_onefile.build()
    G = importlib.import_module("graph_onefile")
    assert hasattr(G, "_install_module"), "onefile に _install_module が無い"
    ce = G._install_module("code_export")
    assert hasattr(ce, "generate_python") and hasattr(ce, "export_code")
    with tempfile.TemporaryDirectory() as d:
        csv = os.path.join(d, "s.csv")
        with open(csv, "w", encoding="utf-8-sig") as f:
            f.write("t,v\n0,1\n1,3\n2,2\n")
        cfg = {
            "files": [csv],
            "file_meta": {"s.csv": {"path": csv, "enc": "utf-8-sig",
                                    "delim": ",", "sheet": None}},
            "x_col": "t", "selected_y": [["s.csv", "v"]], "chart_type": "折れ線",
            "styles": {"s.csv\tv": {"color": "#d62728", "linestyle": "-"}},
            "fonts": {"title": 12, "label": 10, "tick": 9, "legend": 9, "annot": 9},
        }
        src = ce.generate_python(cfg)
        assert "def build_figure" in src and "import matplotlib" in src
        out_py = os.path.join(d, "o.py")
        out_nb = os.path.join(d, "o.ipynb")
        ce.export_code(cfg, out_py)
        ce.export_code(cfg, out_nb)
        assert os.path.getsize(out_py) > 0 and os.path.getsize(out_nb) > 0


if __name__ == "__main__":
    tests = [test_build_and_import_onefile, test_onefile_embeds_code_export]
    passed = 0
    for fn in tests:
        try:
            fn()
            print(f"  [PASS] {fn.__name__}")
            passed += 1
        except Exception:
            import traceback
            traceback.print_exc()
            print(f"  [FAIL] {fn.__name__}")
    print(f"総合: {passed}/{len(tests)} PASS")
    sys.exit(0 if passed == len(tests) else 1)
