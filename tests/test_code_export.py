# -*- coding: utf-8 -*-
"""code_export（設定→Pythonコード生成）の検証。

生成した .py を実際に exec して build_figure() が Figure を返すこと、
.ipynb が妥当な構造であることを、matplotlib の Agg バックエンドで確認する。
Qt 非依存なので offscreen 環境でも軽い。
"""
import json
import os
import sys
import tempfile

import matplotlib
matplotlib.use("Agg")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import code_export  # noqa: E402


def _make_csv(dirpath):
    path = os.path.join(dirpath, "sample.csv")
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        f.write("時刻,値A,値B\n")
        for i in range(20):
            f.write(f"{i},{i * 2},{i * i * 0.1}\n")
    return path


def _config(path, chart_type, **over):
    label = os.path.basename(path)
    cfg = {
        "files": [path],
        "file_meta": {label: {"path": path, "enc": "utf-8-sig", "delim": ",", "sheet": None}},
        "x_col": "時刻",
        "x_leftmost": False,
        "selected_y": [[label, "値A"], [label, "値B"]],
        "chart_type": chart_type,
        "title": "テストグラフ",
        "xlabel": "時刻", "ylabel": "値", "xunit": "s", "yunit": "V",
        "grid": True, "legend": True, "legend_loc": "best",
        "fonts": {"title": 12, "label": 10, "tick": 9, "legend": 9, "annot": 9},
        "styles": {
            f"{label}\t値A": {"color": "#d62728", "linestyle": "-", "linewidth": 2.0,
                              "marker": "o", "markersize": 4.0, "axis": "primary"},
            f"{label}\t値B": {"color": "#1f77b4", "linestyle": "--", "axis": "primary"},
        },
        "xmin": "", "xmax": "", "ymin": "", "ymax": "",
        "xscale": "1", "yscale": "1",
        "bins": 10, "pct": False,
        "trend": "なし", "trend_degree": 2, "trend_window": 5,
        "aspect": "16:9", "aspect_w": 16, "aspect_h": 9,
        "export_dpi": 120, "transparent": False,
    }
    cfg.update(over)
    return cfg


def _exec_build(src):
    """生成した .py を exec し、build_figure() の戻り値を返す。"""
    ns = {}
    code = compile(src, "<generated>", "exec")
    exec(code, ns)                       # __main__ ガードは発火しない
    assert "build_figure" in ns, "build_figure が定義されていない"
    return ns["build_figure"]()


def test_generate_python_runs_for_main_chart_types():
    import matplotlib.figure
    with tempfile.TemporaryDirectory() as d:
        csv = _make_csv(d)
        for ct in ("折れ線", "散布図", "面", "ステップ", "棒", "横棒",
                   "積み上げ棒", "ヒストグラム", "箱ひげ", "バイオリン",
                   "円", "ドーナツ", "ヒートマップ"):
            cfg = _config(csv, ct)
            src = code_export.generate_python(cfg)
            compile(src, f"<{ct}>", "exec")          # 構文チェック
            fig = _exec_build(src)
            assert isinstance(fig, matplotlib.figure.Figure), ct
            assert fig.axes, f"{ct}: 軸が無い"
            matplotlib.pyplot.close(fig)


def test_line_with_trend_and_secondary_axis():
    import matplotlib.pyplot as plt
    with tempfile.TemporaryDirectory() as d:
        csv = _make_csv(d)
        label = os.path.basename(csv)
        cfg = _config(csv, "折れ線", trend="線形", data_labels=True)
        # 値B を第2軸へ
        cfg["styles"][f"{label}\t値B"]["axis"] = "secondary"
        src = code_export.generate_python(cfg)
        fig = _exec_build(src)
        # 主軸に 値A の線 + 近似線、第2軸(twin)が生成される
        assert len(fig.axes) >= 2, "第2軸が作られていない"
        assert fig.axes[0].get_lines(), "主軸に線が無い"
        plt.close(fig)


def test_scale_and_limits_applied():
    import matplotlib.pyplot as plt
    with tempfile.TemporaryDirectory() as d:
        csv = _make_csv(d)
        cfg = _config(csv, "折れ線", yscale="2", ymin="0", ymax="100", ylog=False)
        src = code_export.generate_python(cfg)
        fig = _exec_build(src)
        ax = fig.axes[0]
        lo, hi = ax.get_ylim()
        assert abs(lo - 0.0) < 1e-6 and abs(hi - 100.0) < 1e-6
        plt.close(fig)


def test_unsupported_3d_falls_back_to_line():
    import matplotlib.pyplot as plt
    with tempfile.TemporaryDirectory() as d:
        csv = _make_csv(d)
        cfg = _config(csv, "折れ線", threed=True)
        src = code_export.generate_python(cfg)
        assert "未対応" in src           # 案内コメントが入る
        fig = _exec_build(src)
        assert fig.axes[0].get_lines()
        plt.close(fig)


def test_generate_notebook_structure():
    with tempfile.TemporaryDirectory() as d:
        csv = _make_csv(d)
        nb = code_export.generate_notebook(_config(csv, "折れ線"))
        assert nb["nbformat"] == 4
        assert isinstance(nb["cells"], list) and len(nb["cells"]) >= 4
        assert nb["cells"][0]["cell_type"] == "markdown"
        # json 化できる（=ipynb として保存可能）
        json.dumps(nb, ensure_ascii=False)


def test_export_code_writes_files():
    with tempfile.TemporaryDirectory() as d:
        csv = _make_csv(d)
        cfg = _config(csv, "折れ線")
        py = os.path.join(d, "out.py")
        ipynb = os.path.join(d, "out.ipynb")
        code_export.export_code(cfg, py)
        code_export.export_code(cfg, ipynb)
        assert os.path.isfile(py) and os.path.getsize(py) > 0
        with open(ipynb, encoding="utf-8") as f:
            loaded = json.load(f)
        assert loaded["nbformat"] == 4


def test_missing_file_meta_fallback():
    """file_meta が無い古い設定でも .py を生成でき、構文が通ること。"""
    with tempfile.TemporaryDirectory() as d:
        csv = _make_csv(d)
        cfg = _config(csv, "折れ線")
        cfg.pop("file_meta")             # 旧形式を模す
        src = code_export.generate_python(cfg)
        compile(src, "<nofm>", "exec")
        fig = _exec_build(src)           # 推定ローダで読めるはず
        assert fig.axes[0].get_lines()
        import matplotlib.pyplot as plt
        plt.close(fig)


if __name__ == "__main__":
    # pytest 無しでも直接実行できるようにする
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print("ok:", fn.__name__)
    print(f"ALL GREEN ({len(fns)} tests)")
