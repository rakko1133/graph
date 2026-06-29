# [30/30] graph_app.py の仕様

## 指示

- この仕様だけを読んで、`graph_app.py` を**完全な形**で実装し出力してください。`pass`・`TODO`・「以下省略」・要約・ダミー実装は**禁止**です。実際に動作する完成コードを書いてください。
- もし出力が途中で切れた場合は、ユーザーが「続き」と入力するので、**続きから最後まで**漏れなく出力してください。
- このファイルはアプリのエントリーポイント（起動スクリプト兼 `GraphApp` クラス本体）です。短いファイルですが、`GraphApp.__init__` で初期化する**全インスタンス属性の初期値**と**呼び出し順序**、Mixin の多重継承順序を正確に再現することが重要です。

### アプリ全体の前提（このファイルに関係する分）

- Python 3.10+ / GUI は **PySide6（Qt6）**。ただし Qt 型は**必ず matplotlib 経由**で取得する（このファイルでは直接 import せず、後述の `graph_app_common` 経由で受け取る）。
  - `from matplotlib.backends.qt_compat import QtCore, QtGui, QtWidgets`
  - `from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas, NavigationToolbar2QT as NavigationToolbar`
  - `from matplotlib.figure import Figure`
- Qt6 の列挙は**スコープ付き**（例: `QtCore.Qt.ItemDataRole.UserRole`、`QtCore.Qt.CheckState.Checked`）。
- `GraphApp` は **10 個の Mixin ＋ `QtWidgets.QMainWindow` の多重継承**で構成し、`__init__` と `closeEvent` は **`GraphApp` 本体**に置く。各 Mixin は `__init__` を持たない（メソッド束のみ）。
- 再描画は**デバウンス（`QTimer` 単発）＋再入防止（`_drawing`）＋ `_suspend_redraw`（構築/復元中の抑制）＋ `_has_drawn`** で制御する。本ファイルでは `_suspend_redraw` / `_has_drawn` / 各タイマーを初期化する。
- 日本語フォントは `jp_font` で設定する（`family="monospace"` は使わない）。

---

## ファイルの役割 / 責務

`graph_app.py` は、本アプリ「**CSV / TSV / 波形データ グラフ・解析ツール（PySide6 / Qt）**」の**メインエントリーポイント**である。

モジュール docstring（先頭の三重引用符文字列）の趣旨は以下の通り。原文（正確な値）をそのまま入れること:

```
"""CSV / TSV / 波形データ グラフ・解析ツール（PySide6 / Qt）。

使い方:
    python graph_app.py

機能:
    - 複数の CSV/TSV/波形ファイルをまとめて読み込み、系列を重ねて描画
    - 文字コード・区切りの自動判定（手動指定も可）
    - 8種のグラフ＋系列ごとの色/線種/線幅/マーカー、軸範囲/対数軸/凡例位置
    - Excel相当のグラフ編集：近似曲線（線形/多項式/指数/対数/移動平均＋R²）、
      データラベル、第2軸・複合グラフ（系列ごと主/第2軸＋線/棒/面の混在）、エラーバー
    - データのセル編集（表を直接編集→DataFrameへ反映、行/列追加・削除、CSV保存）
    - オシロスコープ表示（time/div・V/div・位置・divグリッド）
    - オシロ相当の解析（第1/第2…ピーク検出、各種測定、FFT）
    - 設定の保存／読み込み（終了時自動保存・起動時復元）

GUI は matplotlib の qt_compat 経由で実装しており、PySide6 / PyQt6（Qt6系）で動作する。
"""
```

責務:

1. 共有モジュール（`graph_app_common`）と 10 個の Mixin を import する。
2. それらを多重継承した `GraphApp(QMainWindow)` を定義し、`__init__` で全インスタンス状態を初期化・GUI を構築・前回セッションを復元する。
3. `closeEvent` で現在の設定（`_collect_config()` の結果）を `config_io.save_last_session` で自動保存する。
4. `main()` で `QApplication` を起こしてウィンドウを表示し、イベントループを回す。
5. `if __name__ == "__main__": main()` で直接実行に対応する。

このファイル自体には GUI 構築・描画・解析の**実装は無い**（すべて Mixin 側に委譲）。本ファイルは「配線（多重継承）」と「初期化・終了・起動の骨格」を担う薄い層である。

---

## 依存（import するもの）

ファイル冒頭で以下を import する（**この順序・この形**で）:

```python
from graph_app_common import *  # noqa: F401,F403
from graph_app_mixins import (
    UIBuildMixin,
    DataIOMixin,
    StyleTableMixin,
    PlotMixin,
    ScopeCursorMixin,
    AnalysisMixin,
    AdvancedMixin,
    DataSciMixin,
    BatchMixin,
    PersistenceMixin,
)
```

- `from graph_app_common import *` により、以下の名前がこのモジュールのグローバルに入る（`graph_app_common.__all__` で公開されている）。本ファイル内で実際に使うのは特に **`os`, `sys`, `QtCore`, `QtWidgets`, `config_io`, `jp_font`** である。
  - `os`, `sys`, `QtCore`, `QtGui`, `QtWidgets`, `FigureCanvas`, `NavigationToolbar`, `Figure`
  - `advanced`, `analysis`, `config_io`, `data_loader`, `datasci`, `jp_font`, `mathchan`, `plotter`
  - `PREVIEW_ROWS`, `UserRole`, `DECIMATE_TARGET`, `BUSY_ROWS`, `BATCH_PARALLEL_THRESHOLD`
  - `_parse_float`, `CheckListWidget`, `LazyColumnCombo`
- `# noqa: F401,F403` コメントは**そのまま付ける**（ワイルドカード import に対する linter 抑制。再現必須）。
- 10 個の Mixin は `graph_app_mixins` パッケージから上記の**正確な名前**で import する。

---

## 公開 API（クラス・メソッド・関数）

### `class GraphApp(...)`（多重継承の定義）

クラス宣言は**この基底クラス順序を厳守**すること（メソッド解決順序 MRO に影響するため、順序を変えてはならない）:

```python
class GraphApp(UIBuildMixin, DataIOMixin, StyleTableMixin, PlotMixin,
               ScopeCursorMixin, AnalysisMixin, AdvancedMixin, DataSciMixin,
               BatchMixin, PersistenceMixin, QtWidgets.QMainWindow):
```

- 先頭から: `UIBuildMixin`, `DataIOMixin`, `StyleTableMixin`, `PlotMixin`, `ScopeCursorMixin`, `AnalysisMixin`, `AdvancedMixin`, `DataSciMixin`, `BatchMixin`, `PersistenceMixin`、**最後に** `QtWidgets.QMainWindow`。
- Mixin はいずれも `__init__` を持たないため、`super().__init__()` は最終的に `QMainWindow.__init__()` に到達する。
- クラス本体に持つメソッドは `__init__` と `closeEvent` の 2 つだけ。それ以外のメソッドはすべて Mixin から継承する（このファイルには書かない）。

---

### `def __init__(self):`（GraphApp 本体）

役割: ウィンドウとアプリ状態をすべて初期化する。**戻り値なし**。処理は以下の順序で正確に行う（順序・属性名・既定値が再現の核）。

1. `super().__init__()` を最初に呼ぶ（QMainWindow を初期化）。

2. **データ保持用の辞書/属性**を初期化（コメントも再現推奨）:
   - `self.datasets = {}` — `label -> DataFrame`。読み込んだデータ本体。
   - `self.meta = {}` — `label -> {"path","enc","delim"}`。各ファイルのメタ情報。
   - `self.series_styles = {}` — キー文字列 `"file\tcol"`（ファイルラベルと列名をタブ `\t` で連結）→ スタイル辞書。label 上書きも保持。
   - `self.last_dir = os.path.expanduser("~")` — ファイルダイアログの初期ディレクトリ（ホーム）。

3. **再描画制御フラグ**:
   - `self._suspend_redraw = True` — 構築・設定適用中は自動再描画を抑制する。**この時点では `True`**。`__init__` の最後で `False` に戻す（後述）。
   - `self._has_drawn = False` — 一度でも描画したか。リアルタイム更新の発火条件に使う。

4. **日本語フォント設定とウィンドウ基本設定**:
   - `self.font_name = jp_font.setup_japanese_font()` — 日本語フォントをセットアップし、選ばれたフォント名を保持。
   - `self.setWindowTitle("CSV / TSV / 波形 グラフ・解析ツール")` — タイトルバー文字列（**正確にこの文字列**。docstring 見出しとは別文言）。
   - `self.resize(1280, 800)` — 初期ウィンドウサイズ（幅 1280 × 高さ 800）。
   - `self.setAcceptDrops(True)` — Explorer からのドラッグ&ドロップ読み込みを有効化。

5. **再描画デバウンスタイマー**（変更を少し待ってまとめて再描画）:
   - `self._redraw_timer = QtCore.QTimer(self)`
   - `self._redraw_timer.setSingleShot(True)` — 単発。
   - `self._redraw_timer.timeout.connect(self._do_live_redraw)` — タイムアウトで `_do_live_redraw`（PlotMixin 側）を呼ぶ。

6. **ズーム再サンプル用の状態**（表示範囲が変わったとき間引きを再計算する仕組み）:
   - `self._dyn = []` — `[(line, full_x, full_y, max_points), ...]` のリスト。各折れ線の全データを保持。
   - `self._dyn_cid = None` — matplotlib のコールバック ID。
   - `self._resampling = False` — 再サンプル中フラグ（再入防止）。
   - `self._resample_timer = QtCore.QTimer(self)`
   - `self._resample_timer.setSingleShot(True)`
   - `self._resample_timer.timeout.connect(self._do_resample)` — タイムアウトで `_do_resample`（PlotMixin 側）を呼ぶ。
   - `self.recent_files = []` — 最近使ったファイル（MRU）リスト。

7. **カーソル測定の状態**（ScopeCursorMixin が使用）:
   - `self._cursor_cid = None` — マウスクリック等のコールバック ID。
   - `self._cursor_pts = []` — クリックで取得した測定点。
   - `self._cursor_artists = []` — 描いたカーソル系アーティスト一覧。
   - `self._cursors = []` — `[{x, vline, marker}]` 形式。ドラッグ微調整対応のカーソル群。
   - `self._cursor_drag = None` — ドラッグ中のカーソル情報。
   - `self._cursor_text = None` — 測定結果テキストのアーティスト。

8. **GUI 構築（Mixin のメソッドを順に呼ぶ）**:
   - `self._build_menu()` — メニューバー構築（UIBuildMixin）。
   - `self._build_central()` — 中央ウィジェット（タブ/スタイル表/キャンバス等）構築（UIBuildMixin）。
   - `self._build_statusbar()` — ステータスバー構築（UIBuildMixin）。
   - `self._on_chart_type_change()` — グラフ種別の初期選択に応じて関連 UI の表示/有効状態を整える（PlotMixin など）。

9. **前回セッションの復元**:
   - `restored = self._try_restore_session()` — 前回終了時の設定を復元（PersistenceMixin）。成功で `True`、何も復元しなければ `False` を返す（戻り値は真偽）。
   - `if not restored:` のとき、初回ガイドをステータスへ表示:
     - `self._set_status("『データ』タブで「ファイル追加」、またはCSV/TSVファイルをドラッグ&ドロップして読み込んでください。")`
     - この案内文字列は**正確にこの値**（鉤括弧『』と「」の使い分けに注意）。

10. **抑制解除（必ず最後に）**:
    - `self._suspend_redraw = False` — 構築完了。以降は変更で自動再描画する。

注意: `_suspend_redraw` を `True` のまま初期化して**最後に `False`** に戻すことが重要。構築途中で発生しうる UI 変更シグナルによる無駄な（あるいは未完成状態での）再描画を防ぐためのガード。

---

### `def closeEvent(self, event):`（GraphApp 本体）

役割: ウィンドウを閉じる際に、現在の設定を前回セッションとして自動保存する。Qt の `closeEvent` オーバーライド。**戻り値なし**。

擬似コード:

```
try:
    config_io.save_last_session(self._collect_config())
except Exception:
    pass            # 保存に失敗してもウィンドウは必ず閉じる
super().closeEvent(event)
```

- `self._collect_config()` — 現在の全設定を 1 つの辞書にまとめる（PersistenceMixin）。
- `config_io.save_last_session(...)` — その辞書を所定の場所に JSON 等で保存する（`config_io` モジュール）。
- 例外は**握りつぶす**（`except Exception: pass`）。保存失敗で終了処理がブロックされてはならない。
- 最後に必ず `super().closeEvent(event)` を呼び、QMainWindow 既定の終了処理に委ねる。

---

### `def main():`（モジュール関数）

役割: アプリを起動する。**戻り値なし**（最後に `sys.exit` で抜ける）。

擬似コード:

```
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
win = GraphApp()
win.show()
sys.exit(app.exec())
```

- `QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)` — 既存の `QApplication` インスタンスがあればそれを再利用し、無ければ `sys.argv` で新規生成する（多重生成を避けるイディオム。再現必須）。
- `win = GraphApp()` でメインウィンドウを生成。
- `win.show()` で表示。
- `sys.exit(app.exec())` でイベントループを開始し、終了コードでプロセスを終える（Qt6 では `exec_()` ではなく **`exec()`**）。

---

### モジュール末尾

```python
if __name__ == "__main__":
    main()
```

- スクリプトとして直接実行されたときのみ `main()` を呼ぶ（import されただけでは起動しない）。

---

## 定数・データ（正確な値）

このファイルが**定義する**モジュール定数は無い（定数・補助クラスは `graph_app_common` 側）。本ファイルで現れる「正確な値」の文字列・数値は以下:

- ウィンドウタイトル: `"CSV / TSV / 波形 グラフ・解析ツール"`
- 初期ウィンドウサイズ: `resize(1280, 800)`（幅 1280, 高さ 800）。
- 初回ガイドのステータス文言: `"『データ』タブで「ファイル追加」、またはCSV/TSVファイルをドラッグ&ドロップして読み込んでください。"`
- `self.last_dir` の初期値: `os.path.expanduser("~")`（ユーザーのホームディレクトリ）。
- 各種コレクション初期値はすべて空（`{}` または `[]`）、ID/状態系は `None`、真偽フラグは `_suspend_redraw=True`（後で `False`）/ `_has_drawn=False` / `_resampling=False`。

辞書キー名・データ構造（再現必須）:

- `self.meta[label]` の形: `{"path": ..., "enc": ..., "delim": ...}`（キー名は `"path"`, `"enc"`, `"delim"`）。
- `self.series_styles` のキー: ファイルラベルと列名をタブ文字 `\t` で連結した文字列 `"file\tcol"`。
- `self._dyn` の要素: タプル `(line, full_x, full_y, max_points)`。
- `self._cursors` の要素: 辞書 `{x, vline, marker}`（キー `x`, `vline`, `marker`）。

---

## 再現に必須の細部・エッジケース・ガード

- **初期化順序を厳守**: 「データ辞書 → 再描画フラグ → フォント/ウィンドウ設定 → デバウンスタイマー → 再サンプル状態 → MRU → カーソル状態 → `_build_menu`/`_build_central`/`_build_statusbar`/`_on_chart_type_change` → セッション復元 → `_suspend_redraw=False`」の順。GUI 構築（`_build_*`）より前に、それらが参照する状態属性（`datasets`, `series_styles`, `_cursors`, `recent_files` など）を**すべて初期化しておく**こと。
- `_suspend_redraw` は最初 `True`、`__init__` の**最終行**で `False`。この対称性を崩さない。
- `_try_restore_session()` の戻り値で初回ガイドの表示有無を分岐する（復元できたらガイドを出さない）。
- `closeEvent` の保存は `try/except Exception: pass` で囲み、最後に必ず `super().closeEvent(event)` を呼ぶ。
- `main()` は `QApplication.instance()` の再利用イディオムを使う。
- Qt6 のイベントループ開始は `app.exec()`（`exec_()` ではない）。
- 全タイマーは `setSingleShot(True)`（単発）。`timeout` を `_do_live_redraw` / `_do_resample` に接続する。

---

## このファイルに関係する落とし穴

- **Mixin 規約**: `GraphApp` 以外（10 個の Mixin）は `__init__` を持たない。`super().__init__()` が QMainWindow に届くよう、基底クラスの**並び順を変えない**。`__init__` と `closeEvent` を Mixin に移してはいけない（本体に置く）。MRO 順序を変えると、同名メソッドがどの Mixin の実装を採るかが変わり挙動が壊れる。
- **Qt は matplotlib 経由**: このファイルでは `from PySide6 import ...` や `from PyQt6 import ...` を**書かない**。`QtCore` / `QtWidgets` は `graph_app_common`（`matplotlib.backends.qt_compat` 経由）から受け取る。
- **Qt6 のスコープ付き列挙**: 本ファイル内で直接の列挙参照は無いが、共有モジュールやタイマー API は Qt6 流儀（`QtCore.QTimer`、`setSingleShot`、`timeout.connect`）で書くこと。`exec_()` ではなく `exec()`。
- **ワイルドカード import の linter 抑制**: `from graph_app_common import *  # noqa: F401,F403` のコメントを省略しない。
- **`family="monospace"` を使わない**: フォントは `jp_font.setup_japanese_font()` に任せる（日本語の □ 化け回避）。本ファイルでフォント family を直接指定しない。
- **抑制ガード**: `_suspend_redraw` を正しく扱わないと、構築途中の不完全な状態で再描画が走り例外/ちらつきの原因になる。最後に `False` へ戻すのを忘れない。
- **終了時保存の堅牢性**: `_collect_config` / `save_last_session` で例外が出ても**必ずウィンドウは閉じる**こと（例外を握りつぶす）。
