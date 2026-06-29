# -*- coding: utf-8 -*-
"""次元数 d を増やしたときに、サンプリング手法の空間充填品質がどう変化するかを
定量調査する（＝次元の呪い curse of dimensionality の可視化）。

【検証後の修正版】
  - 点数 n=500（実DOEと一致。Sobolは2^9=512で平衡するため低次元の優位がやや
    過大評価される。本版はn=500で公平側に寄せ、傾向は不変）。
  - 最近傍距離の正規化を修正: 旧版の /√d は「平均ペア距離」のスケールであって
    「最近傍間隔(~n^(-1/d))」には不適切で、高次元ほど被覆が良くなるという誤読を
    招いた。本版は random 基準への比（method/random, 正規化不要）で表示する。
  - 優位度は CD だけでなく L2-star でも算出。CDでは高次元でも≧1だが、L2-star
    では高次元で1未満に反転する（QMCがrandomより悪化）＝優位は指標依存と明示。

点数 n を固定し d を 2〜50 掃引。各 (手法,d) を R 回の独立シードで平均±std。
手法: random / sobol / halton / maximin(best-of-25 LHS) / lhs(単一LHS)。
出力: サンプルデータ/DOE/ に CSV と 4枚パネル PNG。
"""
import os
import warnings
import numpy as np
import pandas as pd
from scipy.spatial.distance import pdist
from scipy.stats import qmc

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(HERE, "サンプルデータ", "DOE")

N = 500                      # 実DOEと一致（power-of-2のSobol優位水増しを避ける）
DIMS = [2, 3, 5, 7, 10, 15, 20, 30, 50]
REPS = 20
METHODS = ["random", "sobol", "halton", "maximin", "lhs"]
RNG_BASE = 20240601


def design(method, d, n, seed):
    if method == "random":
        return np.random.default_rng(seed).random((n, d))
    if method == "lhs":
        return qmc.LatinHypercube(d=d, seed=seed).random(n)
    if method == "maximin":
        best, bd = None, -1.0
        for s in range(25):
            x = qmc.LatinHypercube(d=d, seed=seed * 100 + s).random(n)
            m = pdist(x).min()
            if m > bd:
                bd, best = m, x
        return best
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")   # n!=2^m のSobol平衡警告を抑制
        if method == "sobol":
            return qmc.Sobol(d=d, scramble=True, seed=seed).random(n)
        if method == "halton":
            return qmc.Halton(d=d, scramble=True, seed=seed).random(n)
    raise ValueError(method)


def metrics(x):
    pw = pdist(x)
    n = x.shape[0]
    sq = np.zeros((n, n))
    sq[np.triu_indices(n, 1)] = pw
    sq += sq.T
    np.fill_diagonal(sq, np.inf)
    nn = sq.min(axis=1)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        cd = qmc.discrepancy(x, method="CD")
        l2 = qmc.discrepancy(x, method="L2-star")
    return dict(
        mean_nn=float(nn.mean()),                 # 生値（正規化は後で random比）
        min_dist=float(pw.min()),
        concentration=float(pw.std() / pw.mean()),  # 距離集中度 CV（正規化不要）
        CD=float(cd),
        L2star=float(l2),
    )


def main():
    rows = []
    for d in DIMS:
        for method in METHODS:
            acc = {k: [] for k in ("mean_nn", "min_dist", "concentration",
                                   "CD", "L2star")}
            for r in range(REPS):
                seed = RNG_BASE + r * 7919 + d * 13
                m = metrics(design(method, d, N, seed))
                for k in acc:
                    acc[k].append(m[k])
            row = dict(method=method, dim=d, n=N)
            for k, v in acc.items():
                row[k + "_mean"] = float(np.mean(v))
                row[k + "_std"] = float(np.std(v))
            rows.append(row)
        print(f"  dim={d} 完了")
    df = pd.DataFrame(rows)

    # random基準への比（正規化不要の優位度）
    for q in ("CD", "L2star"):
        piv = df.pivot(index="dim", columns="method", values=q + "_mean")
        adv = piv.rdiv(piv["random"], axis=0)   # random/method（>1で優秀）
        for m in METHODS:
            df.loc[df.method == m, q + "_adv"] = \
                df.loc[df.method == m, "dim"].map(adv[m])
    # 最近傍距離の random 比（method/random、>1で random より散る）
    nnp = df.pivot(index="dim", columns="method", values="mean_nn_mean")
    nnr = nnp.div(nnp["random"], axis=0)
    for m in METHODS:
        df.loc[df.method == m, "nn_ratio"] = \
            df.loc[df.method == m, "dim"].map(nnr[m])

    csv = os.path.join(OUT, "次元_サンプリング品質.csv")
    df.to_csv(csv, index=False, encoding="utf-8-sig", float_format="%.6g")
    print("生成:", csv)

    cda = df.pivot(index="dim", columns="method", values="CD_adv")
    l2a = df.pivot(index="dim", columns="method", values="L2star_adv")
    conc = df.pivot(index="dim", columns="method", values="concentration_mean")
    pd.set_option("display.float_format", lambda v: f"{v:.4g}")
    print("\n=== CD優位度 random/method（>1でrandomより一様）===")
    print(cda.to_string())
    print("\n=== L2-star優位度 random/method（高次元で<1に反転に注目）===")
    print(l2a.to_string())
    print("\n=== 距離集中度 CV（random・→0で次元の呪い）===")
    print(conc["random"].to_string())
    print("\n=== 最近傍距離 method/random 比（≒1なら手法差なし）===")
    print(df.pivot(index="dim", columns="method", values="nn_ratio").to_string())

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import sys
        sys.path.insert(0, HERE)
        import jp_font
        jp_font.setup_japanese_font()
        colors = {"random": "#1f77b4", "sobol": "#ff7f0e", "halton": "#2ca02c",
                  "maximin": "#d62728", "lhs": "#9467bd"}
        fig, ax = plt.subplots(2, 2, figsize=(14, 9))

        # (1) CD discrepancy（log）
        for m in METHODS:
            s = df[df.method == m].sort_values("dim")
            ax[0, 0].errorbar(s["dim"], s["CD_mean"], yerr=s["CD_std"],
                              marker="o", ms=4, capsize=2, color=colors[m], label=m)
        ax[0, 0].set_yscale("log")
        ax[0, 0].set_xlabel("次元数 d"); ax[0, 0].set_ylabel("CD（log）")
        ax[0, 0].set_title("centered discrepancy（小さいほど一様）")
        ax[0, 0].grid(True, alpha=0.3); ax[0, 0].legend(fontsize=9, ncol=2)

        # (2) 優位度: CD（実線）と L2-star（破線）— sobol/halton
        for m in ("sobol", "halton"):
            s = df[df.method == m].sort_values("dim")
            ax[0, 1].plot(s["dim"], s["CD_adv"], marker="o", ms=4,
                          color=colors[m], label=f"{m} CD")
            ax[0, 1].plot(s["dim"], s["L2star_adv"], marker="s", ms=4, ls="--",
                          color=colors[m], label=f"{m} L2*")
        ax[0, 1].axhline(1.0, color="k", ls=":", lw=1)
        ax[0, 1].set_yscale("log")
        ax[0, 1].set_xlabel("次元数 d")
        ax[0, 1].set_ylabel("random/method 優位度（log）")
        ax[0, 1].set_title("優位度は指標依存：CDは≧1維持／L2*は高次元で<1反転")
        ax[0, 1].grid(True, alpha=0.3); ax[0, 1].legend(fontsize=8, ncol=2)

        # (3) 最近傍距離 method/random 比（修正パネル）
        for m in METHODS:
            s = df[df.method == m].sort_values("dim")
            ax[1, 0].plot(s["dim"], s["nn_ratio"], marker="o", ms=4,
                          color=colors[m], label=m)
        ax[1, 0].axhline(1.0, color="k", ls=":", lw=1)
        ax[1, 0].set_xlabel("次元数 d")
        ax[1, 0].set_ylabel("最近傍距離 method / random")
        ax[1, 0].set_title("点の散り方は手法でほぼ不変（≒1）・高次元で完全収束")
        ax[1, 0].grid(True, alpha=0.3); ax[1, 0].legend(fontsize=9, ncol=2)

        # (4) 距離集中度 CV（次元の呪い）
        for m in METHODS:
            s = df[df.method == m].sort_values("dim")
            ax[1, 1].errorbar(s["dim"], s["concentration_mean"],
                              yerr=s["concentration_std"], marker="o", ms=4,
                              capsize=2, color=colors[m], label=m)
        ax[1, 1].set_xlabel("次元数 d")
        ax[1, 1].set_ylabel("距離CV = std/mean")
        ax[1, 1].set_title("距離集中度（→0で次元の呪い・全点ほぼ等距離）")
        ax[1, 1].grid(True, alpha=0.3)

        fig.suptitle(f"サンプリング手法の空間充填品質 vs 次元数"
                     f"（n={N}固定・各点 {REPS}回平均）", fontsize=14)
        fig.tight_layout()
        png = os.path.join(OUT, "次元_空間充填品質.png")
        fig.savefig(png, dpi=120)
        print("生成:", png)
    except Exception as e:
        print("図スキップ:", e)


if __name__ == "__main__":
    main()
