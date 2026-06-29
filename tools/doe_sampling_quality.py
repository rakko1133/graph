# -*- coding: utf-8 -*-
"""DOE の 4 サンプリング手法（random/Sobol/Halton/maximin）の空間充填品質を、
実際に生成された params CSV から実測して比較する。

検証で「maximin という名前ほど空間充填が良くない（n=500・7次元では Sobol/Halton
の方が低discrepancy）」と判明したため、誇張せず実数で示すための補助図を作る。

指標:
  - 最小ペア間距離 min-distance（maximin 基準：大きいほど点が散らばる）
  - 平均最近傍距離 mean-NN
  - L2-star discrepancy（小さいほど一様＝低食い違い）
  - centered discrepancy CD（小さいほど良い）
すべて宣言レンジで [0,1]^7 に正規化してから算出。
"""
import os
import numpy as np
import pandas as pd
from scipy.spatial.distance import pdist
from scipy.stats import qmc

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOE = os.path.join(HERE, "サンプルデータ", "DOE")
METHODS = ["random", "sobol", "halton", "maximin"]

# channel_doe.py の PARAMS と一致させること
RANGES = {
    "Z0": (42.0, 58.0), "length": (0.005, 0.05), "Dk": (3.2, 4.6),
    "Df": (0.004, 0.030), "R0": (20.0, 300.0), "kL": (0.03, 0.25),
    "kC": (0.03, 0.25),
}


def unit_cube(df):
    u = np.empty(df.shape, float)
    for j, c in enumerate(df.columns):
        lo, hi = RANGES[c]
        u[:, j] = (df[c].to_numpy() - lo) / (hi - lo)
    return np.clip(u, 0.0, 1.0)


def main():
    rows = []
    designs = {}
    for m in METHODS:
        df = pd.read_csv(os.path.join(DOE, f"DOE_{m}_params.csv"),
                         encoding="utf-8-sig")
        u = unit_cube(df)
        designs[m] = u
        d = pdist(u)
        # 最近傍距離（各点の最小ペア距離）
        n = u.shape[0]
        sq = np.zeros((n, n))
        iu = np.triu_indices(n, 1)
        sq[iu] = d
        sq = sq + sq.T
        np.fill_diagonal(sq, np.inf)
        nn = sq.min(axis=1)
        rows.append(dict(
            method=m,
            n=n,
            min_dist=float(d.min()),
            mean_nn=float(nn.mean()),
            L2star=float(qmc.discrepancy(u, method="L2-star")),
            CD=float(qmc.discrepancy(u, method="CD")),
        ))
    tab = pd.DataFrame(rows).set_index("method")
    pd.set_option("display.float_format", lambda v: f"{v:.5g}")
    print("=== サンプリング品質（[0,1]^7 正規化, n=500・7次元）===")
    print(tab.to_string())
    print("\n解釈: min-distance/mean-NN は大きいほど良い（点が散らばる）。")
    print("      L2star/CD（discrepancy）は小さいほど良い（一様性が高い）。")
    # ランキング
    print("\nmin-distance 順位（大きいほど良い）:",
          " > ".join(tab["min_dist"].sort_values(ascending=False).index))
    print("CD discrepancy 順位（小さいほど良い）:",
          " > ".join(tab["CD"].sort_values().index))

    # 図
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import sys
        sys.path.insert(0, HERE)
        import jp_font
        jp_font.setup_japanese_font()
        colors = {"random": "#1f77b4", "sobol": "#ff7f0e",
                  "halton": "#2ca02c", "maximin": "#d62728"}
        c = [colors[m] for m in tab.index]
        fig, ax = plt.subplots(1, 3, figsize=(13, 4))
        ax[0].bar(tab.index, tab["min_dist"], color=c)
        ax[0].set_title("最小ペア間距離 min-distance\n（大きいほど良い・maximin基準）")
        ax[0].set_ylabel("距離 [-]")
        ax[1].bar(tab.index, tab["mean_nn"], color=c)
        ax[1].set_title("平均最近傍距離 mean-NN\n（大きいほど良い）")
        ax[2].bar(tab.index, tab["CD"], color=c)
        ax[2].set_title("centered discrepancy CD\n（小さいほど良い・一様性）")
        for a in ax:
            a.grid(True, axis="y", alpha=0.3)
        fig.suptitle("DOEサンプリング手法の空間充填品質（実測・7次元500点）",
                     fontsize=13)
        fig.tight_layout()
        png = os.path.join(DOE, "DOE_サンプリング品質.png")
        fig.savefig(png, dpi=120)
        print("\n生成:", png)
    except Exception as e:
        print("図スキップ:", e)


if __name__ == "__main__":
    main()
