"""CSV / TSV ファイルの読み込み。

文字コード（UTF-8 / UTF-8 BOM付き / Shift_JIS(CP932) など）と
区切り文字（カンマ / タブ / セミコロン）を自動判定して
pandas.DataFrame として読み込む。日本語 CSV を想定。
"""

import csv
import os

import pandas as pd

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


def _japanese_score(text):
    """テキスト中の日本語文字数と、壊れた文字（私用領域・置換文字）数を返す。"""
    jp = bad = 0
    for ch in text:
        o = ord(ch)
        if (0x3040 <= o <= 0x30FF) or (0x4E00 <= o <= 0x9FFF) or (0xFF00 <= o <= 0xFFEF):
            jp += 1
        elif (0xE000 <= o <= 0xF8FF) or ch == "�":
            bad += 1
    return jp, bad


def detect_encoding(path):
    """ファイルの文字コードを推定して返す。

    BOM を最優先で判定し、なければ候補を順に decode して最初に成功したものを返す。
    どれも失敗した場合は何でも復号できる latin-1 を返す（最終フォールバック）。
    """
    with open(path, "rb") as f:
        raw = f.read()

    if raw.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return "utf-16"

    # 2) UTF-8 として厳密に解釈できればそれを採用（日本語 UTF-8 はここで確定）。
    try:
        raw.decode("utf-8")
        return "utf-8-sig"
    except UnicodeDecodeError:
        pass

    # 3) 日本語候補(cp932/euc-jp)を実際に復号し、日本語文字を含み壊れていない
    #    （私用領域・置換文字が出ない）ものを優先する。これにより欧文ファイルへの
    #    cp932 強制や、euc-jp の big5 等への誤判定を防ぐ。
    best_jp = None
    for enc in ("cp932", "euc-jp"):
        try:
            text = raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
        jp, bad = _japanese_score(text[:100000])
        if bad == 0 and jp > 0 and (best_jp is None or jp > best_jp[1]):
            best_jp = (enc, jp)
    if best_jp:
        return best_jp[0]

    # 4) charset-normalizer のヒント。日本語系(iso-2022-jp 等)のみ採用する。
    jp_names = {"cp932", "shift-jis", "shift_jis", "sjis", "ms932",
                "windows-31j", "euc-jp", "euc_jp", "iso-2022-jp"}
    alias = {"shift-jis": "cp932", "shift_jis": "cp932", "sjis": "cp932",
             "ms932": "cp932", "windows-31j": "cp932", "euc_jp": "euc-jp"}
    try:
        from charset_normalizer import from_bytes

        best = from_bytes(raw).best()
        if best is not None and best.encoding:
            enc = best.encoding.lower().replace("_", "-")
            if enc in jp_names or "jp" in enc or "932" in enc:
                return alias.get(enc, enc)
    except Exception:
        pass

    # 5) 欧文・その他（cp1252 → latin-1 は必ず成功する）
    for enc in ("cp1252", "latin-1"):
        try:
            raw.decode(enc)
            return enc
        except (UnicodeDecodeError, LookupError):
            continue
    return "latin-1"


def detect_delimiter(path, encoding):
    """区切り文字を推定して返す。拡張子を優先し、なければ内容から判定する。"""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".tsv":
        return "\t"

    # 先頭部分を読んで csv.Sniffer と出現回数から推定
    try:
        with open(path, encoding=encoding, errors="replace") as f:
            sample = f.read(8192)
    except (OSError, LookupError):
        return "," if ext == ".csv" else "\t"

    if not sample:
        return "," if ext == ".csv" else "\t"

    try:
        dialect = csv.Sniffer().sniff(sample, delimiters="".join(_DELIMITERS))
        if dialect.delimiter in _DELIMITERS:
            return dialect.delimiter
    except csv.Error:
        pass

    # Sniffer が失敗したら、先頭行での出現回数が最多の区切り文字を採用
    first_line = sample.splitlines()[0] if sample.splitlines() else sample
    counts = {d: first_line.count(d) for d in _DELIMITERS}
    best = max(counts, key=counts.get)
    if counts[best] > 0:
        return best
    return "," if ext == ".csv" else "\t"


def _normalize_columns(df):
    """列名を文字列化・前後空白除去し、重複は ".1" 付与で一意化（CSV/Excel共通）。"""
    used, new_cols = set(), []
    for c in df.columns:
        base = str(c).strip() or "列"
        name, k = base, 1
        while name in used:
            name = f"{base}.{k}"
            k += 1
        used.add(name)
        new_cols.append(name)
    df.columns = new_cols
    return df


def load_table(path, encoding=None, delimiter=None):
    """CSV/TSV/Excel を読み込み (DataFrame, 使用した encoding, 使用した delimiter) を返す。

    encoding / delimiter を None にすると自動判定する。.xlsx/.xls/.xlsm は Excel として読む。
    """
    if not os.path.isfile(path):
        raise FileNotFoundError(f"ファイルが見つかりません: {path}")

    # --- Excel（先頭シート）---
    if os.path.splitext(path)[1].lower() in (".xlsx", ".xlsm", ".xls"):
        try:
            df = pd.read_excel(path)
        except ImportError as e:
            raise ValueError("Excel(.xlsx) の読み込みには openpyxl が必要です"
                             "（pip install openpyxl）。") from e
        if df.shape[1] == 0:
            raise ValueError("シートから列を読み取れませんでした。")
        return _normalize_columns(df), "excel", "excel"

    if encoding is None:
        encoding = detect_encoding(path)
    if delimiter is None:
        delimiter = detect_delimiter(path, encoding)

    # 単一文字区切りは高速な C エンジンで読み、失敗時のみ柔軟な python エンジンへ
    # フォールバックする（C は python の約7倍速い）。複数文字区切り等は python。
    use_c = bool(delimiter) and len(delimiter) == 1
    base_kwargs = dict(sep=delimiter, skip_blank_lines=True)

    def _read(**extra):
        if use_c:
            try:
                return pd.read_csv(path, engine="c", **base_kwargs, **extra)
            except (pd.errors.ParserError, ValueError):
                pass  # 不整列・特殊ケースは python エンジンで再試行
        return pd.read_csv(path, engine="python", **base_kwargs, **extra)

    try:
        df = _read(encoding=encoding)
    except UnicodeDecodeError:
        # 判定した文字コードで読めなければ置換しながら強制的に読み込む
        df = _read(encoding=encoding, encoding_errors="replace")
    except pd.errors.EmptyDataError:
        raise ValueError("ファイルが空か、データ行がありません。")

    if df.shape[1] == 0:
        raise ValueError("列を読み取れませんでした。区切り文字を確認してください。")

    return _normalize_columns(df), encoding, delimiter


def numeric_columns(df):
    """数値として扱える列名の一覧を返す（グラフの値軸候補）。"""
    cols = []
    for c in df.columns:
        s = pd.to_numeric(df[c], errors="coerce")
        if s.notna().mean() >= 0.8:  # 8割以上が数値なら数値列とみなす
            cols.append(c)
    return cols
