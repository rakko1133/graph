# -*- coding: utf-8 -*-
"""アプリのオフスクリーン・スモーク＋数値正しさテスト。

pytest でもスクリプト単体でも実行できる:
    python -m pytest tests/                  （CI）
    python tests/test_app.py                 （手元での簡易確認）
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import config_io  # noqa: E402

config_io.load_last_session = lambda: None  # セッション復元を無効化（テスト独立）

import graph_app  # noqa: E402
from matplotlib.backends.qt_compat import QtCore, QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
for _m in ("information", "critical", "warning"):
    setattr(QtWidgets.QMessageBox, _m, staticmethod(lambda *a, **k: None))
QtWidgets.QMessageBox.question = staticmethod(
    lambda *a, **k: QtWidgets.QMessageBox.StandardButton.Yes)
QtWidgets.QDialog.exec = lambda self: 0


def _make_app(df, x="時間"):
    w = graph_app.GraphApp()
    w.datasets.clear(); w.file_list.clear(); w.y_list.clear()
    w.datasets["t.csv"] = df
    w.meta["t.csv"] = {"path": "t.csv", "enc": "utf-8", "delim": ","}
    w._add_file_item("t.csv"); w.file_list.setCurrentRow(0); w._refresh_columns()
    w.x_combo.setCurrentText(x)
    for r in range(w.y_list.count()):
        it = w.y_list.item(r)
        on = it.data(graph_app.UserRole)[1] != x
        it.setCheckState(QtCore.Qt.CheckState.Checked if on else QtCore.Qt.CheckState.Unchecked)
    w._on_y_selection_changed()
    return w


def _wave():
    t = np.linspace(0, 0.02, 1000)
    return pd.DataFrame({"時間": t, "電圧": np.sin(2 * np.pi * 500 * t),
                         "電流": np.cos(2 * np.pi * 500 * t)})


# ---------------- スモーク（GUI が壊れていないか）----------------
def test_construct():
    w = _make_app(_wave())
    assert w.tabs.count() == 4
    assert hasattr(w, "ax")


def test_draw_all_chart_types():
    import plotter
    w = _make_app(_wave())
    for ct in plotter.CHART_TYPES:
        w.chart_combo.setCurrentText(ct)
        w.draw_graph()   # 例外を投げないこと


def test_new_chart_types_render_and_colorbar_cleanup():
    """拡充したグラフ種別が実際に描画され、カラーバーが積み重ならないこと。"""
    import plotter
    w = _make_app(_wave())

    def _artist_count():
        ax = w.ax
        return (len(ax.collections) + len(ax.patches)
                + len(ax.get_lines()) + len(ax.images))

    for ct in ("面", "積み上げ面", "ステップ", "ステム", "2Dヒストグラム",
               "hexbin", "バイオリン", "ヒートマップ", "ドーナツ"):
        w.chart_combo.setCurrentText(ct)
        w.draw_graph()
        assert _artist_count() > 0, f"{ct} が何も描画していない"

    # カラーバーを使う種別を繰り返し描いても補助軸は1本までしか残らない
    for ct in ("2Dヒストグラム", "hexbin", "折れ線", "ヒートマップ", "2Dヒストグラム"):
        w.chart_combo.setCurrentText(ct)
        w.draw_graph()
        assert len(w.fig.axes) <= 2, f"{ct} 後に補助軸が累積 ({len(w.fig.axes)})"
    # 折れ線に戻すとカラーバーは消える（メイン軸のみ）
    w.chart_combo.setCurrentText("折れ線")
    w.draw_graph()
    assert len(w.fig.axes) == 1

    # 面グラフでも近似曲線が描ける（間引き前フルデータでフィット）
    w.chart_combo.setCurrentText("面")
    w.trend_combo.setCurrentText("線形"); w.trend_eq.setChecked(True)
    w.draw_graph()
    assert any("近似" in str(ln.get_label()) for ln in w.ax.get_lines())


def test_3d_via_checkbox_and_axis_swap():
    """『3D表示』チェックで3D化される（表示名では判断しない）。往復・視点・復帰も確認。"""
    import plotter
    df = pd.DataFrame({"時間": np.linspace(0, 10, 60),
                       "電圧": np.sin(np.linspace(0, 10, 60)) + 2,
                       "電流": np.cos(np.linspace(0, 10, 60))})
    w = _make_app(df, x="時間")
    w.z_combo.setCurrentText("電流")

    def set_chart(base, threed):
        w.chart_combo.setCurrentText(base)   # ここで _sync_3d_checkbox が走る
        w.threed_check.setChecked(threed)

    # 散布図/折れ線/棒 は「3D表示」チェックONで3D軸になる
    for base in ("散布図", "折れ線", "棒"):
        set_chart(base, True)
        w.draw_graph()
        assert getattr(w.ax, "name", None) == "3d", f"{base}+3D が3D軸でない"
        assert (len(w.ax.collections) + len(w.ax.lines)) > 0

    # 同じ種別でもチェックOFFなら2D（＝名前ではなくチェックで判断している）
    set_chart("散布図", False); w.draw_graph()
    assert getattr(w.ax, "name", None) != "3d"

    # 曲面は常に3D（チェックは固定・無効）
    w.chart_combo.setCurrentText("曲面")
    assert w.threed_check.isChecked() and not w.threed_check.isEnabled()
    w.draw_graph()
    assert getattr(w.ax, "name", None) == "3d"

    # 3D対応でない種別ではチェックが無効
    w.chart_combo.setCurrentText("箱ひげ")
    assert not w.threed_check.isEnabled()

    # 視点角度がグラフに反映される
    set_chart("散布図", True); w.elev_spin.setValue(45); w.azim_spin.setValue(120)
    w.draw_graph()
    assert round(w.ax.elev) == 45 and round(w.ax.azim) == 120

    # 2D⇔3D を往復しても補助軸（カラーバー等）が積み重ならない
    for base, th in [("折れ線", False), ("散布図", True), ("2Dヒストグラム", False),
                     ("曲面", True), ("折れ線", False)]:
        set_chart(base, th); w.draw_graph()
        assert len(w.fig.axes) <= 2, f"{base} 後に補助軸が累積"
    assert getattr(w.ax, "name", None) != "3d"

    # 3D表示中でも FFT（2D専用ビュー）が2D軸に戻って描ける
    set_chart("散布図", True); w.draw_graph()
    w.analysis_target.setCurrentText("電圧"); w.show_fft()
    assert getattr(w.ax, "name", None) != "3d"

    # 3D棒は複数系列でも凡例が出る（bar3d に label を渡している）
    set_chart("棒", True); w.legend_check.setChecked(True); w.draw_graph()
    _, labels = w.ax.get_legend_handles_labels()
    assert len(labels) >= 2

    # 3D表示中に全Y選択を外しても、案内表示（2D軸）へ安全に戻る（クラッシュしない）
    set_chart("散布図", True); w.draw_graph()
    for r in range(w.y_list.count()):
        w.y_list.item(r).setCheckState(QtCore.Qt.CheckState.Unchecked)
    w.draw_graph()   # 空選択 → プレースホルダ。3D軸のままだと例外になっていた
    assert getattr(w.ax, "name", None) != "3d"

    # 旧『3D…』種別名は 2D名＋3Dフラグへ移行される（保存互換）
    assert plotter.migrate_chart_type("3D散布図") == ("散布図", True)
    assert plotter.migrate_chart_type("散布図")[1] is None


def test_pca_creates_3d_ready_dataset():
    """PCA 計算（sklearn/numpy 両対応）と、GUI で PC 列を作り3D散布図で描けること。"""
    import builtins
    import datasci

    rng = np.random.default_rng(0)
    base = rng.normal(0, 1, 200)
    feats = [("f0", base + rng.normal(0, 0.1, 200)),
             ("f1", rng.normal(0, 1, 200)),
             ("f2", base * 0.8 + rng.normal(0, 0.2, 200)),
             ("f3", rng.normal(0, 1, 200))]

    r = datasci.pca(feats, n_components=3, standardize=True)
    assert r is not None and len(r["scores"]) == 3
    # 寄与率は降順、scores 長さ = サンプル数
    assert r["explained_ratio"] == sorted(r["explained_ratio"], reverse=True)
    assert all(len(a) == r["n_samples"] for _, a in r["scores"])

    # NaN を含む行は除外される
    f2 = [(n, a.copy()) for n, a in feats]
    f2[0][1][:10] = np.nan
    assert datasci.pca(f2, n_components=3)["n_samples"] == 190

    # sklearn を隠すと numpy フォールバックで計算できる
    real_import = builtins.__import__

    def _no_sklearn(name, *a, **k):
        if name.startswith("sklearn"):
            raise ImportError("blocked for test")
        return real_import(name, *a, **k)
    builtins.__import__ = _no_sklearn
    try:
        rf = datasci.pca(feats, n_components=3)
    finally:
        builtins.__import__ = real_import
    assert rf["backend"] == "numpy" and len(rf["scores"]) == 3

    # GUI: 選択系列に run_pca → PCA データセット作成 → 3D散布図で描画
    df = pd.DataFrame({n: a for n, a in feats})
    w = graph_app.GraphApp()
    w.datasets.clear(); w.file_list.clear(); w.y_list.clear()
    w.datasets["d.csv"] = df; w.meta["d.csv"] = {"path": "d.csv", "enc": "utf-8", "delim": ","}
    w._add_file_item("d.csv"); w.file_list.setCurrentRow(0); w._refresh_columns()
    for r0 in range(w.y_list.count()):
        w.y_list.item(r0).setCheckState(QtCore.Qt.CheckState.Checked)
    w._on_y_selection_changed()
    n_before = len(w.datasets)
    w.run_pca()
    new = [k for k in w.datasets if k.startswith("PCA:")]
    assert len(w.datasets) == n_before + 1 and new
    assert list(w.datasets[new[0]].columns) == ["PC1", "PC2", "PC3"]

    # 作成した PCA を 3D 散布図で描画（X=PC1, Z=PC3, Y=PC2）
    lbl = new[0]
    labels = [w.file_list.item(i).text() for i in range(w.file_list.count())]
    w.file_list.setCurrentRow(labels.index(lbl)); w._refresh_columns()
    w.x_combo.setCurrentText("PC1"); w.z_combo.setCurrentText("PC3")
    for r0 in range(w.y_list.count()):
        it = w.y_list.item(r0)
        it.setCheckState(QtCore.Qt.CheckState.Checked
                         if it.data(graph_app.UserRole) == (lbl, "PC2")
                         else QtCore.Qt.CheckState.Unchecked)
    w._on_y_selection_changed()
    w.chart_combo.setCurrentText("散布図"); w.threed_check.setChecked(True)
    w.draw_graph()
    assert getattr(w.ax, "name", None) == "3d"


def test_oscilloscope_and_fft():
    w = _make_app(_wave())
    w.chart_combo.setCurrentText("折れ線")
    w.scope_check.setChecked(True); w.tdiv.setCurrentText("1ms"); w.vdiv.setCurrentText("500m")
    w.draw_graph()
    assert tuple(round(c, 3) for c in w.ax.get_facecolor()) != (1.0, 1.0, 1.0, 1.0)  # 濃色背景
    w.scope_check.setChecked(False)
    w.analysis_target.setCurrentText("電圧")
    w.show_fft()
    w.run_analysis()


def test_axis_invert_and_power_notation():
    w = _make_app(_wave())
    w.chart_combo.setCurrentText("折れ線")
    w.xinvert_check.setChecked(True); w.draw_graph()
    x0, x1 = w.ax.get_xlim()
    assert w.ax.xaxis_inverted() and x0 > x1
    import mathchan
    w.xscale_edit.setText("10^-6")   # 倍率欄は式/累乗表記も可
    assert abs(float(mathchan.axis_scale([1.0], "10^-6")[0]) - 1e-6) < 1e-18
    assert list(mathchan.axis_scale([0.0, 100.0], "x*9/5+32")) == [32.0, 212.0]


def test_config_roundtrip():
    w = _make_app(_wave())
    w.title_edit.setText("テスト"); w.xinvert_check.setChecked(True)
    cfg = w._collect_config()
    w2 = graph_app.GraphApp()
    w2._apply_config(cfg, load_files=False)
    assert w2.title_edit.text() == "テスト"
    assert w2.xinvert_check.isChecked() is True


# ---------------- 数値の正しさ（過去に直したバグの回帰防止）----------------
def test_zero_crossing_period_all_duties():
    import analysis_common as ac
    fs = 10000.0
    t = np.arange(0, 0.6, 1 / fs)
    for duty in (0.1, 0.3, 0.5):
        y = np.where((t % 0.1) < 0.1 * duty, 5.0, 0.0)
        assert abs(ac._zero_crossing_period(t, y) - 0.1) < 5e-3   # 全デューティで0.1s


def test_fft_nyquist_amplitude():
    import analysis_spectrum as asp
    n = 1024
    tt = np.arange(n) / 1000.0
    f, amp = asp.fft_spectrum(tt, 2 * np.cos(2 * np.pi * 500 * tt), window="rect", detrend=False)
    assert abs(amp[-1] - 2.0) < 0.05   # ナイキストは2倍にならない


def test_linear_regression():
    import datasci
    x = np.linspace(0, 10, 50)
    d = datasci.linear_regression(x, 2 * x + 1)
    assert abs(d["slope"] - 2) < 1e-6 and abs(d["intercept"] - 1) < 1e-6 and abs(d["r2"] - 1) < 1e-9


def test_curve_fit_extensions():
    import plotter
    import plotter_draw
    assert plotter.TRENDLINES[-3:] == ["ガウシアン", "ローレンツ", "シグモイド"]
    x = np.linspace(-5, 5, 200)
    y = 3.0 * np.exp(-((x - 1.0) ** 2) / (2 * 0.8 ** 2)) + 0.5
    fit = plotter_draw.fit_trendline(x, y, "ガウシアン")
    assert fit is not None and fit[3] > 0.999   # R² ほぼ1


def test_clipboard_paste():
    w = _make_app(_wave())
    n0 = len(w.datasets)
    QtWidgets.QApplication.clipboard().setText("A\tB\n1\t10\n2\t20")
    w.paste_from_clipboard()
    assert len(w.datasets) == n0 + 1


def test_format_preset_roundtrip():
    import glob
    w = _make_app(_wave())
    for p in glob.glob(os.path.join(w._presets_dir(), "*.json")):
        os.remove(p)
    w.grid_check.setChecked(False); w.fs_title.setValue(21)
    QtWidgets.QInputDialog.getText = staticmethod(lambda *a, **k: ("p1", True))
    w.save_preset()
    assert "p1" in w._list_presets()
    w.grid_check.setChecked(True); w.fs_title.setValue(10)
    w.preset_combo.setCurrentText("p1"); w.apply_preset()
    assert w.grid_check.isChecked() is False and w.fs_title.value() == 21
    w.delete_preset()


def test_fill_between():
    from matplotlib.collections import PolyCollection
    w = _make_app(_wave())
    w.chart_combo.setCurrentText("折れ線")
    w.fill_check.setChecked(True)
    w.fill_a.setCurrentText("電圧"); w.fill_b.setCurrentText("電流")
    w.draw_graph()
    assert any(isinstance(c, PolyCollection) for c in w.ax.collections)
    w.fill_b.setCurrentText("0（X軸）"); w.draw_graph()
    assert any(isinstance(c, PolyCollection) for c in w.ax.collections)


def test_undo_redo():
    w = _make_app(_wave())
    for s in ("A", "B", "C"):
        w.title_edit.setText(s); w.draw_graph()
    w.undo()
    assert w.title_edit.text() == "B"
    w.redo()
    assert w.title_edit.text() == "C"


# ---------------- スクリプト単体実行用ランナー ----------------
if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    ok = 0
    for fn in tests:
        try:
            fn(); print(f"  [PASS] {fn.__name__}"); ok += 1
        except Exception as e:  # noqa: BLE001
            import traceback
            print(f"  [FAIL] {fn.__name__}: {traceback.format_exc().splitlines()[-1]}")
    print(f"総合: {ok}/{len(tests)} PASS")
    sys.exit(0 if ok == len(tests) else 1)
