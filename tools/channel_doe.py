"""高速伝送路の挿入損失(IL)・クロストーク(NEXT/FEXT)の DOE（周波数特性版）。

結合損失伝送線路（集中定数 RLGC ラダー）を LTspice で AC スイープ（0〜20GHz・
1001点）し、製造ばらつき相当のパラメータを random / Sobol / Halton / maximin で
各 N 個サンプリング。各サンプル＝1本の周波数特性カーブ（IL(f)/NEXT(f)/FEXT(f)）。
結果は単一値に収束せず分布する（=高速伝送のloss/xtalkは統計的）。

S21 等は 2ポート（整合源・整合負荷）として Vin=1 の振幅から抽出:
    IL=20log10(2|V(far_aggr)|), NEXT=20log10(2|V(near_vict)|), FEXT=20log10(2|V(far_vict)|)

注意: 集中定数モデルは近似。導体表皮効果(∝√f)や誘電損(∝f)の周波数依存は
代表周波数で固定しており、厳密な S パラメータは電磁界ソルバの領域。傾向と
統計ばらつきの評価用。0Hz は AC 不可のため 1Hz(≈DC) から開始する。

使い方:
    python tools/channel_doe.py            # 各手法500個
    python tools/channel_doe.py --n 4      # 動作確認
"""

import argparse
import os

import numpy as np

C_LIGHT = 2.998e8
FMAX = 20e9
NPTS = 1001
F_REP = 10e9   # 誘電損 G を評価する代表周波数（集中定数Gは周波数非依存）

PARAMS = [
    ("Z0", 42.0, 58.0),       # 特性インピーダンス [Ω]
    ("length", 0.005, 0.05),  # 配線長 [m]（20GHzで集中定数が成立する短距離域）
    ("Dk", 3.2, 4.6),         # 比誘電率
    ("Df", 0.004, 0.030),     # 誘電正接 tanδ
    ("R0", 20.0, 300.0),      # 導体損（代表周波数の表皮抵抗相当）[Ω/m]
    ("kL", 0.03, 0.25),       # 相互インダクタンス結合
    ("kC", 0.03, 0.25),       # 容量結合比
]
NAMES = [p[0] for p in PARAMS]
LO = np.array([p[1] for p in PARAMS])
HI = np.array([p[2] for p in PARAMS])


def adaptive_M(length, Dk):
    v = C_LIGHT / np.sqrt(Dk)
    seg_max = v / (np.pi * FMAX) / 3.0   # ラダーcutoffを20GHzの3倍以上に
    return int(np.clip(np.ceil(length / seg_max), 16, 80))


def netlist(Z0, length, Dk, Df, R0, kL, kC):
    M = adaptive_M(length, Dk)
    v = C_LIGHT / np.sqrt(Dk)
    Lpm, Cpm = Z0 / v, 1.0 / (Z0 * v)
    seg = length / M
    Ls, Cs, Rs = Lpm * seg, Cpm * seg, R0 * seg
    Gs = max(2 * np.pi * F_REP * Cpm * Df * seg, 1e-15)
    Cm = kC * Cs
    L = ["* coupled lossy line freq-sweep", "Vin src 0 AC 1",
         f"Rsrc src a0 {Z0}", f"Rvn v0 0 {Z0}"]
    for k in range(1, M + 1):
        L += [f"RA{k} a{k-1} ax{k} {Rs:.6g}", f"LA{k} ax{k} a{k} {Ls:.6g}",
              f"CA{k} a{k} 0 {Cs:.6g}", f"RGA{k} a{k} 0 {1/Gs:.6g}",
              f"RV{k} v{k-1} vx{k} {Rs:.6g}", f"LV{k} vx{k} v{k} {Ls:.6g}",
              f"CV{k} v{k} 0 {Cs:.6g}", f"RGV{k} v{k} 0 {1/Gs:.6g}",
              f"CM{k} a{k} v{k} {Cm:.6g}", f"K{k} LA{k} LV{k} {kL}"]
    L += [f"Rterm a{M} 0 {Z0}", f"Rvf v{M} 0 {Z0}",
          f".ac lin {NPTS} 1 {FMAX:g}", ".backanno", ".end"]  # 0Hz不可→1Hz始まり
    return "\n".join(L), M


def sample(method, n, seed=0):
    d = len(PARAMS)
    if method == "random":
        return np.random.default_rng(seed).random((n, d))
    from scipy.stats import qmc
    if method == "sobol":
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return qmc.Sobol(d=d, scramble=True, seed=seed).random(n)
    if method == "halton":
        return qmc.Halton(d=d, scramble=True, seed=seed).random(n)
    if method == "maximin":
        # 注意: LHS25候補からmin-distance最良を選ぶ簡易maximin。randomより良いが
        # n=500・7次元ではSobol/Haltonの方が空間充填は優秀（README参照）。
        from scipy.spatial.distance import pdist
        best, bestd = None, -1.0
        for s in range(25):
            samp = qmc.LatinHypercube(d=d, seed=seed + s).random(n)
            dm = pdist(samp).min()
            if dm > bestd:
                bestd, best = dm, samp
        return best
    raise ValueError(method)


def run_sweep(runner, raw_cls, work, vec):
    p = dict(zip(NAMES, vec))
    net, M = netlist(**p)
    path = os.path.join(work, "ch.net")
    with open(path, "w") as f:
        f.write(net)
    try:
        raw_path, log = runner.run_now(path)
        raw = raw_cls(raw_path)
        names = raw.get_trace_names()
        fn = next(n for n in names if n.lower() in ("frequency", "freq"))
        freq = np.abs(np.asarray(raw.get_trace(fn).get_wave(0)))

        def mag(node):
            return np.abs(np.asarray(raw.get_trace(node).get_wave(0)))
        af, vn, vf = mag(f"V(a{M})"), mag("V(v0)"), mag(f"V(v{M})")
        with np.errstate(divide="ignore"):
            il = 20 * np.log10(np.maximum(2 * af, 1e-12))
            nx = 20 * np.log10(np.maximum(2 * vn, 1e-12))
            fx = 20 * np.log10(np.maximum(2 * vf, 1e-12))
        for q in (raw_path, log, str(raw_path).replace(".raw", ".op.raw")):
            try:
                os.remove(q)
            except OSError:
                pass
        return freq, il, nx, fx
    except Exception:
        return None, None, None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=500)
    args = ap.parse_args()
    from spicelib import RawRead, SimRunner
    from spicelib.simulators.ltspice_simulator import LTspice

    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    work = os.path.join(here, "tools", "doe_work")
    os.makedirs(work, exist_ok=True)
    out_dir = os.path.join(here, "サンプルデータ", "DOE")
    os.makedirs(out_dir, exist_ok=True)
    runner = SimRunner(output_folder=work, simulator=LTspice)

    methods = ["random", "sobol", "halton", "maximin"]
    freq_axis = None
    store = {}   # method -> dict(IL/NEXT/FEXT arrays [n x 1001], params [n x 7])
    for mi, method in enumerate(methods):
        u = sample(method, args.n, seed=1000 + mi)
        X = LO + u * (HI - LO)
        IL = np.full((args.n, NPTS), np.nan)
        NX = np.full((args.n, NPTS), np.nan)
        FX = np.full((args.n, NPTS), np.nan)
        for j in range(args.n):
            f, il, nx, fx = run_sweep(runner, RawRead, work, X[j])
            if f is not None and len(f) == NPTS:
                freq_axis = f
                IL[j], NX[j], FX[j] = il, nx, fx
            if (j + 1) % 50 == 0:
                print(f"  [{method}] {j+1}/{args.n}")
        store[method] = dict(IL=IL, NX=NX, FX=FX, X=X)
        # 保存（パラメータ＋各特性カーブ：周波数 × 個数）
        np.savetxt(os.path.join(out_dir, f"DOE_{method}_params.csv"), X,
                   delimiter=",", header=",".join(NAMES), comments="",
                   fmt="%.6g", encoding="utf-8-sig")
        for q, arr in (("IL", IL), ("NEXT", NX), ("FEXT", FX)):
            head = "周波数[Hz]," + ",".join(f"sim{j:03d}" for j in range(args.n))
            data = np.column_stack([freq_axis, arr.T])
            np.savetxt(os.path.join(out_dir, f"DOE_{method}_{q}.csv"), data,
                       delimiter=",", header=head, comments="", fmt="%.5g",
                       encoding="utf-8-sig")
        k20 = int(np.argmin(np.abs(freq_axis - FMAX)))
        print(f"[{method}] {args.n}個完了  @20GHz: "
              f"IL {np.nanmean(IL[:,k20]):.1f}±{np.nanstd(IL[:,k20]):.1f}dB  "
              f"NEXT {np.nanmean(NX[:,k20]):.1f}±{np.nanstd(NX[:,k20]):.1f}dB")

    # 周波数特性のばらつき図
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import sys
        sys.path.insert(0, here)
        import jp_font
        jp_font.setup_japanese_font()
        fg = freq_axis / 1e9
        fig, axes = plt.subplots(1, 3, figsize=(15, 4.5))
        colors = {"random": "#1f77b4", "sobol": "#ff7f0e",
                  "halton": "#2ca02c", "maximin": "#d62728"}
        for ax, key, title in zip(axes, ("IL", "NX", "FX"),
                                  ("挿入損失 IL", "NEXT", "FEXT")):
            # randomの個別カーブを薄く（ばらつき＝収束しない様子）
            sub = store["random"][key]
            for j in range(0, min(60, args.n)):
                ax.plot(fg, sub[j], color="#888", lw=0.3, alpha=0.15)
            for m in methods:  # 各手法の中央値
                med = np.nanmedian(store[m][key], axis=0)
                ax.plot(fg, med, color=colors[m], lw=1.6, label=f"{m} 中央値")
            ax.set_xlabel("周波数 [GHz]"); ax.set_ylabel(f"{title} [dB]")
            ax.set_title(title); ax.grid(True, alpha=0.3); ax.set_xlim(0, 20)
        axes[0].legend(fontsize=8)
        fig.suptitle(f"高速伝送 loss/xtalk の周波数特性ばらつき"
                     f"（各手法 {args.n}個・0〜20GHz・1001点）", fontsize=13)
        fig.tight_layout()
        png = os.path.join(out_dir, "DOE_周波数特性.png")
        fig.savefig(png, dpi=120)
        print(f"生成: {png}")
    except Exception as e:
        print("図の生成スキップ:", e)


if __name__ == "__main__":
    main()
