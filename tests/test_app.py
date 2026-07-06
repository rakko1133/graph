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
    assert len(w.left_docks) == 4          # データ/オシロ/高度解析/統計解析 のドック
    assert w.format_dock is not None       # 右端の書式パネル
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


def test_swap_xy_and_multi_x():
    """X↔Y入れ替え（データ・ラベルの転置）と、X軸複数選択（各X×各Yで系列化）。"""
    df = pd.DataFrame({"時間": np.linspace(0, 10, 30),
                       "A": np.linspace(0, 10, 30) * 2,
                       "B": -np.linspace(0, 10, 30),
                       "電圧": np.sin(np.linspace(0, 10, 30))})
    w = _make_app(df, x="時間")
    # Y=電圧 だけ
    for r in range(w.y_list.count()):
        it = w.y_list.item(r)
        it.setCheckState(QtCore.Qt.CheckState.Checked
                         if it.data(graph_app.UserRole)[1] == "電圧"
                         else QtCore.Qt.CheckState.Unchecked)
    w._on_y_selection_changed()
    w.chart_combo.setCurrentText("折れ線")

    # 通常: X=時間(0..10)
    w.swap_xy_check.setChecked(False); w.draw_graph()
    xd = np.asarray(w.ax.get_lines()[0].get_xdata())
    assert xd.min() >= 0 and xd.max() <= 10.01

    # 入れ替え: X が 電圧(sin, -1..1)、Y が 時間(0..10) に転置
    w.swap_xy_check.setChecked(True); w.draw_graph()
    ln = w.ax.get_lines()[0]
    xs = np.asarray(ln.get_xdata()); ys = np.asarray(ln.get_ydata())
    assert xs.min() < 0 and xs.max() <= 1.01 and ys.max() > 9
    w.swap_xy_check.setChecked(False)

    # 複数X: A と B をXに → 電圧×A, 電圧×B の2系列（凡例に [X:A] [X:B]）
    w.chart_combo.setCurrentText("散布図")
    w.multix_check.setChecked(True)
    for r in range(w.x_list.count()):
        it = w.x_list.item(r)
        it.setCheckState(QtCore.Qt.CheckState.Checked
                         if it.data(graph_app.UserRole) in ("A", "B")
                         else QtCore.Qt.CheckState.Unchecked)
    series, _ = w._build_series("散布図")
    labels = [s["label"] for s in series]
    assert len(series) == 2
    assert any("[X:A]" in s for s in labels) and any("[X:B]" in s for s in labels)


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


def test_explorer_tree_sync():
    """ファイル→列ツリーが y_list / file_list と双方向同期すること。"""
    ck, un = QtCore.Qt.CheckState.Checked, QtCore.Qt.CheckState.Unchecked
    w = _make_app(_wave())   # 電圧・電流がチェック済み（時間=X軸列は未チェック）
    tree = w.explorer
    assert tree.topLevelItemCount() == 1
    node = tree.topLevelItem(0)
    assert node.childCount() == w.y_list.count() == 3
    assert node.checkState(0) == QtCore.Qt.CheckState.PartiallyChecked   # 2/3列ON
    # y_list → ツリー（電圧をOFF）
    idx = next(i for i in range(w.y_list.count())
               if w.y_list.item(i).data(graph_app.UserRole)[1] == "電圧")
    w.y_list.item(idx).setCheckState(un)
    assert node.child(idx).checkState(0) == un
    # ツリー → y_list（電圧をON）
    node.child(idx).setCheckState(0, ck)
    assert w.y_list.item(idx).checkState() == ck
    # ファイル行のチェック＝全列一括
    node.setCheckState(0, un)
    assert not w._selected_series_items()
    node.setCheckState(0, ck)
    assert len(w._selected_series_items()) == 3
    assert node.checkState(0) == ck
    # 現在ファイルの同期（file_list → ツリー）
    assert tree.currentItem() is node
    # ファイル削除でツリーも空になる
    w._remove_labels(["t.csv"])
    assert tree.topLevelItemCount() == 0


def test_new_ux_features():
    """段分け表示・区間測定・データ編集Undo・表エクスポートの回帰。"""
    w = _make_app(_wave())
    w.draw_graph()
    # 結果表の行抽出（コピー/CSV保存の土台）
    w.run_analysis()
    rows = w._table_rows(w.meas_table, False)
    assert rows[0][0] == "項目" and len(rows) > 3
    # 区間測定（ドラッグ範囲→測定）
    w.gate_btn.setChecked(True)
    w._on_gate_select(0.002, 0.012)
    assert any(w.meas_table.item(r, 1).text() != "-"
               for r in range(w.meas_table.rowCount()))
    w.gate_btn.setChecked(False)
    # 段分け表示（系列ごとにサブプロット）と通常表示への復帰
    w.stack_check.setChecked(True)
    w.draw_graph()
    assert w._stacked and len(w.fig.axes) == 2   # 電圧・電流の2段
    w.stack_check.setChecked(False)
    w.draw_graph()
    assert not getattr(w, "_stacked", False)
    assert len(w.ax.get_lines()) >= 2            # 単一軸に戻って重ね描き
    # データ編集の Undo / Redo
    lbl = w._preview_label
    n0 = len(w.datasets[lbl])
    w._row_add()
    assert len(w.datasets[lbl]) == n0 + 1
    w._data_undo()
    assert len(w.datasets[lbl]) == n0
    w._data_redo()
    assert len(w.datasets[lbl]) == n0 + 1


def test_new_loaders():
    """WAV / LTspice raw / Excelシート指定の読み込み。"""
    import struct
    import tempfile
    import wave as wavmod
    import data_loader
    d = tempfile.gettempdir()
    # WAV (16bit mono)
    wp = os.path.join(d, "t_load.wav")
    with wavmod.open(wp, "w") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(1000)
        w.writeframes(struct.pack("<4h", 0, 100, -100, 50))
    df, enc, _ = data_loader.load_table(wp)
    assert enc == "wav" and len(df) == 4 and str(df.columns[0]).startswith("時間")
    assert abs(df.iloc[1, 1] - 100) < 1e-9
    # LTspice .raw（バイナリ・time=f64/値=f32）
    rp = os.path.join(d, "t_load.raw")
    hdr = ("Title: * test\nDate: x\nPlotname: Transient Analysis\nFlags: real\n"
           "No. Variables: 2\nNo. Points: 3\nVariables:\n"
           "\t0\ttime\ttime\n\t1\tV(out)\tvoltage\nBinary:\n")
    body = b"".join(struct.pack("<d", i * 1e-3) + struct.pack("<f", float(v))
                    for i, v in enumerate([1.0, 2.0, 3.0]))
    with open(rp, "wb") as fh:
        fh.write(hdr.encode("ascii") + body)
    df3, enc3, _ = data_loader.load_table(rp)
    assert enc3 == "ltspice" and df3.shape == (3, 2)
    assert abs(df3.iloc[2, 1] - 3.0) < 1e-6 and abs(df3.iloc[2, 0] - 2e-3) < 1e-12
    # Excel（シート指定）
    xp = os.path.join(d, "t_load.xlsx")
    with pd.ExcelWriter(xp) as w:
        pd.DataFrame({"a": [1, 2]}).to_excel(w, sheet_name="S1", index=False)
        pd.DataFrame({"b": [3, 4, 5]}).to_excel(w, sheet_name="S2", index=False)
    assert data_loader.excel_sheet_names(xp) == ["S1", "S2"]
    df2, enc2, _ = data_loader.load_table(xp, sheet="S2")
    assert enc2 == "excel" and len(df2) == 3 and "b" in df2.columns


def _stuff_can(bits):
    out, rv, rn = [], None, 0
    for b in bits:
        out.append(b)
        rn = rn + 1 if b == rv else 1
        rv = b
        if rn == 5:
            out.append(1 - b)
            rv, rn = 1 - b, 1
    return out


def test_protocol_decoders_can_lin_onewire():
    """CAN（CRC15/スタッフィング）・LIN（チェックサム）・1-Wire の解読。"""
    import advanced
    # --- CAN 標準フレーム ---
    fid, data = 0x123, [0xDE, 0xAD]
    bits = [0] + [(fid >> i) & 1 for i in range(10, -1, -1)] + [0, 0, 0]
    bits += [(len(data) >> i) & 1 for i in range(3, -1, -1)]
    for dd in data:
        bits += [(dd >> i) & 1 for i in range(7, -1, -1)]
    crc = advanced._can_crc15(bits)
    stuffed = _stuff_can(bits + [(crc >> i) & 1 for i in range(14, -1, -1)])
    wave_bits = [1] * 30 + stuffed + [1, 0, 1] + [1] * 30
    sig = np.repeat(wave_bits, 20).astype(float) * 3.3
    t = np.arange(len(sig)) / (500e3 * 20)
    fr = advanced.decode_can(t, sig, bitrate=500e3)
    assert len(fr) == 1 and fr[0]["id"] == 0x123 and fr[0]["data"] == data
    assert fr[0]["crc_ok"] and not fr[0]["ext"]
    # --- LIN ---
    def uart(v):
        return [0] + [(v >> i) & 1 for i in range(8)] + [1]
    def lin_sum(vals):
        s = 0
        for v in vals:
            s += v
            if s > 0xFF:
                s = (s & 0xFF) + 1
        return (~s) & 0xFF
    pid, ldata = 0x50, [1, 2]   # fid=0x10 の正しいPID
    lbits = [1] * 20 + [0] * 14 + [1] * 2
    for b in [0x55, pid] + ldata + [lin_sum([pid] + ldata)]:
        lbits += uart(b) + [1]
    lsig = np.repeat(lbits + [1] * 20, 16).astype(float) * 12
    lt = np.arange(len(lsig)) / (19200 * 16)
    ev = advanced.decode_lin(lt, lsig, baud=19200)
    kinds = [e["type"] for e in ev]
    assert kinds[:3] == ["BREAK", "SYNC", "PID"]
    assert [e["value"] for e in ev if e["type"] == "data"] == ldata
    assert [e for e in ev if e["type"] == "CSUM"][0]["ok"]
    # --- 1-Wire（リセット＋プレゼンス＋0xA5） ---
    w = [5.0] * 100 + [0.0] * 500 + [5.0] * 30 + [0.0] * 100 + [5.0] * 100
    for i in range(8):
        bit = (0xA5 >> i) & 1
        w += ([0.0] * 6 + [5.0] * 64) if bit else ([0.0] * 60 + [5.0] * 10)
    sig1w = np.array(w + [5.0] * 100)
    t1w = np.arange(len(sig1w)) / 1e6
    ev4 = advanced.decode_onewire(t1w, sig1w)
    assert [e["type"] for e in ev4] == ["RESET", "PRESENCE", "data"]
    assert ev4[-1]["value"] == 0xA5


def test_custom_fit_and_stats():
    """任意関数フィット・t検定・ANOVA（scipy）。"""
    import datasci
    x = np.linspace(0, 1, 200)
    y = 2.5 * np.exp(-x / 0.3) + 1.0
    d = datasci.fit_custom(x, y, "a*exp(-x/b)+c", ["a", "b", "c"], [1.0, 1.0, 0.0])
    assert d and abs(d["params"][0][1] - 2.5) < 1e-3
    assert abs(d["params"][1][1] - 0.3) < 1e-3 and d["r2"] > 0.9999
    tt = datasci.t_test(np.r_[np.zeros(50) + 0.5, 0.4, 0.6], mu=0.0)
    assert tt and tt["sig_5pct"] and tt["p_value"] < 1e-6
    tt2 = datasci.t_test([1, 2, 3, 2, 1, 2], b=[1.1, 2.1, 2.9, 2.0, 1.2, 2.1], paired=True)
    assert tt2 and "p_value" in tt2
    an = datasci.anova_oneway([("g1", [1, 2, 3, 2, 1]), ("g2", [5, 6, 7, 6, 5])])
    assert an and an["sig_5pct"]


def test_waterfall_smoke():
    """FFTウォーターフォール（3D）の表示と通常表示への復帰。"""
    w = _make_app(_wave())
    w.draw_graph()
    w.show_waterfall()
    assert w.ax.name == "3d" and len(w.ax.lines) > 5
    w.draw_graph()
    assert w.ax.name != "3d"


def test_gui_interactions():
    """全系列ホバー値・D&D系列追加・解読オーバーレイ・リンク選択の回帰。"""
    ck, un = QtCore.Qt.CheckState.Checked, QtCore.Qt.CheckState.Unchecked
    w = _make_app(_wave())
    w.draw_graph()
    # 1) ホバー: 表示X座標での全系列値（電圧・電流の2系列分）
    vals = w._hover_values(w.ax, 0.005)
    assert len(vals) == 2 and all(len(v) == 4 for v in vals)
    # 2) D&D: ペイロードを直接ドロップ → 未選択の系列が追加され描画される
    w._find_y_item("t.csv", "電圧").setCheckState(un)
    assert len(w._selected_series_items()) == 1
    w._drop_series("t.csv\t電圧")
    assert len(w._selected_series_items()) == 2
    node = w.explorer.topLevelItem(0)
    leaf = next(node.child(j) for j in range(node.childCount())
                if node.child(j).data(0, graph_app.UserRole)[2] == "電圧")
    assert "t.csv\t電圧" in w.explorer._drag_payload(leaf)
    assert w.explorer._drag_payload(node).count("\t") == 3   # ファイル行=全列
    # 3) 解読オーバーレイ: 注記データ＋チェックONで波形上にテキストが載る
    n_before = len(w.ax.texts)
    w._proto_annotations = {"rows": [(0.001, "data", "0x41", ""),
                                     (0.002, "data", "0x42", "CRC⚠")],
                            "proto": "UART"}
    w.proto_overlay_check.setChecked(True)   # → 再描画で注記
    w.draw_graph()
    assert len(w.ax.texts) >= n_before + 2
    w.proto_overlay_check.setChecked(False)
    w.draw_graph()
    # 4) リンク選択: 表の行選択 → リング強調 ／ 線ピック → 行選択
    w.table.selectRow(3)
    assert len(w._link_artists) == 2   # チェック中の2系列ぶんのリング
    assert w._line_pick_map            # 単純折れ線なのでピック配線がある

    class _PickEv:
        artist = next(iter(w._line_pick_map))
        ind = [7]
    w.table.clearSelection()
    w._on_legend_pick(_PickEv())
    sel = {i.row() for i in w.table.selectedIndexes()}
    assert sel == {7}


def test_layout_presets_and_ltspice_plumbing():
    """レイアウトプリセットの切替と、LTspice連携の配管（実行はしない）。"""
    w = _make_app(_wave())
    w.resize(1280, 800)
    w._apply_layout_preset("graph")
    assert all(d.isHidden() for d in [*w.left_docks, w.format_dock])
    assert w.center_splitter.sizes()[1] == 0
    w._apply_layout_preset("analysis")
    assert not w.left_docks[1].isHidden() and w.left_docks[0].isHidden()
    w._apply_layout_preset("standard")
    assert all(not d.isHidden() for d in [*w.left_docks, w.format_dock])
    # .asc/.net は読み込みではなくシミュレーション実行へディスパッチされる
    called = []
    w.run_ltspice_asc = lambda p=None: called.append(p)
    w._load_file(r"C:\tmp\x.asc")
    w._load_file(r"C:\tmp\y.net")
    assert called == [r"C:\tmp\x.asc", r"C:\tmp\y.net"]
    w._ltspice_exe()   # exe探索がどの環境でも例外なく動く


def test_folder_tree_and_graph_windows():
    """フォルダ階層ツリー・複数グラフウィンドウ・レイアウトプリセットの回帰。"""
    import tempfile
    w = _make_app(_wave())
    w.draw_graph()
    # 複数グラフウィンドウ（開く→描画済み→閉じると参照が消える）
    w.open_graph_window()
    assert len(w._graph_windows) == 1
    axs = w._graph_windows[0].findChild(type(w.canvas)).figure.axes
    assert axs and len(axs[0].get_lines()) >= 2
    w._graph_windows[0].close()
    assert not w._graph_windows
    # フォルダ読込 → 2フォルダでツリーが フォルダ→ファイル→列 に階層化
    base = os.path.join(tempfile.gettempdir(), "gtest_tree")
    for sub, col in (("A", "v1"), ("B", "v2")):
        os.makedirs(os.path.join(base, sub), exist_ok=True)
        pd.DataFrame({"t": [0, 1], col: [1.0, 2.0]}).to_csv(
            os.path.join(base, sub, f"{col}.csv"), index=False)
    w._load_folder(os.path.join(base, "A"))
    w._load_folder(os.path.join(base, "B"))
    kinds = [w.explorer.topLevelItem(i).data(0, graph_app.UserRole)[0]
             for i in range(w.explorer.topLevelItemCount())]
    assert kinds.count("folder") == 2
    assert len(list(w._iter_file_nodes())) == 3   # t.csv + v1.csv + v2.csv
    # 階層があっても列チェックが y_list と同期する
    fnode = next(n for n in w._iter_file_nodes()
                 if n.data(0, graph_app.UserRole)[1] == "v1.csv")
    fnode.child(1).setCheckState(0, QtCore.Qt.CheckState.Checked)
    assert ("v1.csv", "v1") in {it.data(graph_app.UserRole)
                                for it in (w.y_list.item(i) for i in range(w.y_list.count()))
                                if it.checkState() == QtCore.Qt.CheckState.Checked}
    # レイアウトプリセット4種（配置＋外観が両方変わる）→標準復帰
    w.resize(1280, 800)
    w._apply_layout_preset("labplot")   # データ+統計がタブ化・プレビュー表示
    assert (w.left_docks[3] in w.tabifiedDockWidgets(w.left_docks[0])
            or w.left_docks[0] in w.tabifiedDockWidgets(w.left_docks[3]))
    w._apply_layout_preset("veusz")     # ツールバーが左縦に移動
    assert w.toolBarArea(w.main_toolbar) == QtCore.Qt.ToolBarArea.LeftToolBarArea
    w._apply_layout_preset("kst")       # ファイルツリーがフロート小窓
    assert w.files_dock.isFloating() and w.format_dock.isHidden()
    w._apply_layout_preset("igor")      # 3枚カスケードフロート
    assert all(d.isFloating() for d in (w.files_dock, w.left_docks[1], w.format_dock))
    w._apply_layout_preset("standard")
    assert all(not d.isHidden() and not d.isFloating()
               for d in [*w.left_docks, w.format_dock])
    assert w.files_dock.isFloating()    # 読み込み済みファイルの既定は独立ウィンドウ
    assert not w.files_dock.isHidden()
    assert w.toolBarArea(w.main_toolbar) == QtCore.Qt.ToolBarArea.TopToolBarArea
    assert w._ui_style_name == "standard"
    # 内部の幅・高さが実際に変えられる（最小サイズ制約が復活していないこと）
    w.show()
    app = QtWidgets.QApplication.instance()
    w.resizeDocks([w.left_docks[0]], [150], QtCore.Qt.Orientation.Horizontal)
    app.processEvents()
    assert abs(w.left_docks[0].width() - 150) <= 30
    w.resizeDocks([w.format_dock], [160], QtCore.Qt.Orientation.Horizontal)
    app.processEvents()
    assert abs(w.format_dock.width() - 160) <= 30
    # ファイルウィンドウ（フロート）は自由にリサイズできる
    w.files_dock.resize(560, 700)
    app.processEvents()
    assert abs(w.files_dock.width() - 560) <= 10
    w.files_dock.resize(260, 320)
    app.processEvents()
    assert abs(w.files_dock.width() - 260) <= 10
    # UIスタイル単体切替: QSS・ツールバー・ツリー字下げが変わり、機能は生きている
    w._apply_ui_style("veusz")
    assert w.main_toolbar.iconSize().width() == 16 and w.explorer.indentation() == 14
    w.draw_graph()
    assert len(w.ax.get_lines()) >= 1
    w._apply_ui_style("standard")
    # 標準でも基準QSS（ボタン高さ統一）が入り、ツールバーは既定に戻る
    assert "min-height" in w.styleSheet() and w.main_toolbar.iconSize().width() == 24


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
