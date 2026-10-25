# -*- coding: utf-8 -*-
"""data_loader の読み込み正しさ（回帰）。

issue #2: 桁区切り '1,234'・SI接頭辞/単位付き '3.3k' '1.2V' が NaN で欠落していた。
issue #3: ヘッダ無し数値CSVで先頭行が列名に化けて1行消えていた。
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import data_loader  # noqa: E402


def _load(content, suffix=".csv", encoding="utf-8"):
    fd, path = tempfile.mkstemp(suffix=suffix)
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="") as f:
            f.write(content)
        df, _enc, _delim = data_loader.load_table(path)
        return df
    finally:
        os.remove(path)


# ---------------- #3 ヘッダ有無の判定 ----------------
def test_headerless_numeric_csv_keeps_first_row():
    """ヘッダ無し数値CSV: 先頭行がデータとして残り、列名は 列1,列2…。"""
    df = _load("0.5,1.2\n0.6,1.3\n0.7,1.4\n")
    assert len(df) == 3, df                      # 先頭行が消えない
    assert list(df.columns) == ["列1", "列2"]     # 数値が列名に化けない
    assert df["列1"].tolist() == [0.5, 0.6, 0.7]


def test_header_csv_is_detected():
    """見出し付きCSV: 先頭行はヘッダとして使われる（従来どおり）。"""
    df = _load("時間,電圧\n0,1\n0.1,2\n0.2,3\n")
    assert list(df.columns) == ["時間", "電圧"]
    assert len(df) == 3
    assert "電圧" in data_loader.numeric_columns(df)


# ---------------- #2 桁区切り・SI/単位 ----------------
def test_thousands_separator_recovered():
    """桁区切り '1,234'（クオート済み）が数値へ復元される。"""
    df = _load('値\n"1,234"\n"5,678"\n"-9,000"\n')
    assert "値" in data_loader.numeric_columns(df)
    assert df["値"].tolist() == [1234.0, 5678.0, -9000.0]


def test_si_prefix_and_unit_recovered():
    """SI接頭辞 '3.3k'→3300、単位付き '1.2V'→1.2（アプリ共通の parse_eng 規約）。"""
    df = _load("抵抗\n3.3k\n4.7k\n1k\n")
    assert df["抵抗"].tolist() == [3300.0, 4700.0, 1000.0]
    df2 = _load("電圧\n1.2V\n3.4V\n5.6V\n")
    assert np.allclose(df2["電圧"].to_numpy(), [1.2, 3.4, 5.6])


# ---------------- 回帰防止（壊してはいけないもの）----------------
def test_category_column_preserved():
    """文字列カテゴリ列は数値化されず、値もそのまま残る。"""
    df = _load("名前,値\nA,10\nB,20\nC,30\n")
    assert "名前" not in data_loader.numeric_columns(df)
    assert df["名前"].tolist() == ["A", "B", "C"]
    assert "値" in data_loader.numeric_columns(df)


def test_european_decimal_comma_not_corrupted():
    """桁区切りでないカンマ（欧州式小数 '1,5' 等）は 15 や 1 に壊さない。"""
    # タブ区切りにして '1,5' を1フィールドとして読む
    df = _load("x\ty\n1,5\t10\n2,5\t20\n3,5\t30\n")
    assert "x" not in data_loader.numeric_columns(df)   # 数値列に化けない
    assert df["x"].tolist() == ["1,5", "2,5", "3,5"]    # 値は不変（NaN化・切詰めなし）
    assert df["y"].tolist() == [10, 20, 30]


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    ok = 0
    for fn in fns:
        try:
            fn(); ok += 1; print(f"  [PASS] {fn.__name__}")
        except Exception:
            traceback.print_exc(); print(f"  [FAIL] {fn.__name__}")
    print(f"総合: {ok}/{len(fns)} PASS")
    sys.exit(0 if ok == len(fns) else 1)
