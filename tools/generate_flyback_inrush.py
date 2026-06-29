"""フライバックコンバータ入力段の突入電流試験を LTspice で評価する。

AC ライン → ブリッジ整流 → バルクコンデンサ の入力段で、電源投入時（最悪位相）
の突入電流を、突入電流リミッタ（NTC 等）の有無で比較し、評価グラフと CSV を出力する。
"""

import os

import numpy as np

NETLIST = """* Flyback input-stage inrush current test
V1 acA acB SINE(0 {VPK} {FREQ} 0 0 90)
Rg1 acA 0 2Meg
Rg2 acB 0 2Meg
Rin acA a {RIN}
D1 a   dcp Dbr
D2 acB dcp Dbr
D3 0   a   Dbr
D4 0   acB Dbr
Cbulk dcp 0 {CBULK} ic=0
Rload dcp 0 {RLOAD}
.model Dbr D(Is=1e-9 Rs=0.04 N=1.8 Cjo=30p BV=1000)
.tran 0 {TSTOP} 0 {MAXSTEP} uic
.backanno
.end
"""


def _run(work, rin, vpk=325.0, freq=50.0, cbulk="100u", rload=300.0,
         tstop="40m", maxstep="2u", exe=None):
    from spicelib import RawRead, SimRunner
    from spicelib.simulators.ltspice_simulator import LTspice
    if exe:
        LTspice.spice_exe = [exe]
    os.makedirs(work, exist_ok=True)
    net = NETLIST.format(VPK=vpk, FREQ=freq, RIN=rin, CBULK=cbulk,
                         RLOAD=rload, TSTOP=tstop, MAXSTEP=maxstep)
    path = os.path.join(work, f"fb_rin{rin}.net")
    with open(path, "w", encoding="utf-8") as f:
        f.write(net)
    raw_path, _ = SimRunner(output_folder=work, simulator=LTspice).run_now(path)
    raw = RawRead(raw_path)
    names = raw.get_trace_names()
    tn = next(n for n in names if n.lower() == "time")
    t = np.abs(np.asarray(raw.get_trace(tn).get_wave(0), dtype=float))
    i = np.asarray(raw.get_trace(next(n for n in names if n.lower() == "i(rin)")).get_wave(0), float)
    v = np.asarray(raw.get_trace(next(n for n in names if n.lower() == "v(dcp)")).get_wave(0), float)
    # 単調増加の時間に整える（LTspice の重複点対策）
    order = np.argsort(t)
    return t[order], np.abs(i[order]), v[order]


def main():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    import sys
    sys.path.insert(0, here)
    import jp_font
    jp_font.setup_japanese_font()

    work = os.path.join(here, "tools", "fb_work")
    print("LTspice 実行中（制限なし / NTC リミッタ）...")
    cases = [("制限なし (Rin=0.5Ω)", 0.5, "#d62728"),
             ("NTCリミッタ (Rin=15Ω)", 15.0, "#1f77b4")]
    results = []
    for label, rin, color in cases:
        t, i, v = _run(work, rin)
        results.append((label, rin, color, t, i, v))
        print(f"  {label}: ピーク突入電流 {i.max():.1f} A,  最終バルク電圧 {v[-1]:.0f} V")

    # 共通時間グリッドへ補間して CSV 化
    tg = np.linspace(0, 0.04, 20000)
    cols = {"時間[s]": tg}
    for label, rin, color, t, i, v in results:
        cols[f"突入電流_{label}[A]"] = np.interp(tg, t, i)
    cols["バルク電圧[V]"] = np.interp(tg, results[0][3], results[0][5])
    out_csv = os.path.join(here, "サンプルデータ", "フライバック突入電流.csv")
    os.makedirs(os.path.dirname(out_csv), exist_ok=True)
    data = np.column_stack([cols[k] for k in cols])
    np.savetxt(out_csv, data, delimiter=",", header=",".join(cols),
               comments="", fmt="%.6e", encoding="utf-8-sig")

    # 評価グラフ
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(9, 6.5), sharex=True)
    for label, rin, color, t, i, v in results:
        ax1.plot(t * 1e3, i, color=color, lw=1.0, label=f"{label}  ピーク {i.max():.0f} A")
        ipk = i.max(); tpk = t[np.argmax(i)] * 1e3
        ax1.annotate(f"{ipk:.0f} A", (tpk, ipk), textcoords="offset points",
                     xytext=(6, -2), color=color, fontsize=9)
    ax1.set_ylabel("入力突入電流 [A]"); ax1.legend(); ax1.grid(True, alpha=0.3)
    ax1.set_title("フライバックコンバータ 突入電流試験（最悪位相投入・230VAC/50Hz・Cbulk=100µF）")
    for label, rin, color, t, i, v in results:
        ax2.plot(t * 1e3, v, color=color, lw=1.0, label=label)
    ax2.set_xlabel("時間 [ms]"); ax2.set_ylabel("バルクコン電圧 [V]")
    ax2.legend(); ax2.grid(True, alpha=0.3)
    fig.tight_layout()
    out_png = os.path.join(here, "サンプルデータ", "フライバック突入電流_評価.png")
    fig.savefig(out_png, dpi=120)
    print(f"生成: {out_csv}")
    print(f"生成: {out_png}")


if __name__ == "__main__":
    main()
