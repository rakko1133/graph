# -*- coding: utf-8 -*-
"""バッチ一括出力の検証用に、パラメータを変えた波形CSVを多数（既定500個）生成する。

全ファイルとも列構成は共通（「時間[s]」「電圧[V]」）。これにより、アプリで
X=時間[s] / Y=電圧[V] を選び「ファイルごとに一括出力」すると、全ファイルへ同じ
設定が適用されて 1ファイル=1画像 で一括保存できる。

波形の種類とパラメータ（周波数・振幅・減衰・位相・オフセット・ノイズ）を変えて
グラフが1枚ずつ異なるようにする。再現性のため乱数シードは固定。
"""
import argparse
import os
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(HERE, "サンプルデータ", "バッチ検証")

KINDS = ["減衰正弦", "二トーン", "チャープ", "方形波", "三角波", "AM変調", "パルス列"]


def make_wave(kind, t, p):
    w = 2 * np.pi
    f, A, tau, ph, off = p["f"], p["A"], p["tau"], p["ph"], p["off"]
    if kind == "減衰正弦":
        v = A * np.exp(-t / tau) * np.sin(w * f * t + ph)
    elif kind == "二トーン":
        v = A * np.sin(w * f * t + ph) + 0.6 * A * np.sin(w * (f * 1.7 + 1) * t)
    elif kind == "チャープ":
        v = A * np.sin(w * (f + p["k"] * t) * t + ph)
    elif kind == "方形波":
        v = A * np.sign(np.sin(w * f * t + ph))
    elif kind == "三角波":
        v = (2 * A / np.pi) * np.arcsin(np.sin(w * f * t + ph))
    elif kind == "AM変調":
        v = (1 + 0.6 * np.sin(w * (f * 0.15 + 0.5) * t)) * A * np.sin(w * f * 4 * t)
    else:  # パルス列
        duty = 0.2 + 0.3 * (p["A"] % 1)
        v = A * ((np.sin(w * f * t + ph) > np.cos(np.pi * duty)).astype(float))
    return v + off + p["noise"] * np.random.default_rng(p["seed"]).standard_normal(len(t))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=500)
    ap.add_argument("--points", type=int, default=600)
    args = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)

    rng = np.random.default_rng(2026)
    t = np.linspace(0, 1.0, args.points)
    rows = []
    width = len(str(args.n))
    for i in range(1, args.n + 1):
        kind = KINDS[(i - 1) % len(KINDS)]
        p = dict(
            f=float(rng.uniform(2, 18)),
            A=float(rng.uniform(0.4, 2.0)),
            tau=float(rng.uniform(0.15, 1.5)),
            ph=float(rng.uniform(0, 2 * np.pi)),
            off=float(rng.uniform(-0.3, 0.3)),
            noise=float(rng.uniform(0.0, 0.06)),
            k=float(rng.uniform(3, 25)),
            seed=int(i),
        )
        v = make_wave(kind, t, p)
        df = pd.DataFrame({"時間[s]": t.round(5), "電圧[V]": v.round(4)})
        fname = f"波形_{i:0{width}d}_{kind}.csv"
        df.to_csv(os.path.join(OUT, fname), index=False, encoding="utf-8-sig")
        rows.append(dict(ファイル=fname, 種類=kind,
                         周波数Hz=round(p["f"], 2), 振幅=round(p["A"], 2),
                         減衰tau=round(p["tau"], 2), 位相=round(p["ph"], 2),
                         オフセット=round(p["off"], 2), ノイズ=round(p["noise"], 3)))
        if i % 100 == 0:
            print(f"  {i}/{args.n} 生成")

    idx = pd.DataFrame(rows)
    idx.to_csv(os.path.join(OUT, "_パラメータ一覧.csv"), index=False, encoding="utf-8-sig")
    print(f"生成完了: {args.n} 個のCSV → {OUT}")
    print(f"列構成（全ファイル共通）: 時間[s], 電圧[V]")
    print(f"パラメータ一覧: {os.path.join(OUT, '_パラメータ一覧.csv')}")


if __name__ == "__main__":
    main()
