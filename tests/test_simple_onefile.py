# -*- coding: utf-8 -*-
"""シンプル版・単一ファイル（graph_simple_onefile.py）の検証。

ビルドできること、見た目テンプレートが消えていること、そして
**機能は1つも落ちていないこと**を機械的に確かめる。
"""
import importlib
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import config_io  # noqa: E402
config_io.load_last_session = lambda: None
from matplotlib.backends.qt_compat import QtCore, QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
for _m in ("information", "critical", "warning"):
    setattr(QtWidgets.QMessageBox, _m, staticmethod(lambda *a, **k: None))
QtWidgets.QMessageBox.question = staticmethod(
    lambda *a, **k: QtWidgets.QMessageBox.StandardButton.Yes)
QtWidgets.QDialog.exec = lambda self: 0

# 通常版と比べるので両方を組み立てる
import graph_app  # noqa: E402

_CTRL = (QtWidgets.QAbstractButton, QtWidgets.QComboBox,
         QtWidgets.QLineEdit, QtWidgets.QAbstractSpinBox)

# 通常版に実在する主要な入口。シンプル版でも全部呼べなければならない。
FEATURES = (
    "run_analysis", "show_fft", "show_spectrogram", "show_waterfall",
    "decode_protocol", "run_regression", "run_t_test", "run_anova",
    "run_normality", "run_custom_fit", "show_corr_matrix", "show_describe",
    "show_eye_diagram", "run_jitter", "run_mask_test", "show_phase",
    "show_cycle_stats", "show_param_stats", "show_trend", "show_series_picker",
    "create_math_channel", "create_math_expr", "export_excel_report",
    "batch_export", "open_graph_window", "show_command_palette",
    "show_message_log",
)


def _build_and_import():
    builder = importlib.import_module("build_simple_onefile")
    builder.build()
    path = os.path.join(ROOT, "graph_simple_onefile.py")
    assert os.path.isfile(path)
    mod = importlib.import_module("graph_simple_onefile")
    return importlib.reload(mod) if "graph_simple_onefile" in sys.modules else mod


def test_simple_onefile_builds_and_runs():
    """1ファイルで組み立てられ、既定がシンプルであること。"""
    QtCore.QSettings("graph-tool", "GraphApp").clear()
    S = _build_and_import()
    w = S.GraphApp()
    try:
        assert w.ui_level() == "基本"
        assert "シンプル" in w.windowTitle()
        # 表示レベルの保存先が通常版と別（共有すると基本で起動しなくなる）
        assert w.UI_LEVEL_KEY != graph_app.GraphApp.UI_LEVEL_KEY
    finally:
        w.close()
        QtCore.QSettings("graph-tool", "GraphApp").clear()


def test_simple_onefile_is_compact():
    """配布用に圧縮されていること（コメント・docstring・空行を落とす）。

    「読むコード」は元のモジュール側にあるので、動かすための1ファイルからは
    説明文を落としてよい。落としても動作は1ビットも変わらない。"""
    S = sys.modules.get("graph_simple_onefile") or _build_and_import()
    path = os.path.join(ROOT, "graph_simple_onefile.py")
    src = open(path, encoding="utf-8").read()
    assert S.__doc__, "先頭の説明（これは何のファイルか）は残す"
    body = src.split('"""', 2)[-1].lstrip("\n")   # 先頭の改行は分割の副産物
    # 説明文が残っていない
    assert "    # " not in body, "行コメントが残っている"
    assert not [l for l in body.splitlines() if not l.strip()], "空行が残っている"
    # 構文は完全（compile が通る）。本体からテンプレートを廃止した今、通常版との
    # 違いは既定の表示レベルだけなので、サイズの大小比較はもう意味を持たない
    # （「基本で起動する／別キー／別見出し」は test_simple_onefile_builds_and_runs で担保）。
    compile(src, path, "exec")


def test_simple_onefile_has_no_look_templates():
    """見た目テンプレートがコードから消えていること。"""
    S = sys.modules.get("graph_simple_onefile") or _build_and_import()
    assert set(S.GraphApp._UI_STYLES) == {"standard"}
    assert not hasattr(S.GraphApp, "_set_ui_style")
    src = open(os.path.join(ROOT, "graph_simple_onefile.py"), encoding="utf-8").read()
    body = src.split('"""', 2)[-1]          # 冒頭の説明文は対象外
    for word in ("LabPlot風", "Veusz風", "KST2風", "Igor Pro風",
                 "配置は変えずに外観だけ"):
        assert word not in body, f"{word} がコード本体に残っている"


def test_simple_onefile_keeps_every_feature():
    """機能・設定・コントロールが通常版と同じだけ残っていること。"""
    QtCore.QSettings("graph-tool", "GraphApp").clear()
    S = sys.modules.get("graph_simple_onefile") or _build_and_import()
    w, full = S.GraphApp(), graph_app.GraphApp()
    try:
        missing = [m for m in FEATURES if not callable(getattr(w, m, None))]
        assert not missing, f"シンプル版に無い機能: {missing}"
        # ウィジェットも設定キーも通常版と完全一致（隠れているだけ）
        assert ({n for n in dir(w) if isinstance(getattr(w, n, None), _CTRL)}
                == {n for n in dir(full) if isinstance(getattr(full, n, None), _CTRL)})
        w.set_ui_level("全部", announce=False)
        assert set(w._collect_config()) == set(full._collect_config())
        # 作業向けの配置4種は残す（消したのは◯◯風だけ）
        for name in ("standard", "graph", "analysis", "data"):
            w._apply_layout_preset(name)
        # 基本レベルで隠した設定は名前で必ず呼び戻せる
        w.set_ui_level("基本", announce=False)
        hidden = [e for e in w._setting_index if not e["widget"].isVisibleTo(w)]
        assert len(hidden) > 30
        for e in hidden[:10]:
            w.set_ui_level("基本", announce=False)
            assert w._jump_to_setting(e["key"]) is not None
            assert e["widget"].isVisibleTo(w), f"{e['key']} が呼び戻せない"
    finally:
        w.close()
        full.close()
        QtCore.QSettings("graph-tool", "GraphApp").clear()


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    ok = 0
    for fn in tests:
        try:
            fn()
            print(f"  [PASS] {fn.__name__}")
            ok += 1
        except Exception:  # noqa: BLE001
            import traceback
            print(f"  [FAIL] {fn.__name__}: {traceback.format_exc().splitlines()[-1]}")
    print(f"総合: {ok}/{len(tests)} PASS")
    sys.exit(0 if ok == len(tests) else 1)
