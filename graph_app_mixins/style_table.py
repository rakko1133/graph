# -*- coding: utf-8 -*-
"""StyleTableMixin: GraphApp から分離した StyleTableMixin 群（挙動は本体と同一）。"""
from graph_app_common import *  # noqa: F401,F403


class StyleTableMixin:
    def _on_x_changed(self, *_):
        self._request_redraw()

    def _on_xleft_toggled(self, on):
        """『一番左の列をX軸』ON時は名前コンボを無効化し、先頭列をY候補から除外/復帰。"""
        self._refresh_columns()        # Y軸候補を作り直し（先頭列の除外/復帰）＋再描画予約
        self._update_x_combo_enabled()  # 有効/無効は最後に確定

    def _update_x_combo_enabled(self):
        """X名コンボの有効状態を、グラフ種別と『一番左の列をX軸』から決める。"""
        info = plotter.CHART_INFO.get(self.chart_combo.currentText(), {})
        self.x_combo.setEnabled(info.get("use_x", True) and not self._use_leftmost_x())

    def _update_z_combo_enabled(self):
        """Z名コンボ（3Dの奥行き軸）の有効状態を種別から決める。3D種別のみ有効。"""
        if not hasattr(self, "z_combo"):
            return
        info = plotter.CHART_INFO.get(self.chart_combo.currentText(), {})
        self.z_combo.setEnabled(bool(info.get("use_z", False)))

    def _use_leftmost_x(self):
        return bool(getattr(self, "xleft_check", None) and self.xleft_check.isChecked())

    def _x_values(self, df):
        """X軸データ列。『一番左の列』ONなら位置0、OFFなら選択名（無ければ先頭列）。"""
        if self._use_leftmost_x():
            return df.iloc[:, 0].to_numpy()
        xname = self.x_combo.currentText()
        return df[xname].to_numpy() if xname in df.columns else df.iloc[:, 0].to_numpy()

    def _z_values(self, df):
        """Z軸データ列（3D用）。選択名が無ければ最終列で代用する。"""
        zname = self.z_combo.currentText() if hasattr(self, "z_combo") else ""
        return df[zname].to_numpy() if zname in df.columns else df.iloc[:, -1].to_numpy()

    def _effective_x_label(self):
        """既定のX軸ラベル（『一番左の列』ONなら先頭列名、OFFなら選択名）。"""
        if self._use_leftmost_x():
            items = self._selected_series_items()
            if items:
                df = self.datasets.get(items[0][0])
                if df is not None and len(df.columns):
                    return str(df.columns[0])
            return ""
        return self.x_combo.currentText()

    @staticmethod
    def _auto_y_label(names, ctype):
        """系列名からY軸の既定ラベルを作る。1つならその名前、複数は ' / ' で結合
        （長すぎる場合は先頭＋ほかN系列）。ヒストグラムはY軸が頻度なので空。"""
        if ctype == "ヒストグラム":
            return ""
        uniq = list(dict.fromkeys(n for n in names if n))
        if not uniq:
            return ""
        if len(uniq) == 1:
            return uniq[0]
        joined = " / ".join(uniq)
        return joined if len(joined) <= 40 else f"{uniq[0]} ほか{len(uniq) - 1}系列"

    def _file_display_name(self, fl):
        """ファイル名（『拡張子』トグルがオフなら拡張子を除く）。"""
        if hasattr(self, "show_ext_check") and not self.show_ext_check.isChecked():
            return os.path.splitext(fl)[0]
        return fl

    def _series_label(self, fl, col):
        """凡例に使う系列ラベル。ユーザー上書き＞ファイル名表示オプション。
        単一ファイル、または『凡例にファイル名』オフのときは列名のみ。"""
        st = self.series_styles.get(self._style_key(fl, col)) or {}
        if st.get("label"):
            return st["label"]
        multi = len(self.datasets) > 1
        show_fn = (not hasattr(self, "show_filename_check")) or self.show_filename_check.isChecked()
        if multi and show_fn:
            return f"{self._file_display_name(fl)} | {col}"
        return col

    def _effective_y_label(self):
        """既定のY軸ラベル（Y軸名欄が空のとき使用）。主軸の選択系列の『列名』から作る。
        軸名はファイル名を含めず列名ベースにし、全系列が同じ列名ならその1つだけにする
        （第2軸の系列は右側ラベルになるので除外）。"""
        names = []
        for fl, col, disp in self._selected_series_items():
            st = self.series_styles.get(self._style_key(fl, col)) or {}
            if st.get("axis", "primary") == "secondary":
                continue
            names.append(st.get("label") or col)
        return self._auto_y_label(names, self.chart_combo.currentText())

    def _on_y_check_changed(self, _item):
        if self._suspend_redraw:
            return
        self._on_y_selection_changed()

    def _set_all_checks(self, func):
        """func(item) -> bool で各行のチェック状態を一括設定し、まとめて更新。"""
        ck = QtCore.Qt.CheckState.Checked
        un = QtCore.Qt.CheckState.Unchecked
        self.y_list.blockSignals(True)
        for i in range(self.y_list.count()):
            it = self.y_list.item(i)
            it.setCheckState(ck if func(it) else un)
        self.y_list.blockSignals(False)
        self._on_y_selection_changed()

    def _check_all_y(self, checked):
        self._set_all_checks(lambda it: checked)

    def _invert_y(self):
        ck = QtCore.Qt.CheckState.Checked
        self._set_all_checks(lambda it: it.checkState() != ck)

    def select_by_name(self):
        """入力した名前を含む系列だけを選択（他は解除）。複数ファイルで同名列だけ選ぶのに便利。"""
        text = self.y_filter.text().strip()
        if not text:
            self._set_status("名前を入力してください（例: 電圧）。")
            return
        tl = text.lower()

        def match(it):
            fl, col = it.data(UserRole)
            return tl in str(col).lower() or tl in it.text().lower()

        self._set_all_checks(match)
        n = sum(1 for i in range(self.y_list.count())
                if self.y_list.item(i).checkState() == QtCore.Qt.CheckState.Checked)
        self._set_status(f"「{text}」を含む系列を {n} 件選択しました。"
                         if n else f"「{text}」を含む系列はありません。")

    def _select_same_name(self, item):
        """指定系列と同じ列名の系列を（全ファイルから）すべて選択する。"""
        if item is None:
            return
        col = item.data(UserRole)[1]
        self._set_all_checks(lambda it: it.data(UserRole)[1] == col)
        self._set_status(f"列名「{col}」の系列をすべて選択しました。")

    def _on_y_double_clicked(self, item):
        """Y行をダブルクリック → その系列だけにして描画。"""
        self._set_all_checks(lambda it: it is item)
        self.draw_graph()

    def _maybe_draw(self):
        if self.datasets:
            self.draw_graph()

    def _series_menu(self, item):
        """系列の表示/非表示メニュー（Yリスト・上部系列バー共通）。"""
        menu = QtWidgets.QMenu(self)
        if item is not None:
            menu.addAction("この系列だけ表示", lambda: self._solo_series(item))
            menu.addAction("この系列を非表示", lambda: self._hide_series(item))
            menu.addAction("同じ列名をすべて選択",
                           lambda: (self._select_same_name(item), self._maybe_draw()))
            menu.addSeparator()
        menu.addAction("すべて表示", lambda: (self._check_all_y(True), self._maybe_draw()))
        menu.addAction("すべて非表示", lambda: (self._check_all_y(False), self._maybe_draw()))
        return menu

    def _y_list_menu(self, pos):
        """Yリスト右クリックの表示メニュー。"""
        item = self.y_list.itemAt(pos)
        self._series_menu(item).exec(self.y_list.viewport().mapToGlobal(pos))

    def _solo_series(self, item):
        """指定系列だけ表示（他をすべて非表示）。"""
        self._set_all_checks(lambda it: it is item)
        self._maybe_draw()

    def _hide_series(self, item):
        """指定系列を非表示にする（他はそのまま）。"""
        item.setCheckState(QtCore.Qt.CheckState.Unchecked)
        self._maybe_draw()

    def _on_style_label_edited(self, item):
        """系列名（凡例ラベル）の編集を保存して再描画。"""
        if self._suspend_redraw or item.column() != 0:
            return
        key = item.data(UserRole)
        if not key:
            return
        text = item.text().strip()
        st = self.series_styles.setdefault(key, dict(plotter.DEFAULT_STYLE))
        st["label"] = text or None
        self._request_redraw()

    # ------------------------------------------------------------ 系列スタイル
    def _on_y_selection_changed(self):
        self._rebuild_style_table()
        self._rebuild_series_bar()        # 上部の系列選択バーも同期
        self._update_analysis_targets()
        self._request_redraw()

    def _update_analysis_targets(self):
        names = [d for _, _, d in self._selected_series_items()]
        combos = [self.analysis_target]
        # 高度解析・データサイエンス・塗りつぶしの系列コンボも更新（構築済みなら）
        for attr in ("phase_target2", "math_a", "math_b", "ds_target", "fill_a"):
            if hasattr(self, attr):
                combos.append(getattr(self, attr))
        if hasattr(self, "proto_ch"):
            combos.extend(self.proto_ch)
        for cb in combos:
            cur = cb.currentText()
            cb.blockSignals(True)
            cb.clear()
            cb.addItems(names)
            idx = cb.findText(cur)
            if idx >= 0:
                cb.setCurrentIndex(idx)
            cb.blockSignals(False)
        # 塗りつぶしB は先頭に「0（X軸）」を入れる
        if hasattr(self, "fill_b"):
            cur = self.fill_b.currentText()
            self.fill_b.blockSignals(True)
            self.fill_b.clear()
            self.fill_b.addItem("0（X軸）")
            self.fill_b.addItems(names)
            idx = self.fill_b.findText(cur)
            if idx >= 0:
                self.fill_b.setCurrentIndex(idx)
            self.fill_b.blockSignals(False)

    @staticmethod
    def _style_key(fl, col):
        # スタイルを安定キー（ファイル, 列）で保持。表示名の変化に影響されない。
        return f"{fl}\t{col}"

    def _rebuild_style_table(self):
        # 差分更新: 先頭から一致する行は触らず、最初に異なる行以降だけ作り直す
        # （多系列で1系列だけ増減したとき、全行の再生成を避けて高速化）。
        items = self._selected_series_items()
        new_keys = [self._style_key(fl, col) for fl, col, _ in items]
        old_keys = [
            (self.style_table.item(r, 0).data(UserRole)
             if self.style_table.item(r, 0) else None)
            for r in range(self.style_table.rowCount())]
        if new_keys == old_keys:
            return                       # 変化なし: 何もしない
        i = 0
        m = min(len(new_keys), len(old_keys))
        while i < m and new_keys[i] == old_keys[i]:
            i += 1
        prev_suspend = self._suspend_redraw
        self._suspend_redraw = True      # 構築中の signal で再描画/上書きしない
        vbar = self.style_table.verticalScrollBar().value()
        self.style_table.setUpdatesEnabled(False)
        self.style_table.setRowCount(len(items))   # 末尾の増減を反映
        for r in range(i, len(items)):
            fl, col, disp = items[r]
            self._build_style_row(r, fl, col, disp)
        self.style_table.setUpdatesEnabled(True)
        self.style_table.verticalScrollBar().setValue(vbar)
        self._suspend_redraw = prev_suspend

    def _build_style_row(self, r, fl, col, disp):
        """スタイル表の1行（系列名/色/線種/幅/マーカー/軸/種別/誤差列）を作る。"""
        key = self._style_key(fl, col)
        st = self.series_styles.setdefault(key, dict(plotter.DEFAULT_STYLE))
        # 系列名（編集で凡例ラベルを上書き）。キーを UserRole に保持。
        name_item = QtWidgets.QTableWidgetItem(st.get("label") or disp)
        name_item.setData(UserRole, key)
        name_item.setFlags(name_item.flags() | QtCore.Qt.ItemFlag.ItemIsEditable)
        self.style_table.setItem(r, 0, name_item)
        # 色ボタン
        btn = QtWidgets.QPushButton(st.get("color") or "自動")
        if st.get("color"):
            btn.setStyleSheet(f"background:{st['color']};")
        btn.clicked.connect(lambda _=False, k=key, b=btn: self._pick_color(k, b))
        self.style_table.setCellWidget(r, 1, btn)
        # 線種
        cb = QtWidgets.QComboBox(); cb.addItems(list(plotter.LINESTYLES.keys()))
        cur_ls = next((k2 for k2, vv in plotter.LINESTYLES.items() if vv == st["linestyle"]), "実線")
        cb.setCurrentText(cur_ls)
        cb.currentTextChanged.connect(lambda v, k=key: self._set_style(k, "linestyle", plotter.LINESTYLES[v]))
        self.style_table.setCellWidget(r, 2, cb)
        # 幅
        sp = QtWidgets.QDoubleSpinBox(); sp.setRange(0.2, 10); sp.setSingleStep(0.5); sp.setValue(st["linewidth"])
        sp.valueChanged.connect(lambda v, k=key: self._set_style(k, "linewidth", v))
        self.style_table.setCellWidget(r, 3, sp)
        # マーカー
        mb = QtWidgets.QComboBox(); mb.addItems(list(plotter.MARKERS.keys()))
        cur_mk = next((k2 for k2, vv in plotter.MARKERS.items() if vv == st["marker"]), "なし")
        mb.setCurrentText(cur_mk)
        mb.currentTextChanged.connect(lambda v, k=key: self._set_style(k, "marker", plotter.MARKERS[v]))
        self.style_table.setCellWidget(r, 4, mb)
        # マーカーサイズ
        msp = QtWidgets.QDoubleSpinBox(); msp.setRange(1, 50); msp.setSingleStep(1); msp.setDecimals(1)
        msp.setValue(st.get("markersize", 4.0))
        msp.setToolTip("マーカーの大きさ（マーカーを「なし」以外にすると反映）")
        msp.valueChanged.connect(lambda v, k=key: self._set_style(k, "markersize", v))
        self.style_table.setCellWidget(r, 5, msp)
        # 軸（主/第2）── 折れ線/散布図で有効
        axb = QtWidgets.QComboBox(); axb.addItems(list(plotter.SERIES_AXES.keys()))
        axb.setCurrentText(next((k2 for k2, vv in plotter.SERIES_AXES.items()
                                 if vv == st.get("axis", "primary")), "主軸"))
        axb.currentTextChanged.connect(
            lambda v, k=key: self._set_style(k, "axis", plotter.SERIES_AXES[v]))
        self.style_table.setCellWidget(r, 6, axb)
        # 種別（複合グラフ：自動/線/棒/面/散布）
        kb = QtWidgets.QComboBox(); kb.addItems(list(plotter.SERIES_KINDS.keys()))
        kb.setCurrentText(next((k2 for k2, vv in plotter.SERIES_KINDS.items()
                                if vv == st.get("kind", "")), "自動"))
        kb.currentTextChanged.connect(
            lambda v, k=key: self._set_style(k, "kind", plotter.SERIES_KINDS[v]))
        self.style_table.setCellWidget(r, 7, kb)
        # 誤差列（エラーバー）── 同ファイルの列から選択。列一覧は開いた時に遅延展開
        cur_e = st.get("errcol")
        eb = LazyColumnCombo(
            (lambda fl=fl: list(self.datasets[fl].columns) if fl in self.datasets else []),
            cur_e if cur_e is not None else None)
        eb.currentTextChanged.connect(
            lambda v, k=key: self._set_style(k, "errcol", None if v == "なし" else v))
        self.style_table.setCellWidget(r, 8, eb)

    def _pick_color(self, skey, btn):
        col = QtWidgets.QColorDialog.getColor(parent=self)
        if col.isValid():
            hexc = col.name()
            self._set_style(skey, "color", hexc)
            btn.setText(hexc); btn.setStyleSheet(f"background:{hexc};")

    def _pick_bg_color(self):
        """プロット領域の背景色を選ぶ（オシロ表示の濃色固定も上書きできる）。"""
        col = QtWidgets.QColorDialog.getColor(parent=self)
        if col.isValid():
            self.bg_color = col.name()
            self.bg_btn.setText("背景色: " + self.bg_color)
            self.bg_btn.setStyleSheet(f"background:{self.bg_color};")
            self._request_redraw()

    def _reset_bg_color(self):
        """背景色を自動（通常=白・オシロ=濃色）に戻す。"""
        self.bg_color = ""
        self.bg_btn.setText("背景色: 自動")
        self.bg_btn.setStyleSheet("")
        self._request_redraw()

    def _pick_trend_color(self):
        """近似曲線の色を選ぶ（空=自動: 各系列と同じ色）。"""
        col = QtWidgets.QColorDialog.getColor(parent=self)
        if col.isValid():
            self.trend_color = col.name()
            self.trend_color_btn.setText("色: " + self.trend_color)
            self.trend_color_btn.setStyleSheet(f"background:{self.trend_color};")
            self._request_redraw()

    def _reset_trend_color(self):
        """近似曲線の色を自動（系列と同じ色）に戻す。"""
        self.trend_color = ""
        self.trend_color_btn.setText("色: 自動")
        self.trend_color_btn.setStyleSheet("")
        self._request_redraw()

    def _pick_fill_color(self):
        """系列間塗りつぶしの色を選ぶ（空=自動: 系列Aの色）。"""
        col = QtWidgets.QColorDialog.getColor(parent=self)
        if col.isValid():
            self.fill_color = col.name()
            self.fill_color_btn.setText("色: " + self.fill_color)
            self.fill_color_btn.setStyleSheet(f"background:{self.fill_color};")
            self._request_redraw()

    def _reset_fill_color(self):
        """塗りつぶしの色を自動（系列Aの色）に戻す。"""
        self.fill_color = ""
        self.fill_color_btn.setText("色: 自動")
        self.fill_color_btn.setStyleSheet("")
        self._request_redraw()

    # 純視覚スタイル（全再描画せず該当アーティストへ直接反映できるもの）
    _STYLE_VISUAL = frozenset({"color", "linewidth", "linestyle", "marker", "markersize"})

    def _set_style(self, skey, attr, value):
        self.series_styles.setdefault(skey, dict(plotter.DEFAULT_STYLE))[attr] = value
        # スタイルのみの変更は、可能なら全再描画せずアーティストを直接更新（高速・ちらつき無し）。
        # 少しでも不確実なら従来どおりデバウンス全再描画にフォールバックする。
        if not self._try_style_fastpath(skey, attr, value):
            self._request_redraw()

    def _build_style_artist_map(self, series, ctype, decimated):
        """skey -> Line2D。スタイルのみ変更を即時反映できる『単純な折れ線』だけを対象にする。
        散布図/誤差バー/棒・面/間引き/混在があれば空dictを返し、全再描画にフォールバックさせる。"""
        m = {}
        if ctype != "折れ線" or decimated:
            return m
        items = self._selected_series_items()
        if len(items) != len(series):
            return m
        for sr in series:                       # 1つでも非・単純線があれば諦める（安全側）
            if (sr.get("kind") or "") not in ("", "line") or sr.get("yerr") is not None:
                return m
        from matplotlib.lines import Line2D

        def _data_lines(axx):
            # データ系列の線だけを順序どおり抽出。近似曲線（'近似'）やピークマーカー等の
            # 自動ラベル線（'_child'…＝ラベル未指定）は除外する。
            return [ln for ln in axx.get_lines()
                    if isinstance(ln, Line2D)
                    and not str(ln.get_label()).startswith("_")
                    and "近似" not in str(ln.get_label())]
        ax = self.ax
        ax2 = getattr(ax, "_twin_secondary", None)
        prim = _data_lines(ax)
        sec = _data_lines(ax2) if ax2 is not None else []
        prim_items = [it for it, sr in zip(items, series) if sr.get("axis") != "secondary"]
        sec_items = [it for it, sr in zip(items, series) if sr.get("axis") == "secondary"]
        if len(prim_items) != len(prim) or len(sec_items) != len(sec):
            return m                            # 本数が一致しない＝対応が取れない → 諦める
        for (fl, col, _disp), ln in zip(prim_items, prim):
            m[self._style_key(fl, col)] = ln
        for (fl, col, _disp), ln in zip(sec_items, sec):
            m[self._style_key(fl, col)] = ln
        return m

    def _try_style_fastpath(self, skey, attr, value):
        """純視覚スタイルの変更を全再描画せず該当Line2Dへ反映できればして True。
        少しでも不確実なら False を返し、呼び出し側が通常の全再描画を行う。"""
        if attr not in self._STYLE_VISUAL:
            return False
        if self._suspend_redraw or not self._has_drawn:
            return False
        if not getattr(self, "live_check", None) or not self.live_check.isChecked():
            return False
        if self._redraw_timer.isActive():
            return False                        # 全再描画が予約済み → そちらに任せる
        if self.chart_combo.currentText() != "折れ線":
            return False
        if attr == "color" and not value:
            return False                        # 色を自動へ戻す等は全再描画に任せる
        ln = self._style_artists.get(skey)
        if ln is None or ln.axes is None:       # 対応Line2Dが無い/外れている → 全再描画
            return False
        try:
            if attr == "color":
                ln.set_color(value)
            elif attr == "linewidth":
                ln.set_linewidth(float(value))
            elif attr == "linestyle":
                ln.set_linestyle(value)
            elif attr == "marker":
                ln.set_marker(value or "")
            elif attr == "markersize":
                ln.set_markersize(float(value))
        except Exception:                       # noqa: BLE001  予期せぬ値 → 全再描画
            return False
        if attr == "color":
            if self.legend_check.isChecked():
                self._rebuild_legend_inplace()  # 凡例スウォッチの色を更新
            self._rebuild_series_bar(self.chart_combo.currentText())  # 上部バーの色も更新
        self.canvas.draw_idle()
        return True

    def _rebuild_legend_inplace(self):
        """色変更後、凡例を plot_series と同じ loc/フォントで作り直してスウォッチを更新。"""
        ax = self.ax
        handles, labels = ax.get_legend_handles_labels()
        ax2 = getattr(ax, "_twin_secondary", None)
        if ax2 is not None:
            h2, l2 = ax2.get_legend_handles_labels()
            handles = handles + h2; labels = labels + l2
        if handles:
            f = self._fonts()
            ax.legend(handles, labels, loc=self.legend_loc.currentText(),
                      fontsize=(f.get("legend") or f.get("tick", 9)))
