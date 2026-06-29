"""LTspice でノイズ込みの多彩な波形パターンを生成する。

LTspice の振る舞いソース（B源）と乱数関数 white()（一様乱数, 帯域制限白色ノイズ）
を使い、実回路シミュレーションでノイズ重畳波形を作る。1/f 近似は帯域の異なる
white() の和、色付きノイズは RC で帯域制限して表現する（flicker() は本LTspice非対応）。

出力: サンプルデータ/ノイズ波形/ に各パターンの CSV。

使い方:
    python tools/generate_noisy_ltspice.py
"""

import os

import numpy as np

# (ファイル名, B源などの本体, .tran 設定, 出力ノード, 説明)
PATTERNS = [
    ("正弦_高SNR",
     "B1 out 0 V=sin(2*pi*1000*time)+0.04*white(time*300k)",
     "0 8m 0 1u", "out", "正弦1kHz＋小さな白色ノイズ（高SNR）"),
    ("正弦_低SNR_埋もれ",
     "B1 out 0 V=0.6*sin(2*pi*1000*time)+0.9*white(time*300k)",
     "0 8m 0 1u", "out", "正弦が白色ノイズに埋もれる（低SNR）"),
    ("クロック_ノイズ_ジッタ",
     "B1 out 0 V=if(sin(2*pi*1000*time+0.6*white(time*30k))>0,1.8,0)+0.06*white(time*800k)",
     "0 10m 0 0.5u", "out", "方形クロック＋位相ジッタ＋振幅ノイズ"),
    ("減衰振動_ノイズ",
     "V1 in 0 PULSE(0 1 0 1n 1n 1 2)\nR1 in n1 3\nL1 n1 cp 1m\nC1 cp 0 1u\n"
     "B1 out 0 V=V(cp)+0.03*white(time*300k)\nRo out 0 1k",
     "0 6m 0 50n", "out", "RLCリンギング＋ノイズ（実回路）"),
    ("センサ_ドリフト_スパイク",
     "B1 out 0 V=2.5+0.3*sin(2*pi*40*time)+0.05*white(time*50k)"
     "+0.6*exp(-((time-3m)/2e-4)*((time-3m)/2e-4))"
     "+0.5*exp(-((time-7m)/2e-4)*((time-7m)/2e-4))",
     "0 10m 0 2u", "out", "DCオフセット＋緩やかなドリフト＋ノイズ＋スパイク（センサ風）"),
    ("色付きノイズ_1f近似",
     "B1 out 0 V=0.30*white(time*1k+1)+0.20*white(time*10k+2)"
     "+0.12*white(time*100k+3)+0.07*white(time*1meg+4)",
     "0 10m 0 0.5u", "out", "帯域の異なる白色の和で 1/f を近似（ピンク風）"),
    ("帯域制限ノイズ_RC",
     "B1 n 0 V=white(time*2meg)\nR1 n out 1k\nC1 out 0 100n",
     "0 10m 0 0.5u", "out", "白色ノイズをRCで帯域制限した色付きノイズ（アンプ出力風）"),
    ("マルチトーン_ノイズ",
     "B1 out 0 V=sin(2*pi*1000*time)+0.5*sin(2*pi*2500*time)"
     "+0.3*sin(2*pi*6000*time)+0.12*white(time*300k)",
     "0 10m 0 1u", "out", "3トーン＋白色ノイズ（FFT/THD検証）"),
    ("AM変調_ノイズ",
     "B1 out 0 V=(1+0.6*sin(2*pi*200*time))*sin(2*pi*5000*time)+0.1*white(time*400k)",
     "0 10m 0 1u", "out", "AM変調＋ノイズ"),
    ("パルス列_ノイズ",
     "V1 p 0 PULSE(0 1 0.1m 5u 5u 0.3m 1.2m)\n"
     "B1 out 0 V=V(p)+0.06*white(time*800k)\nRo out 0 1k",
     "0 10m 0 0.5u", "out", "パルス列＋ノイズ（立上り/幅測定の検証）"),
    ("三角波_ノイズ",
     "V1 tri 0 PULSE(-1 1 0 0.5m 0.5m 1n 1m)\n"
     "B1 out 0 V=V(tri)+0.05*white(time*300k)\nRo out 0 1k",
     "0 10m 0 1u", "out", "三角波＋ノイズ"),
]


def _run(work, body, tran, node, exe=None):
    from spicelib import RawRead, SimRunner
    from spicelib.simulators.ltspice_simulator import LTspice
    if exe:
        LTspice.spice_exe = [exe]
    os.makedirs(work, exist_ok=True)
    net = (f"* noisy waveform\n{body}\n.tran {tran}\n"
           ".options plotwinsize=0\n.backanno\n.end\n")
    path = os.path.join(work, "nz.net")
    with open(path, "w") as f:
        f.write(net)
    raw_path, _ = SimRunner(output_folder=work, simulator=LTspice).run_now(path)
    if not raw_path or not os.path.exists(raw_path):
        raise RuntimeError("LTspice 実行に失敗しました。")
    raw = RawRead(raw_path)
    names = raw.get_trace_names()
    tn = next(n for n in names if n.lower() == "time")
    t = np.abs(np.asarray(raw.get_trace(tn).get_wave(0), dtype=float))
    vn = next(n for n in names if n.lower() == f"v({node})")
    y = np.asarray(raw.get_trace(vn).get_wave(0), dtype=float)
    order = np.argsort(t)
    return t[order], y[order]


def main():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    work = os.path.join(here, "tools", "noisy_work")
    out_dir = os.path.join(here, "サンプルデータ", "ノイズ波形")
    os.makedirs(out_dir, exist_ok=True)
    print("LTspice でノイズ込み波形を生成中...")
    for name, body, tran, node, desc in PATTERNS:
        try:
            t, y = _run(work, body, tran, node)
        except Exception as e:  # noqa: BLE001
            print(f"  [NG] {name}: {e}")
            continue
        # 一様時間グリッドに補間（CSVを扱いやすく）
        n = min(len(t), 20000)
        tg = np.linspace(t.min(), t.max(), n)
        yg = np.interp(tg, t, y)
        path = os.path.join(out_dir, f"{name}.csv")
        data = np.column_stack([tg, yg])
        np.savetxt(path, data, delimiter=",", header=f"時間[s],{name}",
                   comments="", fmt="%.6e", encoding="utf-8-sig")
        print(f"  [OK] {name:24s} 点数{len(tg):6d}  RMS={np.std(yg):.3f}  {desc}")
    print(f"出力先: {out_dir}")


if __name__ == "__main__":
    main()
