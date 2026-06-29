# [4/30] config_io.py の仕様

## 指示

- この仕様だけを読んで `config_io.py` を**完全な形**で実装し、ファイル全体を出力してください。
- `pass`・`TODO`・省略・要約・「ここは元コード参照」等は**一切禁止**です。すべての関数を実際に動作する本体まで書ききってください。
- 出力が長くて途中で切れた場合は、ユーザーが「続き」と言ったら**最後まで**続きを出力してください。
- このファイルは GUI を一切持たない純粋なユーティリティモジュールです（Qt・matplotlib・numpy・scipy のいずれも import しません）。標準ライブラリ（`json`・`os`）のみで完結します。
- アプリ全体の前提（関連分のみ）: 本アプリは Python 3.10+ / GUI=PySide6(Qt6) の CSV グラフ作成ツールであり、`GraphApp` が UI 状態を 1 個の `dict` にまとめて持つ。本ファイルはその設定 dict を JSON で永続化（保存／読込）する層であり、アプリ終了時の自動保存・起動時の自動復元を担う。Qt や matplotlib に依存しないため、spawn されたサブプロセスからも安全に import できる。

---

## ファイルの役割 / 責務

モジュール docstring（先頭に必ず置く。3 行＋空行込みで以下の趣旨）:

```
"""設定（グラフ・解析・表示状態）の保存と読み込み。

UI の状態を 1 つの dict にまとめ、JSON で保存／読込する。
アプリ終了時の自動保存・起動時の自動復元にも使う。
"""
```

責務:

- アプリの UI 状態を表す**設定 dict** を JSON ファイルへ保存する（`save_config`）。
- JSON ファイルから設定 dict を読み込む（`load_config`）。失敗時は例外を投げずに `None` を返す堅牢な読込。
- ユーザーごとの設定フォルダ（ホーム直下の隠しフォルダ）に、**直近セッション**を自動保存／自動復元する（`save_last_session` / `load_last_session`）。
- 設定フォルダの存在保証（`ensure_app_dir`）。

設計方針: 例外を上位へ伝播させず、保存系・自動復元系は失敗しても `None` を返してアプリの起動・終了を妨げない（堅牢性優先）。設定 dict にはバージョン番号を埋め込み、将来のマイグレーションに備える。

---

## 依存（import するもの）

ファイル冒頭（docstring の直後）で、以下の標準ライブラリのみを import する。**他のサードパーティや自作モジュールは一切 import しない。**

```python
import json
import os
```

---

## モジュール定数（正確な値そのまま）

docstring と import の後に、以下の定数をこの順序・この値で定義する。

| 定数名 | 値 | 意味 |
| --- | --- | --- |
| `APP_DIR` | `os.path.join(os.path.expanduser("~"), ".csv_graph_tool")` | 自動保存先（ユーザーごとの設定フォルダ）。ホームディレクトリ直下の `.csv_graph_tool` フォルダ。 |
| `LAST_CONFIG` | `os.path.join(APP_DIR, "last_session.json")` | 直近セッションの自動保存ファイルのフルパス。`APP_DIR` 直下の `last_session.json`。 |
| `CONFIG_VERSION` | `1`（整数リテラル） | 保存時に設定 dict へ埋め込むバージョン番号。 |

定数の直前に付けるコメント（日本語、正確に）:

- `APP_DIR` の直前: `# 自動保存先（ユーザーごとの設定フォルダ）`

定数の並び順は `APP_DIR` → `LAST_CONFIG` → （空行）→ `CONFIG_VERSION`。

---

## 公開 API（完全なシグネチャと挙動）

すべてモジュールトップレベルの関数（クラスは無し）。定義順は下記のとおり: `ensure_app_dir` → `save_config` → `load_config` → `save_last_session` → `load_last_session`。

### `def ensure_app_dir():`

- 役割: 設定フォルダ `APP_DIR` が無ければ作成する。
- 実装: `os.makedirs(APP_DIR, exist_ok=True)` を呼ぶ。
- 戻り値: `APP_DIR`（文字列）を返す。
- 例外: ここでは捕捉しない（呼び出し側で必要なら捕捉する設計）。

### `def save_config(config, path):`

- docstring: `"""設定 dict を JSON で保存する。"""`
- 役割: 設定 dict を JSON ファイルとして `path` に書き出す。
- 引数: `config`（設定 dict）、`path`（保存先パス文字列）。
- アルゴリズム（この順で精密に）:
  1. `data = dict(config)` … 元の `config` を破壊しないよう浅いコピーを作る。
  2. `data["_version"] = CONFIG_VERSION` … バージョンキー `"_version"` を**書き込み時に必ず付与**する（キー名はアンダースコア始まりの `_version`、値は `1`）。
  3. `folder = os.path.dirname(os.path.abspath(path))` … 絶対パス化してから親ディレクトリを取り出す。
  4. `if folder:` のとき `os.makedirs(folder, exist_ok=True)` … 親フォルダが空文字列でなければ作成（無ければ）する。
  5. `with open(path, "w", encoding="utf-8") as f:` でファイルを開き、`json.dump(data, f, ensure_ascii=False, indent=2)` で書き出す。
- JSON 書き出しオプション（重要・正確に）: `ensure_ascii=False`（日本語をそのまま保存し `\uXXXX` エスケープしない）、`indent=2`（2 スペースの整形インデント）。エンコーディングは `utf-8`。
- 戻り値: `path`（書き出したパス）を返す。
- 例外: ここでは捕捉しない（ファイル書き込みエラー等はそのまま伝播。捕捉は `save_last_session` 側で行う）。

### `def load_config(path):`

- docstring: `"""JSON から設定 dict を読み込む。失敗時は None。"""`
- 役割: JSON ファイルを読み込み、設定 dict を返す。
- 引数: `path`（読込元パス文字列）。
- アルゴリズム:
  1. `try:` の中で `with open(path, "r", encoding="utf-8") as f:` を開き、`return json.load(f)` を返す。
  2. `except (OSError, ValueError):` を捕捉して `return None`。
- 例外ガード（重要）: 捕捉する例外型は **`(OSError, ValueError)` のタプル**。`OSError`（ファイルが存在しない・読めない等）と `ValueError`（JSON パース失敗＝`json.JSONDecodeError` は `ValueError` のサブクラス）を両方カバーする。それ以外の例外は捕捉しない。
- 戻り値: 成功時は読み込んだ dict（または JSON のトップレベルが配列等ならその値）。失敗時は `None`。
- エンコーディングは `utf-8`。

### `def save_last_session(config):`

- docstring: `"""終了時の自動保存。"""`
- 役割: アプリ終了時に、直近セッションを `LAST_CONFIG` へ自動保存する。
- 引数: `config`（設定 dict）。
- アルゴリズム:
  1. `try:` の中で `ensure_app_dir()` を呼んで設定フォルダを保証する。
  2. `return save_config(config, LAST_CONFIG)` で保存し、保存先パスを返す。
  3. `except OSError:` を捕捉して `return None`。
- 例外ガード（重要）: 捕捉するのは **`OSError` のみ**（フォルダ作成・ファイル書込の失敗）。失敗してもアプリの終了処理を妨げないよう `None` を返す。
- 戻り値: 成功時は `LAST_CONFIG`、失敗時は `None`。

### `def load_last_session():`

- docstring: `"""起動時の自動復元。無ければ None。"""`
- 役割: アプリ起動時に、直近セッションファイルがあれば読み込んで返す。
- 引数: なし。
- アルゴリズム:
  1. `if os.path.isfile(LAST_CONFIG):` … `LAST_CONFIG` が**ファイルとして存在する**ときだけ読み込む。
  2. 存在すれば `return load_config(LAST_CONFIG)` を返す（その内部で失敗すれば `None` になる）。
  3. 存在しなければ `return None`。
- 戻り値: ファイルがあり読込成功すれば dict、無いか読込失敗なら `None`。

---

## 再現に必須の細部・エッジケース

- **バージョンキーは保存時のみ付与**: `save_config` が書き込み時に `data["_version"] = CONFIG_VERSION` を入れる。読み込み側（`load_config`）はバージョンの検証や除去を**一切しない**（`"_version"` キーは dict にそのまま残る）。マイグレーション処理はこのファイルには無い。
- **元 dict 非破壊**: `save_config` は `dict(config)` で浅いコピーを作ってからバージョンキーを足すため、呼び出し元が渡した `config` 自身は変更されない。これは必ず守ること（直接 `config["_version"]=...` としない）。
- **親フォルダ自動作成**: `save_config` は `os.path.abspath(path)` 経由で得た親フォルダを `exist_ok=True` で作成する。`folder` が空文字列（カレント直下のファイル名のみ等）の場合は `makedirs` を呼ばない（`if folder:` ガード）。
- **例外捕捉の粒度の違い**（混同しないこと）:
  - `load_config` は `(OSError, ValueError)` を捕捉（読込＋パース両方）。
  - `save_last_session` は `OSError` のみ捕捉。
  - `ensure_app_dir` / `save_config` / `load_last_session` は自前では捕捉しない。
- **`load_last_session` の二重ガード**: 先に `os.path.isfile` で存在確認し、さらに `load_config` 内の例外捕捉でも守られるため、ファイルが壊れていても起動はクラッシュしない。
- **戻り値の一貫性**: 失敗・不在はすべて `None`。成功時はパス文字列（保存系）または dict（読込系）。
- **パス文字列の扱い**: `APP_DIR` / `LAST_CONFIG` は `os.path.join` と `os.path.expanduser("~")` で構築するため OS 依存のセパレータになる（Windows なら `\`）。ハードコードしたパス区切りを使わないこと。

---

## このファイルに関係する落とし穴

- このモジュールは **Qt / matplotlib / numpy / scipy を一切 import しない**こと。`batch_render`（別ファイル）からの spawn 安全性と同様、設定 I/O も純標準ライブラリで完結させる。GUI 由来の落とし穴（Qt6 スコープ付き列挙・Mixin 規約・facade・monospace 回避・grid linewidth=None 回避）は本ファイルには**該当しない**。
- `json.dump` の `ensure_ascii=False` を必ず付けること。これを忘れると日本語のラベル文字列が `\uXXXX` で保存され、ファイルが読みにくくなる（機能は壊れないが仕様に反する）。
- `indent=2` を必ず付けること（人が読める整形 JSON にするため）。
- 例外型を `Exception` で広く捕まえないこと。仕様どおり `load_config` は `(OSError, ValueError)`、`save_last_session` は `OSError` に限定する。
- バージョンキー名は厳密に `"_version"`（先頭アンダースコア）であること。`"version"` ではない。
- 設定フォルダ名は厳密に `.csv_graph_tool`（先頭ドット）、自動保存ファイル名は厳密に `last_session.json` であること。
