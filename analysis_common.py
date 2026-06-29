# -*- coding: utf-8 -*-
"""解析の共通プリミティブ（窓関数・ピーク検出・ゼロ交差・Top/Base 等）。"""
import importlib.util as _ilu

import numpy as np

_trapz = getattr(np, "trapezoid", None) or np.trapz
_HAVE_SCIPY = _ilu.find_spec("scipy") is not None
WINDOWS = ["hann", "hamming", "blackman", "blackmanharris", "flattop",
           "kaiser", "gaussian", "rect"]


def sampling_rate(t):
    """時間軸 t[s] から平均サンプリング周波数[Hz]を推定する。"""
    t = np.asarray(t, dtype=float)
    if t.size < 2:
        return None
    dt = np.median(np.diff(t))
    return 1.0 / dt if dt > 0 else None


def _simple_peaks(sig, distance=1):
    """scipy が無い場合の素朴な極大検出。"""
    idx = np.where((sig[1:-1] > sig[:-2]) & (sig[1:-1] >= sig[2:]))[0] + 1
    return idx


def smooth_signal(y, window):
    """移動窓で平滑化（Savitzky-Golay 優先、無ければ移動平均）。ノイズ低減用。"""
    y = np.asarray(y, dtype=float)
    w = int(window)
    if w < 3 or w > y.size:
        return y
    if w % 2 == 0:
        w += 1
    try:
        from scipy.signal import savgol_filter
        return savgol_filter(y, w, min(2, w - 1))
    except Exception:
        k = np.ones(w) / w
        return np.convolve(y, k, mode="same")


def find_signal_peaks(y, t=None, n=5, prominence_frac=0.05, distance=None,
                      mode="max", smooth=0):
    """信号の主要ピークを上位 n 個、顕著さ(prominence)順で返す。

    第1ピーク・第2ピーク…のように rank 付きで返す。mode="min" で谷を検出。
    smooth>=3 で平滑化してからピーク検出し、ノイズの偽ピークを抑える。

    Returns: list of dict {rank, index, time, value, prominence}
    """
    y = np.asarray(y, dtype=float)
    if y.size < 3:
        return []
    if smooth and smooth >= 3:
        y = smooth_signal(y, smooth)   # 平滑化後の信号でピークを評価
    sig = y if mode == "max" else -y
    span = float(np.nanmax(y) - np.nanmin(y))
    prom = prominence_frac * span if span > 0 else None

    if _HAVE_SCIPY:
        from scipy.signal import find_peaks   # 遅延import（起動を軽くする）
        kwargs = {}
        if prom:
            kwargs["prominence"] = prom
        if distance:
            kwargs["distance"] = int(distance)
        idx, props = find_peaks(sig, **kwargs)
        proms = props.get("prominences")
    else:
        idx = _simple_peaks(sig, distance or 1)
        proms = None

    if len(idx) == 0:
        return []

    if proms is not None and len(proms):
        order = np.argsort(proms)[::-1]
    else:
        order = np.argsort(sig[idx])[::-1]
        proms = np.full(len(idx), np.nan)

    idx_sorted = idx[order][:n]
    prom_sorted = np.asarray(proms)[order][:n]

    peaks = []
    for rank, (i, pr) in enumerate(zip(idx_sorted, prom_sorted), start=1):
        peaks.append({
            "rank": rank,
            "index": int(i),
            "time": float(t[i]) if t is not None else None,
            "value": float(y[i]),
            "prominence": float(pr) if pr == pr else None,  # NaN 判定
        })
    return peaks


def _zero_crossing_period(t, y):
    """平均を引いた信号の上昇ゼロ交差から周期[s]を推定する。"""
    t = np.asarray(t, dtype=float)
    yv = np.asarray(y, dtype=float)
    if np.isfinite(yv).sum() < 3:
        return None
    y0 = yv - np.nanmean(yv)
    sign = np.signbit(y0)                       # True=負
    # 上昇ゼロ交差のみ（負→非負）。立上り/立下りを混ぜると、デューティ比が
    # 50%でない波形（PWM/パルス等）で「上昇間隔」と「下降間隔」が交互に並び、
    # 2×median(半周期) が真の周期からずれてしまう。上昇のみなら全デューティで正しい。
    cross = np.where(np.diff(sign.astype(np.int8)) == -1)[0]
    if cross.size < 2:
        return None
    # 交差点での線形補間をベクトル化（y2==y1 のタイ点は従来同様に除外）
    i = cross
    y1, y2 = y0[i], y0[i + 1]
    mask = y2 != y1
    i, y1, y2 = i[mask], y1[mask], y2[mask]
    tc = t[i] + (-y1) * (t[i + 1] - t[i]) / (y2 - y1)
    if tc.size < 2:
        return None
    per = np.diff(tc)                            # 上昇→上昇 = 1周期
    per = per[per > 0]
    if per.size == 0:
        return None
    period = float(np.median(per))
    return period if period > 0 else None


def _edge_time(t, y, rising=True, lo=0.1, hi=0.9):
    """最初の立上り（または立下り）エッジの 10%-90% 遷移時間を返す。

    0%/100% の基準は実機オシロ標準どおりヒストグラム法の Top/Base（settledした
    高/低レベル）を用い、過渡（オーバーシュート/リンギング）に影響されにくくする。
    ヒストグラムで決められない場合は 5%/95% パーセンタイルにフォールバック。
    10%・90% の交差は「同じエッジ上」で対応付ける（周期信号でも正しく、
    立下りも常に算出できる）。
    """
    t = np.asarray(t, dtype=float)
    y = np.asarray(y, dtype=float)
    if np.isfinite(y).sum() < 3:
        return None
    top, base = histogram_top_base(y)      # 標準: Top/Base を 100%/0% 基準に
    if (top is None or base is None or not np.isfinite(top - base) or (top - base) <= 0):
        base = np.nanpercentile(y, 5)      # フォールバック
        top = np.nanpercentile(y, 95)
    span = top - base
    if not np.isfinite(span) or span <= 0:
        return None
    y_lo = base + lo * span
    y_hi = base + hi * span

    fin = np.isfinite(y)       # NaN は「下」「上」どちらでもない扱いにし、偽の交差を防ぐ
    #   注意: y<level / y>level は NaN に対し常に False になる。両端が有限のときだけ
    #   交差とみなすことで、NaN がエッジ内にあっても偽の交差点を作らない。

    def up_cross(level):       # level を下から上へ横切る位置
        below = y < level
        return np.where(below[:-1] & ~below[1:] & fin[:-1] & fin[1:])[0]

    def down_cross(level):     # level を上から下へ横切る位置
        above = y > level
        return np.where(above[:-1] & ~above[1:] & fin[:-1] & fin[1:])[0]

    if rising:
        lo_idx = up_cross(y_lo)
        if lo_idx.size == 0:
            return None
        i_lo = int(lo_idx[0])
        after = up_cross(y_hi)
        after = after[after > i_lo]     # 同じ立上りで 90% に到達する点
        if after.size == 0:
            return None
        return float(t[int(after[0])] - t[i_lo])
    else:
        hi_idx = down_cross(y_hi)
        if hi_idx.size == 0:
            return None
        i_hi = int(hi_idx[0])
        after = down_cross(y_lo)
        after = after[after > i_hi]     # 同じ立下りで 10% に到達する点
        if after.size == 0:
            return None
        return float(t[int(after[0])] - t[i_hi])


def _window(name, n):
    name = (name or "hann").lower()
    if name == "hamming":
        return np.hamming(n)
    if name == "blackman":
        return np.blackman(n)
    if name in ("blackmanharris", "blackman-harris", "bharris"):
        try:
            from scipy.signal.windows import blackmanharris
            return blackmanharris(n)
        except Exception:
            return np.blackman(n)
    if name == "flattop":
        try:
            from scipy.signal.windows import flattop
            return flattop(n)
        except Exception:
            return np.hanning(n)
    if name == "kaiser":
        return np.kaiser(n, 14.0)            # β=14 ≈ -100dB サイドローブ
    if name == "gaussian":
        try:
            from scipy.signal.windows import gaussian
            return gaussian(n, std=n / 6.0)
        except Exception:
            return np.hanning(n)
    if name in ("none", "rect", "rectangular"):
        return np.ones(n)
    return np.hanning(n)


def to_db(amp, ref=1.0, floor_db=-200.0):
    """振幅を dB（20·log10(amp/ref)）に変換。0 は floor_db に。"""
    amp = np.asarray(amp, dtype=float)
    out = np.full(amp.shape, floor_db)
    nz = amp > 0
    out[nz] = 20.0 * np.log10(amp[nz] / ref)
    return np.maximum(out, floor_db)


def histogram_top_base(y, bins=256):
    """ヒストグラム法で Top(上位の最頻値)・Base(下位の最頻値) を求める。"""
    y = np.asarray(y, dtype=float)
    y = y[np.isfinite(y)]
    if y.size < 4:
        return None, None
    vmin, vmax = float(y.min()), float(y.max())
    if vmax <= vmin:
        return vmin, vmin
    hist, edges = np.histogram(y, bins=bins)
    centers = (edges[:-1] + edges[1:]) / 2.0
    mid = (vmin + vmax) / 2.0
    up, lo = centers >= mid, centers < mid
    top = float(centers[up][np.argmax(hist[up])]) if hist[up].any() else vmax
    base = float(centers[lo][np.argmax(hist[lo])]) if hist[lo].any() else vmin
    return top, base


def _mid_crossings(t, y, level):
    """level を上下に横切る位置（上昇・下降）を返す。"""
    below = y < level
    up = np.where(below[:-1] & ~below[1:])[0]
    down = np.where(~below[:-1] & below[1:])[0]
    return up, down
