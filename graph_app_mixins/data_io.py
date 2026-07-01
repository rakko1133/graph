# -*- coding: utf-8 -*-
"""DataIOMixin: GraphApp から分離した DataIOMixin 群（挙動は本体と同一）。"""
from graph_app_common import *  # noqa: F401,F403


class DataIOMixin:
    # ------------------------------------------------------------ D&D
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = []
        for url in event.mimeData().urls():
            p = url.toLocalFile()
            if p and os.path.splitext(p)[1].lower() in (".csv", ".tsv", ".txt", ".xlsx", ".xlsm", ".xls"):
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
            "データ (*.csv *.tsv *.txt *.xlsx *.xls *.xlsm);;Excel (*.xlsx *.xls *.xlsm);;"
            "CSV/TSV (*.csv *.tsv *.txt);;すべて (*.*)")
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
        enc = self.enc_combo.currentText()
        enc = None if enc.startswith("自動") else enc
        delim = None
        dt = self.delim_combo.currentText()
        if not dt.startswith("自動"):
            for ch, lbl in data_loader.DELIMITER_LABELS.items():
                if lbl == dt:
                    delim = ch
                    break
        size = os.path.getsize(path) if os.path.isfile(path) else 0
        busy = size > 5_000_000   # 5MB 超は待機カーソル＋進捗
        if busy:
            QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
            self._set_status(f"読み込み中… {os.path.basename(path)}")
            QtWidgets.QApplication.processEvents()
        try:
            df, used_enc, used_delim = data_loader.load_table(path, encoding=enc, delimiter=delim)
        except Exception as e:  # noqa: BLE001
            QtWidgets.QMessageBox.critical(self, "読み込みエラー", f"{os.path.basename(path)}\n\n{e}")
            return
        finally:
            if busy:
                QtWidgets.QApplication.restoreOverrideCursor()
        label = os.path.basename(path)
        base, i = label, 2
        while label in self.datasets and self.meta.get(label, {}).get("path") != path:
            label = f"{base} ({i})"; i += 1
        self.datasets[label] = df
        self.meta[label] = {"path": path, "enc": used_enc, "delim": used_delim}
        if not self._find_file_item(label):
            self._add_file_item(label)
        self._push_recent(path)
        self._set_status(f"{label} を読み込み（{len(df)}行 × {len(df.columns)}列, {used_enc}）")

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

        # Y軸候補（ファイル｜列）。選択状態は表示名ではなく安定した
        # (ファイル, 列) 識別子で保持する（ファイル数で表示名が変わっても消えない）。
        checked = QtCore.Qt.CheckState.Checked
        unchecked = QtCore.Qt.CheckState.Unchecked
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
            for r in range(len(head)):
                for c in range(len(cols)):
                    v = head.iat[r, c]
                    self.table.setItem(r, c, QtWidgets.QTableWidgetItem("" if pd.isna(v) else str(v)))
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
        df.iat[r, c] = val
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
        self._populate_preview(df, label=lbl)
        if len(df) > PREVIEW_ROWS:
            self._set_status(f"行を追加（全{len(df)}行。表示は先頭{PREVIEW_ROWS}行）")
        self._request_redraw()

    def _row_del(self):
        lbl = self._edit_target()
        if not lbl:
            return
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        if not rows:
            self._set_status("削除する行を選択してください。")
            return
        df = self.datasets[lbl]
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
        self._populate_preview(df, label=lbl)
        self._refresh_columns()      # X/Y軸の候補へ反映
        self._set_status(f"列「{name}」を追加（値0.0で初期化）")

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
