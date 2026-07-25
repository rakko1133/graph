"""CSV / TSV / 波形データ グラフ・解析ツール（PySide6 / Qt）。

使い方:
    python graph_app.py

機能:
    - 複数の CSV/TSV/波形ファイルをまとめて読み込み、系列を重ねて描画
    - 文字コード・区切りの自動判定（手動指定も可）
    - 8種のグラフ＋系列ごとの色/線種/線幅/マーカー、軸範囲/対数軸/凡例位置
    - Excel相当のグラフ編集：近似曲線（線形/多項式/指数/対数/移動平均＋R²）、
      データラベル、第2軸・複合グラフ（系列ごと主/第2軸＋線/棒/面の混在）、エラーバー
    - オシロスコープ表示（time/div・V/div・位置・divグリッド）
    - オシロ相当の解析（第1/第2…ピーク検出、各種測定、FFT）
    - 設定の保存／読み込み（終了時自動保存・起動時復元）

GUI は matplotlib の qt_compat 経由で実装しており、PySide6 / PyQt6（Qt6系）で動作する。
"""

from graph_app_common import *  # noqa: F401,F403
from graph_app_common import _DelegatingTab  # 内蔵タブ登録用（* では入らない）
# タブは1タブ=1ファイル（graph_app_mixins/）。メインがこれらを import して有効化する。
# 新しいタブを足すときは、graph_app_mixins/ にファイルを1つ作り、ここに1行足す。
from graph_tab_data import DataIOMixin        # 1. データ タブ
from graph_tab_scope import ScopeTabMixin     # 2. オシロ/解析 タブ
from graph_tab_advanced import AdvancedMixin  # 3. 高度解析 タブ
from graph_tab_datasci import DataSciMixin    # 4. 統計解析 タブ
import graph_tab_threshold                     # 5. しきい値（採用した差し込みタブ／register_tab で登録）

# ============================================================
# GUIフレームワーク（旧 graph_app_mixins の host/ui_build/plotting/
# style_table/batch/persistence を統合）。タブは別ファイル。
# ============================================================
class HostMixin:
    def _tab_hook(self, name, *args, default=None):
        """タブが提供するフック（描画注記・ピークマーカー等）を呼ぶ。

        コア（plotting など）が「そのタブが在れば注記を足す」関係を、タブ名を
        直接書かずに表す逃がし口。該当メソッドが無ければ何もせず default を返すので、
        タブを1枚外しても描画は落ちない。"""
        fn = getattr(self, name, None)
        return fn(*args) if callable(fn) else default

    # ---- 差し込みタブ用の拡張口（コアを触らず、タブ側だけで拡張できる）----
    def _draw_plugin_overlays(self):
        """登録タブが定義した draw_overlay(app, ax) をメイングラフへ描く。

        プラグインタブ（graph_tab_*.py）が draw_overlay を持てば、描画のたびに
        ここから呼ばれ、メイン軸へ注記・目印などを重ねられる。draw_graph を
        1行も触らずに『グラフ上へ描く』機能を足せる差し込み口。1枚が失敗しても
        他タブや本体描画は落とさない。"""
        for plugin in registered_tabs():
            fn = getattr(plugin, "draw_overlay", None)
            if callable(fn):
                try:
                    fn(self, self.ax)
                except Exception:
                    applog.get_logger().debug(
                        "draw_overlay 失敗: %s", getattr(plugin, "key", "?"), exc_info=True)

    def _collect_plugin_config(self):
        """各登録タブの collect_config(app) を集めて {key: 設定dict} で返す。"""
        out = {}
        for plugin in registered_tabs():
            fn = getattr(plugin, "collect_config", None)
            if callable(fn):
                try:
                    out[plugin.key] = fn(self)
                except Exception:
                    applog.get_logger().debug(
                        "collect_config 失敗: %s", getattr(plugin, "key", "?"), exc_info=True)
        return out

    def _apply_plugin_config(self, saved):
        """保存済みの {key: 設定dict} を各登録タブの apply_config(app, cfg) へ配る。"""
        if not isinstance(saved, dict):
            return
        for plugin in registered_tabs():
            fn = getattr(plugin, "apply_config", None)
            if callable(fn):
                try:
                    fn(self, saved.get(plugin.key, {}))
                except Exception:
                    applog.get_logger().debug(
                        "apply_config 失敗: %s", getattr(plugin, "key", "?"), exc_info=True)

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

class UIBuildMixin:
    # ------------------------------------------------------------ UI 構築
    def _menu_action(self, menu, label, slot, shortcut=None, tip=None):
        act = QtGui.QAction(label, self)
        if shortcut:
            act.setShortcut(shortcut)
        if tip:
            act.setStatusTip(tip)
        act.triggered.connect(slot)
        menu.addAction(act)
        self._palette_register(menu.title(), label, act)
        return act

    def _palette_register(self, category, label, act):
        """コマンドパレットの候補として登録する。

        メニューを動的に走査すると PySide6 の QAction.menu() が返す一時ラッパーの
        破棄で C++ 側の QMenu ごと削除される（所有権の罠）ため、構築時に登録した
        アクションだけを候補にする。

        QAction 以外（メソッドなど）を混ぜると show_command_palette の
        `a.isEnabled()` が AttributeError になり、**パレット全体が開かなくなる**。
        1件の登録ミスで52コマンドが道連れになるので、ここで弾いて記録する。"""
        if not hasattr(self, "_all_actions"):
            self._all_actions = []
        if not isinstance(act, QtGui.QAction):
            applog.get_logger().warning(
                "コマンドパレットに QAction 以外を登録しようとした: %s / %s (%s)",
                category, label, type(act).__name__)
            return
        cat = str(category).replace("&", "").replace("...", "").strip()
        self._all_actions.append((f"{cat} › {label.replace('&', '')}", act))

    def _build_menu(self):
        m = self.menuBar()
        # ファイル
        fm = m.addMenu("ファイル(&F)")
        self._menu_action(fm, "ファイル追加...", self.add_file, "Ctrl+O")
        self._menu_action(fm, "フォルダを開く...", self.add_folder, "Ctrl+Shift+O",
                          tip="フォルダ内の対応データファイルを一括読み込み。"
                              "複数フォルダを開くとツリーがフォルダごとにグループ化されます")
        self._menu_action(fm, "クリップボードから貼り付け", self.paste_from_clipboard, "Ctrl+Shift+V",
                          tip="Excel等からコピーした表を新規データとして読み込む")
        self.recent_menu = fm.addMenu("最近使ったファイル")
        self._rebuild_recent_menu()
        fm.addSeparator()
        self._watch_action = QtGui.QAction("ファイルの変更を監視して自動再読込", self)
        self._watch_action.setCheckable(True)
        self._watch_action.setStatusTip("読み込み済みファイルが外部で更新されたら自動で読み直して再描画します"
                                        "（測定器・ロガーのライブ監視向け）")
        self._watch_action.toggled.connect(self.toggle_file_watch)
        fm.addAction(self._watch_action)
        self._palette_register("ファイル", "ファイルの変更を監視して自動再読込", self._watch_action)
        fm.addSeparator()
        self._menu_action(fm, "グラフ画像を保存...", self.save_figure, "Ctrl+S")
        self._menu_action(fm, "ファイルごとに一括画像出力...", self.batch_export, "Ctrl+B")
        self._menu_action(fm, "Excelレポート出力...", self.export_excel_report, None,
                          tip="現在のグラフ（ネイティブExcelグラフ）とデータ・解析結果の表を1つのExcelブックに出力")
        self._menu_action(fm, "クリップボードにコピー", self.copy_figure, "Ctrl+Shift+C")
        fm.addSeparator()
        self._menu_action(fm, "設定を保存...", self.save_config_dialog, "Ctrl+Shift+S")
        self._menu_action(fm, "設定を読み込み...", self.load_config_dialog, None)
        fm.addSeparator()
        self._menu_action(fm, "終了", self.close, "Ctrl+Q")
        # 編集
        em = m.addMenu("編集(&E)")
        self._menu_action(em, "元に戻す", self.undo, "Ctrl+Z", tip="書式・設定の変更を1つ戻す")
        self._menu_action(em, "やり直す", self.redo, "Ctrl+Y", tip="戻した変更をやり直す")
        # 表示
        vm = m.addMenu("表示(&V)")
        self.view_menu = vm   # パネルの表示/非表示トグルを _build_central で追加する
        # 表示レベル（画面に出す量）。隠れた項目は Ctrl+F / Ctrl+Shift+P から呼べる
        level_menu = vm.addMenu("表示レベル")
        self._level_actions = {}
        level_group = QtGui.QActionGroup(self)
        level_group.setExclusive(True)
        _LEVEL_TIPS = {
            "基本": "読み込み→列選択→描画に必要な物だけを出す（隠れた設定も Ctrl+F で呼べます）",
            "標準": "基本＋オシロ/解析と主な書式",
            "全部": "すべてのパネル・設定を表示（従来と同じ）",
        }
        for lv in self.UI_LEVELS:
            act = QtGui.QAction(lv, self)
            act.setCheckable(True)
            act.setStatusTip(_LEVEL_TIPS[lv])
            act.triggered.connect(lambda _c=False, x=lv: self.set_ui_level(x))
            level_group.addAction(act)
            level_menu.addAction(act)
            self._level_actions[lv] = act
            self._palette_register("表示レベル", lv, act)
        vm.addSeparator()
        self._menu_action(vm, "コマンドパレット...", self.show_command_palette, "Ctrl+Shift+P",
                          tip="すべてのメニュー操作を名前で検索して実行")
        self._menu_action(vm, "設定を検索...", self._focus_setting_search, "Ctrl+F",
                          tip="設定名でパネルを横断検索し、その項目まで画面を移動します"
                              "（設定はデータ・書式・描画バー・ツールバーに分かれているため）")
        vm.addSeparator()
        self._menu_action(vm, "グラフを描画", self.draw_graph, "F5")
        self._menu_action(vm, "新しいグラフウィンドウ（現在のグラフを複製）",
                          self.open_graph_window, "Ctrl+G",
                          tip="現在のグラフを独立ウィンドウに複製。選択・書式を変えて何枚も並べて比較できます")
        self._menu_action(vm, "全データに合わせる（オートスケール）", self.auto_scale_scope, None)
        # 解析
        am = m.addMenu("解析(&A)")
        self._menu_action(am, "解析実行（ピーク・測定）", self.run_analysis, "Ctrl+R",
                          tip="選択中の解析対象系列のピーク・測定値を計算")
        self._menu_action(am, "FFTスペクトル表示", self.show_fft, None)

    def show_command_palette(self):
        """コマンドパレット（Ctrl+Shift+P）: 登録済みの全メニュー操作を名前で検索して実行する。
        （最近使ったファイルなど動的に増減する項目は対象外）"""
        acts = list(getattr(self, "_all_actions", []))

        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("コマンドパレット")
        dlg.resize(560, 420)
        v = QtWidgets.QVBoxLayout(dlg)
        edit = QtWidgets.QLineEdit()
        edit.setPlaceholderText("コマンド名で検索（例: FFT ／ 保存 ／ 切り離し）")
        lst = QtWidgets.QListWidget()
        v.addWidget(edit)
        v.addWidget(lst, 1)

        def refill(text=""):
            tl = text.strip().lower()
            lst.clear()
            for name, a in acts:
                if tl and tl not in name.lower():
                    continue
                try:
                    if not a.isEnabled():
                        continue
                    sc = a.shortcut().toString()
                except RuntimeError:
                    continue   # 破棄済みアクションはスキップ
                it = QtWidgets.QListWidgetItem(name + (f"　（{sc}）" if sc else ""))
                it.setData(UserRole, a)
                lst.addItem(it)
            if lst.count():
                lst.setCurrentRow(0)

        def run_current():
            it = lst.currentItem()
            if it is not None:
                act = it.data(UserRole)
                dlg.accept()
                try:
                    act.trigger()
                except RuntimeError:
                    self._set_status("この操作は現在実行できません。")

        edit.textChanged.connect(refill)
        edit.returnPressed.connect(run_current)
        lst.itemActivated.connect(lambda *_: run_current())

        class _Nav(QtCore.QObject):
            """検索ボックスにフォーカスしたまま ↑↓ で候補を選べるようにする。"""
            def eventFilter(self, _obj, ev):
                if (ev.type() == QtCore.QEvent.Type.KeyPress
                        and ev.key() in (QtCore.Qt.Key.Key_Down, QtCore.Qt.Key.Key_Up)):
                    step = 1 if ev.key() == QtCore.Qt.Key.Key_Down else -1
                    lst.setCurrentRow(max(0, min(lst.count() - 1, lst.currentRow() + step)))
                    return True
                return False

        nav = _Nav(dlg)
        edit.installEventFilter(nav)
        refill()
        edit.setFocus()
        self._palette_dlg = dlg   # テスト・再入から参照できるように保持
        dlg.exec()

    # ---- UIスタイル（外観テーマ）----
    # ウィジェット構成は一切変えず、QSS＋ツールバー設定で密度・大きさ・配色だけを
    # 変える。機能は全スタイルで同一（見た目の再現のみ）。
    #
    # 色は `$bg` `$fg` のようなトークンで書き、適用時に palette_tokens() で
    # 現在のパレット由来の実色へ展開する。色を直書きすると OS がダークテーマの
    # とき「白背景に白文字」になって読めなくなるため、直書きは禁止。
    _UI_STYLES = {
        # 標準にも「基準QSS」を持たせ、ボタン/入力欄の高さを統一して見切れを防ぐ
        "standard": {
            "qss": """
QPushButton { padding: 4px 10px; min-height: 22px; }
QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox { min-height: 22px; }
""",
            "tb_style": "beside", "tb_icon": 24, "indent": 20},
    }


    def _apply_ui_style(self, name):
        """UIスタイル（外観テーマ）を適用する。ウィジェット・機能は変えない。

        注意: setStyleSheet はその場で PaletteChange を発生させ、テーマ追従
        （_on_palette_changed）が走る。**採用した名前を先に記録**しておかないと、
        追従側が「1つ前のスタイル」を読んで再適用し、選んだ外観が巻き戻る。"""
        style = self._UI_STYLES.get(name)
        if style is None:                 # 旧テーマ名の保存値は標準へ丸める
            name = "standard"
            style = self._UI_STYLES.get(name)
        if style is None:
            return
        self._ui_style_name = name          # ← setStyleSheet より前に確定させる
        self._applying_ui_style = True      # 自分が起こす PaletteChange は無視する
        try:
            self.setStyleSheet(render_qss(style["qss"]))
        finally:
            self._applying_ui_style = False
        tb = getattr(self, "main_toolbar", None)
        if tb is not None:
            tb.setIconSize(QtCore.QSize(style["tb_icon"], style["tb_icon"]))
            tb.setToolButtonStyle(
                QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon
                if style["tb_style"] == "beside"
                else QtCore.Qt.ToolButtonStyle.ToolButtonIconOnly)
        if hasattr(self, "explorer"):
            self.explorer.setIndentation(style["indent"])
        self._ui_settings().setValue("ui/style", name)
        self._apply_figure_theme()

    # ---- 表示レベル（画面に出す量の切り替え）----
    # 方針: 隠すのは setVisible(False) だけ。ウィジェットは常に全部作り、
    # self の属性として保持する。こうすると _collect_config / _apply_config /
    # _scope_dict / _wire_live_signals / 既存テストの属性参照が無改造で動き、
    # 「隠す＝機能を失う」にならない。隠したものは設定検索（Ctrl+F）と
    # コマンドパレット（Ctrl+Shift+P）から名前で必ず呼び戻せる。
    UI_LEVELS = ("基本", "標準", "全部")
    # 通常版の既定。シンプル版はサブクラスでこれを "基本" に上書きする。
    DEFAULT_UI_LEVEL = "全部"
    # レベルの保存先キー。通常版とシンプル版で**別のキー**にしないと、
    # 通常版で「全部」を保存した直後にシンプル版を開いても「全部」で立ち上がり、
    # シンプル版がシンプルでなくなる（実際にそうなっていた）。
    UI_LEVEL_KEY = "ui/level"

    # 各レベルで見せる書式セクション（_fmt_sections のキー）。
    # 「全部」は例外扱いで、この表を参照せず全セクション見せる。
    # 左タブの表示レベルは各タブのプラグイン（min_level）が決める。
    _LEVEL_SECTIONS = {
        "基本": ("axes_sel", "labels", "legend"),
        "標準": ("file_ops", "axes_sel", "labels", "legend", "axis",
                 "trend", "bins", "aspect", "export"),
    }
    # ファイルパネルと書式パネルは全レベルで常設（タブではないので個別扱い）
    _ALWAYS_DOCKS = ("dock_files", "dock_format")

    def ui_level(self):
        return getattr(self, "_ui_level", "全部")

    def set_ui_level(self, level, announce=True):
        """表示レベルを切り替える（メニュー・ステータスバーから）。"""
        if level not in self.UI_LEVELS:
            return
        self._apply_ui_level(level)
        self._ui_settings().setValue(self.UI_LEVEL_KEY, level)
        if announce:
            self.notify(
                f"表示レベル: {level}"
                + ("（隠れている設定も Ctrl+F で名前を入れれば出てきます）"
                   if level != "全部" else ""),
                "info")

    def _apply_ui_level(self, level):
        """レベルに応じてドック・書式セクションの表示/非表示を決める。

        注意: 左のドックはタブ化されているため、背面タブの `isVisible()` は
        False になる。「ユーザーが閉じた」の判定に visibilityChanged を使うと
        タブ切替を閉じたと誤認するので、レベルだけが可視性を決める規約にする。"""
        if level not in self.UI_LEVELS:
            level = "全部"
        self._ui_level = level
        docks = self._all_docks()
        visible_docks = self._visible_dock_names(level)
        visible_sections = self._visible_section_keys(level)
        for d in docks:
            d.setVisible(d.objectName() in visible_docks)
        for key, box in getattr(self, "_fmt_sections", {}).items():
            box.setVisible(key in visible_sections)
        # タブ化された左ドック群は、表示にした中の1枚を必ず前面に出す
        # （全部隠して1枚だけ出したとき、そのタブが選ばれていないと空に見える）
        for d in docks:
            if d.objectName() in visible_docks and not d.isFloating():
                d.raise_()
                break
        # ドックを出し入れすると中央の取り分が変わるので、幅を明示し直す
        if level != "全部":
            self._restore_dock_sizes()
        self._sync_level_ui()
        return level

    def _level_reaches(self, min_level, level):
        """表示レベル level が、min_level 以上か（基本 < 標準 < 全部）。"""
        order = UI_LEVEL_ORDER
        try:
            return order.index(level) >= order.index(min_level)
        except ValueError:
            return True

    def _visible_dock_names(self, level=None):
        """そのレベルで出すドックの objectName 集合。

        タブは各プラグインの min_level で判定する（新しいタブを足しても、
        そのタブが宣言したレベルに自動で従う）。ファイル・書式パネルは常設。"""
        level = level or self.ui_level()
        if level == "全部":
            return {d.objectName() for d in self._all_docks()}
        names = set(self._ALWAYS_DOCKS)
        for oname, plugin in getattr(self, "_tab_plugins", {}).items():
            if self._level_reaches(plugin.min_level, level):
                names.add(oname)
        return names

    def _visible_section_keys(self, level=None):
        """そのレベルで出す書式セクションのキー集合。"""
        level = level or self.ui_level()
        if level not in self._LEVEL_SECTIONS:
            return set(getattr(self, "_fmt_sections", {}))
        return set(self._LEVEL_SECTIONS[level])

    def _all_docks(self):
        """このウィンドウが持つドックの一覧（順序は左タブ→書式）。"""
        docks = [getattr(self, "files_dock", None)]
        docks += list(getattr(self, "left_docks", []))
        docks.append(getattr(self, "format_dock", None))
        return [d for d in docks if d is not None]

    def _restore_dock_sizes(self):
        """レベル変更でドックを隠した後、残ったドックの幅を既定に戻す。"""
        try:
            left = getattr(self, "left_docks", None)
            if left:
                self.resizeDocks([left[0]], [360], QtCore.Qt.Orientation.Horizontal)
            fdock = getattr(self, "format_dock", None)
            if fdock is not None and not fdock.isHidden():
                self.resizeDocks([fdock], [400], QtCore.Qt.Orientation.Horizontal)
        except Exception:   # noqa: BLE001  幅の調整は見た目だけなので失敗しても進む
            applog.get_logger().debug("ドック幅の再設定に失敗", exc_info=True)

    def _sync_level_ui(self):
        """メニューのチェックとステータスバーの表示をレベルに合わせる。"""
        for lv, act in getattr(self, "_level_actions", {}).items():
            act.blockSignals(True)
            act.setChecked(lv == self._ui_level)
            act.blockSignals(False)
        btn = getattr(self, "_level_button", None)
        if btn is not None:
            btn.setText(f"表示: {self._ui_level} ▾")

    # ---- OSのライト/ダーク切替への追従 ----
    def _effective_bg_color(self):
        """グラフの地色。ユーザー指定が無ければウィンドウの配色に合わせる。

        ダークテーマでウィンドウだけ暗くなり、グラフだけ真っ白で残ると
        まぶしくて読めない。明示指定があればそれを最優先する。"""
        user_bg = (getattr(self, "bg_color", "") or "").strip()
        if user_bg:
            return user_bg
        return palette_tokens()["base"] if is_dark_theme() else ""

    def _apply_figure_theme(self, redraw=True):
        """地色の明暗に合わせて、目盛り・軸ラベル・枠線・凡例の文字色を決める。

        描画のたびに呼ぶ（plot_series は地色しか塗らないので、暗い地色のまま
        だと黒い目盛り文字が読めなくなる）。"""
        fig = getattr(self, "fig", None)
        if fig is None:
            return
        try:
            face = self._effective_bg_color() or "white"
            fg = "#e6e6e6" if plotter.is_dark_bg(face) else "black"   # 判定は plotter と共通
            fig.set_facecolor(face)
            for ax in fig.get_axes():
                ax.tick_params(colors=fg, which="both")
                for spine in getattr(ax, "spines", {}).values():
                    spine.set_color(fg)
                axes = [ax.xaxis, ax.yaxis] + ([ax.zaxis] if hasattr(ax, "zaxis") else [])
                for a in axes:
                    a.label.set_color(fg)
                if ax.get_title():
                    ax.title.set_color(fg)
                legend = ax.get_legend()
                if legend is not None:
                    # 枠も塗らないと、暗い地色の上に白い凡例だけが浮いて
                    # その中の明るい文字が読めなくなる
                    frame = legend.get_frame()
                    frame.set_facecolor(face)
                    frame.set_edgecolor(fg)
                    for text in legend.get_texts():
                        text.set_color(fg)
                    title = legend.get_title()
                    if title is not None:
                        title.set_color(fg)
            canvas = getattr(self, "canvas", None)
            if canvas is not None and redraw:
                canvas.draw_idle()
        except Exception:   # noqa: BLE001  配色は表示上の飾りなので失敗しても続行
            applog.get_logger().debug("グラフ配色の適用に失敗", exc_info=True)

    def _on_palette_changed(self, event_type):
        """OS のテーマ変更（ライト⇔ダーク）でスタイルを再適用する。

        呼び出し元は GraphApp.changeEvent（super() を呼ぶメソッドは Mixin に
        置かない、というこのプロジェクトの決まりに従うため本体側に置く）。"""
        if event_type not in (QtCore.QEvent.Type.PaletteChange,
                              QtCore.QEvent.Type.ThemeChange):
            return
        if getattr(self, "_applying_ui_style", False):
            return          # 自分の setStyleSheet が起こした通知。追従不要
        if not getattr(self, "_ui_style_name", None):
            return
        # 名前は**発火時**に読む。ここで捕まえて渡すと、その後ユーザーが別の外観を
        # 選んでも古い方が後から再適用されて巻き戻る。
        QtCore.QTimer.singleShot(
            0, lambda: self._apply_ui_style(getattr(self, "_ui_style_name", None)))

    def _build_toolbar(self):
        """よく使う操作をワンクリックで呼べるツールバー（メニューと同じ機能）。"""
        tb = QtWidgets.QToolBar("メイン")
        tb.setObjectName("main_toolbar")
        tb.setMovable(False)
        tb.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.main_toolbar = tb
        self.addToolBar(tb)
        SP = QtWidgets.QStyle.StandardPixmap

        def act(text, slot, tip, icon=None):
            if icon is not None:
                a = QtGui.QAction(self.style().standardIcon(icon), text, self)
            else:
                a = QtGui.QAction(text, self)
            a.setToolTip(tip)
            a.triggered.connect(slot)
            tb.addAction(a)
            return a

        act("ファイル追加", self.add_file,
            "CSV/TSV/波形ファイルを読み込む（Ctrl+O）。ウィンドウへのドラッグ&ドロップも可",
            SP.SP_DialogOpenButton)
        act("フォルダ", self.add_folder,
            "フォルダ内のデータファイルを一括読み込み（Ctrl+Shift+O）", SP.SP_DirOpenIcon)
        act("貼り付け", self.paste_from_clipboard,
            "Excel等からコピーした表を新規データとして読み込む（Ctrl+Shift+V）")
        tb.addSeparator()
        act("描画", self.draw_graph, "グラフを描画（F5）", SP.SP_BrowserReload)
        act("＋グラフ", self.open_graph_window,
            "現在のグラフを独立ウィンドウに複製（Ctrl+G）。何枚も並べて比較できます")
        tb.addSeparator()
        act("画像保存", self.save_figure, "グラフを画像ファイルに保存（Ctrl+S）",
            SP.SP_DialogSaveButton)
        act("コピー", self.copy_figure, "グラフ画像をクリップボードにコピー（Ctrl+Shift+C）")
        act("一括出力", self.batch_export,
            "読み込んだ各ファイルを個別に描画してまとめて画像保存（Ctrl+B）")
        tb.addSeparator()
        act("戻す", self.undo, "書式・設定の変更を1つ戻す（Ctrl+Z）", SP.SP_ArrowBack)
        act("やり直す", self.redo, "戻した変更をやり直す（Ctrl+Y）", SP.SP_ArrowForward)

    def _build_central(self):
        # 中央＝グラフ＋データ編集。周囲のパネルはすべてドックウィジェット：
        # 既定は従来どおり「左にタブ4枚・右に書式」だが、タブ（タイトル部）を
        # ドラッグすると独立ウィンドウとして切り離せる。閉じたパネルは
        # 「表示」メニューから再表示でき、配置はリセットも可能。
        self.setDockOptions(
            QtWidgets.QMainWindow.DockOption.AnimatedDocks
            | QtWidgets.QMainWindow.DockOption.AllowTabbedDocks
            | QtWidgets.QMainWindow.DockOption.AllowNestedDocks)
        self.setTabPosition(QtCore.Qt.DockWidgetArea.LeftDockWidgetArea,
                            QtWidgets.QTabWidget.TabPosition.North)

        # 読み込み済みファイル＝専用パネル（既定でフロートの独立ウィンドウ）
        left = QtCore.Qt.DockWidgetArea.LeftDockWidgetArea
        files_dock = QtWidgets.QDockWidget("読み込み済みファイル", self)
        files_dock.setObjectName("dock_files")   # saveState に必須
        files_dock.setWidget(self._scrollable(self._build_files_panel()))
        self.addDockWidget(left, files_dock)
        self.files_dock = files_dock

        # 左：入力・解析パネル（軸の選択 / オシロ / 高度解析 / 統計解析）
        # 左タブは差し込み式（graph_app_tabs.py が register_tab で登録）。
        # 新しい機能タブはプラグインを1つ足すだけで、ここは無改造で並べられる。
        self.left_docks = []
        self._tab_plugins = {}     # objectName -> TabPlugin（表示レベルの判定に使う）
        for plugin in registered_tabs():
            dock = QtWidgets.QDockWidget(plugin.title, self)
            dock.setObjectName("dock_" + plugin.key)   # saveState に必須
            w = plugin.build(self)
            # 中身をスクロール可能にして、ドックを好きな幅まで狭められるようにする
            # （中身の最小サイズがドックの縮小を妨げないように。既にスクロール式ならそのまま）
            if not isinstance(w, QtWidgets.QScrollArea):
                w = self._scrollable(w)
            dock.setWidget(w)
            self.addDockWidget(left, dock)
            self.left_docks.append(dock)
            self._tab_plugins[dock.objectName()] = plugin
        for d in self.left_docks[1:]:           # 既定はタブ化（従来の見た目）
            self.tabifyDockWidget(self.left_docks[0], d)

        # 中央：通知バー＋進捗＋（グラフ表示／データ編集）
        center = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
        self.center_splitter = center
        center.addWidget(self._build_plot_area())
        center.setStretchFactor(0, 4)
        holder = QtWidgets.QWidget()
        hlay = QtWidgets.QVBoxLayout(holder)
        hlay.setContentsMargins(0, 0, 0, 0)
        hlay.setSpacing(2)
        # 告知はここに出す（モーダルダイアログで操作を止めない）
        self.notify_bar = NotificationBar(holder)
        hlay.addWidget(self.notify_bar)
        # 読み込みなどの進行状況（非モーダル。キャンセル可）
        self.progress_strip = ProgressStrip(holder)
        self.progress_strip.canceled.connect(self._cancel_background)
        hlay.addWidget(self.progress_strip)
        hlay.addWidget(center, 1)
        self.setCentralWidget(holder)

        # 右端：グラフ書式調整パネル（書式コントロール＋系列スタイル表）
        fdock = QtWidgets.QDockWidget("グラフ書式調整", self)
        fdock.setObjectName("dock_format")
        fdock.setWidget(self._build_format_panel())
        self.addDockWidget(QtCore.Qt.DockWidgetArea.RightDockWidgetArea, fdock)
        self.format_dock = fdock

        self.left_docks[0].raise_()   # 既定は「1. データ」を前面に
        # 幅の初期値（旧レイアウトの 左360 / 右400 相当）
        self.resizeDocks([self.left_docks[0]], [360], QtCore.Qt.Orientation.Horizontal)
        self.resizeDocks([fdock], [400], QtCore.Qt.Orientation.Horizontal)

        # 表示メニューへ各パネルの表示/非表示と配置リセットを追加
        vm = self.view_menu
        vm.addSeparator()
        for d in [self.files_dock, *self.left_docks, fdock]:
            act = d.toggleViewAction()
            act.setStatusTip(f"{d.windowTitle()} パネルの表示/非表示")
            vm.addAction(act)
            self._palette_register("表示", f"{d.windowTitle()} パネルの表示/非表示", act)
        # ドラッグ以外の明示的な切り離し手段（チェック=別ウィンドウ、外す=元に戻す）
        vm.addSeparator()
        float_menu = vm.addMenu("別ウィンドウで表示（切り離し）")
        self._float_actions = {}
        for d in [self.files_dock, *self.left_docks, fdock]:
            a = QtGui.QAction(d.windowTitle(), self)
            a.setCheckable(True)
            a.setStatusTip(f"{d.windowTitle()} を独立ウィンドウとして切り離す／チェックを外すと元の位置へ戻す")
            a.toggled.connect(lambda on, dd=d: self._set_dock_floating(dd, on))
            d.topLevelChanged.connect(lambda floating, aa=a: self._sync_float_action(aa, floating))
            # 切り離したらOSネイティブ枠にして、Windowsのスナップを効かせる
            d.topLevelChanged.connect(lambda floating, dd=d: self._native_float_frame(dd, floating))
            # タイトルのダブルクリック=戻す／メイン左右端へのドロップ=ドッキング
            self._install_dock_native_filter(d)
            # ドックの移動でタブバーが作り直されることがあるため、そのたびに配線し直す
            d.topLevelChanged.connect(self._wire_dock_tabbars)
            d.dockLocationChanged.connect(self._wire_dock_tabbars)
            float_menu.addAction(a)
            self._palette_register("表示", f"{d.windowTitle()} を別ウィンドウで表示", a)
            self._float_actions[d.objectName()] = a
        # 見た目のプリセット。以前は「レイアウト」と「UIスタイル（外観のみ）」の
        # 2メニューに分かれていて、片方だけ変えると中途半端な画面になっていた。
        # 既定は配置＋外観をまとめて適用し、外観だけの切替は下位メニューに置く。
        lay_menu = vm.addMenu("画面の配置")
        self._menu_action(lay_menu, "標準（3ペイン）", lambda: self._apply_layout_preset("standard"),
                          tip="左パネル＋中央グラフ＋右書式の標準配置・標準の外観に戻す")
        self._menu_action(lay_menu, "グラフ集中（Saleae風）",
                          lambda: self._apply_layout_preset("graph"),
                          tip="パネルを全部たたみ、グラフをほぼ全画面に（波形をじっくり見る）")
        self._menu_action(lay_menu, "解析中心（オシロ）",
                          lambda: self._apply_layout_preset("analysis"),
                          tip="オシロ/解析パネル＋大きなグラフ＋データ表（測定作業向け）")
        self._menu_action(lay_menu, "データ整備",
                          lambda: self._apply_layout_preset("data"),
                          tip="データパネル＋大きなデータ編集表（読み込み・クレンジング向け）")
        vm.addSeparator()
        self._menu_action(vm, "メッセージ履歴…", self.show_message_log,
                          tip="これまでのメッセージ・警告・エラーを一覧で見る")
        self._menu_action(vm, "パネル配置をリセット", self._reset_panel_layout,
                          tip="パネルのドッキング配置・表示状態を初期状態に戻す")
        # 読み込み済みファイルは既定で独立ウィンドウとして浮かべる
        # （topLevelChanged→_native_float_frame でOSネイティブ枠＝スナップ対応になる）
        self.files_dock.setFloating(True)
        self.files_dock.resize(400, 620)
        self.files_dock.move(self.x() + 40, self.y() + 120)
        self._default_window_state = self.saveState()   # リセット用に既定配置を記憶
        self._wire_dock_tabbars()   # タブのダブルクリック=切り離し

        self._wire_live_signals()
        self._add_tooltips()
        self._build_setting_index()   # 設定検索の索引（この時点で全部組み上がっている）
        self._apply_accessibility()   # アクセシブル名・buddy・Tab順・ニーモニック

    # ---- ネイティブ枠フロートの「戻す」操作（スナップと両立させる）----
    # OSスナップ=画面の端／ドッキング=メインウィンドウの左右端ゾーン、と場所で
    # 意図を分けることで両立する。さらにタイトルバーのダブルクリックで即ドッキング。
    def _install_dock_native_filter(self, dock):
        if not hasattr(self, "_dock_native_filter"):
            app = self

            class _F(QtCore.QObject):
                def eventFilter(self, obj, ev):
                    t = ev.type()
                    if (t == QtCore.QEvent.Type.NonClientAreaMouseButtonDblClick
                            and isinstance(obj, QtWidgets.QDockWidget)
                            and obj.isFloating()):
                        app._redock(obj)     # タイトルバーのダブルクリック=戻す
                        return True
                    if (t == QtCore.QEvent.Type.Move
                            and isinstance(obj, QtWidgets.QDockWidget)
                            and obj.isFloating()):
                        app._note_float_move(obj)
                    return False

            self._dock_native_filter = _F(self)
        dock.installEventFilter(self._dock_native_filter)

    def _redock(self, dock):
        area = self.dockWidgetArea(dock)
        if area == QtCore.Qt.DockWidgetArea.NoDockWidgetArea:
            area = QtCore.Qt.DockWidgetArea.LeftDockWidgetArea
        self.addDockWidget(area, dock)
        dock.setFloating(False)
        self._set_status(f"{dock.windowTitle()} をドッキングに戻しました。")

    def _note_float_move(self, dock):
        """フロート窓の移動を監視し、ドラッグ終了時に置き場所で意図を判別する。
        連続したMove（ドラッグ）だけを対象にし、プリセット等の単発移動では発動しない。"""
        if getattr(self, "_float_move_dock", None) is not dock:
            self._float_move_dock = dock
            self._float_move_count = 0
        self._float_move_count += 1
        if not hasattr(self, "_float_move_timer"):
            self._float_move_timer = QtCore.QTimer(self)
            self._float_move_timer.setSingleShot(True)
            self._float_move_timer.timeout.connect(
                lambda: self._maybe_dock_on_drop(self._float_move_dock,
                                                 QtGui.QCursor.pos()))
        self._float_move_timer.start(300)

    def _maybe_dock_on_drop(self, dock, pos):
        """ドラッグ終了位置がメインウィンドウの左右端ゾーンならドッキングする。
        画面の端（12px以内）はWindowsスナップの領分なので何もしない。"""
        if (dock is None or not dock.isFloating()
                or getattr(self, "_float_move_count", 0) < 3):   # 単発移動は無視
            self._float_move_count = 0
            return
        self._float_move_count = 0
        screen = QtGui.QGuiApplication.screenAt(pos)
        if screen is not None:
            sg = screen.geometry()
            if (pos.x() - sg.left() <= 12 or sg.right() - pos.x() <= 12
                    or pos.y() - sg.top() <= 12 or sg.bottom() - pos.y() <= 12):
                return   # 画面端＝OSスナップの意図
        fg = self.frameGeometry()
        if not fg.contains(pos):
            return       # メインウィンドウの外＝ただの移動
        if pos.x() - fg.left() <= 160:
            self.addDockWidget(QtCore.Qt.DockWidgetArea.LeftDockWidgetArea, dock)
        elif fg.right() - pos.x() <= 160:
            self.addDockWidget(QtCore.Qt.DockWidgetArea.RightDockWidgetArea, dock)
        else:
            return       # 中央への移動はドッキングしない（誤爆防止）
        dock.setFloating(False)
        self._set_status(f"{dock.windowTitle()} をドッキングしました"
                         "（切り離しはタブのダブルクリック／表示メニューから）。")

    def _native_float_frame(self, dock, floating):
        """切り離したパネルをOSネイティブ枠の通常ウィンドウにする。

        Windows 11 のスナップ（画面端へのドラッグ・最大化ボタンにマウスを載せた
        ときのレイアウト選択・Win+矢印）が Chrome 等と同じように効くようになる。
        代わりにタイトルバーのドラッグ/ダブルクリックでの再ドッキングは使えない
        （戻すのは 表示メニューのチェックを外す か パネル配置をリセット）。"""
        if floating:
            size = dock.size()   # フラグ変更でサイズが失われるため引き継ぐ
            dock.setWindowFlags(QtCore.Qt.WindowType.Window)
            dock.show()   # フラグ変更後は再表示が必要
            if size.width() < 220 or size.height() < 180:
                size = QtCore.QSize(380, 520)   # 極小で浮かないよう既定サイズを保証
            dock.resize(size)

    def _set_dock_floating(self, dock, on):
        """メニューからの切り離し/復帰。非表示なら表示してから切り替える。"""
        if dock.isFloating() == bool(on):
            return
        dock.setVisible(True)
        dock.setFloating(bool(on))
        if on:
            dock.raise_()
            self._set_status(f"{dock.windowTitle()} を別ウィンドウにしました。"
                             "画面端へドラッグ=Windowsスナップ／メインウィンドウの左右端へ"
                             "ドロップ or タイトルをダブルクリック=ドッキングに戻す")

    @staticmethod
    def _sync_float_action(action, floating):
        """ドラッグ等での切り離し/復帰をメニューのチェックへ反映する。"""
        action.blockSignals(True)
        action.setChecked(bool(floating))
        action.blockSignals(False)

    def _wire_dock_tabbars(self, *_):
        """ドックのタブバーに『ダブルクリック=切り離し』を配線する。

        タブバーは Qt がドックのタブ化時に動的に作るため、ドックの移動のたびに
        呼ばれ、未配線のタブバーだけを接続する（多重接続防止にプロパティ印）。"""
        for tb in self.findChildren(QtWidgets.QTabBar):
            if tb.parent() is not self or tb.property("_dock_dbl"):
                continue
            tb.setProperty("_dock_dbl", True)
            tb.setToolTip("ドラッグ=パネルの移動・切り離し／ダブルクリック=別ウィンドウ化")
            tb.tabBarDoubleClicked.connect(
                lambda i, bar=tb: self._float_dock_by_tab(bar, i))

    def _float_dock_by_tab(self, bar, index):
        title = bar.tabText(index)
        for d in [self.files_dock, *self.left_docks, self.format_dock]:
            if d.windowTitle() == title:
                d.setFloating(True)
                d.raise_()
                self._set_status(f"{title} を別ウィンドウにしました。"
                                 "画面端へドラッグ=Windowsスナップ／メインウィンドウの左右端へ"
                                 "ドロップ or タイトルをダブルクリック=ドッキングに戻す")
                return

    def _apply_layout_preset(self, name):
        """ワンクリックのレイアウトプリセット。

        graph=Saleae風（グラフほぼ全画面）／analysis=オシロ作業／data=データ整備。
        隠したパネルは表示メニュー（またはレイアウト→標準）でいつでも戻せる。

        レイアウトは「どのパネルをどこに置くか」を直接決めるものなので、
        表示レベルとは競合する。プリセットを選んだ時点でレベルは「全部」に
        上げる（そうしないと、プリセットが出したパネルをレベルが隠し返す）。"""
        if self.ui_level() != "全部":
            self._apply_ui_level("全部")
            self._ui_settings().setValue(self.UI_LEVEL_KEY, "全部")
        total = max(sum(self.center_splitter.sizes()), 400)
        for d in [self.files_dock, *self.left_docks, self.format_dock]:
            d.setFloating(False)
        # ツールバーは既定の上配置へ戻す
        tb = getattr(self, "main_toolbar", None)
        if tb is not None:
            self.addToolBar(QtCore.Qt.ToolBarArea.TopToolBarArea, tb)
        if name == "standard":
            self._reset_panel_layout()
            self.center_splitter.setSizes([int(total * 0.8), int(total * 0.2)])
            return
        if name == "graph":          # Saleae風: 波形が主役、他は全部たたむ
            for d in [self.files_dock, *self.left_docks, self.format_dock]:
                d.hide()
            self.center_splitter.setSizes([total, 0])
            self._set_status("レイアウト: グラフ集中（パネルは表示メニュー、または"
                             "レイアウト→標準 で戻せます）")
        elif name == "analysis":     # オシロ/解析＋大きなグラフ＋下に測定結果の表
            for d in [self.files_dock, *self.left_docks, self.format_dock]:
                d.hide()
            scope = self.left_docks[1]
            scope.show()
            self.addDockWidget(QtCore.Qt.DockWidgetArea.LeftDockWidgetArea, scope)
            self.resizeDocks([scope], [330], QtCore.Qt.Orientation.Horizontal)
            self.center_splitter.setSizes([int(total * 0.85), int(total * 0.15)])
            self._set_status("レイアウト: 解析中心（オシロ/解析＋グラフ）")
        elif name == "data":         # データ整備: ファイルツリー＋大きな編集表
            for d in [*self.left_docks, self.format_dock]:
                d.hide()
            self.files_dock.show()
            self.addDockWidget(QtCore.Qt.DockWidgetArea.LeftDockWidgetArea, self.files_dock)
            self.resizeDocks([self.files_dock], [380], QtCore.Qt.Orientation.Horizontal)
            self.center_splitter.setSizes([int(total * 0.45), int(total * 0.55)])
            self._set_status("レイアウト: データ整備（ファイルツリー＋データ編集表）")
    def _reset_panel_layout(self):
        """ドッキングパネルの配置・表示状態を初期状態に戻す。"""
        if getattr(self, "_default_window_state", None) is not None:
            self.restoreState(self._default_window_state)
        for d in [*self.left_docks, self.format_dock]:
            d.setFloating(False)
            d.setVisible(True)
        # 読み込み済みファイルの既定は「独立ウィンドウ」（restoreStateがフロートへ戻す）
        self.files_dock.setVisible(True)
        tb = getattr(self, "main_toolbar", None)
        if tb is not None:   # ツールバーは常に上へ戻す
            self.addToolBar(QtCore.Qt.ToolBarArea.TopToolBarArea, tb)
            tb.show()
        self.left_docks[0].raise_()
        self._set_status("パネル配置を初期状態に戻しました。")

    # ---- 読み込み済みファイル（専用ウィンドウ）----
    def _build_files_panel(self):
        """「読み込み済みファイル」専用パネル。ツリー＋ファイル操作＋系列選択＋読み込み設定。
        既定ではフロートの独立ウィンドウとして表示される（ドッキングも可能）。"""
        top = QtWidgets.QWidget(); tv = QtWidgets.QVBoxLayout(top)
        tv.setContentsMargins(4, 4, 4, 4)
        # VS Code風のセクションヘッダー（右側にアクションボタン）
        head = QtWidgets.QHBoxLayout()
        head.addWidget(self._bold("エクスプローラー"))
        head.addStretch(1)
        SP = QtWidgets.QStyle.StandardPixmap

        def tool(icon, tip, slot):
            b = QtWidgets.QToolButton()
            b.setIcon(self.style().standardIcon(icon))
            b.setToolTip(tip)
            b.setAutoRaise(True)
            b.clicked.connect(slot)
            head.addWidget(b)

        tool(SP.SP_FileIcon, "ファイルを追加（Ctrl+O）", self.add_file)
        tool(SP.SP_DirOpenIcon, "フォルダを開く（Ctrl+Shift+O）", self.add_folder)
        tool(SP.SP_BrowserReload, "すべてのファイルを再読込（ディスクの最新内容に更新）",
             self._reload_all_files)
        tool(SP.SP_TitleBarShadeButton, "すべて折りたたむ",
             lambda: self.explorer.collapseAll())
        tv.addLayout(head)
        hint = QtWidgets.QLabel("ファイルを追加（ここにドラッグ&ドロップも可）→ 描きたい列（Y軸）を"
                                "チェック、または列をグラフへドラッグ →「グラフを描画」")
        hint.setWordWrap(True); hint.setStyleSheet("color:#666;")
        tv.addWidget(hint)
        # 旧ファイル一覧は非表示のまま「選択・削除・プレビューの土台」として保持する。
        # 下のツリーと双方向同期するので、既存の機能（複数選択削除・再読込・設定
        # 復元・テスト）はそのまま動く。レイアウトには追加しない。
        self.file_list = QtWidgets.QListWidget()
        self.file_list.setVisible(False)
        self.file_list.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.file_list.currentRowChanged.connect(self._on_file_selected)
        self.file_list.currentRowChanged.connect(self._sync_explorer_current)
        # VS Code風ツリー：ファイル行（アイコン＋行数×列数＋フォルダ名）を展開すると
        # 列（Y系列）がチェックボックス付きで並ぶ。行クリックでチェックがトグル。
        self._explorer_building = False
        self.explorer = ExplorerTree()
        self.explorer.setColumnCount(2)
        self.explorer.setHeaderHidden(True)
        self.explorer.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.explorer.setAllColumnsShowFocus(True)
        self.explorer.setMinimumHeight(60)   # 境界線ドラッグでかなり小さくもできる
        hdr = self.explorer.header()
        hdr.setStretchLastSection(False)
        hdr.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        self.explorer.setToolTip(
            "読み込んだファイルの一覧。▶で展開すると列（Y系列）が出ます。\n"
            "列の行クリック=チェックON/OFF／ダブルクリック=その列だけ表示／\n"
            "列やファイルを【グラフへドラッグ】=系列を追加して描画。\n"
            "ファイルのチェック=全列を一括ON/OFF。右クリックでメニュー\n"
            "（X軸にする・再読込・削除・エクスプローラーで表示など）。\n"
            "ファイル行はCtrl/Shift＋クリックで複数選択→「削除」でまとめて削除。\n"
            "F2=名前の変更／Delete=一覧から削除（ディスクのファイルは消しません）。")
        # VS Code互換のキーボード操作とホバー表示
        self.explorer.renameRequested.connect(self._on_tree_rename)
        self.explorer.deleteRequested.connect(self.remove_file)   # 一覧から削除（ディスクは消さない）
        self.explorer.setStyleSheet(
            "QTreeWidget::item:hover { background: rgba(90, 93, 94, 0.10); }")
        self.explorer.itemChanged.connect(self._on_explorer_item_changed)
        self.explorer.itemDoubleClicked.connect(self._on_explorer_double_clicked)
        self.explorer.itemSelectionChanged.connect(self._on_explorer_selection_changed)
        self.explorer.currentItemChanged.connect(self._on_explorer_current_changed)
        self.explorer.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.explorer.customContextMenuRequested.connect(self._explorer_menu)
        tv.addWidget(self.explorer, 1)

        row = QtWidgets.QHBoxLayout()
        b_add = QtWidgets.QPushButton("追加...")
        b_add.setToolTip("ファイル追加（Ctrl+O）。CSV/Excel/波形などを複数選択で読み込みます。\n"
                         "ウィンドウへのドラッグ&ドロップ、フォルダごと開く（Ctrl+Shift+O）も可。")
        b_add.clicked.connect(self.add_file)
        b_paste = QtWidgets.QPushButton("貼り付け")
        b_paste.setToolTip("Excel等からコピーした表を新規データとして読み込む（Ctrl+Shift+V）")
        b_paste.clicked.connect(self.paste_from_clipboard)
        b_del = QtWidgets.QPushButton("削除")
        b_del.setToolTip("選択中のファイルを削除（Ctrl/Shift＋クリックで複数選択→まとめて削除）")
        b_del.clicked.connect(self.remove_file)
        b_clear = QtWidgets.QPushButton("全削除")
        b_clear.setToolTip("読み込み済みファイルをすべて一覧から削除します。")
        b_clear.clicked.connect(self.clear_all_files)
        # ファイル操作は1行にまとめる（追加系を左・削除系を右に）
        row.addWidget(b_add); row.addWidget(b_paste)
        row.addWidget(b_del); row.addWidget(b_clear)
        tv.addLayout(row)
        # 名前で選択（入力した名前を含む系列だけをチェックし、他は解除）
        yf = QtWidgets.QHBoxLayout()
        self.y_filter = QtWidgets.QLineEdit()
        self.y_filter.setPlaceholderText("名前で選択（例: 電圧）")
        self.y_filter.setToolTip("入力した名前を含む列（系列）だけを選択します（他は解除）。Enter でも実行。\n"
                                 "複数ファイルで同じ列名だけ選びたいときに便利です。")
        self.y_filter.returnPressed.connect(self.select_by_name)
        b_yf = QtWidgets.QPushButton("名前で選択"); b_yf.clicked.connect(self.select_by_name)
        yf.addWidget(self.y_filter, 1); yf.addWidget(b_yf)
        tv.addLayout(yf)
        ybtns = QtWidgets.QHBoxLayout()
        for text, fn in (("全選択", lambda: self._check_all_y(True)),
                         ("全解除", lambda: self._check_all_y(False)),
                         ("反転", self._invert_y)):
            btn = QtWidgets.QPushButton(text); btn.clicked.connect(fn)
            ybtns.addWidget(btn)
        tv.addLayout(ybtns)
        # 読み込み設定（区切り・文字コード・再読込）。使用頻度が低いので畳んで置く
        sec_load = self._fmt_section("読み込み設定（区切り・文字コード）", "file_ops", False)
        file_v = QtWidgets.QVBoxLayout()
        grid = QtWidgets.QGridLayout()
        grid.addWidget(QtWidgets.QLabel("区切り:"), 0, 0)
        self.delim_combo = QtWidgets.QComboBox()
        self.delim_combo.addItem("自動判別")
        for lbl in data_loader.DELIMITER_LABELS.values():
            self.delim_combo.addItem(lbl)
        grid.addWidget(self.delim_combo, 0, 1)
        self.delim_combo.setToolTip("区切り文字。変更後は「選択中ファイルを再読込」を押してください。")
        grid.addWidget(QtWidgets.QLabel("文字コード:"), 1, 0)
        self.enc_combo = QtWidgets.QComboBox()
        self.enc_combo.addItems(["自動判別", "utf-8-sig", "utf-8", "cp932",
                                 "shift_jis", "euc-jp", "utf-16"])
        self.enc_combo.setToolTip("文字化けする場合はここで指定し、「選択中ファイルを再読込」を押します。")
        grid.addWidget(self.enc_combo, 1, 1)
        b_reload = QtWidgets.QPushButton("選択中ファイルを再読込")
        b_reload.setToolTip("区切り・文字コードの変更を反映して読み直します。")
        b_reload.clicked.connect(self.reload_current)
        grid.addWidget(b_reload, 2, 0, 1, 2)
        file_v.addLayout(grid)
        sec_load.set_content_layout(file_v)
        tv.addWidget(sec_load)
        return top

    # ---- データタブ（軸の選択）----

    # ---- VS Code風エクスプローラー（ファイル → 列ツリー）----
    # 真実の源は従来どおり file_list / y_list（非表示）。ツリーは表示と操作の
    # 入り口で、変更は必ず y_list / file_list を経由して既存パイプラインに流す。
    def _find_y_item(self, fl, col):
        for i in range(self.y_list.count()):
            it = self.y_list.item(i)
            if it.data(UserRole) == (fl, col):
                return it
        return None

    def _iter_file_nodes(self):
        """ツリー内の全ファイルノードを返す（フォルダ階層の有無に関わらず）。"""
        tree = self.explorer
        for i in range(tree.topLevelItemCount()):
            top = tree.topLevelItem(i)
            d = top.data(0, UserRole)
            if d and d[0] == "file":
                yield top
            elif d and d[0] == "folder":
                for j in range(top.childCount()):
                    yield top.child(j)

    def _rebuild_explorer(self):
        """ツリーの構造を file_list / y_list から作り直す。

        通常は ファイル→列 の2階層。読み込み元フォルダが2つ以上あるときは
        VS Code のように フォルダ→ファイル→列 の3階層でグループ化する。
        チェック・色・現在ファイルは最後に _sync_explorer_* で確定する。"""
        if not hasattr(self, "explorer"):
            return
        tree = self.explorer
        collapsed = set()   # 既定は展開。ユーザーが畳んだノードだけ覚えて維持する
        def _collect_collapsed(item):
            d = item.data(0, UserRole)
            if d and not item.isExpanded():
                collapsed.add(d[:2])
            for j in range(item.childCount()):
                _collect_collapsed(item.child(j))
        for i in range(tree.topLevelItemCount()):
            _collect_collapsed(tree.topLevelItem(i))
        self._explorer_building = True
        tree.blockSignals(True)
        tree.clear()
        by_file = {}
        for i in range(self.y_list.count()):
            it = self.y_list.item(i)
            fl, _c = it.data(UserRole)
            by_file.setdefault(fl, []).append(it)
        ficon = self.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_FileIcon)
        dicon = self.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_DirIcon)
        gray = QtGui.QBrush(QtGui.QColor("#808080"))
        flags_file = (QtCore.Qt.ItemFlag.ItemIsEnabled
                      | QtCore.Qt.ItemFlag.ItemIsSelectable
                      | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
        # 列は選択不可（ファイル削除の対象にならない）。クリック＝チェックのトグル
        flags_col = (QtCore.Qt.ItemFlag.ItemIsEnabled
                     | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
        labels = [self.file_list.item(r).text() for r in range(self.file_list.count())]
        dirs = {os.path.dirname(self.meta.get(l, {}).get("path", "")) for l in labels}
        dirs.discard("")
        grouped = len(dirs) >= 2   # フォルダが複数あるときだけ階層化

        if not hasattr(self, "_icon_provider"):
            self._icon_provider = QtWidgets.QFileIconProvider()

        def make_file_node(label):
            df = self.datasets.get(label)
            path = self.meta.get(label, {}).get("path", "")
            node = QtWidgets.QTreeWidgetItem([label, ""])
            node.setData(0, UserRole, ("file", label))
            icon = ficon
            if path and os.path.isfile(path):
                try:   # 種別ごとのOS実物アイコン（VS Code同様に拡張子で見分けられる）
                    icon = self._icon_provider.icon(QtCore.QFileInfo(path))
                except Exception:
                    applog.get_logger().debug("make_file_node: 無視した例外", exc_info=True)
            node.setIcon(0, icon)
            node.setFlags(flags_file)
            node.setCheckState(0, QtCore.Qt.CheckState.Unchecked)
            info = f"{len(df):,}×{len(df.columns)}" if df is not None else ""
            folder = "" if grouped else (os.path.basename(os.path.dirname(path)) if path else "")
            node.setText(1, f"{info}  {folder}".strip())
            node.setForeground(1, gray)
            tip = (path or label) + (f"\n{info.replace('×', ' 行 × ')} 列" if info else "")
            node.setToolTip(0, tip); node.setToolTip(1, tip)
            for yit in by_file.get(label, []):
                _fl, col = yit.data(UserRole)
                child = QtWidgets.QTreeWidgetItem([str(col), ""])
                child.setData(0, UserRole, ("col", label, col))
                child.setFlags(flags_col)
                child.setCheckState(0, yit.checkState())
                child.setToolTip(0, "クリック=チェックON/OFF／ダブルクリック=この列だけ表示／"
                                    "ドラッグ=グラフへ追加／右クリック=表示・X軸メニュー")
                node.addChild(child)
            node.setExpanded(("file", label) not in collapsed)
            return node

        # VS Codeと同じ並び: フォルダを先にアルファベット順、ファイルもアルファベット順
        def _dir_of(label):
            return os.path.dirname(self.meta.get(label, {}).get("path", ""))

        if grouped:
            nodir = sorted([l for l in labels if not _dir_of(l)], key=str.lower)
            bydir = {}
            for label in labels:
                dp = _dir_of(label)
                if dp:
                    bydir.setdefault(dp, []).append(label)
            for dirpath in sorted(bydir, key=str.lower):
                fold = QtWidgets.QTreeWidgetItem(
                    [os.path.basename(dirpath) or dirpath, ""])
                fold.setData(0, UserRole, ("folder", dirpath))
                fold.setIcon(0, dicon)
                fold.setFlags(QtCore.Qt.ItemFlag.ItemIsEnabled
                              | QtCore.Qt.ItemFlag.ItemIsSelectable)
                fold.setToolTip(0, dirpath)
                fold.setForeground(1, gray)
                tree.addTopLevelItem(fold)
                for label in sorted(bydir[dirpath], key=str.lower):
                    fnode = make_file_node(label)
                    fold.addChild(fnode)
                    fnode.setExpanded(("file", label) not in collapsed)
                fold.setText(1, f"{fold.childCount()}ファイル")
                fold.setExpanded(("folder", dirpath) not in collapsed)
            for label in nodir:                    # 貼り付け・PCA等はフォルダの後ろに
                node = make_file_node(label)
                tree.addTopLevelItem(node)
                node.setExpanded(("file", label) not in collapsed)
        else:
            for label in sorted(labels, key=str.lower):
                node = make_file_node(label)
                tree.addTopLevelItem(node)
                # addTopLevelItem後でないと展開が効かないため設定し直す
                node.setExpanded(("file", label) not in collapsed)
        tree.blockSignals(False)
        self._explorer_building = False
        self._sync_explorer_checks()
        self._sync_explorer_current()
        # 再構築でツリーの選択は消えている。非表示 file_list に古い複数選択が
        # 残ると「削除」が見えないファイルを巻き添えにするため、必ず映し直す。
        self._on_explorer_selection_changed()

    def _sync_explorer_checks(self):
        """y_list のチェック状態と系列色をツリーへ反映する（y_list が真実の源）。"""
        if not hasattr(self, "explorer") or getattr(self, "_explorer_building", False):
            return
        self._explorer_building = True
        try:
            ymap = {}
            for i in range(self.y_list.count()):
                it = self.y_list.item(i)
                ymap[it.data(UserRole)] = it
            ck = QtCore.Qt.CheckState.Checked
            for node in self._iter_file_nodes():
                n_ck = 0
                for j in range(node.childCount()):
                    child = node.child(j)
                    _k, fl, col = child.data(0, UserRole)
                    yit = ymap.get((fl, col))
                    if yit is None:
                        continue
                    checked = yit.checkState() == ck
                    child.setCheckState(0, ck if checked
                                        else QtCore.Qt.CheckState.Unchecked)
                    n_ck += checked
                    st = self.series_styles.get(self._style_key(fl, col)) or {}
                    color = st.get("color") if checked else None
                    child.setForeground(0, QtGui.QBrush(QtGui.QColor(color)) if color
                                        else QtGui.QBrush())
                    f = child.font(0); f.setBold(checked); child.setFont(0, f)
                total = node.childCount()
                node.setCheckState(0, ck if (total and n_ck == total)
                                   else (QtCore.Qt.CheckState.PartiallyChecked if n_ck
                                         else QtCore.Qt.CheckState.Unchecked))
        finally:
            self._explorer_building = False

    def _sync_explorer_current(self, *_):
        """file_list の現在ファイルをツリーのハイライトに反映する。"""
        if not hasattr(self, "explorer") or getattr(self, "_explorer_building", False):
            return
        it = self.file_list.currentItem()
        label = it.text() if it else None
        self._explorer_building = True
        try:
            for node in self._iter_file_nodes():
                if node.data(0, UserRole)[1] == label:
                    if self.explorer.currentItem() is not node:
                        self.explorer.setCurrentItem(node)
                    break
        finally:
            self._explorer_building = False

    def _on_explorer_item_changed(self, item, column):
        """ツリーのチェック操作を y_list へ流す（列=1系列／ファイル=全列一括）。"""
        if getattr(self, "_explorer_building", False) or column != 0:
            return
        data = item.data(0, UserRole)
        if not data:
            return
        if data[0] == "col":
            _k, fl, col = data
            yit = self._find_y_item(fl, col)
            if yit is not None and yit.checkState() != item.checkState(0):
                yit.setCheckState(item.checkState(0))   # → 既存の再描画・同期パイプへ
        else:   # ファイル行のチェック＝配下の列を一括ON/OFF（他ファイルは維持）
            label = data[1]
            on = item.checkState(0) == QtCore.Qt.CheckState.Checked
            ck = QtCore.Qt.CheckState.Checked
            self._set_all_checks(lambda it: on if it.data(UserRole)[0] == label
                                 else it.checkState() == ck)

    def _on_explorer_double_clicked(self, item, _column):
        """列のダブルクリック＝その列だけ表示（旧Yリストと同じ）。"""
        data = item.data(0, UserRole)
        if data and data[0] == "col":
            yit = self._find_y_item(data[1], data[2])
            if yit is not None:
                self._on_y_double_clicked(yit)

    def _on_explorer_selection_changed(self):
        """ツリーで選択したファイルを file_list の選択へ反映（複数選択削除用）。"""
        if getattr(self, "_explorer_building", False):
            return
        labels = {it.data(0, UserRole)[1] for it in self.explorer.selectedItems()
                  if (it.data(0, UserRole) or ("",))[0] == "file"}
        self._explorer_building = True
        try:
            for i in range(self.file_list.count()):
                it = self.file_list.item(i)
                it.setSelected(it.text() in labels)
        finally:
            self._explorer_building = False

    def _on_explorer_current_changed(self, current, _previous):
        """ツリーの現在ファイルを file_list に反映 → プレビューが追従する。"""
        if getattr(self, "_explorer_building", False) or current is None:
            return
        data = current.data(0, UserRole)
        if not data or data[0] != "file":
            return
        it = self._find_file_item(data[1])
        if it is not None:
            row = self.file_list.row(it)
            if row != self.file_list.currentRow():
                self.file_list.setCurrentRow(row)

    def _explorer_menu(self, pos):
        item = self.explorer.itemAt(pos)
        if item is None:
            return
        gpos = self.explorer.viewport().mapToGlobal(pos)
        data = item.data(0, UserRole)
        if not data:
            return
        if data and data[0] == "col":
            _k, fl, col = data
            menu = self._series_menu(self._find_y_item(fl, col))
            menu.addSeparator()
            menu.addAction("この列をX軸にする", lambda: self._set_x_from_tree(col))
            menu.addAction("名前の変更（凡例ラベル）\tF2", lambda: self._on_tree_rename(item))
            menu.exec(gpos)
            return
        if data[0] == "folder":   # フォルダノードのメニュー
            dirpath = data[1]
            labels = [item.child(j).data(0, UserRole)[1]
                      for j in range(item.childCount())]
            menu = QtWidgets.QMenu(self)
            menu.addAction("フォルダ内を全チェック",
                           lambda: self._check_labels_cols(labels, True))
            menu.addAction("フォルダ内を全解除",
                           lambda: self._check_labels_cols(labels, False))
            menu.addSeparator()
            menu.addAction("フォルダ内のファイルを削除",
                           lambda: (self._remove_labels(labels),
                                    self._set_status(f"{len(labels)}ファイルを削除しました。")))
            if os.path.isdir(dirpath):
                menu.addAction("エクスプローラーで開く",
                               lambda: self._reveal_in_explorer(dirpath))
            menu.exec(gpos)
            return
        label = data[1]
        path = self.meta.get(label, {}).get("path", "")
        menu = QtWidgets.QMenu(self)
        menu.addAction("全列をチェック", lambda: self._check_file_cols(label, True))
        menu.addAction("全列を解除", lambda: self._check_file_cols(label, False))
        menu.addSeparator()
        menu.addAction("名前の変更...\tF2", lambda: self._on_tree_rename(item))
        menu.addAction("再読込", lambda: self._reload_label(label))
        menu.addAction("削除（一覧から）\tDel",
                       lambda: (self._remove_labels([label]),
                                self._set_status(f"{label} を削除しました。")))
        if path and os.path.isfile(path):
            menu.addSeparator()
            menu.addAction("エクスプローラーで表示", lambda: self._reveal_in_explorer(path))
            menu.addAction("パスをコピー",
                           lambda: QtWidgets.QApplication.clipboard().setText(path))
        menu.exec(gpos)

    def _check_file_cols(self, label, on):
        self._check_labels_cols([label], on)

    def _check_labels_cols(self, labels, on):
        """複数ファイルの全列を一括ON/OFF（他ファイルの状態は維持）。"""
        labelset = set(labels)
        ck = QtCore.Qt.CheckState.Checked
        self._set_all_checks(lambda it: on if it.data(UserRole)[0] in labelset
                             else it.checkState() == ck)
        self._maybe_draw()

    def _reload_label(self, label):
        it = self._find_file_item(label)
        if it is not None:
            self.file_list.setCurrentRow(self.file_list.row(it))
            self.reload_current()

    def _set_x_from_tree(self, col):
        if self._use_leftmost_x():
            self._set_status("『一番左の列をX軸にする』がONのため、X軸は先頭列固定です。")
            return
        i = self.x_combo.findText(str(col))
        if i >= 0:
            self.x_combo.setCurrentIndex(i)
            self._set_status(f"X軸を「{col}」にしました。")

    def _drop_series(self, payload):
        """ツリーからグラフへドロップされた系列（'fl\\tcol' 行）をチェックして描画する。"""
        added = []
        ck = QtCore.Qt.CheckState.Checked
        for line in payload.splitlines():
            if "\t" not in line:
                continue
            fl, col = line.split("\t", 1)
            yit = self._find_y_item(fl, col)
            if yit is not None and yit.checkState() != ck:
                yit.setCheckState(ck)
                added.append(str(col))
        if added:
            self.draw_graph()
            self._set_status("ドロップで追加: " + ", ".join(added[:8])
                             + (" ほか" if len(added) > 8 else ""))
        else:
            self._set_status("ドロップされた系列は既に表示されています。")

    # ---- 名前の変更（F2 / 右クリック。VS Code互換）----
    def _on_tree_rename(self, item):
        """列=系列名（凡例ラベル）、ファイル=データセットの表示名を変更する。"""
        data = item.data(0, UserRole)
        if not data:
            return
        if data[0] == "col":
            _k, fl, col = data
            skey = self._style_key(fl, col)
            st = self.series_styles.setdefault(skey, {})
            cur = st.get("label") or str(col)
            new, ok = QtWidgets.QInputDialog.getText(
                self, "系列名の変更", "凡例に表示する名前:", text=cur)
            new = (new or "").strip()
            if not ok or not new:
                return
            if new == str(col):
                st.pop("label", None)   # 列名と同じなら既定に戻す
            else:
                st["label"] = new
            self._on_y_selection_changed()   # ツリー・系列バー・スタイル表へ反映
            if self._has_drawn:
                self.draw_graph()
        elif data[0] == "file":
            old = data[1]
            new, ok = QtWidgets.QInputDialog.getText(
                self, "名前の変更", "一覧に表示する名前（ディスクのファイル名は変わりません）:",
                text=old)
            new = (new or "").strip()
            if ok and new and new != old:
                self._rename_dataset_label(old, new)

    def _rename_dataset_label(self, old, new):
        """データセットの表示名を付け替える（スタイル・チェック・プレビューも追従）。
        ディスク上のファイル名は変更しない（表示名のみ）。"""
        if new in self.datasets:
            self.notify("同名のデータが既にあります。", "warn")
            return
        if old not in self.datasets:
            return
        checked = {(fl, c) for fl, c, _d in self._selected_series_items()}
        self.datasets[new] = self.datasets.pop(old)
        self.meta[new] = self.meta.pop(old, {"path": new, "enc": "-", "delim": "-"})
        prefix = old + "\t"
        for k in [k for k in self.series_styles if k.startswith(prefix)]:
            self.series_styles[new + "\t" + k.split("\t", 1)[1]] = self.series_styles.pop(k)
        it = self._find_file_item(old)
        if it is not None:
            it.setText(new)
        self._refresh_columns()
        # チェック状態を (旧名, 列)→(新名, 列) で引き継ぐ
        ck = QtCore.Qt.CheckState.Checked
        un = QtCore.Qt.CheckState.Unchecked
        self.y_list.blockSignals(True)
        for i in range(self.y_list.count()):
            yit = self.y_list.item(i)
            fl, c = yit.data(UserRole)
            key = (old, c) if fl == new else (fl, c)
            yit.setCheckState(ck if key in checked else un)
        self.y_list.blockSignals(False)
        self._on_y_selection_changed()
        if self._has_drawn:
            self.draw_graph()
        self._set_status(f"名前を変更しました: {old} → {new}（表示名のみ）")

    def _reveal_in_explorer(self, path):
        import subprocess
        try:
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        except OSError:
            self._set_status("エクスプローラーを開けませんでした。")

    # ---- 右側：グラフ書式調整パネル ----
    def _build_style_box(self):
        """系列スタイル表（色/線種/軸/種別/誤差列）。書式調整パネルの下段に置く。"""
        box = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(box); v.setContentsMargins(4, 4, 4, 4)
        hdr = self._bold("系列スタイル（系列名はダブルクリックで変更可）")
        hdr.setWordWrap(True)   # 折り返し可にして、パネルの最小幅を縛らないように
        v.addWidget(hdr)
        self.style_table = QtWidgets.QTableWidget(0, 9)
        self.style_table.setHorizontalHeaderLabels(
            ["系列名", "色", "線種", "幅", "マーカー", "サイズ", "軸", "種別", "誤差列"])
        self.style_table.horizontalHeader().setStretchLastSection(True)
        self.style_table.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.DoubleClicked
            | QtWidgets.QAbstractItemView.EditTrigger.EditKeyPressed)
        self.style_table.itemChanged.connect(self._on_style_label_edited)
        v.addWidget(self.style_table, 1)
        return box

    def _build_format_panel(self):
        """右端のグラフ書式調整パネル（上：設定検索／中：書式コントロール／下：系列スタイル表）。"""
        wrap = QtWidgets.QWidget()
        outer = QtWidgets.QVBoxLayout(wrap)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(2)
        # 設定はこのパネル・データパネル・描画バー・ツールバーに分かれて置かれている。
        # 「どこにあるか」を覚えていなくても名前で辿り着けるように検索を用意する。
        self.setting_search = QtWidgets.QLineEdit()
        self.setting_search.setPlaceholderText("設定を検索（例: 凡例, 対数, DPI）")
        self.setting_search.setToolTip(
            "設定名の一部を入力して Enter。該当のパネルを開いて、その項目まで移動します。")
        self.setting_search.setAccessibleName("設定の検索")
        self.setting_search.setClearButtonEnabled(True)
        self.setting_search.returnPressed.connect(self._jump_to_setting)
        outer.addWidget(self.setting_search)

        split = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
        self.format_splitter = split
        scroll = QtWidgets.QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        scroll.setWidget(self._build_tab_graph())   # 種別/タイトル/軸/近似曲線/縦横比/画像出力
        split.addWidget(scroll)
        split.addWidget(self._build_style_box())     # 系列スタイル表
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        outer.addWidget(split, 1)
        return wrap

    # ---- 設定検索（散らばった設定へジャンプする）----
    def _build_setting_index(self):
        """全パネルのコントロールを「セクション › 名前」で引ける索引にする。"""
        self._setting_index = []
        docks = [getattr(self, "files_dock", None), *getattr(self, "left_docks", []),
                 getattr(self, "format_dock", None)]
        for dock in [d for d in docks if d is not None]:
            if dock.widget() is not None:
                self._index_widget(dock.widget(), dock, "", ["", None])
        # ドックの外にある常設コントロール（描画バー・系列バー・データ編集バー）も
        # 索引に入れる。索引に無い＝名前で呼び戻せない＝隠せない、なので網羅が要る。
        for holder, section in ((getattr(self, "series_bar", None), "描画バー"),
                                (getattr(self, "_preview_bar_host", None), "データ編集")):
            if holder is not None and holder.layout() is not None:
                self._index_layout(holder.layout(), None, section, ["", None])
        for w, name in ((getattr(self, "draw_button", None), "グラフを描画 (F5)"),
                        (getattr(self, "live_check", None), "リアルタイム更新"),
                        (getattr(self, "decimate_check", None), "間引き表示"),
                        (getattr(self, "batch_button", None), "一括画像保存..."),
                        (getattr(self, "_level_button", None), "表示レベルの切替"),
                        (getattr(self, "_msg_button", None), "メッセージ履歴")):
            if w is not None and not any(e["widget"] is w for e in self._setting_index):
                self._setting_index.append(
                    {"name": name, "section": "描画バー", "dock": None,
                     "widget": w, "label": None})
        # 表示名は重複しうる（「自動」チェックが軸ごとに並ぶなど）。同じ見出しが
        # 並ぶと候補一覧で選び分けられないので、2つ目以降に連番を付けて区別する。
        seen = {}
        for e in self._setting_index:
            label = f"{e['section']} › {e['name']}" if e["section"] else e["name"]
            seen[label] = seen.get(label, 0) + 1
            e["key"] = label if seen[label] == 1 else f"{label} ({seen[label]})"
        comp = QtWidgets.QCompleter([e["key"] for e in self._setting_index], self)
        comp.setCaseSensitivity(QtCore.Qt.CaseSensitivity.CaseInsensitive)
        comp.setFilterMode(QtCore.Qt.MatchFlag.MatchContains)
        comp.activated.connect(lambda text: QtCore.QTimer.singleShot(
            0, lambda: self._jump_to_setting(text)))
        if hasattr(self, "setting_search"):
            self.setting_search.setCompleter(comp)
        # 「設定を検索」は _build_menu で正規の QAction として登録済み（Ctrl+F）。
        # ここで重ねて登録しない（メソッドを渡すとパレット全体が壊れる）。
        return self._setting_index

    def _index_layout(self, layout, dock, section, last_label):
        """レイアウトを再帰的にたどってコントロールを索引に積む。

        コントロール自身に文字が無い（コンボや入力欄）ときは、直前に置かれた
        QLabel を名前として使う。画面での読み取り方と同じ順序で拾う。"""
        # 見出しラベル（_bold）に出会ったら、そこから下を新しいセクションとして扱う。
        # オシロ/高度解析/統計解析タブは CollapsibleBox ではなく太字ラベルで
        # 区切られているため、これが無いと索引がセクション名なしになる。
        for i in range(layout.count()):
            item = layout.itemAt(i)
            sub = item.layout()
            if sub is not None:
                self._index_layout(sub, dock, section, last_label)
                continue
            w = item.widget()
            if w is None:
                continue
            if isinstance(w, QtWidgets.QLabel) and w.property("section_header"):
                section = w.text().strip()
                last_label[0], last_label[1] = "", None
                continue
            self._index_widget(w, dock, section, last_label)

    def _index_widget(self, w, dock, section, last_label):
        """ウィジェット1つを索引に積む（コンテナなら中身へ降りる）。

        レイアウトに入らないコンテナ（スプリッタ・タブ・スクロール領域）は
        レイアウト走査では辿れないので、種類ごとに明示的に降りる。"""
        controls = (QtWidgets.QAbstractButton, QtWidgets.QComboBox,
                    QtWidgets.QLineEdit, QtWidgets.QAbstractSpinBox)
        if isinstance(w, QtWidgets.QLabel):
            text = w.text().strip()
            if text:
                last_label[0], last_label[1] = text, w
            return
        if isinstance(w, CollapsibleBox):
            if w.body.layout() is not None:
                self._index_layout(w.body.layout(), dock, w.title(), ["", None])
            return
        if isinstance(w, QtWidgets.QScrollArea):
            if w.widget() is not None:
                self._index_widget(w.widget(), dock, section, last_label)
            return
        if isinstance(w, QtWidgets.QSplitter):
            for i in range(w.count()):
                self._index_widget(w.widget(i), dock, section, last_label)
            return
        if isinstance(w, QtWidgets.QTabWidget):
            for i in range(w.count()):
                self._index_widget(w.widget(i), dock, w.tabText(i), ["", None])
            return
        if isinstance(w, QtWidgets.QGroupBox) and w.title().strip():
            section = w.title().strip()      # グループ名をセクション名として使う
        if isinstance(w, controls):
            own = ""
            if isinstance(w, QtWidgets.QAbstractButton):
                own = w.text()
            elif isinstance(w, QtWidgets.QLineEdit):
                own = w.placeholderText()
            # 明示した accessibleName を最優先にする（索引はこの後の
            # _apply_accessibility より先に作られるので、名前を効かせたい
            # コントロールは _build_* の中で付ける必要がある）
            name = (w.accessibleName() or own or last_label[0] or "").strip()
            name = name.replace("&", "").rstrip(":：") or name.replace("&", "").strip()
            if name:
                self._setting_index.append(
                    {"name": name, "section": section, "dock": dock, "widget": w,
                     # 自前の文字を持たない入力欄は、直前のラベルと結び付ける
                     # （スクリーンリーダーが「編集欄」としか読まないのを防ぐ）
                     "label": None if own else last_label[1]})
            return
        if w.layout() is not None:     # グループボックス等の入れ子
            self._index_layout(w.layout(), dock, section, last_label)

    def _focus_setting_search(self):
        """設定検索へフォーカスを移す（コマンドパレット・ショートカットから）。"""
        if not hasattr(self, "setting_search"):
            return
        if getattr(self, "format_dock", None) is not None:
            self.format_dock.show()
            self.format_dock.raise_()
        self.setting_search.setFocus()
        self.setting_search.selectAll()

    def _find_setting(self, text):
        """検索語に最もよく合う索引項目を返す（完全一致→前方一致→部分一致）。"""
        needle = (text or "").strip().lower()
        if not needle:
            return None
        index = getattr(self, "_setting_index", None) or []
        for pred in (lambda e: e["key"].lower() == needle,
                     lambda e: e["name"].lower() == needle,
                     lambda e: e["name"].lower().startswith(needle),
                     lambda e: needle in e["key"].lower()):
            for e in index:
                if pred(e):
                    return e
        return None

    def _jump_to_setting(self, text=None):
        """検索語に対応する設定コントロールを画面に出して選択状態にする。"""
        if text is None and hasattr(self, "setting_search"):
            text = self.setting_search.text()
        entry = self._find_setting(text)
        if entry is None:
            self.notify(f"「{text}」に一致する設定は見つかりませんでした。", "warn")
            return None
        w = entry["widget"]
        dock = entry["dock"]
        # 表示レベルで隠れている項目なら、レベルを上げてから出す。
        # これが「隠す」と「機能を失う」を分ける仕組みの要。
        raised = self._raise_level_for(w)
        if dock is not None:
            dock.show()
            dock.raise_()
            if dock.isFloating():
                dock.activateWindow()
        # 折りたたまれたセクションの中なら開く
        p = w.parentWidget()
        while p is not None:
            if isinstance(p, CollapsibleBox):
                p.set_expanded(True)
            p = p.parentWidget()
        # スクロール領域なら見える位置まで送る
        area = w.parentWidget()
        while area is not None and not isinstance(area, QtWidgets.QScrollArea):
            area = area.parentWidget()
        if isinstance(area, QtWidgets.QScrollArea):
            area.ensureWidgetVisible(w, 50, 50)
        w.setFocus(QtCore.Qt.FocusReason.ShortcutFocusReason)
        self._flash_widget(w)
        note = f"（表示レベルを「{self.ui_level()}」に上げました）" if raised else ""
        self._set_status(f"設定: {entry['key']}{note}")
        return entry

    def _raise_level_for(self, widget):
        """対象が現在のレベルで隠れているなら、見えるレベルまで上げる。

        「基本」で隠した項目でも Ctrl+F で名前を入れれば必ずたどり着ける、を
        成立させるための逃がし口。上げた場合 True を返す。"""
        if self.ui_level() == "全部":
            return False
        if widget.isVisibleTo(self):
            return False
        for level in self.UI_LEVELS[self.UI_LEVELS.index(self.ui_level()) + 1:]:
            self._apply_ui_level(level)
            self._ui_settings().setValue(self.UI_LEVEL_KEY, level)
            if widget.isVisibleTo(self):
                return True
        return True     # 「全部」まで上げても隠れている＝折りたたみ側の問題

    def _flash_widget(self, w, ms=1600):
        """見つけた項目を一時的に縁取りして目立たせる。"""
        try:
            before = w.styleSheet()
            w.setStyleSheet(before + f"\nborder:2px solid {palette_tokens()['accent']};")
            QtCore.QTimer.singleShot(ms, lambda: w.setStyleSheet(before))
        except Exception:   # noqa: BLE001  強調は飾りなので失敗しても進む
            applog.get_logger().debug("設定のハイライトに失敗", exc_info=True)

    # ---- アクセシビリティ（スクリーンリーダー・キーボード操作）----
    # 主要ボタンの Alt ショートカット。日本語ラベルには自然な頭文字が無いので、
    # 英字を明示的に割り当てる（重複しないよう1か所で管理する）。
    _MNEMONICS = {
        "グラフを描画 (F5)": "D",
        "自動スケール": "A",
        "ファイル追加": "O",
        "フォルダを開く": "F",
        "解析実行": "R",
        "一括画像保存...": "B",
        "画像として保存": "S",
    }

    def _apply_accessibility(self):
        """アクセシブル名・buddy・Tab順・ニーモニックをまとめて設定する。

        個々の構築コードに散らかさず、索引（_build_setting_index）を使って
        画面に並んでいる順序どおりに一括で付ける。新しいコントロールを足しても
        索引に乗れば自動で対象になる。"""
        index = getattr(self, "_setting_index", None) or []
        per_dock = {}
        for e in index:
            w, label = e["widget"], e.get("label")
            if not w.accessibleName():
                w.setAccessibleName(e["key"])
            if not w.accessibleDescription() and w.toolTip():
                w.setAccessibleDescription(w.toolTip().replace("\n", " "))
            # ラベルと入力欄を結び付ける（読み上げの対応づけ＋Altでのフォーカス移動）
            if label is not None and isinstance(label, QtWidgets.QLabel) \
                    and label.buddy() is None:
                label.setBuddy(w)
            # 主要ボタンにだけ Alt ショートカットを与える
            if isinstance(w, QtWidgets.QAbstractButton):
                key = self._MNEMONICS.get(w.text())
                if key and "&" not in w.text():
                    w.setText(f"{w.text()}(&{key})")
            per_dock.setdefault(id(e["dock"]), []).append(w)
        # Tab の移動順を画面の並び順に合わせる（生成順のままだと飛び回る）
        for widgets in per_dock.values():
            focusable = [w for w in widgets
                         if w.focusPolicy() != QtCore.Qt.FocusPolicy.NoFocus]
            for prev, cur in zip(focusable, focusable[1:]):
                self.setTabOrder(prev, cur)
        # グラフ本体もキーボードで到達できるようにする（ツールバーのショートカット用）
        canvas = getattr(self, "canvas", None)
        if canvas is not None:
            canvas.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
            canvas.setAccessibleName("グラフ")
            canvas.setAccessibleDescription(
                "描画したグラフ。ホイールで拡大縮小、ダブルクリックで全体表示。")
        for name, acc in (("explorer", "ファイルと列のツリー"),
                          ("preview", "データ編集表"),
                          ("style_table", "系列スタイル表"),
                          ("y_list", "Y軸の系列一覧")):
            w = getattr(self, name, None)
            if w is not None and not w.accessibleName():
                w.setAccessibleName(acc)
        return index

    # ---- グラフ書式コントロール（右パネル上段）----
    def _fmt_section(self, title, key, default_open):
        """書式パネルの折りたたみセクションを作る（開閉状態は前回起動から復元）。"""
        val = self._ui_settings().value("fmt_section/" + key)
        expanded = default_open if val is None else (str(val) in ("1", "true", "True"))
        box = CollapsibleBox(title, expanded=expanded)
        if not hasattr(self, "_fmt_sections"):
            self._fmt_sections = {}
        self._fmt_sections[key] = box
        return box

    def _build_tab_graph(self):
        w = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(w)

        # 書式プリセット（今の見た目に名前を付けて保存・呼び出し）
        pre = QtWidgets.QHBoxLayout()
        pre.addWidget(QtWidgets.QLabel("書式プリセット"))
        self.preset_combo = QtWidgets.QComboBox()
        self.preset_combo.setToolTip("保存した書式（フォント・グリッド・凡例・色・軸など）を呼び出します。")
        pre.addWidget(self.preset_combo, 1)
        b_pa = QtWidgets.QPushButton("適用"); b_pa.clicked.connect(self.apply_preset)
        b_ps = QtWidgets.QPushButton("保存"); b_ps.clicked.connect(self.save_preset)
        b_ps.setToolTip("現在の書式設定に名前を付けて保存")
        b_pd = QtWidgets.QPushButton("削除"); b_pd.clicked.connect(self.delete_preset)
        pre.addWidget(b_pa); pre.addWidget(b_ps); pre.addWidget(b_pd)
        v.addLayout(pre)
        self._refresh_preset_combo()

        v.addWidget(self._bold("グラフ種別"))
        self.chart_combo = QtWidgets.QComboBox()
        self.chart_combo.addItems(plotter.CHART_TYPES)
        self.chart_combo.currentTextChanged.connect(self._on_chart_type_change)
        v.addWidget(self.chart_combo)
        self.hint_label = QtWidgets.QLabel()
        self.hint_label.setWordWrap(True)
        self.hint_label.setStyleSheet("color:#0a7a55;")
        v.addWidget(self.hint_label)

        # 3D表示・視点角度は「軸の選択」（データパネル）へ移動済み
        # （Z軸コンボとセットの“何をプロットするか”の設定のため）

        # 系列ごとに段を分けるサブプロット表示（折れ線/散布図の2Dのみ）
        self.stack_check = QtWidgets.QCheckBox("系列ごとに段を分ける（サブプロット）")
        self.stack_check.setToolTip(
            "各系列を上下の段に分けて描きます（X軸は共有・最大8段）。\n"
            "単位が違う系列の比較に便利。折れ線/散布図の2Dで有効。\n"
            "オシロ表示・第2軸・塗りつぶしとは併用できません（通常表示に戻ります）。\n"
            "一括画像出力には適用されません。")
        self.stack_check.setEnabled(False)
        v.addWidget(self.stack_check)

        # タイトル・ラベル・フォント
        sec_labels = self._fmt_section("タイトル・軸ラベル・文字", "labels", True)
        form = QtWidgets.QGridLayout()
        form.addWidget(QtWidgets.QLabel("タイトル"), 0, 0)
        self.title_edit = QtWidgets.QLineEdit()
        form.addWidget(self.title_edit, 0, 1, 1, 3)
        form.addWidget(QtWidgets.QLabel("X軸名"), 1, 0)
        self.xlabel_edit = QtWidgets.QLineEdit()
        form.addWidget(self.xlabel_edit, 1, 1)
        form.addWidget(QtWidgets.QLabel("Y軸名"), 1, 2)
        self.ylabel_edit = QtWidgets.QLineEdit()
        form.addWidget(self.ylabel_edit, 1, 3)
        form.addWidget(QtWidgets.QLabel("文字サイズ 題/軸/目盛"), 2, 0)
        self.fs_title = QtWidgets.QSpinBox(); self.fs_title.setRange(6, 40); self.fs_title.setValue(12)
        self.fs_label = QtWidgets.QSpinBox(); self.fs_label.setRange(6, 40); self.fs_label.setValue(10)
        self.fs_tick = QtWidgets.QSpinBox(); self.fs_tick.setRange(6, 40); self.fs_tick.setValue(9)
        form.addWidget(self.fs_title, 2, 1); form.addWidget(self.fs_label, 2, 2); form.addWidget(self.fs_tick, 2, 3)
        # 文字サイズ 凡例 / 注記（グラフ上の測定値・統計の注記ボックス）
        form.addWidget(QtWidgets.QLabel("文字サイズ 凡例/注記"), 5, 0)
        self.fs_legend = QtWidgets.QSpinBox(); self.fs_legend.setRange(6, 40); self.fs_legend.setValue(9)
        self.fs_legend.setToolTip("凡例の文字サイズ")
        self.fs_annot = QtWidgets.QSpinBox(); self.fs_annot.setRange(6, 40); self.fs_annot.setValue(9)
        self.fs_annot.setToolTip("グラフ上に表示する注記（統計解析・測定値のチェック表示）の文字サイズ")
        form.addWidget(self.fs_legend, 5, 1); form.addWidget(self.fs_annot, 5, 2)
        # 軸の単位と倍率（単位を変える＝数値も換算）。倍率1・単位空なら無効。
        form.addWidget(QtWidgets.QLabel("X単位"), 3, 0)
        self.xunit_edit = QtWidgets.QLineEdit(); self.xunit_edit.setPlaceholderText("例: ms")
        self.xunit_edit.setToolTip("X軸ラベルに付ける単位。右の倍率で軸の数値も換算されます。")
        form.addWidget(self.xunit_edit, 3, 1)
        form.addWidget(QtWidgets.QLabel("X倍率/式"), 3, 2)
        self.xscale_edit = QtWidgets.QLineEdit("1")
        self.xscale_edit.setToolTip("X軸の数値変換。数値なら倍率（例: 1000）。\n"
                                    "x を使った式も可: x*9/5+32（℃→℉）, 20*log10(x), (x-273.15) など。")
        form.addWidget(self.xscale_edit, 3, 3)
        form.addWidget(QtWidgets.QLabel("Y単位"), 4, 0)
        self.yunit_edit = QtWidgets.QLineEdit(); self.yunit_edit.setPlaceholderText("例: mV")
        self.yunit_edit.setToolTip("Y軸ラベルに付ける単位。右の倍率で軸の数値も換算されます（主軸）。")
        form.addWidget(self.yunit_edit, 4, 1)
        form.addWidget(QtWidgets.QLabel("Y倍率/式"), 4, 2)
        self.yscale_edit = QtWidgets.QLineEdit("1")
        self.yscale_edit.setToolTip("Y軸の数値変換（主軸）。数値なら倍率（例: 1000）。\n"
                                    "y の代わりに x を使った式も可: 20*log10(x), x**2, abs(x) など。")
        form.addWidget(self.yscale_edit, 4, 3)
        sec_labels.set_content_layout(form)
        v.addWidget(sec_labels)

        # オプション行（凡例・グリッド・背景。横に詰めすぎないよう2行に分ける）
        sec_leg = self._fmt_section("凡例・グリッド・背景・枠線", "legend", True)
        leg_v = QtWidgets.QVBoxLayout()
        opt = QtWidgets.QHBoxLayout()
        self.grid_check = QtWidgets.QCheckBox("グリッド"); self.grid_check.setChecked(True)
        self.legend_check = QtWidgets.QCheckBox("凡例"); self.legend_check.setChecked(True)
        opt.addWidget(self.grid_check); opt.addWidget(self.legend_check)
        opt.addWidget(QtWidgets.QLabel("凡例位置"))
        self.legend_loc = QtWidgets.QComboBox(); self.legend_loc.addItems(plotter.LEGEND_LOCS)
        opt.addWidget(self.legend_loc)
        # 凡例の系列名にファイル名を含めるか／拡張子を含めるか（複数ファイル時に有効）
        self.show_filename_check = QtWidgets.QCheckBox("凡例にファイル名"); self.show_filename_check.setChecked(True)
        self.show_filename_check.setToolTip("複数ファイル時、凡例の系列名に『ファイル名 | 列名』のように\n"
                                            "ファイル名を含めます。オフにすると列名だけになります。")
        self.show_ext_check = QtWidgets.QCheckBox("拡張子"); self.show_ext_check.setChecked(True)
        self.show_ext_check.setToolTip("凡例に表示するファイル名に拡張子（.csv など）を含めます。\n"
                                       "オフにすると拡張子を除いた名前になります。")
        opt2 = QtWidgets.QHBoxLayout()
        opt2.addWidget(self.show_filename_check); opt2.addWidget(self.show_ext_check)
        # 背景色（空=自動: 通常は白・オシロは濃色。指定すると両方その色になる）
        self.bg_color = ""
        self.bg_btn = QtWidgets.QPushButton("背景色: 自動")
        self.bg_btn.setToolTip("プロット領域の背景色。クリックで色を選択／右クリックで自動に戻す。\n"
                               "『自動』は通常=白・オシロ=濃色。オシロでも好きな色にできます。")
        self._wire_color_button("bg")
        opt2.addWidget(self.bg_btn)
        opt.addStretch(1); opt2.addStretch(1)
        leg_v.addLayout(opt); leg_v.addLayout(opt2)

        # 線の太さ（枠線＝プロットの外枠／グリッド線）
        lw = QtWidgets.QHBoxLayout()
        lw.addWidget(QtWidgets.QLabel("線の太さ  枠線"))
        self.frame_width = QtWidgets.QDoubleSpinBox()
        self.frame_width.setRange(0.0, 6.0); self.frame_width.setSingleStep(0.2); self.frame_width.setValue(0.8)
        self.frame_width.setToolTip("グラフの外枠（軸の枠線）の太さ。0 で枠を消します。")
        lw.addWidget(self.frame_width)
        lw.addWidget(QtWidgets.QLabel("グリッド線"))
        self.grid_width = QtWidgets.QDoubleSpinBox()
        self.grid_width.setRange(0.2, 6.0); self.grid_width.setSingleStep(0.2); self.grid_width.setValue(0.8)
        self.grid_width.setToolTip("グリッド線の太さ（「グリッド」オン時）。")
        lw.addWidget(self.grid_width)
        lw.addStretch(1)
        leg_v.addLayout(lw)
        sec_leg.set_content_layout(leg_v)
        v.addWidget(sec_leg)

        # 軸範囲・対数
        sec_axis = self._fmt_section("軸範囲・目盛り・対数・反転", "axis", False)
        ax = QtWidgets.QGridLayout()
        ax.addWidget(QtWidgets.QLabel("X範囲 min/max"), 0, 0)
        self.xmin = QtWidgets.QLineEdit(); self.xmin.setPlaceholderText("自動")
        self.xmax = QtWidgets.QLineEdit(); self.xmax.setPlaceholderText("自動")
        ax.addWidget(self.xmin, 0, 1); ax.addWidget(self.xmax, 0, 2)
        self.xlog = QtWidgets.QCheckBox("X対数"); ax.addWidget(self.xlog, 0, 3)
        ax.addWidget(QtWidgets.QLabel("Y範囲 min/max"), 1, 0)
        self.ymin = QtWidgets.QLineEdit(); self.ymin.setPlaceholderText("自動")
        self.ymax = QtWidgets.QLineEdit(); self.ymax.setPlaceholderText("自動")
        ax.addWidget(self.ymin, 1, 1); ax.addWidget(self.ymax, 1, 2)
        self.ylog = QtWidgets.QCheckBox("Y対数"); ax.addWidget(self.ylog, 1, 3)
        # 目盛り間隔（メモリ間隔）。空欄=自動。折れ線/散布図の数値軸で有効（対数軸は除く）
        ax.addWidget(QtWidgets.QLabel("目盛り間隔 X/Y"), 2, 0)
        self.xtick_edit = QtWidgets.QLineEdit(); self.xtick_edit.setPlaceholderText("自動")
        self.xtick_edit.setToolTip("X軸の目盛り間隔（1メモリの値）。空欄=自動。例: 0.5。\n"
                                   "折れ線/散布図の数値軸で有効。対数軸・カテゴリ軸では無効。")
        self.ytick_edit = QtWidgets.QLineEdit(); self.ytick_edit.setPlaceholderText("自動")
        self.ytick_edit.setToolTip("Y軸の目盛り間隔（1メモリの値）。空欄=自動。例: 10。対数軸では無効。")
        ax.addWidget(self.xtick_edit, 2, 1); ax.addWidget(self.ytick_edit, 2, 2)
        # 軸の向き反転（0→1 を 1→0 のように）
        ax.addWidget(QtWidgets.QLabel("軸反転"), 3, 0)
        self.xinvert_check = QtWidgets.QCheckBox("X軸反転")
        self.xinvert_check.setToolTip("X軸の向きを反転します（例: 0→1 を 1→0 に）。")
        self.yinvert_check = QtWidgets.QCheckBox("Y軸反転")
        self.yinvert_check.setToolTip("Y軸の向きを反転します（例: 下→上 を 上→下 に）。")
        ax.addWidget(self.xinvert_check, 3, 1); ax.addWidget(self.yinvert_check, 3, 2)
        sec_axis.set_content_layout(ax)
        v.addWidget(sec_axis)

        # 近似曲線（トレンドライン）・データラベル（折れ線/散布図向け）
        sec_trend = self._fmt_section("近似曲線・データラベル", "trend", False)
        trend_v = QtWidgets.QVBoxLayout()
        tl = QtWidgets.QHBoxLayout()
        tl.addWidget(QtWidgets.QLabel("近似曲線"))
        self.trend_combo = QtWidgets.QComboBox(); self.trend_combo.addItems(plotter.TRENDLINES)
        self.trend_combo.setToolTip("折れ線/散布図の各系列に近似曲線を重ねる")
        tl.addWidget(self.trend_combo)
        tl.addWidget(QtWidgets.QLabel("次数"))
        self.trend_degree = QtWidgets.QSpinBox(); self.trend_degree.setRange(1, 6); self.trend_degree.setValue(2)
        self.trend_degree.setToolTip("多項式近似の次数")
        tl.addWidget(self.trend_degree)
        tl.addWidget(QtWidgets.QLabel("窓"))
        self.trend_window = QtWidgets.QSpinBox(); self.trend_window.setRange(2, 9999); self.trend_window.setValue(5)
        self.trend_window.setToolTip("移動平均の窓幅")
        tl.addWidget(self.trend_window)
        tl2 = QtWidgets.QHBoxLayout()
        # 近似曲線の色（空=自動: 系列と同じ色）。クリックで選択／右クリックで自動に戻す
        self.trend_color = ""
        self.trend_color_btn = QtWidgets.QPushButton("色: 自動")
        self.trend_color_btn.setToolTip("近似曲線の色。クリックで色を選択／右クリックで自動（系列と同じ色）に戻す。")
        self._wire_color_button("trend")
        tl2.addWidget(self.trend_color_btn)
        self.trend_eq = QtWidgets.QCheckBox("数式/R²"); self.trend_eq.setChecked(True)
        tl2.addWidget(self.trend_eq)
        self.data_labels_check = QtWidgets.QCheckBox("データラベル")
        self.data_labels_check.setToolTip("各データ点/棒に値を表示（点数が多い場合は間引き）")
        tl2.addWidget(self.data_labels_check)
        tl.addStretch(1); tl2.addStretch(1)
        trend_v.addLayout(tl); trend_v.addLayout(tl2)
        sec_trend.set_content_layout(trend_v)
        v.addWidget(sec_trend)

        # 系列間の塗りつぶし（2系列の間、または系列とX軸(0)の間を帯で塗る）※折れ線/散布図
        sec_fill = self._fmt_section("系列間の塗りつぶし", "fill", False)
        fill_v = QtWidgets.QVBoxLayout()
        fl_ = QtWidgets.QHBoxLayout()
        self.fill_check = QtWidgets.QCheckBox("系列間を塗りつぶし")
        self.fill_check.setToolTip("2つの系列の間（または系列とX軸=0の間）を色で塗ります。折れ線/散布図で有効。")
        fl_.addWidget(self.fill_check)
        fl_.addWidget(QtWidgets.QLabel("A"))
        self.fill_a = QtWidgets.QComboBox(); fl_.addWidget(self.fill_a, 1)
        fl_.addWidget(QtWidgets.QLabel("B"))
        self.fill_b = QtWidgets.QComboBox(); fl_.addWidget(self.fill_b, 1)
        fl2 = QtWidgets.QHBoxLayout()
        self.fill_color = ""
        self.fill_color_btn = QtWidgets.QPushButton("色: 自動")
        self.fill_color_btn.setToolTip("塗りつぶしの色。クリックで選択／右クリックで自動（系列Aの色）に戻す。")
        self._wire_color_button("fill")
        fl2.addWidget(self.fill_color_btn)
        fl2.addWidget(QtWidgets.QLabel("濃さ"))
        self.fill_alpha = QtWidgets.QDoubleSpinBox()
        self.fill_alpha.setRange(0.05, 1.0); self.fill_alpha.setSingleStep(0.05); self.fill_alpha.setValue(0.3)
        self.fill_alpha.setToolTip("塗りつぶしの不透明度（0.05〜1.0）")
        fl2.addWidget(self.fill_alpha)
        fl2.addStretch(1)
        fill_v.addLayout(fl_); fill_v.addLayout(fl2)
        sec_fill.set_content_layout(fill_v)
        v.addWidget(sec_fill)

        # ビン数・パーセント
        sec_bins = self._fmt_section("ヒストグラム・円のオプション", "bins", False)
        extra = QtWidgets.QHBoxLayout()
        self.bins_caption = QtWidgets.QLabel("ビン数:")
        extra.addWidget(self.bins_caption)
        self.bins_spin = QtWidgets.QSpinBox(); self.bins_spin.setRange(1, 500); self.bins_spin.setValue(30)
        extra.addWidget(self.bins_spin)
        self.pct_check = QtWidgets.QCheckBox("円グラフ％表示"); self.pct_check.setChecked(True)
        extra.addWidget(self.pct_check); extra.addStretch(1)
        sec_bins.set_content_layout(extra)
        v.addWidget(sec_bins)

        # 縦横比（プロット領域のアスペクト比を固定）
        sec_ar = self._fmt_section("縦横比", "aspect", False)
        ar = QtWidgets.QHBoxLayout()
        ar.addWidget(QtWidgets.QLabel("縦横比"))
        self.aspect_combo = QtWidgets.QComboBox()
        self.aspect_combo.addItems(["自動（画面に合わせる）", "16:9", "4:3", "3:2", "1:1",
                                    "9:16（縦）", "A4横", "A4縦", "カスタム"])
        self.aspect_combo.setToolTip("プロット領域の縦横比を固定します（画面表示・画像出力の両方に反映）。"
                                     "「自動」はウィンドウに合わせます。")
        ar.addWidget(self.aspect_combo)
        ar.addWidget(QtWidgets.QLabel("カスタム W:H"))
        self.aspect_w = QtWidgets.QSpinBox(); self.aspect_w.setRange(1, 100); self.aspect_w.setValue(16)
        self.aspect_w.setAccessibleName("縦横比 横")
        self.aspect_h = QtWidgets.QSpinBox(); self.aspect_h.setRange(1, 100); self.aspect_h.setValue(9)
        # 直前のラベルが「:」だけなので、名前を明示しないと索引から漏れる
        self.aspect_h.setAccessibleName("縦横比 縦")
        ar.addWidget(self.aspect_w); ar.addWidget(QtWidgets.QLabel(":")); ar.addWidget(self.aspect_h)
        ar.addStretch(1)
        sec_ar.set_content_layout(ar)
        v.addWidget(sec_ar)
        self.aspect_combo.currentTextChanged.connect(self._on_aspect_changed)
        self._on_aspect_changed()

        # 出力（解像度・背景透過つき画像／Excelレポート）
        sec_exp = self._fmt_section("出力（画像・Excelレポート）", "export", True)
        exp_v = QtWidgets.QVBoxLayout()
        exp = QtWidgets.QHBoxLayout()
        exp.addWidget(QtWidgets.QLabel("解像度 DPI"))
        self.dpi_spin = QtWidgets.QSpinBox()
        self.dpi_spin.setRange(50, 1200); self.dpi_spin.setSingleStep(50); self.dpi_spin.setValue(150)
        exp.addWidget(self.dpi_spin)
        self.transparent_check = QtWidgets.QCheckBox("背景透過")
        exp.addWidget(self.transparent_check)
        exp.addStretch(1)
        exp_v.addLayout(exp)
        exp2 = QtWidgets.QHBoxLayout()
        b_save = QtWidgets.QPushButton("画像を保存...")
        b_save.clicked.connect(self.save_figure)
        b_copy = QtWidgets.QPushButton("クリップボードにコピー")
        b_copy.clicked.connect(self.copy_figure)
        exp2.addWidget(b_save); exp2.addWidget(b_copy)
        exp_v.addLayout(exp2)
        b_batch = QtWidgets.QPushButton("ファイルごとに一括出力...")
        b_batch.setToolTip("読み込んだ各ファイルを、現在の設定（種別・選択列名・スタイル等）で"
                           "個別に描画し、ファイル名ごとの画像として一括保存します。")
        b_batch.clicked.connect(self.batch_export)
        exp_v.addWidget(b_batch)
        b_xlsx = QtWidgets.QPushButton("Excelレポート出力...")
        b_xlsx.setToolTip("現在のグラフ（ネイティブExcelグラフ）とデータ・解析結果の表を\n"
                          "1つのExcelブックに出力します。")
        b_xlsx.clicked.connect(self.export_excel_report)
        exp_v.addWidget(b_xlsx)
        sec_exp.set_content_layout(exp_v)
        v.addWidget(sec_exp)
        v.addStretch(1)   # 余白を下にまとめ、各行の不自然な隙間をなくす
        return w

    # ---- オシロ/解析タブ ----

    # ---- 高度解析タブ ----

    # ---- データサイエンスタブ ----

    def _build_plot_area(self):
        wrap = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(wrap); lay.setContentsMargins(0, 0, 0, 0)
        # 描画コントロール（データの操作ではなく「表示の制御」なのでグラフ直上に常設。
        # どのパネルを開いていても描画・リアルタイム・間引きへ即アクセスできる）
        drawbar = QtWidgets.QHBoxLayout()
        drawbar.setContentsMargins(6, 4, 6, 0)
        b_draw = QtWidgets.QPushButton("グラフを描画 (F5)")
        b_draw.setStyleSheet("font-weight:bold;")
        b_draw.clicked.connect(self.draw_graph)
        self.draw_button = b_draw        # 設定検索・アクセシビリティから参照する
        drawbar.addWidget(b_draw)
        self.live_check = QtWidgets.QCheckBox("リアルタイム更新")
        self.live_check.setChecked(True)
        self.live_check.setToolTip("オンにすると設定変更が自動で描画に反映されます。大容量データではオフ推奨。")
        drawbar.addWidget(self.live_check)
        self.decimate_check = QtWidgets.QCheckBox("間引き表示")
        self.decimate_check.setChecked(True)
        self.decimate_check.setToolTip("折れ線/散布図で点数が多いとき、見た目を保ったまま間引いて高速描画します"
                                       "（ズーム時は自動で再サンプルします）。")
        drawbar.addWidget(self.decimate_check)
        drawbar.addStretch(1)
        b_batch2 = QtWidgets.QPushButton("一括画像保存...")
        b_batch2.setToolTip("読み込んだ各ファイルを個別に描画し、ファイル名ごとの画像として一括保存します"
                            "（タイトル・形式・DPI等は次の画面で調整できます）。")
        b_batch2.clicked.connect(self.batch_export)
        self.batch_button = b_batch2     # 同上
        drawbar.addWidget(b_batch2)
        lay.addLayout(drawbar)
        # グラフ上部の系列ON/OFFバー（折れ線/散布図の表示切替）。
        # 系列が数百・数千になると横スクロールでは探せないので、絞り込み入力を
        # 左に固定し、並べる数には上限を設けて超過分は一覧ダイアログから選ぶ。
        self.series_bar = QtWidgets.QWidget()
        sb_lay = QtWidgets.QHBoxLayout(self.series_bar)
        sb_lay.setContentsMargins(6, 2, 6, 2)
        sb_lay.setSpacing(4)
        self.series_filter = QtWidgets.QLineEdit()
        self.series_filter.setPlaceholderText("系列を絞り込み")
        self.series_filter.setToolTip("入力した文字を含む系列だけをこのバーに表示します。")
        self.series_filter.setAccessibleName("系列の絞り込み")
        self.series_filter.setClearButtonEnabled(True)
        self.series_filter.setFixedWidth(140)
        self.series_filter.textChanged.connect(lambda _t: self._rebuild_series_bar())
        sb_lay.addWidget(self.series_filter)
        self._series_scroll = QtWidgets.QScrollArea()
        self._series_scroll.setWidgetResizable(True)
        self._series_scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self._series_scroll.setHorizontalScrollBarPolicy(
            QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._series_scroll.setVerticalScrollBarPolicy(
            QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        bar_inner = QtWidgets.QWidget()
        self.series_bar_layout = QtWidgets.QHBoxLayout(bar_inner)
        self.series_bar_layout.setContentsMargins(0, 0, 0, 0)
        self._series_scroll.setWidget(bar_inner)
        sb_lay.addWidget(self._series_scroll, 1)
        self.series_more_btn = QtWidgets.QPushButton("他0件…")
        self.series_more_btn.setToolTip("バーに収まらない系列を一覧から選びます。")
        self.series_more_btn.setAccessibleName("残りの系列を一覧から選ぶ")
        self.series_more_btn.clicked.connect(self.show_series_picker)
        self.series_more_btn.setVisible(False)
        sb_lay.addWidget(self.series_more_btn)
        self.series_bar.setFixedHeight(34)
        self.series_bar.setVisible(False)
        lay.addWidget(self.series_bar)

        self.fig = Figure(figsize=(6, 4.4), dpi=100)
        self.ax = self.fig.add_subplot(111)
        self.canvas = FigureCanvas(self.fig)
        self.toolbar = NavigationToolbar(self.canvas, wrap)
        lay.addWidget(self.toolbar)
        lay.addWidget(self.canvas, 1)
        self._plotted_artists = []   # [(label, artist), ...] 系列バー連携用
        self._style_artists = {}     # skey -> Line2D（単純な折れ線のみ：スタイル即時反映用）
        self._drawing = False        # draw_graph 再入防止フラグ
        # オシロ表示のドラッグ操作（パン/スケール）＋ホイール
        self._scope_drag = None
        self._scope_ov = None
        self.canvas.mpl_connect("button_press_event", self._scope_on_press)
        self.canvas.mpl_connect("motion_notify_event", self._scope_on_motion)
        self.canvas.mpl_connect("button_release_event", self._scope_on_release)
        self.canvas.mpl_connect("scroll_event", self._scope_on_scroll)
        self.canvas.mpl_connect("motion_notify_event", self._hover_readout)
        self.canvas.mpl_connect("pick_event", self._on_legend_pick)
        self.canvas.mpl_connect("draw_event", self._invalidate_crosshair)
        self.canvas.mpl_connect("resize_event", self._invalidate_crosshair)
        self.canvas.mpl_connect("figure_leave_event", lambda e: self._hide_hover_ui())
        # ツリーからの系列ドロップ（PlotJuggler風）とファイルドロップを受け付ける
        self.canvas.setAcceptDrops(True)
        app = self

        class _CanvasDrop(QtCore.QObject):
            def eventFilter(self, _obj, ev):
                et = ev.type()
                if et in (QtCore.QEvent.Type.DragEnter, QtCore.QEvent.Type.DragMove):
                    if ev.mimeData().hasFormat(SERIES_MIME) or ev.mimeData().hasUrls():
                        ev.acceptProposedAction()
                        return True
                elif et == QtCore.QEvent.Type.Drop:
                    md = ev.mimeData()
                    if md.hasFormat(SERIES_MIME):
                        app._drop_series(bytes(md.data(SERIES_MIME)).decode("utf-8"))
                        ev.acceptProposedAction()
                        return True
                    if md.hasUrls():          # ファイルはウィンドウ全体と同じ扱い
                        app.dropEvent(ev)
                        return True
                return False

        self._canvas_drop_filter = _CanvasDrop(self.canvas)
        self.canvas.installEventFilter(self._canvas_drop_filter)
        self._draw_placeholder()
        return wrap

    def _rebuild_series_bar(self, chart_type=None):
        """グラフ上部の系列選択バーを作り直す（折れ線/散布図のみ）。

        利用可能な全Y系列をチェックボックスで表示し、ここでON/OFFすると左の
        Y軸選択と同期して描画される。左でチェックしなくても、データを読み込めば
        上のバーに系列が並ぶ（＝上のバーだけで系列を選べる）。"""
        self._sync_explorer_checks()   # 左のツリーもここで色・チェックを同期
        chart_type = chart_type or self.chart_combo.currentText()
        lay = self.series_bar_layout
        while lay.count():
            it = lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        if chart_type not in ("折れ線", "散布図"):
            self.series_bar.setVisible(False)
            return
        items = [self.y_list.item(i) for i in range(self.y_list.count())]
        if not items:
            self.series_bar.setVisible(False)
            return
        # 絞り込み → チェック済みを先に並べる → 上限で打ち切り、の順で選ぶ。
        # チェック済みを優先するのは、今描いている系列こそ切り替えたいため。
        needle = ""
        if hasattr(self, "series_filter"):
            needle = self.series_filter.text().strip().lower()

        def _label_of(it):
            st = self.series_styles.get(self._style_key(*it.data(UserRole))) or {}
            return st.get("label") or it.text()

        matched = [it for it in items if not needle or needle in _label_of(it).lower()]
        checked_first = ([it for it in matched
                          if it.checkState() == QtCore.Qt.CheckState.Checked]
                         + [it for it in matched
                            if it.checkState() != QtCore.Qt.CheckState.Checked])
        shown = checked_first[:SERIES_BAR_MAX]
        hidden = len(checked_first) - len(shown)

        tok = palette_tokens()
        self._series_bar_building = True
        for it in shown:
            st = self.series_styles.get(self._style_key(*it.data(UserRole))) or {}
            checked = it.checkState() == QtCore.Qt.CheckState.Checked
            color = st.get("color") or (tok["fg"] if checked else tok["muted"])
            cb = QtWidgets.QCheckBox(_label_of(it))
            cb.setChecked(checked)
            cb.setToolTip("右クリック=この系列だけ表示／非表示／すべて表示")
            cb.setAccessibleName(f"系列 {_label_of(it)} の表示")
            cb.setStyleSheet(f"QCheckBox {{ color:{color}; "
                             f"font-weight:{'bold' if checked else 'normal'}; }}")
            cb.toggled.connect(lambda on, item=it: self._toggle_series_select(item, on))
            cb.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
            cb.customContextMenuRequested.connect(
                lambda pos, item=it, wdg=cb: self._series_menu(item).exec(wdg.mapToGlobal(pos)))
            lay.addWidget(cb)
        lay.addStretch(1)
        self._series_bar_building = False
        if hasattr(self, "series_more_btn"):
            self.series_more_btn.setText(f"他{hidden}件…")
            self.series_more_btn.setVisible(hidden > 0)
        if needle and not matched:
            self._set_status(f"「{needle}」に一致する系列はありません。")
        self.series_bar.setVisible(True)

    def show_series_picker(self):
        """全系列をチェックリストで選ぶダイアログ（バーに収まらないとき用）。"""
        items = [self.y_list.item(i) for i in range(self.y_list.count())]
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("系列の選択")
        dlg.resize(420, 520)
        lay = QtWidgets.QVBoxLayout(dlg)
        edit = QtWidgets.QLineEdit()
        edit.setPlaceholderText("絞り込み")
        edit.setAccessibleName("系列の絞り込み")
        lay.addWidget(edit)
        lst = QtWidgets.QListWidget()
        lst.setAccessibleName("系列の一覧")
        lay.addWidget(lst, 1)
        rows = []
        for it in items:
            st = self.series_styles.get(self._style_key(*it.data(UserRole))) or {}
            row = QtWidgets.QListWidgetItem(st.get("label") or it.text())
            row.setFlags(row.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
            row.setCheckState(it.checkState())
            lst.addItem(row)
            rows.append((row, it))
        edit.textChanged.connect(lambda t: [
            r.setHidden(bool(t) and t.strip().lower() not in r.text().lower())
            for r, _ in rows])
        btns = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        lay.addWidget(btns)
        self._series_picker = dlg     # テストから参照できるように保持
        if dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            for row, it in rows:
                if row.checkState() != it.checkState():
                    it.setCheckState(row.checkState())

    def _toggle_series_select(self, item, on):
        """系列バーのチェックで左Yリストの選択を切り替える（→自動再描画）。"""
        if getattr(self, "_series_bar_building", False):
            return
        item.setCheckState(QtCore.Qt.CheckState.Checked if on
                           else QtCore.Qt.CheckState.Unchecked)

    def _build_statusbar(self):
        self.status = self.statusBar()
        # マウス近傍のデータ値の常時表示（右端。通常のステータス文言とは独立）
        self._hover_label = QtWidgets.QLabel("")
        self._hover_label.setStyleSheet(f"color:{palette_tokens()['accent']};")
        self._hover_label.setAccessibleName("カーソル位置の値")
        self.status.addPermanentWidget(self._hover_label)
        # 直近メッセージを開くボタン（ステータスの1行は次の表示で消えてしまうため、
        # 「さっき何か出たが読めなかった」を履歴で追えるようにする）
        # 表示レベルの切替（メニューを開かずに増減できるように常設）
        self._level_button = QtWidgets.QToolButton()
        self._level_button.setText(f"表示: {self.ui_level()} ▾")
        self._level_button.setToolTip("画面に出す設定の量を切り替えます。"
                                      "隠れた項目も Ctrl+F で名前を入れれば出てきます。")
        self._level_button.setAccessibleName("表示レベルの切替")
        self._level_button.setPopupMode(
            QtWidgets.QToolButton.ToolButtonPopupMode.InstantPopup)
        lv_menu = QtWidgets.QMenu(self._level_button)
        for lv, act in getattr(self, "_level_actions", {}).items():
            lv_menu.addAction(act)
        self._level_button.setMenu(lv_menu)
        self.status.addPermanentWidget(self._level_button)
        self._msg_button = QtWidgets.QToolButton()
        self._msg_button.setText("履歴")
        self._msg_button.setToolTip("これまでのメッセージ・警告・エラーの一覧を開きます")
        self._msg_button.setAccessibleName("メッセージ履歴を開く")
        self._msg_button.clicked.connect(self.show_message_log)
        self.status.addPermanentWidget(self._msg_button)
        fi = f"日本語: {self.font_name}" if self.font_name else "日本語フォント未検出"
        self.status.addPermanentWidget(QtWidgets.QLabel(fi))

    # ------------------------------------------------------------ 通知と履歴
    # 方針: 告知はモーダルダイアログではなく画面内の通知バーで出す（操作を止めない）。
    # ステータスバーの1行は次のメッセージで消えるので、すべて履歴にも残す。
    def _log_message(self, text, level="info", detail=""):
        """メッセージを履歴に積む（表示は呼び出し側）。"""
        log = getattr(self, "_message_log", None)
        if log is None:
            log = self._message_log = []
        stamp = QtCore.QDateTime.currentDateTime().toString("HH:mm:ss")
        log.append({"time": stamp, "level": level, "text": str(text),
                    "detail": str(detail or "")})
        if len(log) > MESSAGE_LOG_MAX:
            del log[:len(log) - MESSAGE_LOG_MAX]
        logger = applog.get_logger()
        {"error": logger.error, "warn": logger.warning}.get(level, logger.info)(
            "%s%s", text, f" / {detail}" if detail else "")

    def notify(self, text, level="info", detail="", timeout_ms=NOTIFY_MS):
        """画面内の通知バーにメッセージを出す（非モーダル）。

        level: info / ok / warn / error。error は自動で消えない。"""
        bar = getattr(self, "notify_bar", None)
        if bar is not None:
            bar.show_message(text, level, detail, timeout_ms)
        if getattr(self, "status", None) is not None:
            self._set_status(text, level, detail)     # 履歴への記録もここで行う
        else:                                          # 構築途中（ステータスバー未生成）
            self._log_message(text, level, detail)

    def show_message_log(self):
        """メッセージ履歴のウィンドウを開く。"""
        log = getattr(self, "_message_log", None) or []
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("メッセージ履歴")
        dlg.resize(760, 420)
        lay = QtWidgets.QVBoxLayout(dlg)
        table = QtWidgets.QTableWidget(len(log), 3)
        table.setHorizontalHeaderLabels(["時刻", "種別", "内容"])
        table.setAccessibleName("メッセージ履歴")
        table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        names = {"info": "情報", "ok": "完了", "warn": "警告", "error": "エラー"}
        for r, m in enumerate(reversed(log)):     # 新しいものを上に
            body = m["text"] + (f"\n{m['detail']}" if m["detail"] else "")
            for c, v in enumerate((m["time"], names.get(m["level"], m["level"]), body)):
                table.setItem(r, c, QtWidgets.QTableWidgetItem(v))
        table.resizeColumnsToContents()
        table.horizontalHeader().setStretchLastSection(True)
        lay.addWidget(table)
        self._wire_table_export(table, "メッセージ履歴")
        bar = QtWidgets.QHBoxLayout()
        bar.addStretch(1)
        b_clear = QtWidgets.QPushButton("履歴を消去(&C)")
        b_clear.clicked.connect(lambda: (setattr(self, "_message_log", []),
                                         table.setRowCount(0)))
        bar.addWidget(b_clear)
        b_close = QtWidgets.QPushButton("閉じる(&X)")
        b_close.clicked.connect(dlg.accept)
        bar.addWidget(b_close)
        lay.addLayout(bar)
        self._message_log_dialog = dlg    # テストから参照できるように保持
        dlg.exec()

    # ---- 表の右クリック：コピー / CSV保存（結果表を報告に持ち出せるように）----
    def _wire_table_export(self, table, name):
        """表に右クリックメニュー（コピー/CSV保存）を付ける。読み取り専用の結果表向け。"""
        table.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        table.customContextMenuRequested.connect(
            lambda pos, t=table, n=name: self._table_export_menu(t, n, pos))

    def _table_export_menu(self, table, name, pos):
        menu = QtWidgets.QMenu(table)
        if table.selectedIndexes():
            menu.addAction("選択範囲をコピー", lambda: self._copy_table(table, True))
        menu.addAction("表全体をコピー", lambda: self._copy_table(table, False))
        menu.addAction("CSVで保存…", lambda: self._save_table_csv(table, name))
        menu.exec(table.viewport().mapToGlobal(pos))

    @staticmethod
    def _table_rows(table, selected_only):
        """表の内容を [ヘッダ行, データ行...] で返す。セルウィジェット（チェック等）は空欄。"""
        if selected_only and table.selectedIndexes():
            rows = sorted({i.row() for i in table.selectedIndexes()})
            cols = sorted({i.column() for i in table.selectedIndexes()})
        else:
            rows = range(table.rowCount())
            cols = range(table.columnCount())
        def head(c):
            h = table.horizontalHeaderItem(c)
            return h.text() if h is not None else str(c)
        out = [[head(c) for c in cols]]
        for r in rows:
            line = []
            for c in cols:
                it = table.item(r, c)
                line.append(it.text() if it is not None else "")
            out.append(line)
        return out

    def _copy_table(self, table, selected_only):
        rows = self._table_rows(table, selected_only)
        text = "\n".join("\t".join(cells) for cells in rows)
        QtWidgets.QApplication.clipboard().setText(text)
        self._set_status(f"{len(rows) - 1} 行をコピーしました（Excel等にそのまま貼り付け可）。")

    def _save_table_csv(self, table, name):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, f"{name}をCSVで保存", os.path.join(self.last_dir, f"{name}.csv"),
            "CSV (*.csv)")
        if not path:
            return
        import csv
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                csv.writer(f).writerows(self._table_rows(table, False))
            self.last_dir = os.path.dirname(path)
            self._set_status(f"{name}を保存しました: {path}")
        except OSError as e:
            QtWidgets.QMessageBox.critical(self, "保存エラー", str(e))

    @staticmethod
    def _scrollable(w):
        """ウィジェットをスクロールエリアに包む。パネルを狭くしても中身が
        見切れず（スクロールバーが出る）、ドックの最小幅の制約も消える。"""
        sc = QtWidgets.QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        sc.setWidget(w)
        return sc

    @staticmethod
    def _bold(text):
        """パネル内の見出しラベル。

        section_header プロパティを立てておくと、設定検索の索引が
        「ここから下は別セクション」と解釈して名前に階層を付けられる
        （CollapsibleBox に作り替えなくてもセクション名が付く）。"""
        l = QtWidgets.QLabel(text)
        f = l.font(); f.setBold(True); l.setFont(f)
        l.setProperty("section_header", True)
        l.setWordWrap(True)
        return l

    @staticmethod
    def _hline():
        ln = QtWidgets.QFrame()
        ln.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        ln.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
        return ln

    # ------------------------------------------------------------ ライブ更新
    def _wire_live_signals(self):
        """各コントロールの変更を（リアルタイム更新ON時に）自動再描画へつなぐ。"""
        r = self._request_redraw
        self.chart_combo.currentTextChanged.connect(r)
        for e in (self.title_edit, self.xlabel_edit, self.ylabel_edit,
                  self.xunit_edit, self.yunit_edit, self.xscale_edit, self.yscale_edit):
            e.textChanged.connect(r)
        for s in (self.fs_title, self.fs_label, self.fs_tick, self.fs_legend, self.fs_annot,
                  self.bins_spin, self.frame_width, self.grid_width):
            s.valueChanged.connect(r)
        for c in (self.grid_check, self.legend_check, self.pct_check,
                  self.xlog, self.ylog, self.show_filename_check, self.show_ext_check,
                  self.xinvert_check, self.yinvert_check, self.stack_check):
            c.toggled.connect(r)
        self.legend_loc.currentTextChanged.connect(r)
        # 近似曲線・データラベル
        self.trend_combo.currentTextChanged.connect(r)
        for s in (self.trend_degree, self.trend_window):
            s.valueChanged.connect(r)
        for c in (self.trend_eq, self.data_labels_check, self.fill_check):
            c.toggled.connect(r)
        self.fill_a.currentTextChanged.connect(r)
        self.fill_b.currentTextChanged.connect(r)
        self.fill_alpha.valueChanged.connect(r)
        # 縦横比（コンボは _on_aspect_changed 経由で再描画。W/H は直接）
        for s in (self.aspect_w, self.aspect_h):
            s.valueChanged.connect(r)
        for le in (self.xmin, self.xmax, self.ymin, self.ymax,
                   self.xtick_edit, self.ytick_edit):
            le.editingFinished.connect(r)
        # オシロのつまみ
        self.scope_check.toggled.connect(r)
        for cb in (self.tdiv, self.vdiv):
            cb.currentTextChanged.connect(r)
        for le in (self.xpos, self.ypos):
            le.editingFinished.connect(r)
        for s in (self.xdivs, self.ydivs):
            s.valueChanged.connect(r)
        self.show_peaks_check.toggled.connect(r)
        self.npeaks.valueChanged.connect(r)
        self.smooth_spin.valueChanged.connect(r)

    def _add_tooltips(self):
        tips = {
            self.legend_loc: "凡例の表示位置",
            self.xlog: "X軸を対数目盛に（0以下の値は表示できません）",
            self.ylog: "Y軸を対数目盛に（0以下の値は表示できません）",
            self.bins_spin: "ヒストグラムの区間数（ヒストグラム選択時のみ有効）",
            self.pct_check: "円グラフでパーセント表示（円グラフ選択時のみ有効）",
            self.xmin: "X軸の最小値。空欄で自動。指数表記(1e-3)も可",
            self.xmax: "X軸の最大値。空欄で自動",
            self.ymin: "Y軸の最小値。空欄で自動", self.ymax: "Y軸の最大値。空欄で自動",
            self.dpi_spin: "保存画像の解像度。印刷向けは300以上",
            self.transparent_check: "保存時に背景を透明にします（PNG/PDF/SVG）",
            self.analysis_target: "解析するY系列。データタブでY系列を選ぶと候補に出ます",
            self.npeaks: "検出するピークの個数（第1〜第N）",
            self.show_peaks_check: "検出ピークを折れ線/散布図に重ねて表示",
            self.scope_check: "オシロスコープ風のdiv表示（折れ線/散布図）",
            self.tdiv: "1目盛りあたりの時間。1e-3 のような指数表記も可",
            self.vdiv: "1目盛りあたりの値。1e-3 のような指数表記も可",
            self.xpos: "表示の中心時間", self.ypos: "表示の中心値",
        }
        for w, t in tips.items():
            w.setToolTip(t)

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
        self._sync_3d_checkbox(info)     # 『3D表示』チェックの有効/固定を種別に合わせる
        self._update_x_combo_enabled()
        self._update_z_combo_enabled()   # Z軸コンボは3D表示中のみ有効
        self._update_x_multi_enabled()   # 複数X は 2D xy 種別のみ
        if hasattr(self, "swap_xy_check"):
            self.swap_xy_check.setEnabled(ctype in plotter._SWAP_TYPES)
        uses_bins = ctype in ("ヒストグラム", "2Dヒストグラム", "hexbin")
        self.bins_spin.setEnabled(uses_bins)
        self.bins_caption.setEnabled(uses_bins)
        self.pct_check.setEnabled(ctype in ("円", "ドーナツ"))
        want3d = self._want_3d()
        if hasattr(self, "elev_spin"):   # 視点角度は3D表示中のみ操作可
            self.elev_spin.setEnabled(want3d); self.azim_spin.setEnabled(want3d)
        # この種別で効かない書式はグレーアウトして迷いを減らす（設定値は保持される）
        if hasattr(self, "trend_combo"):
            xy_ok = (ctype in plotter._XY_TYPES) and not want3d   # 近似曲線は2DのXY系のみ
            for w_ in (self.trend_combo, self.trend_degree, self.trend_window,
                       self.trend_color_btn, self.trend_eq):
                w_.setEnabled(xy_ok)
        if hasattr(self, "fill_check"):
            fill_ok = ctype in ("折れ線", "散布図") and not want3d
            for w_ in (self.fill_check, self.fill_a, self.fill_b,
                       self.fill_color_btn, self.fill_alpha):
                w_.setEnabled(fill_ok)
        if hasattr(self, "data_labels_check"):   # データラベルはXY系・棒系・3Dで有効
            self.data_labels_check.setEnabled(
                ctype in plotter._XY_TYPES
                or ctype in ("棒", "横棒", "積み上げ棒") or want3d)
        if hasattr(self, "stack_check"):   # 段分けは折れ線/散布図の2Dのみ
            self.stack_check.setEnabled(ctype in ("折れ線", "散布図") and not want3d)
        if hasattr(self, "series_bar"):
            self._rebuild_series_bar(ctype)   # 折れ線/散布図でのみ上部バーを出す

    def _sync_3d_checkbox(self, info):
        """『3D表示』チェックの有効状態を種別に合わせる（このメソッドは再描画しない）。
        optional(散布図/折れ線/棒): 有効・ユーザーのON/OFFを保持／
        always(曲面): ON固定で無効／非対応: OFF固定で無効。"""
        if not hasattr(self, "threed_check"):
            return
        d3 = info.get("dim3")
        self.threed_check.blockSignals(True)
        if d3 == "always":
            self.threed_check.setChecked(True); self.threed_check.setEnabled(False)
        elif d3 == "optional":
            self.threed_check.setEnabled(True)     # 現在のチェック状態を保持
        else:
            self.threed_check.setChecked(False); self.threed_check.setEnabled(False)
        self.threed_check.blockSignals(False)

    def _on_3d_toggled(self, *_):
        """『3D表示』チェックの切替: Z軸・視点角度・書式の有効状態を更新して再描画する。"""
        self._update_z_combo_enabled()
        self._update_x_multi_enabled()   # 3D中は複数X不可
        self._on_chart_type_change()     # 視点角度・近似曲線などの有効/無効を3D状態に合わせる
        self._request_redraw()

    def _on_multix_toggled(self, *_):
        """『X軸を複数選択』の切替: 複数XリストのON/OFFを更新して再描画する。"""
        self._update_x_multi_enabled()
        self._request_redraw()

    def _build_series(self, chart_type):
        items = self._selected_series_items()
        if not items:
            raise ValueError("Y軸（値）の系列を選択してください。")
        xname = self.x_combo.currentText()
        categories = None
        series = []

        def lbl(fl, col, disp, default):
            st = self.series_styles.get(self._style_key(fl, col)) or {}
            return st.get("label") or default

        if self._want_3d():
            # 3D表示中: 種別（散布図/折れ線/棒/曲面）に関わらず (x, y, z) 系列を作る。
            # X（x_combo）と Z（z_combo）は共有座標。チェックした各Y列を1系列にする。
            for fl, col, disp in items:
                df = self.datasets[fl]
                stmap = self.series_styles.get(self._style_key(fl, col)) or {}
                series.append({"label": self._series_label(fl, col),
                               "x": self._x_values(df), "y": df[col].to_numpy(),
                               "z": self._z_values(df), "style": stmap,
                               "kind": stmap.get("kind", "")})
        elif chart_type in ("棒", "横棒", "積み上げ棒", "円", "ドーナツ"):
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
            xcols = self._selected_x_columns()          # 複数Xなら各Xごとに系列を作る
            multi_x = len(xcols) > 1
            for fl, col, disp in items:
                df = self.datasets[fl]
                stmap = self.series_styles.get(self._style_key(fl, col)) or {}
                errcol = stmap.get("errcol")
                yerr = df[errcol].to_numpy() if (errcol and errcol in df.columns) else None
                for xname_i in xcols:
                    lab = self._series_label(fl, col)
                    st_i = stmap
                    if multi_x:                          # どのXかを凡例に付ける
                        xdisp = str(df.columns[0]) if xname_i is None else xname_i
                        lab = f"{lab} [X:{xdisp}]"
                        if stmap.get("color"):           # 変種ごとに色を分ける（自動色に）
                            st_i = dict(stmap); st_i.pop("color", None)
                    series.append({"label": lab, "x": self._x_values(df, xname_i),
                                   "y": df[col].to_numpy(), "style": st_i,
                                   "axis": st_i.get("axis", "primary"),
                                   "kind": st_i.get("kind", ""),
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

    def _view_angles(self):
        """3Dグラフの視点角度 (仰角 elev, 方位 azim)。UI が無ければ既定値。"""
        elev = self.elev_spin.value() if hasattr(self, "elev_spin") else 30
        azim = self.azim_spin.value() if hasattr(self, "azim_spin") else -60
        return (elev, azim)

    def _on_view_angle_changed(self, *_):
        """仰角・方位スピンの変更を、再描画せず視点だけ更新して反映する。"""
        if self._is_3d() and getattr(self, "_has_drawn", False):
            try:
                self.ax.view_init(elev=self.elev_spin.value(),
                                  azim=self.azim_spin.value())
                self.canvas.draw_idle()
            except Exception:
                applog.get_logger().debug("_on_view_angle_changed: 無視した例外", exc_info=True)

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
        if self._is_3d():
            return   # 3D軸の box_aspect は3要素タプル。スカラー比率は適用しない
        ratio = self._aspect_ratio()
        try:
            self.ax.set_box_aspect(ratio)
            ax2 = getattr(self.ax, "_twin_secondary", None)
            if ax2 is not None:
                ax2.set_box_aspect(ratio)
        except Exception:
            applog.get_logger().debug("_apply_aspect: 無視した例外", exc_info=True)

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
            bg_color=self._effective_bg_color(),   # 未指定ならウィンドウの配色に追従
            grid_width=self.grid_width.value(),
            frame_width=self.frame_width.value(),
            xinvert=self.xinvert_check.isChecked(),
            yinvert=self.yinvert_check.isChecked(),
            swap_xy=(self.swap_xy_check.isChecked()
                     if hasattr(self, "swap_xy_check") else False),
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

    def _confirm_heavy_draw(self, n):
        """系列が極端に多いときだけ、描画前に一度だけ確認する。

        数百系列を一度に描くと凡例とレイアウト計算でウィンドウが数十秒固まる
        （前回セッションの復元でこの状態のまま起動して操作不能になり得る）。
        承諾は同一セッション内で覚えるので、リアルタイム更新中に何度も
        聞かれることはない。"""
        if n <= HEAVY_SERIES or getattr(self, "_heavy_draw_ok", False):
            return True
        ret = QtWidgets.QMessageBox.question(
            self, "系列数の確認",
            f"{n} 系列を一度に描画します。表示が終わるまで時間がかかり、"
            f"操作できなくなることがあります。\n\n続けますか？"
            f"\n（{HEAVY_SERIES} 系列以下に減らすと快適に操作できます）")
        if ret == QtWidgets.QMessageBox.StandardButton.Yes:
            self._heavy_draw_ok = True
            return True
        return False

    def _draw_graph_body(self):
        if not self.datasets:
            self.notify("先にファイルを追加してください。", "warn")
            return
        # Y系列未選択は正常な一時状態。エラーのポップアップは出さず、空表示＋案内のみ。
        selected = self._selected_series_items()
        if not selected:
            self._draw_placeholder()
            self._rebuild_series_bar(self.chart_combo.currentText())
            self._set_status("Y軸（値）の系列をチェックするとグラフを表示します。")
            return
        if not self._confirm_heavy_draw(len(selected)):
            self._draw_placeholder()
            self._rebuild_series_bar(self.chart_combo.currentText())
            self.notify(f"描画を中止しました（{len(selected)} 系列）。"
                        "系列バーの絞り込みでチェックを減らせます。", "warn")
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

        self._ensure_axes_projection(self._want_3d())  # 3D⇔2D 軸を用意
        self._clear_dynamic_resample()
        self._reset_figure_axes()   # スペクトログラム等のカラーバー軸を除去
        self._cursor_pts = []; self._cursor_artists = []  # 再描画で軸がクリアされる
        self._cursors = []; self._cursor_drag = None; self._cursor_text = None
        self._link_artists = []   # リンク選択のリング強調も軸クリアで消える
        try:
            # FFT表示ON: 時間→周波数ドメインへ全系列を切り替える持続表示。
            # 単位変換と同じく、ONの間は再描画してもこの表示が続く（時間ドメインは描かない）。
            if self._tab_hook("_fft_mode_on", default=False):
                self._ensure_axes_projection(False)   # FFTは2D（3D選択中でも2Dへ戻す）
                self._reset_figure_axes()
                self._tab_hook("_draw_fft_view")
                self._rebuild_series_bar(ctype)
                self._plotted_artists = [(ln.get_label(), ln) for ln in self.ax.get_lines()]
                self._has_drawn = True
                self._snapshot()
                return
            series, categories = self._build_series(ctype)
            swap_on = (getattr(self, "swap_xy_check", None) and self.swap_xy_check.isChecked()
                       and ctype in plotter._SWAP_TYPES)
            # 入れ替え中は、その列が乗る軸名でメッセージを出す（元Yは横軸へ）
            yn, xn = ("X", "Y") if swap_on else ("Y", "X")
            if self.ylog.isChecked() and self._has_nonpositive([s["y"] for s in series]):
                issues.append(f"{yn}対数: 0以下の値は表示されません")
            if (self.xlog.isChecked() and ctype in ("折れ線", "散布図")
                    and self._has_nonpositive([s.get("x") for s in series])):
                issues.append(f"{xn}対数: 0以下の値は表示されません")

            # 大容量データの間引き（折れ線/散布図のみ）
            total = sum(len(s.get("y", [])) for s in series)
            max_points = (DECIMATE_TARGET if (self.decimate_check.isChecked()
                          and ctype in ("折れ線", "散布図") and total > DECIMATE_TARGET) else 0)

            # 系列ごとに段を分ける（サブプロット）モード。オシロ・3D・多すぎる系列は通常表示
            stack_now = (getattr(self, "stack_check", None) is not None
                         and self.stack_check.isChecked()
                         and ctype in ("折れ線", "散布図")
                         and not self._want_3d()
                         and not scope["enabled"])
            if stack_now and len(series) > 8:
                issues.append("段分け表示は8系列まで（9系列以上は通常表示に切替）")
                stack_now = False
            if stack_now:
                self._draw_stacked(series, ctype, xlim, ylim, max_points)
                self._rebuild_series_bar(ctype)
                self._has_drawn = True
                self._snapshot()
                msg = f"「{ctype}」を{len(series)}段に分けて描画しました。"
                if issues:
                    msg += "  ⚠ " + " / ".join(issues)
                self._set_status(msg)
                return

            busy = total > BUSY_ROWS
            if busy:
                QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
                self._set_status(f"描画中…（{total:,} 点）"); QtWidgets.QApplication.processEvents()
            try:
                markers = self._tab_hook("_peak_markers") if self.show_peaks_check.isChecked() else None
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
                    zlabel=(self.z_combo.currentText() if self._want_3d() else ""),
                    view_init=(self._view_angles() if self._want_3d() else None),
                    threed=self._want_3d(),
                    **self._plot_format_kwargs(),
                )
                self._apply_aspect()   # 縦横比の固定（自動なら解除）
                self._apply_tick_spacing(ctype, scope)   # 目盛り間隔（指定時）
                self._apply_fill_between(ctype, series)   # 系列間の塗りつぶし（選択時）
                self._tab_hook("_draw_ds_annotations")   # データサイエンス注記（該当タブがあれば）
                self._tab_hook("_draw_proto_overlay", ctype)  # プロトコル解読の波形上注記
                self._draw_plugin_overlays()   # 差し込みタブのオーバーレイ（コア無改変の拡張口）
                # 地色が暗いときは目盛り・軸ラベル・凡例の文字色も明るくする
                # （plot_series は地色しか塗らないので、ここで対比を確保する）
                self._apply_figure_theme(redraw=False)
                try:
                    self.fig.tight_layout()
                except Exception:
                    applog.get_logger().debug("_draw_graph_body: 無視した例外", exc_info=True)
                self.canvas.draw()
            finally:
                if busy:
                    QtWidgets.QApplication.restoreOverrideCursor()

            if max_points and not swap_on:
                # 入れ替え中は series が転置前のためズーム再サンプルが不整合になる。無効化。
                self._setup_dynamic_resample(series, ctype, max_points)
            self._rebuild_series_bar(ctype)   # グラフ上部の系列選択バー
            # カーソル追従用に、実際に描画されたデータ線を保持（近似曲線は除く）
            self._plotted_artists = [
                (ln.get_label(), ln) for ln in self.ax.get_lines()
                if "近似" not in str(ln.get_label())]
            # スタイルのみ変更を即時反映するための skey->Line2D マップ（安全な場合のみ）
            self._style_artists = self._build_style_artist_map(series, ctype, bool(max_points))
            self._wire_legend_picking()   # 凡例クリックで系列ON/OFF
            self._tab_hook("_regate")     # 区間測定ON中は選択機構を作り直す
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

    def open_graph_window(self):
        """現在のグラフを独立ウィンドウとして複製する。

        何枚でも開けるので、選択・書式を変えながら複数のグラフを並べて比較できる。
        各ウィンドウは自分のズームツールバーを持ち、「現在の設定で更新」で
        メイン画面のいまの選択・書式を使って描き直せる。"""
        if not self.datasets or not self._selected_series_items():
            self.notify("先にY系列を選択してください。", "warn")
            return
        dlg = QtWidgets.QDialog(self)
        # 通常ウィンドウ扱いにして、Windowsのスナップ（画面端ドラッグ・
        # 最大化ボタンhoverのレイアウト選択・Win+矢印）を効かせる
        dlg.setWindowFlags(QtCore.Qt.WindowType.Window)
        n = len(getattr(self, "_graph_windows", [])) + 1
        title = self.title_edit.text() or self.chart_combo.currentText()
        dlg.setWindowTitle(f"グラフ {n}: {title}")
        dlg.resize(760, 540)
        v = QtWidgets.QVBoxLayout(dlg)
        fig = Figure(figsize=(6, 4), dpi=100)
        canvas = FigureCanvas(fig)
        tb = NavigationToolbar(canvas, dlg)
        v.addWidget(tb)
        v.addWidget(canvas, 1)
        brow = QtWidgets.QHBoxLayout()
        b_upd = QtWidgets.QPushButton("現在の設定で更新")
        b_upd.setToolTip("メイン画面のいまの系列選択・書式でこのウィンドウを描き直します。")
        brow.addWidget(b_upd)
        brow.addStretch(1)
        v.addLayout(brow)

        def render():
            try:
                ctype = self.chart_combo.currentText()
                series, categories = self._build_series(ctype)
                fig.clf()
                if self._want_3d():
                    from mpl_toolkits.mplot3d import Axes3D  # noqa: F401
                    ax = fig.add_subplot(111, projection="3d")
                else:
                    ax = fig.add_subplot(111)
                ax._twin_secondary = None
                plotter.plot_series(
                    ax, series, ctype, categories=categories,
                    title=self.title_edit.text(),
                    xlabel=self.xlabel_edit.text() or self._effective_x_label(),
                    ylabel=self.ylabel_edit.text() or self._effective_y_label(),
                    xlim=self._range_pair(self.xmin, self.xmax, "X", []),
                    ylim=self._range_pair(self.ymin, self.ymax, "Y", []),
                    scope=None, markers=None, max_points=DECIMATE_TARGET,
                    secondary_label="",
                    zlabel=(self.z_combo.currentText() if self._want_3d() else ""),
                    view_init=(self._view_angles() if self._want_3d() else None),
                    threed=self._want_3d(),
                    **self._plot_format_kwargs())
                dlg.setWindowTitle(f"グラフ {n}: "
                                   f"{self.title_edit.text() or self.chart_combo.currentText()}")
                try:
                    fig.tight_layout()
                except Exception:
                    applog.get_logger().debug("render: 無視した例外", exc_info=True)
                canvas.draw()
            except Exception as e:  # noqa: BLE001
                QtWidgets.QMessageBox.critical(dlg, "描画エラー", str(e))

        b_upd.clicked.connect(render)
        render()
        if not hasattr(self, "_graph_windows"):
            self._graph_windows = []
        self._graph_windows.append(dlg)
        dlg.finished.connect(lambda *_: self._graph_windows.remove(dlg)
                             if dlg in self._graph_windows else None)
        dlg.show()
        self._set_status(f"グラフウィンドウ {n} を開きました"
                         "（メイン画面で選択・書式を変えて複数枚並べられます）。")

    def _draw_stacked(self, series, ctype, xlim, ylim, max_points):
        """系列ごとに上下の段（サブプロット・X軸共有）へ分けて描画する。

        各段のY軸ラベルに系列名を使うので凡例は出さない。第2軸・塗りつぶし・
        動的リサンプル・スタイル即時反映は段分け中は使わない（通常描画に任せる）。"""
        self._clear_dynamic_resample()
        for a in list(self.fig.axes):
            try:
                a.remove()
            except Exception:
                applog.get_logger().debug("_draw_stacked: 無視した例外", exc_info=True)
        n = len(series)
        axes = self.fig.subplots(n, 1, sharex=True)
        if n == 1:
            axes = [axes]
        kw = self._plot_format_kwargs()
        kw["legend"] = False
        xlabel = self.xlabel_edit.text() or self._effective_x_label()
        for i, (ax, s) in enumerate(zip(axes, series)):
            s2 = dict(s)
            s2["axis"] = "primary"   # 段分け中は各段が独立軸なので第2軸は使わない
            st = s.get("style") or {}
            plotter.plot_series(
                ax, [s2], ctype,
                title=(self.title_edit.text() if i == 0 else ""),
                xlabel=(xlabel if i == n - 1 else ""),
                ylabel=str(st.get("label") or s.get("label") or ""),
                xlim=xlim, ylim=ylim,
                scope=None, markers=None, max_points=max_points,
                secondary_label="", threed=False, **kw)
            ax._twin_secondary = None
        self.ax = axes[-1]   # 以降の操作（区間測定・注記等）は最下段を基準にする
        self._tab_hook("_draw_ds_annotations")
        self._apply_figure_theme(redraw=False)   # 段分けでも全段の文字色を地色に合わせる
        try:
            self.fig.tight_layout()
        except Exception:
            applog.get_logger().debug("_draw_stacked: 無視した例外", exc_info=True)
        self.canvas.draw()
        self._plotted_artists = [(ln.get_label(), ln) for a in axes for ln in a.get_lines()
                                 if "近似" not in str(ln.get_label())]
        self._style_artists = {}      # スタイル即時反映は無効（全再描画へフォールバック）
        self._legend_pick_map = {}
        self._tab_hook("_regate")
        self._stacked = True

    def _draw_proto_overlay(self, ctype):
        """プロトコル解読イベントを波形の上部に注記する（Saleae風・最大80件）。

        値（hex）を交互の高さの小さなボックスで並べ、イベント位置に薄い縦線を引く。
        ⚠付き（CRC/パリティ等の不一致）は赤で表示する。"""
        info = getattr(self, "_proto_annotations", None)
        chk = getattr(self, "proto_overlay_check", None)
        if (not info or not info.get("rows") or chk is None or not chk.isChecked()
                or self._is_3d() or getattr(self, "_stacked", False)
                or ctype not in ("折れ線", "散布図")
                or (getattr(self, "swap_xy_check", None)
                    and self.swap_xy_check.isChecked())):
            return
        import numpy as np
        from matplotlib import transforms as mtrans
        from matplotlib.lines import Line2D
        rows = info["rows"][:80]
        xs = mathchan.axis_scale(np.array([r[0] for r in rows], dtype=float),
                                 self.xscale_edit.text())
        trans = mtrans.blended_transform_factory(self.ax.transData, self.ax.transAxes)
        fs = max((self.fs_annot.value() if hasattr(self, "fs_annot") else 9) - 1, 6)
        marker_kinds = {"START", "STOP", "BREAK", "SYNC", "RESET", "PRESENCE"}
        for i, ((_tm, kind, hexv, note), x) in enumerate(zip(rows, xs)):
            warn = "⚠" in str(note)
            color = ("#d02020" if warn
                     else "#0a7a55" if str(kind) in marker_kinds else "#2b6cb0")
            label = str(hexv) if str(hexv) else str(kind)
            ytxt = 0.99 if i % 2 == 0 else 0.92   # 交互に段をずらして重なりを軽減
            self.ax.text(x, ytxt, label, transform=trans, ha="center", va="top",
                         fontsize=fs, color=color, zorder=25, clip_on=True,
                         bbox=dict(facecolor="white", alpha=0.78,
                                   edgecolor=color, lw=0.5, pad=1.2))
            self.ax.add_line(Line2D([x, x], [0.0, 0.86], transform=trans,
                                    color=color, lw=0.6, alpha=0.35, zorder=24))
        if len(info["rows"]) > 80:
            self.ax.text(0.99, 0.84, f"解読 {len(info['rows'])}件中 先頭80件を注記",
                         transform=self.ax.transAxes, ha="right", va="top",
                         fontsize=fs, color="#666", zorder=25)

    def _wire_legend_picking(self):
        """凡例の項目（線・文字）をクリックすると系列の表示/非表示が切り替わるようにする。
        凡例ラベル→(ファイル, 列) の対応が取れた項目だけ有効（複数X時の変種などは対象外）。"""
        self._legend_pick_map = {}
        leg = self.ax.get_legend()
        if leg is None:
            return
        label_map = {}
        for fl, col, _disp in self._selected_series_items():
            st = self.series_styles.get(self._style_key(fl, col)) or {}
            for k in {self._series_label(fl, col), st.get("label") or str(col)}:
                label_map[k] = (fl, col)
        handles = getattr(leg, "legend_handles", None) or getattr(leg, "legendHandles", [])
        for h, t in zip(handles, leg.get_texts()):
            key = label_map.get(t.get_text())
            if key is None:
                continue
            for art in (h, t):
                try:
                    art.set_picker(6)
                    self._legend_pick_map[art] = key
                except Exception:
                    applog.get_logger().debug("_wire_legend_picking: 無視した例外", exc_info=True)
        # データ線のクリック → プレビュー表の行を選択（JMP風リンク選択）。
        # skey→Line2D の即時反映マップがある単純な折れ線のみ（間引き時は行対応が崩れるため無効）
        self._line_pick_map = {}
        for skey, ln in (self._style_artists or {}).items():
            try:
                ln.set_picker(5)
                self._line_pick_map[ln] = skey
            except Exception:
                applog.get_logger().debug("_wire_legend_picking: 無視した例外", exc_info=True)

    def _on_legend_pick(self, event):
        key = getattr(self, "_legend_pick_map", {}).get(event.artist)
        if key is not None:
            yit = self._find_y_item(*key)
            if yit is not None:
                ck = QtCore.Qt.CheckState.Checked
                yit.setCheckState(QtCore.Qt.CheckState.Unchecked
                                  if yit.checkState() == ck else ck)
            return
    def _apply_tick_spacing(self, ctype, scope):
        """目盛り間隔（メモリ間隔）の手動指定を適用する。
        空欄や非対応（オシロdiv表示中・対数軸・カテゴリ軸・円・3D）では何もしない。"""
        if ctype == "円" or self._is_3d():
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
                    applog.get_logger().debug("_apply_tick_spacing: 無視した例外", exc_info=True)
        if dy and dy > 0 and self.ax.get_yscale() != "log":
            y0, y1 = self.ax.get_ylim()
            if not _too_many(y0, y1, dy):
                try:
                    self.ax.yaxis.set_major_locator(MultipleLocator(dy))
                except Exception:
                    applog.get_logger().debug("_apply_tick_spacing: 無視した例外", exc_info=True)

    def _apply_fill_between(self, ctype, series):
        """系列A と 系列B（または X軸=0）の間を塗りつぶす。折れ線/散布図のみ。
        描画は単位換算後の座標に合わせる（B が異なるXでも A の X に補間）。"""
        if not getattr(self, "fill_check", None) or not self.fill_check.isChecked():
            return
        if ctype not in ("折れ線", "散布図") or not series:
            return
        # X↔Y入れ替え中は座標が転置されるため塗りつぶしは無効（対応が取れない）
        if getattr(self, "swap_xy_check", None) and self.swap_xy_check.isChecked():
            self._set_status("塗りつぶし: X↔Y入れ替え中は無効です。")
            return
        import numpy as np
        import pandas as pd
        items = self._selected_series_items()
        # 複数X時は系列数(N_x×N_y)と選択数(N_y)がずれ、名前で系列を一意に選べないため無効
        if len(series) != len(items):
            self._set_status("塗りつぶし: X軸を複数選択中は無効です。")
            return
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
            applog.get_logger().debug("_apply_fill_between: 無視した例外", exc_info=True)

    def _draw_ds_annotations(self):
        """『表示』にチェックした指標をグラフへ注記する。
        データサイエンス＝左上、オシロ/解析の測定値＝右上に分けて描く。"""
        if self._is_3d():
            return   # 3D軸では transAxes 注記が正しく置けないため出さない
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
            applog.get_logger().debug("_draw_annotation_box: 無視した例外", exc_info=True)

    def _reset_figure_axes(self):
        """メイン軸以外（カラーバー等）を図から取り除く。"""
        for a in list(self.fig.axes):
            if a is not self.ax:
                try:
                    a.remove()
                except Exception:
                    applog.get_logger().debug("_reset_figure_axes: 無視した例外", exc_info=True)
        # 系列選択バーの表示/非表示は _rebuild_series_bar が管理する（ここでは触らない）

    def _is_3d(self):
        """現在のメイン軸が 3D（projection='3d'）かどうか（軸の実状態）。"""
        return getattr(getattr(self, "ax", None), "name", None) == "3d"

    def _want_3d(self):
        """いま3Dで描くべきか（GUIの明示指定）。表示名の文字列一致では判断しない。

        『常に3D』の種別（曲面）は常に True、『3D対応』の種別（散布図/折れ線/棒）は
        『3D表示』チェックの状態、それ以外は False。"""
        info = plotter.CHART_INFO.get(self.chart_combo.currentText(), {})
        d3 = info.get("dim3")
        if d3 == "always":
            return True
        if d3 == "optional":
            return bool(getattr(self, "threed_check", None)
                        and self.threed_check.isChecked())
        return False

    def _ensure_axes_projection(self, want_3d):
        """メイン軸を 2D↔3D で必要なときだけ差し替える。

        2D 前提のイベント接続はキャンバス側にあり軸差し替えの影響を受けないが、
        軸に紐づくコールバック（動的リサンプル）や描画キャッシュは張り替える。"""
        cur = getattr(self, "ax", None)
        if getattr(self, "_stacked", False):
            self._stacked = False
            cur = None   # 段分け（複数軸）から戻るときは単一軸を作り直す
        if cur is not None and bool(want_3d) == (getattr(cur, "name", None) == "3d"):
            return   # 既に目的の投影。差し替え不要（clear で再利用）
        self._clear_dynamic_resample()          # 旧軸の xlim コールバックを外す
        for a in list(self.fig.axes):           # 旧軸・残ったカラーバー等を一掃
            try:
                a.remove()
            except Exception:
                applog.get_logger().debug("_ensure_axes_projection: 無視した例外", exc_info=True)
        if want_3d:
            from mpl_toolkits.mplot3d import Axes3D  # noqa: F401  '3d' 投影を登録
            self.ax = self.fig.add_subplot(111, projection="3d")
        else:
            self.ax = self.fig.add_subplot(111)
        self.ax._twin_secondary = None
        # 旧軸を指していたキャッシュ参照をリセット
        self._plotted_artists = []
        self._style_artists = {}
        self._cursor_pts = []; self._cursor_artists = []
        self._cursors = []; self._cursor_drag = None; self._cursor_text = None
        self._dyn = []; self._dyn_cid = None

    # ------------------------------------------------------------ ズーム再サンプル
    def _clear_dynamic_resample(self):
        if self._dyn_cid is not None:
            try:
                self.ax.callbacks.disconnect(self._dyn_cid)
            except Exception:
                applog.get_logger().debug("_clear_dynamic_resample: 無視した例外", exc_info=True)
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
        self._ensure_axes_projection(False)   # 3D表示中でも必ず2D軸で案内を描く
        self._reset_figure_axes()
        self.ax.clear()
        self.ax.set_facecolor("white"); self.ax.tick_params(colors="black")
        self.ax.text(0.5, 0.5, "『データ』タブでファイルを追加し、\n列を選んで「グラフを描画」",
                     ha="center", va="center", fontsize=12, color="#888",
                     transform=self.ax.transAxes)
        self.ax.set_xticks([]); self.ax.set_yticks([])
        self.canvas.draw()

    def _set_status(self, text, level="info", detail=""):
        """ステータスバーに1行出し、同じ内容をメッセージ履歴にも残す。

        ステータスの1行は次のメッセージで消えてしまい、見逃すと二度と読めない。
        すべてここを通して履歴（表示→メッセージ履歴）から追えるようにする。"""
        self.status.showMessage(str(text))
        self._log_message(text, level, detail)

class StyleTableMixin:
    def _on_x_changed(self, *_):
        self._request_redraw()

    def _on_xleft_toggled(self, on):
        """『一番左の列をX軸』ON時は名前コンボを無効化し、先頭列をY候補から除外/復帰。"""
        self._refresh_columns()        # Y軸候補を作り直し（先頭列の除外/復帰）＋再描画予約
        self._update_x_combo_enabled()  # 有効/無効は最後に確定
        self._update_x_multi_enabled()  # 一番左X ON なら複数X不可

    def _update_x_combo_enabled(self):
        """X名コンボの有効状態を、グラフ種別と『一番左の列をX軸』から決める。"""
        info = plotter.CHART_INFO.get(self.chart_combo.currentText(), {})
        self.x_combo.setEnabled(info.get("use_x", True) and not self._use_leftmost_x())

    def _update_z_combo_enabled(self):
        """Z名コンボ（3Dの奥行き軸）の有効状態を決める。3D表示中のみ有効。"""
        if not hasattr(self, "z_combo"):
            return
        self.z_combo.setEnabled(self._want_3d())

    def _use_leftmost_x(self):
        return bool(getattr(self, "xleft_check", None) and self.xleft_check.isChecked())

    def _x_values(self, df, xname=None):
        """X軸データ列。xname 指定時はその列。None は『一番左の列』ONなら位置0、
        OFFなら x_combo の選択名（無ければ先頭列）。"""
        if xname is None and self._use_leftmost_x():
            return df.iloc[:, 0].to_numpy()
        name = xname if xname is not None else self.x_combo.currentText()
        return df[name].to_numpy() if name in df.columns else df.iloc[:, 0].to_numpy()

    def _selected_x_columns(self):
        """描画に使うX列の一覧。『X軸を複数選択』ONでチェックがあればそれら、
        無ければ単一（None＝一番左 or x_combo の1列）。"""
        if (getattr(self, "multix_check", None) and self.multix_check.isChecked()
                and not self._use_leftmost_x()):
            cols = [self.x_list.item(i).data(UserRole)
                    for i in range(self.x_list.count())
                    if self.x_list.item(i).checkState() == QtCore.Qt.CheckState.Checked]
            if cols:
                return cols
        return [None if self._use_leftmost_x() else self.x_combo.currentText()]

    def _update_x_multi_enabled(self):
        """『X軸を複数選択』チェックと複数Xリストの有効状態を種別・設定から決める。"""
        if not hasattr(self, "multix_check"):
            return
        # 複数Xが効くのは 2D の xy 種別かつ『一番左の列』OFF・3D以外
        ok = (self.chart_combo.currentText() in plotter._SWAP_TYPES
              and not self._use_leftmost_x() and not self._want_3d())
        if not ok and self.multix_check.isChecked():
            # 非対応状態になったら複数Xは解除する（後で勝手に復活しないように）
            self.multix_check.blockSignals(True)
            self.multix_check.setChecked(False)
            self.multix_check.blockSignals(False)
        self.multix_check.setEnabled(ok)
        self.x_list.setEnabled(ok and self.multix_check.isChecked())

    def _z_values(self, df):
        """Z軸データ列（3D用）。選択名が無ければ最終列で代用する。"""
        zname = self.z_combo.currentText() if hasattr(self, "z_combo") else ""
        return df[zname].to_numpy() if zname in df.columns else df.iloc[:, -1].to_numpy()

    def _effective_x_label(self):
        """既定のX軸ラベル（『一番左の列』ONなら先頭列名、複数XならX名を連結、
        それ以外は選択名）。"""
        if self._use_leftmost_x():
            items = self._selected_series_items()
            if items:
                df = self.datasets.get(items[0][0])
                if df is not None and len(df.columns):
                    return str(df.columns[0])
            return ""
        xcols = self._selected_x_columns()
        if len(xcols) > 1:
            return " / ".join(str(c) for c in xcols)
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
        # ツリーのチェックと系列バーは「今つけた印」なので即座に反映する。
        # 一方、系列スタイル表と解析候補の作り直しは1列あたり全行を作り直す
        # ので、連続操作（ファイル単位のチェック・すべて選択・まとめてドロップ）
        # では列数の2乗に比例して待たされる。そちらだけ後回しにして
        # 一連の操作が終わってから1回だけ実行する。
        self._rebuild_series_bar()          # 内部で _sync_explorer_checks も呼ぶ
        timer = getattr(self, "_ysel_timer", None)
        if timer is None:
            timer = self._ysel_timer = QtCore.QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(self._apply_y_selection_deferred)
        timer.start(30)

    def _apply_y_selection_deferred(self):
        """まとめた選択変更の重い側（系列表・解析候補・再描画）を反映する。"""
        self._rebuild_style_table()
        self._update_analysis_targets()
        self._request_redraw()

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

    # 「色を選ぶ／自動に戻す」ボタンの定義。attr=色を持つ属性名、
    # btn=ボタンの属性名、prefix=ボタンに出す見出し。
    # 背景色・近似曲線・塗りつぶしで同じ処理を3回書いていたのを1本にまとめた。
    _COLOR_BUTTONS = {
        "bg": ("bg_color", "bg_btn", "背景色: "),
        "trend": ("trend_color", "trend_color_btn", "色: "),
        "fill": ("fill_color", "fill_color_btn", "色: "),
    }

    def pick_color(self, kind):
        """色を選ぶ（キャンセルしたら何も変えない）。"""
        attr, btn_name, prefix = self._COLOR_BUTTONS[kind]
        col = QtWidgets.QColorDialog.getColor(parent=self)
        if not col.isValid():
            return
        setattr(self, attr, col.name())
        btn = getattr(self, btn_name)
        btn.setText(prefix + col.name())
        btn.setStyleSheet(f"background:{col.name()};")
        self._request_redraw()

    def reset_color(self, kind):
        """色を自動に戻す（背景=白/オシロ濃色、近似・塗りつぶし=系列の色）。"""
        attr, btn_name, prefix = self._COLOR_BUTTONS[kind]
        setattr(self, attr, "")
        btn = getattr(self, btn_name)
        btn.setText(prefix + "自動")
        btn.setStyleSheet("")
        self._request_redraw()

    def _wire_color_button(self, kind):
        """色ボタンに「左クリック=選ぶ／右クリック=自動へ戻す」を配線する。"""
        _attr, btn_name, _prefix = self._COLOR_BUTTONS[kind]
        btn = getattr(self, btn_name)
        btn.clicked.connect(lambda *_a, k=kind: self.pick_color(k))
        btn.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        btn.customContextMenuRequested.connect(lambda *_a, k=kind: self.reset_color(k))
        return btn

    # 旧名（設定の復元・プリセット適用から呼ばれる）。中身は上の2本に委譲する。
    def _reset_bg_color(self):
        self.reset_color("bg")

    def _reset_trend_color(self):
        self.reset_color("trend")

    def _reset_fill_color(self):
        self.reset_color("fill")

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

class BatchMixin:
    # ------------------------------------------------------------ 補助
    def _save_current_figure(self, target, dpi, transparent, fmt=None):
        """現在のグラフを保存。縦横比の指定があれば画像そのものをその比率にする
        （図を比率サイズにして bbox トリミングせず保存）。自動なら従来どおり tight 保存。"""
        ratio = self._aspect_ratio()
        if not ratio or self._is_3d():   # 3D は box_aspect 比率調整をせずそのまま保存
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
                applog.get_logger().debug("_save_current_figure: 無視した例外", exc_info=True)
            self.fig.savefig(target, dpi=dpi, transparent=transparent, format=fmt)
        finally:
            self.fig.set_size_inches(orig)        # 画面表示用に元のサイズへ戻す
            self._apply_aspect()
            try:
                self.fig.tight_layout()
            except Exception:
                applog.get_logger().debug("_save_current_figure: 無視した例外", exc_info=True)
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

    def _build_series_for_file(self, label, x_names, y_names, chart_type, style_by_col,
                               z_name="", threed=False):
        """1ファイルから、指定した列名テンプレートで系列を作る（一括出力用）。
        『一番左の列をX軸』ONなら、各ファイルの先頭列を位置でX軸に使う。
        x_names は複数X対応のリスト（None は一番左/単一）。"""
        df = self.datasets[label]
        series, categories = [], None
        leftmost = self._use_leftmost_x()

        def xvals(xn):
            if xn is None or leftmost:
                return df.iloc[:, 0].to_numpy()
            return df[xn].to_numpy() if xn in df.columns else df.iloc[:, 0].to_numpy()

        xcols = list(x_names) if (x_names and not leftmost) else [None]
        primary = xvals(xcols[0])
        if threed:
            zv = (df[z_name].to_numpy() if z_name in df.columns else df.iloc[:, -1].to_numpy())
            for c in y_names:
                st = style_by_col.get(c) or {}
                series.append({"label": c, "x": primary, "y": df[c].to_numpy(), "z": zv,
                               "style": st, "kind": st.get("kind", "")})
        elif chart_type in ("棒", "横棒", "積み上げ棒", "円", "ドーナツ"):
            categories = primary
            for c in y_names:
                series.append({"label": c, "y": df[c].to_numpy(),
                               "style": style_by_col.get(c)})
        elif chart_type in ("折れ線", "散布図", "面", "積み上げ面",
                            "ステップ", "ステム", "2Dヒストグラム", "hexbin"):
            multi = len(xcols) > 1
            for c in y_names:
                st = style_by_col.get(c) or {}
                errcol = st.get("errcol")
                yerr = df[errcol].to_numpy() if (errcol and errcol in df.columns) else None
                for xn in xcols:
                    lab = c if not multi else f"{c} [X:{xn or str(df.columns[0])}]"
                    series.append({"label": lab, "x": xvals(xn), "y": df[c].to_numpy(),
                                   "style": st, "axis": st.get("axis", "primary"),
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
        title_edit.setToolTip("グラフタイトル。{name} はファイル名（拡張子なし）に置き換わります。\n"
                              "空欄にするとタイトルなしで出力します。")
        title_edit.setPlaceholderText("（空欄=タイトルなし）")
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
        # 空欄はそのまま「タイトルなし」として扱う（勝手に {name} へ戻さない）
        return {"title": title_edit.text().strip(), "fmt": fmt_combo.currentText(),
                "dpi": dpi_spin.value(), "transparent": trans.isChecked()}

    def batch_export(self):
        """読み込んだ各ファイルを、現在の設定で個別に描画してファイル名ごとに一括保存する。"""
        if not self.datasets:
            self.notify("先にファイルを追加してください。", "warn")
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
            self.notify("Y軸（値）の系列を1つ以上選んでください。\n"
                        "その列名を各ファイルに適用し、ファイルごとに1枚ずつ出力します。", "warn")
            return
        x_name = self.x_combo.currentText()
        x_names = self._selected_x_columns()   # 複数X対応（[None]=一番左/単一）
        z_name = self.z_combo.currentText() if hasattr(self, "z_combo") else ""
        is3d = self._want_3d()
        view_init = self._view_angles() if is3d else None
        zlabel = z_name if is3d else ""
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
                    label, x_names, cols, ctype, style_by_col, z_name=z_name, threed=is3d)
            except Exception as e:  # noqa: BLE001
                skipped.append(f"{label}（{e}）")
                continue
            stem = os.path.splitext(label)[0]
            sec_label = " / ".join(s["label"] for s in series
                                   if s.get("axis") == "secondary")
            if self.xlabel_edit.text():
                xlab = self.xlabel_edit.text()
            elif self._use_leftmost_x():
                xlab = str(df.columns[0])
            elif len(x_names) > 1 and x_names[0] is not None:
                xlab = " / ".join(str(c) for c in x_names)   # 複数XはX名を連結
            else:
                xlab = x_name
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
                "zlabel": zlabel, "view_init": view_init, "threed": is3d,
                "figsize": tuple(figsize), "tight": tight,
                "dpi": dpi, "transparent": transparent,
                "path": os.path.join(out_dir, f"{name}.{ext}"),
                "font_name": getattr(self, "font_name", None),
            })

        import batch_render
        saved = []
        total = len(tasks)
        # 進捗ダイアログ（キャンセル可）。何が今出力中かが見える。
        prog = QtWidgets.QProgressDialog("画像を出力中…", "キャンセル", 0, total, self)
        prog.setWindowTitle("一括画像出力")
        prog.setWindowModality(QtCore.Qt.WindowModality.WindowModal)
        prog.setMinimumDuration(0)
        prog.setValue(0)
        canceled = False
        try:
            # ファイル数が多いときだけ別プロセス並列（spawn/ピクル/フォント設定の
            # 固定費があるので少数では逆効果）。失敗時は必ず逐次へフォールバックする。
            use_pool = total >= BATCH_PARALLEL_THRESHOLD
            if use_pool:
                try:
                    import concurrent.futures as _cf
                    workers = min(8, (os.cpu_count() or 1))
                    with _cf.ProcessPoolExecutor(max_workers=workers) as ex:
                        futs = {ex.submit(batch_render.render_one, t): t for t in tasks}
                        done = 0
                        for fut in _cf.as_completed(futs):
                            if prog.wasCanceled():
                                canceled = True
                                for f in futs:
                                    f.cancel()
                                break
                            try:
                                saved.append(fut.result())
                            except Exception as e:  # noqa: BLE001
                                skipped.append(
                                    f"{os.path.basename(futs[fut]['path'])}（{e}）")
                            done += 1
                            prog.setLabelText(f"出力中… {done}/{total}")
                            prog.setValue(done)
                            QtWidgets.QApplication.processEvents()
                except Exception as e:  # noqa: BLE001  プール作成失敗/壊れ→逐次へ
                    self._set_status(f"並列出力に失敗、逐次に切替: {e}")
                    use_pool = False
                    saved = []        # 部分結果は破棄し、逐次で全件作り直す
            if not use_pool:
                for idx, t in enumerate(tasks, 1):
                    if prog.wasCanceled():
                        canceled = True
                        break
                    prog.setLabelText(f"出力中… {idx}/{total}: {os.path.basename(t['path'])}")
                    QtWidgets.QApplication.processEvents()
                    try:
                        saved.append(batch_render.render_one(t))
                    except Exception as e:  # noqa: BLE001
                        skipped.append(f"{os.path.basename(t['path'])}（{e}）")
                    prog.setValue(idx)
        finally:
            prog.close()

        self.last_dir = out_dir
        msg = f"一括出力: {len(saved)} 件を保存しました。\n{out_dir}"
        if canceled:
            msg += "\n（途中でキャンセルしました）"
        if skipped:
            head = " / ".join(str(s) for s in skipped[:5])
            msg += f"\n\nスキップ {len(skipped)} 件: {head}" + (" ほか" if len(skipped) > 5 else "")
        self.notify(msg, "info")
        self._set_status(f"一括出力: {len(saved)} 件保存（{out_dir}）")

class PersistenceMixin:
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
        self._apply_ui_level(str(s.value(self.UI_LEVEL_KEY) or self.DEFAULT_UI_LEVEL))
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
        s.setValue(self.UI_LEVEL_KEY, self.ui_level())

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
            "tabs": self._collect_plugin_config(),   # 差し込みタブの設定（各タブが collect_config で提供）
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
        self._apply_plugin_config(cfg.get("tabs", {}))   # 差し込みタブの設定を復元

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

# ---- 内蔵タブの登録（メインがタブをまとめて有効化）----
# 内蔵4タブ。order で並び順、min_level で「どの表示レベルから現れるか」を決める。
# （data=基本, scope=標準, advanced/datasci=全部 という現行の挙動をそのまま宣言）
BUILTIN_TABS = [
    _DelegatingTab("data", "1. データ", 10, "基本", "_build_tab_data"),
    _DelegatingTab("scope", "2. オシロ/解析", 20, "標準", "_build_tab_scope"),
    _DelegatingTab("advanced", "3. 高度解析", 30, "全部", "_build_tab_advanced"),
    _DelegatingTab("datasci", "4. 統計解析", 40, "全部", "_build_tab_datasci"),
]

for _tab in BUILTIN_TABS:
    register_tab(_tab)

class GraphApp(HostMixin, UIBuildMixin, DataIOMixin, StyleTableMixin, PlotMixin,
               ScopeTabMixin, AdvancedMixin, DataSciMixin,
               BatchMixin, PersistenceMixin, QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.datasets = {}      # label -> DataFrame
        self.meta = {}          # label -> {"path","enc","delim"}
        self.series_styles = {} # "file\tcol" -> style dict（label 上書きも保持）
        self.last_dir = os.path.expanduser("~")

        self._suspend_redraw = True   # 構築・設定適用中は自動再描画を抑制
        self._has_drawn = False       # 一度でも描画したか（リアルタイム更新の発火条件）

        self.font_name = jp_font.setup_japanese_font()
        applog.get_logger().info("GraphApp 起動（フォント: %s）", self.font_name or "未検出")
        self.setWindowTitle("CSV / TSV / 波形 グラフ・解析ツール")
        self.resize(1280, 800)
        self.setAcceptDrops(True)     # Explorer からのドラッグ&ドロップ読み込み

        # 変更を少し待ってからまとめて再描画するデバウンスタイマー
        self._redraw_timer = QtCore.QTimer(self)
        self._redraw_timer.setSingleShot(True)
        self._redraw_timer.timeout.connect(self._do_live_redraw)

        # ズーム時に表示範囲を再サンプルするための状態
        self._dyn = []            # [(line, full_x, full_y, max_points), ...]
        self._dyn_cid = None
        self._resampling = False
        self._resample_timer = QtCore.QTimer(self)
        self._resample_timer.setSingleShot(True)
        self._resample_timer.timeout.connect(self._do_resample)
        self.recent_files = []    # 最近使ったファイル（MRU）

        # カーソル測定の状態
        self._cursor_cid = None
        self._cursor_pts = []
        self._cursor_artists = []
        self._cursors = []          # [{x, vline, marker}] ドラッグ微調整対応
        self._cursor_drag = None
        self._cursor_text = None

        self._build_menu()
        self._build_toolbar()
        self._build_central()
        self._build_statusbar()
        self._on_chart_type_change()
        self._restore_ui_state()      # 前回のウィンドウ位置・分割位置・セクション開閉を復元

        restored = self._try_restore_session()
        if not restored:
            self._set_status("『データ』タブで「ファイル追加」、またはCSV/TSVファイルをドラッグ&ドロップして読み込んでください。")
        self._suspend_redraw = False  # 構築完了。以降は変更で自動再描画

    def changeEvent(self, event):
        # OS のライト⇔ダーク切替に追従して外観を作り直す。
        # （super() を呼ぶメソッドは Mixin ではなく本体に置く決まり）
        try:
            self._on_palette_changed(event.type())
        except Exception:
            applog.get_logger().debug("テーマ変更の追従に失敗", exc_info=True)
        super().changeEvent(event)

    def closeEvent(self, event):
        try:
            self._stop_background_tasks()
        except Exception:
            applog.get_logger().debug("バックグラウンド処理の停止に失敗", exc_info=True)
        try:
            config_io.save_last_session(self._collect_config())
        except Exception:
            applog.get_logger().exception("終了時の設定保存に失敗")
        try:
            self._save_ui_state()
        except Exception:
            applog.get_logger().exception("終了時のUI状態保存に失敗")
        applog.get_logger().info("GraphApp 終了")
        super().closeEvent(event)




def main():
    applog.setup_logging()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

    def _notify(text):
        try:
            QtWidgets.QMessageBox.critical(None, "予期しないエラー",
                                           f"{text}\n\n詳細は app.log を確認してください:\n{applog.LOG_FILE}")
        except Exception:  # noqa: BLE001
            applog.get_logger().debug("_notify: 無視した例外", exc_info=True)

    applog.install_excepthook(on_error=_notify)   # 未捕捉例外もログ＋通知（無言終了の防止）
    try:
        win = GraphApp()
        win.show()
        sys.exit(app.exec())
    except Exception:
        applog.get_logger().exception("起動に失敗")
        raise


if __name__ == "__main__":
    main()
