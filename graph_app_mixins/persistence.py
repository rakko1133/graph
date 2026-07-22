# -*- coding: utf-8 -*-
"""PersistenceMixin: GraphApp から分離した PersistenceMixin 群（挙動は本体と同一）。"""
from graph_app_common import *  # noqa: F401,F403


class PersistenceMixin:
    def show_help(self):
        # 使い方は読み込む文章なので、通知バーではなくスクロールできる窓で出す。
        self._show_text_window("使い方", self._HELP_TEXT)

    def _show_text_window(self, title, text):
        """長い文章を読むための独立ウィンドウ（選択・コピー可・スクロール可）。"""
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle(title)
        dlg.resize(760, 560)
        lay = QtWidgets.QVBoxLayout(dlg)
        view = QtWidgets.QPlainTextEdit(text)
        view.setReadOnly(True)
        view.setAccessibleName(title)
        lay.addWidget(view)
        btns = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Close)
        btns.rejected.connect(dlg.reject)
        btns.accepted.connect(dlg.accept)
        lay.addWidget(btns)
        self._text_window = dlg     # テストから参照できるように保持
        dlg.exec()
        return dlg

    _HELP_TEXT = ("【基本の流れ】\n"
                    "1. 『データ』パネルで「ファイル追加」（ドラッグ&ドロップ可）\n"
                    "2. ツリーでファイルを展開し、描きたい列（Y軸）にチェック（行クリックでON/OFF・\n"
                    "   ダブルクリック=その列だけ表示・右クリックでメニュー）。X軸の列は下のコンボで選択\n"
                    "3. 「グラフを描画」(F5)。『リアルタイム更新』ONなら設定変更が即反映\n"
                    "4. 右端の『グラフ書式調整』パネルで種別・色・軸範囲・系列スタイルなどを編集\n"
                    "   （項目は見出しクリックで開閉できます。開閉状態・ウィンドウ配置は次回起動時に復元）\n"
                    "※ パネルの切り離し（別ウィンドウ化）は3通り:\n"
                    "   ①タブをダブルクリック ②タブを外へドラッグ ③表示メニュー「別ウィンドウで表示」\n"
                    "   切り離したウィンドウはWindowsのスナップ対応（画面端へドラッグ／Win+矢印／\n"
                    "   最大化ボタンにマウスでレイアウト選択）。元に戻す: タイトルバーをダブルクリック、\n"
                    "   メインウィンドウの左右端へドロップ、または表示メニューのチェックを外す。\n"
                    "   ✕で閉じたパネルは表示メニューで再表示、「パネル配置をリセット」で初期配置へ\n"
                    "5. 波形は『オシロ/解析』パネルで「解析実行」「FFT表示」「オシロスコープ表示」\n\n"
                    "【グラフ上の操作】ホバー=近傍点の値を右下に表示／ホイール=ズーム"
                    "（Shift+ホイール=X方向のみ）／ダブルクリック=全体表示／凡例クリック=系列ON/OFF\n"
                    "【区間測定】『オシロ/解析』の「区間測定」ONでドラッグした区間だけを測定\n"
                    "【結果の持ち出し】各結果表を右クリック→コピー/CSV保存。"
                    "「ファイル→Excelレポート出力」でグラフ+表を1つのExcelブックに\n"
                    "【その他】Ctrl+Shift+P=コマンドパレット（全操作を検索実行）／"
                    "「ファイル→ファイルの変更を監視」=更新されたCSVを自動再読込／\n"
                    "　書式パネル「系列ごとに段を分ける」=サブプロット表示／"
                    "データ編集バーの「編集を戻す/やり直す」\n"
                    "【出力】右端パネルの画像出力、またはメニュー「ファイル」から保存／コピー\n"
                    "【グラフ種別と列】棒/円は1ファイル、折れ線/散布図は複数ファイル重ね描き可\n"
                    "【設定が見つからないとき】Ctrl+F＝設定を検索（パネルを横断して該当項目へ移動）\n"
                    "【見逃したメッセージ】ステータスバー右の「履歴」ボタンで過去の通知を確認")

    def show_about(self):
        QtWidgets.QMessageBox.about(
            self, "バージョン情報",
            "CSV / TSV / 波形 グラフ・解析ツール\n"
            "PySide6 + matplotlib 製\n"
            f"日本語フォント: {self.font_name or '未検出'}")

    # ------------------------------------------------------------ UI状態（QSettings）
    # ウィンドウ位置・分割位置・書式セクションの開閉といった「見た目の使い勝手」だけを
    # OS のユーザー設定に保存する。グラフ設定（config JSON）とは独立で、混ざらない。
    def _ui_settings(self):
        return QtCore.QSettings("graph-tool", "GraphApp")

    def _restore_ui_state(self):
        s = self._ui_settings()
        geo = s.value("ui/geometry")
        if geo is not None:
            self.restoreGeometry(geo)
        ws = s.value("ui/window_state")   # ドック配置・ツールバー位置
        if ws is not None:
            self.restoreState(ws)
        for key, sp in (("ui/center_splitter", getattr(self, "center_splitter", None)),
                        ("ui/format_splitter", getattr(self, "format_splitter", None)),
                        ("ui/data_splitter", getattr(self, "data_splitter", None))):
            st = s.value(key)
            if st is not None and sp is not None:
                sp.restoreState(st)
        if str(s.value("ui/watch_files")) in ("1", "true", "True"):
            self._watch_action.setChecked(True)   # → toggle_file_watch で監視開始
        # UIスタイル（外観）を復元。標準でも基準QSS（ボタン高さ統一）を必ず適用する
        self._apply_ui_style(str(s.value("ui/style") or "standard"))
        # 表示レベルを復元。既定は「全部」＝従来と同じ見た目（減らすのは明示操作のみ）。
        # シンプル版（graph_app_simple.py）は DEFAULT_UI_LEVEL を上書きして起動する。
        self._apply_ui_level(str(s.value("ui/level") or self.DEFAULT_UI_LEVEL))
        # 復元した切り離し状態をメニューのチェックへ反映し、タブバーも配線し直す
        if hasattr(self, "_float_actions"):
            for d in [*self.left_docks, self.format_dock]:
                a = self._float_actions.get(d.objectName())
                if a is not None:
                    self._sync_float_action(a, d.isFloating())
            self._wire_dock_tabbars()

    def _save_ui_state(self):
        s = self._ui_settings()
        s.setValue("ui/geometry", self.saveGeometry())
        s.setValue("ui/window_state", self.saveState())   # ドック配置・ツールバー位置
        for key, sp in (("ui/center_splitter", getattr(self, "center_splitter", None)),
                        ("ui/format_splitter", getattr(self, "format_splitter", None)),
                        ("ui/data_splitter", getattr(self, "data_splitter", None))):
            if sp is not None:
                s.setValue(key, sp.saveState())
        for k, box in getattr(self, "_fmt_sections", {}).items():
            s.setValue("fmt_section/" + k, "1" if box.is_expanded() else "0")
        s.setValue("ui/level", self.ui_level())

    # ------------------------------------------------------------ Excelレポート出力
    def export_excel_report(self):
        """現在のグラフ設定＋データ＋解析結果の表を1つのExcelブックに出力する。
        グラフはネイティブExcelグラフ（Excelがあれば COM=VBA互換、無ければ openpyxl）。
        測定値・ピーク・FFT指標・統計解析の表は、値が入っていれば別シートで同梱する。"""
        items = self._selected_series_items()
        if not items:
            self.notify("先にY系列を選択してください。", "warn")
            return
        src = items[0][0]   # 棒グラフ等と同じく、最初に選んだ系列のファイルを対象にする
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Excelレポート出力", os.path.join(self.last_dir, "レポート.xlsx"),
            "Excel (*.xlsx)")
        if not path:
            return
        extra = {}
        for name, table in (("測定値", getattr(self, "meas_table", None)),
                            ("ピーク", getattr(self, "peak_table", None)),
                            ("FFT指標", getattr(self, "fft_metrics", None)),
                            ("統計解析", getattr(self, "ds_table", None))):
            if table is not None and table.rowCount():
                extra[name] = self._table_rows(table, False)
        try:
            import excel_chart
            out, eng = excel_chart.export_from_config(
                self.datasets[src], self._collect_config(), out_path=path,
                only_file=src, extra_sheets=extra or None)
        except Exception as e:  # noqa: BLE001  種別未対応・列不一致などを分かりやすく表示
            QtWidgets.QMessageBox.critical(self, "Excelレポート出力", str(e))
            return
        self.last_dir = os.path.dirname(path)
        n = f"＋表{len(extra)}シート" if extra else ""
        self._set_status(f"Excelレポートを出力しました（{eng}エンジン{n}）: {out}")

    # ------------------------------------------------------------ 設定保存
    def _collect_config(self):
        return {
            "files": [self.meta[l]["path"] for l in self.datasets],
            "x_col": self.x_combo.currentText(),
            "z_col": self.z_combo.currentText() if hasattr(self, "z_combo") else "",
            "x_leftmost": self.xleft_check.isChecked(),
            "selected_y": [[fl, col] for fl, col, _ in self._selected_series_items()],
            "chart_type": self.chart_combo.currentText(),
            "threed": self.threed_check.isChecked() if hasattr(self, "threed_check") else False,
            "stack": self.stack_check.isChecked() if hasattr(self, "stack_check") else False,
            "swap_xy": self.swap_xy_check.isChecked() if hasattr(self, "swap_xy_check") else False,
            "multi_x": self.multix_check.isChecked() if hasattr(self, "multix_check") else False,
            "x_cols": ([self.x_list.item(i).data(UserRole)
                        for i in range(self.x_list.count())
                        if self.x_list.item(i).checkState() == QtCore.Qt.CheckState.Checked]
                       if hasattr(self, "x_list") else []),
            "view_elev": self.elev_spin.value() if hasattr(self, "elev_spin") else 30,
            "view_azim": self.azim_spin.value() if hasattr(self, "azim_spin") else -60,
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
            "fill_enabled": self.fill_check.isChecked(),
            "fill_a": self.fill_a.currentText(), "fill_b": self.fill_b.currentText(),
            "fill_color": getattr(self, "fill_color", ""), "fill_alpha": self.fill_alpha.value(),
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
        if cfg.get("z_col") and hasattr(self, "z_combo"):
            j = self.z_combo.findText(cfg["z_col"])
            if j >= 0:
                self.z_combo.setCurrentIndex(j)
        if hasattr(self, "elev_spin") and "view_elev" in cfg:
            self.elev_spin.setValue(int(cfg["view_elev"]))
            self.azim_spin.setValue(int(cfg.get("view_azim", -60)))
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
        # 旧『3D…』種別名は 2D名＋3Dフラグへ移行してから復元する
        ct, mig3d = plotter.migrate_chart_type(cfg.get("chart_type", "折れ線"))
        self.chart_combo.setCurrentText(ct)   # ここで _sync_3d_checkbox が走る
        if hasattr(self, "threed_check"):
            if "threed" in cfg:
                self.threed_check.setChecked(bool(cfg["threed"]))
            elif mig3d is not None:
                self.threed_check.setChecked(mig3d)
        if hasattr(self, "swap_xy_check"):
            self.swap_xy_check.setChecked(bool(cfg.get("swap_xy", False)))
        if hasattr(self, "stack_check"):
            self.stack_check.setChecked(bool(cfg.get("stack", False)))
        if hasattr(self, "x_list"):            # 複数X（列名一致で復元）
            want = set(cfg.get("x_cols", []) or [])
            self.x_list.blockSignals(True)
            for i in range(self.x_list.count()):
                it = self.x_list.item(i)
                it.setCheckState(QtCore.Qt.CheckState.Checked
                                 if it.data(UserRole) in want
                                 else QtCore.Qt.CheckState.Unchecked)
            self.x_list.blockSignals(False)
            self.multix_check.setChecked(bool(cfg.get("multi_x", False)))
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
        # 系列間の塗りつぶし（系列コンボを先に更新してから選択・色を復元）
        self._update_analysis_targets()
        self.fill_check.setChecked(cfg.get("fill_enabled", False))
        self.fill_a.setCurrentText(cfg.get("fill_a", ""))
        self.fill_b.setCurrentText(cfg.get("fill_b", "0（X軸）"))
        self.fill_alpha.setValue(cfg.get("fill_alpha", 0.3))
        fc = cfg.get("fill_color", "")
        if fc:
            self.fill_color = fc
            self.fill_color_btn.setText("色: " + fc)
            self.fill_color_btn.setStyleSheet(f"background:{fc};")
        else:
            self._reset_fill_color()
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
        self._sync_explorer_checks()   # blockSignals中に復元したY選択をツリーへ反映
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
            self.notify("設定を読み込めませんでした。", "warn")
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
                # 前回大量の系列を選んだまま終了していると、起動直後の自動描画で
                # 固まって操作できなくなる（そのまま落ちると復元→再クラッシュの
                # ループになる）。多いときは描かずに案内だけ出す。
                n = len(self._selected_series_items())
                if n > HEAVY_SERIES:
                    self._draw_placeholder()
                    self.notify(
                        f"前回の選択（{n} 系列）は多いため自動描画を省略しました。"
                        "系列を減らすか「グラフを描画」で明示的に実行してください。", "warn")
                    return True
                self.draw_graph()
            self._set_status("前回のセッションを復元しました。")
            return True
        except Exception:
            applog.get_logger().exception("前回セッションの復元に失敗")
            return False

    # ------------------------------------------------------------ 書式プリセット
    # 「データ/ファイル選択」に依存しない“見た目”だけを名前付きで保存・呼び出す。
    _PRESET_KEYS = ("chart_type", "threed", "swap_xy", "stack", "fonts", "grid", "legend", "legend_loc",
                    "show_filename", "show_ext", "frame_width", "grid_width",
                    "xlog", "ylog", "xinvert", "yinvert", "bins", "pct", "data_labels",
                    "trend", "trend_degree", "trend_window", "trend_eq", "trend_color",
                    "bg_color", "aspect", "aspect_w", "aspect_h")

    def _presets_dir(self):
        d = os.path.join(config_io.APP_DIR, "presets")
        try:
            os.makedirs(d, exist_ok=True)
        except OSError:
            applog.get_logger().debug("_presets_dir: 無視した例外", exc_info=True)
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
            self.notify(str(e), "warn")
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
            self.notify("プリセットを読み込めませんでした。", "warn")
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
            applog.get_logger().debug("delete_preset: 無視した例外", exc_info=True)
        self._refresh_preset_combo()

    def _apply_format(self, d):
        """プリセット（見た目のみ）を現在のウィジェットへ適用。データ選択には触れない。"""
        prev = self._suspend_redraw
        self._suspend_redraw = True
        try:
            if "chart_type" in d:
                ct, mig3d = plotter.migrate_chart_type(d["chart_type"])
                self.chart_combo.setCurrentText(ct)   # _sync_3d_checkbox が走る
                if hasattr(self, "threed_check"):
                    if "threed" in d:
                        self.threed_check.setChecked(bool(d["threed"]))
                    elif mig3d is not None:
                        self.threed_check.setChecked(mig3d)
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
                    ("swap_xy", getattr(self, "swap_xy_check", None), "chk"),
                    ("stack", getattr(self, "stack_check", None), "chk"),
                    ("trend", self.trend_combo, "txt"), ("trend_degree", self.trend_degree, "val"),
                    ("trend_window", self.trend_window, "val"), ("trend_eq", self.trend_eq, "chk")):
                if widget is None:
                    continue
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
            else:
                self._reset_trend_color()   # プリセットが自動色なら自動へ戻す
            bgc = d.get("bg_color", "")
            if bgc:
                self.bg_color = bgc; self.bg_btn.setText("背景色: " + bgc)
                self.bg_btn.setStyleSheet(f"background:{bgc};")
            else:
                self._reset_bg_color()
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
