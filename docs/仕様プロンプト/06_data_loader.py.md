# [6/30] data_loader.py の仕様

## 指示

- **この仕様だけを読んで `data_loader.py` を完全な形で実装し、その全文を出力してください。**
- **`pass`・`TODO`・「（省略）」・要約・部分実装は禁止です。** すべての関数を最後まで完全に書き切ってください。
- **出力が途中で切れた場合は、「続き」と言われたら続きを最後まで出力してください。**

### アプリ全体の前提（本ファイルに関係する分のみ）

- Python 3.10+ / GUI は PySide6(Qt6) を使うアプリだが、**本ファイルは純粋なデータ読み込みモジュールであり、Qt も matplotlib も一切 import しない**（GUI 非依存・spawn 安全）。
- `scipy` 等の重い依存も使わない。依存は標準ライブラリ（`csv`, `os`）と `pandas` のみ。`charset_normalizer` は存在すれば使うが、無くても動く（遅延 import ＋ 例外握りつぶし）。
- 日本語 CSV を主たる対象とする。文字コード・区切り文字を堅牢に自動判定することが本ファイルの存在意義。

---

## 1. ファイルの役割 / 責務

CSV / TSV ファイルの読み込みを担うモジュール。

docstring（モジュール冒頭）の趣旨は次のとおり（この文面をそのまま docstring にする）:

```
CSV / TSV ファイルの読み込み。

文字コード（UTF-8 / UTF-8 BOM付き / Shift_JIS(CP932) など）と
区切り文字（カンマ / タブ / セミコロン）を自動判定して
pandas.DataFrame として読み込む。日本語 CSV を想定。
```

責務:
- ファイルの**文字コードを推定**する（BOM 優先 → UTF-8 厳密判定 → 日本語候補の復号スコア → charset-normalizer ヒント → 欧文フォールバック）。
- ファイルの**区切り文字を推定**する（拡張子優先 → `csv.Sniffer` → 出現回数）。
- 上記を使って `pandas.DataFrame` として**読み込み**、使用した encoding / delimiter とともに返す。C エンジン優先・python エンジンフォールバック。
- **列名の正規化**（文字列化・空白除去・重複の一意化）。
- DataFrame から**数値列の一覧**を抽出（グラフの値軸候補）。

---

## 2. 依存（import するもの）

ファイル先頭で次を import する（この順序）:

```python
import csv
import os

import pandas as pd
```

- `charset_normalizer.from_bytes` は `detect_encoding` の内部で**遅延 import**する（トップレベルでは import しない）。
- それ以外の外部依存は無い。

---

## 3. モジュール定数・データ（正確な値そのまま）

ファイル冒頭（import の直後）に、以下を**この値・この順序・このコメント**で定義する。

```python
# 試行する文字コード（日本語環境でよくある順）。
# UTF-8 系を先に試し、最後に必ず成功する latin-1 をフォールバックに置く。
_ENCODINGS = ["utf-8-sig", "utf-8", "cp932", "shift_jis", "euc-jp", "latin-1"]

# 自動判定で候補とする区切り文字
_DELIMITERS = [",", "\t", ";", "|"]

DELIMITER_LABELS = {
    ",": "カンマ ( , )",
    "\t": "タブ ( \\t )",
    ";": "セミコロン ( ; )",
    "|": "パイプ ( | )",
}
```

注意点:
- `_ENCODINGS` は定義しておくが（他モジュールからの参照・将来用途のため公開的に保持）、`detect_encoding` 本体は後述の独自ロジックを使う。値は上記 6 要素を正確に保持すること。
- `_DELIMITERS` は **4 要素**（カンマ・タブ・セミコロン・パイプ）。順序も重要（`max` のタイブレークやループ順に影響）。
- `DELIMITER_LABELS` は **公開定数**（先頭にアンダースコアなし）。GUI 側で区切り文字のラベル表示に使われる。タブのラベル値は `"タブ ( \\t )"` で、ソース上は `"タブ ( \\t )"`（バックスラッシュをエスケープして文字列として `\t` の 2 文字が表示される形）にする。キーは実際のタブ文字 `"\t"`。

---

## 4. 公開 API（完全なシグネチャと挙動）

### 4.1 `_japanese_score(text)`

```python
def _japanese_score(text):
```

- 役割: テキスト中の「日本語文字数」と「壊れた文字数」をカウントして返すヘルパー。
- docstring: `"テキスト中の日本語文字数と、壊れた文字（私用領域・置換文字）数を返す。"`
- アルゴリズム:
  - `jp = bad = 0` で初期化。
  - `text` の各文字 `ch` について `o = ord(ch)` を取り、
    - 日本語とみなす範囲のいずれかに入れば `jp += 1`:
      - `0x3040 <= o <= 0x30FF`（ひらがな・カタカナ）
      - または `0x4E00 <= o <= 0x9FFF`（CJK 統合漢字）
      - または `0xFF00 <= o <= 0xFFEF`（半角・全角形）
    - そうでなく、壊れた文字とみなす条件に入れば `bad += 1`:
      - `0xE000 <= o <= 0xF8FF`（私用領域 PUA）
      - または `ch == "�"`（U+FFFD 置換文字）
  - これらは `if / elif` の関係（日本語判定が優先）。
- 戻り値: タプル `(jp, bad)`。

### 4.2 `detect_encoding(path)`

```python
def detect_encoding(path):
```

- 役割: ファイルの文字コードを推定して文字列で返す。
- docstring:
  ```
  ファイルの文字コードを推定して返す。

  BOM を最優先で判定し、なければ候補を順に decode して最初に成功したものを返す。
  どれも失敗した場合は何でも復号できる latin-1 を返す（最終フォールバック）。
  ```
- アルゴリズム（**この順序を厳守**。各ステップの判定が決め手）:

  1. ファイルをバイナリで全読み: `with open(path, "rb") as f: raw = f.read()`。

  2. **BOM 判定（最優先）**:
     - `raw.startswith(b"\xef\xbb\xbf")` なら `return "utf-8-sig"`。
     - `raw.startswith((b"\xff\xfe", b"\xfe\xff"))` なら `return "utf-16"`。

  3. **UTF-8 厳密判定**: `raw.decode("utf-8")` を試し、成功したら `return "utf-8-sig"`（BOM 無し UTF-8 も `utf-8-sig` を返す＝BOM があっても無くても同じ指定で読めるため）。`UnicodeDecodeError` は `pass` で次へ。

  4. **日本語候補の復号スコア比較**:
     - `best_jp = None`。
     - `for enc in ("cp932", "euc-jp"):` の順で:
       - `text = raw.decode(enc)` を試行。`(UnicodeDecodeError, LookupError)` なら `continue`。
       - `jp, bad = _japanese_score(text[:100000])`（先頭 10 万文字だけ採点）。
       - `if bad == 0 and jp > 0 and (best_jp is None or jp > best_jp[1]):` のとき `best_jp = (enc, jp)` に更新。
     - ループ後 `if best_jp: return best_jp[0]`。
     - 目的: 欧文ファイルへ cp932 を強制したり、euc-jp が big5 等へ誤判定するのを防ぐ。「壊れた文字が 0 かつ日本語を含む」候補のうち日本語文字数が最大のものを選ぶ。

  5. **charset-normalizer ヒント（日本語系のみ採用）**:
     - 許容名集合:
       ```python
       jp_names = {"cp932", "shift-jis", "shift_jis", "sjis", "ms932",
                   "windows-31j", "euc-jp", "euc_jp", "iso-2022-jp"}
       ```
     - エイリアス変換表:
       ```python
       alias = {"shift-jis": "cp932", "shift_jis": "cp932", "sjis": "cp932",
                "ms932": "cp932", "windows-31j": "cp932", "euc_jp": "euc-jp"}
       ```
     - `try:` ブロック内で `from charset_normalizer import from_bytes`、`best = from_bytes(raw).best()`。
     - `if best is not None and best.encoding:` のとき、`enc = best.encoding.lower().replace("_", "-")` に正規化。
     - `if enc in jp_names or "jp" in enc or "932" in enc:` なら `return alias.get(enc, enc)`。
     - 全体を `except Exception: pass` で囲む（charset_normalizer 未インストール・実行時エラーでも落ちない）。

  6. **欧文・その他フォールバック**:
     - `for enc in ("cp1252", "latin-1"):` で `raw.decode(enc)` を試し、成功した最初のものを返す。`(UnicodeDecodeError, LookupError)` なら `continue`。
     - それでも決まらなければ最後に `return "latin-1"`（latin-1 は任意バイト列を復号できる最終フォールバック）。

- 戻り値: encoding 名の文字列。

### 4.3 `detect_delimiter(path, encoding)`

```python
def detect_delimiter(path, encoding):
```

- 役割: 区切り文字を推定して 1 文字の文字列で返す。
- docstring: `"区切り文字を推定して返す。拡張子を優先し、なければ内容から判定する。"`
- アルゴリズム:
  1. `ext = os.path.splitext(path)[1].lower()`。
  2. **拡張子優先**: `if ext == ".tsv": return "\t"`。
  3. **サンプル読み込み**: `try: with open(path, encoding=encoding, errors="replace") as f: sample = f.read(8192)`。例外 `(OSError, LookupError)` のときは `return "," if ext == ".csv" else "\t"`。
  4. **空サンプル**: `if not sample: return "," if ext == ".csv" else "\t"`。
  5. **csv.Sniffer 判定**:
     - `try: dialect = csv.Sniffer().sniff(sample, delimiters="".join(_DELIMITERS))`。
     - `if dialect.delimiter in _DELIMITERS: return dialect.delimiter`。
     - `except csv.Error: pass`。
  6. **出現回数による判定（Sniffer 失敗時）**:
     - `first_line = sample.splitlines()[0] if sample.splitlines() else sample`（先頭行を取得。行が無ければ sample 全体）。
     - `counts = {d: first_line.count(d) for d in _DELIMITERS}`。
     - `best = max(counts, key=counts.get)`（最頻の区切り文字。同数なら `_DELIMITERS` の並び順で最初のもの）。
     - `if counts[best] > 0: return best`。
  7. **最終フォールバック**: `return "," if ext == ".csv" else "\t"`。
- 戻り値: 1 文字の区切り文字。

### 4.4 `load_table(path, encoding=None, delimiter=None)`

```python
def load_table(path, encoding=None, delimiter=None):
```

- 役割: CSV/TSV を読み込み、`(DataFrame, 使用した encoding, 使用した delimiter)` のタプルを返す。
- docstring:
  ```
  CSV/TSV を読み込み (DataFrame, 使用した encoding, 使用した delimiter) を返す。

  encoding / delimiter を None にすると自動判定する。
  ```
- アルゴリズム:
  1. **存在チェック**: `if not os.path.isfile(path): raise FileNotFoundError(f"ファイルが見つかりません: {path}")`。
  2. **自動判定**: `encoding is None` なら `encoding = detect_encoding(path)`。`delimiter is None` なら `delimiter = detect_delimiter(path, encoding)`。
  3. **エンジン選択**:
     - `use_c = bool(delimiter) and len(delimiter) == 1`（単一文字区切りのときだけ C エンジンを使う。C は python の約 7 倍速い）。
     - `base_kwargs = dict(sep=delimiter, skip_blank_lines=True)`。
  4. **内部関数 `_read(**extra)`**:
     ```python
     def _read(**extra):
         if use_c:
             try:
                 return pd.read_csv(path, engine="c", **base_kwargs, **extra)
             except (pd.errors.ParserError, ValueError):
                 pass  # 不整列・特殊ケースは python エンジンで再試行
         return pd.read_csv(path, engine="python", **base_kwargs, **extra)
     ```
     - C エンジンで読み、`(pd.errors.ParserError, ValueError)` のときは python エンジンへフォールバック。
  5. **読み込み（例外処理付き）**:
     ```python
     try:
         df = _read(encoding=encoding)
     except UnicodeDecodeError:
         df = _read(encoding=encoding, encoding_errors="replace")
     except pd.errors.EmptyDataError:
         raise ValueError("ファイルが空か、データ行がありません。")
     ```
     - 文字コードで読めない場合は `encoding_errors="replace"` を付けて強制再読み込み。
     - 空ファイルは `ValueError("ファイルが空か、データ行がありません。")`。
  6. **列ゼロチェック**: `if df.shape[1] == 0: raise ValueError("列を読み取れませんでした。区切り文字を確認してください。")`。
  7. **列名の正規化と一意化**:
     ```python
     used = set()
     new_cols = []
     for c in df.columns:
         base = str(c).strip() or "列"
         name, k = base, 1
         while name in used:  # 生成した名前も含めて必ず一意化する
             name = f"{base}.{k}"
             k += 1
         used.add(name)
         new_cols.append(name)
     df.columns = new_cols
     ```
     - 各列名を `str(c).strip()` で文字列化＆前後空白除去。**空文字になったら `"列"`** をベース名にする（`or "列"`）。
     - すでに使われている名前なら `f"{base}.{k}"`（`k` は 1 から増加）で一意化。生成した名前も `used` と照合して必ず一意にする。
     - 目的: 空白除去で重複が生じると `df[col]` が DataFrame になり数値判定・描画が壊れるため、pandas 同様 `.1` 付与で一意化。
  8. 戻り値: `return df, encoding, delimiter`。

### 4.5 `numeric_columns(df)`

```python
def numeric_columns(df):
```

- 役割: 数値として扱える列名の一覧を返す（グラフの値軸候補）。
- docstring: `"数値として扱える列名の一覧を返す（グラフの値軸候補）。"`
- アルゴリズム:
  - `cols = []`。
  - 各列 `c` について `s = pd.to_numeric(df[c], errors="coerce")` で数値変換を試み、`if s.notna().mean() >= 0.8:`（**8 割以上**が数値に変換できれば数値列とみなす）なら `cols.append(c)`。
  - コメント: `# 8割以上が数値なら数値列とみなす`。
- 戻り値: 列名のリスト（元の列順を保持）。

---

## 5. 再現に必須の細部・エッジケース・ガード

- **判定順序の厳守**: `detect_encoding` は「BOM → UTF-8 厳密 → 日本語候補スコア → charset-normalizer → 欧文」の順。この順序が日本語ファイルと欧文ファイルの誤判定回避の要。
- **UTF-8 は `utf-8-sig` を返す**: BOM 無しでも `utf-8-sig` を返すことで、BOM 付き/無しのどちらでも安全に読める。
- **日本語スコアは先頭 10 万文字のみ採点**（`text[:100000]`）で性能を確保。
- **`bad == 0 and jp > 0`** が日本語候補採用の条件。壊れた文字（PUA・置換文字）が 1 つでもあればその候補は不採用。
- **charset-normalizer は日本語系のみ採用**: ヒントが `jp_names` に含まれるか、名前に `"jp"` または `"932"` を含む場合のみ採用。それ以外のヒントは無視（欧文は後段のフォールバックに委ねる）。
- **`charset_normalizer` 未インストールでも動く**: `try/except Exception: pass` で全体を保護。遅延 import。
- **`latin-1` は最終フォールバック**: 任意バイト列を復号できるため必ず成功する。
- **エンジンフォールバック**: 単一文字区切りのみ C エンジンを使用。`ParserError`/`ValueError` で python エンジンへ。複数文字区切り（`len != 1`）や空区切りは最初から python エンジン。
- **`UnicodeDecodeError` → `encoding_errors="replace"`** で強制読み込み（文字化けしてでも読む）。
- **空ファイル / 列ゼロ** はそれぞれ専用の `ValueError` メッセージを送出（文言を正確に）。
- **列名の重複一意化**は `while` ループで「生成した名前も含めて」衝突チェックする点が重要（単純な 1 回付与では不十分なケースがある）。
- **空列名は `"列"`** にフォールバック。
- **`numeric_columns` の閾値は 0.8**（`>=`）。`notna().mean()` を使うため NaN 比率で判定。

---

## 6. 本ファイルに関係する落とし穴

- **Qt / matplotlib を import しない**: 本モジュールは GUI 非依存・spawn 安全（バッチ描画プロセスからも安全に import できる）。Qt6 列挙やデバウンス等の GUI 規約は本ファイルには無関係。誤って GUI 依存を持ち込まないこと。
- **`charset_normalizer` の import はトップレベルに置かない**: 必ず関数内の遅延 import かつ例外保護。トップレベル import にすると未インストール環境で起動不能になる。
- **`DELIMITER_LABELS` のタブ表記**: 表示文字列は `"タブ ( \\t )"`（ソース上のエスケープに注意）。キーは実タブ文字 `"\t"`。
- **`_DELIMITERS` の順序を変えない**: `max(..., key=counts.get)` の同数タイブレークが順序依存。
- **戻り値の形を変えない**: `load_table` は必ず 3 要素タプル `(df, encoding, delimiter)`。呼び出し側はこの形に依存する。
- **列名一意化を省略しない**: 重複列があると `df[col]` が DataFrame を返し、数値判定・描画が壊れる。
- **公開名を保つ**: `DELIMITER_LABELS`, `detect_encoding`, `detect_delimiter`, `load_table`, `numeric_columns` は外部から参照される公開 API。名前・シグネチャを変えないこと。
