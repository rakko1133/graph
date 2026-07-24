# -*- coding: utf-8 -*-
"""ScopeTabMixin: 「オシロ/解析」タブ（1タブ=1ファイル）。

旧 scope_cursor.py（オシロ表示・カーソル・区間測定・パン/ズーム）と
旧 analysis_peaks.py（ピーク検出・自動測定・FFT表示・全系列一括解析）を統合。
共通の系列取り出し等は HostMixin（host.py）にあり、このタブはそれに依存する。
"""
from graph_app_common import *  # noqa: F401,F403


class ScopeTabMixin:
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
                applog.get_logger().debug("_clear_cursor_artists: 無視した例外", exc_info=True)
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
                applog.get_logger().debug("_cursor_near: 無視した例外", exc_info=True)
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
                applog.get_logger().debug("_update_cursor_readout: 無視した例外", exc_info=True)
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
                applog.get_logger().debug("_remove_scope_overlay: 無視した例外", exc_info=True)
            self._scope_ov = None

    def _shift_held(self, event=None):
        """Shift押下を判定。matplotlibの event.key はバックエンドによりスクロール時に
        Shiftを取りこぼすため、Qtのキーボード修飾キー状態を優先して見る。"""
        try:
            mods = QtWidgets.QApplication.keyboardModifiers()
            if bool(mods & QtCore.Qt.KeyboardModifier.ShiftModifier):
                return True
        except Exception:
            applog.get_logger().debug("_shift_held: 無視した例外", exc_info=True)
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
                    applog.get_logger().debug("toggle_gate: 無視した例外", exc_info=True)
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

    def _hover_lines(self, ax):
        """ホバー対象の (系列名, Line2D) 候補（対象軸＋重なる第2軸/主軸）。"""
        axs = [ax]
        twin = getattr(ax, "_twin_secondary", None)
        if twin is not None:
            axs.append(twin)
        if ax is getattr(self.ax, "_twin_secondary", None):
            axs.append(self.ax)
        return [(str(ln.get_label()), ln) for a in axs for ln in a.get_lines()
                if not str(ln.get_label()).startswith("_")
                and "近似" not in str(ln.get_label())]

    def _hover_values(self, ax, x_disp):
        """表示X座標 x_disp における各系列の値 [(名前, 色, x, y), ...] を返す。
        各系列の最近傍点を採用する（Grafana風の全系列読み出し）。"""
        import numpy as np
        out = []
        for label, ln in self._hover_lines(ax):
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
            xs, ys = xd[m], yd[m]
            i = int(np.argmin(np.abs(xs - x_disp)))
            out.append((label, ln.get_color(), float(xs[i]), float(ys[i])))
        return out

    def _hover_readout(self, event):
        """ホバー位置の全系列の値をツールチップに、最近傍点をステータスバーに表示し、
        十字カーソルを重ねる（Grafana風）。対数軸・単位換算後の表示座標でも正しい。"""
        lbl = getattr(self, "_hover_label", None)
        if lbl is None:
            return
        ax = event.inaxes
        if (ax is None or ax not in self.fig.axes or event.x is None
                or event.xdata is None
                or not getattr(self, "_has_drawn", False)
                or getattr(ax, "name", None) == "3d"
                or ax.get_label() == "<colorbar>"
                or self._scope_drag or self._cursor_drag is not None):
            if lbl.text():
                lbl.setText("")
            self._hide_hover_ui()
            return
        import time
        now = time.monotonic()
        if now - getattr(self, "_hover_t", 0.0) < 0.05:   # 20Hzに間引き（負荷対策）
            return
        self._hover_t = now
        import numpy as np
        vals = self._hover_values(ax, float(event.xdata))
        # ステータスバー右には従来どおり「最近傍1点」を出す
        best = None
        for label, _c, x, y in vals:
            pt = ax.transData.transform([[x, y]])[0]
            d2 = (pt[0] - event.x) ** 2 + (pt[1] - event.y) ** 2
            if best is None or d2 < best[0]:
                best = (d2, label, x, y)
        if best is not None and best[0] <= 20.0 ** 2:
            _, label, x, y = best
            lbl.setText(f"{label}:  X={plotter.format_eng(x)}  Y={plotter.format_eng(y)}  ")
        elif lbl.text():
            lbl.setText("")
        # 全系列ツールチップ（色付き・最大12系列）
        if vals:
            rows = [f"<b>X = {plotter.format_eng(float(event.xdata))}</b>"]
            for label, color, _x, y in vals[:12]:
                rows.append(f"<span style='color:{color}'>■</span> "
                            f"{label}: <b>{plotter.format_eng(y)}</b>")
            if len(vals) > 12:
                rows.append(f"…他 {len(vals) - 12} 系列")
            QtWidgets.QToolTip.showText(QtGui.QCursor.pos(),
                                        "<br>".join(rows), self.canvas)
        else:
            QtWidgets.QToolTip.hideText()
        self._draw_crosshair(ax, event.xdata, event.ydata)

    # ---- 十字カーソル（blit描画。通常の再描画には含まれない animated アーティスト）----
    def _hide_hover_ui(self):
        QtWidgets.QToolTip.hideText()
        if getattr(self, "_xhair_bg", None) is None:
            return
        size = (int(self.fig.bbox.width), int(self.fig.bbox.height),
                self.canvas.width(), self.canvas.height())
        if getattr(self, "_xhair_size", None) != size or getattr(self, "_drawing", False):
            self._xhair_bg = None   # サイズ不一致の背景は書き戻さない（クラッシュ対策）
            return
        try:
            self.canvas.restore_region(self._xhair_bg)
            self.canvas.blit(self.fig.bbox)
        except Exception:
            applog.get_logger().debug("_hide_hover_ui: 無視した例外", exc_info=True)
        self._xhair_bg = None

    def _invalidate_crosshair(self, *_):
        """本描画のたびに背景キャッシュを捨てる（draw_eventで呼ばれる）。"""
        self._xhair_bg = None

    def _draw_crosshair(self, ax, x, y):
        # 区間測定(SpanSelector)やカーソル測定は独自のblit/ドラッグを持つため干渉を避ける
        if (x is None or y is None
                or (getattr(self, "gate_btn", None) and self.gate_btn.isChecked())
                or self._cursor_cid is not None
                or getattr(self.toolbar, "mode", "")):
            return
        xh = getattr(self, "_xhair", None)
        if not xh or xh[0].axes is not ax:   # 軸が変わった/消えたら作り直す
            if xh:
                for a in xh:
                    try:
                        a.remove()
                    except Exception:
                        applog.get_logger().debug("_draw_crosshair: 無視した例外", exc_info=True)
            v = ax.axvline(x, color="#888", lw=0.7, ls="--", animated=True, zorder=30)
            h = ax.axhline(y, color="#888", lw=0.7, ls="--", animated=True, zorder=30)
            self._xhair = (v, h)
            self._xhair_bg = None
        # キャンバスサイズが変わっていたら背景キャッシュを捨てる。サイズ違いの
        # 背景を restore_region で書き戻すとネイティブレベルで落ちることがある
        # （起動直後の初回描画・リサイズ中にマウスが乗っていたときの間欠クラッシュ対策。
        # アクセス違反は Python の except では捕まらないため、事前チェックが必須）。
        size = (int(self.fig.bbox.width), int(self.fig.bbox.height),
                self.canvas.width(), self.canvas.height())
        if getattr(self, "_xhair_size", None) != size:
            self._xhair_bg = None
        if getattr(self, "_drawing", False):
            return   # 本描画の最中はblitしない（バッファが確定していない）
        try:
            if getattr(self, "_xhair_bg", None) is None:
                self._xhair_bg = self.canvas.copy_from_bbox(self.fig.bbox)
                self._xhair_size = size
            self.canvas.restore_region(self._xhair_bg)
            self._xhair[0].set_xdata([x, x])
            self._xhair[1].set_ydata([y, y])
            ax.draw_artist(self._xhair[0])
            ax.draw_artist(self._xhair[1])
            self.canvas.blit(self.fig.bbox)
        except Exception:   # バックエンド差異等では静かに諦める（ツールチップは生きる）
            self._xhair_bg = None

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
            self.notify("データタブでY系列を選択してください。", "warn")
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
            self.notify("数値データがありません。", "warn")
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

    def _build_tab_scope(self):
        w = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(w)

        self.scope_check = QtWidgets.QCheckBox("オシロスコープ表示（折れ線/散布図）")
        v.addWidget(self.scope_check)
        g = QtWidgets.QGridLayout()
        g.addWidget(QtWidgets.QLabel("time/div [s]"), 0, 0)
        self.tdiv = QtWidgets.QComboBox(); self.tdiv.setEditable(True)
        self.tdiv.addItems(plotter.eng_125_sequence(1e-9, 1.0, "s"))
        self.tdiv.setCurrentText("1ms")
        g.addWidget(self.tdiv, 0, 1)
        g.addWidget(QtWidgets.QLabel("V/div"), 0, 2)
        self.vdiv = QtWidgets.QComboBox(); self.vdiv.setEditable(True)
        self.vdiv.addItems(plotter.eng_125_sequence(1e-3, 100.0, ""))
        self.vdiv.setCurrentText("500m")
        g.addWidget(self.vdiv, 0, 3)
        g.addWidget(QtWidgets.QLabel("X位置(中心)"), 1, 0)
        self.xpos = QtWidgets.QLineEdit("0"); g.addWidget(self.xpos, 1, 1)
        g.addWidget(QtWidgets.QLabel("Y位置(中心)"), 1, 2)
        self.ypos = QtWidgets.QLineEdit("0"); g.addWidget(self.ypos, 1, 3)
        g.addWidget(QtWidgets.QLabel("X div数"), 2, 0)
        self.xdivs = QtWidgets.QSpinBox(); self.xdivs.setRange(2, 20); self.xdivs.setValue(10)
        g.addWidget(self.xdivs, 2, 1)
        g.addWidget(QtWidgets.QLabel("Y div数"), 2, 2)
        self.ydivs = QtWidgets.QSpinBox(); self.ydivs.setRange(2, 20); self.ydivs.setValue(8)
        g.addWidget(self.ydivs, 2, 3)
        v.addLayout(g)
        b_auto = QtWidgets.QPushButton("自動スケール（解析対象に合わせる）")
        b_auto.clicked.connect(self.auto_scale_scope)
        v.addWidget(b_auto)
        scope_hint = QtWidgets.QLabel(
            "💡 オシロ表示中はグラフを直接操作可：左ドラッグ=位置移動／右ドラッグ=time/V/div／"
            "ホイール=time/div・Shift+ホイール=V/div（ドラッグ中は数値を表示）")
        scope_hint.setWordWrap(True); scope_hint.setStyleSheet("color:#0a7a55; font-size:11px;")
        v.addWidget(scope_hint)

        v.addWidget(self._hline())
        # 解析対象
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("解析対象:"))
        self.analysis_target = QtWidgets.QComboBox()
        row.addWidget(self.analysis_target, 1)
        v.addLayout(row)
        row2 = QtWidgets.QHBoxLayout()
        row2.addWidget(QtWidgets.QLabel("ピーク数 N:"))
        self.npeaks = QtWidgets.QSpinBox(); self.npeaks.setRange(1, 50); self.npeaks.setValue(5)
        row2.addWidget(self.npeaks)
        row2.addWidget(QtWidgets.QLabel("平滑化(点):"))
        self.smooth_spin = QtWidgets.QSpinBox(); self.smooth_spin.setRange(0, 501)
        self.smooth_spin.setSingleStep(2); self.smooth_spin.setValue(0)
        self.smooth_spin.setToolTip("ノイズの多い実測データで偽ピークを抑える。0=平滑化なし。窓の点数（奇数推奨）。")
        row2.addWidget(self.smooth_spin); row2.addStretch(1)
        v.addLayout(row2)
        self.show_peaks_check = QtWidgets.QCheckBox("ピークをグラフに表示"); self.show_peaks_check.setChecked(False)
        v.addWidget(self.show_peaks_check)
        self.window_meas_check = QtWidgets.QCheckBox("表示範囲のみ測定（ズーム/オシロ窓に追従）")
        self.window_meas_check.setToolTip("オンにすると、画面に見えているX範囲だけを対象に解析します。")
        v.addWidget(self.window_meas_check)
        # 解析アクションは4個。1行に詰めると見切れるので2段に分ける
        b_an = QtWidgets.QPushButton("解析実行"); b_an.clicked.connect(self.run_analysis)
        b_an.setToolTip("解析対象コンボで選んだ1系列のピーク・測定を下の表に表示")
        b_all = QtWidgets.QPushButton("全系列を解析…")
        b_all.setToolTip("選択中の全系列のピーク・測定を別ウィンドウに一覧表示（CSV保存可）")
        b_all.clicked.connect(self.analyze_all_series)
        b_fft = QtWidgets.QPushButton("FFT表示"); b_fft.clicked.connect(self.show_fft)
        b_fft.setToolTip("FFTスペクトル表示：選択中の全系列のFFTを1枚に重ね描き（系列ごとに色分け）")
        b_cur = QtWidgets.QPushButton("カーソル測定"); b_cur.setCheckable(True)
        b_cur.setToolTip("グラフを2回クリックして Δt・ΔV・1/Δt を測ります")
        b_cur.toggled.connect(self.toggle_cursors)
        self.cursor_btn = b_cur
        # 1行目=実行系（押すと計算して表を更新）、2行目=測定モード系（ON/OFFトグル）
        brow = QtWidgets.QHBoxLayout()
        brow.addWidget(b_an); brow.addWidget(b_all); brow.addWidget(b_fft)
        v.addLayout(brow)
        b_gate = QtWidgets.QPushButton("区間測定")
        b_gate.setCheckable(True)
        b_gate.setToolTip("ONにしてグラフ上を横にドラッグすると、選んだX区間だけの\n"
                          "測定値（平均/RMS/周期など）を下の表に表示します。")
        b_gate.toggled.connect(self.toggle_gate)
        self.gate_btn = b_gate
        brow2 = QtWidgets.QHBoxLayout()
        brow2.addWidget(b_cur); brow2.addWidget(b_gate)
        v.addLayout(brow2)

        v.addWidget(self._bold("ピーク（第1=最大）"))
        self.peak_table = QtWidgets.QTableWidget(0, 3)
        self.peak_table.setHorizontalHeaderLabels(["順位", "時間/周波数", "値"])
        self.peak_table.horizontalHeader().setStretchLastSection(True)
        self.peak_table.setMaximumHeight(160)
        self._wire_table_export(self.peak_table, "ピーク")
        v.addWidget(self.peak_table)

        v.addWidget(self._bold("測定値（右端「表示」でグラフに注記）"))
        self.meas_table = QtWidgets.QTableWidget(0, 3)
        self.meas_table.setHorizontalHeaderLabels(["項目", "値", "表示"])
        mh = self.meas_table.horizontalHeader()
        mh.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        mh.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Stretch)
        mh.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        self.meas_table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self._wire_table_export(self.meas_table, "測定値")
        v.addWidget(self.meas_table, 1)
        # 統計・トレンド・位相
        srow = QtWidgets.QHBoxLayout()
        b_stat = QtWidgets.QPushButton("サイクル統計"); b_stat.clicked.connect(self.show_cycle_stats)
        b_trend = QtWidgets.QPushButton("トレンド表示"); b_trend.clicked.connect(self.show_trend)
        b_pstat = QtWidgets.QPushButton("パラメータ統計…")
        b_pstat.setToolTip("サイクルごとの統計（平均/最大/最小/σ）とパラメータ間演算を別ウィンドウで表示")
        b_pstat.clicked.connect(self.show_param_stats)
        srow.addWidget(b_stat); srow.addWidget(b_trend); srow.addWidget(b_pstat)
        v.addLayout(srow)
        prow = QtWidgets.QHBoxLayout()
        prow.addWidget(QtWidgets.QLabel("位相差 対象2:"))
        self.phase_target2 = QtWidgets.QComboBox(); prow.addWidget(self.phase_target2, 1)
        b_phase = QtWidgets.QPushButton("位相差/遅延"); b_phase.clicked.connect(self.show_phase)
        prow.addWidget(b_phase)
        v.addLayout(prow)
        return w


    # ------------------------------------------------------------ 解析

    def _peak_markers(self):
        if self.chart_combo.currentText() not in ("折れ線", "散布図"):
            return None
        t, y, _ = self._analysis_xy()
        if t is None:
            return None
        try:
            peaks = analysis.find_signal_peaks(y, t=t, n=self.npeaks.value(),
                                               smooth=self.smooth_spin.value())
        except Exception:
            return None
        # マーカーは表示座標（単位変換後）に合わせる。生座標のままだと倍率/式で線とズレる。
        xspec, yspec = self.xscale_edit.text(), self.yscale_edit.text()
        out = []
        for p in peaks:
            if p["time"] is None:
                continue
            out.append({"x": float(mathchan.axis_scale([p["time"]], xspec)[0]),
                        "y": float(mathchan.axis_scale([p["value"]], yspec)[0]),
                        "text": f"第{p['rank']}", "color": "#ff3030"})
        return out

    def run_analysis(self):
        got = self.analysis_xy_or_warn()
        if got is None:
            return
        t, y, label = got
        import numpy as np
        y = np.asarray(y, float)
        res = analysis.analyze(t, y, n_peaks=self.npeaks.value(),
                               smooth=self.smooth_spin.value())
        self._show_analysis_result(res, f"解析しました: {label}")

    def _run_gated_analysis(self, x0, x1):
        """区間測定: 表示座標 [x0, x1] の範囲だけを解析して表に表示する。"""
        import numpy as np
        t, y, label = self._analysis_xy()
        if t is None:
            self._set_status("区間測定: 『オシロ/解析』の解析対象で系列を選択してください。")
            return
        t = np.asarray(t, float)
        # 画面のX座標は単位変換後。生の t を同じ変換にかけてから区間を切り出す
        t_disp = mathchan.axis_scale(t, self.xscale_edit.text())
        mask = (t_disp >= x0) & (t_disp <= x1)
        if int(mask.sum()) < 3:
            self._set_status("区間測定: 選択した区間のデータ点が少なすぎます（3点以上必要）。")
            return
        res = analysis.analyze(t[mask], np.asarray(y, float)[mask],
                               n_peaks=self.npeaks.value(), smooth=self.smooth_spin.value())
        self._show_analysis_result(
            res,
            f"区間測定 [{plotter.format_eng(x0)} 〜 {plotter.format_eng(x1)}]: "
            f"{label}（{int(mask.sum()):,}点）", redraw_ok=False)

    def _show_analysis_result(self, res, status, redraw_ok=True):
        """解析結果（ピーク・測定値）を表に反映する（解析実行・区間測定で共通）。"""
        self.peak_table.setRowCount(len(res["peaks"]))
        for r, p in enumerate(res["peaks"]):
            self.peak_table.setItem(r, 0, QtWidgets.QTableWidgetItem(f"第{p['rank']}"))
            tv = "-" if p["time"] is None else f"{p['time']*1e3:.4g} ms"
            self.peak_table.setItem(r, 1, QtWidgets.QTableWidgetItem(tv))
            self.peak_table.setItem(r, 2, QtWidgets.QTableWidgetItem(f"{p['value']:.4g}"))

        rows = res["measurements"]
        had_ann = bool(getattr(self, "_meas_annotations", None))
        self._meas_annotations = []   # 新しい解析を表示したら前回の注記はリセット
        self.meas_table.setRowCount(len(rows))
        for r, m in enumerate(rows):
            val = m["value"]
            txt = "-" if val is None else f"{val:.6g} {m['unit']}"
            self.meas_table.setItem(r, 0, QtWidgets.QTableWidgetItem(m["name"]))
            self.meas_table.setItem(r, 1, QtWidgets.QTableWidgetItem(txt))
            cb = QtWidgets.QCheckBox()
            cb.setToolTip("チェックすると、この測定値をグラフ上に注記表示します。")
            cb.toggled.connect(self._refresh_meas_annotations)
            self.meas_table.setCellWidget(r, 2, cb)

        if redraw_ok and (self.show_peaks_check.isChecked() or had_ann):
            self.draw_graph()   # ピーク表示中、または前回の注記を消すため
        self._set_status(status)

    def _refresh_meas_annotations(self, *_):
        """測定値表で『表示』にチェックした行を集めてグラフへ注記表示する。"""
        anns = []
        for r in range(self.meas_table.rowCount()):
            cb = self.meas_table.cellWidget(r, 2)
            if cb is not None and cb.isChecked():
                k = self.meas_table.item(r, 0)
                val = self.meas_table.item(r, 1)
                if k is not None and val is not None:
                    anns.append(f"{k.text()} = {val.text()}")
        self._meas_annotations = anns
        if self.datasets:   # 特殊表示(スペクトログラム等)直後でも通常グラフへ再描画して反映
            self.draw_graph()

    def show_fft(self):
        """選択中の全系列のFFTスペクトルを1枚に重ね描き（系列ごとに色分け・凡例）。"""
        items = self._selected_series_items()
        if not items:
            self.notify("解析する系列を選択してください。", "warn")
            return
        import numpy as np
        win = self.fft_window.currentText() if hasattr(self, "fft_window") else "hann"
        use_db = hasattr(self, "fft_db") and self.fft_db.isChecked()
        ylab = "振幅 [dBV]" if use_db else "振幅"
        series, markers, drawn = [], [], 0
        for idx, (fl, col, disp) in enumerate(items):
            t, y = self._xy_for(fl, col)
            if t is None or len(np.asarray(y)) < 4:
                continue
            freqs, amp = analysis.fft_spectrum(t, np.asarray(y, float), window=win)
            if freqs is None:
                continue
            color = (self.series_styles.get(self._style_key(fl, col)) or {}).get("color") \
                or f"C{idx % 10}"        # 系列の指定色、無ければ既定カラーサイクル
            disp_amp = analysis.to_db(amp) if use_db else amp
            series.append({"label": f"FFT: {disp}", "x": freqs, "y": disp_amp,
                           "style": {"color": color, "linewidth": 1.0}})
            for p in analysis.find_spectral_peaks(t, np.asarray(y, float), n=self.npeaks.value()):
                yv = analysis.to_db(np.array([p["amplitude"]]))[0] if use_db else p["amplitude"]
                markers.append({"x": p["frequency"], "y": yv,
                                "text": f"{p['frequency']:.0f}Hz", "color": color})
            drawn += 1
        if drawn == 0:
            self.notify("FFT を計算できませんでした。", "warn")
            return
        self._ensure_axes_projection(False)   # 3D表示中でも2D軸に戻して描く
        self._reset_figure_axes()
        plotter.plot_series(
            self.ax, series, "折れ線",
            title=f"FFTスペクトル（{win}窓・{drawn}系列）", xlabel="周波数 [Hz]", ylabel=ylab,
            grid=True, legend=(drawn > 1), markers=markers, fonts=self._fonts())
        self._apply_aspect()   # 縦横比の設定をFFT表示にも適用（自動なら解除）
        try:
            self.fig.tight_layout()
        except Exception:
            applog.get_logger().debug("show_fft: 無視した例外", exc_info=True)
        self.canvas.draw()
        self._set_status(f"FFT表示: {drawn}系列を重ね描き")

    # -------------------------------------------------- 全系列の一括解析（別ウィンドウ・CSV保存）
    def analyze_all_series(self):
        """選択中の全系列のピーク＋測定を計算し、別ウィンドウ（表＋CSV保存）で表示する。"""
        items = self._selected_series_items()
        if not items:
            self.notify("解析する系列を選択してください。", "warn")
            return
        import numpy as np
        peak_rows, meas_rows = [], []
        for fl, col, disp in items:
            t, y = self._xy_for(fl, col)
            if t is None or len(np.asarray(y)) < 2:
                continue
            r = analysis.analyze(t, np.asarray(y, float),
                                 n_peaks=self.npeaks.value(), smooth=self.smooth_spin.value())
            for p in r["peaks"]:
                tv = None if p["time"] is None else p["time"] * 1e3
                peak_rows.append((disp, f"第{p['rank']}", tv, p["value"]))
            for m in r["measurements"]:
                meas_rows.append((disp, m["name"], m["value"], m["unit"]))
        if not peak_rows and not meas_rows:
            self.notify("解析できる系列がありません。", "warn")
            return
        self._show_analysis_window(peak_rows, meas_rows)

    def _show_analysis_window(self, peak_rows, meas_rows):
        """系列ごとのピーク・測定を2つの表で別ウィンドウ表示。CSV保存ボタン付き。"""
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("全系列の解析結果")
        dlg.resize(760, 600)
        lay = QtWidgets.QVBoxLayout(dlg)
        no_edit = QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers

        lay.addWidget(QtWidgets.QLabel("■ ピーク（系列ごと）"))
        pk = QtWidgets.QTableWidget(len(peak_rows), 4)
        pk.setHorizontalHeaderLabels(["系列", "順位", "時刻", "値"])
        pk.setEditTriggers(no_edit)
        for r, (s, rank, tv, val) in enumerate(peak_rows):
            pk.setItem(r, 0, QtWidgets.QTableWidgetItem(str(s)))
            pk.setItem(r, 1, QtWidgets.QTableWidgetItem(str(rank)))
            pk.setItem(r, 2, QtWidgets.QTableWidgetItem("-" if tv is None else f"{tv:.4g} ms"))
            pk.setItem(r, 3, QtWidgets.QTableWidgetItem(f"{val:.6g}"))
        pk.resizeColumnsToContents()
        self._wire_table_export(pk, "全系列ピーク")
        lay.addWidget(pk)

        lay.addWidget(QtWidgets.QLabel("■ 測定（系列ごと）"))
        ms = QtWidgets.QTableWidget(len(meas_rows), 4)
        ms.setHorizontalHeaderLabels(["系列", "項目", "値", "単位"])
        ms.setEditTriggers(no_edit)
        for r, (s, name, val, unit) in enumerate(meas_rows):
            ms.setItem(r, 0, QtWidgets.QTableWidgetItem(str(s)))
            ms.setItem(r, 1, QtWidgets.QTableWidgetItem(str(name)))
            ms.setItem(r, 2, QtWidgets.QTableWidgetItem("-" if val is None else f"{val:.6g}"))
            ms.setItem(r, 3, QtWidgets.QTableWidgetItem(str(unit)))
        ms.resizeColumnsToContents()
        self._wire_table_export(ms, "全系列測定")
        lay.addWidget(ms, 1)

        brow = QtWidgets.QHBoxLayout()
        b_save = QtWidgets.QPushButton("CSVで保存…")
        b_save.clicked.connect(lambda: self._save_analysis_csv(peak_rows, meas_rows))
        b_close = QtWidgets.QPushButton("閉じる")
        b_close.clicked.connect(dlg.close)
        brow.addStretch(1); brow.addWidget(b_save); brow.addWidget(b_close)
        lay.addLayout(brow)
        self._analysis_window = dlg   # 参照保持（GCで即閉じしないように）
        dlg.show()

    def _save_analysis_csv(self, peak_rows, meas_rows):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "解析結果をCSVで保存", self.last_dir, "CSV (*.csv)")
        if not path:
            return
        import csv
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                w.writerow(["# ピーク"])
                w.writerow(["系列", "順位", "時刻[ms]", "値"])
                for s, rank, tv, val in peak_rows:
                    w.writerow([s, rank, "" if tv is None else f"{tv:.6g}", f"{val:.6g}"])
                w.writerow([])
                w.writerow(["# 測定"])
                w.writerow(["系列", "項目", "値", "単位"])
                for s, name, val, unit in meas_rows:
                    w.writerow([s, name, "" if val is None else f"{val:.6g}", unit])
            self.last_dir = os.path.dirname(path)
            self._set_status(f"解析結果を保存しました: {path}")
        except Exception as e:  # noqa: BLE001
            QtWidgets.QMessageBox.critical(self, "保存エラー", str(e))
