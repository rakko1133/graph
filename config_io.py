"""設定（グラフ・解析・表示状態）の保存と読み込み。

UI の状態を 1 つの dict にまとめ、JSON で保存／読込する。
アプリ終了時の自動保存・起動時の自動復元にも使う。
"""

import json
import os

# 自動保存先（ユーザーごとの設定フォルダ）
APP_DIR = os.path.join(os.path.expanduser("~"), ".csv_graph_tool")
LAST_CONFIG = os.path.join(APP_DIR, "last_session.json")

CONFIG_VERSION = 1


def ensure_app_dir():
    os.makedirs(APP_DIR, exist_ok=True)
    return APP_DIR


def save_config(config, path):
    """設定 dict を JSON で保存する。"""
    data = dict(config)
    data["_version"] = CONFIG_VERSION
    folder = os.path.dirname(os.path.abspath(path))
    if folder:
        os.makedirs(folder, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def load_config(path):
    """JSON から設定 dict を読み込む。失敗時は None。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def save_last_session(config):
    """終了時の自動保存。"""
    try:
        ensure_app_dir()
        return save_config(config, LAST_CONFIG)
    except OSError:
        return None


def load_last_session():
    """起動時の自動復元。無ければ None。"""
    if os.path.isfile(LAST_CONFIG):
        return load_config(LAST_CONFIG)
    return None
