"""CSV / TSV / 波形データ グラフ・解析ツール — シンプル版（PySide6 / Qt）。

使い方:
    python graph_app_simple.py

通常版（graph_app.py）と**同じアプリの同じ機能**を、画面に出す量だけ絞って
起動する入口です。別の実装ではありません:

    - 読み込み・描画・解析・出力のロジックは通常版と完全に共有（1行も複製しない）
    - 画面から消えている設定は `setVisible(False)` で隠れているだけで、
      ウィジェットも設定値も生きている（設定ファイル・プリセットの互換性も同じ）
    - 隠れた設定には **Ctrl+F（設定を検索）** で名前を入れれば到達できる。
      該当パネルを開き、必要なら表示レベルを自動で上げてその項目まで移動する
    - **Ctrl+Shift+P（コマンドパレット）** からは全メニュー操作を名前で実行できる
    - 足りなくなったら 表示→表示レベル→標準／全部 でその場で増やせる
      （再起動不要。通常版と同じウィンドウのまま全機能が現れる）

つまり「機能を落とした版」ではなく「最初に見せる量を絞った版」です。

通常版と設定を分けたい場合は環境変数 GRAPHAPP_PROFILE に名前を入れて起動します
（例: set GRAPHAPP_PROFILE=simple）。既定では通常版と設定を共有します。
"""

import os
import sys

from graph_app import GraphApp
from graph_app_common import QtCore, QtWidgets, applog


class SimpleGraphApp(GraphApp):
    """既定の表示レベルだけを変えた GraphApp。

    ロジックもウィジェットも通常版と同一。`DEFAULT_UI_LEVEL` を "基本" にすることで
    `_restore_ui_state`（persistence.py）が起動時に薄い画面を組む。
    ユーザーが表示レベルを変えれば QSettings に保存され、次回はそれが優先される。
    """

    DEFAULT_UI_LEVEL = "基本"

    def __init__(self):
        super().__init__()
        self.setWindowTitle("CSV / TSV / 波形 グラフ・解析ツール — シンプル版")
        self._install_simple_guide()

    def _install_simple_guide(self):
        """初回起動時に、最短手順と「増やし方」を通知バーで案内する。"""
        settings = self._ui_settings()
        if str(settings.value("ui/simple_guided")) in ("1", "true", "True"):
            return
        settings.setValue("ui/simple_guided", "1")
        QtCore.QTimer.singleShot(0, lambda: self.notify(
            "① ファイルをドラッグ&ドロップ → ② 列にチェック → ③ グラフを描画 (F5)",
            "info",
            "機能は通常版と同じです。画面に出ていない設定は Ctrl+F で名前を検索すると"
            "そこまで移動します。まとめて出すなら 表示→表示レベル→標準／全部。",
            timeout_ms=0))


def main():
    applog.setup_logging()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

    def _report(text):
        try:
            QtWidgets.QMessageBox.critical(
                None, "予期しないエラー",
                f"{text}\n\n詳細は app.log を確認してください:\n{applog.LOG_FILE}")
        except Exception:  # noqa: BLE001
            applog.get_logger().debug("エラー通知に失敗", exc_info=True)

    applog.install_excepthook(on_error=_report)
    try:
        win = SimpleGraphApp()
        win.show()
        sys.exit(app.exec())
    except Exception:
        applog.get_logger().exception("シンプル版の起動に失敗")
        raise


if __name__ == "__main__":
    main()
