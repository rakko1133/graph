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
from matplotlib.backends.qt_compat import QtCore, QtGui, QtWidgets  # noqa: E402

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
    w.fft_btn.setChecked(False)   # 持続FFTを解除し、以降は時間ドメイン描画へ戻す

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


def test_fft_mode_is_persistent_frequency_domain():
    """FFT表示ONで全体が周波数ドメインへ切り替わり、再描画しても持続すること（単位変換のよう）。"""
    w = _make_app(_wave())
    w.chart_combo.setCurrentText("折れ線"); w.draw_graph()
    assert "周波数" not in w.ax.get_xlabel()          # 時間ドメイン
    # ON → 周波数ドメインへ全体切替（トグルが draw_graph を呼ぶ）
    w.fft_btn.setChecked(True)
    assert w._fft_mode_on() and "周波数" in w.ax.get_xlabel()
    # 再描画（設定変更を模す）してもFFTのまま＝持続
    w.draw_graph()
    assert "周波数" in w.ax.get_xlabel()
    # OFF → 時間ドメインへ戻る
    w.fft_btn.setChecked(False)
    assert "周波数" not in w.ax.get_xlabel()


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
    # レイアウトプリセット「標準」→ 既定配置へ戻る（◯◯風スキンは廃止済み）
    w.resize(1280, 800)
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
    # UIスタイルは標準のみ（着せ替えテーマは廃止）。基準QSS（ボタン高さ統一）が入る
    w._apply_ui_style("standard")
    w.draw_graph()
    assert len(w.ax.get_lines()) >= 1
    assert "min-height" in w.styleSheet() and w.main_toolbar.iconSize().width() == 24


def test_undo_redo():
    w = _make_app(_wave())
    for s in ("A", "B", "C"):
        w.title_edit.setText(s); w.draw_graph()
    w.undo()
    assert w.title_edit.text() == "B"
    w.redo()
    assert w.title_edit.text() == "C"


# ---------------- GUI改修の回帰 ----------------
def test_notification_bar_and_message_log():
    """告知が非モーダルの通知バーに出て、履歴に残ること。"""
    w = _make_app(_wave())
    w.notify("テスト通知", "info")
    assert not w.notify_bar.isHidden() and w.notify_bar.current_text() == "テスト通知"
    w.notify_bar.dismiss()
    assert w.notify_bar.isHidden()
    # エラーは自動で消えない（タイマーを動かさない＝残り続ける）
    w.notify("読めません", "error", "詳細テキスト")
    assert not w.notify_bar.isHidden()
    # 履歴に両方が積まれ、種別と詳細も保持される
    log = w._message_log
    assert [m["text"] for m in log[-2:]] == ["テスト通知", "読めません"]
    assert log[-1]["level"] == "error" and log[-1]["detail"] == "詳細テキスト"
    # ステータスバーの1行にも同じ文言が出る
    assert w.status.currentMessage() == "読めません"
    # 「先にファイルを追加」がモーダルでなく通知になった
    w2 = graph_app.GraphApp()
    w2.datasets.clear()
    w2.draw_graph()
    assert "ファイル" in w2.notify_bar.current_text()
    # 上限を超えた履歴は古いものから捨てられる
    for i in range(graph_app.MESSAGE_LOG_MAX + 20):
        w._log_message(f"m{i}")
    assert len(w._message_log) == graph_app.MESSAGE_LOG_MAX


def _make_app_wide(n, rows=20):
    """n 列のデータを読み込み、Y を一括チェックしたアプリを返す。

    1件ずつ setCheckState すると選択変更のたびに系列表を作り直すため、
    列数の2乗に比例して時間がかかる。ここではまとめて設定して1回だけ通知する。
    """
    df = pd.DataFrame({"時間": np.arange(float(rows))})
    for i in range(n):
        df[f"ch{i:03d}"] = np.arange(float(rows)) + i
    w = graph_app.GraphApp()
    w.datasets.clear(); w.file_list.clear(); w.y_list.clear()
    w.datasets["t.csv"] = df
    w.meta["t.csv"] = {"path": "t.csv", "enc": "utf-8", "delim": ","}
    w._add_file_item("t.csv"); w.file_list.setCurrentRow(0); w._refresh_columns()
    w.x_combo.setCurrentText("時間")
    w.y_list.blockSignals(True)
    for r in range(w.y_list.count()):
        it = w.y_list.item(r)
        on = it.data(graph_app.UserRole)[1] != "時間"
        it.setCheckState(QtCore.Qt.CheckState.Checked if on
                         else QtCore.Qt.CheckState.Unchecked)
    w.y_list.blockSignals(False)
    w._on_y_selection_changed()
    return w


def _y_item(w, col):
    """y_list から列名で項目を探す（並び順に依存しないため）。"""
    for r in range(w.y_list.count()):
        it = w.y_list.item(r)
        if it.data(graph_app.UserRole)[1] == col:
            return it
    raise AssertionError(f"{col} が y_list にない")


def _bar_checkboxes(w):
    return [w.series_bar_layout.itemAt(i).widget()
            for i in range(w.series_bar_layout.count())
            if isinstance(w.series_bar_layout.itemAt(i).widget(), QtWidgets.QCheckBox)]


def test_series_bar_cap_and_filter():
    """系列バーが上限で打ち切られ、絞り込みが効くこと。"""
    n = graph_app.SERIES_BAR_MAX + 25
    w = _make_app_wide(n)
    w.chart_combo.setCurrentText("折れ線")
    w._rebuild_series_bar("折れ線")
    assert len(_bar_checkboxes(w)) == graph_app.SERIES_BAR_MAX   # 無制限に生成しない
    assert not w.series_more_btn.isHidden()
    hidden = w.y_list.count() - graph_app.SERIES_BAR_MAX
    assert w.series_more_btn.text() == f"他{hidden}件…"
    # 絞り込むと該当だけが並ぶ
    w.series_filter.setText("ch00")
    names = [b.text() for b in _bar_checkboxes(w)]
    assert names and all(nm.startswith("ch00") for nm in names)
    w.series_filter.setText("")
    # チェック済みが先に並ぶ（描いている系列をすぐ切り替えられる）
    w.y_list.blockSignals(True)
    for r in range(w.y_list.count()):
        w.y_list.item(r).setCheckState(QtCore.Qt.CheckState.Unchecked)
    _y_item(w, f"ch{n - 1:03d}").setCheckState(QtCore.Qt.CheckState.Checked)
    w.y_list.blockSignals(False)
    w._rebuild_series_bar("折れ線")
    first = _bar_checkboxes(w)[0]
    assert first.text() == f"ch{n - 1:03d}" and first.isChecked()


def test_heavy_series_confirmation():
    """系列が多すぎる描画は確認を挟み、拒否すると描かないこと。"""
    n = graph_app.HEAVY_SERIES + 10
    w = _make_app_wide(n)
    orig = QtWidgets.QMessageBox.question
    QtWidgets.QMessageBox.question = staticmethod(
        lambda *a, **k: QtWidgets.QMessageBox.StandardButton.No)
    try:
        w.draw_graph()
        assert not w.ax.get_lines()            # 拒否したので描かれない
        assert "中止" in w.notify_bar.current_text()
    finally:
        QtWidgets.QMessageBox.question = orig
    w.draw_graph()                             # 承諾すると描く（以後は聞かれない）
    assert len(w.ax.get_lines()) >= n
    assert w._heavy_draw_ok is True


_CTRL = (QtWidgets.QAbstractButton, QtWidgets.QComboBox,
         QtWidgets.QLineEdit, QtWidgets.QAbstractSpinBox)


def _control_attrs(w):
    """アプリが保持しているコントロール属性名の集合。"""
    return {n for n in dir(w) if isinstance(getattr(w, n, None), _CTRL)}


def _visible_controls(w):
    """そのレベルで画面に出ているコントロールの数（表の中身は除く）。"""
    vis = w._visible_dock_names()
    n = 0
    for d in w._all_docks():
        if d.objectName() not in vis:
            continue
        for c in d.findChildren(QtWidgets.QWidget):
            if not isinstance(c, _CTRL) or c.isHidden():
                continue
            p, skip = c.parentWidget(), False
            while p is not None and p is not d:
                if isinstance(p, QtWidgets.QAbstractItemView) or p.isHidden():
                    skip = True
                    break
                p = p.parentWidget()
            if not skip:
                n += 1
    return n


def test_tabs_do_not_depend_on_each_other():
    """タブ間の相互依存が無く、共通サービスは HostMixin に集約されていること。"""
    hm = graph_app.HostMixin   # HostMixin はメイン graph_app.py に統合済み
    # タブ横断で使う土台サービスは HostMixin が持つ
    for name in ("series_xy", "analysis_xy_or_warn", "_analysis_xy",
                 "_xy_by_disp", "prepare_view_axes", "_tab_hook"):
        assert name in hm.__dict__, f"{name} が HostMixin に無い"
    # HostMixin 由来であることを実機で確認
    w = _make_app(_wave())
    for name in ("analysis_xy_or_warn", "_xy_by_disp"):
        owner = next(c.__name__ for c in type(w).__mro__ if name in c.__dict__)
        assert owner == "HostMixin", f"{name} の所有者が {owner}"


def test_draw_path_survives_missing_tab_hook():
    """タブ由来の描画フックが欠けても描画が落ちないこと（タブを外せる担保）。

    plotting はタブのメソッド名を直接呼ばず _tab_hook 経由にしたので、
    該当タブ（メソッド）が無い構成でも draw が例外を出さない。"""
    w = _make_app(_wave())
    # 欠けているフック名は default を返す（呼び出しは起きない）
    assert w._tab_hook("_no_such_overlay_xyz") is None
    assert w._tab_hook("_no_such_overlay_xyz", default=False) is False
    # 実在フックは通常どおり値を返す
    assert callable(getattr(w, "_draw_ds_annotations", None))
    # インスタンス側でフックを None に潰しても（＝タブ非搭載相当）draw は通る
    w._draw_ds_annotations = None
    w._draw_proto_overlay = None
    w._peak_markers = None
    w.chart_combo.setCurrentText("折れ線")
    w.draw_graph()
    assert len(w.ax.get_lines()) >= 1


def test_builtin_tabs_are_registered_plugins():
    """内蔵4タブがプラグインとして登録され、順序・レベルが従来どおりであること。"""
    import graph_app_common as C
    tabs = C.registered_tabs()
    assert [t.key for t in tabs] == ["data", "scope", "advanced", "datasci"]
    assert [t.min_level for t in tabs] == ["基本", "標準", "全部", "全部"]
    w = _make_app(_wave())
    assert [d.objectName() for d in w.left_docks] == \
        ["dock_data", "dock_scope", "dock_advanced", "dock_datasci"]
    # 表示レベルはプラグインの min_level から導出される（旧ハードコードと一致）
    w.set_ui_level("基本", announce=False)
    assert w._visible_dock_names() == {"dock_files", "dock_format", "dock_data"}
    w.set_ui_level("標準", announce=False)
    assert w._visible_dock_names() == {
        "dock_files", "dock_format", "dock_data", "dock_scope"}


def test_new_tab_can_be_added_by_plugin():
    """メインを触らず、プラグインを1つ登録するだけで新しいタブが増えること。"""
    import graph_app_common as C

    class _ProbeTab(C.TabPlugin):
        key, title, order, min_level = "probe_xyz", "9. 検証タブ", 90, "全部"

        def build(self, app):
            w = QtWidgets.QWidget()
            lay = QtWidgets.QVBoxLayout(w)
            b = QtWidgets.QPushButton("実行")
            # app（GraphApp）の既存メソッドをそのまま呼べる
            b.clicked.connect(lambda: app.notify("検証タブ実行"))
            self.button = b
            lay.addWidget(b)
            return w

    probe = _ProbeTab()
    C.register_tab(probe)
    try:
        w = graph_app.GraphApp()
        try:
            # 新タブがドックとして並び、末尾（order=90）に来る
            names = [d.objectName() for d in w.left_docks]
            assert "dock_probe_xyz" in names
            assert names[-1] == "dock_probe_xyz"
            # min_level=全部 なので基本では隠れ、全部で出る
            w.set_ui_level("基本", announce=False)
            assert "dock_probe_xyz" not in w._visible_dock_names()
            w.set_ui_level("全部", announce=False)
            assert "dock_probe_xyz" in w._visible_dock_names()
            # build に渡された app は本物の GraphApp（notify が呼べる）
            probe.button.click()
            assert "検証タブ" in w.notify_bar.current_text()
        finally:
            w.close()
    finally:
        # レジストリを元に戻す（他テストへ影響させない）
        C._TAB_REGISTRY[:] = [p for p in C._TAB_REGISTRY if p.key != "probe_xyz"]


def test_plugin_can_draw_overlay_and_persist_settings():
    """コアを触らず、プラグインが (1) メイングラフへ描画でき (2) 設定を保存/復元できること。"""
    import graph_app_common as C

    class _OverlayTab(C.TabPlugin):
        key, title, order, min_level = "ov_probe", "9. 注記検証", 91, "全部"

        def build(self, app):
            w = QtWidgets.QWidget()
            self.spin = QtWidgets.QSpinBox(); self.spin.setValue(3)
            QtWidgets.QVBoxLayout(w).addWidget(self.spin)
            return w

        def draw_overlay(self, app, ax):          # コア無改変の描画差し込み口
            for i in range(self.spin.value()):
                ax.axvline(i, color="magenta", linestyle=":", label="_ovprobe")

        def collect_config(self, app):
            return {"n": self.spin.value()}

        def apply_config(self, app, cfg):
            self.spin.setValue(int(cfg.get("n", 3)))

    probe = _OverlayTab()
    C.register_tab(probe)
    try:
        w = _make_app(_wave())
        try:
            probe.spin.setValue(4)
            w.draw_graph()
            # (1) プラグインの draw_overlay がメイン軸へ描いた（縦線4本）
            vlines = [ln for ln in w.ax.get_lines() if ln.get_label() == "_ovprobe"]
            assert len(vlines) == 4
            # (2) タブ設定が config に載る（key 名前空間の下）
            cfg = w._collect_config()
            assert cfg["tabs"]["ov_probe"] == {"n": 4}
        finally:
            w.close()
        # 別インスタンスへ config を適用するとタブ設定が復元される
        w2 = graph_app.GraphApp()
        try:
            assert probe.spin.value() == 3        # build 直後の既定
            w2._apply_config(cfg, load_files=False)
            assert probe.spin.value() == 4        # apply_config で復元
        finally:
            w2.close()
    finally:
        C._TAB_REGISTRY[:] = [p for p in C._TAB_REGISTRY if p.key != "ov_probe"]


def test_ui_level_hides_without_destroying():
    """表示レベルは setVisible だけで、ウィジェットも設定も失わないこと。"""
    w = _make_app(_wave())
    assert w.DEFAULT_UI_LEVEL == "全部"        # 通常版の既定は従来どおり
    attrs_full = _control_attrs(w)
    cfg_full = set(w._collect_config().keys())
    counts = {}
    for lv in w.UI_LEVELS:
        w.set_ui_level(lv, announce=False)
        assert w.ui_level() == lv
        counts[lv] = _visible_controls(w)
        # ウィジェットは1つも消えない＝設定の保存・復元・テストの属性参照が生きる
        assert _control_attrs(w) == attrs_full, f"{lv} でウィジェット属性が変化した"
        assert set(w._collect_config().keys()) == cfg_full, f"{lv} で設定キーが変化した"
    # 実際に段階的に減っている
    assert counts["基本"] < counts["標準"] < counts["全部"]
    # 「全部」は従来と同じ＝どのドックも隠れていない
    w.set_ui_level("全部", announce=False)
    assert w._visible_dock_names() == {d.objectName() for d in w._all_docks()}


def test_hidden_settings_are_still_reachable_by_name():
    """基本レベルで隠れている設定も、名前で検索すれば必ず出てくること。

    これが「隠す」と「機能を落とす」を分ける唯一の担保なので、機械的に確かめる。"""
    w = _make_app(_wave())
    w.set_ui_level("基本", announce=False)
    hidden = [e for e in w._setting_index if not e["widget"].isVisibleTo(w)]
    assert hidden, "基本レベルなのに隠れている設定が無い＝レベルが効いていない"
    for entry in hidden[:25]:                  # 代表を確認（全件は時間がかかる）
        w.set_ui_level("基本", announce=False)
        got = w._jump_to_setting(entry["key"])
        assert got is not None, f"{entry['key']} を名前で呼び出せない"
        assert got["widget"] is entry["widget"]
        assert entry["widget"].isVisibleTo(w), f"{entry['key']} が呼び出しても出てこない"
    # 呼び戻しでレベルが自動的に上がっている
    assert w.ui_level() != "基本"


def test_layout_preset_promotes_level():
    """レイアウトプリセットは表示レベルと競合するので「全部」へ上げること。

    上げないと、プリセットが出したパネルをレベルが隠し返して
    「選んだのに何も起きない」状態になる。"""
    w = _make_app(_wave())
    w.set_ui_level("基本", announce=False)
    w._apply_layout_preset("analysis")
    assert w.ui_level() == "全部"
    assert not w.left_docks[1].isHidden()      # オシロ/解析が実際に出ている
    w._apply_layout_preset("standard")
    assert w.ui_level() == "全部"


def test_simple_edition_is_same_app_with_fewer_controls():
    """シンプル版が同じ機能・同じ設定で、表示量だけ絞られていること。"""
    import graph_app_simple
    QtCore.QSettings("graph-tool", "GraphApp").clear()
    s = graph_app_simple.SimpleGraphApp()
    try:
        assert isinstance(s, graph_app.GraphApp)       # 別実装ではない
        assert s.ui_level() == "基本"
        assert "シンプル" in s.windowTitle()
        full = _make_app(_wave())
        full.set_ui_level("全部", announce=False)
        # 保持するウィジェット・設定キー・解析メソッドは通常版と完全に同一
        assert _control_attrs(s) == _control_attrs(full)
        assert set(s._collect_config().keys()) == set(full._collect_config().keys())
        for m in ("run_analysis", "show_fft", "decode_protocol", "run_regression",
                  "export_excel_report", "batch_export", "show_waterfall"):
            assert callable(getattr(s, m, None)), f"{m} がシンプル版に無い"
        # 画面に出ている量だけが違う
        assert _visible_controls(s) < _visible_controls(full)
        # その場で全機能を出せる（再起動不要）
        s.set_ui_level("全部", announce=False)
        assert _visible_controls(s) == _visible_controls(full)
    finally:
        s.close()
        QtCore.QSettings("graph-tool", "GraphApp").clear()


def test_editions_remember_their_level_separately():
    """通常版とシンプル版が表示レベルを取り合わないこと。

    保存キーを共有していると、通常版を「全部」で使った直後にシンプル版を
    開いても「全部」で立ち上がり、シンプル版がシンプルでなくなる。"""
    import graph_app_simple
    QtCore.QSettings("graph-tool", "GraphApp").clear()
    try:
        assert graph_app.GraphApp.UI_LEVEL_KEY != graph_app_simple.SimpleGraphApp.UI_LEVEL_KEY
        full = graph_app.GraphApp()
        full.set_ui_level("全部", announce=False)
        full._save_ui_state()
        full.close()
        simple = graph_app_simple.SimpleGraphApp()
        assert simple.ui_level() == "基本"        # 通常版の設定に引きずられない
        simple.set_ui_level("標準", announce=False)
        simple._save_ui_state()
        simple.close()
        again_full = graph_app.GraphApp()
        assert again_full.ui_level() == "全部"    # 通常版は自分の設定を保つ
        again_full.close()
        again_simple = graph_app_simple.SimpleGraphApp()
        assert again_simple.ui_level() == "標準"  # シンプル版も自分の設定を覚える
        again_simple.close()
    finally:
        QtCore.QSettings("graph-tool", "GraphApp").clear()


def test_reload_keeps_generated_datasets():
    """実体ファイルの無いデータに再読込しても消えないこと。

    以前は datasets から先に取り除いてから読み直そうとしていたため、
    貼り付け・数学チャンネル・フィット・PCA のデータが黙って消えていた。"""
    w = _make_app(_wave())
    w.datasets["Math: A+B"] = pd.DataFrame({"時間[s]": [0, 1], "A+B": [1.0, 2.0]})
    w.meta["Math: A+B"] = {"path": "Math: A+B", "enc": "-", "delim": "-"}
    w._add_file_item("Math: A+B")
    w._refresh_columns()
    for i in range(w.file_list.count()):
        if w.file_list.item(i).text() == "Math: A+B":
            w.file_list.setCurrentRow(i)
            break
    w.reload_current()
    assert "Math: A+B" in w.datasets, "生成データが再読込で消えた"
    assert w._find_file_item("Math: A+B") is not None
    assert "再読込できません" in w.notify_bar.current_text()


def test_register_dataset_is_shared():
    """生成データの登録が共通口を通り、名前の重複も避けられること。"""
    w = _make_app(_wave())
    df = pd.DataFrame({"時間[s]": [0, 1], "値": [1.0, 2.0]})
    a = w.register_dataset("Math: test", df, status="作成: {label}")
    b = w.register_dataset("Math: test", df)
    assert a == "Math: test" and b == "Math: test (2)"     # 重複を避ける
    for label in (a, b):
        assert label in w.datasets
        assert w.meta[label]["path"] == label              # 実体なしの印
        assert w._find_file_item(label) is not None
    assert "作成: Math: test" in [m["text"] for m in w._message_log]


def test_color_buttons_share_one_implementation():
    """3つの色ボタンが同じ実装を通り、選択・自動戻しが効くこと。"""
    w = _make_app(_wave())
    for kind, attr, btn_name in (("bg", "bg_color", "bg_btn"),
                                 ("trend", "trend_color", "trend_color_btn"),
                                 ("fill", "fill_color", "fill_color_btn")):
        setattr(w, attr, "#123456")
        w.reset_color(kind)
        assert getattr(w, attr) == ""
        assert "自動" in getattr(w, btn_name).text()
        assert getattr(w, btn_name).styleSheet() == ""
    # 旧名（設定復元・プリセットから呼ばれる）も生きている
    for legacy in ("_reset_bg_color", "_reset_trend_color", "_reset_fill_color"):
        getattr(w, legacy)()


def test_extension_list_has_one_source():
    """対応拡張子の定義が1つで、ダイアログのフィルタと食い違わないこと。"""
    import data_loader
    w = _make_app(_wave())
    assert w._ACCEPT_EXTS is data_loader.ACCEPT_EXTS
    filt = data_loader.file_dialog_filter()
    for ext in data_loader.ACCEPT_EXTS:
        assert "*" + ext in filt, f"{ext} がファイルダイアログのフィルタに無い"
    assert "*.net" in filt                      # 以前ここだけ抜けていた
    assert set(data_loader.TABLE_EXTS) == set(data_loader.ACCEPT_EXTS) - set(
        data_loader.RUNNABLE_EXTS)


def test_dark_background_check_is_shared():
    """地色の明暗判定が1本で、グラフ側とGUI側で食い違わないこと。"""
    import plotter
    import plotter_draw
    assert not hasattr(plotter_draw, "_is_dark")     # 重複実装を消した
    assert plotter.is_dark_bg("#000000") and not plotter.is_dark_bg("#ffffff")
    assert plotter.is_dark_bg("不正な色名")          # 解釈できない色は暗い扱い（従来どおり）
    # 輝度0.45〜0.5 の中間色でも、グラフの格子とGUIの文字色が同じ判断になる
    mid = "#787878"
    w = _make_app(_wave())
    w.bg_color = mid
    w.draw_graph()
    assert plotter.is_dark_bg(mid) == (w.ax.get_xticklabels()[0].get_color() != "black")


def test_command_palette_opens_with_all_commands():
    """コマンドパレットが開き、登録が全部 QAction であること。

    QAction 以外を1件でも登録すると show_command_palette の isEnabled() が
    AttributeError になり、Ctrl+Shift+P が丸ごと使えなくなる（実際に起きた）。"""
    w = _make_app(_wave())
    assert len(w._all_actions) >= 40
    assert all(isinstance(a, QtGui.QAction) for _k, a in w._all_actions)
    w.show_command_palette()                     # 例外を投げないこと
    lst = w._palette_dlg.findChild(QtWidgets.QListWidget)
    assert lst is not None and lst.count() == len(w._all_actions)
    # QAction 以外は登録時に弾かれ、候補を汚さない
    before = len(w._all_actions)
    w._palette_register("表示", "壊れた登録", lambda: None)
    assert len(w._all_actions) == before


def test_setting_search_jumps_to_control():
    """設定検索が索引を作り、該当コントロールへ移動できること。"""
    w = _make_app(_wave())
    index = w._setting_index
    assert len(index) > 40                     # 全パネルから拾えている
    keys = [e["key"] for e in index]
    assert any("凡例" in k for k in keys) and any("描画バー" in k for k in keys)
    assert len(set(keys)) == len(keys)          # 候補一覧で選び分けられる
    # ラベルが「:」だけの入力欄も索引に載る（accessibleName を優先するため）
    indexed = {id(e["widget"]) for e in index}
    for attr in ("xmin", "xmax", "ymin", "ymax", "aspect_w", "aspect_h",
                 "mask_upper", "mask_lower", "bins_spin", "legend_loc"):
        wdg = getattr(w, attr, None)
        assert wdg is None or id(wdg) in indexed, f"{attr} が設定検索から漏れている"
    assert w._find_setting("縦横比 縦") is not None
    # 折りたたまれたセクションの中の項目でも、開いて選択状態にする
    box = w._fmt_sections["legend"]
    box.set_expanded(False)
    entry = w._jump_to_setting("凡例")
    assert entry is not None and box.is_expanded()
    assert w.focusWidget() is entry["widget"] or entry["widget"].hasFocus()
    # 見つからない語は通知で知らせる（黙って何も起きない、をなくす）
    assert w._jump_to_setting("存在しない設定名") is None
    assert "見つかりません" in w.notify_bar.current_text()


def test_accessibility_names_and_buddies():
    """アクセシブル名・buddy・キャンバスのフォーカスが設定されていること。"""
    w = _make_app(_wave())
    named = [e for e in w._setting_index if e["widget"].accessibleName()]
    assert len(named) == len(w._setting_index)          # 全項目に名前が付く
    buddied = [e for e in w._setting_index
               if e.get("label") is not None and e["label"].buddy() is not None]
    assert buddied                                       # ラベルと入力欄が結ばれている
    assert w.canvas.focusPolicy() == QtCore.Qt.FocusPolicy.StrongFocus
    assert w.canvas.accessibleName() == "グラフ"
    assert w.explorer.accessibleName()
    # 主要ボタンにはAltショートカットが付く
    draw_btn = next(e["widget"] for e in w._setting_index
                    if e["name"].startswith("グラフを描画"))
    assert "&" in draw_btn.text()


def test_theme_tokens_follow_palette():
    """QSSに色が直書きされておらず、ダークパレットでも文字色が反転すること。"""
    for style in graph_app.GraphApp._UI_STYLES.values():
        assert "background:white" not in style["qss"]
        assert "#fcfcfc" not in style["qss"] and "#ececec" not in style["qss"]
    light = graph_app.palette_tokens(QtGui.QPalette(QtGui.QColor("#ffffff")))
    dark = graph_app.palette_tokens(QtGui.QPalette(QtGui.QColor("#202020")))
    assert graph_app.is_dark_theme(QtGui.QPalette(QtGui.QColor("#202020")))
    assert not graph_app.is_dark_theme(QtGui.QPalette(QtGui.QColor("#ffffff")))
    assert light["bg"] != dark["bg"] and light["fg"] != dark["fg"]
    # render_qss は $トークン（$fg/$bg）を実値へ展開し、$ を残さない
    expanded = graph_app.render_qss("QLabel { color: $fg; background: $bg; }")
    assert "$" not in expanded and "color:" in expanded
    # スタイル適用とパレット変更イベントで例外が出ない（標準QSSにトークンは無い）
    w = _make_app(_wave())
    w._apply_ui_style("standard")
    assert "$" not in w.styleSheet()
    # パレット変更イベントでスタイルを作り直す（例外を出さない）
    w._on_palette_changed(QtCore.QEvent.Type.PaletteChange)


def test_ui_style_survives_event_loop():
    """標準スタイルがイベントループやパレット変更で巻き戻らないこと。

    setStyleSheet はその場で PaletteChange を起こす。テーマ追従が
    「1つ前のスタイル名」を捕まえて後から再適用すると外観が静かに戻る
    バグがあった（◯◯風スキンは廃止したが、この不変条件は標準で担保する）。"""
    w = _make_app(_wave())
    app = QtWidgets.QApplication.instance()
    w._apply_ui_style("standard")
    app.processEvents()
    app.processEvents()
    assert w._ui_style_name == "standard"
    # OS のテーマ変更で呼ばれる経路は、今のスタイルを保つ
    w._on_palette_changed(QtCore.QEvent.Type.PaletteChange)
    app.processEvents()
    app.processEvents()
    assert w._ui_style_name == "standard"


def test_dark_palette_makes_graph_readable():
    """ダークパレットで地色・目盛り・凡例枠まで反転し、対比が保たれること。"""
    before = _app.palette()
    pal = QtGui.QPalette()
    for role, col in ((QtGui.QPalette.ColorRole.Window, "#1e1e1e"),
                      (QtGui.QPalette.ColorRole.Base, "#252526"),
                      (QtGui.QPalette.ColorRole.Button, "#333333"),
                      (QtGui.QPalette.ColorRole.WindowText, "#e6e6e6"),
                      (QtGui.QPalette.ColorRole.Text, "#e6e6e6"),
                      (QtGui.QPalette.ColorRole.Highlight, "#0a84ff")):
        pal.setColor(role, QtGui.QColor(col))
    try:
        _app.setPalette(pal)
        w = _make_app(_wave())
        w.legend_check.setChecked(True)
        w.draw_graph()
        face = w.fig.get_facecolor()
        assert max(face[:3]) < 0.4                    # 地色が暗い
        assert w.ax.get_xticklabels()[0].get_color() == "#e6e6e6"
        legend = w.ax.get_legend()
        assert legend is not None
        lf = legend.get_frame().get_facecolor()
        assert max(lf[:3]) < 0.4                      # 凡例の枠も暗い＝白抜けしない
        assert all(t.get_color() == "#e6e6e6" for t in legend.get_texts())
        # 背景色を明示指定したときはユーザーの指定が優先される
        w.bg_color = "#ffffff"
        w.draw_graph()
        assert min(w.fig.get_facecolor()[:3]) > 0.9
        assert w.ax.get_xticklabels()[0].get_color() == "black"
    finally:
        _app.setPalette(before)


def test_bulk_check_defers_heavy_rebuild():
    """列を続けてチェックしても、重い作り直しは最後に1回だけになること。"""
    w = _make_app_wide(20)
    calls = []
    orig = w._rebuild_style_table
    w._rebuild_style_table = lambda *a, **k: (calls.append(1), orig(*a, **k))[1]
    # 10列を1つずつ外す（＝ツリーでファイル単位に外したときと同じ流れ）
    targets = [_y_item(w, f"ch{i:03d}") for i in range(10)]
    for it in targets:
        it.setCheckState(QtCore.Qt.CheckState.Unchecked)
    # 見た目（ツリーのチェック）はその場で追従している
    assert all(nd.checkState(0) == QtCore.Qt.CheckState.Unchecked
               for nd in [w.explorer.topLevelItem(0).child(i)
                          for i in range(w.explorer.topLevelItem(0).childCount())
                          if w.explorer.topLevelItem(0).child(i).text(0).startswith("ch00")])
    assert not calls                       # 途中では重い作り直しをしていない
    w._ysel_timer.stop(); w._apply_y_selection_deferred()   # まとめて1回
    assert len(calls) == 1
    assert w.style_table.rowCount() == 10


def test_async_load_keeps_ui_responsive():
    """大きめの読み込みがワーカースレッドへ回り、キャンセルできること。"""
    import tempfile
    d = os.path.join(tempfile.gettempdir(), "gtest_async")
    os.makedirs(d, exist_ok=True)
    big = pd.DataFrame({"時間": np.arange(120000.0),
                        "値": np.sin(np.arange(120000.0) / 100)})
    paths = []
    for i in range(2):
        p = os.path.join(d, f"big{i}.csv")
        big.to_csv(p, index=False)
        paths.append(p)
    w = graph_app.GraphApp()
    w.datasets.clear(); w.file_list.clear(); w.y_list.clear()
    thread = w._load_files_async(paths)
    assert thread is not None                 # 閾値超えはスレッドで読む
    assert not w.progress_strip.isHidden()
    assert w.wait_for_loads(60000)
    assert len(w.datasets) == 2 and w.progress_strip.isHidden()
    assert w._load_thread is None
    # 小さいファイルはスレッドを起こさない（完了タイミングが素直）
    small = os.path.join(d, "small.csv")
    pd.DataFrame({"時間": [0, 1], "値": [1.0, 2.0]}).to_csv(small, index=False)
    w2 = graph_app.GraphApp()
    w2.datasets.clear(); w2.file_list.clear(); w2.y_list.clear()
    assert w2._load_files_async([small]) is None
    assert len(w2.datasets) == 1              # 呼び出し直後に読み終わっている
    # 終了時にワーカーを止める経路が例外を出さない
    w._stop_background_tasks()


def test_session_restore_skips_huge_selection():
    """前回選択が多すぎるとき、起動時の自動描画を省いて固まらないこと。"""
    n = graph_app.HEAVY_SERIES + 5
    df = pd.DataFrame({"時間": np.arange(10.0)})
    for i in range(n):
        df[f"ch{i:03d}"] = np.arange(10.0) + i
    w = _make_app(df)
    w._has_drawn = False
    w.ax.clear()
    cfg = w._collect_config()
    orig = config_io.load_last_session
    config_io.load_last_session = lambda: cfg
    try:
        restored = w._try_restore_session()
    finally:
        config_io.load_last_session = orig
    assert restored is True
    assert not w.ax.get_lines()                       # 自動描画していない
    assert "自動描画を省略" in w.notify_bar.current_text()


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
