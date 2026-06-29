# -*- coding: utf-8 -*-
"""Excel相当グラフ編集機能のデモ用サンプルCSVと、機能showcaseのPNGを生成する。"""
import os
import sys
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(HERE, "サンプルデータ")
os.makedirs(OUT, exist_ok=True)
sys.path.insert(0, HERE)
import plotter, jp_font
jp_font.setup_japanese_font()

rng = np.random.default_rng(3)
t = np.arange(0, 24, dtype=float)               # 時刻[h]
temp = 18 + 6 * np.sin((t - 8) / 24 * 2 * np.pi) + rng.normal(0, 0.8, t.size)
power = 120 + 60 * np.sin((t - 14) / 24 * 2 * np.pi) + rng.normal(0, 8, t.size)  # 別スケール
sales = np.clip(40 + 3 * t + rng.normal(0, 8, t.size), 0, None)
err = 2 + 0.3 * np.abs(rng.normal(0, 3, t.size))

df = pd.DataFrame({"時刻[h]": t, "気温[℃]": temp.round(2),
                   "電力[kW]": power.round(1), "売上[万円]": sales.round(1),
                   "売上誤差": err.round(2)})
csv = os.path.join(OUT, "Excel編集デモ.csv")
df.to_csv(csv, index=False, encoding="utf-8-sig")
print("生成:", csv)

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
fig, ax = plt.subplots(2, 3, figsize=(16, 9))

# ① 近似曲線(線形)+R²
plotter.plot_series(ax[0, 0], [{"label": "売上", "x": t, "y": sales,
                    "style": {"color": "#1f77b4", "marker": "o", "linestyle": "None"}}],
                    "散布図", title="① 近似曲線(線形)+R²", xlabel="時刻", ylabel="売上",
                    trendline={"type": "線形", "show_eq": True})
# ② 多項式近似
plotter.plot_series(ax[0, 1], [{"label": "気温", "x": t, "y": temp,
                    "style": {"color": "#2ca02c", "marker": "o", "linestyle": "None"}}],
                    "散布図", title="② 近似曲線(多項式3次)", xlabel="時刻", ylabel="気温",
                    trendline={"type": "多項式", "degree": 3, "show_eq": True})
# ③ 第2軸（気温 vs 電力）
plotter.plot_series(ax[0, 2], [
    {"label": "気温[℃]", "x": t, "y": temp, "axis": "primary", "style": {"color": "#d62728"}},
    {"label": "電力[kW]", "x": t, "y": power, "axis": "secondary", "style": {"color": "#1f77b4"}},
], "折れ線", title="③ 第2軸(左右で別スケール)", xlabel="時刻", ylabel="気温[℃]",
   secondary_label="電力[kW]")
# ④ 複合グラフ（棒+線, 第2軸）
plotter.plot_series(ax[1, 0], [
    {"label": "売上(棒)", "x": t, "y": sales, "kind": "bar", "style": {"color": "#9467bd"}},
    {"label": "気温(線/第2軸)", "x": t, "y": temp, "kind": "line", "axis": "secondary",
     "style": {"color": "#d62728"}},
], "折れ線", title="④ 複合グラフ(棒+線+第2軸)", xlabel="時刻", ylabel="売上",
   secondary_label="気温[℃]")
# ⑤ エラーバー
plotter.plot_series(ax[1, 1], [{"label": "売上±誤差", "x": t, "y": sales, "yerr": err,
                    "style": {"color": "#ff7f0e"}}],
                    "折れ線", title="⑤ エラーバー", xlabel="時刻", ylabel="売上")
# ⑥ データラベル(棒)
plotter.plot_series(ax[1, 2], [{"label": "売上", "y": sales[:8], "style": {"color": "#2ca02c"}}],
                    "棒", categories=[f"{int(h)}h" for h in t[:8]],
                    title="⑥ データラベル(棒)", data_labels=True)

fig.suptitle("Excel相当グラフ編集：近似曲線 / 第2軸 / 複合 / エラーバー / データラベル",
             fontsize=15)
fig.tight_layout()
png = os.path.join(OUT, "Excel編集機能_デモ.png")
fig.savefig(png, dpi=110)
print("生成:", png)
