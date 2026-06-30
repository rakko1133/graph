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


class GraphApp(UIBuildMixin, DataIOMixin, StyleTableMixin, PlotMixin,
               ScopeCursorMixin, AnalysisMixin, AdvancedMixin, DataSciMixin,
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
        self._build_central()
        self._build_statusbar()
        self._on_chart_type_change()

        restored = self._try_restore_session()
        if not restored:
            self._set_status("『データ』タブで「ファイル追加」、またはCSV/TSVファイルをドラッグ&ドロップして読み込んでください。")
        self._suspend_redraw = False  # 構築完了。以降は変更で自動再描画

    def closeEvent(self, event):
        try:
            config_io.save_last_session(self._collect_config())
        except Exception:
            applog.get_logger().exception("終了時の設定保存に失敗")
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
            pass

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
