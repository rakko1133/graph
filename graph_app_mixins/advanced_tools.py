# -*- coding: utf-8 -*-
"""AdvancedMixin: GraphApp から分離した AdvancedMixin 群（挙動は本体と同一）。"""
from graph_app_common import *  # noqa: F401,F403


class AdvancedMixin:
    # ------------------------------------------------------------ 高度解析
    def _xy_by_disp(self, disp):
        """選択中系列の表示名から (t, y) を取得（時間軸は数値化）。"""
        import numpy as np
        import pandas as pd
        for fl, col, d in self._selected_series_items():
            if d == disp:
                df = self.datasets[fl]
                xname = self.x_combo.currentText()
                raw = df[xname].to_numpy() if xname in df.columns else df.iloc[:, 0].to_numpy()
                t = pd.to_numeric(pd.Series(raw), errors="coerce").to_numpy(dtype=float)
                if np.isnan(t).mean() > 0.5:
                    t = np.arange(len(t), dtype=float)
                y = pd.to_numeric(pd.Series(df[col].to_numpy()), errors="coerce").to_numpy(dtype=float)
                return t, y
        return None, None

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
            QtWidgets.QMessageBox.information(self, "情報", "演算対象Aをデータタブで選択してください。")
            return
        try:
            if op in mathchan.BINARY_OPS:
                tb, yb = self._xy_by_disp(self.math_b.currentText())
                if tb is None:
                    QtWidgets.QMessageBox.information(self, "情報", "演算対象Bを選択してください。")
                    return
                x, r = mathchan.binary(ta, ya, tb, yb, op)
            else:
                param = plotter.parse_eng(self.math_param.text(), None)
                x, r = mathchan.unary(ta, ya, op, param)
        except Exception as e:  # noqa: BLE001
            QtWidgets.QMessageBox.critical(self, "演算エラー", str(e)); return
        import pandas as pd
        col = f"{op}"
        label = f"Math: {op}"
        base, i = label, 2
        while label in self.datasets:
            label = f"{base} ({i})"; i += 1
        self.datasets[label] = pd.DataFrame({"時間[s]": x, col: r})
        self.meta[label] = {"path": label, "enc": "-", "delim": "-"}
        self._add_file_item(label)
        self._refresh_columns()
        self._set_status(f"数学チャンネルを作成: {label} ▸ {col}")

    def create_math_expr(self):
        """任意数式（A,B,VAR1,VAR2,t と許可関数）で新チャンネルを作成。"""
        import numpy as np
        import pandas as pd
        expr = self.math_expr.text().strip()
        if not expr:
            QtWidgets.QMessageBox.information(self, "情報", "数式を入力してください。")
            return
        ta, ya = self._xy_by_disp(self.math_a.currentText())
        if ta is None:
            QtWidgets.QMessageBox.information(self, "情報", "変数Aの系列をデータタブで選択してください。")
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
        label = f"Expr: {expr[:24]}"
        base, i = label, 2
        while label in self.datasets:
            label = f"{base} ({i})"; i += 1
        self.datasets[label] = pd.DataFrame({"時間[s]": ta, "結果": r})
        self.meta[label] = {"path": label, "enc": "-", "delim": "-"}
        self._add_file_item(label)
        self._refresh_columns()
        self._set_status(f"数式チャンネルを作成: {label}")

    def show_param_stats(self):
        """解析対象チャンネルのサイクル統計表＋パラメータ間演算を別ウィンドウで表示。"""
        import numpy as np
        t, y, label = self._analysis_xy()
        if t is None:
            QtWidgets.QMessageBox.information(self, "情報", "解析対象の系列を選択してください。")
            return
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
        t, y, label = self._analysis_xy()
        if t is None:
            QtWidgets.QMessageBox.information(self, "情報", "解析対象の系列を選択してください。")
            return
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
        t, y, label = self._analysis_xy()
        if t is None:
            QtWidgets.QMessageBox.information(self, "情報", "解析対象の系列を選択してください。")
            return
        f, tt, S = analysis.spectrogram(t, np.asarray(y, float),
                                        window=self.fft_window.currentText())
        if S is None:
            QtWidgets.QMessageBox.warning(self, "スペクトログラム", "計算できませんでした。")
            return
        self._ensure_axes_projection(False)   # 3D表示中でも2D軸に戻して描く
        self._reset_figure_axes()
        self.ax.clear()
        self.ax.set_facecolor("white"); self.ax.tick_params(colors="black")
        mesh = self.ax.pcolormesh(tt, f, S, shading="auto", cmap="viridis")
        self.ax.set_xlabel("時間 [s]"); self.ax.set_ylabel("周波数 [Hz]")
        self.ax.set_title(f"スペクトログラム: {label}")
        try:
            self.fig.colorbar(mesh, ax=self.ax, label="dB")
        except Exception:
            pass
        self._apply_aspect()   # 縦横比の設定をスペクトログラムにも適用
        try:
            self.fig.tight_layout()
        except Exception:
            pass
        self.canvas.draw()
        self._has_drawn = False  # カラーバー付き特殊表示。次のdrawで作り直す
        self._set_status(f"スペクトログラム表示: {label}")

    def run_mask_test(self):
        import numpy as np
        t, y, label = self._analysis_xy()
        if t is None:
            QtWidgets.QMessageBox.information(self, "情報", "解析対象の系列を選択してください。")
            return
        up = plotter.parse_eng(self.mask_upper.text(), None)
        lo = plotter.parse_eng(self.mask_lower.text(), None)
        if up is None and lo is None:
            QtWidgets.QMessageBox.information(self, "情報", "上限または下限を入力してください。")
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
        t, y, label = self._analysis_xy()
        if t is None:
            QtWidgets.QMessageBox.information(self, "情報", "解析対象の系列を選択してください。")
            return
        val = plotter.parse_eng(self.eye_rate.text(), 1e6)
        # シンボルレート[Hz] と解釈（>1 ならレート、<1 なら周期[s]とみなす）
        sym_period = (1.0 / val) if val and val > 1 else (val or 1e-6)
        phase, yy = advanced.eye_diagram(t, np.asarray(y, float), sym_period, n_ui=2)
        self._ensure_axes_projection(False)   # 3D表示中でも2D軸に戻して描く
        self._reset_figure_axes()
        self.ax.clear()
        self.ax.set_facecolor("white"); self.ax.tick_params(colors="black")
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
            pass
        self.canvas.draw()
        self._has_drawn = False
        self._set_status(f"アイダイアグラム表示: {label}")

    def run_jitter(self):
        import numpy as np
        t, y, label = self._analysis_xy()
        if t is None:
            QtWidgets.QMessageBox.information(self, "情報", "解析対象の系列を選択してください。")
            return
        jr = advanced.jitter_tie(t, np.asarray(y, float))
        if not jr:
            QtWidgets.QMessageBox.warning(self, "ジッタ", "エッジが不足し計算できませんでした。")
            return
        msg = (f"ジッタ: RMS={plotter.format_eng(jr['rms'])}s  "
               f"pp={plotter.format_eng(jr['pp'])}s  "
               f"クロック≈{plotter.format_eng(jr['freq'])}Hz  エッジ{jr['edges']}本")
        self.adv_result.setText(msg)
        self._set_status(msg)

    def show_cycle_stats(self):
        import numpy as np
        t, y, label = self._analysis_xy()
        if t is None:
            QtWidgets.QMessageBox.information(self, "情報", "解析対象の系列を選択してください。")
            return
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
        t, y, label = self._analysis_xy()
        if t is None:
            QtWidgets.QMessageBox.information(self, "情報", "解析対象の系列を選択してください。")
            return
        cm = analysis.cycle_measurements(t, np.asarray(y, float))
        if len(cm["cycle_time"]) < 2:
            QtWidgets.QMessageBox.warning(self, "トレンド", "サイクルが不足しています。")
            return
        self._ensure_axes_projection(False)   # 3D表示中でも2D軸に戻して描く
        self._reset_figure_axes()
        self.ax.clear()
        self.ax.set_facecolor("white"); self.ax.tick_params(colors="black")
        self.ax.plot(cm["cycle_time"], cm["freq"], "-o", ms=3, color="#1f77b4")
        self.ax.set_xlabel("時間 [s]"); self.ax.set_ylabel("周波数 [Hz]")
        self.ax.set_title(f"周波数トレンド（サイクルごと）: {label}")
        self.ax.grid(True, alpha=0.3)
        try:
            self.fig.tight_layout()
        except Exception:
            pass
        self.canvas.draw()
        self._has_drawn = False
        self._set_status(f"トレンド表示: {label}")

    def show_phase(self):
        import numpy as np
        t1, y1, l1 = self._analysis_xy()
        t2, y2 = self._xy_by_disp(self.phase_target2.currentText())
        if t1 is None or t2 is None:
            QtWidgets.QMessageBox.information(self, "情報", "解析対象と対象2を選択してください。")
            return
        delay, phase = analysis.phase_delay(t1, np.asarray(y1, float), np.asarray(y2, float))
        if delay is None:
            QtWidgets.QMessageBox.warning(self, "位相差", "計算できませんでした。")
            return
        ph = "-" if phase is None else f"{phase:.1f}°"
        msg = f"位相差/遅延（{l1} vs {self.phase_target2.currentText()}）: 遅延={plotter.format_eng(delay)}s  位相={ph}"
        self.adv_result.setText(msg); self._set_status(msg)

    def _on_proto_change(self, proto):
        cfg = {
            "UART": (["信号線", "", ""], "ボーレート", "115200"),
            "I2C": (["SCL", "SDA", ""], "不使用", ""),
            "SPI": (["SCK", "MOSI", "CS(任意)"], "不使用", ""),
        }[proto]
        labels, baud_lbl, baud_val = cfg
        for i in range(3):
            show = labels[i] != ""
            self.proto_ch_labels[i].setText(labels[i]); self.proto_ch_labels[i].setVisible(show)
            self.proto_ch[i].setVisible(show)
        self.proto_baud.setEnabled(proto == "UART")
        if baud_val:
            self.proto_baud.setText(baud_val)

    def decode_protocol(self):
        import numpy as np
        proto = self.proto_combo.currentText()
        t1, y1 = self._xy_by_disp(self.proto_ch[0].currentText())
        if t1 is None:
            QtWidgets.QMessageBox.information(self, "情報", "Ch1（信号線）をデータタブで選択してください。")
            return
        try:
            if proto == "UART":
                baud = plotter.parse_eng(self.proto_baud.text(), 115200)
                ev = advanced.decode_uart(t1, np.asarray(y1, float), baud=baud)
                rows = [(e["time"], "data", e["hex"], (e["char"] + ("" if e["ok"] else " ⚠")).strip()) for e in ev]
            elif proto == "I2C":
                t2, y2 = self._xy_by_disp(self.proto_ch[1].currentText())
                if t2 is None:
                    QtWidgets.QMessageBox.information(self, "情報", "SDA(Ch2)も選択してください。"); return
                ev = advanced.decode_i2c(t1, np.asarray(y1, float), np.asarray(y2, float))
                rows = []
                for e in ev:
                    if e["type"] in ("START", "STOP"):
                        rows.append((e["time"], e["type"], "", ""))
                    else:
                        rows.append((e["time"], e["type"], e["hex"],
                                     f"{e.get('rw','')} {e.get('ack','')}".strip()))
            else:  # SPI
                t2, y2 = self._xy_by_disp(self.proto_ch[1].currentText())
                if t2 is None:
                    QtWidgets.QMessageBox.information(self, "情報", "MOSI(Ch2)も選択してください。"); return
                cs = None
                if self.proto_ch[2].currentText():
                    _, cs = self._xy_by_disp(self.proto_ch[2].currentText())
                    cs = np.asarray(cs, float) if cs is not None else None
                ev = advanced.decode_spi(t1, np.asarray(y1, float), np.asarray(y2, float), cs=cs)
                rows = [(e["time"], "data", e["hex"], "") for e in ev]
        except Exception as e:  # noqa: BLE001
            QtWidgets.QMessageBox.critical(self, "解読エラー", str(e)); return

        self.proto_table.setRowCount(len(rows))
        for r, (tm, kind, hexv, note) in enumerate(rows):
            self.proto_table.setItem(r, 0, QtWidgets.QTableWidgetItem(f"{tm*1e3:.4g} ms"))
            self.proto_table.setItem(r, 1, QtWidgets.QTableWidgetItem(str(kind)))
            self.proto_table.setItem(r, 2, QtWidgets.QTableWidgetItem(str(hexv)))
            self.proto_table.setItem(r, 3, QtWidgets.QTableWidgetItem(str(note)))
        self._set_status(f"{proto} 解読: {len(rows)} 件")
