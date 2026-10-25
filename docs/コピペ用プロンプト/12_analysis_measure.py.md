# [12/30] ファイル `analysis_measure.py` を作成

あなたは PySide6 + matplotlib 製のデスクトップアプリ「CSV / TSV / 波形 グラフ・解析ツール」を、複数ファイルに分けて再現しています。
これはその **12 番目** のファイルです（全 30 ファイル）。

## 指示（厳守）
- 下のコードブロックの内容で、ファイル `analysis_measure.py` を**新規作成**してください。
- **一字一句そのまま・省略なし**で出力すること。`pass` だけの空クラス／`# TODO`／`… 省略 …`／要約・解説への置き換えは**禁止**。
- 出力が途中で切れたら、こちらが「続き」と言うので、**最後の行まで**出力してください。
- 前置き・後書き・他ファイルの説明は不要。**このファイルの完全な中身だけ**を返してください。
- 文字コードは UTF-8。フォルダ付きパス（例 `graph_app_mixins/...`）はその階層に作成してください。

## `analysis_measure.py` の中身（このまま出力）
```python
# -*- coding: utf-8 -*-
"""自動測定（Vpp/RMS・立上り・パルス幅・サイクル統計・位相差・一括 analyze）。"""
import numpy as np

from analysis_common import (sampling_rate, find_signal_peaks, _trapz,
                             _zero_crossing_period, _edge_time,
                             histogram_top_base, _mid_crossings)
from analysis_spectrum import dominant_frequency, find_spectral_peaks


def measurements(t, y):
    """主要測定値のリストを返す。各要素は {name, value, unit}。"""
    t = np.asarray(t, dtype=float)
    y = np.asarray(y, dtype=float)
    rows = []

    def add(name, value, unit=""):
        rows.append({"name": name, "value": value, "unit": unit})

    finite = np.isfinite(y)
    has = bool(finite.any())
    vmax = float(np.nanmax(y)) if has else None
    vmin = float(np.nanmin(y)) if has else None
    add("最大値 Vmax", vmax, "V")
    add("最小値 Vmin", vmin, "V")
    add("P-P値 Vpp", (vmax - vmin) if has else None, "V")
    add("平均 Vmean", float(np.nanmean(y)) if has else None, "V")
    add("実効値 Vrms", float(np.sqrt(np.nanmean(y ** 2))) if has else None, "V")
    add("標準偏差 σ", float(np.nanstd(y)) if has else None, "V")

    period = _zero_crossing_period(t, y)
    add("周期", period, "s")
    add("周波数(ゼロ交差)", (1.0 / period) if period else None, "Hz")
    add("周波数(FFT)", dominant_frequency(t, y), "Hz")

    # Top/Base（ヒストグラム法）と振幅・オーバーシュート等
    top, base = histogram_top_base(y) if has else (None, None)
    add("Top", top, "V")
    add("Base", base, "V")
    amp = (top - base) if (top is not None and base is not None) else None
    add("振幅 Vamp(Top-Base)", amp, "V")
    if amp and amp > 0:
        add("オーバーシュート", (vmax - top) / amp * 100.0, "%")
        add("アンダーシュート", (base - vmin) / amp * 100.0, "%")
    else:
        add("オーバーシュート", None, "%")
        add("アンダーシュート", None, "%")

    add("立上り時間 (10-90%)", _edge_time(t, y, rising=True), "s")
    add("立下り時間 (90-10%)", _edge_time(t, y, rising=False), "s")

    # パルス幅・デューティ・エッジ/サイクル数（中央しきい値）
    pm = pulse_metrics(t, y)
    add("+パルス幅", pm.get("pos_width"), "s")
    add("-パルス幅", pm.get("neg_width"), "s")
    add("+デューティ比", pm.get("pos_duty"), "%")
    add("-デューティ比", pm.get("neg_duty"), "%")
    add("立上りエッジ数", pm.get("rising_edges"), "")
    add("サイクル数", pm.get("cycles"), "")

    # エッジ間時間（立上り→立上り 等）
    ei = edge_intervals(t, y)
    add("立上り→立上り", ei.get("rise_to_rise"), "s")
    add("立下り→立下り", ei.get("fall_to_fall"), "s")
    add("立上り→立下り(High幅)", ei.get("rise_to_fall"), "s")
    add("立下り→立上り(Low幅)", ei.get("fall_to_rise"), "s")

    # ピーク到達時刻・面積
    if has:
        add("Time@Max", float(t[int(np.nanargmax(y))]), "s")
        add("Time@Min", float(t[int(np.nanargmin(y))]), "s")
        fin = np.isfinite(y) & np.isfinite(t)
        if fin.sum() >= 2:
            add("面積 ∫y dt", float(_trapz(y[fin], t[fin])), "V·s")
        else:
            add("面積 ∫y dt", None, "V·s")
    else:
        add("Time@Max", None, "s"); add("Time@Min", None, "s")
        add("面積 ∫y dt", None, "V·s")

    add("サンプル数", float(y.size), "点")
    add("サンプリング周波数", sampling_rate(t), "Hz")

    # --- 追加測定（中央値/リプル/スルーレート/サイクル統計/ヒストグラム由来）---
    add("中央値 Median", float(np.nanmedian(y)) if has else None, "V")
    add("リプル(AC RMS)", float(np.nanstd(y)) if has else None, "V")
    sr = slew_rate(t, y)
    add("スルーレート(立上り最大)", sr.get("rise"), "V/s")
    add("スルーレート(立下り最大)", sr.get("fall"), "V/s")
    cs = cycle_stats(t, y)
    add("サイクル平均", cs.get("cycle_mean"), "V")
    add("サイクルRMS", cs.get("cycle_rms"), "V")
    add("Cycle-Cycleジッタ", cs.get("cc_jitter"), "s")
    pd_ = pm.get("pos_duty")
    add("デューティ誤差(50%基準)", (pd_ - 50.0) if pd_ is not None else None, "%")
    hb = histogram_box_stats(y) if has else {}
    add("最頻ビン点数 PEAKHits", hb.get("peak_hits"), "点")
    add("±1σ以内", hb.get("sigma1"), "%")
    add("±2σ以内", hb.get("sigma2"), "%")
    add("±3σ以内", hb.get("sigma3"), "%")
    return rows


def slew_rate(t, y):
    """最大の立上り/立下りスルーレート [V/s]（隣接サンプル間の傾きの最大/最小）。"""
    t = np.asarray(t, dtype=float)
    y = np.asarray(y, dtype=float)
    if t.size < 2:
        return {}
    dt = np.diff(t)
    dy = np.diff(y)
    sl = np.divide(dy, dt, out=np.full_like(dy, np.nan), where=dt != 0)
    sl = sl[np.isfinite(sl)]
    if sl.size == 0:
        return {}
    return {"rise": float(np.max(sl)), "fall": float(np.min(sl))}


def cycle_stats(t, y):
    """サイクル（上昇ゼロ交差〜次の上昇ゼロ交差）単位の平均/RMS と、
    Cycle-Cycle ジッタ（隣り合う周期長の差の標準偏差）を返す。"""
    t = np.asarray(t, dtype=float)
    y = np.asarray(y, dtype=float)
    if t.size < 8:
        return {}
    y0 = y - np.nanmean(y)
    below = y0 < 0
    up = np.where(below[:-1] & ~below[1:])[0]   # 上昇ゼロ交差
    if up.size < 3:
        return {}
    periods = np.diff(t[up])
    means, rmss = [], []
    for a, b in zip(up[:-1], up[1:]):
        seg = y[a:b]
        seg = seg[np.isfinite(seg)]
        if seg.size:
            means.append(float(seg.mean()))
            rmss.append(float(np.sqrt(np.mean(seg ** 2))))
    out = {}
    if means:
        out["cycle_mean"] = float(np.mean(means))
        out["cycle_rms"] = float(np.mean(rmss))
    if periods.size >= 2:
        out["cc_jitter"] = float(np.std(np.diff(periods)))
    return out


def histogram_box_stats(y, bins=256):
    """ヒストグラム由来の測定：最頻ビンの点数 PEAKHits、平均±1/2/3σ内の割合[%]。"""
    y = np.asarray(y, dtype=float)
    y = y[np.isfinite(y)]
    if y.size < 4:
        return {}
    hist, _ = np.histogram(y, bins=bins)
    mean = float(y.mean())
    std = float(y.std())

    def within(k):
        return float(np.mean(np.abs(y - mean) <= k * std) * 100.0) if std > 0 else None

    return {"peak_hits": float(hist.max()),
            "sigma1": within(1), "sigma2": within(2), "sigma3": within(3)}


def cycle_statistics(t, y):
    """サイクルごとの 周波数/周期/振幅/Vpp の統計（min/max/mean/std/count）を返す。
    Returns dict: {param名: {min, max, mean, std, count}}。"""
    cm = cycle_measurements(t, y)
    out = {}
    freq = np.asarray(cm.get("freq", []), dtype=float)
    out["周波数 [Hz]"] = measurement_stats(freq)
    if freq.size:
        out["周期 [s]"] = measurement_stats(1.0 / freq[freq > 0])
    out["振幅 [V]"] = measurement_stats(np.asarray(cm.get("amp", []), dtype=float))
    out["Vpp [V]"] = measurement_stats(np.asarray(cm.get("vpp", []), dtype=float))
    return out


def edge_intervals(t, y, level=None):
    """エッジ間時間（立上り→立上り/立下り→立下り/立上り→立下り/立下り→立上り）の平均[s]。"""
    t = np.asarray(t, dtype=float)
    y = np.asarray(y, dtype=float)
    if np.isfinite(y).sum() < 4:
        return {}
    if level is None:
        top, base = histogram_top_base(y)
        if top is None or top <= base:
            return {}
        level = (top + base) / 2.0
    up, dn = _mid_crossings(t, y, level)

    def cross_times(idx):
        idx = np.asarray(idx, dtype=int)
        if idx.size == 0:
            return np.asarray([], dtype=float)
        y1, y2 = y[idx], y[idx + 1]
        denom = y2 - y1
        f = np.where(denom != 0.0, (level - y1) / np.where(denom != 0.0, denom, 1.0), 0.0)
        return t[idx] + f * (t[idx + 1] - t[idx])

    ut, dt_ = cross_times(up), cross_times(dn)
    res = {}
    if ut.size >= 2:
        res["rise_to_rise"] = float(np.mean(np.diff(ut)))
    if dt_.size >= 2:
        res["fall_to_fall"] = float(np.mean(np.diff(dt_)))
    rf = [dt_[dt_ > u][0] - u for u in ut if (dt_ > u).any()]   # 立上り→次の立下り=High幅
    fr = [ut[ut > d][0] - d for d in dt_ if (ut > d).any()]     # 立下り→次の立上り=Low幅
    if rf:
        res["rise_to_fall"] = float(np.mean(rf))
    if fr:
        res["fall_to_rise"] = float(np.mean(fr))
    return res


def pulse_metrics(t, y, level=None):
    """+/- パルス幅・デューティ・エッジ数・サイクル数を返す。"""
    t = np.asarray(t, dtype=float)
    y = np.asarray(y, dtype=float)
    out = {}
    finite = np.isfinite(y)
    if finite.sum() < 4:
        return out
    if level is None:
        top, base = histogram_top_base(y)
        if top is None or top <= base:
            return out
        level = (top + base) / 2.0
    up, down = _mid_crossings(t, y, level)
    out["rising_edges"] = float(len(up))
    # 高区間（up→次のdown）と低区間（down→次のup）の幅
    highs, lows = [], []
    for u in up:
        nxt = down[down > u]
        if nxt.size:
            highs.append(t[nxt[0]] - t[u])
    for d in down:
        nxt = up[up > d]
        if nxt.size:
            lows.append(t[nxt[0]] - t[d])
    pw = float(np.mean(highs)) if highs else None
    nw = float(np.mean(lows)) if lows else None
    out["pos_width"] = pw
    out["neg_width"] = nw
    if pw and nw:
        out["pos_duty"] = pw / (pw + nw) * 100.0
        out["neg_duty"] = nw / (pw + nw) * 100.0
    out["cycles"] = float(min(len(up), len(down))) if (len(up) and len(down)) else float(len(up))
    return out


def cycle_measurements(t, y):
    """サイクルごとの周波数・振幅の配列を返す（トレンド/統計用）。

    Returns dict: {cycle_time, freq, amp, vpp}（各配列）
    """
    t = np.asarray(t, dtype=float)
    y = np.asarray(y, dtype=float)
    y0 = y - np.nanmean(y)
    below = y0 < 0
    up = np.where(below[:-1] & ~below[1:])[0]  # 上昇ゼロ交差
    res = {"cycle_time": [], "freq": [], "amp": [], "vpp": []}
    for a, b in zip(up[:-1], up[1:]):
        period = t[b] - t[a]
        if period <= 0:
            continue
        seg = y[a:b]
        seg = seg[np.isfinite(seg)]
        if seg.size == 0:
            continue
        res["cycle_time"].append((t[a] + t[b]) / 2.0)
        res["freq"].append(1.0 / period)
        res["vpp"].append(float(seg.max() - seg.min()))
        res["amp"].append(float((seg.max() - seg.min()) / 2.0))
    for k in res:
        res[k] = np.asarray(res[k], dtype=float)
    return res


def measurement_stats(values):
    """測定値配列の min/max/mean/σ/数 を返す。"""
    v = np.asarray(values, dtype=float)
    v = v[np.isfinite(v)]
    if v.size == 0:
        return {"min": None, "max": None, "mean": None, "std": None, "count": 0}
    return {"min": float(v.min()), "max": float(v.max()),
            "mean": float(v.mean()), "std": float(v.std()), "count": int(v.size)}


def phase_delay(t, y1, y2):
    """2チャンネル間の遅延[s]と位相差[deg]を相互相関で求める。"""
    t = np.asarray(t, dtype=float)
    a = np.asarray(y1, dtype=float)
    b = np.asarray(y2, dtype=float)
    n = min(a.size, b.size)
    if n < 4:
        return None, None
    a, b = a[:n], b[:n]
    a = a - np.nanmean(a)
    b = b - np.nanmean(b)
    a = np.nan_to_num(a)
    b = np.nan_to_num(b)
    corr = np.correlate(a, b, mode="full")
    lag = int(np.argmax(corr)) - (n - 1)
    dt = np.median(np.diff(t[:n]))
    delay = -lag * dt              # y2 が遅れていれば正
    period = _zero_crossing_period(t, a)
    phase = (-delay / period * 360.0) if period else None  # 遅れは負位相
    if phase is not None:
        phase = ((phase + 180.0) % 360.0) - 180.0  # -180..180 に正規化
    return float(delay), (float(phase) if phase is not None else None)


def analyze(t, y, n_peaks=5, smooth=0):
    """ピーク・測定・FFT をまとめて返す便利関数。smooth で平滑化してピーク検出。"""
    return {
        "peaks": find_signal_peaks(y, t=t, n=n_peaks, smooth=smooth),
        "troughs": find_signal_peaks(y, t=t, n=n_peaks, mode="min", smooth=smooth),
        "measurements": measurements(t, y),
        "spectral_peaks": find_spectral_peaks(t, y, n=n_peaks),
    }
```
