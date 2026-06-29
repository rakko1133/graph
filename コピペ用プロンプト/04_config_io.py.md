# [4/30] ファイル `config_io.py` を作成

あなたは PySide6 + matplotlib 製のデスクトップアプリ「CSV / TSV / 波形 グラフ・解析ツール」を、複数ファイルに分けて再現しています。
これはその **4 番目** のファイルです（全 30 ファイル）。

## 指示（厳守）
- 下のコードブロックの内容で、ファイル `config_io.py` を**新規作成**してください。
- **一字一句そのまま・省略なし**で出力すること。`pass` だけの空クラス／`# TODO`／`… 省略 …`／要約・解説への置き換えは**禁止**。
- 出力が途中で切れたら、こちらが「続き」と言うので、**最後の行まで**出力してください。
- 前置き・後書き・他ファイルの説明は不要。**このファイルの完全な中身だけ**を返してください。
- 文字コードは UTF-8。フォルダ付きパス（例 `graph_app_mixins/...`）はその階層に作成してください。

## `config_io.py` の中身（このまま出力）
```python
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
```
