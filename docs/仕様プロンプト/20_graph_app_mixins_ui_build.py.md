# [20/30] graph_app_mixins/ui_build.py の仕様

## 指示

- この仕様だけを読んで `graph_app_mixins/ui_build.py` を**完全な形**で実装し出力してください。
- `pass`・`TODO`・「以下省略」・要約・抜粋は**禁止**です。すべてのメソッドを最後まで実装してください。
- 出力が長くて途中で切れた場合は、続けて「続き」と入力されたら**最後まで**出し切ってください。
- このファイルは GUI 構築専用の Mixin です。実際の描画・解析・I/O ロジックは他 Mixin が持ち、ここは**ウィジェットの生成・配置・シグナル接続・初期状態の設定のみ**を担います。

### アプリ全体の前提（このファイルに関係する分）

- Python 3.10+ / GUI=PySide6(Qt6)。Qt は必ず matplotlib 経由で取得する（`graph_app_common` 内で import 済みのものを `from graph_app_common import *` で受け取る）。直接 `from PySide6 import ...` は書かない。
  - `from matplotlib.backends.qt_compat import QtCore, QtGui, QtWidgets`
  - `from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas, NavigationToolbar2QT as NavigationToolbar`
  - `from matplotlib.figure import Figure`
- Qt6 の列挙は**スコープ付き**で書く（例: `QtCore.Qt.CheckState.Checked` / `QtCore.Qt.ItemDataRole.UserRole` / `QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers` / `QtCore.Qt.Orientation.Horizontal` / `QtWidgets.QHeaderView.ResizeMode.Stretch` 等）。短縮形（`QtCore.Qt.Checked` 等）は使わない。
- `GraphApp` は 10 個の Mixin ＋ `QtWidgets.QMainWindow` の多重継承。`__init__` / `closeEvent` は `GraphApp` 本体にあり、各 Mixin は `from graph_app_common import *` で始まる**メソッド束**で、`__init__` を持たない。`@staticmethod` は装飾ごと担当 Mixin に置く。
- 日本語ラベルに `family="monospace"` は使わない（□化け回避）。本ファイルでは matplotlib のフォント指定は行わない（ウィジェット文字列のみ）。
- このファイルは GraphApp 本体が `__init__` の中で各 `_build_*` を呼ぶことを前提とする受け身の Mixin。`self` の属性（`self.series_styles`, `self.font_name`, `self._style_key`, `self._request_redraw`, 各スロットメソッド等）は他 Mixin / 本体が用意している前提で参照する。

---

## ファイルの役割・責務

`UIBuildMixin` という単一クラスを定義する。役割は **GraphApp のメインウィンドウ UI を組み立てること**。具体的には:

- メニューバーの構築（`_build_menu` / `_menu_action`）。
- 中央レイアウト（3 ペインの水平スプリッタ）の構築（`_build_central`）。
- 左の 4 タブ（データ / オシロ・解析 / 高度解析 / データサイエンス）の構築。
- 中央のグラフ描画エリア＋データ編集プレビューの構築。
- 右端のグラフ書式調整パネル（書式コントロール＋系列スタイル表）の構築。
- ステータスバー、ツールチップ一括設定、ライブ更新シグナル配線。
- 小ヘルパ（太字ラベル `_bold`、水平線 `_hline`）。

docstring（モジュール先頭）の趣旨:
`"""UIBuildMixin: GraphApp から分離した UIBuildMixin 群（挙動は本体と同一）。"""`

このクラスは `__init__` を**持たない**。`from graph_app_common import *  # noqa: F401,F403` をモジュール先頭（docstring 直後）に置く。

---

## 依存（import するもの）

```python
# -*- coding: utf-8 -*-
"""UIBuildMixin: GraphApp から分離した UIBuildMixin 群（挙動は本体と同一）。"""
from graph_app_common import *  # noqa: F401,F403
```

これ 1 行のみ。`graph_app_common` のワイルドカード import 経由で、以下が利用可能である前提で使う:

- `QtCore`, `QtGui`, `QtWidgets`（matplotlib 経由）
- `Figure`, `FigureCanvas`, `NavigationToolbar`
- `UserRole`（= `QtCore.Qt.ItemDataRole.UserRole` のエイリアス定数。`it.data(UserRole)` の形で使う）
- `CheckListWidget`（チェックボックス付きリストウィジェットのカスタムクラス）
- モジュール `data_loader`, `plotter`, `analysis`, `mathchan`（属性/定数を参照）

参照する外部モジュール定数（値は当該モジュール側で定義。ここでは**参照のみ**）:

- `data_loader.DELIMITER_LABELS`（dict。`.values()` をコンボに追加）
- `plotter.CHART_TYPES`（chart_combo のアイテム）
- `plotter.LEGEND_LOCS`（legend_loc のアイテム）
- `plotter.TRENDLINES`（trend_combo のアイテム）
- `plotter.eng_125_sequence(lo, hi, unit)`（1-2-5 系列の文字列リストを返す関数）
- `analysis.WINDOWS`（fft_window のアイテム）
- `mathchan.BINARY_OPS`, `mathchan.UNARY_OPS`（math_op のアイテム。`BINARY_OPS + UNARY_OPS` で連結）

---

## 公開 API（メソッド一覧と完全シグネチャ）

すべて `UIBuildMixin` のメソッド。明示しない限りインスタンスメソッド。

### `def _menu_action(self, menu, label, slot, shortcut=None, tip=None)`
- `QtGui.QAction(label, self)` を生成。
- `shortcut` が真なら `act.setShortcut(shortcut)`。
- `tip` が真なら `act.setStatusTip(tip)`。
- `act.triggered.connect(slot)` → `menu.addAction(act)` → `return act`。

### `def _build_menu(self)`
`m = self.menuBar()` を起点に 4 メニューを構築。各項目は `self._menu_action(...)` で追加。正確な構成（順序・ラベル・スロット・ショートカット・tip）:

**ファイル(&F)** メニュー `fm`:
1. `"ファイル追加..."` → `self.add_file`、`"Ctrl+O"`
2. `self.recent_menu = fm.addMenu("最近使ったファイル")`; その直後に `self._rebuild_recent_menu()` を呼ぶ
3. `fm.addSeparator()`
4. `"グラフ画像を保存..."` → `self.save_figure`、`"Ctrl+S"`
5. `"ファイルごとに一括画像出力..."` → `self.batch_export`、`"Ctrl+B"`
6. `"クリップボードにコピー"` → `self.copy_figure`、`"Ctrl+Shift+C"`
7. `fm.addSeparator()`
8. `"設定を保存..."` → `self.save_config_dialog`、`"Ctrl+Shift+S"`
9. `"設定を読み込み..."` → `self.load_config_dialog`、`None`
10. `fm.addSeparator()`
11. `"終了"` → `self.close`、`"Ctrl+Q"`

**表示(&V)** メニュー `vm`:
1. `"グラフを描画"` → `self.draw_graph`、`"F5"`
2. `"全データに合わせる（オートスケール）"` → `self.auto_scale_scope`、`None`

**解析(&A)** メニュー `am`:
1. `"解析実行（ピーク・測定）"` → `self.run_analysis`、`"Ctrl+R"`、`tip="選択中の解析対象系列のピーク・測定値を計算"`
2. `"FFTスペクトル表示"` → `self.show_fft`、`None`

**ヘルプ(&H)** メニュー `hm`:
1. `"使い方"` → `self.show_help`、`"F1"`
2. `"バージョン情報"` → `self.show_about`、`None`

### `def _build_central(self)`
中央ウィジェットと 3 ペインスプリッタを構築:
- `central = QtWidgets.QWidget()`; `self.setCentralWidget(central)`。
- `outer = QtWidgets.QHBoxLayout(central)`; `outer.setContentsMargins(6, 6, 6, 6)`。
- `splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)`; `outer.addWidget(splitter)`。
- **左ペイン**: `tabs = QtWidgets.QTabWidget()`; `self.tabs = tabs`; `tabs.setMinimumWidth(220)`。タブ追加（順序とタイトル厳守）:
  - `self._build_tab_data()` → `"1. データ"`
  - `self._build_tab_scope()` → `"2. オシロ/解析"`
  - `self._build_tab_advanced()` → `"3. 高度解析"`
  - `self._build_tab_datasci()` → `"4. データサイエンス"`
  - `splitter.addWidget(tabs)`
- **中央ペイン**: `center = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)`; `center.addWidget(self._build_plot_area())`; `center.addWidget(self._build_preview())`; `center.setStretchFactor(0, 4)`; `center.setStretchFactor(1, 1)`; `splitter.addWidget(center)`。
- **右ペイン**: `splitter.addWidget(self._build_format_panel())`。
- スプリッタの stretch: `splitter.setStretchFactor(0, 0)`, `(1, 1)`, `(2, 0)`; `splitter.setSizes([360, 680, 400])`。
- 末尾で `self._wire_live_signals()` と `self._add_tooltips()` を呼ぶ。

### `def _build_tab_data(self)` → `QWidget`
データタブ。縦スプリッタで上段（ファイル一覧）と下段（読込設定・X/Y 選択・描画）に分割。
- `w = QtWidgets.QWidget()`; `outer = QtWidgets.QVBoxLayout(w)`; `outer.setContentsMargins(0, 0, 0, 0)`。
- `vsplit = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)`; `outer.addWidget(vsplit)`。

**上段** `top`（`tv = QtWidgets.QVBoxLayout(top)`, `tv.setContentsMargins(2, 2, 2, 2)`）:
- `tv.addWidget(self._bold("読み込み済みファイル"))`。
- ヒント `QLabel`: 文言 `"ファイルを追加（ここにドラッグ&ドロップも可）→ X/Y を選び「グラフを描画」"`。`setWordWrap(True)`、`setStyleSheet("color:#666;")`。
- `self.file_list = QtWidgets.QListWidget()`:
  - `setMinimumHeight(60)`。
  - ツールチップ（複数行）:
    `"読み込んだファイル一覧。選択するとプレビューを表示します。\n長い名前は横スクロール／ホバーで全体を表示。\n縦幅は下の境界線、横幅は左パネルとグラフの境界線をドラッグで変えられます。"`
  - `setTextElideMode(QtCore.Qt.TextElideMode.ElideNone)`、`setWordWrap(False)`。
  - `setHorizontalScrollMode(QtWidgets.QAbstractItemView.ScrollMode.ScrollPerPixel)`。
  - `setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded)`。
  - `setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)`（複数選択可）。
  - `currentRowChanged.connect(self._on_file_selected)`。
  - `tv.addWidget(self.file_list, 1)`。
- ボタン行 `row = QHBoxLayout()`:
  - `b_add = QPushButton("ファイル追加...")` → `clicked.connect(self.add_file)`。
  - `b_del = QPushButton("削除")`、tip `"選択中のファイルを削除（Ctrl/Shift＋クリックで複数選択→まとめて削除）"`、`clicked.connect(self.remove_file)`。
  - `b_clear = QPushButton("全削除")`、tip `"読み込み済みファイルをすべて一覧から削除します。"`、`clicked.connect(self.clear_all_files)`。
  - `row.addWidget(b_add)`; `tv.addLayout(row)`。
  - 2 行目 `row_b = QHBoxLayout()`: `row_b.addWidget(b_del)`; `row_b.addWidget(b_clear)`; `tv.addLayout(row_b)`。
- `vsplit.addWidget(top)`。

**下段** `bottom`（`v = QtWidgets.QVBoxLayout(bottom)`, `v.setContentsMargins(2, 2, 2, 2)`）:
- 区切り・文字コード `grid = QGridLayout()`:
  - `(0,0)` ラベル `"区切り:"`。`self.delim_combo = QComboBox()`; 先頭に `addItem("自動判別")`; その後 `for lbl in data_loader.DELIMITER_LABELS.values(): self.delim_combo.addItem(lbl)`; `(0,1)` に配置。tip `"区切り文字。変更後は「選択中ファイルを再読込」を押してください。"`。
  - `(1,0)` ラベル `"文字コード:"`。`self.enc_combo = QComboBox()`; `addItems(["自動判別", "utf-8-sig", "utf-8", "cp932", "shift_jis", "euc-jp", "utf-16"])`; tip `"文字化けする場合はここで指定し、「選択中ファイルを再読込」を押します。"`; `(1,1)` に配置。
  - `b_reload = QPushButton("選択中ファイルを再読込")`; tip `"区切り・文字コードの変更を反映して読み直します。"`; `clicked.connect(self.reload_current)`; `grid.addWidget(b_reload, 2, 0, 1, 2)`。
  - `v.addLayout(grid)`。
- `v.addWidget(self._hline())`。
- `v.addWidget(QtWidgets.QLabel("X軸（横軸 / ラベル）"))`。
- `self.xleft_check = QCheckBox("一番左の列をX軸にする（位置で固定）")`:
  - tip（複数行）: `"ONにすると各ファイルの『一番左の列』をX軸に使います（列名が違っても適用）。\n複数ファイル／バッチ出力でX軸を固定したいときに便利。\nOFFなら下のコンボで列名を指定します。"`
  - `toggled.connect(self._on_xleft_toggled)`; `v.addWidget(self.xleft_check)`。
- `self.x_combo = QComboBox()`; tip `"横軸に使う列（列名で指定）。波形なら時間列を選びます。"`; `currentTextChanged.connect(self._on_x_changed)`; `v.addWidget(self.x_combo)`。
- `ylab = QLabel("Y軸（値）※チェックした系列を描画（行クリックでON/OFF）")`; `ylab.setWordWrap(True)`; `v.addWidget(ylab)`。
- `self.y_list = CheckListWidget()`:
  - `setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.NoSelection)`。
  - tip `"描画したい系列にチェック。ダブルクリック=その系列だけ表示／右クリック=表示メニュー（この系列だけ／非表示／すべて表示）"`（コード上は 2 文字列の暗黙連結だが、実体は 1 続きの文字列）。
  - `setStyleSheet("QListWidget::indicator { width:16px; height:16px; }")`。
  - `itemChanged.connect(self._on_y_check_changed)`。
  - `itemDoubleClicked.connect(self._on_y_double_clicked)`。
  - `setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)`。
  - `customContextMenuRequested.connect(self._y_list_menu)`。
  - `v.addWidget(self.y_list, 1)`。
- Y ボタン行 `ybtns = QHBoxLayout()`。ループで 3 ボタン生成（テキストとスロットのタプル順）:
  - `("全選択", lambda: self._check_all_y(True))`
  - `("全解除", lambda: self._check_all_y(False))`
  - `("反転", self._invert_y)`
  - 各 `btn = QPushButton(text)`; `btn.clicked.connect(fn)`; `ybtns.addWidget(btn)`; ループ後 `v.addLayout(ybtns)`。
- `self.live_check = QCheckBox("リアルタイム更新（変更を即反映）")`; `setChecked(True)`; tip `"オンにすると設定変更が自動で描画に反映されます。大容量データではオフ推奨。"`; 追加。
- `self.decimate_check = QCheckBox("大容量データを間引き表示")`; `setChecked(True)`; tip `"折れ線/散布図で点数が多いとき、見た目を保ったまま間引いて高速描画します（ズーム時は自動で再サンプルします）。"`; 追加。
- 描画行 `drow = QHBoxLayout()`:
  - `b_draw = QPushButton("グラフを描画 (F5)")`; `setStyleSheet("font-weight:bold; padding:6px;")`; `clicked.connect(self.draw_graph)`。
  - `b_batch2 = QPushButton("一括画像保存...")`; `setStyleSheet("padding:6px;")`; tip `"読み込んだ各ファイルを個別に描画し、ファイル名ごとの画像として一括保存します（タイトル・形式・DPI等は次の画面で調整できます）。"`; `clicked.connect(self.batch_export)`。
  - `drow.addWidget(b_draw, 2)`; `drow.addWidget(b_batch2, 1)`; `v.addLayout(drow)`。
- `vsplit.addWidget(bottom)`; `vsplit.setStretchFactor(0, 0)`; `vsplit.setStretchFactor(1, 1)`; `vsplit.setSizes([140, 520])`; `return w`。

### `def _build_style_box(self)` → `QWidget`
docstring: `"""系列スタイル表（色/線種/軸/種別/誤差列）。書式調整パネルの下段に置く。"""`
- `box = QtWidgets.QWidget()`; `v = QtWidgets.QVBoxLayout(box)`; `v.setContentsMargins(4, 4, 4, 4)`。
- `v.addWidget(self._bold("系列スタイル（系列名はダブルクリックで変更可）"))`。
- `self.style_table = QtWidgets.QTableWidget(0, 9)`。
- 列見出し（9 列、順序厳守）: `["系列名", "色", "線種", "幅", "マーカー", "サイズ", "軸", "種別", "誤差列"]`。
- `self.style_table.horizontalHeader().setStretchLastSection(True)`。
- 編集トリガ: `setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.DoubleClicked | QtWidgets.QAbstractItemView.EditTrigger.EditKeyPressed)`。
- `itemChanged.connect(self._on_style_label_edited)`。
- `v.addWidget(self.style_table, 1)`; `return box`。

### `def _build_format_panel(self)` → `QSplitter`
docstring: `"""右端のグラフ書式調整パネル（上：グラフ書式コントロール／下：系列スタイル表）。"""`
- `split = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)`; `split.setMinimumWidth(360)`。
- `scroll = QtWidgets.QScrollArea()`; `scroll.setWidgetResizable(True)`; `scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)`; `scroll.setWidget(self._build_tab_graph())`; `split.addWidget(scroll)`。
- `split.addWidget(self._build_style_box())`。
- `split.setStretchFactor(0, 3)`; `split.setStretchFactor(1, 2)`; `return split`。

### `def _build_tab_graph(self)` → `QWidget`
右パネル上段のグラフ書式コントロール。`w = QtWidgets.QWidget()`; `v = QtWidgets.QVBoxLayout(w)`。以下を順に積む:

**グラフ種別**:
- `v.addWidget(self._bold("グラフ種別"))`。
- `self.chart_combo = QComboBox()`; `addItems(plotter.CHART_TYPES)`; `currentTextChanged.connect(self._on_chart_type_change)`; 追加。
- `self.hint_label = QLabel()`; `setWordWrap(True)`; `setStyleSheet("color:#0a7a55;")`; 追加。

**タイトル・ラベル・フォント** `form = QGridLayout()`:
- `(0,0)` `"タイトル"`; `self.title_edit = QLineEdit()`; `(0,1,1,3)`。
- `(1,0)` `"X軸名"`; `self.xlabel_edit = QLineEdit()`; `(1,1)`。
- `(1,2)` `"Y軸名"`; `self.ylabel_edit = QLineEdit()`; `(1,3)`。
- `(2,0)` `"文字サイズ 題/軸/目盛"`。スピンボックス 3 個（すべて `setRange(6, 40)`）:
  - `self.fs_title` 値 12、`self.fs_label` 値 10、`self.fs_tick` 値 9。`(2,1)/(2,2)/(2,3)` に配置。
- `(5,0)` `"文字サイズ 凡例/注記"`（**行番号 5**。3・4 行は単位行が使う）:
  - `self.fs_legend` `setRange(6,40)` 値 9、tip `"凡例の文字サイズ"`。
  - `self.fs_annot` `setRange(6,40)` 値 9、tip `"グラフ上に表示する注記（データサイエンス・測定値のチェック表示）の文字サイズ"`。
  - `(5,1)/(5,2)` に配置。
- `(3,0)` `"X単位"`; `self.xunit_edit = QLineEdit()`; `setPlaceholderText("例: ms")`; tip `"X軸ラベルに付ける単位。右の倍率で軸の数値も換算されます。"`; `(3,1)`。
- `(3,2)` `"X倍率"`; `self.xscale_edit = QLineEdit("1")`; tip `"X軸の数値に掛ける倍率。例: 秒→ミリ秒は 1000。"`; `(3,3)`。
- `(4,0)` `"Y単位"`; `self.yunit_edit = QLineEdit()`; `setPlaceholderText("例: mV")`; tip `"Y軸ラベルに付ける単位。右の倍率で軸の数値も換算されます（主軸）。"`; `(4,1)`。
- `(4,2)` `"Y倍率"`; `self.yscale_edit = QLineEdit("1")`; tip `"Y軸の数値に掛ける倍率。例: V→mV は 1000。"`; `(4,3)`。
- `v.addLayout(form)`。
- 注意: グリッド行は `0,1,2,3,4,5` の順で使うが、コード上の生成順は上記のとおり（2 行目スピンの後に 5 行目を作り、その後 3・4 行を作る）。**配置先の行番号が正しければ生成順は問わない**。

**オプション行** `opt = QHBoxLayout()`:
- `self.grid_check = QCheckBox("グリッド")`; `setChecked(True)`。
- `self.legend_check = QCheckBox("凡例")`; `setChecked(True)`。
- `opt.addWidget(self.grid_check)`; `opt.addWidget(self.legend_check)`。
- `opt.addWidget(QtWidgets.QLabel("凡例位置"))`。
- `self.legend_loc = QComboBox()`; `addItems(plotter.LEGEND_LOCS)`; `opt.addWidget(self.legend_loc)`。
- `self.show_filename_check = QCheckBox("凡例にファイル名")`; `setChecked(True)`; tip `"複数ファイル時、凡例の系列名に『ファイル名 | 列名』のように\nファイル名を含めます。オフにすると列名だけになります。"`。
- `self.show_ext_check = QCheckBox("拡張子")`; `setChecked(True)`; tip `"凡例に表示するファイル名に拡張子（.csv など）を含めます。\nオフにすると拡張子を除いた名前になります。"`。
- `opt.addWidget(self.show_filename_check)`; `opt.addWidget(self.show_ext_check)`。
- `self.bg_color = ""`（背景色の状態。空=自動）。
- `self.bg_btn = QPushButton("背景色: 自動")`; tip `"プロット領域の背景色。クリックで色を選択／右クリックで自動に戻す。\n『自動』は通常=白・オシロ=濃色。オシロでも好きな色にできます。"`; `clicked.connect(self._pick_bg_color)`; `setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)`; `customContextMenuRequested.connect(lambda *_: self._reset_bg_color())`; `opt.addWidget(self.bg_btn)`。
- `opt.addStretch(1)`; `v.addLayout(opt)`。

**線の太さ** `lw = QHBoxLayout()`:
- `lw.addWidget(QtWidgets.QLabel("線の太さ  枠線"))`（「線の太さ」と「枠線」の間は半角スペース 2 つ）。
- `self.frame_width = QDoubleSpinBox()`; `setRange(0.0, 6.0)`; `setSingleStep(0.2)`; `setValue(0.8)`; tip `"グラフの外枠（軸の枠線）の太さ。0 で枠を消します。"`; `lw.addWidget(self.frame_width)`。
- `lw.addWidget(QtWidgets.QLabel("グリッド線"))`。
- `self.grid_width = QDoubleSpinBox()`; `setRange(0.2, 6.0)`; `setSingleStep(0.2)`; `setValue(0.8)`; tip `"グリッド線の太さ（「グリッド」オン時）。"`; `lw.addWidget(self.grid_width)`。
- `lw.addStretch(1)`; `v.addLayout(lw)`。
- 注意（落とし穴）: `grid_width` の最小値は **0.2**（0 にできない）。描画側で grid の linewidth に `None` を渡さない（指定があるときだけ渡す）規約があるが、本ファイルはウィジェット定義のみで描画はしない。

**軸範囲・対数** `ax = QGridLayout()`:
- `(0,0)` `"X範囲 min/max"`; `self.xmin = QLineEdit()` `setPlaceholderText("自動")`; `self.xmax = QLineEdit()` `setPlaceholderText("自動")`; `(0,1)/(0,2)`。
- `self.xlog = QCheckBox("X対数")`; `(0,3)`。
- `(1,0)` `"Y範囲 min/max"`; `self.ymin = QLineEdit()` `setPlaceholderText("自動")`; `self.ymax = QLineEdit()` `setPlaceholderText("自動")`; `(1,1)/(1,2)`。
- `self.ylog = QCheckBox("Y対数")`; `(1,3)`。
- `(2,0)` `"目盛り間隔 X/Y"`; `self.xtick_edit = QLineEdit()` `setPlaceholderText("自動")` tip `"X軸の目盛り間隔（1メモリの値）。空欄=自動。例: 0.5。\n折れ線/散布図の数値軸で有効。対数軸・カテゴリ軸では無効。"`; `self.ytick_edit = QLineEdit()` `setPlaceholderText("自動")` tip `"Y軸の目盛り間隔（1メモリの値）。空欄=自動。例: 10。対数軸では無効。"`; `(2,1)/(2,2)`。
- `v.addLayout(ax)`。

**近似曲線・データラベル** `tl = QHBoxLayout()`:
- `tl.addWidget(QtWidgets.QLabel("近似曲線"))`。
- `self.trend_combo = QComboBox()`; `addItems(plotter.TRENDLINES)`; tip `"折れ線/散布図の各系列に近似曲線を重ねる"`; 追加。
- `tl.addWidget(QtWidgets.QLabel("次数"))`; `self.trend_degree = QSpinBox()`; `setRange(1, 6)`; `setValue(2)`; tip `"多項式近似の次数"`; 追加。
- `tl.addWidget(QtWidgets.QLabel("窓"))`; `self.trend_window = QSpinBox()`; `setRange(2, 9999)`; `setValue(5)`; tip `"移動平均の窓幅"`; 追加。
- `self.trend_color = ""`（近似曲線色。空=自動=系列と同色）。
- `self.trend_color_btn = QPushButton("色: 自動")`; tip `"近似曲線の色。クリックで色を選択／右クリックで自動（系列と同じ色）に戻す。"`; `clicked.connect(self._pick_trend_color)`; `setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)`; `customContextMenuRequested.connect(lambda *_: self._reset_trend_color())`; `tl.addWidget(self.trend_color_btn)`。
- `self.trend_eq = QCheckBox("数式/R²")`; `setChecked(True)`; `tl.addWidget(self.trend_eq)`。
- `self.data_labels_check = QCheckBox("データラベル")`; tip `"各データ点/棒に値を表示（点数が多い場合は間引き）"`; `tl.addWidget(self.data_labels_check)`。
- `tl.addStretch(1)`; `v.addLayout(tl)`。

**ビン数・パーセント** `extra = QHBoxLayout()`:
- `self.bins_caption = QLabel("ビン数:")`; `extra.addWidget(self.bins_caption)`。
- `self.bins_spin = QSpinBox()`; `setRange(1, 500)`; `setValue(30)`; `extra.addWidget(self.bins_spin)`。
- `self.pct_check = QCheckBox("円グラフ％表示")`; `setChecked(True)`; `extra.addWidget(self.pct_check)`; `extra.addStretch(1)`。
- `v.addLayout(extra)`。

**縦横比** `ar = QHBoxLayout()`:
- `ar.addWidget(QtWidgets.QLabel("縦横比"))`。
- `self.aspect_combo = QComboBox()`; `addItems(["自動（画面に合わせる）", "16:9", "4:3", "3:2", "1:1", "9:16（縦）", "A4横", "A4縦", "カスタム"])`; tip `"プロット領域の縦横比を固定します（画面表示・画像出力の両方に反映）。「自動」はウィンドウに合わせます。"`; `ar.addWidget(self.aspect_combo)`。
- `ar.addWidget(QtWidgets.QLabel("カスタム W:H"))`。
- `self.aspect_w = QSpinBox()`; `setRange(1, 100)`; `setValue(16)`。
- `self.aspect_h = QSpinBox()`; `setRange(1, 100)`; `setValue(9)`。
- `ar.addWidget(self.aspect_w)`; `ar.addWidget(QtWidgets.QLabel(":"))`; `ar.addWidget(self.aspect_h)`; `ar.addStretch(1)`; `v.addLayout(ar)`。
- `self.aspect_combo.currentTextChanged.connect(self._on_aspect_changed)`; その直後に `self._on_aspect_changed()` を**呼ぶ**（初期反映）。

**画像出力**:
- `v.addWidget(self._hline())`; `v.addWidget(self._bold("画像出力"))`。
- `exp = QHBoxLayout()`:
  - `exp.addWidget(QtWidgets.QLabel("解像度 DPI"))`。
  - `self.dpi_spin = QSpinBox()`; `setRange(50, 1200)`; `setSingleStep(50)`; `setValue(150)`; 追加。
  - `self.transparent_check = QCheckBox("背景透過")`; 追加。
  - `exp.addStretch(1)`; `v.addLayout(exp)`。
- `exp2 = QHBoxLayout()`:
  - `b_save = QPushButton("画像を保存...")`; `clicked.connect(self.save_figure)`。
  - `b_copy = QPushButton("クリップボードにコピー")`; `clicked.connect(self.copy_figure)`。
  - `exp2.addWidget(b_save)`; `exp2.addWidget(b_copy)`; `v.addLayout(exp2)`。
- `b_batch = QPushButton("ファイルごとに一括出力...")`; tip `"読み込んだ各ファイルを、現在の設定（種別・選択列名・スタイル等）で個別に描画し、ファイル名ごとの画像として一括保存します。"`; `clicked.connect(self.batch_export)`; `v.addWidget(b_batch)`。
- `v.addStretch(1)`; `return w`。

### `def _build_tab_scope(self)` → `QWidget`
オシロ/解析タブ。`w = QtWidgets.QWidget()`; `v = QtWidgets.QVBoxLayout(w)`。

- `self.scope_check = QCheckBox("オシロスコープ表示（折れ線/散布図）")`; `v.addWidget(self.scope_check)`。
- `g = QGridLayout()`（div 設定）:
  - `(0,0)` `"time/div [s]"`; `self.tdiv = QComboBox()` `setEditable(True)`; `addItems(plotter.eng_125_sequence(1e-9, 1.0, "s"))`; `setCurrentText("1ms")`; `(0,1)`。
  - `(0,2)` `"V/div"`; `self.vdiv = QComboBox()` `setEditable(True)`; `addItems(plotter.eng_125_sequence(1e-3, 100.0, ""))`; `setCurrentText("500m")`; `(0,3)`。
  - `(1,0)` `"X位置(中心)"`; `self.xpos = QLineEdit("0")`; `(1,1)`。
  - `(1,2)` `"Y位置(中心)"`; `self.ypos = QLineEdit("0")`; `(1,3)`。
  - `(2,0)` `"X div数"`; `self.xdivs = QSpinBox()` `setRange(2, 20)` `setValue(10)`; `(2,1)`。
  - `(2,2)` `"Y div数"`; `self.ydivs = QSpinBox()` `setRange(2, 20)` `setValue(8)`; `(2,3)`。
  - `v.addLayout(g)`。
- `b_auto = QPushButton("自動スケール（解析対象に合わせる）")`; `clicked.connect(self.auto_scale_scope)`; `v.addWidget(b_auto)`。
- `scope_hint = QLabel("💡 オシロ表示中はグラフを直接操作可：左ドラッグ=位置移動／右ドラッグ=time/V/div／ホイール=time/div・Shift+ホイール=V/div（ドラッグ中は数値を表示）")`; `setWordWrap(True)`; `setStyleSheet("color:#0a7a55; font-size:11px;")`; `v.addWidget(scope_hint)`。
- `v.addWidget(self._hline())`。
- 解析対象行 `row = QHBoxLayout()`: `row.addWidget(QtWidgets.QLabel("解析対象:"))`; `self.analysis_target = QComboBox()`; `row.addWidget(self.analysis_target, 1)`; `v.addLayout(row)`。
- `row2 = QHBoxLayout()`:
  - `row2.addWidget(QtWidgets.QLabel("ピーク数 N:"))`; `self.npeaks = QSpinBox()` `setRange(1, 50)` `setValue(5)`; 追加。
  - `row2.addWidget(QtWidgets.QLabel("平滑化(点):"))`; `self.smooth_spin = QSpinBox()` `setRange(0, 501)` `setSingleStep(2)` `setValue(0)`; tip `"ノイズの多い実測データで偽ピークを抑える。0=平滑化なし。窓の点数（奇数推奨）。"`; 追加。
  - `row2.addStretch(1)`; `v.addLayout(row2)`。
- `self.show_peaks_check = QCheckBox("ピークをグラフに表示")`; `setChecked(False)`; `v.addWidget(...)`。
- `self.window_meas_check = QCheckBox("表示範囲のみ測定（ズーム/オシロ窓に追従）")`; tip `"オンにすると、画面に見えているX範囲だけを対象に解析します。"`; `v.addWidget(...)`。
- 解析アクション 4 ボタンを 2 段に分けて配置（1 行に詰めると見切れるため）:
  - `b_an = QPushButton("解析実行")`; `clicked.connect(self.run_analysis)`; tip `"解析対象コンボで選んだ1系列のピーク・測定を下の表に表示"`。
  - `b_all = QPushButton("全系列を解析…")`; tip `"選択中の全系列のピーク・測定を別ウィンドウに一覧表示（CSV保存可）"`; `clicked.connect(self.analyze_all_series)`。
  - `b_fft = QPushButton("FFTスペクトル表示")`; `clicked.connect(self.show_fft)`; tip `"選択中の全系列のFFTを1枚に重ね描き（系列ごとに色分け）"`。
  - `b_cur = QPushButton("カーソル測定")`; `setCheckable(True)`; tip `"グラフを2回クリックして Δt・ΔV・1/Δt を測ります"`; `toggled.connect(self.toggle_cursors)`; `self.cursor_btn = b_cur`。
  - 1 段目 `brow = QHBoxLayout()`: `brow.addWidget(b_an)`; `brow.addWidget(b_all)`; `v.addLayout(brow)`。
  - 2 段目 `brow2 = QHBoxLayout()`: `brow2.addWidget(b_fft)`; `brow2.addWidget(b_cur)`; `v.addLayout(brow2)`。
- `v.addWidget(self._bold("ピーク（第1=最大）"))`。
- `self.peak_table = QtWidgets.QTableWidget(0, 3)`; 見出し `["順位", "時間/周波数", "値"]`; `horizontalHeader().setStretchLastSection(True)`; `setMaximumHeight(160)`; `v.addWidget(self.peak_table)`。
- `v.addWidget(self._bold("測定値（右端「表示」でグラフに注記）"))`。
- `self.meas_table = QtWidgets.QTableWidget(0, 3)`; 見出し `["項目", "値", "表示"]`。
  - `mh = self.meas_table.horizontalHeader()`; `mh.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)`; `mh.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Stretch)`; `mh.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)`。
  - `setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)`; `v.addWidget(self.meas_table, 1)`。
- 統計・トレンド・位相 `srow = QHBoxLayout()`:
  - `b_stat = QPushButton("サイクル統計")`; `clicked.connect(self.show_cycle_stats)`。
  - `b_trend = QPushButton("トレンド表示")`; `clicked.connect(self.show_trend)`。
  - `b_pstat = QPushButton("パラメータ統計…")`; tip `"サイクルごとの統計（平均/最大/最小/σ）とパラメータ間演算を別ウィンドウで表示"`; `clicked.connect(self.show_param_stats)`。
  - `srow.addWidget(b_stat)`; `srow.addWidget(b_trend)`; `srow.addWidget(b_pstat)`; `v.addLayout(srow)`。
- 位相行 `prow = QHBoxLayout()`:
  - `prow.addWidget(QtWidgets.QLabel("位相差 対象2:"))`; `self.phase_target2 = QComboBox()`; `prow.addWidget(self.phase_target2, 1)`。
  - `b_phase = QPushButton("位相差/遅延")`; `clicked.connect(self.show_phase)`; `prow.addWidget(b_phase)`; `v.addLayout(prow)`。
- `return w`。

### `def _build_tab_advanced(self)` → `QScrollArea`
高度解析タブ。スクロール内に詰める。
- `outer = QtWidgets.QScrollArea()`; `outer.setWidgetResizable(True)`; `w = QtWidgets.QWidget()`; `outer.setWidget(w)`; `v = QtWidgets.QVBoxLayout(w)`。

**数学チャンネル**:
- `v.addWidget(self._bold("数学チャンネル（演算で新しい波形を作成）"))`。
- `mg = QGridLayout()`:
  - `(0,0)` `"演算"`; `self.math_op = QComboBox()`; `addItems(mathchan.BINARY_OPS + mathchan.UNARY_OPS)`; `currentTextChanged.connect(self._on_math_op_change)`; `(0,1,1,3)`。
  - `(1,0)` `"A"`; `self.math_a = QComboBox()`; `(1,1)`。
  - `self.math_b_label = QLabel("B")`; `(1,2)`; `self.math_b = QComboBox()`; `(1,3)`。
  - `self.math_param_label = QLabel("パラメータ")`; `(2,0)`; `self.math_param = QLineEdit("5")`; tip `"移動平均=窓長(点)、ローパス=カットオフ[Hz]"`; `(2,1)`。
  - `b_math = QPushButton("数学チャンネルを作成")`; `clicked.connect(self.create_math_channel)`; `(2,2,1,2)`。
  - `v.addLayout(mg)`。
- 任意数式 `eg = QGridLayout()`:
  - `(0,0)` `"数式"`; `self.math_expr = QLineEdit()`; `setPlaceholderText("例: sqrt(A**2+B**2) / sin(2*pi*t)*VAR1 / A-VAR1")`; tip（複数行）: `"変数: A=対象A, B=対象B, t=時間, VAR1, VAR2, 定数 pi/e。\n関数: sin/cos/tan/asin/.../exp/log/log10/log2/sqrt/abs/sign/min/max/clip/where。"`; `(0,1,1,3)`。
  - `(1,0)` `"VAR1"`; `self.math_var1 = QLineEdit("1")`; `(1,1)`。
  - `(1,2)` `"VAR2"`; `self.math_var2 = QLineEdit("0")`; `(1,3)`。
  - `b_expr = QPushButton("数式でチャンネル作成")`; `clicked.connect(self.create_math_expr)`; `(2,0,1,4)`。
  - `v.addLayout(eg)`。
- `v.addWidget(self._hline())`。

**FFT 詳細**:
- `v.addWidget(self._bold("FFT 詳細（窓・dB・THD/SNR・スペクトログラム）"))`。
- `fg = QGridLayout()`:
  - `(0,0)` `"窓関数"`; `self.fft_window = QComboBox()`; `addItems(analysis.WINDOWS)`; `setCurrentText("hann")`; `(0,1)`。
  - `self.fft_db = QCheckBox("dB表示")`; `(0,2)`。
  - `b_m = QPushButton("THD/SNR等を計算")`; `clicked.connect(self.compute_fft_metrics)`; `(1,0,1,2)`。
  - `b_sp = QPushButton("スペクトログラム")`; `clicked.connect(self.show_spectrogram)`; `(1,2,1,1)`。
  - `v.addLayout(fg)`。
- `self.fft_metrics = QtWidgets.QTableWidget(0, 2)`; 見出し `["指標", "値"]`; `horizontalHeader().setStretchLastSection(True)`; `setMaximumHeight(170)`; `v.addWidget(self.fft_metrics)`。
- `v.addWidget(self._hline())`。

**マスク試験 / アイ / ジッタ**:
- `v.addWidget(self._bold("マスク試験 / アイダイアグラム / ジッタ"))`。
- `mk = QGridLayout()`:
  - `(0,0)` `"上限"`; `self.mask_upper = QLineEdit()` `setPlaceholderText("なし")`; `(0,1)`。
  - `(0,2)` `"下限"`; `self.mask_lower = QLineEdit()` `setPlaceholderText("なし")`; `(0,3)`。
  - `b_mask = QPushButton("マスク判定")`; `clicked.connect(self.run_mask_test)`; `(1,0,1,2)`。
  - `(2,0,1,2)` `"シンボルレート[Hz]/周期[s]"`（colspan 2）。`self.eye_rate = QLineEdit("1e6")`; `(2,2)`。
  - `b_eye = QPushButton("アイダイアグラム")`; `clicked.connect(self.show_eye_diagram)`; `(2,3)`。
  - `b_jit = QPushButton("ジッタ解析(TIE)")`; `clicked.connect(self.run_jitter)`; `(1,2,1,2)`。
  - `v.addLayout(mk)`。
- `self.adv_result = QLabel("")`; `setWordWrap(True)`; `setStyleSheet("color:#0a3;")`; `v.addWidget(self.adv_result)`。
- `v.addWidget(self._hline())`。

**シリアルプロトコル解読**:
- `v.addWidget(self._bold("シリアルプロトコル解読"))`。
- `pg = QGridLayout()`:
  - `(0,0)` `"プロトコル"`; `self.proto_combo = QComboBox()`; `addItems(["UART", "I2C", "SPI"])`; `currentTextChanged.connect(self._on_proto_change)`; `(0,1)`。
  - `(0,2)` `"ボーレート/不使用"`; `self.proto_baud = QLineEdit("115200")`; `(0,3)`。
  - `self.proto_ch_labels = [QtWidgets.QLabel("Ch1"), QtWidgets.QLabel("Ch2"), QtWidgets.QLabel("Ch3")]`。
  - `self.proto_ch = [QtWidgets.QComboBox(), QtWidgets.QComboBox(), QtWidgets.QComboBox()]`。
  - `for i in range(3): pg.addWidget(self.proto_ch_labels[i], 1 + i, 0); pg.addWidget(self.proto_ch[i], 1 + i, 1, 1, 3)`（行 1,2,3 に Ch1/Ch2/Ch3）。
  - `b_dec = QPushButton("解読")`; `clicked.connect(self.decode_protocol)`; `(4,0,1,4)`。
  - `v.addLayout(pg)`。
- `self.proto_table = QtWidgets.QTableWidget(0, 4)`; 見出し `["時刻", "種別", "値(hex)", "備考"]`; `horizontalHeader().setStretchLastSection(True)`; `v.addWidget(self.proto_table, 1)`。
- 末尾で初期状態を反映: `self._on_math_op_change(self.math_op.currentText())`; `self._on_proto_change("UART")`; `return outer`。

### `def _build_tab_datasci(self)` → `QScrollArea`
データサイエンスタブ。
- `outer = QtWidgets.QScrollArea()`; `outer.setWidgetResizable(True)`; `w = QtWidgets.QWidget()`; `outer.setWidget(w)`; `v = QtWidgets.QVBoxLayout(w)`。
- `v.addWidget(self._bold("データサイエンス（回帰・統計・相関）"))`。
- `info = QLabel("選択中のY系列を、現在のX軸列に対して解析します。データタブでX軸とY系列を選んでから実行してください。")`; `setWordWrap(True)`; `setStyleSheet("color:#555;")`; `v.addWidget(info)`。
- 対象行 `row = QHBoxLayout()`: `row.addWidget(QtWidgets.QLabel("対象:"))`; `self.ds_target = QComboBox()`; tip `"解析するY系列。データタブでY系列を選ぶと候補に出ます"`; `row.addWidget(self.ds_target, 1)`; `v.addLayout(row)`。
- 回帰:
  - `b_reg = QPushButton("線形回帰（Y vs X）")`; tip `"傾き・切片・R²・相関r・直線性誤差[%FS] を計算（線形性の評価）"`; `clicked.connect(self.run_regression)`。
  - `self.ds_fit_check = QCheckBox("回帰直線をグラフに重ねる")`; tip `"回帰実行時に近似曲線（線形）をグラフへ重ねて表示します"`。
  - `reg_row = QHBoxLayout()`: `reg_row.addWidget(b_reg)`; `reg_row.addWidget(self.ds_fit_check)`; `reg_row.addStretch(1)`; `v.addLayout(reg_row)`。
- 統計・正規性・相関 `brow = QHBoxLayout()`:
  - `b_desc = QPushButton("記述統計")`; `clicked.connect(self.show_describe)`; tip `"平均/中央値/標準偏差/分散/歪度/尖度/四分位 など"`。
  - `b_norm = QPushButton("正規性検定")`; `clicked.connect(self.run_normality)`; tip `"Shapiro-Wilk 検定（scipy 必要）"`。
  - `b_corr = QPushButton("相関行列（選択系列）")`; `clicked.connect(self.show_corr_matrix)`; tip `"選択中の全Y系列どうしのピアソン相関を行列で表示"`。
  - `brow.addWidget(b_desc)`; `brow.addWidget(b_norm)`; `brow.addWidget(b_corr)`; `v.addLayout(brow)`。
- `self.ds_title = self._bold("結果")`; `v.addWidget(self.ds_title)`（注: `_bold` の戻り `QLabel` を `self.ds_title` に保持する）。
- `hint = QLabel("右端の「表示」にチェックした項目は、その値をグラフに注記表示します。")`; `setWordWrap(True)`; `setStyleSheet("color:#555;")`; `v.addWidget(hint)`。
- `self.ds_table = QtWidgets.QTableWidget(0, 3)`; 見出し `["項目", "値", "表示"]`。
  - `hh = self.ds_table.horizontalHeader()`; `hh.setSectionResizeMode(0, Stretch)`; `(1, Stretch)`; `(2, ResizeToContents)`（`QtWidgets.QHeaderView.ResizeMode.*`）。
  - `setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)`; `v.addWidget(self.ds_table, 1)`。
- `return outer`。

### `def _build_plot_area(self)` → `QWidget`
中央のグラフ描画エリア。
- `wrap = QtWidgets.QWidget()`; `lay = QtWidgets.QVBoxLayout(wrap)`; `lay.setContentsMargins(0, 0, 0, 0)`。
- 系列 ON/OFF バー（折れ線/散布図用）:
  - `self.series_bar = QtWidgets.QScrollArea()`; `setWidgetResizable(True)`; `setFixedHeight(34)`; `setFrameShape(QtWidgets.QFrame.Shape.NoFrame)`。
  - `setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded)`; `setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)`。
  - `bar_inner = QtWidgets.QWidget()`; `self.series_bar_layout = QtWidgets.QHBoxLayout(bar_inner)`; `setContentsMargins(6, 2, 6, 2)`; `self.series_bar.setWidget(bar_inner)`。
  - `self.series_bar.setVisible(False)`; `lay.addWidget(self.series_bar)`。
- matplotlib:
  - `self.fig = Figure(figsize=(6, 4.4), dpi=100)`。
  - `self.ax = self.fig.add_subplot(111)`。
  - `self.canvas = FigureCanvas(self.fig)`。
  - `self.toolbar = NavigationToolbar(self.canvas, wrap)`。
  - `lay.addWidget(self.toolbar)`; `lay.addWidget(self.canvas, 1)`。
- 状態の初期化:
  - `self._plotted_artists = []`（コメント: `[(label, artist), ...] 系列バー連携用`）。
  - `self._style_artists = {}`（コメント: `skey -> Line2D（単純な折れ線のみ：スタイル即時反映用）`）。
  - `self._drawing = False`（`draw_graph` 再入防止フラグ）。
  - `self._scope_drag = None`; `self._scope_ov = None`。
- mpl イベント接続:
  - `self.canvas.mpl_connect("button_press_event", self._scope_on_press)`
  - `self.canvas.mpl_connect("motion_notify_event", self._scope_on_motion)`
  - `self.canvas.mpl_connect("button_release_event", self._scope_on_release)`
  - `self.canvas.mpl_connect("scroll_event", self._scope_on_scroll)`
- `self._draw_placeholder()`; `return wrap`。

### `def _rebuild_series_bar(self, chart_type=None)`
docstring（趣旨）: グラフ上部の系列選択バーを作り直す（折れ線/散布図のみ）。利用可能な全 Y 系列をチェックボックスで表示し、ここで ON/OFF すると左の Y 軸選択と同期して描画される。左でチェックしなくても、データを読み込めば上のバーに系列が並ぶ。

アルゴリズム:
1. `chart_type = chart_type or self.chart_combo.currentText()`。
2. `lay = self.series_bar_layout`。既存ウィジェットを全削除: `while lay.count(): it = lay.takeAt(0); if it.widget(): it.widget().deleteLater()`。
3. `if chart_type not in ("折れ線", "散布図"): self.series_bar.setVisible(False); return`。
4. `items = [(self.y_list.item(i),) for i in range(self.y_list.count())]`。`if not items: self.series_bar.setVisible(False); return`。
5. `self._series_bar_building = True`（再入抑止フラグ。トグルシグナルが構築中に発火しても無視させる）。
6. 各アイテムに対し:
   - `fl, col = it.data(UserRole)`（item の UserRole データは `(ファイルラベル, 列名)` のタプル）。
   - `st = self.series_styles.get(self._style_key(fl, col)) or {}`。
   - `checked = it.checkState() == QtCore.Qt.CheckState.Checked`。
   - `label = st.get("label") or it.text()`。
   - `color = st.get("color") or ("#333" if checked else "#888")`（チェック時は濃いグレー、未チェックは薄いグレー）。
   - `cb = QtWidgets.QCheckBox(label)`; `cb.setChecked(checked)`; tip `"右クリック=この系列だけ表示／非表示／すべて表示"`。
   - スタイルシート: `f"QCheckBox {{ color:{color}; font-weight:{'bold' if checked else 'normal'}; }}"`（チェック時のみ太字）。
   - `cb.toggled.connect(lambda on, item=it: self._toggle_series_select(item, on))`（`item=it` でループ変数を束縛）。
   - `cb.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)`。
   - `cb.customContextMenuRequested.connect(lambda pos, item=it, wdg=cb: self._series_menu(item).exec(wdg.mapToGlobal(pos)))`。
   - `lay.addWidget(cb)`。
7. `lay.addStretch(1)`; `self._series_bar_building = False`; `self.series_bar.setVisible(True)`。

### `def _toggle_series_select(self, item, on)`
docstring（趣旨）: 系列バーのチェックで左 Y リストの選択を切り替える（→自動再描画）。
- `if getattr(self, "_series_bar_building", False): return`（構築中は無視）。
- `item.setCheckState(QtCore.Qt.CheckState.Checked if on else QtCore.Qt.CheckState.Unchecked)`（左リスト側を変えると、その `itemChanged` 経由で再描画が走る）。

### `def _build_preview(self)` → `QGroupBox`
中央下のデータ編集プレビュー。
- `box = QtWidgets.QGroupBox("データ編集（選択中ファイル・先頭100行）")`; `lay = QtWidgets.QVBoxLayout(box)`; `lay.setContentsMargins(4, 4, 4, 4)`。
- `self._preview_label = None`; `self._preview_loading = False`（状態初期化）。
- ツールバー行 `bar = QHBoxLayout()`:
  - `self.edit_check = QCheckBox("編集可")`; tip `"セルをダブルクリックで編集。値はその場でDataFrameに反映され、グラフにも反映されます。"`; `toggled.connect(self._on_edit_toggle)`; `bar.addWidget(self.edit_check)`。
  - 4 ボタンをループで生成（`(text, slot, tip)` のリスト、順序厳守）:
    - `("行追加", self._row_add, "末尾に空行を追加")`
    - `("行削除", self._row_del, "選択した行を削除")`
    - `("列追加", self._col_add, "新しい数値列を追加")`
    - `("CSV保存", self._save_csv, "編集後のデータをCSV/TSVに書き出し")`
    - 各 `b = QPushButton(text)`; `b.setToolTip(tip)`; `b.clicked.connect(slot)`; `bar.addWidget(b)`。
  - `bar.addStretch(1)`; `lay.addLayout(bar)`。
- `self.table = QtWidgets.QTableWidget()`; `setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)`; `setAlternatingRowColors(True)`; `itemChanged.connect(self._on_cell_edited)`; `lay.addWidget(self.table)`。
- `return box`。

### `def _build_statusbar(self)`
- `self.status = self.statusBar()`。
- `fi = f"日本語: {self.font_name}" if self.font_name else "日本語フォント未検出"`（`self.font_name` は本体が用意した日本語フォント名。検出失敗時は空/None）。
- `self.status.addPermanentWidget(QtWidgets.QLabel(fi))`。

### `@staticmethod def _bold(text)`
- `l = QtWidgets.QLabel(text)`; `f = l.font()`; `f.setBold(True)`; `l.setFont(f)`; `return l`（太字の `QLabel` を返す）。
- `@staticmethod` を装飾ごとこの Mixin に置く（Mixin 規約）。

### `@staticmethod def _hline()`
- `ln = QtWidgets.QFrame()`; `ln.setFrameShape(QtWidgets.QFrame.Shape.HLine)`; `ln.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)`; `return ln`（水平区切り線）。
- `@staticmethod`。

### `def _wire_live_signals(self)`
docstring: `"""各コントロールの変更を（リアルタイム更新ON時に）自動再描画へつなぐ。"""`
`r = self._request_redraw` を取り、以下を `r` に接続する（接続するシグナルは種類で異なる）:

- `self.chart_combo.currentTextChanged.connect(r)`。
- `textChanged` → `r`: `(self.title_edit, self.xlabel_edit, self.ylabel_edit, self.xunit_edit, self.yunit_edit, self.xscale_edit, self.yscale_edit)`。
- `valueChanged` → `r`: `(self.fs_title, self.fs_label, self.fs_tick, self.fs_legend, self.fs_annot, self.bins_spin, self.frame_width, self.grid_width)`。
- `toggled` → `r`: `(self.grid_check, self.legend_check, self.pct_check, self.xlog, self.ylog, self.show_filename_check, self.show_ext_check)`。
- `self.legend_loc.currentTextChanged.connect(r)`。
- 近似曲線・データラベル:
  - `self.trend_combo.currentTextChanged.connect(r)`。
  - `valueChanged` → `r`: `(self.trend_degree, self.trend_window)`。
  - `toggled` → `r`: `(self.trend_eq, self.data_labels_check)`。
- 縦横比（コンボは `_on_aspect_changed` 経由で再描画するので**ここでは接続しない**。W/H は直接）: `valueChanged` → `r`: `(self.aspect_w, self.aspect_h)`。
- `editingFinished` → `r`: `(self.xmin, self.xmax, self.ymin, self.ymax, self.xtick_edit, self.ytick_edit)`。
- オシロ:
  - `self.scope_check.toggled.connect(r)`。
  - `currentTextChanged` → `r`: `(self.tdiv, self.vdiv)`。
  - `editingFinished` → `r`: `(self.xpos, self.ypos)`。
  - `valueChanged` → `r`: `(self.xdivs, self.ydivs)`。
  - `self.show_peaks_check.toggled.connect(r)`。
  - `self.npeaks.valueChanged.connect(r)`。
  - `self.smooth_spin.valueChanged.connect(r)`。

### `def _add_tooltips(self)`
`tips` 辞書（キー=ウィジェット、値=ツールチップ文字列）を作り、`for w, t in tips.items(): w.setToolTip(t)` で一括適用。辞書内容（**正確な文言**）:

- `self.legend_loc`: `"凡例の表示位置"`
- `self.xlog`: `"X軸を対数目盛に（0以下の値は表示できません）"`
- `self.ylog`: `"Y軸を対数目盛に（0以下の値は表示できません）"`
- `self.bins_spin`: `"ヒストグラムの区間数（ヒストグラム選択時のみ有効）"`
- `self.pct_check`: `"円グラフでパーセント表示（円グラフ選択時のみ有効）"`
- `self.xmin`: `"X軸の最小値。空欄で自動。指数表記(1e-3)も可"`
- `self.xmax`: `"X軸の最大値。空欄で自動"`
- `self.ymin`: `"Y軸の最小値。空欄で自動"`
- `self.ymax`: `"Y軸の最大値。空欄で自動"`
- `self.dpi_spin`: `"保存画像の解像度。印刷向けは300以上"`
- `self.transparent_check`: `"保存時に背景を透明にします（PNG/PDF/SVG）"`
- `self.analysis_target`: `"解析するY系列。データタブでY系列を選ぶと候補に出ます"`
- `self.npeaks`: `"検出するピークの個数（第1〜第N）"`
- `self.show_peaks_check`: `"検出ピークを折れ線/散布図に重ねて表示"`
- `self.scope_check`: `"オシロスコープ風のdiv表示（折れ線/散布図）"`
- `self.tdiv`: `"1目盛りあたりの時間。1e-3 のような指数表記も可"`
- `self.vdiv`: `"1目盛りあたりの値。1e-3 のような指数表記も可"`
- `self.xpos`: `"表示の中心時間"`
- `self.ypos`: `"表示の中心値"`

注: 一部のウィジェット（`legend_loc`, `xlog` 等）は構築時にも tip 未設定 or 別 tip があるが、ここで上書き設定される。`_add_tooltips` は `_build_central` の末尾で呼ばれるので、上記の値が最終的に有効。

---

## 定数・データ・正確な文字列（再現必須）

### 列見出し（テーブル）
- `style_table`（9 列）: `["系列名", "色", "線種", "幅", "マーカー", "サイズ", "軸", "種別", "誤差列"]`
- `peak_table`（3 列）: `["順位", "時間/周波数", "値"]`
- `meas_table`（3 列）: `["項目", "値", "表示"]`（列 0,1=Stretch、列 2=ResizeToContents）
- `fft_metrics`（2 列）: `["指標", "値"]`
- `proto_table`（4 列）: `["時刻", "種別", "値(hex)", "備考"]`
- `ds_table`（3 列）: `["項目", "値", "表示"]`（列 0,1=Stretch、列 2=ResizeToContents）

### コンボの固定アイテム（外部定数でない、リテラルなもの）
- `enc_combo`: `["自動判別", "utf-8-sig", "utf-8", "cp932", "shift_jis", "euc-jp", "utf-16"]`（先頭は自動判別）。
- `aspect_combo`: `["自動（画面に合わせる）", "16:9", "4:3", "3:2", "1:1", "9:16（縦）", "A4横", "A4縦", "カスタム"]`。
- `proto_combo`: `["UART", "I2C", "SPI"]`。
- `delim_combo`: 先頭 `"自動判別"` ＋ `data_loader.DELIMITER_LABELS.values()`。

### 数値の既定値・範囲（スピンボックス等）
| ウィジェット | range | step | 既定値 |
|---|---|---|---|
| fs_title | (6,40) | - | 12 |
| fs_label | (6,40) | - | 10 |
| fs_tick | (6,40) | - | 9 |
| fs_legend | (6,40) | - | 9 |
| fs_annot | (6,40) | - | 9 |
| frame_width | (0.0,6.0) | 0.2 | 0.8 |
| grid_width | (0.2,6.0) | 0.2 | 0.8 |
| trend_degree | (1,6) | - | 2 |
| trend_window | (2,9999) | - | 5 |
| bins_spin | (1,500) | - | 30 |
| aspect_w | (1,100) | - | 16 |
| aspect_h | (1,100) | - | 9 |
| dpi_spin | (50,1200) | 50 | 150 |
| npeaks | (1,50) | - | 5 |
| smooth_spin | (0,501) | 2 | 0 |
| xdivs | (2,20) | - | 10 |
| ydivs | (2,20) | - | 8 |

### LineEdit の既定テキスト/プレースホルダ
- `xscale_edit("1")`, `yscale_edit("1")`（既定値 "1"）。
- `xpos("0")`, `ypos("0")`。
- `math_param("5")`, `math_var1("1")`, `math_var2("0")`。
- `proto_baud("115200")`, `eye_rate("1e6")`。
- placeholder: `xunit_edit "例: ms"`, `yunit_edit "例: mV"`, `xmin/xmax/ymin/ymax/xtick_edit/ytick_edit` すべて `"自動"`, `mask_upper/mask_lower` `"なし"`, `math_expr "例: sqrt(A**2+B**2) / sin(2*pi*t)*VAR1 / A-VAR1"`。

### チェックボックスの初期 checked 状態
- `setChecked(True)`: `live_check`, `decimate_check`, `grid_check`, `legend_check`, `show_filename_check`, `show_ext_check`, `pct_check`, `trend_eq`。
- `setChecked(False)` を明示: `show_peaks_check`。
- 既定（未指定=False）: `xleft_check`, `data_labels_check`, `xlog`, `ylog`, `transparent_check`, `window_meas_check`, `scope_check`, `edit_check`, `fft_db`, `ds_fit_check`。

### コンボの初期選択
- `tdiv.setCurrentText("1ms")`, `vdiv.setCurrentText("500m")`, `fft_window.setCurrentText("hann")`。

### 状態属性の初期値
- `self.bg_color = ""`, `self.trend_color = ""`（空=自動）。
- `self._plotted_artists = []`, `self._style_artists = {}`, `self._drawing = False`, `self._scope_drag = None`, `self._scope_ov = None`, `self._preview_label = None`, `self._preview_loading = False`。
- `self.cursor_btn = b_cur`（カーソル測定ボタン参照を保持）。
- `self.proto_ch_labels`（3 個の QLabel）, `self.proto_ch`（3 個の QComboBox）。

### スタイルシート文字列（正確に）
- ヒント/補助ラベル: `"color:#666;"`, `"color:#555;"`, `"color:#0a7a55;"`, `"color:#0a3;"`。
- `scope_hint`: `"color:#0a7a55; font-size:11px;"`。
- `y_list`: `"QListWidget::indicator { width:16px; height:16px; }"`。
- `b_draw`: `"font-weight:bold; padding:6px;"`、`b_batch2`: `"padding:6px;"`。
- 系列バー cb: `f"QCheckBox {{ color:{color}; font-weight:{'bold' if checked else 'normal'}; }}"`。

---

## 再現に必須の細部・エッジケース・落とし穴

1. **Mixin 規約**: クラスに `__init__` を書かない。`from graph_app_common import *` で受け取った名前を使う。`@staticmethod`（`_bold` / `_hline`）は装飾ごとこの Mixin に置く。
2. **Qt6 スコープ付き列挙**: すべての列挙はフルパスで書く（`QtCore.Qt.CheckState.Checked`, `QtCore.Qt.Orientation.Vertical`, `QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection`, `QtWidgets.QHeaderView.ResizeMode.Stretch`, `QtCore.Qt.TextElideMode.ElideNone`, `QtCore.Qt.ContextMenuPolicy.CustomContextMenu` 等）。短縮形は使わない。
3. **`UserRole` の使用**: `it.data(UserRole)` は `(ファイルラベル fl, 列名 col)` のタプルを返す前提。`UserRole` は `graph_app_common` 由来の定数（`QtCore.Qt.ItemDataRole.UserRole`）。
4. **系列バーの再入防止**: `_rebuild_series_bar` は構築中に `_series_bar_building = True` を立て、`_toggle_series_select` がそのフラグ中は何もしない（チェック設定時に発火する `toggled` の連鎖を防ぐ）。
5. **lambda のループ変数束縛**: 系列バーの `cb.toggled` / `customContextMenuRequested` 接続、Y ボタンの 3 ボタン、プレビュー 4 ボタンはいずれもデフォルト引数（`item=it`, `wdg=cb` 等）でループ変数を束縛する。束縛しないと最後の値を共有してしまう。
6. **`_build_tab_graph` のグリッド行番号**: フォントサイズ凡例/注記は**行 5**、単位/倍率は**行 3・4**。生成順とは独立に行番号で位置決めする。
7. **`_on_aspect_changed()` の初期呼び出し**: `aspect_combo` のシグナル接続直後に 1 回呼んで初期状態（カスタム W/H の有効/無効など）を反映する。`_build_tab_advanced` 末尾の `_on_math_op_change` / `_on_proto_change("UART")` も同様に初期反映の呼び出し。
8. **`recent_menu` の即時再構築**: `_build_menu` 内で `self.recent_menu` を作った直後に `self._rebuild_recent_menu()` を呼ぶ。
9. **`grid_width` の最小値は 0.2**（0 不可）。描画側で grid linewidth に `None` を渡さない規約があるが、本ファイルは UI 定義のみ。
10. **ファイルリストの長名対応**: `ElideNone` ＋ `WordWrap(False)` ＋ 横スクロール `ScrollPerPixel` ＋ スクロールバー `ScrollBarAsNeeded` で長いファイル名を省略せず横スクロールで読める。複数選択は `ExtendedSelection`。
11. **系列バーの可視性**: 折れ線/散布図以外、または Y 系列が無いときは `series_bar.setVisible(False)`。ある場合のみ True。
12. **`_build_tab_advanced` / `_build_tab_datasci` は `QScrollArea` を返す**（中身ウィジェットをスクロール内に入れる）。`_build_format_panel` は `QSplitter` を返し、上段はスクロール内の `_build_tab_graph`。
13. **`monospace` は使わない**: ラベル文字列に等幅フォント指定を入れない（□化け回避）。フォント関連はステータスバーの `self.font_name` 表示のみ。
14. **絵文字**: `scope_hint` 先頭の「💡」と数式 placeholder のスラッシュなど、文字列はそのまま（ASCII でない文字も正確に）。
15. **暗黙の文字列連結**: ソース上で複数行に分かれた文字列リテラル（例: `y_list` の tip、各種長い tip）は Python の隣接リテラル連結で 1 つの文字列になる。実装では 1 続きの文字列として正しく結合されていればよい。
16. **シグナルとスロットの厳密対応**: 各ウィジェットの `connect` 先メソッド名は他 Mixin/本体に存在する前提。名前を取り違えない（例: `xleft_check → _on_xleft_toggled`, `x_combo.currentTextChanged → _on_x_changed`, `y_list.itemChanged → _on_y_check_changed`, `chart_combo.currentTextChanged → _on_chart_type_change`, `math_op → _on_math_op_change`, `proto_combo → _on_proto_change`, `aspect_combo → _on_aspect_changed`, `style_table.itemChanged → _on_style_label_edited`, `table.itemChanged → _on_cell_edited`, `edit_check → _on_edit_toggle`, `file_list.currentRowChanged → _on_file_selected`）。
17. **背景色/近似曲線色ボタン**: クリックで色選択（`_pick_bg_color` / `_pick_trend_color`）、右クリック（CustomContextMenu）で自動に戻す（`lambda *_: self._reset_bg_color()` / `lambda *_: self._reset_trend_color()`）。

---

以上を満たすよう、`graph_app_mixins/ui_build.py` を 1 ファイルとして完全に実装してください。`pass` や省略は禁止です。
