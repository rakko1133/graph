# -*- coding: utf-8 -*-
"""決定実験（修正版）：discrepancy の優位が実際の数値積分精度にどう伝わるかを、
次元 d を変えて測る。Koksma–Hlawka の橋渡しを実測し「d=7でCD優位なのに7パラ
DOEで4手法が統計的に同一」という謎を解く。

【検証で判明した前版の欠陥への対処】
  1. 真値を Sobol 基準にしていた → Sobol推定との相関疑い。本版は *厳密な閉形式*
     （1次元積分の積に分解できる3関数のみ採用）を使い、基準バイアスを完全排除。
  2. corner_peak/product_peak は高次元で積分値が0に潰れ、相対誤差が病的に発散。
     しかも全関数を相対誤差でRMSプールしていたため「d=20で優位1に収束」が
     これら病的関数のアーティファクトだった → 本版は well-behaved な3関数のみ、
     *絶対*RMSEの優位比を *関数別* に出し、集計は幾何平均（プールの罠を回避）。
  3. 難易度を Σa=const で固定 → 高次元で被積分が平坦化し減衰を隠蔽 → 本版は
     各座標スケール固定（総難易度は次元とともに増す＝公平）。

採用関数（[0,1]^d、すべて閉形式積分）:
  oscillatory : cos(2πw + Σ a_i x_i)
  gaussian    : exp(-Σ a_i^2 (x_i-u_i)^2)
  continuous  : exp(-Σ a_i |x_i-u_i|)
手法: random / sobol / halton / lhs。優位度 = RMSE_random / RMSE_method。
出力: サンプルデータ/DOE/次元_積分誤差.png と CSV。
"""
import os
import warnings
import numpy as np
from scipy.special import erf
from scipy.stats import qmc

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(HERE, "サンプルデータ", "DOE")

N = 500
DIMS = [2, 3, 5, 8, 12, 16, 20, 25]
INST = 30
REPS = 40
METHODS = ["random", "sobol", "halton", "lhs"]
FAMILIES = ["oscillatory", "gaussian", "continuous"]
SCALE = {"oscillatory": 1.0, "gaussian": 1.0, "continuous": 1.5}  # 各座標固定
RNG_BASE = 20240601


def feval(name, X, a, u, w):
    if name == "oscillatory":
        return np.cos(2 * np.pi * w + X @ a)
    if name == "gaussian":
        return np.exp(-((a ** 2) * (X - u) ** 2).sum(axis=1))
    if name == "continuous":
        return np.exp(-(a * np.abs(X - u)).sum(axis=1))
    raise ValueError(name)


def exact(name, a, u, w):
    """[0,1]^d 上の厳密積分（1次元積分の積）。"""
    if name == "oscillatory":
        # Re[ e^{i2πw} Π (e^{i a}-1)/(i a) ]
        z = (np.exp(1j * a) - 1.0) / (1j * a)
        return float(np.real(np.exp(1j * 2 * np.pi * w) * np.prod(z)))
    if name == "gaussian":
        t = (np.sqrt(np.pi) / (2 * a)) * (erf(a * (1 - u)) + erf(a * u))
        return float(np.prod(t))
    if name == "continuous":
        t = (1.0 / a) * (2 - np.exp(-a * u) - np.exp(-a * (1 - u)))
        return float(np.prod(t))
    raise ValueError(name)


def design(method, d, n, seed):
    if method == "random":
        return np.random.default_rng(seed).random((n, d))
    if method == "lhs":
        return qmc.LatinHypercube(d=d, seed=seed).random(n)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        if method == "sobol":
            return qmc.Sobol(d=d, scramble=True, seed=seed).random(n)
        if method == "halton":
            return qmc.Halton(d=d, scramble=True, seed=seed).random(n)
    raise ValueError(method)


def main():
    import pandas as pd
    rows = []
    for d in DIMS:
        designs = {m: [design(m, d, N, RNG_BASE + 13 * d + 7 * r)
                       for r in range(REPS)] for m in METHODS}
        # 絶対二乗誤差を (method, family) で集計
        sqerr = {(m, f): [] for m in METHODS for f in FAMILIES}
        rng = np.random.default_rng(RNG_BASE + d)
        for fam in FAMILIES:
            s = SCALE[fam]
            for _ in range(INST):
                a = rng.random(d) * s + 1e-3      # 各座標固定スケール（総難易度↑）
                u = rng.random(d)
                w = rng.random()
                truth = exact(fam, a, u, w)
                for m in METHODS:
                    for X in designs[m]:
                        est = float(feval(fam, X, a, u, w).mean())
                        sqerr[(m, fam)].append((est - truth) ** 2)
        for m in METHODS:
            row = dict(method=m, dim=d)
            for fam in FAMILIES:
                row[f"rmse_{fam}"] = float(np.sqrt(np.mean(sqerr[(m, fam)])))
            rows.append(row)
        print(f"  dim={d} 完了")

    df = pd.DataFrame(rows)
    # 関数別の優位比（絶対RMSE）→ 幾何平均で集計（プールの罠回避）
    for fam in FAMILIES:
        piv = df.pivot(index="dim", columns="method", values=f"rmse_{fam}")
        a = piv.rdiv(piv["random"], axis=0)
        for m in METHODS:
            df.loc[df.method == m, f"adv_{fam}"] = \
                df.loc[df.method == m, "dim"].map(a[m])
    advcols = [f"adv_{f}" for f in FAMILIES]
    df["adv_geo"] = np.exp(df[advcols].apply(lambda r: np.log(r).mean(), axis=1))

    csv = os.path.join(OUT, "次元_積分誤差.csv")
    df.to_csv(csv, index=False, encoding="utf-8-sig", float_format="%.6g")
    print("生成:", csv)
    pd.set_option("display.float_format", lambda v: f"{v:.4g}")
    geo = df.pivot(index="dim", columns="method", values="adv_geo")
    print("\n=== 積分精度の優位度（幾何平均, RMSE_random/RMSE_method, >1で高精度）===")
    print(geo.to_string())
    print("\n=== Sobol 関数別優位度 ===")
    print(df[df.method == "sobol"].set_index("dim")[advcols].to_string())

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import sys
        sys.path.insert(0, HERE)
        import jp_font
        jp_font.setup_japanese_font()
        colors = {"random": "#1f77b4", "sobol": "#ff7f0e",
                  "halton": "#2ca02c", "lhs": "#9467bd"}
        fig, ax = plt.subplots(1, 2, figsize=(14, 5.5))
        # 左: 各手法の幾何平均優位度 vs d
        for m in METHODS:
            sdf = df[df.method == m].sort_values("dim")
            ax[0].plot(sdf["dim"], sdf["adv_geo"], marker="o", ms=5,
                       color=colors[m], label=m)
        ax[0].axhline(1.0, color="k", ls=":", lw=1)
        ax[0].set_yscale("log")
        ax[0].set_xlabel("次元数 d")
        ax[0].set_ylabel("積分優位度（幾何平均, log）")
        ax[0].set_title(f"n={N} 数値積分のQMC優位（厳密真値・3関数幾何平均）")
        ax[0].grid(True, alpha=0.3); ax[0].legend(fontsize=10)
        # 右: Sobol 関数別
        ls = {"oscillatory": "-", "gaussian": "--", "continuous": ":"}
        for fam in FAMILIES:
            sdf = df[df.method == "sobol"].sort_values("dim")
            ax[1].plot(sdf["dim"], sdf[f"adv_{fam}"], marker="o", ms=5,
                       ls=ls[fam], color="#ff7f0e", label=f"sobol {fam}")
            sdf2 = df[df.method == "lhs"].sort_values("dim")
            ax[1].plot(sdf2["dim"], sdf2[f"adv_{fam}"], marker="s", ms=4,
                       ls=ls[fam], color="#9467bd", label=f"lhs {fam}")
        ax[1].axhline(1.0, color="k", ls=":", lw=1)
        ax[1].set_yscale("log")
        ax[1].set_xlabel("次元数 d"); ax[1].set_ylabel("優位度（log）")
        ax[1].set_title("関数別：低次元で大・高次元で減衰（病的関数を排除した実像）")
        ax[1].grid(True, alpha=0.3); ax[1].legend(fontsize=8, ncol=2)
        fig.suptitle("discrepancyの優位は数値積分精度に伝わるか vs 次元数（修正版）",
                     fontsize=14)
        fig.tight_layout()
        png = os.path.join(OUT, "次元_積分誤差.png")
        fig.savefig(png, dpi=120)
        print("生成:", png)
    except Exception as e:
        print("図スキップ:", e)


if __name__ == "__main__":
    main()
