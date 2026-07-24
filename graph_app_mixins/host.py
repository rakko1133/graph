# -*- coding: utf-8 -*-
"""HostMixin: タブが共通で使う「土台サービス」。

解析対象の系列取り出し（series_xy / analysis_xy_or_warn / _analysis_xy /
_xy_by_disp / _apply_measure_window）と、特殊表示の軸準備（prepare_view_axes）を
ここに集約する。以前は scope タブ（analysis_peaks）と advanced タブ
（advanced_tools）にあり、他タブが直接呼んでいた＝タブ同士が依存していた。
ここへ剥がすことで各タブは HostMixin だけに依存し、タブ同士は独立になる
（1タブのファイルを消しても他タブは壊れない）。挙動は完全に不変。
"""
from graph_app_common import *  # noqa: F401,F403


class HostMixin:
    def _tab_hook(self, name, *args, default=None):
        """タブが提供するフック（描画注記・ピークマーカー等）を呼ぶ。

        コア（plotting など）が「そのタブが在れば注記を足す」関係を、タブ名を
        直接書かずに表す逃がし口。該当メソッドが無ければ何もせず default を返すので、
        タブを1枚外しても描画は落ちない。"""
        fn = getattr(self, name, None)
        return fn(*args) if callable(fn) else default

    def series_xy(self, fl, col, gated=False):
        """指定系列(fl,col)の (t, y) を数値配列で返す。

        時間軸は数値化し、非数値のX（文字列カテゴリ等）ならインデックスを
        時間軸とみなす。gated=True なら「表示範囲のみ測定」の設定に従って
        画面のX範囲に絞る。

        以前は同じ取り出し処理が _xy_for と _xy_by_disp に写経されており、
        片方だけ直すと解析タブと高度解析タブで別の値が出る状態だった。
        """
        import numpy as np
        import pandas as pd
        df = self.datasets[fl]
        xname = self.x_combo.currentText()
        raw = df[xname].to_numpy() if xname in df.columns else df.iloc[:, 0].to_numpy()
        t = pd.to_numeric(pd.Series(raw), errors="coerce").to_numpy(dtype=float)
        if np.isnan(t).mean() > 0.5:  # 非数値Xはインデックスを時間軸とみなす
            t = np.arange(len(t), dtype=float)
        y = pd.to_numeric(pd.Series(df[col].to_numpy()), errors="coerce").to_numpy(dtype=float)
        if gated:
            t, y = self._apply_measure_window(t, y)
        return t, y

    def _xy_for(self, fl, col):
        """指定系列(fl,col)の (t, y)。「表示範囲のみ測定」ONなら画面範囲に絞る。"""
        return self.series_xy(fl, col, gated=True)

    def analysis_xy_or_warn(self, msg="解析対象の系列を選択してください。"):
        """解析対象の (t, y, label)。未選択なら通知して None を返す。

        「取得→未選択なら警告して return」の4行が解析系の入口11箇所に
        写経されていたのをまとめたもの。呼び出し側は
        `got = self.analysis_xy_or_warn()` / `if got is None: return` で使う。"""
        t, y, label = self._analysis_xy()
        if t is None:
            self.notify(msg, "warn")
            return None
        return t, y, label

    def prepare_view_axes(self, three_d=False, white_bg=True):
        """特殊表示（スペクトログラム／アイ／トレンド等）のために軸を作り直す。

        3D表示中でも指定の投影に戻し、補助軸（カラーバー等）を片付けてから
        まっさらにする。white_bg=True なら地色を白・目盛りを黒にする
        （オシロの濃色設定が残ったままだと解析ビューが読めないため）。"""
        self._ensure_axes_projection(three_d)
        self._reset_figure_axes()
        self.ax.clear()
        if white_bg:
            self.ax.set_facecolor("white")
            self.ax.tick_params(colors="black")
        return self.ax

    def _apply_measure_window(self, t, y):
        """「表示範囲のみ測定」がONなら、画面のX範囲だけに絞り込む。"""
        import numpy as np   # noqa: F401  （呼び出し側と同じ遅延importの流儀）
        if self.window_meas_check.isChecked() and self._has_drawn:
            x0, x1 = self.ax.get_xlim()
            if x1 < x0:
                x0, x1 = x1, x0
            # 画面のX範囲は「単位変換後」の座標。生の t を同じ変換にかけてから絞る
            # （倍率/式を使うと生 t と表示座標がズレるため）。値は生のまま解析する。
            t_disp = mathchan.axis_scale(t, self.xscale_edit.text())
            mask = (t_disp >= x0) & (t_disp <= x1)
            if int(mask.sum()) >= 3:
                t, y = t[mask], y[mask]
        return t, y

    def _analysis_xy(self):
        """解析対象（解析対象コンボで選んだ1系列）の (t, y, label) を返す。"""
        disp = self.analysis_target.currentText()
        for fl, col, d in self._selected_series_items():
            if d == disp:
                t, y = self._xy_for(fl, col)
                return t, y, d
        return None, None, None

    def _xy_by_disp(self, disp):
        """選択中系列の表示名から (t, y) を取得（時間軸は数値化）。

        取り出しは series_xy と共通。ここは区間で絞らない（生成データや
        相関の対象を切り詰めないため）。"""
        for fl, col, d in self._selected_series_items():
            if d == disp:
                return self.series_xy(fl, col, gated=False)
        return None, None
