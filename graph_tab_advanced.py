# -*- coding: utf-8 -*-
"""AdvancedMixin: GraphApp から分離した AdvancedMixin 群（挙動は本体と同一）。"""
from graph_app_common import *  # noqa: F401,F403


class AdvancedMixin:
    # ------------------------------------------------------------ 高度解析

    def _on_math_op_change(self, op):
        binary = op in mathchan.BINARY_OPS
        self.math_b.setEnabled(binary); self.math_b_label.setEnabled(binary)
        needs_param = op in ("移動平均", "ローパス(RC)",
                             "ローパス(Butterworth)", "ハイパス(Butterworth)")
        self.math_param.setEnabled(needs_param); self.math_param_label.setEnabled(needs_param)

    def create_math_channel(self):
        op = self.math_op.currentText()
        ta, ya = self._xy_by_disp(self.math_a.currentText())
        if ta is None:
            self.notify("演算対象Aをデータタブで選択してください。", "warn")
            return
        try:
            if op in mathchan.BINARY_OPS:
                tb, yb = self._xy_by_disp(self.math_b.currentText())
                if tb is None:
                    self.notify("演算対象Bを選択してください。", "warn")
                    return
                x, r = mathchan.binary(ta, ya, tb, yb, op)
            else:
                param = plotter.parse_eng(self.math_param.text(), None)
                x, r = mathchan.unary(ta, ya, op, param)
        except Exception as e:  # noqa: BLE001
            QtWidgets.QMessageBox.critical(self, "演算エラー", str(e)); return
        import pandas as pd
        col = f"{op}"
        self.register_dataset(f"Math: {op}",
                              pd.DataFrame({"時間[s]": x, col: r}),
                              status=f"数学チャンネルを作成: {{label}} ▸ {col}")

    def create_math_expr(self):
        """任意数式（A,B,VAR1,VAR2,t と許可関数）で新チャンネルを作成。"""
        import numpy as np
        import pandas as pd
        expr = self.math_expr.text().strip()
        if not expr:
            self.notify("数式を入力してください。", "warn")
            return
        ta, ya = self._xy_by_disp(self.math_a.currentText())
        if ta is None:
            self.notify("変数Aの系列をデータタブで選択してください。", "warn")
            return
        variables = {"A": ya, "t": ta,
                     "VAR1": plotter.parse_eng(self.math_var1.text(), 0.0) or 0.0,
                     "VAR2": plotter.parse_eng(self.math_var2.text(), 0.0) or 0.0}
        tb, yb = self._xy_by_disp(self.math_b.currentText())
        if tb is not None and yb is not None:
            variables["B"] = yb if len(yb) == len(ya) else np.interp(ta, tb, yb)
        try:
            r = mathchan.eval_expr(expr, variables)
            r = np.broadcast_to(np.asarray(r, dtype=float), ya.shape).astype(float)
        except Exception as e:  # noqa: BLE001
            QtWidgets.QMessageBox.critical(self, "数式エラー", str(e))
            return
        self.register_dataset(f"Expr: {expr[:24]}",
                              pd.DataFrame({"時間[s]": ta, "結果": r}),
                              status="数式チャンネルを作成: {label}")

    def show_param_stats(self):
        """解析対象チャンネルのサイクル統計表＋パラメータ間演算を別ウィンドウで表示。"""
        import numpy as np
        got = self.analysis_xy_or_warn()
        if got is None:
            return
        t, y, label = got
        yv = np.asarray(y, float)
        self._show_param_stats_window(label, analysis.cycle_statistics(t, yv),
                                      analysis.measurements(t, yv))

    def _show_param_stats_window(self, label, stats, meas):
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle(f"パラメータ統計: {label}")
        dlg.resize(700, 560)
        lay = QtWidgets.QVBoxLayout(dlg)
        no_edit = QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers

        lay.addWidget(QtWidgets.QLabel("■ サイクル統計（周期ごとに測り、平均/最大/最小/σ で集計）"))
        tb = QtWidgets.QTableWidget(len(stats), 6)
        tb.setEditTriggers(no_edit)
        tb.setHorizontalHeaderLabels(["パラメータ", "平均", "最大", "最小", "σ", "数"])
        for r, (pname, s) in enumerate(stats.items()):
            tb.setItem(r, 0, QtWidgets.QTableWidgetItem(str(pname)))
            for c, k in enumerate(["mean", "max", "min", "std"], start=1):
                v = s.get(k)
                tb.setItem(r, c, QtWidgets.QTableWidgetItem("-" if v is None else f"{v:.5g}"))
            tb.setItem(r, 5, QtWidgets.QTableWidgetItem(str(s.get("count", 0))))
        tb.resizeColumnsToContents()
        lay.addWidget(tb)

        lay.addWidget(QtWidgets.QLabel("■ パラメータ間演算（測定値どうしを四則）"))
        vals = {m["name"]: m["value"] for m in meas if m["value"] is not None}
        names = list(vals.keys())
        prow = QtWidgets.QHBoxLayout()
        ca = QtWidgets.QComboBox(); ca.addItems(names)
        op = QtWidgets.QComboBox(); op.addItems(["+", "-", "×", "÷"])
        cb = QtWidgets.QComboBox(); cb.addItems(names)
        out = QtWidgets.QLabel("= ?")

        def compute():
            a = vals.get(ca.currentText()); b = vals.get(cb.currentText())
            o = op.currentText()
            try:
                r = {"+": a + b, "-": a - b, "×": a * b,
                     "÷": (a / b if b else float("nan"))}[o]
                out.setText(f"= {r:.6g}")
            except Exception:  # noqa: BLE001
                out.setText("= -")
        bcalc = QtWidgets.QPushButton("計算"); bcalc.clicked.connect(compute)
        prow.addWidget(ca); prow.addWidget(op); prow.addWidget(cb)
        prow.addWidget(bcalc); prow.addWidget(out, 1)
        lay.addLayout(prow)
        bclose = QtWidgets.QPushButton("閉じる"); bclose.clicked.connect(dlg.close)
        lay.addWidget(bclose)
        self._param_stats_window = dlg
        dlg.show()

    def compute_fft_metrics(self):
        import numpy as np
        got = self.analysis_xy_or_warn()
        if got is None:
            return
        t, y, label = got
        win = self.fft_window.currentText()
        yv = np.asarray(y, float)
        m = analysis.spectrum_metrics(t, yv, window=win)
        rows = [
            ("基本波 f0", m.get("f0"), "Hz"),
            ("THD", m.get("THD_pct"), "%"),
            ("THD", m.get("THD_dB"), "dB"),
            ("SNR", m.get("SNR_dB"), "dB"),
            ("SINAD", m.get("SINAD_dB"), "dB"),
            ("ENOB", m.get("ENOB_bits"), "bit"),
            ("SFDR", m.get("SFDR_dB"), "dB"),
            ("占有帯域幅(99%)", analysis.occupied_bandwidth(t, yv, window=win), "Hz"),
            ("チャネル電力(全)", analysis.channel_power(t, yv, window=win), "V²"),
        ]
        for h in analysis.harmonic_search(t, yv, n_harm=5, window=win):
            rows.append((f"第{h['harmonic']}高調波", h["frequency"], "Hz"))
        self.fft_metrics.setRowCount(len(rows))
        for r, (name, val, unit) in enumerate(rows):
            self.fft_metrics.setItem(r, 0, QtWidgets.QTableWidgetItem(name))
            txt = "-" if val is None else f"{val:.4g} {unit}"
            self.fft_metrics.setItem(r, 1, QtWidgets.QTableWidgetItem(txt))
        self._set_status(f"スペクトル指標を計算: {label}")

    def show_spectrogram(self):
        import numpy as np
        got = self.analysis_xy_or_warn()
        if got is None:
            return
        t, y, label = got
        f, tt, S = analysis.spectrogram(t, np.asarray(y, float),
                                        window=self.fft_window.currentText())
        if S is None:
            self.notify("計算できませんでした。", "warn")
            return
        self.prepare_view_axes()
        mesh = self.ax.pcolormesh(tt, f, S, shading="auto", cmap="viridis")
        self.ax.set_xlabel("時間 [s]"); self.ax.set_ylabel("周波数 [Hz]")
        self.ax.set_title(f"スペクトログラム: {label}")
        try:
            self.fig.colorbar(mesh, ax=self.ax, label="dB")
        except Exception:
            applog.get_logger().debug("show_spectrogram: 無視した例外", exc_info=True)
        self._apply_aspect()   # 縦横比の設定をスペクトログラムにも適用
        try:
            self.fig.tight_layout()
        except Exception:
            applog.get_logger().debug("show_spectrogram: 無視した例外", exc_info=True)
        self.canvas.draw()
        self._has_drawn = False  # カラーバー付き特殊表示。次のdrawで作り直す
        self._set_status(f"スペクトログラム表示: {label}")

    def show_waterfall(self):
        """FFTウォーターフォール: STFTの時間スライスを3Dに重ねて周波数変化を見る。"""
        import numpy as np
        got = self.analysis_xy_or_warn()
        if got is None:
            return
        t, y, label = got
        f, tt, S = analysis.spectrogram(t, np.asarray(y, float),
                                        window=self.fft_window.currentText())
        if S is None:
            self.notify("計算できませんでした。", "warn")
            return
        self.prepare_view_axes(three_d=True, white_bg=False)
        from matplotlib import cm
        n = S.shape[1]
        step = max(1, n // 60)   # スライスは最大60本（視認性と速度のバランス）
        f = np.asarray(f, float)
        for i in range(0, n, step):
            self.ax.plot(f, np.full_like(f, tt[i]), S[:, i], lw=0.8,
                         color=cm.viridis(i / max(n - 1, 1)))
        self.ax.set_xlabel("周波数 [Hz]")
        self.ax.set_ylabel("時間 [s]")
        self.ax.set_zlabel("振幅 [dB]")
        self.ax.set_title(f"FFTウォーターフォール: {label}")
        try:
            self.ax.view_init(elev=self.elev_spin.value(), azim=self.azim_spin.value())
        except Exception:
            applog.get_logger().debug("show_waterfall: 無視した例外", exc_info=True)
        try:
            self.fig.tight_layout()
        except Exception:
            applog.get_logger().debug("show_waterfall: 無視した例外", exc_info=True)
        self.canvas.draw()
        self._has_drawn = False  # 特殊表示。次の「グラフを描画」で通常表示に戻る
        self._set_status(f"FFTウォーターフォール表示: {label}（{(n + step - 1) // step}スライス・"
                         "ドラッグで回転）")

    def run_mask_test(self):
        import numpy as np
        got = self.analysis_xy_or_warn()
        if got is None:
            return
        t, y, label = got
        up = plotter.parse_eng(self.mask_upper.text(), None)
        lo = plotter.parse_eng(self.mask_lower.text(), None)
        if up is None and lo is None:
            self.notify("上限または下限を入力してください。", "warn")
            return
        res = advanced.mask_test(t, np.asarray(y, float), upper=up, lower=lo)
        # マスク線と違反点を重畳（現在のグラフに重ねる。3Dの上には重ねない）
        self.draw_graph()
        if getattr(self.ax, "name", None) != "3d":
            if up is not None:
                self.ax.axhline(up, color="#d00", ls="--", lw=0.8)
            if lo is not None:
                self.ax.axhline(lo, color="#d00", ls="--", lw=0.8)
            if res["violations"]:
                vt = res["violation_times"]
                yv = np.asarray(y, float)[res["mask"]]
                self.ax.plot(vt, yv, ".", color="#d00", ms=3)
            self.canvas.draw()
        verdict = "PASS ✅" if res["passed"] else f"FAIL ❌（{res['violations']}点 超過）"
        self.adv_result.setText(f"マスク判定: {verdict}")
        self._set_status(f"マスク判定 {label}: {verdict}")

    def show_eye_diagram(self):
        import numpy as np
        got = self.analysis_xy_or_warn()
        if got is None:
            return
        t, y, label = got
        val = plotter.parse_eng(self.eye_rate.text(), 1e6)
        # シンボルレート[Hz] と解釈（>1 ならレート、<1 なら周期[s]とみなす）
        sym_period = (1.0 / val) if val and val > 1 else (val or 1e-6)
        phase, yy = advanced.eye_diagram(t, np.asarray(y, float), sym_period, n_ui=2)
        self.prepare_view_axes()
        self.ax.plot(phase * 1e6, yy, ".", ms=0.5, alpha=0.3, color="#1f77b4")
        self.ax.set_xlabel("UI内時間 [µs]"); self.ax.set_ylabel("電圧")
        self.ax.set_title(f"アイダイアグラム: {label}")
        self.ax.grid(True, alpha=0.3)
        em = advanced.eye_measurements(t, np.asarray(y, float), sym_period)
        if em:
            self.ax.axhline(em["level1"], color="#2ca02c", ls=":", lw=0.9)
            self.ax.axhline(em["level0"], color="#2ca02c", ls=":", lw=0.9)

            def _g(k):
                v = em.get(k)
                return float("nan") if v is None else v
            self.adv_result.setText(
                "アイ測定: 振幅={:.4g} 高さ={:.4g} 幅={:.4g}µs Q={:.3g} "
                "ER={:.3g}dB ジッタpp={:.3g}ns".format(
                    _g("eye_amplitude"), _g("eye_height"), _g("eye_width") * 1e6,
                    _g("q_factor"), _g("extinction_ratio_db"), _g("jitter_pp") * 1e9))
        try:
            self.fig.tight_layout()
        except Exception:
            applog.get_logger().debug("show_eye_diagram: 無視した例外", exc_info=True)
        self.canvas.draw()
        self._has_drawn = False
        self._set_status(f"アイダイアグラム表示: {label}")

    def run_jitter(self):
        import numpy as np
        got = self.analysis_xy_or_warn()
        if got is None:
            return
        t, y, label = got
        jr = advanced.jitter_tie(t, np.asarray(y, float))
        if not jr:
            self.notify("エッジが不足し計算できませんでした。", "warn")
            return
        msg = (f"ジッタ: RMS={plotter.format_eng(jr['rms'])}s  "
               f"pp={plotter.format_eng(jr['pp'])}s  "
               f"クロック≈{plotter.format_eng(jr['freq'])}Hz  エッジ{jr['edges']}本")
        self.adv_result.setText(msg)
        self._set_status(msg)

    def show_cycle_stats(self):
        import numpy as np
        got = self.analysis_xy_or_warn()
        if got is None:
            return
        t, y, label = got
        cm = analysis.cycle_measurements(t, np.asarray(y, float))
        fs = analysis.measurement_stats(cm["freq"])
        amps = analysis.measurement_stats(cm["vpp"])
        lines = []
        if fs["count"]:
            lines.append(f"周波数: 平均{plotter.format_eng(fs['mean'])}Hz σ={plotter.format_eng(fs['std'])} "
                         f"min{plotter.format_eng(fs['min'])}〜max{plotter.format_eng(fs['max'])} ({fs['count']}サイクル)")
        if amps["count"]:
            lines.append(f"Vpp: 平均{amps['mean']:.4g} σ={amps['std']:.3g} "
                         f"min{amps['min']:.4g}〜max{amps['max']:.4g}")
        self.adv_result.setText("　".join(lines) or "サイクルを検出できませんでした。")
        self._set_status(f"サイクル統計: {label}")

    def show_trend(self):
        import numpy as np
        got = self.analysis_xy_or_warn()
        if got is None:
            return
        t, y, label = got
        cm = analysis.cycle_measurements(t, np.asarray(y, float))
        if len(cm["cycle_time"]) < 2:
            self.notify("サイクルが不足しています。", "warn")
            return
        self.prepare_view_axes()
        self.ax.plot(cm["cycle_time"], cm["freq"], "-o", ms=3, color="#1f77b4")
        self.ax.set_xlabel("時間 [s]"); self.ax.set_ylabel("周波数 [Hz]")
        self.ax.set_title(f"周波数トレンド（サイクルごと）: {label}")
        self.ax.grid(True, alpha=0.3)
        try:
            self.fig.tight_layout()
        except Exception:
            applog.get_logger().debug("show_trend: 無視した例外", exc_info=True)
        self.canvas.draw()
        self._has_drawn = False
        self._set_status(f"トレンド表示: {label}")

    def show_phase(self):
        import numpy as np
        t1, y1, l1 = self._analysis_xy()
        t2, y2 = self._xy_by_disp(self.phase_target2.currentText())
        if t1 is None or t2 is None:
            self.notify("解析対象と対象2を選択してください。", "warn")
            return
        delay, phase = analysis.phase_delay(t1, np.asarray(y1, float), np.asarray(y2, float))
        if delay is None:
            self.notify("計算できませんでした。", "warn")
            return
        ph = "-" if phase is None else f"{phase:.1f}°"
        msg = f"位相差/遅延（{l1} vs {self.phase_target2.currentText()}）: 遅延={plotter.format_eng(delay)}s  位相={ph}"
        self.adv_result.setText(msg); self._set_status(msg)

    def _on_proto_change(self, proto):
        cfg = {
            "UART": (["信号線", "", ""], "ボーレート", "115200"),
            "I2C": (["SCL", "SDA", ""], "不使用", ""),
            "SPI": (["SCK", "MOSI", "CS(任意)"], "不使用", ""),
            "CAN": (["CAN(RXまたは差動)", "", ""], "ビットレート", "500k"),
            "LIN": (["信号線", "", ""], "ボーレート", "19200"),
            "1-Wire": (["信号線", "", ""], "不使用", ""),
        }[proto]
        labels, baud_lbl, baud_val = cfg
        for i in range(3):
            show = labels[i] != ""
            self.proto_ch_labels[i].setText(labels[i]); self.proto_ch_labels[i].setVisible(show)
            self.proto_ch[i].setVisible(show)
        self.proto_baud.setEnabled(proto in ("UART", "CAN", "LIN"))
        if baud_val:
            self.proto_baud.setText(baud_val)

    def decode_protocol(self):
        import numpy as np
        proto = self.proto_combo.currentText()
        t1, y1 = self._xy_by_disp(self.proto_ch[0].currentText())
        if t1 is None:
            self.notify("Ch1（信号線）をデータタブで選択してください。", "warn")
            return
        try:
            if proto == "UART":
                baud = plotter.parse_eng(self.proto_baud.text(), 115200)
                ev = advanced.decode_uart(t1, np.asarray(y1, float), baud=baud)
                rows = [(e["time"], "data", e["hex"], (e["char"] + ("" if e["ok"] else " ⚠")).strip()) for e in ev]
            elif proto == "I2C":
                t2, y2 = self._xy_by_disp(self.proto_ch[1].currentText())
                if t2 is None:
                    self.notify("SDA(Ch2)も選択してください。", "warn"); return
                ev = advanced.decode_i2c(t1, np.asarray(y1, float), np.asarray(y2, float))
                rows = []
                for e in ev:
                    if e["type"] in ("START", "STOP"):
                        rows.append((e["time"], e["type"], "", ""))
                    else:
                        rows.append((e["time"], e["type"], e["hex"],
                                     f"{e.get('rw','')} {e.get('ack','')}".strip()))
            elif proto == "SPI":
                t2, y2 = self._xy_by_disp(self.proto_ch[1].currentText())
                if t2 is None:
                    self.notify("MOSI(Ch2)も選択してください。", "warn"); return
                cs = None
                if self.proto_ch[2].currentText():
                    _, cs = self._xy_by_disp(self.proto_ch[2].currentText())
                    cs = np.asarray(cs, float) if cs is not None else None
                ev = advanced.decode_spi(t1, np.asarray(y1, float), np.asarray(y2, float), cs=cs)
                rows = [(e["time"], "data", e["hex"], "") for e in ev]
            elif proto == "CAN":
                rate = plotter.parse_eng(self.proto_baud.text(), 500e3)
                ev = advanced.decode_can(t1, np.asarray(y1, float), bitrate=rate)
                rows = []
                for e in ev:
                    idw = f"{e['id']:08X}" if e["ext"] else f"{e['id']:03X}"
                    kind = ("CANx" if e["ext"] else "CAN") + ("/RTR" if e["rtr"] else "")
                    note = f"DLC={e['dlc']}" + ("" if e["crc_ok"] else " CRC⚠")
                    rows.append((e["time"], kind, f"ID={idw} [{e['hex']}]", note))
            elif proto == "LIN":
                baud = plotter.parse_eng(self.proto_baud.text(), 19200)
                ev = advanced.decode_lin(t1, np.asarray(y1, float), baud=baud)
                rows = []
                for e in ev:
                    if e["type"] == "BREAK":
                        rows.append((e["time"], "BREAK", "", ""))
                    elif e["type"] == "PID":
                        rows.append((e["time"], "PID", f"0x{e['value']:02X}",
                                     "" if e.get("ok") else "パリティ⚠"))
                    elif e["type"] == "CSUM":
                        rows.append((e["time"], "CSUM", f"0x{e['value']:02X}",
                                     "OK" if e.get("ok") else "不一致⚠"))
                    else:
                        rows.append((e["time"], e["type"], f"0x{e['value']:02X}", ""))
            else:  # 1-Wire
                ev = advanced.decode_onewire(t1, np.asarray(y1, float))
                rows = [(e["time"], e["type"],
                         f"0x{e['value']:02X}" if e["type"] == "data" else "", "")
                        for e in ev]
        except Exception as e:  # noqa: BLE001
            QtWidgets.QMessageBox.critical(self, "解読エラー", str(e)); return

        self.proto_table.setRowCount(len(rows))
        for r, (tm, kind, hexv, note) in enumerate(rows):
            self.proto_table.setItem(r, 0, QtWidgets.QTableWidgetItem(f"{tm*1e3:.4g} ms"))
            self.proto_table.setItem(r, 1, QtWidgets.QTableWidgetItem(str(kind)))
            self.proto_table.setItem(r, 2, QtWidgets.QTableWidgetItem(str(hexv)))
            self.proto_table.setItem(r, 3, QtWidgets.QTableWidgetItem(str(note)))
        # 波形上の注記用に保持（「解読結果をグラフに注記表示」ON時に描画）
        self._proto_annotations = {"rows": rows, "proto": proto}
        if (getattr(self, "proto_overlay_check", None)
                and self.proto_overlay_check.isChecked() and self._has_drawn):
            self.draw_graph()
        self._set_status(f"{proto} 解読: {len(rows)} 件")

    def _on_proto_overlay_toggled(self, *_):
        if self.datasets and self._has_drawn:
            self.draw_graph()

    def _build_tab_advanced(self):
        outer = QtWidgets.QScrollArea(); outer.setWidgetResizable(True)
        w = QtWidgets.QWidget(); outer.setWidget(w)
        v = QtWidgets.QVBoxLayout(w)

        # --- 数学チャンネル ---
        v.addWidget(self._bold("数学チャンネル（演算で新しい波形を作成）"))
        mg = QtWidgets.QGridLayout()
        mg.addWidget(QtWidgets.QLabel("演算"), 0, 0)
        self.math_op = QtWidgets.QComboBox()
        self.math_op.addItems(mathchan.BINARY_OPS + mathchan.UNARY_OPS)
        self.math_op.currentTextChanged.connect(self._on_math_op_change)
        mg.addWidget(self.math_op, 0, 1, 1, 3)
        mg.addWidget(QtWidgets.QLabel("A"), 1, 0)
        self.math_a = QtWidgets.QComboBox(); mg.addWidget(self.math_a, 1, 1)
        self.math_b_label = QtWidgets.QLabel("B"); mg.addWidget(self.math_b_label, 1, 2)
        self.math_b = QtWidgets.QComboBox(); mg.addWidget(self.math_b, 1, 3)
        self.math_param_label = QtWidgets.QLabel("パラメータ"); mg.addWidget(self.math_param_label, 2, 0)
        self.math_param = QtWidgets.QLineEdit("5"); self.math_param.setToolTip("移動平均=窓長(点)、ローパス=カットオフ[Hz]")
        mg.addWidget(self.math_param, 2, 1)
        b_math = QtWidgets.QPushButton("数学チャンネルを作成"); b_math.clicked.connect(self.create_math_channel)
        mg.addWidget(b_math, 2, 2, 1, 2)
        v.addLayout(mg)
        # 任意数式（A,B,VAR1,VAR2,t と関数で自由に演算）
        eg = QtWidgets.QGridLayout()
        eg.addWidget(QtWidgets.QLabel("数式"), 0, 0)
        self.math_expr = QtWidgets.QLineEdit()
        self.math_expr.setPlaceholderText("例: sqrt(A**2+B**2) / sin(2*pi*t)*VAR1 / A-VAR1")
        self.math_expr.setToolTip("変数: A=対象A, B=対象B, t=時間, VAR1, VAR2, 定数 pi/e。\n"
                                  "関数: sin/cos/tan/asin/.../exp/log/log10/log2/sqrt/abs/sign/min/max/clip/where。")
        eg.addWidget(self.math_expr, 0, 1, 1, 3)
        eg.addWidget(QtWidgets.QLabel("VAR1"), 1, 0)
        self.math_var1 = QtWidgets.QLineEdit("1"); eg.addWidget(self.math_var1, 1, 1)
        eg.addWidget(QtWidgets.QLabel("VAR2"), 1, 2)
        self.math_var2 = QtWidgets.QLineEdit("0"); eg.addWidget(self.math_var2, 1, 3)
        b_expr = QtWidgets.QPushButton("数式でチャンネル作成"); b_expr.clicked.connect(self.create_math_expr)
        eg.addWidget(b_expr, 2, 0, 1, 4)
        v.addLayout(eg)
        v.addWidget(self._hline())

        # --- FFT 詳細 ---
        v.addWidget(self._bold("FFT 詳細（窓・dB・THD/SNR・スペクトログラム）"))
        fg = QtWidgets.QGridLayout()
        fg.addWidget(QtWidgets.QLabel("窓関数"), 0, 0)
        self.fft_window = QtWidgets.QComboBox(); self.fft_window.addItems(analysis.WINDOWS)
        self.fft_window.setCurrentText("hann"); fg.addWidget(self.fft_window, 0, 1)
        self.fft_db = QtWidgets.QCheckBox("dB表示"); fg.addWidget(self.fft_db, 0, 2)
        b_m = QtWidgets.QPushButton("THD/SNR等を計算"); b_m.clicked.connect(self.compute_fft_metrics)
        fg.addWidget(b_m, 1, 0, 1, 2)
        b_sp = QtWidgets.QPushButton("スペクトログラム"); b_sp.clicked.connect(self.show_spectrogram)
        fg.addWidget(b_sp, 1, 2, 1, 1)
        b_wf = QtWidgets.QPushButton("ウォーターフォール")
        b_wf.setToolTip("STFTの時間スライスを3Dに重ねて表示（周波数成分の時間変化を見る）。"
                        "ドラッグで回転できます。")
        b_wf.clicked.connect(self.show_waterfall)
        fg.addWidget(b_wf, 1, 3, 1, 1)
        v.addLayout(fg)
        self.fft_metrics = QtWidgets.QTableWidget(0, 2)
        self.fft_metrics.setHorizontalHeaderLabels(["指標", "値"])
        self.fft_metrics.horizontalHeader().setStretchLastSection(True)
        self.fft_metrics.setMaximumHeight(170)
        self._wire_table_export(self.fft_metrics, "FFT指標")
        v.addWidget(self.fft_metrics)
        v.addWidget(self._hline())

        # --- マスク試験 / アイ / ジッタ ---
        v.addWidget(self._bold("マスク試験 / アイダイアグラム / ジッタ"))
        mk = QtWidgets.QGridLayout()
        mk.addWidget(QtWidgets.QLabel("上限"), 0, 0)
        # プレースホルダが「なし」なので、名前を明示しないと索引で区別できない
        self.mask_upper = QtWidgets.QLineEdit(); self.mask_upper.setPlaceholderText("なし")
        self.mask_upper.setAccessibleName("マスク上限")
        mk.addWidget(self.mask_upper, 0, 1)
        mk.addWidget(QtWidgets.QLabel("下限"), 0, 2)
        self.mask_lower = QtWidgets.QLineEdit(); self.mask_lower.setPlaceholderText("なし")
        self.mask_lower.setAccessibleName("マスク下限")
        mk.addWidget(self.mask_lower, 0, 3)
        b_mask = QtWidgets.QPushButton("マスク判定"); b_mask.clicked.connect(self.run_mask_test)
        mk.addWidget(b_mask, 1, 0, 1, 2)
        mk.addWidget(QtWidgets.QLabel("シンボルレート[Hz]/周期[s]"), 2, 0, 1, 2)
        self.eye_rate = QtWidgets.QLineEdit("1e6"); mk.addWidget(self.eye_rate, 2, 2)
        b_eye = QtWidgets.QPushButton("アイダイアグラム"); b_eye.clicked.connect(self.show_eye_diagram)
        mk.addWidget(b_eye, 2, 3)
        b_jit = QtWidgets.QPushButton("ジッタ解析(TIE)"); b_jit.clicked.connect(self.run_jitter)
        mk.addWidget(b_jit, 1, 2, 1, 2)
        v.addLayout(mk)
        self.adv_result = QtWidgets.QLabel(""); self.adv_result.setWordWrap(True)
        self.adv_result.setStyleSheet("color:#0a3;")
        v.addWidget(self.adv_result)
        v.addWidget(self._hline())

        # --- プロトコル解読 ---
        v.addWidget(self._bold("シリアルプロトコル解読"))
        pg = QtWidgets.QGridLayout()
        pg.addWidget(QtWidgets.QLabel("プロトコル"), 0, 0)
        self.proto_combo = QtWidgets.QComboBox()
        self.proto_combo.addItems(["UART", "I2C", "SPI", "CAN", "LIN", "1-Wire"])
        self.proto_combo.currentTextChanged.connect(self._on_proto_change)
        pg.addWidget(self.proto_combo, 0, 1)
        pg.addWidget(QtWidgets.QLabel("ボーレート/不使用"), 0, 2)
        self.proto_baud = QtWidgets.QLineEdit("115200"); pg.addWidget(self.proto_baud, 0, 3)
        self.proto_ch_labels = [QtWidgets.QLabel("Ch1"), QtWidgets.QLabel("Ch2"), QtWidgets.QLabel("Ch3")]
        self.proto_ch = [QtWidgets.QComboBox(), QtWidgets.QComboBox(), QtWidgets.QComboBox()]
        for i in range(3):
            pg.addWidget(self.proto_ch_labels[i], 1 + i, 0)
            pg.addWidget(self.proto_ch[i], 1 + i, 1, 1, 3)
        b_dec = QtWidgets.QPushButton("解読"); b_dec.clicked.connect(self.decode_protocol)
        pg.addWidget(b_dec, 4, 0, 1, 4)
        self.proto_overlay_check = QtWidgets.QCheckBox("解読結果をグラフに注記表示")
        self.proto_overlay_check.setToolTip(
            "解読したフレームの値を波形の上に直接注記します（Saleae風・先頭80件まで）。\n"
            "CRC/パリティ等の不一致は赤で表示。折れ線/散布図の2D表示で有効。")
        self.proto_overlay_check.toggled.connect(self._on_proto_overlay_toggled)
        pg.addWidget(self.proto_overlay_check, 5, 0, 1, 4)
        v.addLayout(pg)
        self.proto_table = QtWidgets.QTableWidget(0, 4)
        self.proto_table.setHorizontalHeaderLabels(["時刻", "種別", "値(hex)", "備考"])
        self.proto_table.horizontalHeader().setStretchLastSection(True)
        self._wire_table_export(self.proto_table, "プロトコル解読")
        v.addWidget(self.proto_table, 1)

        self._on_math_op_change(self.math_op.currentText())
        self._on_proto_change("UART")
        return outer
