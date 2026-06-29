# -*- coding: utf-8 -*-
"""SI接頭辞つき数値フォーマット（format_eng / parse_eng / eng_125_sequence）。"""
import numpy as np


def _eng(x):
    """工学接頭辞付きの簡易表記。"""
    if x == 0:
        return "0"
    units = [(1e-12, "p"), (1e-9, "n"), (1e-6, "µ"), (1e-3, "m"),
             (1, ""), (1e3, "k"), (1e6, "M"), (1e9, "G")]
    for factor, suf in units:
        if abs(x) < factor * 1000:
            return f"{x / factor:.3g}{suf}"
    return f"{x:.3g}"


format_eng = _eng  # 公開名


_ENG_MULT = {"p": 1e-12, "n": 1e-9, "u": 1e-6, "µ": 1e-6, "m": 1e-3,
             "k": 1e3, "M": 1e6, "G": 1e9}


def parse_eng(text, default=None):
    """'1ms' '500us' '2.5' '1e-3' のような入力を float へ変換する。"""
    s = (text or "").strip()
    if not s:
        return default
    try:
        return float(s)  # 1e-3 などはここで確定
    except ValueError:
        pass
    import re
    m = re.match(r"^\s*([+-]?[\d.]+)\s*([a-zA-Zµ]*)", s)
    if not m:
        return default
    try:
        num = float(m.group(1))
    except ValueError:
        return default
    for ch in m.group(2):           # 単位中の SI 接頭辞を探す
        if ch in _ENG_MULT:
            return num * _ENG_MULT[ch]
    return num                       # 単位のみ（例 '2V'）は倍率なし


def eng_125_sequence(lo, hi, suffix=""):
    """lo〜hi を 1-2-5 刻みで並べた表示文字列のリストを返す（オシロのプリセット用）。"""
    seq, dec = [], -12
    while 10.0 ** dec <= hi * 1.0001:
        for m in (1, 2, 5):
            v = m * 10.0 ** dec
            if lo * 0.9999 <= v <= hi * 1.0001:
                seq.append(format_eng(v) + suffix)
        dec += 1
    return seq
