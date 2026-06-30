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
        fh = logging.handlers.RotatingFileHandler(
            LOG_FILE, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except OSError:
        pass  # 書き込めない環境でもアプリは動かす
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    logger.addHandler(ch)
    logger.propagate = False
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
