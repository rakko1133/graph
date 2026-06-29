# -*- coding: utf-8 -*-
"""オシロ測定の概念図を生成して オシロ機能_図/ に保存する（レポート図解用）。"""
import os, sys
sys.path.insert(0, r"C:\Users\motto\OneDrive\デスクトップ\グラフ")
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import jp_font; jp_font.setup_japanese_font()

OUT = r"C:\Users\motto\OneDrive\デスクトップ\グラフ\オシロ機能_図"
os.makedirs(OUT, exist_ok=True)
BLUE, RED, GRAY, GREEN = "#1f77b4", "#d62728", "#888888", "#2ca02c"


def save(fig, name):
    fig.savefig(os.path.join(OUT, name), dpi=110, bbox_inches="tight")
    plt.close(fig)


# 1) 振幅レベル（Top/Base/振幅/Max/Min/オーバーシュート/プリシュート/アンダーシュート）
def fig_levels():
    t = np.linspace(0, 10, 2000)
    base, top = 0.0, 1.0
    y = np.full_like(t, base)
    rise = (t >= 2) & (t < 2.4)
    y[rise] = base + (top - base) * (t[rise] - 2) / 0.4
    hi = t >= 2.4
    ring = 0.18 * np.exp(-(t - 2.4) / 0.7) * np.cos(2 * np.pi * 2.0 * (t - 2.4))
    y[hi] = top + ring[hi]
    pre = (t >= 1.6) & (t < 2)
    y[pre] = base - 0.12 * np.exp(-(2 - t[pre]) / 0.2)
    fall = t >= 7
    y[fall] = base - 0.16 * np.exp(-(t[fall] - 7) / 0.7) * np.cos(2 * np.pi * 2 * (t[fall] - 7))
    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    ax.plot(t, y, color=BLUE, lw=1.8)
    for lv, lab, c in [(top, "Top（上位レベル）", RED), (base, "Base（下位レベル）", GREEN),
                       (top + 0.18, "Max", GRAY), (base - 0.16, "Min", GRAY),
                       (base + 0.1 * (top - base), "10%", "#bbb"),
                       (base + 0.5 * (top - base), "50%", "#bbb"),
                       (base + 0.9 * (top - base), "90%", "#bbb")]:
        ax.axhline(lv, color=c, ls="--", lw=1)
        ax.text(10.05, lv, lab, va="center", fontsize=9, color=c)
    ax.annotate("", xy=(0.6, top), xytext=(0.6, base),
                arrowprops=dict(arrowstyle="<->", color="black"))
    ax.text(0.75, 0.5, "振幅\n=Top−Base", fontsize=9)
    ax.annotate("オーバーシュート\n(Max−Top)", xy=(2.5, top + 0.18), xytext=(3.2, 1.35),
                fontsize=9, color=RED, arrowprops=dict(arrowstyle="->", color=RED))
    ax.annotate("プリシュート", xy=(1.8, base - 0.1), xytext=(0.2, -0.45),
                fontsize=9, color="#a0522d", arrowprops=dict(arrowstyle="->", color="#a0522d"))
    ax.annotate("アンダーシュート", xy=(7.3, base - 0.14), xytext=(7.8, -0.5),
                fontsize=9, color="#a0522d", arrowprops=dict(arrowstyle="->", color="#a0522d"))
    ax.set_title("振幅系の測定：Top / Base / 振幅 / オーバーシュート 等")
    ax.set_xlabel("時間"); ax.set_ylabel("電圧"); ax.set_xlim(0, 11.8); ax.set_ylim(-0.7, 1.6)
    ax.set_yticks([]); ax.set_xticks([])
    save(fig, "01_levels.png")


# 2) 時間系（立上り/立下り・周期・±幅・デューティ）
def fig_timing():
    t = np.linspace(0, 12, 3000)
    y = (np.sign(np.sin(2 * np.pi * t / 4 - 0.3)) + 1) / 2
    # なまし（エッジに傾き）
    from scipy.ndimage import uniform_filter1d
    y = uniform_filter1d(y, 40)
    fig, ax = plt.subplots(figsize=(7.2, 3.6))
    ax.plot(t, y, color=BLUE, lw=1.8)
    ax.axhline(0.1, color="#ccc", ls="--", lw=0.8); ax.axhline(0.9, color="#ccc", ls="--", lw=0.8)
    ax.text(12.1, 0.1, "10%", fontsize=8, color="#999"); ax.text(12.1, 0.9, "90%", fontsize=8, color="#999")
    # 周期 T
    ax.annotate("", xy=(4.7, 1.15), xytext=(0.7, 1.15), arrowprops=dict(arrowstyle="<->", color="black"))
    ax.text(2.3, 1.2, "周期 T", fontsize=9, ha="center")
    # +幅, -幅
    ax.annotate("", xy=(2.7, 0.55), xytext=(0.9, 0.55), arrowprops=dict(arrowstyle="<->", color=RED))
    ax.text(1.8, 0.62, "+幅", color=RED, fontsize=9, ha="center")
    ax.annotate("", xy=(4.7, 0.45), xytext=(2.7, 0.45), arrowprops=dict(arrowstyle="<->", color=GREEN))
    ax.text(3.7, 0.3, "−幅", color=GREEN, fontsize=9, ha="center")
    ax.text(6.2, 1.2, "デューティ = +幅 / T ×100[%]", fontsize=9)
    ax.annotate("立上り時間\n(10→90%)", xy=(1.1, 0.5), xytext=(0.0, -0.35), fontsize=8,
                arrowprops=dict(arrowstyle="->"))
    ax.set_title("時間系の測定：周期・パルス幅・デューティ・立上り/立下り時間")
    ax.set_xlabel("時間"); ax.set_xlim(0, 13.2); ax.set_ylim(-0.5, 1.4)
    ax.set_yticks([]); ax.set_xticks([])
    save(fig, "02_timing.png")


# 3) FFTのTHD/SNR/SINAD/ENOB/SFDR
def fig_fft():
    f = np.linspace(0, 1000, 2000)
    floor = -90 + 3 * np.random.default_rng(0).standard_normal(f.size)
    spec = floor.copy()
    def peak(fc, amp, w=4):
        return amp * np.exp(-((f - fc) ** 2) / (2 * w ** 2))
    lin = np.maximum(10 ** (floor / 20), 0)
    sig = peak(100, 1.0) + peak(200, 0.05) + peak(300, 0.03) + peak(550, 0.02) + lin
    spec = 20 * np.log10(np.maximum(sig, 1e-6))
    fig, ax = plt.subplots(figsize=(7.2, 4.0))
    ax.plot(f, spec, color=BLUE, lw=1.0)
    ax.annotate("基本波\n(fundamental)", xy=(100, 0), xytext=(110, 5), fontsize=9, color=RED,
                arrowprops=dict(arrowstyle="->", color=RED))
    ax.annotate("高調波 2f,3f…\n(歪み)", xy=(200, -26), xytext=(230, -10), fontsize=9, color="#a0522d",
                arrowprops=dict(arrowstyle="->", color="#a0522d"))
    ax.annotate("最大スプリアス\n→ SFDR", xy=(550, -34), xytext=(600, -18), fontsize=9, color=GREEN,
                arrowprops=dict(arrowstyle="->", color=GREEN))
    ax.axhline(-90, color="#ccc", ls="--", lw=0.8)
    ax.text(700, -86, "ノイズフロア（雑音）", fontsize=9, color="#999")
    ax.text(360, -52,
            "THD = √(Σ高調波電力 / 基本波電力)\n"
            "SNR = 基本波 / 雑音（高調波除く）\n"
            "SINAD = 基本波 / (雑音+歪み)\n"
            "ENOB = (SINAD−1.76)/6.02 [bit]\n"
            "SFDR = 基本波 / 最大スプリアス",
            fontsize=8.5,
            bbox=dict(facecolor="#f5f5f5", edgecolor="#ccc"))
    ax.set_title("FFTスペクトルの品質指標：THD / SNR / SINAD / ENOB / SFDR")
    ax.set_xlabel("周波数 [Hz]"); ax.set_ylabel("振幅 [dB]"); ax.set_ylim(-100, 12)
    save(fig, "03_fft_metrics.png")


# 4) アイダイアグラム + 構造化アイ測定
def fig_eye():
    rng = np.random.default_rng(3)
    ui = 1.0; n = 200; sps = 60
    bits = rng.integers(0, 2, n)
    fig, ax = plt.subplots(figsize=(6.6, 4.0))
    tt = np.linspace(0, 2 * ui, 2 * sps)
    for i in range(1, n - 2):
        seg = []
        for k in (i, i + 1):
            a, b = bits[k - 1], bits[k]
            x = np.linspace(0, 1, sps)
            seg.append(a + (b - a) * (0.5 - 0.5 * np.cos(np.pi * x)))
        y = np.concatenate(seg) + 0.03 * rng.standard_normal(2 * sps)
        jit = 0.04 * rng.standard_normal()
        ax.plot(tt + jit, y, color=BLUE, lw=0.4, alpha=0.25)
    ax.annotate("", xy=(1.0, 0.18), xytext=(1.0, 0.82),
                arrowprops=dict(arrowstyle="<->", color=RED))
    ax.text(1.04, 0.5, "アイ高さ\n(eye height)", color=RED, fontsize=9)
    ax.annotate("", xy=(0.7, 0.5), xytext=(1.3, 0.5),
                arrowprops=dict(arrowstyle="<->", color=GREEN))
    ax.text(0.72, 0.56, "アイ幅 (eye width)", color=GREEN, fontsize=9)
    ax.text(0.05, 0.92, "レベル1", fontsize=8, color="#555")
    ax.text(0.05, 0.06, "レベル0", fontsize=8, color="#555")
    ax.text(1.35, 0.05,
            "他に：Q factor, 消光比(ER),\nジッタ(pp/RMS), DCD 等",
            fontsize=8, bbox=dict(facecolor="#f5f5f5", edgecolor="#ccc"))
    ax.set_title("アイダイアグラムと構造化アイ測定")
    ax.set_xlabel("時間（UIで正規化）"); ax.set_ylabel("電圧"); ax.set_yticks([])
    save(fig, "04_eye.png")


# 5) ジッタ TIE
def fig_jitter():
    fig, ax = plt.subplots(figsize=(7.2, 3.0))
    rng = np.random.default_rng(1)
    ideal = np.arange(1, 9)
    actual = ideal + 0.12 * rng.standard_normal(ideal.size)
    for x in ideal:
        ax.axvline(x, color="#bbb", ls="--", lw=1)
    ax.plot(actual, np.zeros_like(actual) + 0.5, "o", color=RED, ms=7)
    for xi, xa in zip(ideal, actual):
        ax.annotate("", xy=(xa, 0.5), xytext=(xi, 0.5),
                    arrowprops=dict(arrowstyle="->", color=GREEN, lw=1.5))
    ax.text(0.2, 0.85, "破線=理想エッジ（等間隔）／赤=実エッジ", fontsize=9)
    ax.text(0.2, 0.12, "TIE = 実エッジ時刻 − 理想エッジ時刻（緑の矢印）", fontsize=9, color=GREEN)
    ax.set_title("ジッタ TIE（タイムインターバルエラー）")
    ax.set_xlabel("時間"); ax.set_xlim(0, 9.5); ax.set_ylim(0, 1); ax.set_yticks([])
    save(fig, "05_jitter_tie.png")


# 6) セットアップ/ホールド時間
def fig_setup_hold():
    fig, ax = plt.subplots(figsize=(7.2, 3.4))
    t = np.linspace(0, 10, 1000)
    clk = (np.sign(np.sin(2 * np.pi * t / 5 - 1.2)) + 1) / 2 + 1.4
    ax.plot(t, clk, color=BLUE, lw=1.6); ax.text(0.1, 2.55, "CLK", color=BLUE)
    edge = 5.0
    ax.axvline(edge, color=BLUE, ls=":", lw=1)
    data = np.full_like(t, 0.0)
    data[(t > 3.3)] = 1.0
    from scipy.ndimage import uniform_filter1d
    data = uniform_filter1d(data, 30)
    ax.plot(t, data, color="#a0522d", lw=1.6); ax.text(0.1, 0.55, "DATA", color="#a0522d")
    ax.axvspan(edge - 1.4, edge, color=GREEN, alpha=0.15)
    ax.axvspan(edge, edge + 1.0, color=RED, alpha=0.15)
    ax.annotate("セットアップ\n(クロック前にデータ確定)", xy=(edge - 0.7, 1.15), xytext=(2.0, -0.5),
                fontsize=9, color=GREEN, arrowprops=dict(arrowstyle="->", color=GREEN))
    ax.annotate("ホールド\n(クロック後も保持)", xy=(edge + 0.5, 1.15), xytext=(6.2, -0.5),
                fontsize=9, color=RED, arrowprops=dict(arrowstyle="->", color=RED))
    ax.text(edge + 0.1, 2.7, "クロックエッジ", fontsize=8, color=BLUE)
    ax.set_title("セットアップ / ホールド時間")
    ax.set_xlabel("時間"); ax.set_ylim(-0.8, 2.9); ax.set_yticks([]); ax.set_xticks([])
    save(fig, "06_setup_hold.png")


# 7) スルーレート
def fig_slew():
    fig, ax = plt.subplots(figsize=(6.0, 3.4))
    t = np.linspace(0, 4, 1000)
    y = np.clip((t - 1.2) / 1.0, 0, 1)
    ax.plot(t, y, color=BLUE, lw=2)
    ax.plot([1.4, 2.0], [0.2, 0.2], color=GRAY, lw=1)
    ax.plot([2.0, 2.0], [0.2, 0.8], color=GRAY, lw=1)
    ax.annotate("Δt", xy=(1.7, 0.13), fontsize=10)
    ax.annotate("ΔV", xy=(2.05, 0.5), fontsize=10)
    ax.text(0.3, 0.8, "スルーレート = ΔV / Δt\n（エッジの傾き）", fontsize=10,
            bbox=dict(facecolor="#f5f5f5", edgecolor="#ccc"))
    ax.set_title("スルーレート（立上りの速さ）")
    ax.set_xlabel("時間"); ax.set_ylabel("電圧"); ax.set_yticks([]); ax.set_xticks([])
    save(fig, "07_slew_rate.png")


# 8) ヒストグラム由来の Top/Base
def fig_hist():
    rng = np.random.default_rng(2)
    y = np.concatenate([rng.normal(0.05, 0.03, 4000), rng.normal(1.0, 0.03, 4000),
                        rng.uniform(0, 1, 800)])
    fig, ax = plt.subplots(figsize=(6.4, 3.6))
    ax.hist(y, bins=80, color=BLUE, alpha=0.8, orientation="horizontal")
    ax.axhline(1.0, color=RED, ls="--"); ax.text(ax.get_xlim()[1]*0.5, 1.03, "Top＝上側の最頻値", color=RED, fontsize=9)
    ax.axhline(0.05, color=GREEN, ls="--"); ax.text(ax.get_xlim()[1]*0.5, 0.12, "Base＝下側の最頻値", color=GREEN, fontsize=9)
    ax.set_title("ヒストグラム法による Top / Base")
    ax.set_xlabel("出現回数"); ax.set_ylabel("電圧")
    save(fig, "08_histogram_topbase.png")


def fig_mask():
    import matplotlib.patches as mp
    t = np.linspace(0, 10, 2000)
    y = 0.5 + 0.45 * np.sin(2 * np.pi * t / 3.3)
    y += 0.5 * np.exp(-((t - 5.0) ** 2) / 0.05)
    fig, ax = plt.subplots(figsize=(7.0, 3.8))
    mask = mp.Polygon([(3.5, 0.78), (6.5, 0.78), (6.5, 1.3), (3.5, 1.3)], closed=True,
                      facecolor=RED, alpha=0.13, edgecolor=RED, lw=1.5, hatch="//")
    ax.add_patch(mask)
    ax.plot(t, y, color=BLUE, lw=1.5)
    inmask = (y > 0.78) & (t > 3.5) & (t < 6.5)
    ax.plot(t[inmask], y[inmask], ".", color=RED, ms=4)
    ax.text(5.0, 1.34, "マスク（禁止領域）", color=RED, ha="center", fontsize=9)
    ax.annotate("マスク違反点", xy=(5.0, 1.0), xytext=(7.2, 1.2), color=RED, fontsize=9,
                arrowprops=dict(arrowstyle="->", color=RED))
    ax.set_title("マスク試験（波形が禁止領域に入ると不合格）")
    ax.set_xlabel("時間"); ax.set_ylabel("電圧"); ax.set_yticks([]); ax.set_xticks([]); ax.set_ylim(0, 1.5)
    save(fig, "09_mask.png")


def fig_spectrum_power():
    f = np.linspace(0, 100, 2000)
    rng = np.random.default_rng(5)
    band = np.exp(-((f - 50) ** 2) / (2 * 8 ** 2))
    spec = band + 0.01 + 0.004 * np.abs(rng.standard_normal(f.size))
    fig, ax = plt.subplots(figsize=(7.0, 3.8))
    ax.plot(f, spec, color=BLUE, lw=1.0)
    ax.fill_between(f, 0, spec, where=(f >= 36) & (f <= 64), color=GREEN, alpha=0.2)
    ax.annotate("", xy=(64, 0.62), xytext=(36, 0.62), arrowprops=dict(arrowstyle="<->", color=RED))
    ax.text(50, 0.68, "占有帯域幅\n(全電力の99%が入る幅)", color=RED, ha="center", fontsize=9)
    ax.text(50, 0.2, "チャネル電力\n(帯域内の総電力)", color=GREEN, ha="center", fontsize=9)
    ax.set_title("スペクトル測定：チャネル電力 / 占有帯域幅")
    ax.set_xlabel("周波数"); ax.set_ylabel("電力"); ax.set_yticks([]); ax.set_ylim(0, 0.82)
    save(fig, "10_spectrum_power.png")


def fig_jitter_rjdj():
    rng = np.random.default_rng(6)
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(8.6, 3.4))
    tie = np.concatenate([rng.normal(-0.4, 0.12, 6000), rng.normal(0.4, 0.12, 6000)])
    a1.hist(tie, bins=60, color=BLUE, alpha=0.8)
    a1.set_title("TIEのヒストグラム → ジッタ分解")
    a1.set_xlabel("時間ズレ (TIE)"); a1.set_yticks([])
    a1.annotate("DJ：2つの山の間隔\n(確定性・境界あり)", xy=(0, 250), xytext=(-1.7, 560),
                fontsize=8.5, color=RED, arrowprops=dict(arrowstyle="->", color=RED))
    a1.annotate("RJ：山の広がり\n(ランダム・ガウス)", xy=(0.4, 250), xytext=(0.55, 560),
                fontsize=8.5, color=GREEN, arrowprops=dict(arrowstyle="->", color=GREEN))
    x = np.linspace(0, 1, 400)
    ber = 10.0 ** (-12 + 11 * (2 * np.abs(x - 0.5)) ** 4)
    a2.semilogy(x, ber, color=BLUE, lw=1.8)
    a2.set_title("bathtub 曲線 (BER vs サンプル位置)")
    a2.set_xlabel("UI内のサンプル位置"); a2.set_ylabel("BER")
    a2.annotate("開いている幅\n=タイミング余裕", xy=(0.5, 1e-11), xytext=(0.08, 1e-6),
                fontsize=8.5, arrowprops=dict(arrowstyle="->"))
    fig.tight_layout()
    save(fig, "11_jitter_rjdj.png")


def fig_cycle():
    t = np.linspace(0, 9, 2000)
    y = 0.5 + 0.4 * np.sin(2 * np.pi * t / 3)
    fig, ax = plt.subplots(figsize=(7.0, 3.2))
    ax.plot(t, y, color=BLUE, lw=1.5)
    ax.axvspan(3.0, 6.0, color=GREEN, alpha=0.15)
    ax.annotate("この1サイクルだけを対象に\n平均/RMS/面積などを計算\n（サイクル系測定）",
                xy=(4.5, 0.5), xytext=(6.2, 0.82), fontsize=9, color=GREEN,
                arrowprops=dict(arrowstyle="->", color=GREEN))
    ax.set_title("サイクル系測定（1周期だけを対象にする）")
    ax.set_xlabel("時間"); ax.set_ylabel("電圧"); ax.set_yticks([]); ax.set_xticks([])
    save(fig, "12_cycle.png")


def fig_burst():
    from scipy.ndimage import uniform_filter1d
    t = np.linspace(0, 12, 3000)
    env = uniform_filter1d(((t > 3) & (t < 8)).astype(float), 60)
    y = 0.5 + 0.42 * env * np.sin(2 * np.pi * t * 2)
    fig, ax = plt.subplots(figsize=(7.0, 3.0))
    ax.plot(t, y, color=BLUE, lw=1.0)
    ax.annotate("", xy=(8, 1.05), xytext=(3, 1.05), arrowprops=dict(arrowstyle="<->", color=RED))
    ax.text(5.5, 1.1, "バースト幅（活動が続く区間の長さ）", color=RED, ha="center", fontsize=9)
    ax.set_title("バースト幅")
    ax.set_xlabel("時間"); ax.set_ylabel("電圧"); ax.set_yticks([]); ax.set_xticks([]); ax.set_ylim(0, 1.25)
    save(fig, "13_burst.png")


for fn in [fig_levels, fig_timing, fig_fft, fig_eye, fig_jitter, fig_setup_hold, fig_slew, fig_hist,
           fig_mask, fig_spectrum_power, fig_jitter_rjdj, fig_cycle, fig_burst]:
    fn(); print("done:", fn.__name__)
print("saved to", OUT)
