# -*- coding: utf-8 -*-
"""ScopeCursorMixin: GraphApp から分離した ScopeCursorMixin 群（挙動は本体と同一）。"""
from graph_app_common import *  # noqa: F401,F403


class ScopeCursorMixin:
    # ------------------------------------------------------------ カーソル測定
    def toggle_cursors(self, on):
        if on and getattr(self, "gate_btn", None) and self.gate_btn.isChecked():
            self.gate_btn.setChecked(False)   # 区間測定と排他（ドラッグ操作が競合する）
        if on:
            self._cursors = []          # [{x, vline, marker}, ...] 最大2本
            self._cursor_drag = None
            self._cursor_text = None
            self._clear_cursor_artists()
            self._cursor_cid = (
                self.canvas.mpl_connect("button_press_event", self._on_cursor_press),
                self.canvas.mpl_connect("motion_notify_event", self._on_cursor_motion),
                self.canvas.mpl_connect("button_release_event", self._on_cursor_release),
            )
            self._set_status("カーソル: クリックで2本設置 → 線をドラッグで微調整（波形に追従）")
        else:
            if self._cursor_cid:
                for c in self._cursor_cid:
                    self.canvas.mpl_disconnect(c)
                self._cursor_cid = None
            self._clear_cursor_artists()
            self.canvas.draw_idle()

    def _clear_cursor_artists(self):
        for a in self._cursor_artists:
            try:
                a.remove()
            except Exception:
                pass
        self._cursor_artists = []
        self._cursors = []
        self._cursor_text = None

    def _cursor_track_y(self, x):
        """最初に描画した線の x における y を補間（カーソルを波形に追従させる）。"""
        if not self._plotted_artists:
            return 0.0
        try:
            import numpy as np
            line = self._plotted_artists[0][1]
            xd = np.asarray(line.get_xdata(), float)
            yd = np.asarray(line.get_ydata(), float)
            order = np.argsort(xd)
            return float(np.interp(x, xd[order], yd[order]))
        except Exception:
            return 0.0

    def _add_cursor(self, x):
        y = self._cursor_track_y(x)
        vl = self.ax.axvline(x, color="#e6194b", lw=0.9, ls="--")
        mk, = self.ax.plot([x], [y], "o", color="#e6194b", ms=6)
        self._cursors.append({"x": x, "vline": vl, "marker": mk})
        self._cursor_artists += [vl, mk]

    def _cursor_near(self, event):
        """クリック位置に近い既存カーソルの index を返す（無ければ None）。"""
        for i, c in enumerate(self._cursors):
            try:
                cx_px = self.ax.transData.transform((c["x"], 0))[0]
                if abs(event.x - cx_px) < 8:
                    return i
            except Exception:
                pass
        return None

    def _on_cursor_press(self, event):
        if event.inaxes is not self.ax or event.xdata is None:
            return
        if getattr(self.ax, "name", None) == "3d":   # 3Dは回転を優先しカーソル無効
            return
        near = self._cursor_near(event)
        if near is not None:                       # 既存カーソルを掴んで微調整
            self._cursor_drag = near
            return
        if len(self._cursors) >= 2:                # 3本目で計測リセット
            self._clear_cursor_artists()
        self._add_cursor(event.xdata)
        self._update_cursor_readout()
        self.canvas.draw_idle()

    def _on_cursor_motion(self, event):
        if self._cursor_drag is None or event.inaxes is not self.ax or event.xdata is None:
            return
        c = self._cursors[self._cursor_drag]
        c["x"] = event.xdata
        c["vline"].set_xdata([event.xdata, event.xdata])
        c["marker"].set_data([event.xdata], [self._cursor_track_y(event.xdata)])
        self._update_cursor_readout()
        self.canvas.draw_idle()

    def _on_cursor_release(self, event):
        self._cursor_drag = None

    def _update_cursor_readout(self):
        if self._cursor_text is not None:
            try:
                self._cursor_text.remove()
            except Exception:
                pass
            self._cursor_text = None
        if len(self._cursors) == 2:
            x1, x2 = self._cursors[0]["x"], self._cursors[1]["x"]
            y1, y2 = self._cursor_track_y(x1), self._cursor_track_y(x2)
            dt, dv = x2 - x1, y2 - y1
            freq = (1.0 / dt) if dt else float("inf")
            txt = (f"Δt={plotter.format_eng(abs(dt))}  ΔV={plotter.format_eng(abs(dv))}"
                   f"  1/Δt={plotter.format_eng(abs(freq))}Hz")
            self._cursor_text = self.ax.text(
                0.5, 0.98, txt, transform=self.ax.transAxes, ha="center", va="top",
                color="#e6194b", fontsize=9,
                bbox=dict(facecolor="white", alpha=0.75, edgecolor="#e6194b"))
            self._cursor_artists.append(self._cursor_text)
            self._set_status("カーソル  " + txt)

    # ------------------------------------------------------ オシロ ドラッグ操作
    def _scope_active(self):
        """オシロのドラッグ操作が有効か（オシロ表示ON・折れ線/散布図・他モード非競合）。"""
        return (self.scope_check.isChecked()
                and self.chart_combo.currentText() in ("折れ線", "散布図")
                and self._has_drawn
                and self._cursor_cid is None
                and not getattr(self.toolbar, "mode", ""))

    def _scope_overlay(self, text):
        self._remove_scope_overlay()
        # family="monospace" は日本語グリフを持たず「位置/中心」等が文字化けするため指定しない
        # （rcParams の日本語フォントを使う）。
        self._scope_ov = self.ax.text(
            0.99, 0.02, text, transform=self.ax.transAxes, ha="right", va="bottom",
            color="#7CFC00", fontsize=11,
            bbox=dict(facecolor="black", alpha=0.65, edgecolor="#7CFC00"))

    def _remove_scope_overlay(self):
        if self._scope_ov is not None:
            try:
                self._scope_ov.remove()
            except Exception:
                pass
            self._scope_ov = None

    def _shift_held(self, event=None):
        """Shift押下を判定。matplotlibの event.key はバックエンドによりスクロール時に
        Shiftを取りこぼすため、Qtのキーボード修飾キー状態を優先して見る。"""
        try:
            mods = QtWidgets.QApplication.keyboardModifiers()
            if bool(mods & QtCore.Qt.KeyboardModifier.ShiftModifier):
                return True
        except Exception:
            pass
        return bool(event is not None and event.key and "shift" in str(event.key))

    def _scope_on_press(self, event):
        # ダブルクリック=全体表示（カーソル測定・ツールバーモード・3Dでは無効）
        if (event.dblclick and event.button == 1
                and event.inaxes is not None and event.inaxes in self.fig.axes
                and self._cursor_cid is None and not getattr(self.toolbar, "mode", "")
                and getattr(event.inaxes, "name", None) != "3d"
                and event.inaxes.get_label() != "<colorbar>"
                and getattr(self, "_has_drawn", False)):
            self._autoscale_view()
            return
        if (not self._scope_active() or event.inaxes is not self.ax
                or event.button not in (1, 3) or event.x is None):
            return
        bbox = self.ax.get_window_extent()
        self._scope_drag = {
            "button": event.button, "shift": self._shift_held(event),
            "px": (event.x, event.y),
            "xlim": self.ax.get_xlim(), "ylim": self.ax.get_ylim(),
            "tdiv": plotter.parse_eng(self.tdiv.currentText(), 1e-3) or 1e-3,
            "vdiv": plotter.parse_eng(self.vdiv.currentText(), 1.0) or 1.0,
            "w": max(bbox.width, 1.0), "h": max(bbox.height, 1.0),
        }

    def _scope_on_motion(self, event):
        d = self._scope_drag
        if not d or event.x is None:
            return
        dxpx = event.x - d["px"][0]
        dypx = event.y - d["px"][1]
        xd, yd = self.xdivs.value(), self.ydivs.value()
        if d["button"] == 1 and not d["shift"]:   # 左ドラッグ = パン（位置移動）
            x0, x1 = d["xlim"]; y0, y1 = d["ylim"]
            dpx = (x1 - x0) / d["w"]; dpy = (y1 - y0) / d["h"]
            nx0, nx1 = x0 - dxpx * dpx, x1 - dxpx * dpx
            ny0, ny1 = y0 - dypx * dpy, y1 - dypx * dpy
            self.ax.set_xlim(nx0, nx1); self.ax.set_ylim(ny0, ny1)
            self._scope_overlay(f"位置  X中心={plotter.format_eng((nx0+nx1)/2)}  "
                                f"Y中心={plotter.format_eng((ny0+ny1)/2)}")
        else:                                       # 右ドラッグ/Shift = スケール（div）
            xc = (d["xlim"][0] + d["xlim"][1]) / 2
            yc = (d["ylim"][0] + d["ylim"][1]) / 2
            ntdiv = d["tdiv"] * (2 ** (dxpx / 150.0))
            nvdiv = d["vdiv"] * (2 ** (-dypx / 150.0))
            self.ax.set_xlim(xc - xd / 2 * ntdiv, xc + xd / 2 * ntdiv)
            self.ax.set_ylim(yc - yd / 2 * nvdiv, yc + yd / 2 * nvdiv)
            self._scope_overlay(f"{plotter.format_eng(ntdiv)}s/div   "
                                f"{plotter.format_eng(nvdiv)}/div")
        self.canvas.draw_idle()

    def _scope_on_release(self, event):
        if not self._scope_drag:
            return
        self._scope_drag = None
        self._remove_scope_overlay()
        x0, x1 = self.ax.get_xlim(); y0, y1 = self.ax.get_ylim()
        xd, yd = self.xdivs.value(), self.ydivs.value()
        self._suspend_redraw = True
        self.xpos.setText(f"{(x0+x1)/2:.6g}"); self.ypos.setText(f"{(y0+y1)/2:.6g}")
        self.tdiv.setCurrentText(plotter.format_eng((x1 - x0) / xd) + "s")
        self.vdiv.setCurrentText(plotter.format_eng((y1 - y0) / yd))
        self._suspend_redraw = False
        self.draw_graph()   # グラティクル等を正式に再構築

    def _scope_on_scroll(self, event):
        if event.inaxes is not self.ax:
            return
        if self._scope_active():
            step = 0.8 if event.button == "up" else 1.25   # up=ズームイン(div小)
            self._suspend_redraw = True
            if self._shift_held(event):
                cur = plotter.parse_eng(self.vdiv.currentText(), 1.0) or 1.0
                self.vdiv.setCurrentText(plotter.format_eng(cur * step))
            else:
                cur = plotter.parse_eng(self.tdiv.currentText(), 1e-3) or 1e-3
                self.tdiv.setCurrentText(plotter.format_eng(cur * step) + "s")
            self._suspend_redraw = False
            self.draw_graph()
            return
        # オシロ表示以外でもホイールで拡大縮小（カーソル位置を中心に）
        self._wheel_zoom(event)

    def _wheel_zoom(self, event):
        """通常グラフのマウスホイール拡大縮小。カーソル位置を中心にズームする。
        Shift+ホイールはX方向のみ（波形の横拡大）。段分け表示中はホバー中の段を拡縮。"""
        # カーソル測定中・ツールバーのパン/ズーム中・未描画・円・3Dでは無効
        # （3Dは mplot3d 標準のドラッグ回転・ホイールに任せる）
        ax = event.inaxes if event.inaxes in self.fig.axes else self.ax
        if (self._cursor_cid is not None
                or getattr(self.toolbar, "mode", "")
                or not getattr(self, "_has_drawn", False)
                or self.chart_combo.currentText() == "円"
                or getattr(ax, "name", None) == "3d"
                or ax.get_label() == "<colorbar>"):
            return
        factor = 0.8 if event.button == "up" else 1.25   # up=拡大（範囲を狭める）
        x0, x1 = ax.get_xlim()
        y0, y1 = ax.get_ylim()
        xc = event.xdata if event.xdata is not None else (x0 + x1) / 2.0
        yc = event.ydata if event.ydata is not None else (y0 + y1) / 2.0
        xlog = ax.get_xscale() == "log"
        ylog = ax.get_yscale() == "log"
        ax.set_xlim(*self._zoom_pair(x0, x1, xc, factor, xlog))
        if not self._shift_held(event):     # Shift押下時はYを保持（横方向のみ拡大）
            ax.set_ylim(*self._zoom_pair(y0, y1, yc, factor, ylog))
        self.canvas.draw_idle()

    # ------------------------------------------------------ 区間測定（ゲーティング）
    def toggle_gate(self, on):
        """ONの間、グラフを横にドラッグしてX区間を選ぶと、その区間だけを測定する。"""
        if on:
            if getattr(self.ax, "name", None) == "3d":
                self._set_status("区間測定は2Dグラフで使えます（3D表示では無効）。")
                self.gate_btn.setChecked(False)
                return
            if self.cursor_btn.isChecked():
                self.cursor_btn.setChecked(False)   # カーソル測定と排他
            from matplotlib.widgets import SpanSelector
            self._gate_span = SpanSelector(
                self.ax, self._on_gate_select, "horizontal", useblit=True,
                props=dict(alpha=0.2, facecolor="#2b6cb0"), interactive=True)
            self._set_status("区間測定: グラフ上を横にドラッグしてX範囲を選ぶと、"
                             "その区間だけの測定値を下の表に表示します。")
        else:
            sp = getattr(self, "_gate_span", None)
            if sp is not None:
                try:
                    sp.set_visible(False)
                    sp.disconnect_events()
                except Exception:
                    pass
            self._gate_span = None
            self.canvas.draw_idle()

    def _regate(self):
        """再描画で軸の中身がクリアされた後、区間測定の選択機構を作り直す。"""
        if getattr(self, "gate_btn", None) and self.gate_btn.isChecked():
            self.toggle_gate(False)
            if getattr(self.ax, "name", None) == "3d":
                self.gate_btn.setChecked(False)   # 3Dに切り替わったら解除
            else:
                self.toggle_gate(True)

    def _on_gate_select(self, x0, x1):
        if x1 < x0:
            x0, x1 = x1, x0
        if x0 == x1:
            return
        self._run_gated_analysis(float(x0), float(x1))

    def _autoscale_view(self):
        """ダブルクリックで全体表示。通常グラフは軸範囲指定をクリアして再描画、
        オシロ表示中は自動スケール（解析対象に合わせる）。"""
        if (self.scope_check.isChecked()
                and self.chart_combo.currentText() in ("折れ線", "散布図")):
            self.auto_scale_scope()
            return
        self._suspend_redraw = True
        for le in (self.xmin, self.xmax, self.ymin, self.ymax):
            le.clear()
        self._suspend_redraw = False
        self.draw_graph()
        self._set_status("全体表示に戻しました（ダブルクリックでいつでも戻れます）。")

    def _hover_readout(self, event):
        """マウス近傍のデータ点（系列名・X・Y）をステータスバー右端に常時表示する。
        ピクセル座標で最近傍を探すので、対数軸・単位換算後の表示座標でも正しい。"""
        lbl = getattr(self, "_hover_label", None)
        if lbl is None:
            return
        ax = event.inaxes
        if (ax is None or ax not in self.fig.axes or event.x is None
                or not getattr(self, "_has_drawn", False)
                or getattr(ax, "name", None) == "3d"
                or self._scope_drag or self._cursor_drag is not None):
            if lbl.text():
                lbl.setText("")
            return
        import time
        now = time.monotonic()
        if now - getattr(self, "_hover_t", 0.0) < 0.05:   # 20Hzに間引き（負荷対策）
            return
        self._hover_t = now
        import numpy as np
        # イベントの軸（段分け中は各段）と、重なっている第2軸/主軸を対象にする
        axs = [ax]
        twin = getattr(ax, "_twin_secondary", None)
        if twin is not None:
            axs.append(twin)
        if ax is getattr(self.ax, "_twin_secondary", None):
            axs.append(self.ax)
        cands = [(ln.get_label(), ln) for a in axs for ln in a.get_lines()
                 if not str(ln.get_label()).startswith("_")
                 and "近似" not in str(ln.get_label())]
        best = None   # (画面距離^2, 系列名, x, y)
        for label, ln in cands:
            try:
                xd = np.asarray(ln.get_xdata(), float)
                yd = np.asarray(ln.get_ydata(), float)
            except (TypeError, ValueError):
                continue
            if xd.size == 0 or xd.size != yd.size:
                continue
            m = np.isfinite(xd) & np.isfinite(yd)
            if not m.any():
                continue
            pts = ln.axes.transData.transform(np.column_stack([xd[m], yd[m]]))
            d2 = (pts[:, 0] - event.x) ** 2 + (pts[:, 1] - event.y) ** 2
            i = int(np.argmin(d2))
            if best is None or d2[i] < best[0]:
                best = (float(d2[i]), str(label), float(xd[m][i]), float(yd[m][i]))
        if best is not None and best[0] <= 20.0 ** 2:   # 20px以内の点だけ表示
            _, label, x, y = best
            lbl.setText(f"{label}:  X={plotter.format_eng(x)}  Y={plotter.format_eng(y)}  ")
        elif lbl.text():
            lbl.setText("")

    @staticmethod
    def _zoom_pair(lo, hi, center, factor, log=False):
        """[lo, hi] を center を中心に factor 倍に拡縮した新しい範囲を返す（log軸対応）。"""
        import numpy as np
        if log and lo > 0 and hi > 0 and center > 0:
            l0, l1, lc = np.log10(lo), np.log10(hi), np.log10(center)
            return 10.0 ** (lc - (lc - l0) * factor), 10.0 ** (lc + (l1 - lc) * factor)
        return center - (center - lo) * factor, center + (hi - center) * factor

    def auto_scale_scope(self):
        """選択中の全系列が収まるように time/div・V/div・中心を自動設定する。"""
        import numpy as np
        import pandas as pd
        items = self._selected_series_items()
        if not items:
            QtWidgets.QMessageBox.information(self, "情報", "データタブでY系列を選択してください。")
            return
        xname = self.x_combo.currentText()
        xspec = self.xscale_edit.text()   # 表示と同じ単位変換（倍率/式）を反映して範囲を求める
        yspec = self.yscale_edit.text()
        tmins, tmaxs, ymins, ymaxs = [], [], [], []
        for fl, col, _ in items:
            df = self.datasets[fl]
            raw = df[xname].to_numpy() if xname in df.columns else df.iloc[:, 0].to_numpy()
            tt = pd.to_numeric(pd.Series(raw), errors="coerce").to_numpy(dtype=float)
            if np.isnan(tt).mean() > 0.5:
                tt = np.arange(len(tt), dtype=float)
            yy = pd.to_numeric(pd.Series(df[col].to_numpy()), errors="coerce").to_numpy(dtype=float)
            tt = mathchan.axis_scale(tt, xspec)
            yy = mathchan.axis_scale(yy, yspec)
            tt, yy = tt[np.isfinite(tt)], yy[np.isfinite(yy)]
            if tt.size:
                tmins.append(tt.min()); tmaxs.append(tt.max())
            if yy.size:
                ymins.append(yy.min()); ymaxs.append(yy.max())
        if not tmins or not ymins:
            QtWidgets.QMessageBox.information(self, "情報", "数値データがありません。")
            return
        tmin, tmax = min(tmins), max(tmaxs)
        ymin, ymax = min(ymins), max(ymaxs)
        xd, yd = self.xdivs.value(), self.ydivs.value()
        tpd = (tmax - tmin) / xd if tmax > tmin else 1e-3
        vpd = (ymax - ymin) / (yd - 1) if ymax > ymin else 1.0
        self._suspend_redraw = True
        self.tdiv.setCurrentText(plotter.format_eng(tpd) + "s")
        self.vdiv.setCurrentText(plotter.format_eng(vpd))
        self.xpos.setText(f"{(tmin+tmax)/2:.4g}"); self.ypos.setText(f"{(ymin+ymax)/2:.4g}")
        self.scope_check.setChecked(True)
        self._suspend_redraw = False
        self.draw_graph()
