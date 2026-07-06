# -*- coding: utf-8 -*-
"""UIBuildMixin: GraphApp から分離した UIBuildMixin 群（挙動は本体と同一）。"""
from graph_app_common import *  # noqa: F401,F403


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
        アクションだけを候補にする。"""
        if not hasattr(self, "_all_actions"):
            self._all_actions = []
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
        self._menu_action(vm, "コマンドパレット...", self.show_command_palette, "Ctrl+Shift+P",
                          tip="すべてのメニュー操作を名前で検索して実行")
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
        # ツール
        tm = m.addMenu("ツール(&T)")
        self._menu_action(tm, "LTspiceシミュレーション実行(.asc)...", self.run_ltspice_asc,
                          tip="LTspice回路をバッチ実行し、生成された .raw 波形を自動で読み込みます。"
                              "回路(.asc)のドラッグ&ドロップでも実行できます")
        self._menu_action(tm, "LTspiceの場所を設定...", self.set_ltspice_path,
                          tip="LTspice実行ファイル（LTspice.exe / XVIIx64.exe）の場所を指定")
        # ヘルプ
        hm = m.addMenu("ヘルプ(&H)")
        self._menu_action(hm, "使い方", self.show_help, "F1")
        self._menu_action(hm, "バージョン情報", self.show_about, None)

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
    _UI_STYLES = {
        # 標準にも「基準QSS」を持たせ、ボタン/入力欄の高さを統一して見切れを防ぐ
        "standard": {
            "qss": """
QPushButton { padding: 4px 10px; min-height: 22px; }
QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox { min-height: 22px; }
""",
            "tb_style": "beside", "tb_icon": 24, "indent": 20},
        "labplot": {   # KDE Breeze調: ゆったり・角丸・青アクセント
            "qss": """
QWidget { font-size: 10pt; }
QPushButton { background:#fcfcfc; border:1px solid #bfc4c9; border-radius:3px;
              padding:5px 12px; }
QPushButton:hover { border-color:#3daee9; }
QPushButton:pressed, QPushButton:checked { background:#d6ecf8; border-color:#3daee9; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    border:1px solid #bfc4c9; border-radius:3px; padding:3px 6px; background:white; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border-color:#3daee9; }
QTreeWidget, QListWidget, QTableWidget { border:1px solid #cfd4d9; border-radius:3px; }
QTreeWidget::item { min-height:24px; }
QTabBar::tab { padding:6px 14px; }
QToolBar { spacing:4px; padding:3px; }
QToolButton { padding:4px; border-radius:3px; }
QToolButton:hover { background:#d6ecf8; }
QDockWidget::title { background:#eff0f1; padding:5px; }
""",
            "tb_style": "beside", "tb_icon": 22, "indent": 20},
        "veusz": {     # 実用主義コンパクト: 小さく詰めて情報密度を上げる
            "qss": """
QWidget { font-size: 8pt; }
QPushButton { padding:2px 8px; min-height:18px; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox { padding:1px 3px; min-height:18px; }
QTreeWidget::item { min-height:18px; }
QTabBar::tab { padding:3px 8px; }
QToolBar { spacing:1px; padding:1px; }
QToolButton { padding:2px; }
QDockWidget::title { padding:2px; }
""",
            "tb_style": "icon", "tb_icon": 16, "indent": 14},
        "kst": {       # ミニマル: 枠・装飾を減らしプロットに集中
            "qss": """
QWidget { font-size: 9pt; }
QToolBar { border:0; spacing:2px; padding:2px; background:transparent; }
QDockWidget::title { background:transparent; padding:3px; }
QPushButton { padding:3px 10px; border:1px solid #c9c9c9; border-radius:2px;
              background:#f7f7f7; }
QPushButton:checked { background:#e2e2e2; }
QTreeWidget, QListWidget, QTableWidget { border:1px solid #dddddd; }
QTreeWidget::item { min-height:20px; }
QTabBar::tab { padding:4px 10px; }
""",
            "tb_style": "icon", "tb_icon": 18, "indent": 16},
        "igor": {      # クラシック高密度: グレー基調・小さな立体ボタン
            "qss": """
QWidget { font-size: 8pt; }
QMainWindow, QDockWidget, QTabWidget::pane { background-color:#ececec; }
QPushButton { background:qlineargradient(x1:0,y1:0,x2:0,y2:1,
                                         stop:0 #fdfdfd, stop:1 #dcdcdc);
              border:1px solid #8f8f8f; border-radius:2px; padding:2px 9px;
              min-height:18px; }
QPushButton:pressed, QPushButton:checked { background:#cfcfcf; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    background:white; border:1px solid #9a9a9a; padding:1px 3px; }
QTreeWidget, QListWidget, QTableWidget { background:white; border:1px solid #9a9a9a; }
QTreeWidget::item { min-height:18px; }
QDockWidget::title { background:#dcdcdc; border:1px solid #b0b0b0; padding:3px; }
QTabBar::tab { padding:3px 10px; background:#dcdcdc; border:1px solid #b0b0b0; }
QTabBar::tab:selected { background:#ececec; }
QToolBar { background:#e4e4e4; spacing:1px; }
""",
            "tb_style": "icon", "tb_icon": 20, "indent": 14},
    }

    def _set_ui_style(self, name):
        """メニューからのUIスタイル切替（ステータス案内つき）。"""
        self._apply_ui_style(name)
        names = {"standard": "標準", "labplot": "LabPlot風", "veusz": "Veusz風",
                 "kst": "KST2風", "igor": "Igor Pro風"}
        self._set_status(f"UIスタイル: {names.get(name, name)}"
                         "（配置も合わせるなら 表示→レイアウト を併用）")

    def _apply_ui_style(self, name):
        """UIスタイル（外観テーマ）を適用する。ウィジェット・機能は変えない。"""
        style = self._UI_STYLES.get(name)
        if style is None:
            return
        self.setStyleSheet(style["qss"])
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
        self._ui_style_name = name

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
        self.left_docks = []
        for key, title, builder in (
                ("data", "1. データ", self._build_tab_data),
                ("scope", "2. オシロ/解析", self._build_tab_scope),
                ("advanced", "3. 高度解析", self._build_tab_advanced),
                ("datasci", "4. 統計解析", self._build_tab_datasci)):
            dock = QtWidgets.QDockWidget(title, self)
            dock.setObjectName("dock_" + key)   # saveState に必須
            w = builder()
            # 中身をスクロール可能にして、ドックを好きな幅まで狭められるようにする
            # （中身の最小サイズがドックの縮小を妨げないように。既にスクロール式ならそのまま）
            if not isinstance(w, QtWidgets.QScrollArea):
                w = self._scrollable(w)
            dock.setWidget(w)
            self.addDockWidget(left, dock)
            self.left_docks.append(dock)
        for d in self.left_docks[1:]:           # 既定はタブ化（従来の見た目）
            self.tabifyDockWidget(self.left_docks[0], d)

        # 中央：グラフ表示＋データ編集
        center = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
        self.center_splitter = center
        center.addWidget(self._build_plot_area())
        center.addWidget(self._build_preview())
        center.setStretchFactor(0, 4)
        center.setStretchFactor(1, 1)
        self.setCentralWidget(center)

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
        # ワンクリックのレイアウトプリセット（GUIが評価の高いツールの配置を再現）
        lay_menu = vm.addMenu("レイアウト")
        self._menu_action(lay_menu, "標準（3ペイン）", lambda: self._apply_layout_preset("standard"),
                          tip="左パネル＋中央グラフ＋右書式の標準配置に戻す")
        self._menu_action(lay_menu, "グラフ集中（Saleae風）",
                          lambda: self._apply_layout_preset("graph"),
                          tip="パネルを全部たたみ、グラフをほぼ全画面に（波形をじっくり見る）")
        self._menu_action(lay_menu, "解析中心（オシロ）",
                          lambda: self._apply_layout_preset("analysis"),
                          tip="オシロ/解析パネル＋大きなグラフ＋データ表（測定作業向け）")
        self._menu_action(lay_menu, "データ整備",
                          lambda: self._apply_layout_preset("data"),
                          tip="データパネル＋大きなデータ編集表（読み込み・クレンジング向け）")
        lay_menu.addSeparator()
        self._menu_action(lay_menu, "LabPlot風（配置＋外観）",
                          lambda: self._apply_layout_preset("labplot"),
                          tip="左にプロジェクトツリー＋統計解析タブ・右にプロパティ・下にスプレッドシート、"
                              "外観はBreeze調（LabPlotの標準画面）")
        self._menu_action(lay_menu, "Veusz風（配置＋外観）",
                          lambda: self._apply_layout_preset("veusz"),
                          tip="ツールバーを左縦に移し、左にデータツリー（上）＋書式（下）の縦積み、"
                              "右は大きなグラフ。外観はコンパクト（Veuszの編集画面）")
        self._menu_action(lay_menu, "KST2風（配置＋外観）",
                          lambda: self._apply_layout_preset("kst"),
                          tip="プロットを全画面にし、データはフロートの小窓（データマネージャ風）。"
                              "外観はミニマル（KST2のライブ監視画面）")
        self._menu_action(lay_menu, "Igor Pro風（配置＋外観）",
                          lambda: self._apply_layout_preset("igor"),
                          tip="データ・オシロ解析・書式の3枚をカスケードのフロートウィンドウにし、"
                              "メインはグラフ専用。外観はクラシック高密度（IgorのMDI風）")
        # 外観テーマ（配置は保ったまま、ボタンの大きさ・余白・密度・配色だけ切り替える）
        style_menu = vm.addMenu("UIスタイル（外観のみ）")
        self._menu_action(style_menu, "標準", lambda: self._set_ui_style("standard"),
                          tip="既定の外観に戻す（配置はそのまま）")
        self._menu_action(style_menu, "LabPlot風（ゆったりモダン）",
                          lambda: self._set_ui_style("labplot"),
                          tip="外観のみ: Breeze調の大きめボタン・角丸・青アクセント。配置も変えるなら レイアウト→LabPlot風")
        self._menu_action(style_menu, "Veusz風（コンパクト）",
                          lambda: self._set_ui_style("veusz"),
                          tip="外観のみ: 小さいフォントと詰めた余白。配置も変えるなら レイアウト→Veusz風")
        self._menu_action(style_menu, "KST2風（ミニマル）",
                          lambda: self._set_ui_style("kst"),
                          tip="外観のみ: 枠線・装飾を減らした薄いクローム。配置も変えるなら レイアウト→KST2風")
        self._menu_action(style_menu, "Igor Pro風（クラシック高密度）",
                          lambda: self._set_ui_style("igor"),
                          tip="外観のみ: グレー基調・小さな立体ボタン。配置も変えるなら レイアウト→Igor Pro風")
        vm.addSeparator()
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
        隠したパネルは表示メニュー（またはレイアウト→標準）でいつでも戻せる。"""
        total = max(sum(self.center_splitter.sizes()), 400)
        for d in [self.files_dock, *self.left_docks, self.format_dock]:
            d.setFloating(False)
        # ツールバーは既定の上配置へ戻す（Veusz風だけが左縦に移す）
        tb = getattr(self, "main_toolbar", None)
        if tb is not None:
            self.addToolBar(QtCore.Qt.ToolBarArea.TopToolBarArea, tb)
        # 「◯◯風」プリセットは配置だけでなく外観（ボタンの大きさ・密度・配色）も適用する
        if name in self._UI_STYLES:
            self._apply_ui_style(name)
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
        elif name == "labplot":
            # LabPlot: 左=ファイルツリー＋軸＋統計のタブ、右=プロパティ、
            # 下=スプレッドシート（データ表）という4区画のワークベンチ配置
            for d in (self.left_docks[1], self.left_docks[2]):
                d.hide()
            files, data, ds = self.files_dock, self.left_docks[0], self.left_docks[3]
            for d in (files, data, ds):
                d.show()
                self.addDockWidget(QtCore.Qt.DockWidgetArea.LeftDockWidgetArea, d)
            self.tabifyDockWidget(files, data)   # ファイル/軸/統計をタブで切替
            self.tabifyDockWidget(data, ds)
            files.raise_()
            self.format_dock.show()
            self.addDockWidget(QtCore.Qt.DockWidgetArea.RightDockWidgetArea, self.format_dock)
            self.resizeDocks([files], [330], QtCore.Qt.Orientation.Horizontal)
            self.resizeDocks([self.format_dock], [390], QtCore.Qt.Orientation.Horizontal)
            self.center_splitter.setSizes([int(total * 0.75), int(total * 0.25)])
            self._set_status("レイアウト: LabPlot風（ファイル+軸+統計タブ／グラフ＋スプレッドシート／プロパティ）")
        elif name == "veusz":
            # Veusz: ツールバーは左縦、左列にファイルツリー(上)＋書式(下)の縦積み
            if tb is not None:
                self.addToolBar(QtCore.Qt.ToolBarArea.LeftToolBarArea, tb)
            for d in self.left_docks:
                d.hide()
            files = self.files_dock
            files.show()
            self.addDockWidget(QtCore.Qt.DockWidgetArea.LeftDockWidgetArea, files)
            self.format_dock.show()
            self.addDockWidget(QtCore.Qt.DockWidgetArea.LeftDockWidgetArea, self.format_dock)
            self.splitDockWidget(files, self.format_dock, QtCore.Qt.Orientation.Vertical)
            self.resizeDocks([files, self.format_dock], [370, 370],
                             QtCore.Qt.Orientation.Horizontal)
            self.center_splitter.setSizes([total, 0])
            self._set_status("レイアウト: Veusz風（左縦ツールバー＋編集パネル縦積み＋大きなグラフ）")
        elif name == "kst":
            # KST2: プロット全画面＋データマネージャ風のフロート小窓（=ファイルツリー）
            for d in [*self.left_docks, self.format_dock]:
                d.hide()
            files = self.files_dock
            files.show()
            files.setFloating(True)
            files.resize(300, 430)
            files.move(self.x() + max(self.width() - 340, 80), self.y() + 110)
            self.center_splitter.setSizes([total, 0])
            self._set_status("レイアウト: KST2風（プロット全画面＋データマネージャの小窓）")
        elif name == "igor":
            # Igor Pro: ファイル・オシロ解析・書式の3枚をカスケードのツールウィンドウに
            for d in (self.left_docks[0], self.left_docks[2], self.left_docks[3]):
                d.hide()
            casc = [(self.files_dock, (340, 480)),
                    (self.left_docks[1], (360, 460)),
                    (self.format_dock, (400, 540))]
            for i, (d, size) in enumerate(casc):
                d.show()
                d.setFloating(True)
                d.resize(*size)
                d.move(self.x() + 50 + i * 48, self.y() + 100 + i * 42)
            self.center_splitter.setSizes([total, 0])
            self._set_status("レイアウト: Igor Pro風（データ/オシロ/書式をカスケードのウィンドウに。"
                             "『新しいグラフウィンドウ』(Ctrl+G)と組み合わせるとMDI風になります）")

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
        if tb is not None:   # Veusz風で左縦に移したツールバーも上へ戻す
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
                    pass
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
            QtWidgets.QMessageBox.warning(self, "名前の変更", "同名のデータが既にあります。")
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
        if getattr(self, "_preview_label", None) == old:
            self._preview_label = new
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
        """右端のグラフ書式調整パネル（上：グラフ書式コントロール／下：系列スタイル表）。"""
        split = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
        self.format_splitter = split
        scroll = QtWidgets.QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        scroll.setWidget(self._build_tab_graph())   # 種別/タイトル/軸/近似曲線/縦横比/画像出力
        split.addWidget(scroll)
        split.addWidget(self._build_style_box())     # 系列スタイル表
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        return split

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
        self.bg_btn.clicked.connect(self._pick_bg_color)
        self.bg_btn.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.bg_btn.customContextMenuRequested.connect(lambda *_: self._reset_bg_color())
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
        self.trend_color_btn.clicked.connect(self._pick_trend_color)
        self.trend_color_btn.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.trend_color_btn.customContextMenuRequested.connect(lambda *_: self._reset_trend_color())
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
        self.fill_color_btn.clicked.connect(self._pick_fill_color)
        self.fill_color_btn.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.fill_color_btn.customContextMenuRequested.connect(lambda *_: self._reset_fill_color())
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
        self.aspect_h = QtWidgets.QSpinBox(); self.aspect_h.setRange(1, 100); self.aspect_h.setValue(9)
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
    def _build_tab_scope(self):
        w = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(w)

        self.scope_check = QtWidgets.QCheckBox("オシロスコープ表示（折れ線/散布図）")
        v.addWidget(self.scope_check)
        g = QtWidgets.QGridLayout()
        g.addWidget(QtWidgets.QLabel("time/div [s]"), 0, 0)
        self.tdiv = QtWidgets.QComboBox(); self.tdiv.setEditable(True)
        self.tdiv.addItems(plotter.eng_125_sequence(1e-9, 1.0, "s"))
        self.tdiv.setCurrentText("1ms")
        g.addWidget(self.tdiv, 0, 1)
        g.addWidget(QtWidgets.QLabel("V/div"), 0, 2)
        self.vdiv = QtWidgets.QComboBox(); self.vdiv.setEditable(True)
        self.vdiv.addItems(plotter.eng_125_sequence(1e-3, 100.0, ""))
        self.vdiv.setCurrentText("500m")
        g.addWidget(self.vdiv, 0, 3)
        g.addWidget(QtWidgets.QLabel("X位置(中心)"), 1, 0)
        self.xpos = QtWidgets.QLineEdit("0"); g.addWidget(self.xpos, 1, 1)
        g.addWidget(QtWidgets.QLabel("Y位置(中心)"), 1, 2)
        self.ypos = QtWidgets.QLineEdit("0"); g.addWidget(self.ypos, 1, 3)
        g.addWidget(QtWidgets.QLabel("X div数"), 2, 0)
        self.xdivs = QtWidgets.QSpinBox(); self.xdivs.setRange(2, 20); self.xdivs.setValue(10)
        g.addWidget(self.xdivs, 2, 1)
        g.addWidget(QtWidgets.QLabel("Y div数"), 2, 2)
        self.ydivs = QtWidgets.QSpinBox(); self.ydivs.setRange(2, 20); self.ydivs.setValue(8)
        g.addWidget(self.ydivs, 2, 3)
        v.addLayout(g)
        b_auto = QtWidgets.QPushButton("自動スケール（解析対象に合わせる）")
        b_auto.clicked.connect(self.auto_scale_scope)
        v.addWidget(b_auto)
        scope_hint = QtWidgets.QLabel(
            "💡 オシロ表示中はグラフを直接操作可：左ドラッグ=位置移動／右ドラッグ=time/V/div／"
            "ホイール=time/div・Shift+ホイール=V/div（ドラッグ中は数値を表示）")
        scope_hint.setWordWrap(True); scope_hint.setStyleSheet("color:#0a7a55; font-size:11px;")
        v.addWidget(scope_hint)

        v.addWidget(self._hline())
        # 解析対象
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("解析対象:"))
        self.analysis_target = QtWidgets.QComboBox()
        row.addWidget(self.analysis_target, 1)
        v.addLayout(row)
        row2 = QtWidgets.QHBoxLayout()
        row2.addWidget(QtWidgets.QLabel("ピーク数 N:"))
        self.npeaks = QtWidgets.QSpinBox(); self.npeaks.setRange(1, 50); self.npeaks.setValue(5)
        row2.addWidget(self.npeaks)
        row2.addWidget(QtWidgets.QLabel("平滑化(点):"))
        self.smooth_spin = QtWidgets.QSpinBox(); self.smooth_spin.setRange(0, 501)
        self.smooth_spin.setSingleStep(2); self.smooth_spin.setValue(0)
        self.smooth_spin.setToolTip("ノイズの多い実測データで偽ピークを抑える。0=平滑化なし。窓の点数（奇数推奨）。")
        row2.addWidget(self.smooth_spin); row2.addStretch(1)
        v.addLayout(row2)
        self.show_peaks_check = QtWidgets.QCheckBox("ピークをグラフに表示"); self.show_peaks_check.setChecked(False)
        v.addWidget(self.show_peaks_check)
        self.window_meas_check = QtWidgets.QCheckBox("表示範囲のみ測定（ズーム/オシロ窓に追従）")
        self.window_meas_check.setToolTip("オンにすると、画面に見えているX範囲だけを対象に解析します。")
        v.addWidget(self.window_meas_check)
        # 解析アクションは4個。1行に詰めると見切れるので2段に分ける
        b_an = QtWidgets.QPushButton("解析実行"); b_an.clicked.connect(self.run_analysis)
        b_an.setToolTip("解析対象コンボで選んだ1系列のピーク・測定を下の表に表示")
        b_all = QtWidgets.QPushButton("全系列を解析…")
        b_all.setToolTip("選択中の全系列のピーク・測定を別ウィンドウに一覧表示（CSV保存可）")
        b_all.clicked.connect(self.analyze_all_series)
        b_fft = QtWidgets.QPushButton("FFT表示"); b_fft.clicked.connect(self.show_fft)
        b_fft.setToolTip("FFTスペクトル表示：選択中の全系列のFFTを1枚に重ね描き（系列ごとに色分け）")
        b_cur = QtWidgets.QPushButton("カーソル測定"); b_cur.setCheckable(True)
        b_cur.setToolTip("グラフを2回クリックして Δt・ΔV・1/Δt を測ります")
        b_cur.toggled.connect(self.toggle_cursors)
        self.cursor_btn = b_cur
        # 1行目=実行系（押すと計算して表を更新）、2行目=測定モード系（ON/OFFトグル）
        brow = QtWidgets.QHBoxLayout()
        brow.addWidget(b_an); brow.addWidget(b_all); brow.addWidget(b_fft)
        v.addLayout(brow)
        b_gate = QtWidgets.QPushButton("区間測定")
        b_gate.setCheckable(True)
        b_gate.setToolTip("ONにしてグラフ上を横にドラッグすると、選んだX区間だけの\n"
                          "測定値（平均/RMS/周期など）を下の表に表示します。")
        b_gate.toggled.connect(self.toggle_gate)
        self.gate_btn = b_gate
        brow2 = QtWidgets.QHBoxLayout()
        brow2.addWidget(b_cur); brow2.addWidget(b_gate)
        v.addLayout(brow2)

        v.addWidget(self._bold("ピーク（第1=最大）"))
        self.peak_table = QtWidgets.QTableWidget(0, 3)
        self.peak_table.setHorizontalHeaderLabels(["順位", "時間/周波数", "値"])
        self.peak_table.horizontalHeader().setStretchLastSection(True)
        self.peak_table.setMaximumHeight(160)
        self._wire_table_export(self.peak_table, "ピーク")
        v.addWidget(self.peak_table)

        v.addWidget(self._bold("測定値（右端「表示」でグラフに注記）"))
        self.meas_table = QtWidgets.QTableWidget(0, 3)
        self.meas_table.setHorizontalHeaderLabels(["項目", "値", "表示"])
        mh = self.meas_table.horizontalHeader()
        mh.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        mh.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Stretch)
        mh.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        self.meas_table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self._wire_table_export(self.meas_table, "測定値")
        v.addWidget(self.meas_table, 1)
        # 統計・トレンド・位相
        srow = QtWidgets.QHBoxLayout()
        b_stat = QtWidgets.QPushButton("サイクル統計"); b_stat.clicked.connect(self.show_cycle_stats)
        b_trend = QtWidgets.QPushButton("トレンド表示"); b_trend.clicked.connect(self.show_trend)
        b_pstat = QtWidgets.QPushButton("パラメータ統計…")
        b_pstat.setToolTip("サイクルごとの統計（平均/最大/最小/σ）とパラメータ間演算を別ウィンドウで表示")
        b_pstat.clicked.connect(self.show_param_stats)
        srow.addWidget(b_stat); srow.addWidget(b_trend); srow.addWidget(b_pstat)
        v.addLayout(srow)
        prow = QtWidgets.QHBoxLayout()
        prow.addWidget(QtWidgets.QLabel("位相差 対象2:"))
        self.phase_target2 = QtWidgets.QComboBox(); prow.addWidget(self.phase_target2, 1)
        b_phase = QtWidgets.QPushButton("位相差/遅延"); b_phase.clicked.connect(self.show_phase)
        prow.addWidget(b_phase)
        v.addLayout(prow)
        return w

    # ---- 高度解析タブ ----
    def _build_tab_advanced(self):
        outer = QtWidgets.QScrollArea(); outer.setWidgetResizable(True)
        w = QtWidgets.QWidget(); outer.setWidget(w)
        v = QtWidgets.QVBoxLayout(w)

        # --- 数学チャンネル ---
        v.addWidget(self._bold("数学チャンネル（演算で新しい波形を作成）"))
        mg = QtWidgets.QGridLayout()
        mg.addWidget(QtWidgets.QLabel("演算"), 0, 0)
        self.math_op = QtWidgets.QComboBox()
        self.math_op.addItems(mathchan.BINARY_OPS + mathchan.UNARY_OPS)
        self.math_op.currentTextChanged.connect(self._on_math_op_change)
        mg.addWidget(self.math_op, 0, 1, 1, 3)
        mg.addWidget(QtWidgets.QLabel("A"), 1, 0)
        self.math_a = QtWidgets.QComboBox(); mg.addWidget(self.math_a, 1, 1)
        self.math_b_label = QtWidgets.QLabel("B"); mg.addWidget(self.math_b_label, 1, 2)
        self.math_b = QtWidgets.QComboBox(); mg.addWidget(self.math_b, 1, 3)
        self.math_param_label = QtWidgets.QLabel("パラメータ"); mg.addWidget(self.math_param_label, 2, 0)
        self.math_param = QtWidgets.QLineEdit("5"); self.math_param.setToolTip("移動平均=窓長(点)、ローパス=カットオフ[Hz]")
        mg.addWidget(self.math_param, 2, 1)
        b_math = QtWidgets.QPushButton("数学チャンネルを作成"); b_math.clicked.connect(self.create_math_channel)
        mg.addWidget(b_math, 2, 2, 1, 2)
        v.addLayout(mg)
        # 任意数式（A,B,VAR1,VAR2,t と関数で自由に演算）
        eg = QtWidgets.QGridLayout()
        eg.addWidget(QtWidgets.QLabel("数式"), 0, 0)
        self.math_expr = QtWidgets.QLineEdit()
        self.math_expr.setPlaceholderText("例: sqrt(A**2+B**2) / sin(2*pi*t)*VAR1 / A-VAR1")
        self.math_expr.setToolTip("変数: A=対象A, B=対象B, t=時間, VAR1, VAR2, 定数 pi/e。\n"
                                  "関数: sin/cos/tan/asin/.../exp/log/log10/log2/sqrt/abs/sign/min/max/clip/where。")
        eg.addWidget(self.math_expr, 0, 1, 1, 3)
        eg.addWidget(QtWidgets.QLabel("VAR1"), 1, 0)
        self.math_var1 = QtWidgets.QLineEdit("1"); eg.addWidget(self.math_var1, 1, 1)
        eg.addWidget(QtWidgets.QLabel("VAR2"), 1, 2)
        self.math_var2 = QtWidgets.QLineEdit("0"); eg.addWidget(self.math_var2, 1, 3)
        b_expr = QtWidgets.QPushButton("数式でチャンネル作成"); b_expr.clicked.connect(self.create_math_expr)
        eg.addWidget(b_expr, 2, 0, 1, 4)
        v.addLayout(eg)
        v.addWidget(self._hline())

        # --- FFT 詳細 ---
        v.addWidget(self._bold("FFT 詳細（窓・dB・THD/SNR・スペクトログラム）"))
        fg = QtWidgets.QGridLayout()
        fg.addWidget(QtWidgets.QLabel("窓関数"), 0, 0)
        self.fft_window = QtWidgets.QComboBox(); self.fft_window.addItems(analysis.WINDOWS)
        self.fft_window.setCurrentText("hann"); fg.addWidget(self.fft_window, 0, 1)
        self.fft_db = QtWidgets.QCheckBox("dB表示"); fg.addWidget(self.fft_db, 0, 2)
        b_m = QtWidgets.QPushButton("THD/SNR等を計算"); b_m.clicked.connect(self.compute_fft_metrics)
        fg.addWidget(b_m, 1, 0, 1, 2)
        b_sp = QtWidgets.QPushButton("スペクトログラム"); b_sp.clicked.connect(self.show_spectrogram)
        fg.addWidget(b_sp, 1, 2, 1, 1)
        b_wf = QtWidgets.QPushButton("ウォーターフォール")
        b_wf.setToolTip("STFTの時間スライスを3Dに重ねて表示（周波数成分の時間変化を見る）。"
                        "ドラッグで回転できます。")
        b_wf.clicked.connect(self.show_waterfall)
        fg.addWidget(b_wf, 1, 3, 1, 1)
        v.addLayout(fg)
        self.fft_metrics = QtWidgets.QTableWidget(0, 2)
        self.fft_metrics.setHorizontalHeaderLabels(["指標", "値"])
        self.fft_metrics.horizontalHeader().setStretchLastSection(True)
        self.fft_metrics.setMaximumHeight(170)
        self._wire_table_export(self.fft_metrics, "FFT指標")
        v.addWidget(self.fft_metrics)
        v.addWidget(self._hline())

        # --- マスク試験 / アイ / ジッタ ---
        v.addWidget(self._bold("マスク試験 / アイダイアグラム / ジッタ"))
        mk = QtWidgets.QGridLayout()
        mk.addWidget(QtWidgets.QLabel("上限"), 0, 0)
        self.mask_upper = QtWidgets.QLineEdit(); self.mask_upper.setPlaceholderText("なし")
        mk.addWidget(self.mask_upper, 0, 1)
        mk.addWidget(QtWidgets.QLabel("下限"), 0, 2)
        self.mask_lower = QtWidgets.QLineEdit(); self.mask_lower.setPlaceholderText("なし")
        mk.addWidget(self.mask_lower, 0, 3)
        b_mask = QtWidgets.QPushButton("マスク判定"); b_mask.clicked.connect(self.run_mask_test)
        mk.addWidget(b_mask, 1, 0, 1, 2)
        mk.addWidget(QtWidgets.QLabel("シンボルレート[Hz]/周期[s]"), 2, 0, 1, 2)
        self.eye_rate = QtWidgets.QLineEdit("1e6"); mk.addWidget(self.eye_rate, 2, 2)
        b_eye = QtWidgets.QPushButton("アイダイアグラム"); b_eye.clicked.connect(self.show_eye_diagram)
        mk.addWidget(b_eye, 2, 3)
        b_jit = QtWidgets.QPushButton("ジッタ解析(TIE)"); b_jit.clicked.connect(self.run_jitter)
        mk.addWidget(b_jit, 1, 2, 1, 2)
        v.addLayout(mk)
        self.adv_result = QtWidgets.QLabel(""); self.adv_result.setWordWrap(True)
        self.adv_result.setStyleSheet("color:#0a3;")
        v.addWidget(self.adv_result)
        v.addWidget(self._hline())

        # --- プロトコル解読 ---
        v.addWidget(self._bold("シリアルプロトコル解読"))
        pg = QtWidgets.QGridLayout()
        pg.addWidget(QtWidgets.QLabel("プロトコル"), 0, 0)
        self.proto_combo = QtWidgets.QComboBox()
        self.proto_combo.addItems(["UART", "I2C", "SPI", "CAN", "LIN", "1-Wire"])
        self.proto_combo.currentTextChanged.connect(self._on_proto_change)
        pg.addWidget(self.proto_combo, 0, 1)
        pg.addWidget(QtWidgets.QLabel("ボーレート/不使用"), 0, 2)
        self.proto_baud = QtWidgets.QLineEdit("115200"); pg.addWidget(self.proto_baud, 0, 3)
        self.proto_ch_labels = [QtWidgets.QLabel("Ch1"), QtWidgets.QLabel("Ch2"), QtWidgets.QLabel("Ch3")]
        self.proto_ch = [QtWidgets.QComboBox(), QtWidgets.QComboBox(), QtWidgets.QComboBox()]
        for i in range(3):
            pg.addWidget(self.proto_ch_labels[i], 1 + i, 0)
            pg.addWidget(self.proto_ch[i], 1 + i, 1, 1, 3)
        b_dec = QtWidgets.QPushButton("解読"); b_dec.clicked.connect(self.decode_protocol)
        pg.addWidget(b_dec, 4, 0, 1, 4)
        self.proto_overlay_check = QtWidgets.QCheckBox("解読結果をグラフに注記表示")
        self.proto_overlay_check.setToolTip(
            "解読したフレームの値を波形の上に直接注記します（Saleae風・先頭80件まで）。\n"
            "CRC/パリティ等の不一致は赤で表示。折れ線/散布図の2D表示で有効。")
        self.proto_overlay_check.toggled.connect(self._on_proto_overlay_toggled)
        pg.addWidget(self.proto_overlay_check, 5, 0, 1, 4)
        v.addLayout(pg)
        self.proto_table = QtWidgets.QTableWidget(0, 4)
        self.proto_table.setHorizontalHeaderLabels(["時刻", "種別", "値(hex)", "備考"])
        self.proto_table.horizontalHeader().setStretchLastSection(True)
        self._wire_table_export(self.proto_table, "プロトコル解読")
        v.addWidget(self.proto_table, 1)

        self._on_math_op_change(self.math_op.currentText())
        self._on_proto_change("UART")
        return outer

    # ---- データサイエンスタブ ----
    def _build_tab_datasci(self):
        outer = QtWidgets.QScrollArea(); outer.setWidgetResizable(True)
        w = QtWidgets.QWidget(); outer.setWidget(w)
        v = QtWidgets.QVBoxLayout(w)

        v.addWidget(self._bold("統計解析（回帰・記述統計・相関・正規性）"))
        info = QtWidgets.QLabel("選択中のY系列を、現在のX軸列に対して解析します。"
                                "データタブでX軸とY系列を選んでから実行してください。")
        info.setWordWrap(True); info.setStyleSheet("color:#555;")
        v.addWidget(info)

        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("対象:"))
        self.ds_target = QtWidgets.QComboBox()
        self.ds_target.setToolTip("解析するY系列。データタブでY系列を選ぶと候補に出ます")
        row.addWidget(self.ds_target, 1)
        v.addLayout(row)

        # 回帰（線形性）
        b_reg = QtWidgets.QPushButton("線形回帰（Y vs X）")
        b_reg.setToolTip("傾き・切片・R²・相関r・直線性誤差[%FS] を計算（線形性の評価）")
        b_reg.clicked.connect(self.run_regression)
        self.ds_fit_check = QtWidgets.QCheckBox("回帰直線を重ねる")
        self.ds_fit_check.setToolTip("回帰実行時に近似曲線（線形）をグラフへ重ねて表示します")
        reg_row = QtWidgets.QHBoxLayout()
        reg_row.addWidget(b_reg); reg_row.addWidget(self.ds_fit_check); reg_row.addStretch(1)
        v.addLayout(reg_row)

        # 統計・正規性・相関行列
        brow = QtWidgets.QHBoxLayout()
        b_desc = QtWidgets.QPushButton("記述統計"); b_desc.clicked.connect(self.show_describe)
        b_desc.setToolTip("平均/中央値/標準偏差/分散/歪度/尖度/四分位 など")
        b_norm = QtWidgets.QPushButton("正規性検定"); b_norm.clicked.connect(self.run_normality)
        b_norm.setToolTip("Shapiro-Wilk 検定（scipy 必要）")
        b_corr = QtWidgets.QPushButton("相関行列"); b_corr.clicked.connect(self.show_corr_matrix)
        b_corr.setToolTip("選択中の全Y系列どうしのピアソン相関を行列で表示")
        brow.addWidget(b_desc); brow.addWidget(b_norm); brow.addWidget(b_corr)
        v.addLayout(brow)

        # 任意関数フィット・検定
        brow2 = QtWidgets.QHBoxLayout()
        b_cfit = QtWidgets.QPushButton("任意関数フィット…")
        b_cfit.setToolTip("モデル式（例: a*exp(-x/b)+c）とパラメータ初期値を指定して\n"
                          "非線形フィット。パラメータ±標準誤差とR²を表示し、\n"
                          "フィット曲線を新データとして重ね描きできます（scipy 必要）。")
        b_cfit.clicked.connect(self.run_custom_fit)
        b_tt = QtWidgets.QPushButton("t検定…")
        b_tt.setToolTip("1標本（母平均と比較）／対応なし2標本（Welch）／対応あり2標本（scipy 必要）")
        b_tt.clicked.connect(self.run_t_test)
        b_an = QtWidgets.QPushButton("ANOVA")
        b_an.setToolTip("一元配置分散分析。選択中の全Y系列を群として比較します（scipy 必要）")
        b_an.clicked.connect(self.run_anova)
        brow2.addWidget(b_cfit); brow2.addWidget(b_tt); brow2.addWidget(b_an)
        v.addLayout(brow2)

        # 主成分分析（PCA）: 選択系列を特徴量として次元圧縮 → 3D表示で確認できる
        v.addWidget(self._bold("主成分分析 (PCA)"))
        pca_hint = QtWidgets.QLabel(
            "選択中のY系列を特徴量として主成分分析し、PC1〜PCk を新しいデータとして作成します。"
            "PC1〜3 を作れば『データ』タブで選び 3D 散布図で確認できます。")
        pca_hint.setWordWrap(True); pca_hint.setStyleSheet("color:#555;")
        v.addWidget(pca_hint)
        prow = QtWidgets.QHBoxLayout()
        prow.addWidget(QtWidgets.QLabel("主成分数"))
        self.pca_ncomp = QtWidgets.QSpinBox(); self.pca_ncomp.setRange(1, 20)
        self.pca_ncomp.setValue(3)
        self.pca_ncomp.setToolTip("取り出す主成分の数。3D散布図で見るなら3を推奨。")
        prow.addWidget(self.pca_ncomp)
        self.pca_std = QtWidgets.QCheckBox("標準化")
        self.pca_std.setChecked(True)
        self.pca_std.setToolTip("各特徴量を平均0・分散1にそろえてから分析（単位が違う列の混在に有効）。")
        prow.addWidget(self.pca_std)
        b_pca = QtWidgets.QPushButton("PCA を実行（選択系列）")
        b_pca.setToolTip("選択中のY系列を特徴量にPCAを実行し、PC列を新データとして作成します。"
                         "scikit-learn があればそれを使用（無ければ numpy で計算）。")
        b_pca.clicked.connect(self.run_pca)
        prow.addWidget(b_pca); prow.addStretch(1)
        v.addLayout(prow)

        self.ds_title = self._bold("結果")
        v.addWidget(self.ds_title)
        hint = QtWidgets.QLabel("右端の「表示」にチェックした項目は、その値をグラフに注記表示します。")
        hint.setWordWrap(True); hint.setStyleSheet("color:#555;")
        v.addWidget(hint)
        self.ds_table = QtWidgets.QTableWidget(0, 3)
        self.ds_table.setHorizontalHeaderLabels(["項目", "値", "表示"])
        hh = self.ds_table.horizontalHeader()
        hh.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        self.ds_table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self._wire_table_export(self.ds_table, "統計解析")
        v.addWidget(self.ds_table, 1)
        return outer

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
        drawbar.addWidget(b_batch2)
        lay.addLayout(drawbar)
        # グラフ上部の系列ON/OFFバー（折れ線/散布図の表示切替）
        self.series_bar = QtWidgets.QScrollArea()
        self.series_bar.setWidgetResizable(True)
        self.series_bar.setFixedHeight(34)
        self.series_bar.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self.series_bar.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.series_bar.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        bar_inner = QtWidgets.QWidget()
        self.series_bar_layout = QtWidgets.QHBoxLayout(bar_inner)
        self.series_bar_layout.setContentsMargins(6, 2, 6, 2)
        self.series_bar.setWidget(bar_inner)
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
        items = [(self.y_list.item(i),) for i in range(self.y_list.count())]
        if not items:
            self.series_bar.setVisible(False)
            return
        self._series_bar_building = True
        for (it,) in items:
            fl, col = it.data(UserRole)
            st = self.series_styles.get(self._style_key(fl, col)) or {}
            checked = it.checkState() == QtCore.Qt.CheckState.Checked
            label = st.get("label") or it.text()
            color = st.get("color") or ("#333" if checked else "#888")
            cb = QtWidgets.QCheckBox(label)
            cb.setChecked(checked)
            cb.setToolTip("右クリック=この系列だけ表示／非表示／すべて表示")
            cb.setStyleSheet(f"QCheckBox {{ color:{color}; "
                             f"font-weight:{'bold' if checked else 'normal'}; }}")
            cb.toggled.connect(lambda on, item=it: self._toggle_series_select(item, on))
            cb.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
            cb.customContextMenuRequested.connect(
                lambda pos, item=it, wdg=cb: self._series_menu(item).exec(wdg.mapToGlobal(pos)))
            lay.addWidget(cb)
        lay.addStretch(1)
        self._series_bar_building = False
        self.series_bar.setVisible(True)

    def _toggle_series_select(self, item, on):
        """系列バーのチェックで左Yリストの選択を切り替える（→自動再描画）。"""
        if getattr(self, "_series_bar_building", False):
            return
        item.setCheckState(QtCore.Qt.CheckState.Checked if on
                           else QtCore.Qt.CheckState.Unchecked)

    def _build_preview(self):
        box = QtWidgets.QGroupBox("データ編集（選択中ファイル・先頭100行）")
        lay = QtWidgets.QVBoxLayout(box); lay.setContentsMargins(4, 4, 4, 4)
        self._preview_label = None
        self._preview_loading = False
        bar = QtWidgets.QHBoxLayout()
        self.edit_check = QtWidgets.QCheckBox("編集可")
        self.edit_check.setToolTip("セルをダブルクリックで編集。値はその場でDataFrameに反映され、グラフにも反映されます。")
        self.edit_check.toggled.connect(self._on_edit_toggle)
        bar.addWidget(self.edit_check)
        for text, slot, tip in [
                ("行追加", self._row_add, "末尾に空行を追加"),
                ("行削除", self._row_del, "選択した行を削除"),
                ("列追加", self._col_add, "新しい数値列を追加"),
                ("編集を戻す", self._data_undo, "データ編集（セル・行・列）を1つ戻す"),
                ("やり直す", self._data_redo, "戻したデータ編集をやり直す"),
                ("CSV保存", self._save_csv, "編集後のデータをCSV/TSVに書き出し")]:
            b = QtWidgets.QPushButton(text); b.setToolTip(tip)
            b.clicked.connect(slot); bar.addWidget(b)
        bar.addStretch(1)
        lay.addLayout(bar)
        self.table = QtWidgets.QTableWidget()
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.itemChanged.connect(self._on_cell_edited)
        # 行選択⇔グラフの点のリンク（JMP風）。グラフの点クリックでも行が選ばれる
        self.table.setToolTip("行を選択するとグラフ上の対応する点がリングで強調されます。\n"
                              "逆にグラフの点（単純な折れ線）をクリックするとこの表の行が選ばれます。")
        self.table.itemSelectionChanged.connect(self._on_preview_selection_changed)
        lay.addWidget(self.table)
        return box

    def _build_statusbar(self):
        self.status = self.statusBar()
        # マウス近傍のデータ値の常時表示（右端。通常のステータス文言とは独立）
        self._hover_label = QtWidgets.QLabel("")
        self._hover_label.setStyleSheet("color:#0a7a55;")
        self.status.addPermanentWidget(self._hover_label)
        fi = f"日本語: {self.font_name}" if self.font_name else "日本語フォント未検出"
        self.status.addPermanentWidget(QtWidgets.QLabel(fi))

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
        l = QtWidgets.QLabel(text); f = l.font(); f.setBold(True); l.setFont(f); return l

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
