# [5/30] jp_font.py の仕様

## 指示

- この仕様だけを読んで `jp_font.py` を**完全な形**で実装し、出力してください。
- `pass`・`TODO`・「省略」・「要約」・「以下同様」などは**一切禁止**です。すべての関数本体・分岐・戻り値を実コードとして書き切ってください。
- 出力が途中で切れた場合は、ユーザーが「続き」と言ったら、続きを最後まで出力してください（コードの再掲は不要、切れた箇所から継続）。

### アプリ全体の前提（このファイルに関係する分のみ）

- Python 3.10+ / GUI は PySide6(Qt6)。ただし本ファイルは GUI を一切扱わず、Qt も import しない。matplotlib のみに依存する純粋なユーティリティモジュールである。
- 日本語表示に `family="monospace"` を**使わない**（□（豆腐）化けを避ける）。日本語フォントの設定とマイナス記号の文字化け防止（`axes.unicode_minus = False`）は、この `jp_font.py` が一手に担う中核モジュールである。アプリの各所はこのモジュールを呼んで日本語フォントを有効化する。
- `batch_render` などの spawn 安全な経路からも import されうるため、Qt 非依存・副作用は matplotlib の rcParams 設定のみに限定する。

---

## 役割 / 責務

`matplotlib` に日本語フォントを設定するユーティリティモジュール。

docstring（モジュール冒頭）の趣旨は次のとおり（この文面をモジュール docstring として記載すること）:

> matplotlib に日本語フォントを設定するユーティリティ。
>
> OS にインストールされている一般的な日本語フォントを優先順に探し、
> 最初に見つかったものを matplotlib の既定フォントに設定する。
> タイトル・軸ラベル・凡例の日本語が文字化け（□□□）しないようにする。

要約すると:

- OS（Windows / macOS / Linux）にインストール済みの代表的な日本語フォントを、決め打ちした優先順位リストの上から順に探索する。
- 最初に見つかったフォントを matplotlib の既定フォント（`font.family = "sans-serif"` の sans-serif 先頭）に設定する。
- 併せて `axes.unicode_minus = False` を設定し、マイナス記号（−）の文字化けを防ぐ。
- 採用したフォント名を返す。見つからなければ `None` を返す（ただしマイナス記号対策だけは必ず適用する）。

---

## 依存（import するもの）

ファイル先頭で次の 2 つだけを import する（この順序）:

```python
import matplotlib
import matplotlib.font_manager as fm
```

- Qt / PySide6 は import しない。
- numpy / scipy も import しない。
- ロギングや print も行わない（副作用は rcParams 設定のみ）。

---

## モジュール定数（正確な値そのまま）

モジュールレベルに、探索する日本語フォント候補のリストを定義する。変数名は `_CANDIDATES`（先頭アンダースコアの非公開定数）。コメント付きで、OS ごとに区切って次の**順序のまま**列挙すること。

```python
# 優先順位（上から順に探す）。Windows / macOS / Linux の代表的な日本語フォント。
_CANDIDATES = [
    # Windows
    "Yu Gothic", "Meiryo", "BIZ UDGothic", "MS Gothic", "MS PGothic", "Yu Mincho",
    # macOS
    "Hiragino Sans", "Hiragino Kaku Gothic Pro", "Hiragino Maru Gothic Pro",
    # Linux（インストールされていれば）
    "Noto Sans CJK JP", "IPAexGothic", "IPAGothic", "TakaoGothic", "VL Gothic",
]
```

要点:

- 順序が**そのまま優先順位**になる（前方ほど優先）。並びを変えてはならない。
- 文字列は上記のとおり正確に（"Yu Gothic" のスペース、"MS PGothic" の大文字小文字、"Noto Sans CJK JP" の表記など完全一致）。
- Windows 6 件 → macOS 3 件 → Linux 5 件、合計 14 件。

---

## 公開 API（完全なシグネチャと挙動）

このモジュールには関数が 2 つだけある。クラスはない。両方ともモジュールレベルのトップレベル関数。

### 1. `available_japanese_fonts()`

```python
def available_japanese_fonts():
```

- 引数なし。
- docstring: `"""利用可能な日本語フォント名の一覧を優先順で返す。"""`
- 役割: 現在 matplotlib が認識しているインストール済みフォントのうち、`_CANDIDATES` に含まれるものだけを、**`_CANDIDATES` の優先順を保ったまま**リストで返す。
- アルゴリズム（擬似コード）:
  1. `installed = {f.name for f in fm.fontManager.ttflist}` で、インストール済みフォント名の**集合（set）**を作る（`fm.fontManager.ttflist` は `FontEntry` のリスト、各要素の `.name` 属性がフォント名）。
  2. `_CANDIDATES` をその並び順で走査し、`name in installed` を満たすものだけを集めたリスト内包表記を返す: `return [name for name in _CANDIDATES if name in installed]`。
- 戻り値の形: `list[str]`（0 件なら空リスト）。並びは `_CANDIDATES` 準拠（インストール集合の並びには依存しない）。
- 副作用: なし（rcParams を変更しない）。

### 2. `setup_japanese_font(preferred=None)`

```python
def setup_japanese_font(preferred=None):
```

- 引数: `preferred`（位置/キーワード両用、デフォルト `None`）。キーワード専用マーカー `*` は使わない。
- docstring（NumPy スタイル。次の内容を記載すること）:

  ```
  日本語フォントを matplotlib に設定し、採用したフォント名を返す。

  Parameters
  ----------
  preferred : str | None
      明示的に使いたいフォント名。利用可能ならこれを最優先で採用する。

  Returns
  -------
  str | None
      採用したフォント名。見つからなければ None。
  ```

- 役割: 候補フォントを優先順に探索し、最初にインストール済みだったものを matplotlib の既定 sans-serif 先頭に設定して、その名前を返す。`preferred` が与えられた場合はそれを最優先で試す。
- アルゴリズム（擬似コード、精密に）:
  1. `installed = {f.name for f in fm.fontManager.ttflist}`（インストール済みフォント名の集合）。
  2. 探索順リスト `order` を構築する:
     - `order = []`
     - `if preferred:`（真値判定。`None` や空文字列はスキップ） → `order.append(preferred)`
     - `order.extend(_CANDIDATES)`
     - ※ `preferred` が `_CANDIDATES` に含まれていても重複排除はしない（リスト先頭に同名が二重に入りうるが、後段の探索は最初の一致で `return` するため実害なし）。
  3. `for name in order:` で先頭から走査し、最初に `name in installed` を満たした `name` について以下を実行して即 `return name`:
     - `matplotlib.rcParams["font.family"] = "sans-serif"`
       - コメント: `# sans-serif の先頭に入れておくと未指定箇所でも日本語が出る`
     - `current = matplotlib.rcParams.get("font.sans-serif", [])`（現行の sans-serif フォールバック列を取得。未設定時は空リスト）
     - `matplotlib.rcParams["font.sans-serif"] = [name] + [f for f in current if f != name]`
       - 採用フォントを**先頭**に置き、既存リストから**同名を除いた**残りを後ろに連結する（重複防止＋優先順位確立）。
     - `matplotlib.rcParams["axes.unicode_minus"] = False`
       - コメント: `# マイナス記号の文字化け防止`
     - `return name`
  4. ループを抜けた（＝候補が 1 つもインストールされていない）場合のフォールバック:
     - コメント: `# 日本語フォントが見つからない場合も、最低限マイナス記号の化けだけは防ぐ`
     - `matplotlib.rcParams["axes.unicode_minus"] = False`
     - `return None`
- 戻り値の形: `str`（採用フォント名）または `None`。
- 副作用: 採用時は `font.family` / `font.sans-serif` / `axes.unicode_minus` の 3 つの rcParams を変更。未採用時は `axes.unicode_minus` のみ変更。

---

## 再現に必須の細部 / エッジケース / ガード

- **優先順位の二段構え**: `preferred` を先頭に積んでから `_CANDIDATES` を続ける。これにより「明示指定 → OS 標準の優先順」の順で探索される。
- **真値判定**: `if preferred:` は `None` だけでなく空文字列 `""` も弾く（空文字を `order` に積まない）。`preferred=None` を明示しても省略しても同じ挙動。
- **インストール判定は set（`installed`）** を使い、`in` 判定を O(1) にする。`available_japanese_fonts` / `setup_japanese_font` の両方で同じ作り方（`{f.name for f in fm.fontManager.ttflist}`）。
- **sans-serif リストの再構成**は `[name] + [f for f in current if f != name]`。採用フォントを必ず先頭にし、既存列から同名を除去して重複させない。`current` が空でも `[name]` だけになるので安全。
- **採用順は最初の一致で確定**: `for` ループ内で `return` するため、最初にヒットした候補のみが設定対象。後続候補は評価されない。
- **どの分岐でも `axes.unicode_minus = False` を必ず適用**する（採用時はループ内、未採用時はフォールバックで）。これが抜けるとマイナス記号が □ 化けする。
- **戻り値の使われ方**: 呼び出し側はフォント名（または `None`）を受け取れる。`None` の場合でもマイナス記号対策は済んでいる前提で良い。
- **副作用は matplotlib の rcParams のみ**。ファイル I/O・ネットワーク・print・例外送出のいずれも行わない（フォント未発見は例外ではなく `None` で表現する）。

---

## このファイルに関係する落とし穴

- **monospace 回避**: 日本語に `family="monospace"` を使うと □ 化けする。本モジュールは `font.family` を一貫して `"sans-serif"` に設定し、sans-serif 先頭に日本語フォントを差し込む方針。`"monospace"` を設定してはならない。
- **`axes.unicode_minus = False` の徹底**: 採用・未採用の**両方の経路**で設定する。片方だけだとフォント未検出環境でマイナス記号が化ける。
- **Qt 非依存**: このモジュールは Qt / PySide6 を import しない。`batch_render`（spawn 安全な別プロセス）からも安全に import できる前提を壊さないこと。
- **`_CANDIDATES` の並び**は仕様（優先順位）そのもの。並べ替え・追加削除・表記ゆれ（スペースや大文字小文字）を起こさない。
- **重複排除を `order` 構築時に行わない**設計を踏襲する（最初の一致で `return` するため不要。余計な `set` 化で順序を壊さない）。
- **grid linewidth=None 問題・Mixin 規約・facade** などは本ファイルには無関係（GUI/プロット本体側の事項）。本ファイルでは考慮不要。
