# -*- coding: utf-8 -*-
"""PlotMixin: GraphApp から分離した PlotMixin 群（挙動は本体と同一）。"""
from graph_app_common import *  # noqa: F401,F403


class PlotMixin:
    def _request_redraw(self, *args):
        """リアルタイム更新ON・描画済みのときだけ、デバウンスして再描画予約。"""
        if self._suspend_redraw or not self._has_drawn:
            return
        if not getattr(self, "live_check", None) or not self.live_check.isChecked():
            return
        self._redraw_timer.start(180)

    def _do_live_redraw(self):
        if self.datasets and self._has_drawn:
            self.draw_graph()

    # ------------------------------------------------------------ 描画
    def _on_chart_type_change(self, *_):
        ctype = self.chart_combo.currentText()
        info = plotter.CHART_INFO.get(ctype, {})
        self.hint_label.setText("➤ " + info.get("hint", ""))
        self._update_x_combo_enabled()
        uses_bins = ctype in ("ヒストグラム", "2Dヒストグラム", "hexbin")
        self.bins_spin.setEnabled(uses_bins)
        self.bins_caption.setEnabled(uses_bins)
        self.pct_check.setEnabled(ctype in ("円", "ドーナツ"))
        if hasattr(self, "series_bar"):
            self._rebuild_series_bar(ctype)   # 折れ線/散布図でのみ上部バーを出す

    def _build_series(self, chart_type):
        info = plotter.CHART_INFO[chart_type]
        items = self._selected_series_items()
        if not items:
            raise ValueError("Y軸（値）の系列を選択してください。")
        xname = self.x_combo.currentText()
        categories = None
        series = []

        def lbl(fl, col, disp, default):
            st = self.series_styles.get(self._style_key(fl, col)) or {}
            return st.get("label") or default

        if chart_type in ("棒", "横棒", "積み上げ棒", "円", "ドーナツ"):
            # 単一ファイル（最初に選んだ系列のファイル）を使う
            src = items[0][0]
            df = self.datasets[src]
            if not self._use_leftmost_x() and xname not in df.columns:
                raise ValueError(f"X軸の列『{xname}』が『{src}』にありません。")
            categories = self._x_values(df)
            for fl, col, disp in items:
                if fl != src:
                    continue
                series.append({"label": lbl(fl, col, disp, col), "y": self.datasets[fl][col].to_numpy(),
                               "style": self.series_styles.get(self._style_key(fl, col))})
        elif chart_type in ("折れ線", "散布図", "面", "積み上げ面",
                            "ステップ", "ステム", "2Dヒストグラム", "hexbin"):
            for fl, col, disp in items:
                df = self.datasets[fl]
                xv = self._x_values(df)
                stmap = self.series_styles.get(self._style_key(fl, col)) or {}
                errcol = stmap.get("errcol")
                yerr = df[errcol].to_numpy() if (errcol and errcol in df.columns) else None
                series.append({"label": self._series_label(fl, col), "x": xv, "y": df[col].to_numpy(),
                               "style": stmap,
                               "axis": stmap.get("axis", "primary"),
                               "kind": stmap.get("kind", ""),
                               "yerr": yerr})
        else:  # ヒストグラム / 箱ひげ
            for fl, col, disp in items:
                series.append({"label": self._series_label(fl, col), "y": self.datasets[fl][col].to_numpy(),
                               "style": self.series_styles.get(self._style_key(fl, col))})
        return series, categories

    def _scope_dict(self):
        return {
            "enabled": self.scope_check.isChecked(),
            "t_per_div": plotter.parse_eng(self.tdiv.currentText(), 1e-3),
            "v_per_div": plotter.parse_eng(self.vdiv.currentText(), 1.0),
            "x_pos": _parse_float(self.xpos.text(), 0.0),
            "y_pos": _parse_float(self.ypos.text(), 0.0),
            "x_divs": self.xdivs.value(),
            "y_divs": self.ydivs.value(),
        }

    def _fonts(self):
        return {"title": self.fs_title.value(), "label": self.fs_label.value(),
                "tick": self.fs_tick.value(),
                "legend": self.fs_legend.value(),
                "annot": self.fs_annot.value()}

    def _on_aspect_changed(self, *_):
        custom = self.aspect_combo.currentText() == "カスタム"
        self.aspect_w.setEnabled(custom)
        self.aspect_h.setEnabled(custom)
        self._request_redraw()

    def _aspect_ratio(self):
        """選択中の縦横比から box aspect（高さ/幅）を返す。自動は None。"""
        t = self.aspect_combo.currentText()
        presets = {"16:9": (16, 9), "4:3": (4, 3), "3:2": (3, 2), "1:1": (1, 1),
                   "9:16（縦）": (9, 16), "A4横": (297, 210), "A4縦": (210, 297)}
        if t in presets:
            w, h = presets[t]
        elif t == "カスタム":
            w, h = self.aspect_w.value(), self.aspect_h.value()
        else:
            return None
        return (h / w) if w else None

    def _apply_aspect(self):
        """プロット領域の縦横比を固定（None で解除）。第2軸にも適用。画面プレビュー用。"""
        ratio = self._aspect_ratio()
        try:
            self.ax.set_box_aspect(ratio)
            ax2 = getattr(self.ax, "_twin_secondary", None)
            if ax2 is not None:
                ax2.set_box_aspect(ratio)
        except Exception:
            pass

    def _export_figsize(self, base=7.0):
        """出力画像のサイズ(インチ)。選択比率があれば画像そのものをその比率にする。
        自動なら現在の図サイズ。ratio は高さ/幅。"""
        ratio = self._aspect_ratio()
        if not ratio:
            return tuple(self.fig.get_size_inches())
        if ratio <= 1.0:                 # 横長: 幅を base に
            return (base, base * ratio)
        return (base / ratio, base)      # 縦長: 高さを base に

    @staticmethod
    def _field_float(le):
        """QLineEdit を (値 or None, 妥当か) で返す。空欄は (None, True)。"""
        t = le.text().strip()
        if t == "":
            return None, True
        try:
            return float(t), True
        except ValueError:
            return None, False

    def _range_pair(self, le_min, le_max, name, issues):
        vmin, ok1 = self._field_float(le_min)
        vmax, ok2 = self._field_float(le_max)
        if not ok1:
            issues.append(f"{name}軸 最小値を数値として読めません")
        if not ok2:
            issues.append(f"{name}軸 最大値を数値として読めません")
        if vmin is not None and vmax is not None and vmin >= vmax:
            issues.append(f"{name}軸 最小≥最大のため範囲指定を無視しました")
            return (None, None)
        return (vmin, vmax)

    @staticmethod
    def _has_nonpositive(arrays):
        import numpy as np
        import pandas as pd
        for a in arrays:
            if a is None:
                continue
            v = pd.to_numeric(pd.Series(a), errors="coerce").to_numpy(dtype=float)
            v = v[np.isfinite(v)]
            if v.size and v.min() <= 0:
                return True
        return False

    def _plot_format_kwargs(self):
        """draw_graph と batch_export で共通の描画フォーマット設定を1か所に集約。
        新しい書式オプションはここに足せば両方（画面描画／一括出力）へ自動反映される。"""
        return dict(
            bins=self.bins_spin.value(),
            grid=self.grid_check.isChecked(),
            legend=self.legend_check.isChecked(),
            legend_loc=self.legend_loc.currentText(),
            xlog=self.xlog.isChecked(), ylog=self.ylog.isChecked(),
            pct=self.pct_check.isChecked(), fonts=self._fonts(),
            trendline={"type": self.trend_combo.currentText(),
                       "degree": self.trend_degree.value(),
                       "window": self.trend_window.value(),
                       "show_eq": self.trend_eq.isChecked(),
                       "color": getattr(self, "trend_color", "") or ""},
            data_labels=self.data_labels_check.isChecked(),
            xscale=self.xscale_edit.text(),   # 数値=倍率／x を使った式も可
            yscale=self.yscale_edit.text(),
            xunit=self.xunit_edit.text().strip(),
            yunit=self.yunit_edit.text().strip(),
            bg_color=getattr(self, "bg_color", "") or "",
            grid_width=self.grid_width.value(),
            frame_width=self.frame_width.value(),
            xinvert=self.xinvert_check.isChecked(),
            yinvert=self.yinvert_check.isChecked(),
        )

    def draw_graph(self):
        # 再入防止: busy描画中の processEvents() からデバウンス再描画が割り込むと、
        # 軸が中途半端な状態のまま再描画され不正なアーティストが残る。1回に直列化する。
        if getattr(self, "_drawing", False):
            return
        self._drawing = True
        try:
            self._draw_graph_body()
        finally:
            self._drawing = False

    def _draw_graph_body(self):
        if not self.datasets:
            QtWidgets.QMessageBox.information(self, "情報", "先にファイルを追加してください。")
            return
        # Y系列未選択は正常な一時状態。エラーのポップアップは出さず、空表示＋案内のみ。
        if not self._selected_series_items():
            self._draw_placeholder()
            self._rebuild_series_bar(self.chart_combo.currentText())
            self._set_status("Y軸（値）の系列をチェックするとグラフを表示します。")
            return
        ctype = self.chart_combo.currentText()
        issues = []
        xlim = self._range_pair(self.xmin, self.xmax, "X", issues)
        ylim = self._range_pair(self.ymin, self.ymax, "Y", issues)

        scope = self._scope_dict()
        if scope["enabled"] and ctype in ("折れ線", "散布図"):
            if not (scope["t_per_div"] and scope["t_per_div"] > 0
                    and scope["v_per_div"] and scope["v_per_div"] > 0):
                issues.append("time/div・V/div は正の値が必要（オシロ表示を無効化）")
                scope = dict(scope, enabled=False)

        self._clear_dynamic_resample()
        self._reset_figure_axes()   # スペクトログラム等のカラーバー軸を除去
        self._cursor_pts = []; self._cursor_artists = []  # 再描画で軸がクリアされる
        self._cursors = []; self._cursor_drag = None; self._cursor_text = None
        try:
            series, categories = self._build_series(ctype)
            if self.ylog.isChecked() and self._has_nonpositive([s["y"] for s in series]):
                issues.append("Y対数: 0以下の値は表示されません")
            if (self.xlog.isChecked() and ctype in ("折れ線", "散布図")
                    and self._has_nonpositive([s.get("x") for s in series])):
                issues.append("X対数: 0以下の値は表示されません")

            # 大容量データの間引き（折れ線/散布図のみ）
            total = sum(len(s.get("y", [])) for s in series)
            max_points = (DECIMATE_TARGET if (self.decimate_check.isChecked()
                          and ctype in ("折れ線", "散布図") and total > DECIMATE_TARGET) else 0)

            busy = total > BUSY_ROWS
            if busy:
                QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
                self._set_status(f"描画中…（{total:,} 点）"); QtWidgets.QApplication.processEvents()
            try:
                markers = self._peak_markers() if self.show_peaks_check.isChecked() else None
                sec_label = " / ".join(s["label"] for s in series
                                       if s.get("axis") == "secondary")
                plotter.plot_series(
                    self.ax, series, ctype, categories=categories,
                    title=self.title_edit.text(),
                    xlabel=self.xlabel_edit.text() or self._effective_x_label(),
                    ylabel=self.ylabel_edit.text() or self._effective_y_label(),
                    xlim=xlim, ylim=ylim,
                    scope=scope, markers=markers, max_points=max_points,
                    secondary_label=sec_label,
                    **self._plot_format_kwargs(),
                )
                self._apply_aspect()   # 縦横比の固定（自動なら解除）
                self._apply_tick_spacing(ctype, scope)   # 目盛り間隔（指定時）
                self._apply_fill_between(ctype, series)   # 系列間の塗りつぶし（選択時）
                self._draw_ds_annotations()              # データサイエンス注記（選択時）
                try:
                    self.fig.tight_layout()
                except Exception:
                    pass
                self.canvas.draw()
            finally:
                if busy:
                    QtWidgets.QApplication.restoreOverrideCursor()

            if max_points:
                self._setup_dynamic_resample(series, ctype, max_points)
            self._rebuild_series_bar(ctype)   # グラフ上部の系列選択バー
            # カーソル追従用に、実際に描画されたデータ線を保持（近似曲線は除く）
            self._plotted_artists = [
                (ln.get_label(), ln) for ln in self.ax.get_lines()
                if "近似" not in str(ln.get_label())]
            # スタイルのみ変更を即時反映するための skey->Line2D マップ（安全な場合のみ）
            self._style_artists = self._build_style_artist_map(series, ctype, bool(max_points))
            self._has_drawn = True
            self._snapshot()   # Undo/Redo 用に設定の履歴を記録
            msg = f"「{ctype}」を描画しました（系列 {len(series)}）。"
            if max_points:
                msg += f"（{total:,}点を間引き表示）"
            if issues:
                msg += "  ⚠ " + " / ".join(issues)
            self._set_status(msg)
        except Exception as e:  # noqa: BLE001
            applog.get_logger().exception("描画エラー")
            QtWidgets.QMessageBox.critical(self, "描画エラー", str(e))

    def _apply_tick_spacing(self, ctype, scope):
        """目盛り間隔（メモリ間隔）の手動指定を適用する。
        空欄や非対応（オシロdiv表示中・対数軸・カテゴリ軸・円）では何もしない。"""
        if ctype == "円":
            return
        if scope.get("enabled") and ctype in ("折れ線", "散布図"):
            return   # オシロ表示中は div 目盛りを優先
        from matplotlib.ticker import MultipleLocator
        dx = _parse_float(self.xtick_edit.text())
        dy = _parse_float(self.ytick_edit.text())

        def _too_many(lo, hi, step):
            # 間隔が範囲に対して小さすぎると数千の目盛りを生成し matplotlib が
            # MAXTICKS 警告を連発する。目盛りが多すぎる指定は無視する（暴走防止）。
            try:
                return abs(hi - lo) / step > 1000
            except (ZeroDivisionError, TypeError):
                return True

        # X目盛りは数値X（折れ線/散布図）でのみ意味を持つ。カテゴリ軸（棒/円）は対象外
        if (dx and dx > 0 and ctype in ("折れ線", "散布図")
                and self.ax.get_xscale() != "log"):
            x0, x1 = self.ax.get_xlim()
            if not _too_many(x0, x1, dx):
                try:
                    self.ax.xaxis.set_major_locator(MultipleLocator(dx))
                except Exception:
                    pass
        if dy and dy > 0 and self.ax.get_yscale() != "log":
            y0, y1 = self.ax.get_ylim()
            if not _too_many(y0, y1, dy):
                try:
                    self.ax.yaxis.set_major_locator(MultipleLocator(dy))
                except Exception:
                    pass

    def _apply_fill_between(self, ctype, series):
        """系列A と 系列B（または X軸=0）の間を塗りつぶす。折れ線/散布図のみ。
        描画は単位換算後の座標に合わせる（B が異なるXでも A の X に補間）。"""
        if not getattr(self, "fill_check", None) or not self.fill_check.isChecked():
            return
        if ctype not in ("折れ線", "散布図") or not series:
            return
        import numpy as np
        import pandas as pd
        items = self._selected_series_items()
        dispmap = {it[2]: s for it, s in zip(items, series)}
        a = dispmap.get(self.fill_a.currentText())
        if a is None or a.get("x") is None:
            return
        xspec = self.xscale_edit.text()
        yspec = self.yscale_edit.text()

        def sxy(s):
            x = mathchan.axis_scale(pd.to_numeric(pd.Series(s["x"]), errors="coerce").to_numpy(float), xspec)
            y = pd.to_numeric(pd.Series(s["y"]), errors="coerce").to_numpy(float)
            if s.get("axis") != "secondary":
                y = mathchan.axis_scale(y, yspec)
            return x, y

        xa, ya = sxy(a)
        bname = self.fill_b.currentText()
        if bname == "0（X軸）":
            yb = np.zeros_like(ya)
        else:
            b = dispmap.get(bname)
            if b is None or b.get("x") is None:
                return
            if (b.get("axis") or "primary") != (a.get("axis") or "primary"):
                # A と B が別軸だと座標系が混ざり塗り位置がズレる。同一軸のときだけ塗る。
                self._set_status("塗りつぶし: A と B は同じ軸の系列にしてください。")
                return
            xb, ybv = sxy(b)
            order = np.argsort(xb)
            yb = np.interp(xa, xb[order], ybv[order])
        color = self.fill_color or (a.get("style") or {}).get("color") or None
        target = self.ax
        if a.get("axis") == "secondary":
            target = getattr(self.ax, "_twin_secondary", None) or self.ax
        try:
            m = np.isfinite(xa) & np.isfinite(ya) & np.isfinite(yb)
            target.fill_between(xa, ya, yb, where=m, color=color,
                                alpha=self.fill_alpha.value(), zorder=0, linewidth=0)
        except Exception:
            pass

    def _draw_ds_annotations(self):
        """『表示』にチェックした指標をグラフへ注記する。
        データサイエンス＝左上、オシロ/解析の測定値＝右上に分けて描く。"""
        self._draw_annotation_box(getattr(self, "_ds_annotations", None), "tl")
        self._draw_annotation_box(getattr(self, "_meas_annotations", None), "tr")

    def _draw_annotation_box(self, anns, corner):
        """注記テキストボックスを指定コーナーに描く（注記フォントサイズを使用）。"""
        if not anns:
            return
        fs = self.fs_annot.value() if hasattr(self, "fs_annot") else 9
        x, y, ha, va = {"tl": (0.02, 0.98, "left", "top"),
                        "tr": (0.98, 0.98, "right", "top")}[corner]
        try:
            self.ax.text(
                x, y, "\n".join(anns), transform=self.ax.transAxes,
                ha=ha, va=va, fontsize=fs, zorder=20,
                bbox=dict(boxstyle="round", facecolor="white", alpha=0.8, edgecolor="#888"))
        except Exception:
            pass

    def _reset_figure_axes(self):
        """メイン軸以外（カラーバー等）を図から取り除く。"""
        for a in list(self.fig.axes):
            if a is not self.ax:
                try:
                    a.remove()
                except Exception:
                    pass
        # 系列選択バーの表示/非表示は _rebuild_series_bar が管理する（ここでは触らない）

    # ------------------------------------------------------------ ズーム再サンプル
    def _clear_dynamic_resample(self):
        if self._dyn_cid is not None:
            try:
                self.ax.callbacks.disconnect(self._dyn_cid)
            except Exception:
                pass
            self._dyn_cid = None
        self._dyn = []

    def _setup_dynamic_resample(self, series, ctype, max_points):
        """折れ線（数値X）について、間引き元の全データと描画線を保持し、
        ズーム時に表示範囲だけ再サンプルできるようにする。"""
        if ctype != "折れ線":
            return
        import numpy as np
        import pandas as pd
        # 描画線は単位換算後の座標を持つ。再サンプル元データにも同じ変換を掛けておかないと、
        # ズーム時に未換算座標へ戻り曲線が誤った位置/大きさに飛ぶ。
        xspec = self.xscale_edit.text()
        yspec = self.yscale_edit.text()
        lines = self.ax.get_lines()
        for i, s in enumerate(series):
            if i >= len(lines) or s.get("x") is None:
                continue
            fx = pd.to_numeric(pd.Series(s["x"]), errors="coerce").to_numpy(dtype=float)
            if np.isfinite(fx).mean() < 0.8:    # 数値Xのみ対象
                continue
            fy = pd.to_numeric(pd.Series(s["y"]), errors="coerce").to_numpy(dtype=float)
            fx = mathchan.axis_scale(fx, xspec)
            if s.get("axis") != "secondary":    # Y換算は主軸のみ（描画と同じ）
                fy = mathchan.axis_scale(fy, yspec)
            order = np.argsort(fx)
            self._dyn.append((lines[i], fx[order], fy[order], max_points))
        if self._dyn:
            self._dyn_cid = self.ax.callbacks.connect("xlim_changed", self._on_xlim_changed)

    def _on_xlim_changed(self, _ax):
        if self._resampling or not self._dyn:
            return
        self._resample_timer.start(120)

    def _do_resample(self):
        if not self._dyn:
            return
        import numpy as np
        x0, x1 = self.ax.get_xlim()
        if x1 < x0:
            x0, x1 = x1, x0
        margin = (x1 - x0) * 0.05
        self._resampling = True
        try:
            for line, fx, fy, mp in self._dyn:
                lo = np.searchsorted(fx, x0 - margin)
                hi = np.searchsorted(fx, x1 + margin)
                vx, vy = fx[lo:hi], fy[lo:hi]
                if vx.size == 0:
                    continue
                dx, dy = plotter.decimate_minmax(vx, vy, mp)
                line.set_data(dx, dy)
            self.canvas.draw_idle()
        finally:
            self._resampling = False

    def _draw_placeholder(self):
        self._reset_figure_axes()
        self.ax.clear()
        self.ax.set_facecolor("white"); self.ax.tick_params(colors="black")
        self.ax.text(0.5, 0.5, "『データ』タブでファイルを追加し、\n列を選んで「グラフを描画」",
                     ha="center", va="center", fontsize=12, color="#888",
                     transform=self.ax.transAxes)
        self.ax.set_xticks([]); self.ax.set_yticks([])
        self.canvas.draw()

    def _set_status(self, text):
        self.status.showMessage(text)
