# -*- coding: utf-8 -*-
"""PersistenceMixin: GraphApp から分離した PersistenceMixin 群（挙動は本体と同一）。"""
from graph_app_common import *  # noqa: F401,F403


class PersistenceMixin:
    def show_help(self):
        QtWidgets.QMessageBox.information(
            self, "使い方",
            "【基本の流れ】\n"
            "1. 『データ』タブで「ファイル追加」（ドラッグ&ドロップ可）\n"
            "2. X軸の列を選び、Y軸（値）は描きたい系列にチェック（行クリックでON/OFF・全選択ボタンあり）\n"
            "3. 「グラフを描画」(F5)。『リアルタイム更新』ONなら設定変更が即反映\n"
            "4. 右端の『グラフ書式調整』パネルで種別・色・軸範囲・系列スタイルなどを編集\n"
            "5. 波形は『オシロ/解析』タブで「解析実行」「FFT表示」「オシロスコープ表示」\n\n"
            "【出力】右端パネルの画像出力、またはメニュー「ファイル」から保存／コピー\n"
            "【グラフ種別と列】棒/円は1ファイル、折れ線/散布図は複数ファイル重ね描き可")

    def show_about(self):
        QtWidgets.QMessageBox.about(
            self, "バージョン情報",
            "CSV / TSV / 波形 グラフ・解析ツール\n"
            "PySide6 + matplotlib 製\n"
            f"日本語フォント: {self.font_name or '未検出'}")

    # ------------------------------------------------------------ 設定保存
    def _collect_config(self):
        return {
            "files": [self.meta[l]["path"] for l in self.datasets],
            "x_col": self.x_combo.currentText(),
            "x_leftmost": self.xleft_check.isChecked(),
            "selected_y": [[fl, col] for fl, col, _ in self._selected_series_items()],
            "chart_type": self.chart_combo.currentText(),
            "title": self.title_edit.text(),
            "xlabel": self.xlabel_edit.text(), "ylabel": self.ylabel_edit.text(),
            "fonts": self._fonts(),
            "grid": self.grid_check.isChecked(), "legend": self.legend_check.isChecked(),
            "legend_loc": self.legend_loc.currentText(),
            "show_filename": self.show_filename_check.isChecked(),
            "show_ext": self.show_ext_check.isChecked(),
            "frame_width": self.frame_width.value(), "grid_width": self.grid_width.value(),
            "xmin": self.xmin.text(), "xmax": self.xmax.text(),
            "ymin": self.ymin.text(), "ymax": self.ymax.text(),
            "xtick": self.xtick_edit.text(), "ytick": self.ytick_edit.text(),
            "xunit": self.xunit_edit.text(), "yunit": self.yunit_edit.text(),
            "xscale": self.xscale_edit.text(), "yscale": self.yscale_edit.text(),
            "xlog": self.xlog.isChecked(), "ylog": self.ylog.isChecked(),
            "xinvert": self.xinvert_check.isChecked(), "yinvert": self.yinvert_check.isChecked(),
            "bins": self.bins_spin.value(), "pct": self.pct_check.isChecked(),
            "trend": self.trend_combo.currentText(),
            "trend_degree": self.trend_degree.value(),
            "trend_window": self.trend_window.value(),
            "trend_eq": self.trend_eq.isChecked(),
            "trend_color": getattr(self, "trend_color", ""),
            "data_labels": self.data_labels_check.isChecked(),
            "aspect": self.aspect_combo.currentText(),
            "aspect_w": self.aspect_w.value(), "aspect_h": self.aspect_h.value(),
            "bg_color": getattr(self, "bg_color", ""),
            "export_dpi": self.dpi_spin.value(), "transparent": self.transparent_check.isChecked(),
            "recent_files": self.recent_files,
            "styles": self.series_styles,
            "scope": self._scope_dict(),
            "npeaks": self.npeaks.value(),
        }

    def _apply_config(self, cfg, load_files=True):
        prev_suspend = self._suspend_redraw
        self._suspend_redraw = True  # 復元中の連鎖再描画を抑制
        try:
            self._apply_config_inner(cfg, load_files)
        finally:
            self._suspend_redraw = prev_suspend

    def _apply_config_inner(self, cfg, load_files=True):
        rec = cfg.get("recent_files")
        if isinstance(rec, list):
            self.recent_files = [p for p in rec if isinstance(p, str)][:12]
            self._rebuild_recent_menu()
        if load_files:
            for p in cfg.get("files", []):
                if os.path.isfile(p):
                    self._load_file(p)
            self._refresh_columns()
        if cfg.get("x_col"):
            i = self.x_combo.findText(cfg["x_col"])
            if i >= 0:
                self.x_combo.setCurrentIndex(i)
        self.xleft_check.setChecked(bool(cfg.get("x_leftmost", False)))
        self._refresh_columns()
        # Y 選択を復元（安定した (ファイル, 列) 識別子で照合）
        want = set()
        for p in cfg.get("selected_y", []):
            if isinstance(p, (list, tuple)) and len(p) == 2:
                want.add((p[0], p[1]))
        self.y_list.blockSignals(True)
        for i in range(self.y_list.count()):
            it = self.y_list.item(i)
            it.setCheckState(QtCore.Qt.CheckState.Checked if it.data(UserRole) in want
                             else QtCore.Qt.CheckState.Unchecked)
        self.y_list.blockSignals(False)
        self.series_styles.update(cfg.get("styles", {}) or {})
        self.chart_combo.setCurrentText(cfg.get("chart_type", "折れ線"))
        self.title_edit.setText(cfg.get("title", ""))
        self.xlabel_edit.setText(cfg.get("xlabel", "")); self.ylabel_edit.setText(cfg.get("ylabel", ""))
        f = cfg.get("fonts", {})
        self.fs_title.setValue(f.get("title", 12)); self.fs_label.setValue(f.get("label", 10)); self.fs_tick.setValue(f.get("tick", 9))
        self.fs_legend.setValue(f.get("legend", 9)); self.fs_annot.setValue(f.get("annot", 9))
        self.grid_check.setChecked(cfg.get("grid", True)); self.legend_check.setChecked(cfg.get("legend", True))
        self.legend_loc.setCurrentText(cfg.get("legend_loc", "best"))
        self.show_filename_check.setChecked(cfg.get("show_filename", True))
        self.show_ext_check.setChecked(cfg.get("show_ext", True))
        self.frame_width.setValue(cfg.get("frame_width", 0.8))
        self.grid_width.setValue(cfg.get("grid_width", 0.8))
        self.xmin.setText(cfg.get("xmin", "")); self.xmax.setText(cfg.get("xmax", ""))
        self.ymin.setText(cfg.get("ymin", "")); self.ymax.setText(cfg.get("ymax", ""))
        self.xtick_edit.setText(cfg.get("xtick", "")); self.ytick_edit.setText(cfg.get("ytick", ""))
        self.xunit_edit.setText(cfg.get("xunit", "")); self.yunit_edit.setText(cfg.get("yunit", ""))
        self.xscale_edit.setText(cfg.get("xscale", "1")); self.yscale_edit.setText(cfg.get("yscale", "1"))
        self.xlog.setChecked(cfg.get("xlog", False)); self.ylog.setChecked(cfg.get("ylog", False))
        self.xinvert_check.setChecked(cfg.get("xinvert", False)); self.yinvert_check.setChecked(cfg.get("yinvert", False))
        self.bins_spin.setValue(cfg.get("bins", 30)); self.pct_check.setChecked(cfg.get("pct", True))
        self.trend_combo.setCurrentText(cfg.get("trend", "なし"))
        self.trend_degree.setValue(cfg.get("trend_degree", 2))
        self.trend_window.setValue(cfg.get("trend_window", 5))
        self.trend_eq.setChecked(cfg.get("trend_eq", True))
        tc = cfg.get("trend_color", "")
        if tc:
            self.trend_color = tc
            self.trend_color_btn.setText("色: " + tc)
            self.trend_color_btn.setStyleSheet(f"background:{tc};")
        else:
            self._reset_trend_color()
        self.data_labels_check.setChecked(cfg.get("data_labels", False))
        self.aspect_w.setValue(int(cfg.get("aspect_w", 16)))
        self.aspect_h.setValue(int(cfg.get("aspect_h", 9)))
        self.aspect_combo.setCurrentText(cfg.get("aspect", "自動（画面に合わせる）"))
        bgc = cfg.get("bg_color", "")
        if bgc:
            self.bg_color = bgc
            self.bg_btn.setText("背景色: " + bgc)
            self.bg_btn.setStyleSheet(f"background:{bgc};")
        else:
            self._reset_bg_color()
        self.dpi_spin.setValue(cfg.get("export_dpi", 150)); self.transparent_check.setChecked(cfg.get("transparent", False))
        sc = cfg.get("scope", {})
        self.scope_check.setChecked(sc.get("enabled", False))
        self.tdiv.setCurrentText(plotter.format_eng(sc.get("t_per_div") or 1e-3) + "s")
        self.vdiv.setCurrentText(plotter.format_eng(sc.get("v_per_div") or 0.5))
        self.xpos.setText(str(sc.get("x_pos", 0))); self.ypos.setText(str(sc.get("y_pos", 0)))
        self.xdivs.setValue(sc.get("x_divs", 10)); self.ydivs.setValue(sc.get("y_divs", 8))
        self.npeaks.setValue(cfg.get("npeaks", 5))
        self._rebuild_style_table()
        self._on_chart_type_change()

    def save_config_dialog(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "設定を保存", os.path.join(self.last_dir, "graph_config.json"),
            "JSON (*.json)")
        if not path:
            return
        try:
            config_io.save_config(self._collect_config(), path)
            self._set_status(f"設定を保存: {path}")
        except Exception as e:  # noqa: BLE001
            QtWidgets.QMessageBox.critical(self, "保存エラー", str(e))

    def load_config_dialog(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "設定を読み込み", self.last_dir, "JSON (*.json)")
        if not path:
            return
        cfg = config_io.load_config(path)
        if not cfg:
            QtWidgets.QMessageBox.warning(self, "読込エラー", "設定を読み込めませんでした。")
            return
        self._apply_config(cfg)
        self.draw_graph()
        self._set_status(f"設定を読み込み: {path}")

    def _try_restore_session(self):
        cfg = config_io.load_last_session()
        if not cfg or not cfg.get("files"):
            return False
        try:
            self._apply_config(cfg)
            if self.datasets:
                self.draw_graph()
            self._set_status("前回のセッションを復元しました。")
            return True
        except Exception:
            return False

    # ------------------------------------------------------------ 書式プリセット
    # 「データ/ファイル選択」に依存しない“見た目”だけを名前付きで保存・呼び出す。
    _PRESET_KEYS = ("chart_type", "fonts", "grid", "legend", "legend_loc",
                    "show_filename", "show_ext", "frame_width", "grid_width",
                    "xlog", "ylog", "xinvert", "yinvert", "bins", "pct", "data_labels",
                    "trend", "trend_degree", "trend_window", "trend_eq", "trend_color",
                    "bg_color", "aspect", "aspect_w", "aspect_h")

    def _presets_dir(self):
        d = os.path.join(config_io.APP_DIR, "presets")
        try:
            os.makedirs(d, exist_ok=True)
        except OSError:
            pass
        return d

    def _list_presets(self):
        import glob
        return sorted(os.path.splitext(os.path.basename(p))[0]
                      for p in glob.glob(os.path.join(self._presets_dir(), "*.json")))

    def _refresh_preset_combo(self, select=None):
        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()
        self.preset_combo.addItems(self._list_presets())
        if select:
            i = self.preset_combo.findText(select)
            if i >= 0:
                self.preset_combo.setCurrentIndex(i)
        self.preset_combo.blockSignals(False)

    def save_preset(self):
        import json
        name, ok = QtWidgets.QInputDialog.getText(self, "書式プリセット保存", "プリセット名:")
        name = (name or "").strip()
        if not ok or not name:
            return
        data = {k: v for k, v in self._collect_config().items() if k in self._PRESET_KEYS}
        try:
            with open(os.path.join(self._presets_dir(), name + ".json"), "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except OSError as e:  # noqa: BLE001
            QtWidgets.QMessageBox.warning(self, "保存", str(e))
            return
        self._refresh_preset_combo(select=name)
        self._set_status(f"書式プリセット「{name}」を保存しました。")

    def apply_preset(self):
        import json
        name = self.preset_combo.currentText()
        if not name:
            return
        try:
            with open(os.path.join(self._presets_dir(), name + ".json"), encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            QtWidgets.QMessageBox.warning(self, "適用", "プリセットを読み込めませんでした。")
            return
        self._apply_format(data)
        self._set_status(f"書式プリセット「{name}」を適用しました。")

    def delete_preset(self):
        name = self.preset_combo.currentText()
        if not name:
            return
        try:
            os.remove(os.path.join(self._presets_dir(), name + ".json"))
        except OSError:
            pass
        self._refresh_preset_combo()

    def _apply_format(self, d):
        """プリセット（見た目のみ）を現在のウィジェットへ適用。データ選択には触れない。"""
        prev = self._suspend_redraw
        self._suspend_redraw = True
        try:
            if "chart_type" in d:
                self.chart_combo.setCurrentText(d["chart_type"])
            f = d.get("fonts") or {}
            if f:
                self.fs_title.setValue(f.get("title", 12)); self.fs_label.setValue(f.get("label", 10))
                self.fs_tick.setValue(f.get("tick", 9)); self.fs_legend.setValue(f.get("legend", 9))
                self.fs_annot.setValue(f.get("annot", 9))
            for key, widget, kind in (
                    ("grid", self.grid_check, "chk"), ("legend", self.legend_check, "chk"),
                    ("legend_loc", self.legend_loc, "txt"),
                    ("show_filename", self.show_filename_check, "chk"),
                    ("show_ext", self.show_ext_check, "chk"),
                    ("frame_width", self.frame_width, "val"), ("grid_width", self.grid_width, "val"),
                    ("xlog", self.xlog, "chk"), ("ylog", self.ylog, "chk"),
                    ("xinvert", self.xinvert_check, "chk"), ("yinvert", self.yinvert_check, "chk"),
                    ("bins", self.bins_spin, "val"), ("pct", self.pct_check, "chk"),
                    ("data_labels", self.data_labels_check, "chk"),
                    ("trend", self.trend_combo, "txt"), ("trend_degree", self.trend_degree, "val"),
                    ("trend_window", self.trend_window, "val"), ("trend_eq", self.trend_eq, "chk")):
                if key in d:
                    if kind == "chk":
                        widget.setChecked(bool(d[key]))
                    elif kind == "txt":
                        widget.setCurrentText(d[key])
                    else:
                        widget.setValue(d[key])
            tc = d.get("trend_color", "")
            if tc:
                self.trend_color = tc; self.trend_color_btn.setText("色: " + tc)
                self.trend_color_btn.setStyleSheet(f"background:{tc};")
            bgc = d.get("bg_color", "")
            if bgc:
                self.bg_color = bgc; self.bg_btn.setText("背景色: " + bgc)
                self.bg_btn.setStyleSheet(f"background:{bgc};")
            if "aspect" in d:
                self.aspect_w.setValue(int(d.get("aspect_w", 16)))
                self.aspect_h.setValue(int(d.get("aspect_h", 9)))
                self.aspect_combo.setCurrentText(d["aspect"])
        finally:
            self._suspend_redraw = prev
        if self.datasets:
            self.draw_graph()

    # ------------------------------------------------------------ Undo / Redo
    def _snapshot(self):
        """現在の設定を履歴に記録（Undo/Redo 用）。直前と同じなら積まない。"""
        if getattr(self, "_restoring_undo", False):
            return
        import json
        cfg = self._collect_config()
        hist = getattr(self, "_hist", None)
        if hist is None:
            self._hist, self._hist_i = [cfg], 0
            return
        if json.dumps(cfg, ensure_ascii=False, sort_keys=True) == \
                json.dumps(self._hist[self._hist_i], ensure_ascii=False, sort_keys=True):
            return
        del self._hist[self._hist_i + 1:]      # redo 分岐を捨てる
        self._hist.append(cfg)
        if len(self._hist) > 50:               # 上限
            self._hist.pop(0)
        self._hist_i = len(self._hist) - 1

    def _apply_snapshot(self, cfg):
        self._restoring_undo = True
        try:
            self._apply_config(cfg, load_files=False)
            self.draw_graph()
        finally:
            self._restoring_undo = False

    def undo(self):
        hist = getattr(self, "_hist", None)
        if not hist or self._hist_i <= 0:
            self._set_status("これ以上戻せません。")
            return
        self._hist_i -= 1
        self._apply_snapshot(self._hist[self._hist_i])
        self._set_status("元に戻しました。")

    def redo(self):
        hist = getattr(self, "_hist", None)
        if not hist or self._hist_i >= len(hist) - 1:
            self._set_status("これ以上やり直せません。")
            return
        self._hist_i += 1
        self._apply_snapshot(self._hist[self._hist_i])
        self._set_status("やり直しました。")
