# -*- coding: utf-8 -*-
"""DataSciMixin: 「データサイエンス」タブの解析アクション。

選択中のY系列に対し、線形回帰（線形性）・記述統計・相関・正規性検定などを計算して表で表示する。
実体の計算は datasci モジュール（GUI 非依存）に置き、ここは取得→計算→表示の橋渡しに徹する。
"""
from graph_app_common import *  # noqa: F401,F403


class DataSciMixin:
    # ---- 共通: 解析対象 (t, y) の取得 ----
    def _ds_xy(self):
        """データサイエンスタブの対象コンボから (x, y) を取得。x は現在のX軸列。"""
        disp = self.ds_target.currentText()
        if not disp:
            self.notify("データタブでY系列を選択してください。", "warn")
            return None, None, None
        t, y = self._xy_by_disp(disp)   # AdvancedMixin と共用（同一クラスのメソッド）
        if t is None:
            self.notify("対象の数値データが取得できません。", "warn")
            return None, None, None
        return disp, t, y

    def _ds_show(self, title, rows):
        """[(項目, 値文字列), ...] を結果テーブルに表示する。各行に「表示」チェックを付ける。"""
        had = bool(getattr(self, "_ds_annotations", None))
        self._ds_annotations = []   # 新しい解析を表示したら前回の注記はリセット
        self.ds_title.setText(title)
        self.ds_table.setRowCount(len(rows))
        for r, (k, v) in enumerate(rows):
            self.ds_table.setItem(r, 0, QtWidgets.QTableWidgetItem(str(k)))
            self.ds_table.setItem(r, 1, QtWidgets.QTableWidgetItem(str(v)))
            cb = QtWidgets.QCheckBox()
            cb.setToolTip("チェックすると、この項目の値をグラフ上に注記表示します。")
            cb.toggled.connect(self._refresh_ds_annotations)
            self.ds_table.setCellWidget(r, 2, cb)
        if had and getattr(self, "_has_drawn", False):
            self.draw_graph()   # 前回の注記を消す

    def _refresh_ds_annotations(self, *_):
        """「表示」にチェックされた行を集めてグラフへ注記表示する。"""
        anns = []
        for r in range(self.ds_table.rowCount()):
            cb = self.ds_table.cellWidget(r, 2)
            if cb is not None and cb.isChecked():
                k = self.ds_table.item(r, 0)
                v = self.ds_table.item(r, 1)
                if k is not None and v is not None:
                    anns.append(f"{k.text()} = {v.text()}")
        self._ds_annotations = anns
        if self.datasets:   # 特殊表示直後でも通常グラフへ再描画して反映
            self.draw_graph()

    @staticmethod
    def _fmt(v):
        if v is None:
            return "—"
        if isinstance(v, bool):
            return "はい" if v else "いいえ"
        if isinstance(v, int):
            return str(v)
        try:
            return f"{float(v):.6g}"
        except (TypeError, ValueError):
            return str(v)

    # ---- 線形回帰（線形性） ----
    def run_regression(self):
        disp, t, y = self._ds_xy()
        if t is None:
            return
        d = datasci.linear_regression(t, y)
        if not d:
            self.notify("回帰に十分なデータがありません。", "warn")
            return
        f = self._fmt
        rows = [
            ("点数 n", f(d["n"])),
            ("傾き slope", f(d["slope"])),
            ("切片 intercept", f(d["intercept"])),
            ("相関 r (ピアソン)", f(d["r"])),
            ("決定係数 R²", f(d["r2"])),
            ("p値 (傾き=0)", f(d["p_value"])),
            ("傾きの標準誤差", f(d["std_err"])),
            ("RMSE (残差)", f(d["rmse"])),
            ("直線性誤差 [%FS]", f(d["linearity_error_pct"])),
        ]
        sp = datasci.correlation(t, y, "spearman")
        if sp:
            rows.append(("相関 (スピアマン)", f(sp["r"])))
        self._ds_show(f"線形回帰: {disp}（Y vs X）", rows)
        if self.ds_fit_check.isChecked():
            # 既存の近似曲線(線形)機能でグラフに直線を重ねる
            self.trend_combo.setCurrentText("線形")
            self.draw_graph()

    # ---- 記述統計 ----
    def show_describe(self):
        disp, t, y = self._ds_xy()
        if t is None:
            return
        d = datasci.describe(y)
        if not d:
            self.notify("数値データがありません。", "warn")
            return
        f = self._fmt
        order = [
            ("件数", "count"), ("平均", "mean"), ("中央値", "median"),
            ("標準偏差 σ", "std"), ("分散", "var"), ("最小", "min"), ("最大", "max"),
            ("範囲", "range"), ("変動係数 CV", "cv"), ("歪度 skew", "skew"),
            ("尖度 kurtosis", "kurtosis"), ("第1四分位 Q1", "p25"),
            ("中央 Q2", "p50"), ("第3四分位 Q3", "p75"), ("四分位範囲 IQR", "iqr"),
        ]
        self._ds_show(f"記述統計: {disp}", [(lbl, f(d.get(k))) for lbl, k in order])

    # ---- 正規性検定 ----
    def run_normality(self):
        disp, t, y = self._ds_xy()
        if t is None:
            return
        d = datasci.normality(y)
        if not d:
            self.notify("正規性検定には scipy が必要です（または点数不足）。", "warn")
            return
        f = self._fmt
        rows = [
            ("W統計量", f(d["W"])),
            ("p値", f(d["p_value"])),
            ("5%有意で正規とみなせる", f(d["normal_5pct"])),
        ]
        self._ds_show(f"正規性検定 (Shapiro-Wilk): {disp}", rows)

    # ---- 相関行列（選択中の全系列） ----
    def show_corr_matrix(self):
        items = self._selected_series_items()
        if len(items) < 2:
            self.notify("相関行列には2系列以上をデータタブで選択してください。", "warn")
            return
        named = []
        for fl, col, disp in items:
            t, y = self._xy_by_disp(disp)
            if y is not None:
                named.append((disp, y))
        names, mat = datasci.correlation_matrix(named, "pearson")
        if mat is None:
            self.notify("相関行列を計算できませんでした。", "warn")
            return
        self._show_corr_window(names, mat)

    def _show_corr_window(self, names, mat):
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("相関行列（ピアソン）")
        dlg.resize(min(120 + 90 * len(names), 900), min(120 + 30 * len(names), 700))
        lay = QtWidgets.QVBoxLayout(dlg)
        n = len(names)
        tbl = QtWidgets.QTableWidget(n, n)
        tbl.setHorizontalHeaderLabels(names)
        tbl.setVerticalHeaderLabels(names)
        for i in range(n):
            for j in range(n):
                v = float(mat[i, j])
                it = QtWidgets.QTableWidgetItem(f"{v:.3f}")
                it.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
                # 相関の強さで色付け（赤=正・青=負）
                a = max(0.0, min(1.0, abs(v)))
                if v >= 0:
                    it.setBackground(QtGui.QColor(255, int(255 * (1 - a)), int(255 * (1 - a))))
                else:
                    it.setBackground(QtGui.QColor(int(255 * (1 - a)), int(255 * (1 - a)), 255))
                tbl.setItem(i, j, it)
        lay.addWidget(tbl)
        btn = QtWidgets.QPushButton("閉じる")
        btn.clicked.connect(dlg.accept)
        lay.addWidget(btn)
        dlg.exec()

    # ---- 任意関数フィッティング ----
    def run_custom_fit(self):
        """モデル式とパラメータ初期値を指定して非線形フィット（scipy curve_fit）。"""
        disp, t, y = self._ds_xy()
        if t is None:
            return
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle(f"任意関数フィット: {disp}")
        form = QtWidgets.QFormLayout(dlg)
        last = getattr(self, "_fit_last", {})
        e_expr = QtWidgets.QLineEdit(last.get("expr", "a*exp(-x/b)+c"))
        e_expr.setToolTip("変数 x とパラメータ名で書くモデル式。\n"
                          "使える関数: sin/cos/tan/exp/log/log10/sqrt/abs など"
                          "（数学チャンネルの数式と同じ）。")
        e_par = QtWidgets.QLineEdit(last.get("params", "a, b, c"))
        e_par.setToolTip("フィットするパラメータ名（カンマ区切り）")
        e_p0 = QtWidgets.QLineEdit(last.get("p0", "1, 1, 0"))
        e_p0.setToolTip("各パラメータの初期値（カンマ区切り・パラメータ名と同順）")
        c_add = QtWidgets.QCheckBox("フィット曲線を新しいデータとして追加（グラフに重ねられる）")
        c_add.setChecked(True)
        form.addRow("モデル式 f(x) =", e_expr)
        form.addRow("パラメータ", e_par)
        form.addRow("初期値", e_p0)
        form.addRow(c_add)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok
                                        | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept); bb.rejected.connect(dlg.reject)
        form.addRow(bb)
        if not dlg.exec():
            return
        expr = e_expr.text().strip()
        params = [p.strip() for p in e_par.text().split(",") if p.strip()]
        try:
            p0 = [float(v) for v in e_p0.text().split(",")]
        except ValueError:
            self.notify("初期値は数値をカンマ区切りで入力してください。", "warn")
            return
        if not expr or not params or len(p0) != len(params):
            self.notify("式・パラメータ名・初期値（同数）を入力してください。", "warn")
            return
        self._fit_last = {"expr": expr, "params": e_par.text(), "p0": e_p0.text()}
        try:
            d = datasci.fit_custom(t, y, expr, params, p0)
        except Exception as e:  # noqa: BLE001  収束失敗・式エラーなど
            self.notify(f"フィットできませんでした:\n{e}\n\n"
                        "初期値を変える・式を見直すと収束することがあります。", "warn")
            return
        if not d:
            self.notify("フィットに十分なデータがありません（要scipy・点数>パラメータ数+1）。", "warn")
            return
        f = self._fmt
        rows = [("モデル式", f"f(x) = {expr}"), ("点数 n", f(d["n"]))]
        for nm, v, err in d["params"]:
            rows.append((f"{nm}", f"{v:.6g} ± {err:.3g}"))
        rows += [("決定係数 R²", f(d["r2"])), ("RMSE (残差)", f(d["rmse"]))]
        self._ds_show(f"任意関数フィット: {disp}", rows)
        if c_add.isChecked():
            import pandas as pd
            xname = self.x_combo.currentText() or "x"
            df = pd.DataFrame({xname: d["x"], f"fit({disp})": d["yfit"]})
            base = f"FIT: {disp}"
            label, i = base, 2
            while label in self.datasets:
                label = f"{base} ({i})"; i += 1
            self.datasets[label] = df
            self.meta[label] = {"path": label, "enc": "-", "delim": "-"}
            self._add_file_item(label)
            self._refresh_columns()
            self._set_status(f"フィット完了: R²={f(d['r2'])}。曲線を『{label}』として追加しました"
                             "（ツリーでチェックすると重ね描きできます）。")
        else:
            self._set_status(f"フィット完了: R²={f(d['r2'])}")

    # ---- t検定・分散分析 ----
    def run_t_test(self):
        """t検定（1標本 / 対応なしWelch / 対応あり）。対象Aはこのタブの対象コンボ。"""
        disp, t, y = self._ds_xy()
        if t is None:
            return
        others = [d for _fl, _c, d in self._selected_series_items() if d != disp]
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle(f"t検定: {disp}")
        form = QtWidgets.QFormLayout(dlg)
        kind = QtWidgets.QComboBox()
        kind.addItems(["1標本（母平均μ0と比較）", "対応なし2標本（Welch）", "対応あり2標本"])
        e_mu = QtWidgets.QLineEdit("0")
        cb_b = QtWidgets.QComboBox(); cb_b.addItems(others)
        form.addRow("種類", kind)
        form.addRow("μ0（1標本のとき）", e_mu)
        form.addRow("対象B（2標本のとき）", cb_b)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok
                                        | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept); bb.rejected.connect(dlg.reject)
        form.addRow(bb)
        if not dlg.exec():
            return
        ki = kind.currentIndex()
        b = None
        if ki > 0:
            if not cb_b.currentText():
                self.notify("2標本の検定には対象Bの系列もデータタブで選択してください。", "warn")
                return
            _tb, b = self._xy_by_disp(cb_b.currentText())
        d = datasci.t_test(y, b=b, mu=_parse_float(e_mu.text(), 0.0) or 0.0,
                           paired=(ki == 2))
        if not d:
            self.notify("t検定を計算できませんでした（要scipy・点数を確認）。", "warn")
            return
        f = self._fmt
        name = ["1標本", "対応なし(Welch)", "対応あり"][ki]
        rows = [("種類", name), ("平均 A", f(d["mean_a"]))]
        if d["mean_b"] is not None:
            rows.append(("平均 B", f(d["mean_b"])))
        rows += [("t統計量", f(d["t"])), ("p値", f(d["p_value"]))]
        if d["df"] is not None:
            rows.append(("自由度", f(d["df"])))
        rows.append(("5%有意差あり", f(d["sig_5pct"])))
        self._ds_show(f"t検定（{name}）: {disp}"
                      + (f" vs {cb_b.currentText()}" if ki > 0 else ""), rows)

    def run_anova(self):
        """一元配置分散分析。選択中の全Y系列を群として比較する。"""
        items = self._selected_series_items()
        if len(items) < 2:
            self.notify("分散分析には2系列以上をデータタブで選択してください。", "warn")
            return
        groups = []
        for _fl, _c, disp in items:
            _t, y = self._xy_by_disp(disp)
            if y is not None:
                groups.append((disp, y))
        d = datasci.anova_oneway(groups)
        if not d:
            self.notify("分散分析を計算できませんでした（要scipy）。", "warn")
            return
        f = self._fmt
        rows = [("F統計量", f(d["F"])), ("p値", f(d["p_value"])),
                ("5%有意差あり", f(d["sig_5pct"]))]
        for name, n, mean, std in d["groups"]:
            rows.append((f"{name}", f"n={n}, 平均={mean:.6g}, σ={std:.6g}"))
        self._ds_show(f"一元配置ANOVA（{len(d['groups'])}群）", rows)

    # ---- 主成分分析（PCA） ----
    def run_pca(self):
        """選択中の系列（特徴量）に PCA をかけ、PC1..PCk を新データセットとして作る。
        作成後は『データ』タブで選び、3D表示（散布図/折れ線）で確認できる。"""
        items = self._selected_series_items()
        if len(items) < 2:
            self.notify("主成分分析には特徴量として2系列以上をデータタブで選択してください。\n"
                        "（例: 複数のセンサ列や測定列。PC1〜3 を作れば3D散布図で確認できます）", "warn")
            return
        named = []
        for fl, col, disp in items:
            _t, y = self._xy_by_disp(disp)
            if y is not None:
                named.append((disp, y))
        if len(named) < 2:
            self.notify("有効な数値系列が不足しています。", "warn")
            return
        res = datasci.pca(named, n_components=self.pca_ncomp.value(),
                          standardize=self.pca_std.isChecked())
        if not res:
            self.notify("主成分分析を計算できませんでした（系列数・点数・数値を確認してください）。", "warn")
            return
        import pandas as pd
        df = pd.DataFrame({name: arr for name, arr in res["scores"]})
        src = items[0][0]
        base = f"PCA: {os.path.splitext(os.path.basename(str(src)))[0]}"
        label, i = base, 2
        while label in self.datasets:
            label = f"{base} ({i})"; i += 1
        self.datasets[label] = df
        self.meta[label] = {"path": label, "enc": "-", "delim": "-"}
        self._add_file_item(label)
        self._refresh_columns()

        f = self._fmt
        rows = [("使用した特徴量", ", ".join(res["features"])),
                ("サンプル数", res["n_samples"]),
                ("標準化", self.pca_std.isChecked()),
                ("計算エンジン", res["backend"])]
        for j, r in enumerate(res["explained_ratio"]):
            rows.append((f"PC{j + 1} 寄与率", f"{r * 100:.1f}%"))
        rows.append(("累積寄与率", f"{sum(res['explained_ratio']) * 100:.1f}%"))
        self._ds_show(f"主成分分析 (PCA) → 『{label}』を作成", rows)
        self._set_status(
            f"主成分分析を作成: {label}（PC1〜{res['n_components']}, {res['backend']}）。"
            "『データ』タブで選び、3D表示で確認できます。")
