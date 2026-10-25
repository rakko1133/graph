# -*- coding: utf-8 -*-
"""数値計算の正しさ（回帰）。

issue #7: SciPy 非搭載フォールバックが本物と不一致
  - 歪度/尖度が ddof=1 標準偏差で正規化され scipy.stats と系統差
  - 積分が台形則でなく右端矩形則
  - ピーク検出が distance を無視し高さ順（prominence でない）
issue #8: SFDR が分子=バンド合算/分母=単一ビンで非対称に過大評価
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import numpy as np  # noqa: E402


# ---------------- #7a 歪度/尖度フォールバック == scipy ----------------
def test_moment_skew_kurtosis_matches_scipy():
    from scipy import stats
    import datasci
    rng = np.random.default_rng(0)
    cases = [rng.exponential(1.0, 12),          # 小標本・歪んだ分布（差が出やすい）
             rng.normal(0, 1, 200),
             rng.uniform(-1, 1, 50),
             np.array([1.0, 2, 2, 3, 3, 3, 9])]
    for y in cases:
        sk, ku = datasci._moment_skew_kurtosis(y, float(np.mean(y)))
        assert abs(sk - float(stats.skew(y))) < 1e-9, (sk, stats.skew(y))
        assert abs(ku - float(stats.kurtosis(y))) < 1e-9, (ku, stats.kurtosis(y))


# ---------------- #7b 積分フォールバック == 台形則 ----------------
def test_cumtrapz_fallback_is_trapezoid():
    from scipy.integrate import cumulative_trapezoid
    import mathchan
    x = np.linspace(0, 1, 11)
    y = x.copy()
    r = mathchan._cumtrapz(y, x)
    assert abs(r[-1] - 0.5) < 1e-12, r[-1]      # ∫x dx [0,1] = 0.5（矩形則なら 0.55）
    assert np.allclose(r, cumulative_trapezoid(y, x, initial=0.0))
    # 非一様サンプル・一般波形でも scipy と一致
    x2 = np.array([0.0, 0.1, 0.35, 0.4, 1.0])
    y2 = np.array([1.0, -2.0, 3.0, 0.5, 2.0])
    assert np.allclose(mathchan._cumtrapz(y2, x2),
                       cumulative_trapezoid(y2, x2, initial=0.0))


# ---------------- #7c ピーク検出が distance / prominence を尊重 ----------------
def test_simple_peaks_respects_distance_and_prominence():
    import analysis_common as ac
    sig = np.array([0, 5, 0, 6, 0, 7, 0, 8, 0], dtype=float)

    idx, proms = ac._simple_peaks(sig, distance=1)
    assert idx.tolist() == [1, 3, 5, 7]                 # 全ピーク
    assert np.allclose(proms, [5, 6, 7, 8])             # 顕著さが返る（NaN でない）

    idx, _ = ac._simple_peaks(sig, distance=100)        # 間隔100 → 最も高い1本だけ
    assert idx.tolist() == [7], idx

    idx, proms = ac._simple_peaks(sig, prominence=6)     # 顕著さ6以上のみ
    assert idx.tolist() == [3, 5, 7], idx
    assert np.all(proms >= 6)


# ---------------- #8 SFDR が過大評価されない ----------------
def test_sfdr_is_peak_to_peak_not_inflated():
    import analysis
    fs, n = 10000.0, 4000
    t = np.arange(n) / fs
    # 非整数周期でわざと窓漏れを起こす。基本波 A=1、単一スプリアス A=0.1。
    y = np.sin(2 * np.pi * 300.7 * t) + 0.1 * np.sin(2 * np.pi * 1700.3 * t)
    m = analysis.spectrum_metrics(t, y)
    sfdr = m["SFDR_dB"]
    # 真値: 20*log10(1/0.1) = 20 dB。ピーク対ピークなら漏れが分子分母で相殺され ~20。
    # 旧実装（分子=基本波バンド合算）は数dB過大になる。
    assert abs(sfdr - 20.0) < 2.0, sfdr


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
