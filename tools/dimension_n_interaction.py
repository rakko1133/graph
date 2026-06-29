# -*- coding: utf-8 -*-
"""次元 d と点数 n の相互作用：低食い違い列(QMC)の優位は「n≫2^d のとき」効くこと
を示す。固定nで d を上げると優位が消えるが、n を上げれば優位を保てる有効次元が伸びる。

指標: CD優位度 = CD_random / CD_method（>1で randomより一様）。
手法: sobol / halton（vs random 基準）。n と d を格子で掃引、各点 REPS 回平均。
discrepancy のみ使用（最近傍行列を作らないので大 n でも軽量）。
出力: サンプルデータ/DOE/次元_n依存性.png と CSV。
"""
import os
import warnings
import numpy as np
import pandas as pd
from scipy.stats import qmc

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(HERE, "サンプルデータ", "DOE")

NS = [64, 128, 256, 512, 1024, 2048, 4096]
DIMS = [2, 3, 5, 8, 12, 16, 20]
REPS = 8
RNG_BASE = 20240601


def cd(method, d, n, seed):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        if method == "random":
            x = np.random.default_rng(seed).random((n, d))
        elif method == "sobol":
            x = qmc.Sobol(d=d, scramble=True, seed=seed).random(n)
        elif method == "halton":
            x = qmc.Halton(d=d, scramble=True, seed=seed).random(n)
        return float(qmc.discrepancy(x, method="CD"))


def main():
    rows = []
    for n in NS:
        for d in DIMS:
            vals = {m: [] for m in ("random", "sobol", "halton")}
            for r in range(REPS):
                s = RNG_BASE + r * 7919 + d * 13 + n
                for m in vals:
                    vals[m].append(cd(m, d, n, s))
            cr = np.mean(vals["random"])
            rows.append(dict(n=n, dim=d,
                             sobol_adv=cr / np.mean(vals["sobol"]),
                             halton_adv=cr / np.mean(vals["halton"])))
        print(f"  n={n} 完了")
    df = pd.DataFrame(rows)
    csv = os.path.join(OUT, "次元_n依存性.csv")
    df.to_csv(csv, index=False, encoding="utf-8-sig", float_format="%.5g")
    print("生成:", csv)

    sob = df.pivot(index="n", columns="dim", values="sobol_adv")
    print("\n=== Sobol CD優位度 CD_random/CD_sobol（行=n, 列=d, >1で優位）===")
    pd.set_option("display.float_format", lambda v: f"{v:.3g}")
    print(sob.to_string())

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import sys
        sys.path.insert(0, HERE)
        import jp_font
        jp_font.setup_japanese_font()
        fig, ax = plt.subplots(1, 2, figsize=(14, 5.5))
        cmap = plt.get_cmap("viridis")
        # 左: 各nについて 優位度 vs d
        for i, n in enumerate(NS):
            s = df[df.n == n].sort_values("dim")
            ax[0].plot(s["dim"], s["sobol_adv"], marker="o", ms=4,
                       color=cmap(i / (len(NS) - 1)), label=f"n={n}")
        ax[0].axhline(1.0, color="k", ls=":", lw=1)
        ax[0].set_yscale("log")
        ax[0].set_xlabel("次元数 d"); ax[0].set_ylabel("Sobol CD優位度 (log)")
        ax[0].set_title("固定nで d↑ → 優位消滅。n↑で優位を保てる次元が伸びる")
        ax[0].grid(True, alpha=0.3); ax[0].legend(fontsize=8, ncol=2)
        # 右: ヒートマップ log2(優位度)
        Z = np.log2(sob.values)
        im = ax[1].imshow(Z, origin="lower", aspect="auto", cmap="RdBu_r",
                          vmin=-np.abs(Z).max(), vmax=np.abs(Z).max())
        ax[1].set_xticks(range(len(DIMS))); ax[1].set_xticklabels(DIMS)
        ax[1].set_yticks(range(len(NS))); ax[1].set_yticklabels(NS)
        ax[1].set_xlabel("次元数 d"); ax[1].set_ylabel("点数 n")
        ax[1].set_title("log2(Sobol優位度)  赤=QMC有利 / 白=random同等")
        # n≈2^d 目安線（d→ そのときの n=2^d がNSのどこか）
        for j, d in enumerate(DIMS):
            target = 2 ** d
            yk = [k for k, nn in enumerate(NS) if nn >= target]
            if yk:
                ax[1].plot(j, yk[0], "k*", ms=9)
        fig.colorbar(im, ax=ax[1], shrink=0.8, label="log2(優位度)")
        fig.suptitle("低食い違い列の優位は n≫2^d で効く（★ = n≥2^d の最小n）",
                     fontsize=13)
        fig.tight_layout()
        png = os.path.join(OUT, "次元_n依存性.png")
        fig.savefig(png, dpi=120)
        print("生成:", png)
    except Exception as e:
        print("図スキップ:", e)


if __name__ == "__main__":
    main()
