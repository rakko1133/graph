# [28/30] ファイル `graph_app_mixins/batch.py` を作成

あなたは PySide6 + matplotlib 製のデスクトップアプリ「CSV / TSV / 波形 グラフ・解析ツール」を、複数ファイルに分けて再現しています。
これはその **28 番目** のファイルです（全 30 ファイル）。

## 指示（厳守）
- 下のコードブロックの内容で、ファイル `graph_app_mixins/batch.py` を**新規作成**してください。
- **一字一句そのまま・省略なし**で出力すること。`pass` だけの空クラス／`# TODO`／`… 省略 …`／要約・解説への置き換えは**禁止**。
- 出力が途中で切れたら、こちらが「続き」と言うので、**最後の行まで**出力してください。
- 前置き・後書き・他ファイルの説明は不要。**このファイルの完全な中身だけ**を返してください。
- 文字コードは UTF-8。フォルダ付きパス（例 `graph_app_mixins/...`）はその階層に作成してください。

## `graph_app_mixins/batch.py` の中身（このまま出力）
```python
# -*- coding: utf-8 -*-
"""BatchMixin: GraphApp から分離した BatchMixin 群（挙動は本体と同一）。"""
from graph_app_common import *  # noqa: F401,F403


class BatchMixin:
    # ------------------------------------------------------------ 補助
    def _save_current_figure(self, target, dpi, transparent, fmt=None):
        """現在のグラフを保存。縦横比の指定があれば画像そのものをその比率にする
        （図を比率サイズにして bbox トリミングせず保存）。自動なら従来どおり tight 保存。"""
        ratio = self._aspect_ratio()
        if not ratio:
            self.fig.savefig(target, dpi=dpi, bbox_inches="tight",
                             transparent=transparent, format=fmt)
            return
        orig = self.fig.get_size_inches()
        try:
            self.fig.set_size_inches(self._export_figsize())
            self.ax.set_box_aspect(None)          # 図いっぱいに描く（枠固定を一時解除）
            ax2 = getattr(self.ax, "_twin_secondary", None)
            if ax2 is not None:
                ax2.set_box_aspect(None)
            try:
                self.fig.tight_layout()
            except Exception:
                pass
            self.fig.savefig(target, dpi=dpi, transparent=transparent, format=fmt)
        finally:
            self.fig.set_size_inches(orig)        # 画面表示用に元のサイズへ戻す
            self._apply_aspect()
            try:
                self.fig.tight_layout()
            except Exception:
                pass
            self.canvas.draw_idle()

    def save_figure(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "グラフ画像を保存", os.path.join(self.last_dir, "graph.png"),
            "PNG (*.png);;JPEG (*.jpg);;PDF (*.pdf);;SVG (*.svg);;EPS (*.eps)")
        if not path:
            return
        try:
            dpi = self.dpi_spin.value()
            transparent = self.transparent_check.isChecked()
            self._save_current_figure(path, dpi, transparent)
            self.last_dir = os.path.dirname(path)
            self._set_status(f"保存しました: {path}（{dpi} DPI{'・背景透過' if transparent else ''}）")
        except Exception as e:  # noqa: BLE001
            QtWidgets.QMessageBox.critical(self, "保存エラー", str(e))

    def copy_figure(self):
        """現在のグラフを画像としてクリップボードにコピーする。"""
        import io
        try:
            buf = io.BytesIO()
            self._save_current_figure(buf, self.dpi_spin.value(),
                                      self.transparent_check.isChecked(), fmt="png")
            buf.seek(0)
            img = QtGui.QImage.fromData(buf.getvalue(), "PNG")
            if img.isNull():
                raise RuntimeError("画像の生成に失敗しました。")
            QtWidgets.QApplication.clipboard().setImage(img)
            self._set_status("グラフをクリップボードにコピーしました。")
        except Exception as e:  # noqa: BLE001
            QtWidgets.QMessageBox.critical(self, "コピーエラー", str(e))

    # ------------------------------------------------------------ 一括出力
    @staticmethod
    def _safe_filename(name):
        import re
        return re.sub(r'[\\/:*?"<>|]+', "_", str(name)).strip() or "graph"

    def _build_series_for_file(self, label, x_name, y_names, chart_type, style_by_col):
        """1ファイルから、指定した列名テンプレートで系列を作る（一括出力用）。
        『一番左の列をX軸』ONなら、各ファイルの先頭列を位置でX軸に使う。"""
        df = self.datasets[label]
        series, categories = [], None
        leftmost = self._use_leftmost_x()
        xv = (df.iloc[:, 0].to_numpy() if leftmost
              else (df[x_name].to_numpy() if x_name in df.columns else df.iloc[:, 0].to_numpy()))
        if chart_type in ("棒", "横棒", "積み上げ棒", "円"):
            categories = xv
            for c in y_names:
                series.append({"label": c, "y": df[c].to_numpy(),
                               "style": style_by_col.get(c)})
        elif chart_type in ("折れ線", "散布図"):
            for c in y_names:
                st = style_by_col.get(c) or {}
                errcol = st.get("errcol")
                yerr = df[errcol].to_numpy() if (errcol and errcol in df.columns) else None
                series.append({"label": c, "x": xv, "y": df[c].to_numpy(), "style": st,
                               "axis": st.get("axis", "primary"),
                               "kind": st.get("kind", ""), "yerr": yerr})
        else:  # ヒストグラム / 箱ひげ
            for c in y_names:
                series.append({"label": c, "y": df[c].to_numpy(),
                               "style": style_by_col.get(c)})
        return series, categories

    def _batch_options_dialog(self):
        """一括出力の調整（タイトル・形式・DPI・透過）。OKで dict、キャンセルで None。"""
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("一括画像保存の設定")
        form = QtWidgets.QFormLayout(dlg)
        info = QtWidgets.QLabel("各ファイルを現在のグラフ設定で1枚ずつ保存します。\n"
                                "軸名・凡例・近似曲線・縦横比などは右の書式パネルの値を使います。")
        info.setStyleSheet("color:#666;"); form.addRow(info)
        title_edit = QtWidgets.QLineEdit(self.title_edit.text() or "{name}")
        title_edit.setToolTip("グラフタイトル。{name} はファイル名（拡張子なし）に置き換わります。")
        form.addRow("グラフタイトル", title_edit)
        fmt_combo = QtWidgets.QComboBox(); fmt_combo.addItems(["png", "jpg", "pdf", "svg"])
        form.addRow("出力形式", fmt_combo)
        dpi_spin = QtWidgets.QSpinBox(); dpi_spin.setRange(50, 1200)
        dpi_spin.setSingleStep(50); dpi_spin.setValue(self.dpi_spin.value())
        form.addRow("解像度 DPI", dpi_spin)
        trans = QtWidgets.QCheckBox(); trans.setChecked(self.transparent_check.isChecked())
        form.addRow("背景透過", trans)
        bb = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        bb.button(QtWidgets.QDialogButtonBox.StandardButton.Ok).setText("フォルダを選んで保存...")
        bb.accepted.connect(dlg.accept); bb.rejected.connect(dlg.reject)
        form.addRow(bb)
        if dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return None
        title = title_edit.text().strip() or "{name}"
        return {"title": title, "fmt": fmt_combo.currentText(),
                "dpi": dpi_spin.value(), "transparent": trans.isChecked()}

    def batch_export(self):
        """読み込んだ各ファイルを、現在の設定で個別に描画してファイル名ごとに一括保存する。"""
        if not self.datasets:
            QtWidgets.QMessageBox.information(self, "情報", "先にファイルを追加してください。")
            return
        ctype = self.chart_combo.currentText()
        # テンプレート＝選択中Y系列の「列名」（順序保持・重複除去）とそのスタイル
        y_names, style_by_col = [], {}
        for fl, col, disp in self._selected_series_items():
            if col not in y_names:
                y_names.append(col)
            style_by_col.setdefault(col, self.series_styles.get(self._style_key(fl, col)))
        # Y軸名が空なら主軸の列名から自動生成（画面描画と同じ規則）
        prim_y = [c for c in y_names
                  if (style_by_col.get(c) or {}).get("axis", "primary") != "secondary"]
        auto_ylabel = self.ylabel_edit.text() or self._auto_y_label(prim_y, ctype)
        if not y_names:
            QtWidgets.QMessageBox.information(
                self, "情報",
                "Y軸（値）の系列を1つ以上選んでください。\n"
                "その列名を各ファイルに適用し、ファイルごとに1枚ずつ出力します。")
            return
        x_name = self.x_combo.currentText()
        opts = self._batch_options_dialog()   # タイトル・形式・DPI・透過を調整
        if opts is None:
            return
        out_dir = QtWidgets.QFileDialog.getExistingDirectory(
            self, "一括出力フォルダを選択", self.last_dir)
        if not out_dir:
            return

        dpi = opts["dpi"]
        transparent = opts["transparent"]
        title_tpl = opts["title"]
        ext = opts["fmt"]
        ratio = self._aspect_ratio()
        fmt = self._plot_format_kwargs()   # 共通フォーマット（bins/grid/凡例/対数/近似/ラベル等）
        # 縦横比の指定があれば画像そのものをその比率に（図サイズで決め、bboxトリミングしない）
        if ratio:
            figsize = self._export_figsize()
            tight = False
        else:
            figsize = self.fig.get_size_inches()
            tight = True
        issues = []
        xlim = self._range_pair(self.xmin, self.xmax, "X", issues)
        ylim = self._range_pair(self.ymin, self.ymax, "Y", issues)
        max_points = (DECIMATE_TARGET if (self.decimate_check.isChecked()
                      and ctype in ("折れ線", "散布図")) else 0)

        # ---- 各ファイルのタスク（picklableなdict）を構築。ファイル名の重複解決は
        #      順序依存なのでここで逐次に確定させ、各タスクに最終パスを持たせる ----
        tasks, skipped, used = [], [], set()
        for label, df in self.datasets.items():
            cols = [c for c in y_names if c in df.columns]
            if not cols:
                skipped.append(f"{label}（対象列なし）")
                continue
            try:
                series, categories = self._build_series_for_file(
                    label, x_name, cols, ctype, style_by_col)
            except Exception as e:  # noqa: BLE001
                skipped.append(f"{label}（{e}）")
                continue
            stem = os.path.splitext(label)[0]
            sec_label = " / ".join(s["label"] for s in series
                                   if s.get("axis") == "secondary")
            xlab = self.xlabel_edit.text() or (
                str(df.columns[0]) if self._use_leftmost_x() else x_name)
            base = self._safe_filename(stem)
            name, k = base, 2
            while name in used:
                name = f"{base}_{k}"; k += 1
            used.add(name)
            tasks.append({
                "series": series, "categories": categories, "ctype": ctype,
                "title": title_tpl.replace("{name}", stem),
                "xlabel": xlab, "ylabel": auto_ylabel,
                "xlim": xlim, "ylim": ylim, "sec_label": sec_label,
                "max_points": max_points, "fmt": fmt, "ratio": None,
                "figsize": tuple(figsize), "tight": tight,
                "dpi": dpi, "transparent": transparent,
                "path": os.path.join(out_dir, f"{name}.{ext}"),
                "font_name": getattr(self, "font_name", None),
            })

        import batch_render
        saved = []
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
        try:
            # ファイル数が多いときだけ別プロセス並列（spawn/ピクル/フォント設定の
            # 固定費があるので少数では逆効果）。失敗時は必ず逐次へフォールバックする。
            use_pool = len(tasks) >= BATCH_PARALLEL_THRESHOLD
            if use_pool:
                try:
                    import concurrent.futures as _cf
                    workers = min(8, (os.cpu_count() or 1))
                    with _cf.ProcessPoolExecutor(max_workers=workers) as ex:
                        futs = {ex.submit(batch_render.render_one, t): t for t in tasks}
                        for fut in _cf.as_completed(futs):
                            try:
                                saved.append(fut.result())
                            except Exception as e:  # noqa: BLE001
                                skipped.append(
                                    f"{os.path.basename(futs[fut]['path'])}（{e}）")
                            QtWidgets.QApplication.processEvents()
                except Exception as e:  # noqa: BLE001  プール作成失敗/壊れ→逐次へ
                    self._set_status(f"並列出力に失敗、逐次に切替: {e}")
                    use_pool = False
                    saved = []        # 部分結果は破棄し、逐次で全件作り直す
            if not use_pool:
                saved, seq_skipped = batch_render.render_sequential(tasks)
                skipped.extend(seq_skipped)
                QtWidgets.QApplication.processEvents()
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

        self.last_dir = out_dir
        msg = f"一括出力: {len(saved)} 件を保存しました。\n{out_dir}"
        if skipped:
            head = " / ".join(str(s) for s in skipped[:5])
            msg += f"\n\nスキップ {len(skipped)} 件: {head}" + (" ほか" if len(skipped) > 5 else "")
        QtWidgets.QMessageBox.information(self, "一括出力", msg)
        self._set_status(f"一括出力: {len(saved)} 件保存（{out_dir}）")
```
