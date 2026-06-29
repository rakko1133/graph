"""合成アナログ波形データ生成ツール（numpy）。

LTspice が無くても使える、点数を自由に増やせる波形ジェネレータ。
オシロ解析の検証用に「既知の多重ピーク構造」を持つ波形を作る。
負荷テスト用に点数を大きくできる。

使い方:
    # 既定のサンプル一式を サンプルデータ/ に生成
    python tools/generate_waveforms.py

    # 個別生成（種類・点数・サンプリング周波数・出力先を指定）
    python tools/generate_waveforms.py --type multitone --points 500000 \
        --fs 1e6 --output サンプルデータ/負荷テスト.csv
"""

import argparse
import os

import numpy as np


def time_axis(points, fs):
    """点数 points・サンプリング周波数 fs[Hz] の時間軸[s]を返す。"""
    return np.arange(points, dtype=np.float64) / float(fs)


def multitone(t, tones=((1000, 1.0), (2500, 0.5), (6000, 0.25)), noise=0.02, seed=0):
    """複数正弦波の和。FFT に複数ピーク（第1/第2ピーク）が立つ。"""
    rng = np.random.default_rng(seed)
    y = np.zeros_like(t)
    for f, a in tones:
        y += a * np.sin(2 * np.pi * f * t)
    if noise:
        y += noise * rng.standard_normal(t.size)
    return y


def damped_ring(t, f=500.0, tau=5e-3, amp=1.0, offset=0.0):
    """減衰振動（RLC ステップ応答風）。時間波形に減衰する複数ピーク。"""
    return offset + amp * np.exp(-t / tau) * np.sin(2 * np.pi * f * t)


def am_signal(t, fc=5000.0, fm=200.0, depth=0.6):
    """振幅変調（AM）。包絡線と搬送波で側帯波ピークが出る。"""
    return (1.0 + depth * np.sin(2 * np.pi * fm * t)) * np.sin(2 * np.pi * fc * t)


def chirp(t, f0=200.0, f1=8000.0):
    """線形チャープ（周波数掃引）。"""
    T = t[-1] if t[-1] > 0 else 1.0
    k = (f1 - f0) / T
    phase = 2 * np.pi * (f0 * t + 0.5 * k * t * t)
    return np.sin(phase)


def square_wave(t, f=1000.0, duty=0.5, amp=1.0, slew=0.0):
    """方形波（高調波が豊富）。slew>0 で立上り時間の測定用に少しなまらせる。"""
    phase = (f * t) % 1.0
    y = np.where(phase < duty, amp, -amp)
    if slew > 0:
        # 単純な1次ローパスで角を鈍らせる
        alpha = float(slew)
        out = np.empty_like(y)
        acc = y[0]
        for i in range(y.size):
            acc += alpha * (y[i] - acc)
            out[i] = acc
        return out
    return y


SIGNALS = {
    "multitone": lambda t: multitone(t),
    "damped": lambda t: damped_ring(t),
    "am": lambda t: am_signal(t),
    "chirp": lambda t: chirp(t),
    "square": lambda t: square_wave(t, slew=0.05),
}


def write_csv(path, time_col, columns, time_name="時間[s]", float_fmt="%.6e"):
    """時間列と {列名: 配列} を CSV に高速書き出し（numpy.savetxt）。"""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    names = list(columns.keys())
    data = np.column_stack([time_col] + [columns[n] for n in names])
    header = ",".join([time_name] + names)
    # 文字コードを utf-8-sig に固定（BOM 付き）。自動判定が一意になる。
    np.savetxt(path, data, delimiter=",", header=header, comments="",
               fmt=float_fmt, encoding="utf-8-sig")
    return path


def generate_default_set(out_dir, fs=1e6):
    """検証用・負荷テスト用のサンプル一式を生成する。"""
    made = []

    # 1) マルチトーン（FFTに複数ピーク） 50k点
    t = time_axis(50_000, fs)
    made.append(write_csv(
        os.path.join(out_dir, "波形_マルチトーン.csv"), t,
        {
            "信号A_1k+2.5k+6kHz": multitone(t, ((1000, 1.0), (2500, 0.5), (6000, 0.25))),
            "信号B_1.5k+4kHz": multitone(t, ((1500, 0.8), (4000, 0.4)), noise=0.01, seed=1),
        },
    ))

    # 2) 減衰振動（時間波形に減衰する複数ピーク） 50k点
    t = time_axis(50_000, fs)
    made.append(write_csv(
        os.path.join(out_dir, "波形_減衰振動.csv"), t,
        {
            "減衰振動_500Hz": damped_ring(t, f=500, tau=5e-3, amp=1.0),
            "減衰振動_800Hz": damped_ring(t, f=800, tau=3e-3, amp=0.7, offset=0.0),
        },
    ))

    # 3) AM・チャープ・方形波の詰め合わせ 50k点
    t = time_axis(50_000, fs)
    made.append(write_csv(
        os.path.join(out_dir, "波形_各種.csv"), t,
        {
            "AM_5kHz": am_signal(t),
            "チャープ": chirp(t),
            "方形波_1kHz": square_wave(t, f=1000, slew=0.05),
        },
    ))

    # 4) 負荷テスト用 大量データ 500k点（複数チャンネル）
    t = time_axis(500_000, fs)
    made.append(write_csv(
        os.path.join(out_dir, "波形_負荷テスト_500k.csv"), t,
        {
            "ch1": multitone(t, ((1000, 1.0), (3000, 0.5), (7500, 0.3)), noise=0.03, seed=2),
            "ch2": damped_ring(t, f=1200, tau=20e-3, amp=1.2),
            "ch3": am_signal(t, fc=8000, fm=300, depth=0.7),
            "ch4": chirp(t, f0=100, f1=20000),
        },
    ))

    return made


def main():
    p = argparse.ArgumentParser(description="合成アナログ波形データ生成")
    p.add_argument("--type", choices=sorted(SIGNALS), help="生成する波形の種類")
    p.add_argument("--points", type=int, default=50_000, help="点数")
    p.add_argument("--fs", type=float, default=1e6, help="サンプリング周波数[Hz]")
    p.add_argument("--output", help="出力CSVパス")
    p.add_argument("--out-dir", default=None, help="既定セットの出力ディレクトリ")
    args = p.parse_args()

    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out_dir = args.out_dir or os.path.join(here, "サンプルデータ")

    if args.type:
        t = time_axis(args.points, args.fs)
        y = SIGNALS[args.type](t)
        out = args.output or os.path.join(out_dir, f"波形_{args.type}_{args.points}.csv")
        write_csv(out, t, {args.type: y})
        print(f"生成: {out}  ({args.points} 点, fs={args.fs:g}Hz)")
    else:
        made = generate_default_set(out_dir, fs=args.fs)
        print("既定のサンプル一式を生成しました:")
        for m in made:
            size = os.path.getsize(m)
            print(f"  {m}  ({size/1e6:.1f} MB)")


if __name__ == "__main__":
    main()
