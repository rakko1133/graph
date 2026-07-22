# -*- coding: utf-8 -*-
"""アプリのロギング設定（Qt 非依存）。

ファイル（~/.csv_graph_tool/app.log・ローテーション付き）とコンソールへ出力し、
未捕捉の例外も記録する。pythonw（コンソール無し）で無言終了しても、原因が
app.log に残るようにするのが目的。
"""
import logging
import logging.handlers
import os
import sys

LOG_DIR = os.path.join(os.path.expanduser("~"), ".csv_graph_tool")
LOG_FILE = os.path.join(LOG_DIR, "app.log")
_logger = None
_crash_file = None   # faulthandler の出力先（GCで閉じないよう保持）


class _TolerantRotatingFileHandler(logging.handlers.RotatingFileHandler):
    """ローテーションに失敗しても落ちないファイルハンドラ。

    Windows では別のプロセス（同時に起動したアプリ・テスト）が app.log を
    開いていると os.rename が PermissionError になり、標準のハンドラは
    そのたびに「--- Logging error ---」とトレースバックを吐く。ログが
    肥大するだけで実害は無いので、失敗したら今回のローテーションを諦めて
    そのまま書き続ける。"""

    def doRollover(self):
        try:
            super().doRollover()
        except OSError:
            # 回せなかった。ファイルを開き直して追記を続ける（記録は止めない）
            if self.stream is None:
                self.stream = self._open()


def setup_logging(level=logging.INFO):
    """ロガーを構成して返す（多重構成しない）。"""
    global _logger
    if _logger is not None:
        return _logger
    logger = logging.getLogger("graphtool")
    logger.setLevel(level)
    logger.handlers.clear()
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        fh = _TolerantRotatingFileHandler(
            LOG_FILE, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except OSError:
        pass  # 書き込めない環境でもアプリは動かす
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    logger.addHandler(ch)
    logger.propagate = False
    # ネイティブクラッシュ（アクセス違反等）でもPythonスタックが crash.log に残るように。
    # 通常の例外フックでは捕まらない 0xC0000005 系の事後解析用。
    try:
        import faulthandler
        global _crash_file
        _crash_file = open(os.path.join(LOG_DIR, "crash.log"), "a", encoding="utf-8")
        _crash_file.write("\n==== 起動 ====\n")
        _crash_file.flush()
        faulthandler.enable(file=_crash_file)
    except OSError:
        pass
    _logger = logger
    return logger


def get_logger():
    """構成済みロガー（未構成なら構成して返す）。"""
    return _logger or setup_logging()


def install_excepthook(on_error=None):
    """未捕捉例外を app.log に記録する。on_error(text) があれば併せて呼ぶ（GUI通知用）。"""
    logger = get_logger()

    def _hook(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        logger.critical("未捕捉の例外", exc_info=(exc_type, exc, tb))
        if on_error is not None:
            try:
                on_error(f"{exc_type.__name__}: {exc}")
            except Exception:  # noqa: BLE001  通知失敗でフックを壊さない
                pass

    sys.excepthook = _hook
