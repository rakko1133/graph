# -*- coding: utf-8 -*-
"""単一ファイル版（graph_onefile.py）がビルドでき、import して主要シンボルが揃うか検証。"""
import importlib
import os
import sys

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


if __name__ == "__main__":
    try:
        test_build_and_import_onefile()
        print("  [PASS] test_build_and_import_onefile")
        print("総合: 1/1 PASS")
    except Exception:
        import traceback
        traceback.print_exc()
        print("総合: 0/1 PASS")
        sys.exit(1)
