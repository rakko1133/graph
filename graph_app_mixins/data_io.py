# -*- coding: utf-8 -*-
"""DataIOMixin: GraphApp から分離した DataIOMixin 群（挙動は本体と同一）。"""
from graph_app_common import *  # noqa: F401,F403


class DataIOMixin:
    # ------------------------------------------------------------ D&D
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    _ACCEPT_EXTS = (".csv", ".tsv", ".txt", ".xlsx", ".xlsm", ".xls",
                    ".wav", ".raw", ".tdms", ".mf4", ".mdf", ".h5", ".hdf5",
                    ".asc", ".net")   # LTspice回路/ネットリスト（実行→.raw読込）

    def dropEvent(self, event):
        paths = []
        for url in event.mimeData().urls():
            p = url.toLocalFile()
            if p and os.path.splitext(p)[1].lower() in self._ACCEPT_EXTS:
                paths.append(p)
        if not paths:
            return
        for p in paths:
            self._load_file(p)
        self.last_dir = os.path.dirname(paths[-1])
        self._refresh_columns()
        if self._has_drawn:
            self.draw_graph()

    # ------------------------------------------------------------ ファイル
    def add_file(self):
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self, "ファイルを追加（複数選択可）", self.last_dir,
            "データ (*.csv *.tsv *.txt *.xlsx *.xls *.xlsm *.wav *.raw *.tdms *.mf4 *.mdf *.h5 *.hdf5 *.asc);;"
            "Excel (*.xlsx *.xls *.xlsm);;CSV/TSV (*.csv *.tsv *.txt);;"
            "波形/計測 (*.wav *.raw *.tdms *.mf4 *.mdf *.h5 *.hdf5);;"
            "LTspice回路 (*.asc *.net);;すべて (*.*)")
        for p in paths:
            self._load_file(p)
        if paths:
            self.last_dir = os.path.dirname(paths[-1])
            self._refresh_columns()

    def paste_from_clipboard(self):
        """クリップボードの表データ（Excel等からのコピー＝TSV/CSV）を新規データとして読み込む。"""
        import io
        import pandas as pd
        text = QtWidgets.QApplication.clipboard().text()
        if not text or not text.strip():
            QtWidgets.QMessageBox.information(self, "貼り付け", "クリップボードに表データがありません。")
            return
        first = text.splitlines()[0]
        sep = "\t" if first.count("\t") >= first.count(",") else ","   # Excelコピーはタブ区切り
        try:
            df = pd.read_csv(io.StringIO(text), sep=sep, engine="python", skip_blank_lines=True)
            df = data_loader._normalize_columns(df)
        except Exception as e:  # noqa: BLE001
            QtWidgets.QMessageBox.warning(self, "貼り付け", f"表として読み取れませんでした:\n{e}")
            return
        if df.shape[1] == 0 or len(df) == 0:
            QtWidgets.QMessageBox.warning(self, "貼り付け", "表として読み取れませんでした。")
            return
        label, i = "貼り付け", 2
        while label in self.datasets:
            label = f"貼り付け ({i})"; i += 1
        self.datasets[label] = df
        self.meta[label] = {"path": "(clipboard)", "enc": "clipboard", "delim": sep}
        self._add_file_item(label)
        self.file_list.setCurrentRow(self.file_list.count() - 1)
        self._refresh_columns()
        self._set_status(f"クリップボードから {len(df)}行 × {len(df.columns)}列 を貼り付けました。")

    def _load_file(self, path):
        if os.path.splitext(path)[1].lower() in (".asc", ".net"):
            self.run_ltspice_asc(path)   # 回路図/ネットリストは実行→.raw読込
            return
        enc = self.enc_combo.currentText()
        enc = None if enc.startswith("自動") else enc
        delim = None
        dt = self.delim_combo.currentText()
        if not dt.startswith("自動"):
            for ch, lbl in data_loader.DELIMITER_LABELS.items():
                if lbl == dt:
                    delim = ch
                    break
        # Excelで複数シートがある場合はどのシートを読むか選んでもらう
        sheet = None
        if os.path.splitext(path)[1].lower() in (".xlsx", ".xlsm", ".xls"):
            sheets = data_loader.excel_sheet_names(path)
            if len(sheets) > 1:
                sheet, ok = QtWidgets.QInputDialog.getItem(
                    self, "シートの選択", f"{os.path.basename(path)} のシート:",
                    sheets, 0, False)
                if not ok:
                    return
        size = os.path.getsize(path) if os.path.isfile(path) else 0
        busy = size > 5_000_000   # 5MB 超は待機カーソル＋進捗
        if busy:
            QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
            self._set_status(f"読み込み中… {os.path.basename(path)}")
            QtWidgets.QApplication.processEvents()
        try:
            df, used_enc, used_delim = data_loader.load_table(
                path, encoding=enc, delimiter=delim, sheet=sheet)
        except Exception as e:  # noqa: BLE001
            QtWidgets.QMessageBox.critical(self, "読み込みエラー", f"{os.path.basename(path)}\n\n{e}")
            return
        finally:
            if busy:
                QtWidgets.QApplication.restoreOverrideCursor()
        label = os.path.basename(path)
        if sheet:
            label = f"{label}[{sheet}]"   # シート違いを別データとして区別できるように
        base, i = label, 2
        while label in self.datasets and self.meta.get(label, {}).get("path") != path:
            label = f"{base} ({i})"; i += 1
        self.datasets[label] = df
        self.meta[label] = {"path": path, "enc": used_enc, "delim": used_delim,
                            "sheet": sheet}
        if not self._find_file_item(label):
            self._add_file_item(label)
        self._push_recent(path)
        self._set_status(f"{label} を読み込み（{len(df)}行 × {len(df.columns)}列, {used_enc}）")

    # ------------------------------------------------------------ フォルダを開く
    def add_folder(self):
        """フォルダ内の対応データファイルを一括で読み込む（VS Codeの「フォルダを開く」相当）。"""
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "フォルダを開く", self.last_dir)
        if d:
            self._load_folder(d)

    def _load_folder(self, d):
        exts = set(self._ACCEPT_EXTS) - {".asc", ".net"}   # 回路は誤爆実行を避けて除外
        try:
            names = sorted(os.listdir(d))
        except OSError as e:
            QtWidgets.QMessageBox.critical(self, "フォルダを開く", str(e))
            return
        files = [os.path.join(d, f) for f in names
                 if os.path.splitext(f)[1].lower() in exts
                 and os.path.isfile(os.path.join(d, f))]
        if not files:
            QtWidgets.QMessageBox.information(
                self, "情報", "このフォルダに読み込めるデータファイルがありません。")
            return
        if len(files) > 40:
            ret = QtWidgets.QMessageBox.question(
                self, "フォルダを開く",
                f"{len(files)} 個のファイルが見つかりました。すべて読み込みますか？")
            if ret != QtWidgets.QMessageBox.StandardButton.Yes:
                return
        for p in files:
            self._load_file(p)
        self.last_dir = d
        self._refresh_columns()
        if self._has_drawn:
            self.draw_graph()
        self._set_status(f"フォルダを読み込みました: {os.path.basename(d)}（{len(files)}ファイル）")

    # ------------------------------------------------------------ LTspice 連携
    # .asc 回路をバッチ実行し、生成された .raw を自動で読み込む。ファイル監視を
    # ONにしておけば、以降 LTspice 側で再シミュレーションするたびに自動更新される。
    _LTSPICE_CANDIDATES = (
        r"C:\Program Files\ADI\LTspice\LTspice.exe",
        r"C:\Program Files\LTC\LTspiceXVII\XVIIx64.exe",
        r"C:\Program Files (x86)\LTC\LTspiceIV\scad3.exe",
    )

    def _ltspice_exe(self):
        """LTspice実行ファイルの場所（設定→既知パス→spicelib検出→PATHの順で探す）。"""
        p = self._ui_settings().value("ltspice/exe")
        if p and os.path.isfile(str(p)):
            return str(p)
        cands = list(self._LTSPICE_CANDIDATES) + [
            os.path.expanduser(r"~\AppData\Local\Programs\ADI\LTspice\LTspice.exe")]
        for c in cands:
            if os.path.isfile(c):
                return c
        try:   # spicelib が入っていればその自動検出も利用する
            from spicelib.simulators.ltspice_simulator import LTspice
            for c in LTspice.spice_exe:
                if os.path.isfile(str(c)):
                    return str(c)
        except Exception:
            pass
        import shutil
        return shutil.which("LTspice") or shutil.which("XVIIx64")

    def set_ltspice_path(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "LTspice実行ファイルの場所", r"C:\Program Files",
            "LTspice (*.exe)")
        if path:
            self._ui_settings().setValue("ltspice/exe", path)
            self._set_status(f"LTspiceの場所を設定しました: {path}")

    def run_ltspice_asc(self, path=None):
        """LTspice回路(.asc)をバッチ実行し、生成された .raw を読み込んで描画する。"""
        if getattr(self, "_lt_proc", None) is not None \
                and self._lt_proc.state() != QtCore.QProcess.ProcessState.NotRunning:
            self._set_status("LTspiceシミュレーションを実行中です。完了までお待ちください。")
            return
        if not path:
            path, _ = QtWidgets.QFileDialog.getOpenFileName(
                self, "LTspice回路を実行", self.last_dir,
                "LTspice回路/ネットリスト (*.asc *.net)")
            if not path:
                return
        exe = self._ltspice_exe()
        if not exe:
            ret = QtWidgets.QMessageBox.question(
                self, "LTspiceが見つかりません",
                "LTspice の実行ファイルが見つかりませんでした。\n場所を指定しますか？")
            if ret == QtWidgets.QMessageBox.StandardButton.Yes:
                self.set_ltspice_path()
                exe = self._ltspice_exe()
            if not exe:
                return
        self.last_dir = os.path.dirname(path)
        raw = os.path.splitext(path)[0] + ".raw"
        proc = QtCore.QProcess(self)
        self._lt_proc = proc
        proc.finished.connect(
            lambda code, _st, p=path, r=raw: self._on_ltspice_finished(code, p, r))
        proc.start(exe, ["-b", path])   # -b: バッチ実行（.rawを回路と同じ場所に生成）
        if not proc.waitForStarted(5000):
            self._lt_proc = None
            QtWidgets.QMessageBox.critical(self, "LTspice", f"起動できませんでした: {exe}")
            return
        self._set_status(f"LTspiceシミュレーション実行中… {os.path.basename(path)}"
                         "（完了すると自動で波形を読み込みます）")

    def _on_ltspice_finished(self, code, asc_path, raw_path):
        self._lt_proc = None
        if not os.path.isfile(raw_path):
            QtWidgets.QMessageBox.warning(
                self, "LTspice",
                f"シミュレーションは終了しましたが .raw が見つかりません（終了コード {code}）。\n"
                f"回路にエラーがないか LTspice で確認してください:\n{asc_path}")
            return
        self._load_file(raw_path)
        self._refresh_columns()
        if self._has_drawn:
            self.draw_graph()
        note = ("（ファイル監視ONなので、LTspice側で再実行すると自動更新されます）"
                if self._watch_enabled() else
                "（メニュー『ファイル→ファイルの変更を監視』をONにすると、"
                "LTspice側の再実行で自動更新されます）")
        self._set_status(f"LTspice完了: {os.path.basename(raw_path)} を読み込みました {note}")

    # ------------------------------------------------------------ ファイル監視（自動再読込）
    # 測定器やロガーが書き続けるCSVを監視し、更新されたら自動で読み直して再描画する。
    # メニュー「ファイル→ファイルの変更を監視して自動再読込」でON/OFF（QSettingsに保存）。
    def _watch_enabled(self):
        return bool(getattr(self, "_watch_action", None) and self._watch_action.isChecked())

    def toggle_file_watch(self, on):
        self._ui_settings().setValue("ui/watch_files", "1" if on else "0")
        if on:
            self._ensure_watcher()
            self._rebuild_watch_paths()
            self._set_status("ファイル監視: ON（監視中のファイルが更新されると自動で再読込・再描画します）")
        else:
            w = getattr(self, "_fs_watcher", None)
            if w is not None and w.files():
                w.removePaths(w.files())
            self._set_status("ファイル監視: OFF")

    def _ensure_watcher(self):
        if getattr(self, "_fs_watcher", None) is None:
            self._fs_watcher = QtCore.QFileSystemWatcher(self)
            self._fs_watcher.fileChanged.connect(self._on_watched_file_changed)
            self._watch_pending = set()
            self._watch_timer = QtCore.QTimer(self)
            self._watch_timer.setSingleShot(True)
            self._watch_timer.setInterval(600)   # 書き込み途中の連続イベントをまとめる
            self._watch_timer.timeout.connect(self._reload_watched)

    def _rebuild_watch_paths(self):
        """監視対象を現在の読み込みファイル一覧に合わせて貼り直す。"""
        if not self._watch_enabled():
            return
        self._ensure_watcher()
        w = self._fs_watcher
        if w.files():
            w.removePaths(w.files())
        paths = sorted({m.get("path") for m in self.meta.values()
                        if m.get("path") and os.path.isfile(m.get("path"))})
        if paths:
            w.addPaths(paths)

    def _on_watched_file_changed(self, path):
        self._watch_pending.add(path)
        self._watch_timer.start()

    def _reload_watched(self):
        pending, self._watch_pending = set(self._watch_pending), set()
        labels = [l for l, m in self.meta.items() if m.get("path") in pending]
        reloaded = []
        for label in labels:
            if self._reload_label_inplace(label):
                reloaded.append(label)
        # エディタの「置換保存」では旧ファイルが消えて監視から外れるため貼り直す
        self._rebuild_watch_paths()
        if reloaded:
            self._refresh_columns()
            if self._has_drawn:
                self.draw_graph()
            self._set_status("自動再読込: " + ", ".join(reloaded))

    def _reload_all_files(self):
        """全ファイルをディスクの最新内容で読み直す（並び・チェックは維持）。"""
        reloaded = [l for l in list(self.datasets) if self._reload_label_inplace(l)]
        if reloaded:
            self._refresh_columns()
            if self._has_drawn:
                self.draw_graph()
            self._set_status(f"再読込しました: {len(reloaded)}ファイル")
        else:
            self._set_status("再読込できるファイルがありません（貼り付け・生成データのみ）。")

    def _reload_label_inplace(self, label):
        """一覧の並びと選択を保ったまま、保存済みの読み込み条件でデータだけ差し替える。"""
        meta = self.meta.get(label) or {}
        path = meta.get("path")
        if not path or not os.path.isfile(path):
            return False
        enc = meta.get("enc")
        enc = None if (not enc or str(enc).startswith(("自動", "clipboard"))) else enc
        try:
            df, used_enc, used_delim = data_loader.load_table(
                path, encoding=enc, delimiter=meta.get("delim"),
                sheet=meta.get("sheet"))
        except Exception:  # noqa: BLE001  書き込み途中で開けない等は次の変更イベントに任せる
            return False
        self.datasets[label] = df
        self.meta[label] = {"path": path, "enc": used_enc, "delim": used_delim,
                            "sheet": meta.get("sheet")}
        if getattr(self, "_preview_label", None) == label:
            self._populate_preview(df, label=label)
        return True

    def _find_file_item(self, label):
        for i in range(self.file_list.count()):
            if self.file_list.item(i).text() == label:
                return self.file_list.item(i)
        return None

    def _add_file_item(self, label):
        """ファイル一覧へ項目を追加（ホバーで全名を出すツールチップ付き）。"""
        it = QtWidgets.QListWidgetItem(label)
        it.setToolTip(label)
        self.file_list.addItem(it)

    def _push_recent(self, path):
        if path in self.recent_files:
            self.recent_files.remove(path)
        self.recent_files.insert(0, path)
        del self.recent_files[12:]
        self._rebuild_recent_menu()

    def _rebuild_recent_menu(self):
        self.recent_menu.clear()
        if not self.recent_files:
            act = self.recent_menu.addAction("（履歴なし）"); act.setEnabled(False)
            return
        for p in self.recent_files:
            self.recent_menu.addAction(os.path.basename(p),
                                       lambda checked=False, q=p: self._open_recent(q))

    def _open_recent(self, path):
        if not os.path.isfile(path):
            QtWidgets.QMessageBox.information(self, "情報", f"ファイルが見つかりません:\n{path}")
            self.recent_files = [q for q in self.recent_files if q != path]
            self._rebuild_recent_menu()
            return
        self._load_file(path)
        self._refresh_columns()
        if self._has_drawn:
            self.draw_graph()

    def remove_file(self):
        """選択中のファイルを削除（複数選択していればまとめて削除）。"""
        items = self.file_list.selectedItems()
        if not items and self.file_list.currentItem():
            items = [self.file_list.currentItem()]
        labels = [it.text() for it in items]
        if not labels:
            QtWidgets.QMessageBox.information(self, "情報", "削除するファイルを選択してください。")
            return
        if len(labels) > 1:
            ret = QtWidgets.QMessageBox.question(
                self, "一括削除", f"{len(labels)} 個のファイルを一覧から削除しますか？")
            if ret != QtWidgets.QMessageBox.StandardButton.Yes:
                return
        self._remove_labels(labels)
        self._set_status(f"{len(labels)} 個のファイルを削除しました。")

    def clear_all_files(self):
        """読み込み済みファイルをすべて削除する。"""
        if not self.datasets:
            QtWidgets.QMessageBox.information(self, "情報", "読み込み済みファイルがありません。")
            return
        ret = QtWidgets.QMessageBox.question(
            self, "全削除", f"読み込み済みの {len(self.datasets)} 個すべてを一覧から削除しますか？")
        if ret != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        n = len(self.datasets)
        self._remove_labels(list(self.datasets.keys()))
        self._set_status(f"すべて（{n} 個）のファイルを削除しました。")

    def _remove_labels(self, labels):
        """指定ラベルのファイルをデータ・一覧・スタイルから取り除き、表示を更新する。"""
        labelset = set(labels)
        # ズーム再サンプル用に保持していた全解像度データの参照を解放（メモリリーク防止）
        self._clear_dynamic_resample()
        for label in labels:
            self.datasets.pop(label, None)
            self.meta.pop(label, None)
        # 該当ファイルの系列スタイルも掃除（"file\tcol" キー）
        for key in [k for k in self.series_styles if k.split("\t", 1)[0] in labelset]:
            self.series_styles.pop(key, None)
        # 削除したデータに紐づく解析注記・解析表をクリア（古い注記が次の描画に残らないように）
        self._meas_annotations = []
        self._ds_annotations = []
        self._proto_annotations = None
        if hasattr(self, "meas_table"):
            self.meas_table.setRowCount(0)
        if hasattr(self, "ds_table"):
            self.ds_table.setRowCount(0)
        self.file_list.blockSignals(True)
        for i in range(self.file_list.count() - 1, -1, -1):
            if self.file_list.item(i).text() in labelset:
                self.file_list.takeItem(i)
        self.file_list.blockSignals(False)
        self._refresh_columns()
        if self.datasets:
            self.file_list.setCurrentRow(0)   # プレビューを残りの先頭へ
        else:
            self._preview_label = None
            self.table.clearContents()
            self.table.setRowCount(0)
            self.table.setColumnCount(0)
            self._draw_placeholder()

    def reload_current(self):
        it = self.file_list.currentItem()
        if not it:
            QtWidgets.QMessageBox.information(self, "情報", "ファイルを選択してください。")
            return
        path = self.meta[it.text()]["path"]
        self.datasets.pop(it.text(), None)
        self.meta.pop(it.text(), None)
        self.file_list.takeItem(self.file_list.row(it))
        self._load_file(path)
        self._refresh_columns()

    def _on_file_selected(self, _row):
        it = self.file_list.currentItem()
        if it and it.text() in self.datasets:
            self._populate_preview(self.datasets[it.text()], label=it.text())
            meta = self.meta[it.text()]
            self.enc_combo.setCurrentText(meta["enc"]) if self.enc_combo.findText(meta["enc"]) >= 0 else None

    def _refresh_columns(self):
        # X軸候補（全ファイルの列名の和集合、出現順）
        seen, xcols = set(), []
        for df in self.datasets.values():
            for c in df.columns:
                if c not in seen:
                    seen.add(c); xcols.append(c)
        cur_x = self.x_combo.currentText()
        self.x_combo.blockSignals(True)
        self.x_combo.clear(); self.x_combo.addItems(xcols)
        if cur_x in xcols:
            self.x_combo.setCurrentText(cur_x)
        self.x_combo.blockSignals(False)

        # Z軸候補（3D用）。X と同じ列集合。既定は最終列。
        if hasattr(self, "z_combo"):
            cur_z = self.z_combo.currentText()
            self.z_combo.blockSignals(True)
            self.z_combo.clear(); self.z_combo.addItems(xcols)
            if cur_z in xcols:
                self.z_combo.setCurrentText(cur_z)
            elif xcols:
                self.z_combo.setCurrentText(xcols[-1])
            self.z_combo.blockSignals(False)

        # 複数X候補（列名。チェック状態を維持）。X と同じ列集合。
        checked = QtCore.Qt.CheckState.Checked
        unchecked = QtCore.Qt.CheckState.Unchecked
        if hasattr(self, "x_list"):
            prev_x = {self.x_list.item(i).data(UserRole)
                      for i in range(self.x_list.count())
                      if self.x_list.item(i).checkState() == checked}
            self.x_list.blockSignals(True)
            self.x_list.clear()
            for c in xcols:
                it = QtWidgets.QListWidgetItem(str(c))
                it.setData(UserRole, c)
                it.setFlags(QtCore.Qt.ItemFlag.ItemIsUserCheckable
                            | QtCore.Qt.ItemFlag.ItemIsEnabled)
                it.setCheckState(checked if c in prev_x else unchecked)
                self.x_list.addItem(it)
            self.x_list.blockSignals(False)

        # Y軸候補（ファイル｜列）。選択状態は表示名ではなく安定した
        # (ファイル, 列) 識別子で保持する（ファイル数で表示名が変わっても消えない）。
        prev = {self.y_list.item(i).data(UserRole)
                for i in range(self.y_list.count())
                if self.y_list.item(i).checkState() == checked}
        self.y_list.blockSignals(True)   # 構築中のチェック変更で何度も再描画しない
        self.y_list.clear()
        multi = len(self.datasets) > 1
        use_left = self._use_leftmost_x()
        for label, df in self.datasets.items():
            for ci, c in enumerate(df.columns):
                if use_left and ci == 0:   # 先頭列はX軸なのでY軸候補から除外
                    continue
                disp = f"{label} | {c}" if multi else c
                item = QtWidgets.QListWidgetItem(disp)
                item.setData(UserRole, (label, c))
                item.setFlags(QtCore.Qt.ItemFlag.ItemIsUserCheckable
                              | QtCore.Qt.ItemFlag.ItemIsEnabled)
                item.setCheckState(checked if (label, c) in prev else unchecked)
                self.y_list.addItem(item)
        self.y_list.blockSignals(False)
        if hasattr(self, "explorer"):
            self._rebuild_explorer()     # ファイル→列ツリーを作り直す
        self._rebuild_watch_paths()      # ファイル監視ON時は監視対象を貼り直す
        self._on_y_selection_changed()   # スタイル表・解析候補をまとめて更新

    def _selected_series_items(self):
        """チェック済みの (file_label, column, display_label) のリスト（並び順保持）。"""
        out = []
        for i in range(self.y_list.count()):
            it = self.y_list.item(i)
            if it.checkState() == QtCore.Qt.CheckState.Checked:
                fl, col = it.data(UserRole)
                out.append((fl, col, it.text()))
        return out

    def _populate_preview(self, df, label=None):
        import pandas as pd
        self._preview_loading = True   # 構築中の itemChanged を書き戻さない
        try:
            head = df.head(PREVIEW_ROWS)
            cols = list(df.columns)
            self.table.clear()
            self.table.setColumnCount(len(cols))
            self.table.setRowCount(len(head))
            self.table.setHorizontalHeaderLabels([str(c) for c in cols])
            nan_bg = QtGui.QBrush(QtGui.QColor("#ffe4e1"))   # 欠損セルは薄赤で目立たせる
            for r in range(len(head)):
                for c in range(len(cols)):
                    v = head.iat[r, c]
                    missing = pd.isna(v)
                    it = QtWidgets.QTableWidgetItem("" if missing else str(v))
                    if missing:
                        it.setBackground(nan_bg)
                        it.setToolTip("欠損値（NaN）")
                    self.table.setItem(r, c, it)
            # 列ヘッダに品質情報のツールチップ（型・全行の欠損数・数値なら範囲）。
            # 欠損を含む列はヘッダ名に ⚠ を付けて一目でわかるようにする。
            for c, col in enumerate(cols):
                s = df[col]
                n_nan = int(s.isna().sum())
                tip = [f"列: {col}", f"型: {s.dtype}", f"全 {len(s):,} 行"]
                if n_nan:
                    tip.append(f"⚠ 欠損: {n_nan:,} 行（{n_nan / max(len(s), 1):.1%}）")
                if pd.api.types.is_numeric_dtype(s):
                    v = s.dropna()
                    if len(v):
                        tip.append(f"範囲: {v.min():.6g} 〜 {v.max():.6g}")
                hi = QtWidgets.QTableWidgetItem(("⚠ " if n_nan else "") + str(col))
                hi.setToolTip("\n".join(tip))
                self.table.setHorizontalHeaderItem(c, hi)
            self.table.resizeColumnsToContents()
            if label is not None:
                self._preview_label = label
        finally:
            self._preview_loading = False

    # ------------------------------------------------------------ データ編集
    def _on_edit_toggle(self, on):
        ET = QtWidgets.QAbstractItemView.EditTrigger
        self.table.setEditTriggers(
            (ET.DoubleClicked | ET.EditKeyPressed | ET.AnyKeyPressed)
            if on else ET.NoEditTriggers)

    def _on_cell_edited(self, item):
        if self._preview_loading or not getattr(self, "_preview_label", None):
            return
        import pandas as pd
        df = self.datasets.get(self._preview_label)
        if df is None:
            return
        r, c = item.row(), item.column()
        if r >= len(df) or c >= df.shape[1]:
            return
        col = df.columns[c]
        text = item.text()
        if pd.api.types.is_numeric_dtype(df[col]):
            val = pd.to_numeric(text, errors="coerce")   # 数値列は数値化（不可ならNaN）
        else:
            val = text
        old = df.iat[r, c]
        df.iat[r, c] = val
        self._data_record({"kind": "cell", "label": self._preview_label,
                           "row": r, "col": c, "old": old, "new": val})
        self._set_status(f"編集: {self._preview_label} 行{r}「{col}」= {text}")
        self._request_redraw()

    def _edit_target(self):
        lbl = getattr(self, "_preview_label", None)
        if not lbl or lbl not in self.datasets:
            QtWidgets.QMessageBox.information(self, "情報", "左の一覧でファイルを選択してください。")
            return None
        return lbl

    def _row_add(self):
        import numpy as np
        lbl = self._edit_target()
        if not lbl:
            return
        df = self.datasets[lbl]
        df.loc[len(df)] = [np.nan] * df.shape[1]
        df.reset_index(drop=True, inplace=True)
        self._data_record({"kind": "row_add", "label": lbl})
        self._populate_preview(df, label=lbl)
        if len(df) > PREVIEW_ROWS:
            self._set_status(f"行を追加（全{len(df)}行。表示は先頭{PREVIEW_ROWS}行）")
        self._request_redraw()

    def _row_del(self):
        lbl = self._edit_target()
        if not lbl:
            return
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        if not rows:
            self._set_status("削除する行を選択してください。")
            return
        df = self.datasets[lbl]
        self._data_record({"kind": "row_del", "label": lbl, "rows": rows,
                           "data": df.iloc[rows].copy()})
        df.drop(df.index[rows], inplace=True)
        df.reset_index(drop=True, inplace=True)
        self._populate_preview(df, label=lbl)
        self._request_redraw()

    def _col_add(self):
        lbl = self._edit_target()
        if not lbl:
            return
        name, ok = QtWidgets.QInputDialog.getText(self, "列追加", "新しい列名:")
        name = (name or "").strip()
        if not ok or not name:
            return
        df = self.datasets[lbl]
        if name in df.columns:
            QtWidgets.QMessageBox.warning(self, "列追加", "同名の列が既にあります。")
            return
        df[name] = 0.0
        self._data_record({"kind": "col_add", "label": lbl, "name": name})
        self._populate_preview(df, label=lbl)
        self._refresh_columns()      # X/Y軸の候補へ反映
        self._set_status(f"列「{name}」を追加（値0.0で初期化）")

    # ------------------------------------------------------------ データ編集の Undo / Redo
    # 設定のUndo（Ctrl+Z）とは別に、セル編集・行追加/削除・列追加を逆操作で戻せる。
    # 位置ベースの記録だが、スタックを順に戻す/やり直す限り整合する（LIFO前提）。
    def _data_record(self, op):
        if not hasattr(self, "_data_hist"):
            self._data_hist, self._data_hist_i = [], -1
        del self._data_hist[self._data_hist_i + 1:]   # redo分岐を捨てる
        self._data_hist.append(op)
        if len(self._data_hist) > 100:
            self._data_hist.pop(0)
        self._data_hist_i = len(self._data_hist) - 1

    def _data_undo(self):
        hist = getattr(self, "_data_hist", None)
        if not hist or self._data_hist_i < 0:
            self._set_status("戻せるデータ編集はありません。")
            return
        op = hist[self._data_hist_i]
        if self._data_apply(op, forward=False):
            self._data_hist_i -= 1
            self._set_status(f"データ編集を戻しました（{self._data_op_name(op)}）。")

    def _data_redo(self):
        hist = getattr(self, "_data_hist", None)
        if not hist or self._data_hist_i >= len(hist) - 1:
            self._set_status("やり直せるデータ編集はありません。")
            return
        op = hist[self._data_hist_i + 1]
        if self._data_apply(op, forward=True):
            self._data_hist_i += 1
            self._set_status(f"データ編集をやり直しました（{self._data_op_name(op)}）。")

    @staticmethod
    def _data_op_name(op):
        return {"cell": "セル編集", "row_add": "行追加",
                "row_del": "行削除", "col_add": "列追加"}.get(op["kind"], op["kind"])

    def _data_apply(self, op, forward):
        """opを適用（forward=True）/逆適用（False）する。対象ファイルが無ければ何もしない。"""
        import pandas as pd
        label = op["label"]
        df = self.datasets.get(label)
        if df is None:
            self._set_status(f"対象ファイル「{label}」は読み込まれていません。")
            return False
        kind = op["kind"]
        if kind == "cell":
            r, c = op["row"], op["col"]
            if r >= len(df) or c >= df.shape[1]:
                return False
            df.iat[r, c] = op["new"] if forward else op["old"]
        elif kind == "row_add":
            if forward:
                import numpy as np
                df.loc[len(df)] = [np.nan] * df.shape[1]
                df.reset_index(drop=True, inplace=True)
            else:
                if not len(df):
                    return False
                df.drop(df.index[-1], inplace=True)
                df.reset_index(drop=True, inplace=True)
        elif kind == "row_del":
            if forward:
                df.drop(df.index[op["rows"]], inplace=True)
                df.reset_index(drop=True, inplace=True)
            else:   # 削除した行を元の位置へ差し戻す（1回のconcatで済ませる）
                parts, prev = [], 0
                for j, r in enumerate(op["rows"]):
                    cut = r - j
                    parts.append(df.iloc[prev:cut])
                    parts.append(op["data"].iloc[[j]])
                    prev = cut
                parts.append(df.iloc[prev:])
                self.datasets[label] = pd.concat(parts, ignore_index=True)
        elif kind == "col_add":
            if forward:
                self.datasets[label][op["name"]] = 0.0
            else:
                self.datasets[label].drop(columns=[op["name"]], inplace=True, errors="ignore")
        df2 = self.datasets[label]
        if getattr(self, "_preview_label", None) == label:
            self._populate_preview(df2, label=label)
        if kind == "col_add":
            self._refresh_columns()   # X/Y候補・ツリーへ反映
        self._request_redraw()
        return True

    def _save_csv(self):
        lbl = self._edit_target()
        if not lbl:
            return
        default = lbl if lbl.lower().endswith((".csv", ".tsv")) else lbl + ".csv"
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "CSV/TSVとして保存", default,
            "CSV (*.csv);;TSV (*.tsv);;全てのファイル (*.*)")
        if not path:
            return
        try:
            sep = "\t" if path.lower().endswith(".tsv") else ","
            self.datasets[lbl].to_csv(path, index=False, sep=sep, encoding="utf-8-sig")
            self._set_status(f"保存しました: {path}（全{len(self.datasets[lbl])}行）")
        except Exception as e:  # noqa: BLE001
            QtWidgets.QMessageBox.critical(self, "保存エラー", str(e))
