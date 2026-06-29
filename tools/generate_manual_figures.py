# -*- coding: utf-8 -*-
"""説明書用：各グラフ種別・各機能の「入力データ例」と「出力グラフ例」を生成する。
画像は 説明書_図/ に保存し、各例の入力データ先頭行を Markdown 表として標準出力に出す
（説明書に正確な値を載せるため）。"""
import os
import sys
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(HERE, "説明書_図")
os.makedirs(OUT, exist_ok=True)
sys.path.insert(0, HERE)
import plotter, jp_font
jp_font.setup_japanese_font()

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def md_table(df, n=4):
    h = df.head(n)
    cols = list(h.columns)
    lines = ["| " + " | ".join(str(c) for c in cols) + " |",
             "|" + "|".join(["---"] * len(cols)) + "|"]
    for _, row in h.iterrows():
        cells = []
        for v in row:
            if isinstance(v, float):
                cells.append(f"{v:.3g}")
            else:
                cells.append(str(v))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def save(fig, name):
    fig.tight_layout()
    p = os.path.join(OUT, name)
    fig.savefig(p, dpi=100)
    plt.close(fig)
    return p


def fresh(w=5.4, h=3.3):
    return plt.subplots(figsize=(w, h))


examples = []   # (見出し, ファイル名, 入力df, 説明)

# ---- 8グラフ種別 ----
rng = np.random.default_rng(7)

# 折れ線
df = pd.DataFrame({"月": list(range(1, 13)),
                   "東京": [5, 6, 9, 14, 19, 22, 26, 27, 23, 18, 12, 7],
                   "札幌": [-4, -3, 1, 7, 13, 17, 21, 22, 17, 11, 4, -1]})
fig, ax = fresh()
plotter.plot_series(ax, [{"label": "東京", "x": df["月"], "y": df["東京"], "style": {"color": "#d62728", "marker": "o"}},
                         {"label": "札幌", "x": df["月"], "y": df["札幌"], "style": {"color": "#1f77b4", "marker": "s"}}],
                    "折れ線", title="月別平均気温", xlabel="月", ylabel="気温[℃]")
examples.append(("折れ線", "ex_line.png", df, "X軸=月、Y軸=複数都市。時系列・推移の表示に。", save(fig, "ex_line.png")))

# 棒
dfb = pd.DataFrame({"製品": ["A", "B", "C", "D"], "売上": [120, 85, 200, 150]})
fig, ax = fresh()
plotter.plot_series(ax, [{"label": "売上", "y": dfb["売上"], "style": {"color": "#2ca02c"}}],
                    "棒", categories=dfb["製品"], title="製品別売上", ylabel="売上[万円]")
examples.append(("棒", "ex_bar.png", dfb, "X軸=カテゴリ、Y軸=値。大小比較に。", save(fig, "ex_bar.png")))

# 横棒
fig, ax = fresh()
plotter.plot_series(ax, [{"label": "売上", "y": dfb["売上"], "style": {"color": "#ff7f0e"}}],
                    "横棒", categories=dfb["製品"], title="製品別売上（横棒）", xlabel="売上[万円]")
examples.append(("横棒", "ex_barh.png", dfb, "棒を横向きに。ラベルが長いときに。", save(fig, "ex_barh.png")))

# 積み上げ棒
dfs = pd.DataFrame({"四半期": ["Q1", "Q2", "Q3", "Q4"],
                    "国内": [60, 75, 90, 110], "海外": [40, 55, 70, 95]})
fig, ax = fresh()
plotter.plot_series(ax, [{"label": "国内", "y": dfs["国内"], "style": {"color": "#1f77b4"}},
                         {"label": "海外", "y": dfs["海外"], "style": {"color": "#ff7f0e"}}],
                    "積み上げ棒", categories=dfs["四半期"], title="四半期売上（内訳）", ylabel="売上[万円]")
examples.append(("積み上げ棒", "ex_stack.png", dfs, "複数系列を積み上げ。内訳と合計を同時に。", save(fig, "ex_stack.png")))

# 散布図
dfsc = pd.DataFrame({"身長": np.round(150 + rng.normal(0, 9, 40), 1)})
dfsc["体重"] = np.round(0.6 * (dfsc["身長"] - 150) + 48 + rng.normal(0, 3, 40), 1)
fig, ax = fresh()
plotter.plot_series(ax, [{"label": "個人", "x": dfsc["身長"], "y": dfsc["体重"],
                          "style": {"color": "#9467bd", "marker": "o", "linestyle": "None"}}],
                    "散布図", title="身長と体重", xlabel="身長[cm]", ylabel="体重[kg]")
examples.append(("散布図", "ex_scatter.png", dfsc, "X-Yの相関を点で。", save(fig, "ex_scatter.png")))

# ヒストグラム
dfh = pd.DataFrame({"点数": np.clip(np.round(rng.normal(62, 15, 200)), 0, 100)})
fig, ax = fresh()
plotter.plot_series(ax, [{"label": "点数", "y": dfh["点数"], "style": {"color": "#1f77b4"}}],
                    "ヒストグラム", bins=20, title="テスト点数の分布", xlabel="点数")
examples.append(("ヒストグラム", "ex_hist.png", dfh, "1列の分布を度数で。ビン数で粒度調整。", save(fig, "ex_hist.png")))

# 箱ひげ
dfx = pd.DataFrame({"A組": np.round(rng.normal(65, 10, 30), 1),
                    "B組": np.round(rng.normal(72, 8, 30), 1),
                    "C組": np.round(rng.normal(60, 14, 30), 1)})
fig, ax = fresh()
plotter.plot_series(ax, [{"label": c, "y": dfx[c], "style": {}} for c in dfx.columns],
                    "箱ひげ", title="クラス別点数のばらつき", ylabel="点数")
examples.append(("箱ひげ", "ex_box.png", dfx, "複数群の中央値・四分位・外れ値を比較。", save(fig, "ex_box.png")))

# 円
dfp = pd.DataFrame({"OS": ["Windows", "macOS", "Linux", "その他"], "シェア": [62, 18, 12, 8]})
fig, ax = fresh(4.6, 3.6)
plotter.plot_series(ax, [{"label": "シェア", "y": dfp["シェア"], "style": {}}],
                    "円", categories=dfp["OS"], title="OSシェア", pct=True)
examples.append(("円", "ex_pie.png", dfp, "構成比を扇形で。％表示可。", save(fig, "ex_pie.png")))

# ---- 5つの追加機能 ----
# 近似曲線
fig, ax = fresh()
plotter.plot_series(ax, [{"label": "個人", "x": dfsc["身長"], "y": dfsc["体重"],
                          "style": {"color": "#9467bd", "marker": "o", "linestyle": "None"}}],
                    "散布図", title="近似曲線（線形）＋R²", xlabel="身長[cm]", ylabel="体重[kg]",
                    trendline={"type": "線形", "show_eq": True})
examples.append(("近似曲線", "ex_trend.png", dfsc, "散布図に回帰直線と数式・R²を凡例表示。", save(fig, "ex_trend.png")))

# データラベル
fig, ax = fresh()
plotter.plot_series(ax, [{"label": "売上", "y": dfb["売上"], "style": {"color": "#2ca02c"}}],
                    "棒", categories=dfb["製品"], title="データラベル（棒に値表示）",
                    ylabel="売上[万円]", data_labels=True)
examples.append(("データラベル", "ex_label.png", dfb, "各棒・各点に値を表示。", save(fig, "ex_label.png")))

# 第2軸・複合
dfc = pd.DataFrame({"時刻": list(range(0, 24, 2)),
                    "電力": [80, 70, 95, 160, 175, 150, 130, 110, 140, 165, 120, 90],
                    "気温": [16, 15, 18, 23, 27, 28, 26, 24, 22, 20, 18, 17]})
fig, ax = fresh()
plotter.plot_series(ax, [
    {"label": "電力[kW]", "x": dfc["時刻"], "y": dfc["電力"], "kind": "bar", "style": {"color": "#9467bd"}},
    {"label": "気温[℃]", "x": dfc["時刻"], "y": dfc["気温"], "kind": "line", "axis": "secondary",
     "style": {"color": "#d62728"}},
], "折れ線", title="第2軸＋複合（棒＋線）", xlabel="時刻[h]", ylabel="電力[kW]", secondary_label="気温[℃]")
examples.append(("第2軸・複合グラフ", "ex_secondary.png", dfc, "単位の違う2値を左右の軸＋棒/線混在で1枚に。", save(fig, "ex_secondary.png")))

# エラーバー
dfe = pd.DataFrame({"温度": list(range(0, 60, 10)),
                    "抵抗": [100, 104, 109, 113, 118, 122],
                    "誤差": [2, 2.5, 3, 3.2, 3.8, 4]})
fig, ax = fresh()
plotter.plot_series(ax, [{"label": "抵抗±誤差", "x": dfe["温度"], "y": dfe["抵抗"], "yerr": dfe["誤差"],
                          "style": {"color": "#ff7f0e", "marker": "o"}}],
                    "折れ線", title="エラーバー", xlabel="温度[℃]", ylabel="抵抗[Ω]")
examples.append(("エラーバー", "ex_errorbar.png", dfe, "誤差列を指定して縦のエラーバーを表示。", save(fig, "ex_errorbar.png")))

# ---- 出力（説明書に貼る入力データ表）----
print("=== 入力データ例（先頭行）と画像 ===\n")
for title, fname, df_in, desc, path in examples:
    print(f"### {title}  ({fname})")
    print(desc)
    print(md_table(df_in))
    print(f"画像: {path}\n")
print("生成枚数:", len(examples), " 保存先:", OUT)

# ---- 説明書に挿入するギャラリーMarkdownを出力 ----
def _img(path):
    return "説明書_図/" + os.path.basename(path)

gal = ["## 図例ギャラリー（入力データ例と出力グラフ例）", "",
       "各グラフ種別・各機能について、入力データの例（先頭4行）と、それを描いた"
       "出力グラフを示します。画像は `説明書_図/` フォルダにあります。同じデータを"
       "アプリで読み込み、グラフ種別と系列を選べば同様の図を再現できます。", "",
       "### グラフ種別ごとの例", ""]
for i, (title, fname, df_in, desc, path) in enumerate(examples):
    if i == 8:
        gal += ["### 追加機能の例（Excel相当の編集）", ""]
    gal += [f"#### {title}", "", desc, "",
            "**入力データ例（先頭4行）**", "", md_table(df_in), "",
            f"![{title}の出力例]({_img(path)})", ""]
gpath = os.path.join(OUT, "_gallery.md")
with open(gpath, "w", encoding="utf-8") as f:
    f.write("\n".join(gal))
print("ギャラリーMarkdown:", gpath)
