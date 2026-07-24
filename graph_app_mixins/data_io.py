# -*- coding: utf-8 -*-
"""DataIOMixin: GraphApp から分離した DataIOMixin 群（挙動は本体と同一）。"""
from graph_app_common import *  # noqa: F401,F403


class DataIOMixin:
    # ------------------------------------------------------------ D&D
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    # 対応拡張子の定義は data_loader に一本化（D&D・ダイアログ・フォルダ読込で共通）
    _ACCEPT_EXTS = data_loader.ACCEPT_EXTS

    def dropEvent(self, event):
        paths = []
        for url in event.mimeData().urls():
            p = url.toLocalFile()
            if p and os.path.splitext(p)[1].lower() in self._ACCEPT_EXTS:
                paths.append(p)
        if not paths:
            return
        self.last_dir = os.path.dirname(paths[-1])
        self._load_files_async(paths)

    # ------------------------------------------------------------ ファイル
    def add_file(self):
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self, "ファイルを追加（複数選択可）", self.last_dir,
            data_loader.file_dialog_filter())
        if paths:
            self.last_dir = os.path.dirname(paths[-1])
            self._load_files_async(paths)

    def paste_from_clipboard(self):
        """クリップボードの表データ（Excel等からのコピー＝TSV/CSV）を新規データとして読み込む。"""
        import io
        import pandas as pd
        text = QtWidgets.QApplication.clipboard().text()
        if not text or not text.strip():
            self.notify("クリップボードに表データがありません。", "info")
            return
        first = text.splitlines()[0]
        sep = "\t" if first.count("\t") >= first.count(",") else ","   # Excelコピーはタブ区切り
        try:
            df = pd.read_csv(io.StringIO(text), sep=sep, engine="python", skip_blank_lines=True)
            df = data_loader._normalize_columns(df)
        except Exception as e:  # noqa: BLE001
            self.notify(f"表として読み取れませんでした:\n{e}", "warn")
            return
        if df.shape[1] == 0 or len(df) == 0:
            self.notify("表として読み取れませんでした。", "warn")
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

    # ------------------------------------------------------------ 読み込み
    # 読み込みは「GUI が必要な準備」「重い解析」「GUI への登録」の3段に分かれる。
    # 重い部分だけをワーカースレッドへ出せるように分割してある。
    def _load_job(self, path):
        """読み込みの準備（GUIスレッドで行う部分）。ジョブ辞書か None を返す。"""
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
            try:
                sheets = data_loader.excel_sheet_names(path)
            except Exception as e:  # noqa: BLE001  壊れたブックはここで弾く
                self.notify(f"{os.path.basename(path)} のシートを読めませんでした。",
                            "error", str(e))
                return None
            if len(sheets) > 1:
                sheet, ok = QtWidgets.QInputDialog.getItem(
                    self, "シートの選択", f"{os.path.basename(path)} のシート:",
                    sheets, 0, False)
                if not ok:
                    return None
        return {"path": path, "enc": enc, "delim": delim, "sheet": sheet}

    def register_dataset(self, base_label, df, *, path=None, enc="-", delim="-",
                         status=None):
        """生成したデータを新しいデータセットとして登録する。

        数学チャンネル・カーブフィットなどが作った表を
        取り込む共通口。同名があれば「(2)」を付けて重複を避け、ファイル一覧と
        列一覧まで更新する。使う側は「何を作ったか」だけ書けばよい。

        path を省くとラベルをそのまま入れる（＝ディスク上の実体は無い印。
        reload_current はこれを見て再読込を断る）。
        """
        label, i = base_label, 2
        while label in self.datasets:
            label = f"{base_label} ({i})"
            i += 1
        self.datasets[label] = df
        self.meta[label] = {"path": path if path is not None else label,
                            "enc": enc, "delim": delim}
        self._add_file_item(label)
        self._refresh_columns()
        if status:
            self._set_status(status.format(label=label))
        return label

    def _register_loaded(self, job, result):
        """読み込み結果をデータセットへ登録する（GUIスレッドで行う部分）。"""
        path, sheet = job["path"], job.get("sheet")
        df, used_enc, used_delim = result
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
        return label

    def _load_file(self, path):
        """1ファイルを同期読み込みする（小さいファイル・スクリプト用の従来API）。"""
        if os.path.splitext(path)[1].lower() in data_loader.RUNNABLE_EXTS:
            self.run_ltspice_asc(path)   # 回路図/ネットリストは実行→.raw読込
            return
        job = self._load_job(path)
        if job is None:
            return
        size = os.path.getsize(path) if os.path.isfile(path) else 0
        busy = size > 5_000_000   # 5MB 超は待機カーソル
        if busy:
            QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
            self._set_status(f"読み込み中… {os.path.basename(path)}")
            QtWidgets.QApplication.processEvents()
        try:
            result = data_loader.load_table(
                path, encoding=job["enc"], delimiter=job["delim"], sheet=job["sheet"])
        except Exception as e:  # noqa: BLE001
            self.notify(f"{os.path.basename(path)} を読み込めませんでした。", "error", str(e))
            return
        finally:
            if busy:
                QtWidgets.QApplication.restoreOverrideCursor()
        self._register_loaded(job, result)

    # ---- 非同期読み込み（GUIを固まらせない）----
    def _load_files_async(self, paths, on_finished=None):
        """複数ファイルをワーカースレッドで読み込む。

        pandas の解析は Qt に触らないのでスレッドで実行できる。GUI が必要な
        準備（シート選択）と登録だけをメインスレッドで行い、その間ウィンドウは
        操作可能なまま。進捗バーの「キャンセル」で途中中止できる。"""
        paths = list(paths)
        for p in [p for p in paths if os.path.splitext(p)[1].lower() in data_loader.RUNNABLE_EXTS]:
            self.run_ltspice_asc(p)       # 回路は別系統（QProcess）で非同期実行
        targets = [p for p in paths
                   if os.path.splitext(p)[1].lower() not in data_loader.RUNNABLE_EXTS]
        jobs = []
        for p in targets:
            job = self._load_job(p)       # シート選択などはここで先に済ませる
            if job is not None:
                jobs.append(job)
        if not jobs:
            if on_finished:
                on_finished([])
            return None
        if getattr(self, "_load_thread", None) is not None:
            self.notify("前の読み込みが実行中です。終わるまでお待ちください。", "warn")
            return None

        loaded, errors = [], []

        # 小さくて少ない読み込みは、その場で済ませる。スレッド起動と進捗バーの
        # 明滅のほうが待ち時間より長く、呼び出し側から見た完了タイミングも
        # 素直になる（フリーズが問題になるのは大きい・多いときだけ）。
        total_bytes = 0
        for job in jobs:
            try:
                total_bytes += os.path.getsize(job["path"])
            except OSError:
                applog.get_logger().debug("_load_files_async: 無視した例外", exc_info=True)
        if len(jobs) <= ASYNC_LOAD_COUNT and total_bytes <= ASYNC_LOAD_BYTES:
            for job in jobs:
                name = os.path.basename(job["path"])
                try:
                    res = data_loader.load_table(
                        job["path"], encoding=job["enc"], delimiter=job["delim"],
                        sheet=job["sheet"])
                    loaded.append(self._register_loaded(job, res))
                except Exception as e:  # noqa: BLE001
                    errors.append(f"{name}: {e}")
            self._refresh_columns()
            if loaded and self._has_drawn:
                self.draw_graph()
            if errors:
                self.notify(f"{len(errors)} 件のファイルを読み込めませんでした。",
                            "error", "\n".join(errors))
            if on_finished:
                on_finished(loaded)
            return None

        def _on_one(index, result, err):
            job = jobs[index]
            name = os.path.basename(job["path"])
            if result is None:
                errors.append(f"{name}: {err}")
            else:
                try:
                    loaded.append(self._register_loaded(job, result))
                except Exception as e:  # noqa: BLE001  登録側の失敗も1件ずつ報告
                    errors.append(f"{name}: {e}")
            self.progress_strip.update(index + 1)

        def _on_progress(done, name):
            self.progress_strip.update(done, f"読み込み中… {name}（{done + 1}/{len(jobs)}）")

        def _on_finished():
            thread = getattr(self, "_load_thread", None)
            canceled = bool(thread is not None and thread.is_canceled())
            self._load_thread = None
            self.progress_strip.finish()
            self._refresh_columns()
            if loaded and self._has_drawn:
                self.draw_graph()
            if errors:
                self.notify(f"{len(errors)} 件のファイルを読み込めませんでした。",
                            "error", "\n".join(errors))
            elif canceled:
                self.notify(f"読み込みを中止しました（{len(loaded)} 件は読み込み済み）。", "warn")
            elif loaded:
                self.notify(f"{len(loaded)} 件のファイルを読み込みました。", "ok")
            if on_finished:
                on_finished(loaded)

        thread = TableLoadThread(jobs, self)
        self._load_thread = thread
        thread.one_done.connect(_on_one)
        thread.progressed.connect(_on_progress)
        thread.finished.connect(_on_finished)
        self.progress_strip.start(f"読み込み中…（0/{len(jobs)}）", len(jobs))
        thread.start()
        return thread

    def _cancel_background(self):
        """進捗バーのキャンセルボタン。実行中のワーカーへ中止を伝える。"""
        thread = getattr(self, "_load_thread", None)
        if thread is not None:
            thread.cancel()
            self._set_status("読み込みの中止を要求しました（実行中の1件が終わり次第停止）。")

    def _stop_background_tasks(self):
        """終了時にワーカースレッドを止める（スレッド生存中の破棄を避ける）。"""
        thread = getattr(self, "_load_thread", None)
        if thread is not None:
            thread.cancel()
            thread.wait(5000)
            self._load_thread = None

    def wait_for_loads(self, timeout_ms=30000):
        """非同期読み込みの完了を待つ（スクリプト・テストから使う同期用）。

        イベントループを回しながら待つので、登録処理（メインスレッド側）も
        きちんと進む。GUI 操作からは使わない。"""
        app = QtWidgets.QApplication.instance()
        deadline = QtCore.QElapsedTimer()
        deadline.start()
        while getattr(self, "_load_thread", None) is not None:
            if deadline.hasExpired(timeout_ms):
                return False
            if app is not None:
                app.processEvents(QtCore.QEventLoop.ProcessEventsFlag.AllEvents, 20)
        if app is not None:
            app.processEvents()
        return True

    # ------------------------------------------------------------ フォルダを開く
    def add_folder(self):
        """フォルダ内の対応データファイルを一括で読み込む（VS Codeの「フォルダを開く」相当）。"""
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "フォルダを開く", self.last_dir)
        if d:
            self._load_folder(d)

    def _load_folder(self, d):
        exts = set(data_loader.TABLE_EXTS)   # 回路(.asc/.net)は誤爆実行を避けて除外
        try:
            names = sorted(os.listdir(d))
        except OSError as e:
            QtWidgets.QMessageBox.critical(self, "フォルダを開く", str(e))
            return
        files = [os.path.join(d, f) for f in names
                 if os.path.splitext(f)[1].lower() in exts
                 and os.path.isfile(os.path.join(d, f))]
        if not files:
            self.notify("このフォルダに読み込めるデータファイルがありません。", "warn")
            return
        if len(files) > 40:
            ret = QtWidgets.QMessageBox.question(
                self, "フォルダを開く",
                f"{len(files)} 個のファイルが見つかりました。すべて読み込みますか？")
            if ret != QtWidgets.QMessageBox.StandardButton.Yes:
                return
        self.last_dir = d
        self._load_files_async(
            files,
            on_finished=lambda labels: self.notify(
                f"フォルダを読み込みました: {os.path.basename(d)}"
                f"（{len(labels)}/{len(files)} ファイル）", "ok"))

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
            applog.get_logger().debug("_ltspice_exe: 無視した例外", exc_info=True)
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
            self.notify(f"シミュレーションは終了しましたが .raw が見つかりません（終了コード {code}）。\n"
                        f"回路にエラーがないか LTspice で確認してください:\n{asc_path}", "warn")
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
            self.notify(f"ファイルが見つかりません:\n{path}", "warn")
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
            self.notify("削除するファイルを選択してください。", "warn")
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
            self.notify("読み込み済みファイルがありません。", "warn")
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
        """選択中のファイルをディスクから読み直す。

        読み込み元の実体が無いデータ（クリップボード貼り付け・数学チャンネル・
        フィット/PCA などの生成物）は再読込できない。以前はここで先に
        datasets から取り除いてから読み直そうとしていたため、読み込みに
        失敗した時点で**データが永久に消えていた**。先に確認してから外す。"""
        it = self.file_list.currentItem()
        if not it:
            self.notify("ファイルを選択してください。", "warn")
            return
        label = it.text()
        meta = dict(self.meta.get(label) or {})
        path = meta.get("path", "")
        if not path or not os.path.isfile(path):
            self.notify(f"『{label}』は読み込み元のファイルが無いので再読込できません。",
                        "warn",
                        "貼り付けたデータや、数学チャンネル・カーブフィットなどで"
                        "作ったデータセットが該当します（データはそのまま残しました）。")
            return
        df = self.datasets.get(label)
        row = self.file_list.row(it)
        self.datasets.pop(label, None)
        self.meta.pop(label, None)
        self.file_list.takeItem(row)
        self._load_file(path)
        if label not in self.datasets and df is not None:
            # 読み直しに失敗した（ファイルが壊れた等）。元の内容へ戻す。
            self.datasets[label] = df
            self.meta[label] = meta
            if not self._find_file_item(label):
                self._add_file_item(label)
            self.notify(f"『{label}』を読み直せなかったので、元の内容を残しました。", "warn")
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
            self.notify("左の一覧でファイルを選択してください。", "warn")
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
            self.notify("同名の列が既にあります。", "warn")
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

    def _build_tab_data(self):
        w = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(w)
        v.setContentsMargins(2, 2, 2, 2)
        note = QtWidgets.QLabel("Y系列の選択は「読み込み済みファイル」ウィンドウで行います"
                                "（表示メニューから再表示できます）。")
        note.setWordWrap(True); note.setStyleSheet("color:#666;")
        v.addWidget(note)
        # 軸の選択（X/Y/Z と 3D表示）。「何をプロットするか」をここに集約する
        sec_axes = self._fmt_section("軸の選択（X・Z・3D）", "axes_sel", True)
        v.addWidget(sec_axes)
        av = QtWidgets.QVBoxLayout()
        av.addWidget(QtWidgets.QLabel("X軸（横軸 / ラベル）"))
        self.xleft_check = QtWidgets.QCheckBox("一番左の列をX軸にする（位置で固定）")
        self.xleft_check.setToolTip(
            "ONにすると各ファイルの『一番左の列』をX軸に使います（列名が違っても適用）。\n"
            "複数ファイル／バッチ出力でX軸を固定したいときに便利。\n"
            "OFFなら下のコンボで列名を指定します。")
        self.xleft_check.toggled.connect(self._on_xleft_toggled)
        av.addWidget(self.xleft_check)
        self.x_combo = QtWidgets.QComboBox()
        self.x_combo.setToolTip("横軸に使う列（列名で指定）。波形なら時間列を選びます。")
        self.x_combo.currentTextChanged.connect(self._on_x_changed)
        av.addWidget(self.x_combo)

        # X↔Y 入れ替え／X軸を複数選択（散布図などの 2D xy 種別で有効）
        xrow = QtWidgets.QHBoxLayout()
        self.swap_xy_check = QtWidgets.QCheckBox("X↔Y 入れ替え")
        self.swap_xy_check.setToolTip("XとYを入れ替えて描く（軸の“向き反転”0→1↔1→0 とは別）。"
                                      "散布図・折れ線などの2D種別で有効。")
        self.swap_xy_check.toggled.connect(self._request_redraw)
        xrow.addWidget(self.swap_xy_check)
        self.multix_check = QtWidgets.QCheckBox("X軸を複数選択")
        self.multix_check.setToolTip("ONにすると下のリストでチェックした複数の列をXにし、"
                                     "各X×各Yの組み合わせを系列として描きます。")
        self.multix_check.setEnabled(False)
        self.multix_check.toggled.connect(self._on_multix_toggled)
        xrow.addWidget(self.multix_check); xrow.addStretch(1)
        av.addLayout(xrow)
        self.x_list = CheckListWidget()
        self.x_list.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.NoSelection)
        self.x_list.setToolTip("『X軸を複数選択』ON時に、Xに使う列をチェックします。")
        self.x_list.setStyleSheet("QListWidget::indicator { width:16px; height:16px; }")
        self.x_list.setMaximumHeight(90)
        self.x_list.itemChanged.connect(self._request_redraw)
        self.x_list.setEnabled(False)
        av.addWidget(self.x_list)

        self.z_label = QtWidgets.QLabel("Z軸（3Dの奥行き）")
        av.addWidget(self.z_label)
        self.z_combo = QtWidgets.QComboBox()
        self.z_combo.setToolTip("3Dグラフの奥行き（Z軸）に使う列。3D種別のときだけ有効になります。")
        self.z_combo.currentTextChanged.connect(self._on_x_changed)
        self.z_combo.setEnabled(False)
        av.addWidget(self.z_combo)

        # 3D表示はZ軸とセットの「何をプロットするか」の設定なので、ここ（軸の選択）に置く
        self.threed_check = QtWidgets.QCheckBox("3D表示（Z軸を使う・ドラッグで回転）")
        self.threed_check.setToolTip(
            "散布図・折れ線・棒でONにするとZ軸を使った3D描画になります。\n"
            "曲面は常に3Dです。3D対応でない種別では選べません（種別は書式パネルで選択）。")
        self.threed_check.setEnabled(False)
        self.threed_check.toggled.connect(self._on_3d_toggled)
        av.addWidget(self.threed_check)
        view = QtWidgets.QHBoxLayout()
        view.addWidget(QtWidgets.QLabel("3D視点 仰角"))
        self.elev_spin = QtWidgets.QSpinBox(); self.elev_spin.setRange(-90, 90)
        self.elev_spin.setValue(30)
        self.elev_spin.setToolTip("3Dグラフの仰角（上下の見おろし角）。ドラッグでも回転できます。")
        self.elev_spin.valueChanged.connect(self._on_view_angle_changed)
        view.addWidget(self.elev_spin)
        view.addWidget(QtWidgets.QLabel("方位"))
        self.azim_spin = QtWidgets.QSpinBox(); self.azim_spin.setRange(-180, 180)
        self.azim_spin.setValue(-60)
        self.azim_spin.setToolTip("3Dグラフの方位（左右の回転角）。ドラッグでも回転できます。")
        self.azim_spin.valueChanged.connect(self._on_view_angle_changed)
        view.addWidget(self.azim_spin)
        view.addStretch(1)
        self.elev_spin.setEnabled(False); self.azim_spin.setEnabled(False)
        av.addLayout(view)
        sec_axes.set_content_layout(av)

        # 旧Yリストは非表示の「選択モデル」として保持（ツリー・系列バー・
        # 設定復元・テストが (ファイル, 列) 単位でここを読む）。レイアウトには足さない。
        self.y_list = CheckListWidget()
        self.y_list.setVisible(False)
        self.y_list.itemChanged.connect(self._on_y_check_changed)
        self.y_list.itemDoubleClicked.connect(self._on_y_double_clicked)
        v.addStretch(1)
        return w
