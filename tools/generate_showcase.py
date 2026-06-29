"""各機能の性能を確認できるサンプルデータ群を生成する。

サンプルデータ/機能デモ/ 以下に、ピーク検出・FFT/THD・ジッタ・プロトコル解読
（UART/I2C/SPI）・マスク試験・アイダイアグラムなどを実証するCSVを出力する。
"""

import os

import numpy as np

HI, LO = 3.3, 0.0


def _write(path, time, cols, time_name="時間[s]"):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    data = np.column_stack([time] + [cols[k] for k in cols])
    header = ",".join([time_name] + list(cols))
    np.savetxt(path, data, delimiter=",", header=header, comments="",
               fmt="%.6e", encoding="utf-8-sig")
    return path


def _render(segments, fs):
    """[(levels_tuple, duration), ...] を fs でサンプリングした (t, [ch...]) に展開。"""
    nch = len(segments[0][0])
    seg = [(lv, max(1, int(round(d * fs)))) for lv, d in segments]
    total = sum(n for _, n in seg)
    t = np.arange(total) / fs
    ys = [np.empty(total) for _ in range(nch)]
    pos = 0
    for lv, n in seg:
        for c in range(nch):
            ys[c][pos:pos + n] = HI if lv[c] else LO
        pos += n
    return t, ys


def gen_noisy_peaks(out, fs=1e5):
    """ガウスピーク3本＋ノイズ（ピーク検出・平滑化のデモ）。"""
    x = np.linspace(0, 1, 100_000)
    rng = np.random.default_rng(1)
    def g(c, a, w): return a * np.exp(-0.5 * ((x - c) / w) ** 2)
    y = g(0.2, 1.0, 0.012) + g(0.5, 0.6, 0.012) + g(0.8, 0.85, 0.012)
    y_clean = y.copy()
    y = y + 0.5 * np.sin(2 * np.pi * 0.6 * x) + rng.normal(0, 0.08, x.size)  # ドリフト＋ノイズ
    return _write(out, x, {"ノイズ込み信号": y, "真の信号(参考)": y_clean}, time_name="位置")


def gen_harmonics(out, fs=1e6):
    """基本波＋既知高調波（THD≈5.4%）。FFT/THD/SNRのデモ。"""
    t = np.arange(0, 0.05, 1 / fs)
    sig = (np.sin(2 * np.pi * 1000 * t)
           + 0.05 * np.sin(2 * np.pi * 2000 * t)
           + 0.02 * np.sin(2 * np.pi * 3000 * t)
           + np.random.default_rng(2).normal(0, 0.002, t.size))
    return _write(out, t, {"歪み信号_1kHz基本波": sig})


def gen_jitter_clock(out, f=1e6, N=400, fs=2e8):
    """ジッタ入りクロック（TIE/RMS/ppジッタのデモ）。RMSジッタ約3ns。"""
    rng = np.random.default_rng(3)
    edges = np.sort(np.arange(N) / f + rng.normal(0, 3e-9, N))
    T = N / f
    t = np.arange(0, T, 1 / fs)
    sig = (np.searchsorted(edges, t, side="right") % 2).astype(float) * HI
    return _write(out, t, {"クロック(ジッタ3ns)": sig})


def gen_uart(out, text="Hello, scope!", baud=115200, fs=2e6, bits=8):
    bt = 1 / baud
    seg = [((1,), 5 * bt)]
    for ch in text.encode("ascii", "replace"):
        seg.append(((0,), bt))                      # start
        for k in range(bits):                        # LSB first
            seg.append((((ch >> k) & 1,), bt))
        seg.append(((1,), bt))                       # stop
    seg.append(((1,), 5 * bt))
    t, (y,) = _render(seg, fs)
    return _write(out, t, {"UART_TX": y})


def gen_i2c(out, addr=0x50, data=(0xA5, 0x3C), baud=1e5, fs=4e6):
    Tb = 1 / baud; h = Tb / 2
    seg = [((1, 1), 5 * Tb), ((1, 1), h), ((1, 0), h)]   # idle + START
    def clk(bl):
        s = []
        for b in bl:
            s += [((0, b), h), ((1, b), h)]
        return s
    seg += clk([(((addr << 1) >> k) & 1) for k in range(7, -1, -1)] + [0])
    for d in data:
        seg += clk([((d >> k) & 1) for k in range(7, -1, -1)] + [0])
    seg += [((0, 0), h), ((1, 0), h), ((1, 1), h), ((1, 1), 5 * Tb)]  # STOP
    t, (scl, sda) = _render(seg, fs)
    return _write(out, t, {"SCL": scl, "SDA": sda})


def gen_spi(out, data=(0x3C, 0xF0, 0xAA), baud=1e6, fs=8e6, bits=8):
    Tb = 1 / baud; h = Tb / 2
    seg = [((0, 0, 1), 3 * Tb), ((0, 0, 0), Tb)]
    for d in data:
        for k in range(bits - 1, -1, -1):
            b = (d >> k) & 1
            seg += [((0, b, 0), h), ((1, b, 0), h)]
        seg.append(((0, 0, 0), h))
    seg += [((0, 0, 1), 3 * Tb)]
    t, (sck, mosi, cs) = _render(seg, fs)
    return _write(out, t, {"SCK": sck, "MOSI": mosi, "CS": cs})


def gen_mask_fail(out, fs=1e5):
    """ところどころ±0.8を超えるグリッチを含む信号（マスク試験のデモ）。"""
    t = np.arange(0, 0.02, 1 / fs)
    rng = np.random.default_rng(4)
    y = 0.6 * np.sin(2 * np.pi * 200 * t) + rng.normal(0, 0.03, t.size)
    for c in (0.004, 0.011, 0.017):                 # 3か所にスパイク
        y += 0.6 * np.exp(-0.5 * ((t - c) / 5e-5) ** 2)
    return _write(out, t, {"被測定信号": y})


def gen_eye_nrz(out, baud=1e6, n_bits=400, fs=2e7):
    """帯域制限＋ノイズの NRZ ランダムデータ（アイダイアグラムのデモ）。"""
    rng = np.random.default_rng(5)
    bits = rng.integers(0, 2, n_bits)
    spb = int(fs / baud)
    raw = np.repeat(bits * 2.0 - 1.0, spb)           # ±1 NRZ
    # 1次ローパスで帯域制限（ISIを作る）＋ノイズ
    alpha = 0.25
    filt = np.empty_like(raw); acc = raw[0]
    for i in range(raw.size):
        acc += alpha * (raw[i] - acc); filt[i] = acc
    filt = filt + rng.normal(0, 0.08, filt.size)
    t = np.arange(filt.size) / fs
    return _write(out, t, {"NRZ_1Mbps": filt})


def main():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out_dir = os.path.join(here, "サンプルデータ", "機能デモ")
    made = [
        ("ピーク検出/平滑化", gen_noisy_peaks(os.path.join(out_dir, "ピーク_ノイズ込み.csv"))),
        ("FFT/THD/SNR", gen_harmonics(os.path.join(out_dir, "FFT_高調波THD.csv"))),
        ("ジッタ(TIE)", gen_jitter_clock(os.path.join(out_dir, "ジッタ_クロック.csv"))),
        ("UART解読", gen_uart(os.path.join(out_dir, "プロトコル_UART.csv"))),
        ("I2C解読", gen_i2c(os.path.join(out_dir, "プロトコル_I2C.csv"))),
        ("SPI解読", gen_spi(os.path.join(out_dir, "プロトコル_SPI.csv"))),
        ("マスク試験", gen_mask_fail(os.path.join(out_dir, "マスク_グリッチ.csv"))),
        ("アイダイアグラム", gen_eye_nrz(os.path.join(out_dir, "アイ_NRZ.csv"))),
    ]
    print("機能デモ用サンプルを生成しました:")
    for feature, path in made:
        print(f"  [{feature:16s}] {os.path.basename(path)}  ({os.path.getsize(path)/1e3:.0f} KB)")


if __name__ == "__main__":
    main()
