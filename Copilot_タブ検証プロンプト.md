# Copilot 用ひな型：生成したタブが「ちゃんと使えるコードか」を Copilot 自身に検証させる

> 使い方: タブを生成させた**同じチャット**で、生成直後に下の「プロンプト本体」を貼る。
> Copilot がさっき出した `graph_tab_<名前>.py` を、チェックリストで自己点検し、
> 要修正があれば**直した完全版**を出し直す。
> （生成する側のひな型は `Copilot_新タブ生成プロンプト.md`。実際に実行して確かめる版は `check_tab.py`。）

---

## プロンプト本体（ここから下をコピーして使う）

さっきあなたが出力した `graph_tab_<名前>.py` を、下のチェックリストで **1項目ずつ自己点検**して
ください。コードを実際に読み、各項目を「✅クリア / ❌要修正」で判定し、根拠（該当箇所）を一言添える。
**❌が1つでもあれば、直した完全版のファイルを丸ごと再出力**する。全部✅なら「全項目クリア」とだけ書く。
**推測で✅にしない**（自信が無ければ❌にして直す）。

### チェックリスト

**［骨組み・登録］**
1. `graph_app_common.TabPlugin` を継承し、ファイル末尾で `register_tab(<クラス>())` を1回呼んでいる。
2. クラス属性が揃って妥当: `key`(英小文字・一意) / `title` / `order`(**50以上**) / `min_level`(`"基本"`/`"標準"`/`"全部"` のいずれか)。
3. `build(self, app)` がウィジェットを `return` し、後で使う入力欄は `self.` に保持している。

**［API・依存］**
4. 呼んでいる `app.xxx` が **「使ってよいAPI」に実在するものだけ**（`analysis_xy_or_warn` / `series_xy` / `register_dataset` / `draw_graph` / `notify` / `_set_status` / `_selected_series_items`）。それ以外の app のメソッド・属性を**発明していない**。
5. 使っているライブラリ（`numpy`/`pandas` 等）を**自分で import** している。**未使用の import が無い**。
6. `register_dataset` を使うなら、渡す `DataFrame` が **横軸列＋値列** を持つ形になっている。

**［再描画の配線］**
7. 値変更で `app.draw_graph()` を呼ぶ配線があり、`QLineEdit` は **`editingFinished`**、チェック/コンボ/スピンは `toggled`/`currentTextChanged`/`valueChanged`。**`textChanged` で毎文字描画していない**。

**［任意メソッド：定義しているものだけ判定］**
8. `draw_overlay(self, app, ax)`: 描く線/帯/注記に**色を明示**、**3D軸を前提にしない**、`float()`変換・空文字・`None` を握って（try/except か早期 return）例外で落とさない、**この中で `app.draw_graph()` を呼んでいない**（無限ループ回避）。
9. `collect_config(self, app)`: **JSON化できる値だけ**（数値/文字列/真偽/リスト/辞書）の dict を返す。
10. `apply_config(self, app, cfg)`: 値を**ウィジェットに戻すだけ**。`blockSignals(True/False)` で囲み、**`app.draw_graph()` を呼んでいない**。`collect_config` が返すキーと `apply_config` が読むキーが**一致**している。

**［堅牢性・完成度］**
11. 実行時に落ちうる所（空入力・`float()`失敗・`KeyError`・`None`参照・0除算・範囲外）をガードしている。
12. そのまま保存して動く**完全な1ファイル**（未完成の `...` や擬似コードが無く、構文が通る）。`graph_app.py` に足す import は**1行だけ**で済む形。

### 出力形式
1. チェック結果の表（`番号 | ✅/❌ | 根拠一言`）。
2. ❌があれば、続けて「修正版 `graph_tab_<名前>.py`（全文）」と「足す import 1行」を出す。
3. 全部✅なら「全項目クリア。そのまま採用OK」とだけ書く。

---

## 補足（2段構えで確実に）
- **この検証プロンプト** … Copilot にコードを読ませて自己点検させる（実行不要・チャット内で完結）。
- **`check_tab.py`** … 人間側で `python check_tab.py graph_tab_<名前>` を回し、import→組み立て→描画→設定往復まで**実際に実行**して PASS/FAIL を出す。

両方通れば、`graph_app.py` に import 1行を足して安心して採用できる。
