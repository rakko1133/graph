# -*- coding: utf-8 -*-
"""アプリの堅牢性（回帰）。

issue #9:  一括出力の並列中に worker 崩壊 → 逐次フォールバックせず全スキップ
issue #10: 「設定を読み込み」が型不正 JSON を握らず未捕捉例外＋半適用
issue #12: プラグインの collect/apply/overlay 失敗が debug のみで気づけない
（#11 終了時スレッドは実スレッド依存のため no-op 経路のみ確認）
"""
import os
import sys
import json
import tempfile
import contextlib

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import config_io  # noqa: E402

config_io.load_last_session = lambda: None   # セッション復元を無効化（テスト独立）

import graph_app  # noqa: E402
import graph_app_common as gac  # noqa: E402
from matplotlib.backends.qt_compat import QtCore, QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
for _m in ("information", "warning", "critical"):
    setattr(QtWidgets.QMessageBox, _m, staticmethod(lambda *a, **k: None))
QtWidgets.QMessageBox.question = staticmethod(
    lambda *a, **k: QtWidgets.QMessageBox.StandardButton.Yes)
QtWidgets.QDialog.exec = lambda self: 0


@contextlib.contextmanager
def _patch(obj, name, value):
    old = getattr(obj, name)
    setattr(obj, name, value)
    try:
        yield
    finally:
        setattr(obj, name, old)


def _make_app(files=("a.csv",)):
    w = graph_app.GraphApp()
    w.datasets.clear(); w.file_list.clear(); w.y_list.clear()
    t = np.linspace(0, 0.02, 200)
    df = pd.DataFrame({"時間": t, "電圧": np.sin(2 * np.pi * 500 * t),
                       "電流": np.cos(2 * np.pi * 500 * t)})
    for name in files:
        w.datasets[name] = df.copy()
        w.meta[name] = {"path": name, "enc": "utf-8", "delim": ","}
        w._add_file_item(name)
    w.file_list.setCurrentRow(0); w._refresh_columns()
    w.x_combo.setCurrentText("時間")
    for r in range(w.y_list.count()):
        it = w.y_list.item(r)
        on = it.data(graph_app.UserRole)[1] != "時間"
        it.setCheckState(QtCore.Qt.CheckState.Checked if on
                         else QtCore.Qt.CheckState.Unchecked)
    w._on_y_selection_changed()
    return w


# ---------------- #9 一括出力: worker 崩壊でも逐次で全件出力 ----------------
class _BrokenFut:
    def result(self):
        from concurrent.futures.process import BrokenProcessPool
        raise BrokenProcessPool("worker died")
    def cancel(self):
        pass


class _BrokenExec:
    def __init__(self, *a, **k):
        pass
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False
    def submit(self, fn, task):
        return _BrokenFut()


def test_batch_export_falls_back_to_sequential_on_broken_pool():
    import concurrent.futures as cf
    w = _make_app(files=("a.csv", "b.csv"))
    out_dir = tempfile.mkdtemp()
    opts = {"dpi": 80, "transparent": False, "title": "{name}", "fmt": "png"}
    with _patch(graph_app, "BATCH_PARALLEL_THRESHOLD", 1), \
         _patch(cf, "ProcessPoolExecutor", _BrokenExec), \
         _patch(cf, "as_completed", lambda futs: list(futs)), \
         _patch(QtWidgets.QFileDialog, "getExistingDirectory",
                staticmethod(lambda *a, **k: out_dir)), \
         _patch(w, "_batch_options_dialog", lambda: opts):
        w.batch_export()        # プール崩壊 → 例外で落ちず逐次フォールバック
    # 2ファイルとも出力される（＝全スキップにならない）
    produced = sorted(f for f in os.listdir(out_dir) if f.endswith(".png"))
    assert len(produced) == 2, produced


# ---------------- #10 設定読み込み: 型不正でも未捕捉で落とさない ----------------
def test_load_config_dialog_survives_apply_error():
    w = _make_app()
    fd, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"files": [], "view_elev": "high"}, f)   # 型不正（int化で失敗）
    notified = []

    def _raise(_cfg, *a, **k):
        raise ValueError("bad type in config")

    try:
        with _patch(QtWidgets.QFileDialog, "getOpenFileName",
                    staticmethod(lambda *a, **k: (path, ""))), \
             _patch(w, "_apply_config", _raise), \
             _patch(w, "notify",
                    lambda msg, level="info", *a, **k: notified.append((level, msg))):
            w.load_config_dialog()          # 例外を外へ漏らさないこと
    finally:
        os.remove(path)
    assert any(lv == "warn" for lv, _ in notified), notified


# ---------------- #11 終了時スレッド停止: スレッド未起動でも安全 ----------------
def test_stop_background_tasks_without_thread():
    w = _make_app()
    w._load_thread = None
    w._stop_background_tasks()              # 何もせず落ちない
    assert w._load_thread is None

    class _Finished:
        def isRunning(self):
            return False
    w._load_thread = _Finished()
    w._stop_background_tasks()              # 完了済みは wait/terminate せず解放
    assert w._load_thread is None


# ---------------- #12 不良プラグインで本体が落ちない / 失敗が可視化される ----------------
class _BrokenPlugin(gac.TabPlugin):
    key = "broken_test"
    title = "壊れタブ"
    order = 999
    min_level = "全部"

    def build(self, app):
        return QtWidgets.QWidget()

    def draw_overlay(self, app, ax):
        raise RuntimeError("overlay boom")

    def collect_config(self, app):
        raise RuntimeError("collect boom")

    def apply_config(self, app, cfg):
        raise RuntimeError("apply boom")


def test_broken_plugin_does_not_crash_host():
    gac.register_tab(_BrokenPlugin())
    try:
        w = _make_app()
        w._draw_plugin_overlays()                       # 例外で本体描画を落とさない
        cfg = w._collect_plugin_config()
        assert "broken_test" not in cfg                 # 失敗したタブの設定は入らない

        notified = []
        with _patch(w, "notify",
                    lambda msg, level="info", *a, **k: notified.append((level, msg))):
            w._apply_plugin_config({"broken_test": {"x": 1}})   # 落とさず通知する
        assert any(lv == "warn" for lv, _ in notified), notified
    finally:
        gac._TAB_REGISTRY[:] = [p for p in gac._TAB_REGISTRY if p.key != "broken_test"]


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    ok = 0
    for fn in fns:
        try:
            fn(); ok += 1; print(f"  [PASS] {fn.__name__}")
        except Exception:
            traceback.print_exc(); print(f"  [FAIL] {fn.__name__}")
    print(f"総合: {ok}/{len(fns)} PASS")
    sys.exit(0 if ok == len(fns) else 1)
