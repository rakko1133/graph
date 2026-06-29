# -*- coding: utf-8 -*-
"""次元調査の5観点を1枚にまとめた総括図（レポート冒頭用）。
既存の検証済みCSV（次元_サンプリング品質 / 次元_n依存性 / 次元_積分誤差）から作図。
出力: サンプルデータ/DOE/次元_総括5観点.png
"""
import os
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOE = os.path.join(HERE, "サンプルデータ", "DOE")

q = pd.read_csv(os.path.join(DOE, "次元_サンプリング品質.csv"), encoding="utf-8-sig")
nx = pd.read_csv(os.path.join(DOE, "次元_n依存性.csv"), encoding="utf-8-sig")
ig = pd.read_csv(os.path.join(DOE, "次元_積分誤差.csv"), encoding="utf-8-sig")

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import sys
sys.path.insert(0, HERE)
import jp_font
jp_font.setup_japanese_font()

COL = {"random": "#1f77b4", "sobol": "#ff7f0e", "halton": "#2ca02c",
       "maximin": "#d62728", "lhs": "#9467bd"}
METHODS = ["random", "sobol", "halton", "maximin", "lhs"]

fig, ax = plt.subplots(2, 3, figsize=(16, 9))

# ① CD優位度の崩壊
a = ax[0, 0]
for m in ["sobol", "halton", "maximin", "lhs"]:
    s = q[q.method == m].sort_values("dim")
    a.plot(s["dim"], s["CD_adv"], marker="o", ms=4, color=COL[m], label=m)
a.axhline(1, color="k", ls=":", lw=1)
a.set_yscale("log"); a.set_xlabel("次元数 d"); a.set_ylabel("CD優位度 random/method (log)")
a.set_title("① 一様性優位の崩壊（n=500）"); a.grid(True, alpha=0.3); a.legend(fontsize=8)

# ② 指標依存（CD vs L2-star 反転）
a = ax[0, 1]
s = q[q.method == "sobol"].sort_values("dim")
a.plot(s["dim"], s["CD_adv"], marker="o", ms=4, color="#ff7f0e", label="Sobol CD")
a.plot(s["dim"], s["L2star_adv"], marker="s", ms=4, ls="--", color="#d62728",
       label="Sobol L2-star")
a.axhline(1, color="k", ls=":", lw=1)
a.set_yscale("log"); a.set_xlabel("次元数 d"); a.set_ylabel("優位度 (log)")
a.set_title("② 指標依存：L2-starは高次元で<1反転"); a.grid(True, alpha=0.3); a.legend(fontsize=8)

# ③ 次元の呪い（距離集中CV）
a = ax[0, 2]
s = q[q.method == "random"].sort_values("dim")
a.plot(s["dim"], s["concentration_mean"], marker="o", ms=4, color="#1f77b4",
       label="実測 (random)")
a.plot(s["dim"], 0.6 / np.sqrt(s["dim"]), ls="--", color="#888", label="理論 0.6/√d")
a.set_xlabel("次元数 d"); a.set_ylabel("距離CV = std/mean")
a.set_title("③ 次元の呪い（距離集中）"); a.grid(True, alpha=0.3); a.legend(fontsize=8)

# ④ n×d 相互作用
a = ax[1, 0]
cmap = plt.get_cmap("viridis")
ns = sorted(nx["n"].unique())
for i, nn in enumerate([64, 512, 4096]):
    s = nx[nx.n == nn].sort_values("dim")
    a.plot(s["dim"], s["sobol_adv"], marker="o", ms=4,
           color=cmap(i / 2), label=f"n={nn}")
a.axhline(1, color="k", ls=":", lw=1)
a.set_yscale("log"); a.set_xlabel("次元数 d"); a.set_ylabel("Sobol CD優位度 (log)")
a.set_title("④ n×d：n≳2^d で優位を保てる"); a.grid(True, alpha=0.3); a.legend(fontsize=8)

# ⑤ 積分精度の優位
a = ax[1, 1]
for m in ["sobol", "halton", "lhs"]:
    s = ig[ig.method == m].sort_values("dim")
    a.plot(s["dim"], s["adv_geo"], marker="o", ms=4, color=COL[m], label=m)
a.axhline(1, color="k", ls=":", lw=1)
a.set_yscale("log"); a.set_xlabel("次元数 d"); a.set_ylabel("積分優位度 geomean (log)")
a.set_title("⑤ 積分精度の優位（d=25でも約6倍）"); a.grid(True, alpha=0.3); a.legend(fontsize=8)

# ⑥ まとめテキスト
a = ax[1, 2]; a.axis("off")
txt = ("【要点】\n"
       "・n固定で d↑ → QMCの一様性優位は急減し\n"
       "  d≈20でrandom同等（次元の呪い）。\n"
       "・優位は指標依存：CDは≧1だがL2-starは\n"
       "  高次元で<1に反転。\n"
       "・距離集中 CV∝1/√d → 高次元で全点が\n"
       "  ほぼ等距離（最近傍が無意味化）。\n"
       "・優位が効くのは n≳2^d。有効次元≈log₂(n)。\n"
       "・単一積分の優位は粘り強く d=25でも約6倍。\n"
       "  ただし分布の特性化はほぼ手法非依存\n"
       "  （= 7パラDOEで4手法が同一だった理由）。\n\n"
       "【指針 n～500】 d≲8: Sobol一択 /\n"
       "  10〜20: 差は縮小 / 20〜30+: 実質どれでも可")
a.text(0.0, 0.98, txt, va="top", ha="left", fontsize=10.5, family="sans-serif",
       linespacing=1.5)

fig.suptitle("次元数とサンプリング空間充填品質：総括（n=500・検証済み）", fontsize=15)
fig.tight_layout()
png = os.path.join(DOE, "次元_総括5観点.png")
fig.savefig(png, dpi=120)
print("生成:", png)
