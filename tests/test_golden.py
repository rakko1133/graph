# -*- coding: utf-8 -*-
"""数値の黄金値テスト（リファクタで計算結果が変わったら必ず落ちる）。

しきい値交差・中間レベル・スペクトルの実装を統合するとき、境界条件
（NaN・等値点・非50%デューティ）の扱いがずれても、普通のスモークテストでは
気づけない。ここで代表波形の測定値を固定しておき、**値が1つでも動いたら
落ちる**ようにする。

黄金値の更新（意図して値を変えたとき）:
    python tests/test_golden.py --update
差分を必ず目視レビューしてからコミットすること。
"""
import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import numpy as np  # noqa: E402

import advanced  # noqa: E402
import analysis  # noqa: E402

GOLDEN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "golden_values.json")
TOL = 1e-9          # 実装統合では**ビット単位で同じ**を要求する


# ---------------- 代表波形（境界条件をわざと含める）----------------
def _waveforms():
    out = {}
    t = np.linspace(0, 0.01, 2001)

    out["正弦1kHz"] = (t, np.sin(2 * np.pi * 1000 * t))
    out["矩形1kHz"] = (t, np.sign(np.sin(2 * np.pi * 1000 * t)))

    # 非50%デューティ（デューティ25%）。交差判定の左右対称性が崩れていると値が動く
    duty = ((t * 1000) % 1.0 < 0.25).astype(float) * 2 - 1
    out["PWM25%"] = (t, duty)

    # 立ち上がりに有限傾斜（rise/fall time が意味を持つ）
    ramp = np.clip(np.sin(2 * np.pi * 1000 * t) * 4, -1, 1)
    out["台形波"] = (t, ramp)

    # 連続する等値点（y2 == y1）。ゼロ除算ガードの書き方で結果が変わりうる
    flat = np.round(np.sin(2 * np.pi * 500 * t) * 3) / 3.0
    out["階段波"] = (t, flat)

    # NaN 混入（欠測のあるロガーCSVを模す）
    nan_y = np.sin(2 * np.pi * 1000 * t).copy()
    nan_y[500:510] = np.nan
    out["NaN混入"] = (t, nan_y)

    # 高調波つき（THD/SFDR が意味を持つ）
    h = (np.sin(2 * np.pi * 1000 * t)
         + 0.05 * np.sin(2 * np.pi * 2000 * t)
         + 0.02 * np.sin(2 * np.pi * 3000 * t))
    out["高調波あり"] = (t, h)
    return out


def _clean(v):
    """JSON に載る形へ（NaN/inf も文字列として固定する）。"""
    if isinstance(v, (bool, str)) or v is None:
        return v
    if isinstance(v, (int, float, np.floating, np.integer)):
        f = float(v)
        if math.isnan(f):
            return "nan"
        if math.isinf(f):
            return "inf" if f > 0 else "-inf"
        return f
    if isinstance(v, dict):
        return {str(k): _clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple, np.ndarray)):
        return [_clean(x) for x in v]
    return str(v)


def compute():
    """現在の実装で全指標を計算する。"""
    got = {}
    for name, (t, y) in _waveforms().items():
        d = {}
        # 自動測定（43項目）— crossings/mid_level の統合が効く中心。
        # 戻り値は [{"name","value","unit"}, ...] のリスト。
        for row in analysis.measurements(t, y):
            d[f"measure.{row['name']}"] = _clean(row.get("value"))
        # 周期・エッジまわり
        d["cycle_stats"] = _clean(analysis.cycle_stats(t, y))
        d["pulse_metrics"] = _clean(analysis.pulse_metrics(t, y))
        d["edge_intervals"] = _clean(analysis.edge_intervals(t, y))
        d["slew_rate"] = _clean(analysis.slew_rate(t, y))
        d["histogram_top_base"] = _clean(analysis.histogram_top_base(y))
        # スペクトル（rfft の回数を減らす統合で値が変わりやすい）
        d["spectrum_metrics"] = _clean(analysis.spectrum_metrics(t, y))
        d["dominant_frequency"] = _clean(analysis.dominant_frequency(t, y))
        d["occupied_bandwidth"] = _clean(analysis.occupied_bandwidth(t, y))
        d["harmonic_search"] = _clean(analysis.harmonic_search(t, y, n_harm=3))
        f, a = analysis.fft_spectrum(t, y)
        d["fft.len"] = len(f)
        d["fft.peak_freq"] = _clean(f[int(np.argmax(a))])
        d["fft.peak_amp"] = _clean(float(np.max(a)))
        # しきい値交差（5実装あるものの代表）
        d["advanced.auto_threshold"] = _clean(advanced.auto_threshold(y))
        lv = advanced.auto_threshold(y)
        for edge in ("both", "rising", "falling"):
            cr = advanced.crossings(t, y, lv, edge=edge)
            d[f"advanced.crossings.{edge}.n"] = len(cr)
            d[f"advanced.crossings.{edge}.head"] = _clean(list(cr[:5]))
        got[name] = d
    return got


def _walk(prefix, value, out):
    """入れ子の dict/list を「キー: 値」の平らな辞書に潰す。"""
    if isinstance(value, dict):
        for k, v in value.items():
            _walk(f"{prefix}.{k}", v, out)
    elif isinstance(value, list):
        for i, v in enumerate(value):
            _walk(f"{prefix}[{i}]", v, out)
    else:
        out[prefix] = value
    return out


def _flat_diff(exp, got):
    """黄金値と実測の差を (キー, 期待, 実測) で列挙する。"""
    diffs = []
    for wave in sorted(set(exp) | set(got)):
        e = _walk(wave, exp.get(wave, {}), {})
        g = _walk(wave, got.get(wave, {}), {})
        for key in sorted(set(e) | set(g)):
            a, b = e.get(key, "<無し>"), g.get(key, "<無し>")
            if isinstance(a, float) and isinstance(b, float):
                if abs(a - b) <= TOL * max(1.0, abs(a)):
                    continue
            elif a == b:
                continue
            diffs.append((key, a, b))
    return diffs


def test_numeric_results_are_unchanged():
    """全指標が黄金値と一致すること。"""
    assert os.path.isfile(GOLDEN), (
        "黄金値ファイルが無い。`python tests/test_golden.py --update` で作成する")
    with open(GOLDEN, encoding="utf-8") as f:
        expected = json.load(f)
    diffs = _flat_diff(expected, compute())
    if diffs:
        head = "\n".join(f"  {k}: 期待 {a} → 実測 {b}" for k, a, b in diffs[:20])
        raise AssertionError(
            f"数値が {len(diffs)} 項目変わった:\n{head}\n"
            "意図した変更なら tests/test_golden.py --update で更新し、差分をレビューすること")


def test_golden_covers_enough():
    """固定している指標が十分な数あること（テストが痩せていないか）。"""
    with open(GOLDEN, encoding="utf-8") as f:
        expected = json.load(f)
    total = sum(len(v) for v in expected.values())
    assert len(expected) >= 7, "波形の種類が少ない"
    assert total >= 300, f"固定している指標が少ない（{total}）"


def update():
    got = compute()
    with open(GOLDEN, "w", encoding="utf-8") as f:
        json.dump(got, f, ensure_ascii=False, indent=1, sort_keys=True)
    print(f"黄金値を更新: {GOLDEN}")
    print(f"  波形 {len(got)} 種 / 指標 {sum(len(v) for v in got.values())} 項目")


if __name__ == "__main__":
    if "--update" in sys.argv:
        update()
        sys.exit(0)
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    ok = 0
    for fn in tests:
        try:
            fn()
            print(f"  [PASS] {fn.__name__}")
            ok += 1
        except Exception:  # noqa: BLE001
            import traceback
            print(f"  [FAIL] {fn.__name__}")
            print(traceback.format_exc())
    print(f"総合: {ok}/{len(tests)} PASS")
    sys.exit(0 if ok == len(tests) else 1)
