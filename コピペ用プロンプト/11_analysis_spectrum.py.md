# [11/30] ファイル `analysis_spectrum.py` を作成

あなたは PySide6 + matplotlib 製のデスクトップアプリ「CSV / TSV / 波形 グラフ・解析ツール」を、複数ファイルに分けて再現しています。
これはその **11 番目** のファイルです（全 30 ファイル）。

## 指示（厳守）
- 下のコードブロックの内容で、ファイル `analysis_spectrum.py` を**新規作成**してください。
- **一字一句そのまま・省略なし**で出力すること。`pass` だけの空クラス／`# TODO`／`… 省略 …`／要約・解説への置き換えは**禁止**。
- 出力が途中で切れたら、こちらが「続き」と言うので、**最後の行まで**出力してください。
- 前置き・後書き・他ファイルの説明は不要。**このファイルの完全な中身だけ**を返してください。
- 文字コードは UTF-8。フォルダ付きパス（例 `graph_app_mixins/...`）はその階層に作成してください。

## `analysis_spectrum.py` の中身（このまま出力）
```python
# -*- coding: utf-8 -*-
"""スペクトル系（FFT・スペクトルピーク・THD/SNR/SINAD/ENOB/SFDR・STFT）。"""
import numpy as np

from analysis_common import sampling_rate, find_signal_peaks, _window


def fft_spectrum(t, y, window="hann", detrend=True):
    """片側振幅スペクトル (freqs[Hz], amplitude) を返す。

    一様サンプリングを仮定し、時間軸からサンプリング周波数を推定する。
    """
    t = np.asarray(t, dtype=float)
    y = np.asarray(y, dtype=float)
    n = y.size
    if n < 4:
        return None, None
    fs = sampling_rate(t)
    if not fs:
        return None, None

    yw = y - np.mean(y) if detrend else y.copy()
    w = _window(window, n)
    yw = yw * w

    spec = np.fft.rfft(yw)
    freqs = np.fft.rfftfreq(n, d=1.0 / fs)
    # 単側振幅（窓のコヒーレントゲインで正規化）
    amp = np.abs(spec) / (np.sum(w) / 2.0)
    # DC とナイキスト（n が偶数のとき rfft の末尾）は負側の共役対が無いため、
    # 片側化の ×2 を掛けてはいけない（掛けると 2 倍に過大評価される）。半分に戻す。
    if amp.size:
        amp[0] *= 0.5
        if n % 2 == 0:
            amp[-1] *= 0.5
    return freqs, amp


def dominant_frequency(t, y):
    """FFT で最大振幅の周波数[Hz]を返す（基本周波数の推定）。"""
    freqs, mag = fft_spectrum(t, y)
    if freqs is None or len(freqs) < 2:
        return None
    m = mag[1:]  # DC を除く
    if m.size == 0 or not np.isfinite(m).any():
        return None  # 全 NaN スペクトル
    if np.nanmax(m) <= 0:
        return None  # 平坦・定数の信号では周波数を返さない
    return float(freqs[int(np.nanargmax(m)) + 1])


def find_spectral_peaks(t, y, n=5, prominence_frac=0.02):
    """FFT スペクトルの主要ピーク（基本波・高調波など）を上位 n 個返す。

    Returns: list of dict {rank, frequency, amplitude}
    """
    freqs, amp = fft_spectrum(t, y)
    if freqs is None:
        return []
    peaks = find_signal_peaks(amp[1:], t=freqs[1:], n=n,
                              prominence_frac=prominence_frac, mode="max")
    out = []
    for p in peaks:
        out.append({
            "rank": p["rank"],
            "frequency": p["time"],     # find_signal_peaks の time に freqs を入れた
            "amplitude": p["value"],
        })
    return out


def spectrum_metrics(t, y, n_harm=6, window="hann", half_bins=3):
    """THD / SNR / SINAD / ENOB / SFDR と基本波周波数を返す。

    各成分はリーク対策として基本波・各高調波バンドのパワーを近傍ビンで合算する。
    """
    t = np.asarray(t, dtype=float)
    y = np.asarray(y, dtype=float)
    n = y.size
    if n < 16:
        return {}
    fs = sampling_rate(t)
    if not fs:
        return {}
    w = _window(window, n)
    yw = (y - np.mean(y)) * w
    spec = np.fft.rfft(yw)
    power = (np.abs(spec) ** 2)
    if power.size < 4 or not np.isfinite(power).any():
        return {}

    k0 = int(np.argmax(power[1:]) + 1)  # 基本波ビン（DC除く）
    f0 = k0 * fs / n

    def band(kc):
        a = max(1, kc - half_bins)
        b = min(power.size, kc + half_bins + 1)
        return a, b

    fa, fb = band(k0)
    p_fund = float(power[fa:fb].sum())
    if p_fund <= 0:
        return {}

    # 高調波バンドが基本波や他の高調波と重なる場合（k0 が小さい＝短時間捕捉で起こる）、
    # 同じビンを二重計上すると harm_power が過大になり noise_only が負→クランプされて
    # SNR が物理的にあり得ない巨大値になる。既取得ビンを除外して重複なく合算する。
    claimed = set(range(fa, fb))
    harm_power = 0.0
    for h in range(2, n_harm + 1):
        kc = int(round(k0 * h))
        if kc >= power.size - 1:
            break
        a, b = band(kc)
        bins = sorted(set(range(a, b)) - claimed)
        claimed |= set(range(a, b))
        if bins:
            harm_power += float(power[bins].sum())

    total = float(power[1:].sum())  # DC 除く全パワー
    noise_only = max(total - p_fund - harm_power, 1e-30)
    nd = max(total - p_fund, 1e-30)  # ノイズ＋歪み

    thd = float(np.sqrt(harm_power / p_fund) * 100.0)         # %
    thd_db = float(10 * np.log10(harm_power / p_fund)) if harm_power > 0 else None
    snr = float(10 * np.log10(p_fund / noise_only))
    sinad = float(10 * np.log10(p_fund / nd))
    enob = float((sinad - 1.76) / 6.02)

    spur = power.copy()
    spur[0] = 0
    spur[fa:fb] = 0
    sfdr = float(10 * np.log10(p_fund / spur.max())) if spur.max() > 0 else None

    return {"f0": f0, "THD_pct": thd, "THD_dB": thd_db, "SNR_dB": snr,
            "SINAD_dB": sinad, "ENOB_bits": enob, "SFDR_dB": sfdr}


def spectrogram(t, y, nperseg=256, window="hann"):
    """STFT のスペクトログラム (f, time, Sxx[dB]) を返す。scipy 使用。"""
    fs = sampling_rate(t)
    if not fs:
        return None, None, None
    try:
        from scipy.signal import spectrogram as _spec
    except Exception:
        return None, None, None
    y = np.asarray(y, dtype=float)
    y = np.nan_to_num(y - np.nanmean(y))
    nperseg = int(min(nperseg, len(y)))
    if nperseg < 16:
        return None, None, None
    f, tt, Sxx = _spec(y, fs=fs, window=window, nperseg=nperseg,
                       noverlap=nperseg // 2, scaling="spectrum")
    Sxx_db = 10.0 * np.log10(Sxx + 1e-20)
    return f, tt + (t[0] if len(t) else 0.0), Sxx_db


def channel_power(t, y, f_lo=None, f_hi=None, window="hann"):
    """指定帯域 [f_lo, f_hi] の電力（振幅²の総和）。帯域未指定なら全帯域（DC除く）。"""
    freqs, amp = fft_spectrum(t, y, window=window)
    if freqs is None:
        return None
    p = np.asarray(amp, dtype=float) ** 2
    lo = freqs[1] if f_lo is None else f_lo   # DC を除く
    hi = freqs[-1] if f_hi is None else f_hi
    band = (freqs >= lo) & (freqs <= hi)
    return float(p[band].sum())


def occupied_bandwidth(t, y, frac=0.99, window="hann"):
    """全電力の frac（既定99%）が収まる占有帯域幅[Hz]。DC は除く。"""
    freqs, amp = fft_spectrum(t, y, window=window)
    if freqs is None or freqs.size < 3:
        return None
    p = np.asarray(amp, dtype=float) ** 2
    p[0] = 0.0                                 # DC 除外
    tot = p.sum()
    if tot <= 0:
        return None
    c = np.cumsum(p) / tot
    lo_i = int(np.searchsorted(c, (1.0 - frac) / 2.0))
    hi_i = int(np.searchsorted(c, 1.0 - (1.0 - frac) / 2.0))
    hi_i = min(hi_i, freqs.size - 1)
    return float(freqs[hi_i] - freqs[lo_i])


def harmonic_search(t, y, n_harm=5, window="hann"):
    """基本波と高調波（基本波の整数倍に最も近いビン）の周波数・振幅を返す。

    Returns: list of dict {harmonic, frequency, amplitude}
    """
    freqs, amp = fft_spectrum(t, y, window=window)
    if freqs is None or freqs.size < 3:
        return []
    k0 = int(np.argmax(amp[1:]) + 1)           # 基本波ビン（DC除く）
    f0 = float(freqs[k0])
    if f0 <= 0:
        return []
    # 平坦/全ゼロ/定数信号では基本波が存在しない。dominant_frequency と同様にガードし、
    # 振幅ゼロの偽の高調波を並べない（compute_fft_metrics の表に矛盾行が出るのを防ぐ）。
    if not np.isfinite(amp[k0]) or amp[k0] <= 0:
        return []
    out = []
    for h in range(1, n_harm + 1):
        k = int(np.argmin(np.abs(freqs - f0 * h)))
        out.append({"harmonic": h, "frequency": float(freqs[k]),
                    "amplitude": float(amp[k])})
    return out
```
