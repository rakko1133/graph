"""LTspice 連携によるアナログ波形データ生成（spicelib）。

LTspice 本体をバッチ実行して実回路の過渡解析を行い、結果(.raw)を CSV に
書き出す。既定では直列 RLC のパルス応答（減衰リンギング＝複数ピーク）を生成する。

前提:
    - LTspice 本体がインストール済み（spicelib が自動検出）
    - pip install spicelib

使い方:
    python tools/generate_ltspice.py
    python tools/generate_ltspice.py --tstop 20m --maxstep 20n   # 点数を増やす
"""

import argparse
import os
import sys

# 直列 RLC（パルス駆動）。out が容量電圧でリンギングする。
# plotwinsize=0 で波形圧縮を無効化し、点数を多く出力する（負荷テスト向け）。
NETLIST_TEMPLATE = """* 直列RLC 減衰リンギング（spicelib 生成）
V1 N001 0 PULSE(0 1 0 1n 1n 1 2)
R1 N001 N002 {R}
L1 N002 out {L}
C1 out 0 {C}
.tran 0 {TSTOP} 0 {MAXSTEP}
.options plotwinsize=0
.backanno
.end
"""


def build_netlist(path, R="10", L="1m", C="1u", tstop="10m", maxstep="50n"):
    text = NETLIST_TEMPLATE.format(R=R, L=L, C=C, TSTOP=tstop, MAXSTEP=maxstep)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def run_and_export(out_csv, work_dir, R, L, C, tstop, maxstep, exe=None):
    from spicelib import RawRead, SimRunner
    from spicelib.simulators.ltspice_simulator import LTspice

    if exe:
        LTspice.spice_exe = [exe]
    print(f"LTspice 実行ファイル: {LTspice.spice_exe}")

    os.makedirs(work_dir, exist_ok=True)
    netlist = build_netlist(os.path.join(work_dir, "rlc.net"),
                            R=R, L=L, C=C, tstop=tstop, maxstep=maxstep)

    runner = SimRunner(output_folder=work_dir, simulator=LTspice)
    print("シミュレーション実行中...")
    raw_path, log_path = runner.run_now(netlist)
    if raw_path is None or not os.path.exists(raw_path):
        raise RuntimeError(f"LTspice 実行に失敗しました（log: {log_path}）")

    import numpy as np

    raw = RawRead(raw_path)
    names = raw.get_trace_names()
    try:
        time = raw.get_axis(0)
    except Exception:
        # 新ADI版 LTspice 等で軸が認識されない場合は 'time' トレースを直読み
        time_name = next((n for n in names if n.lower() == "time"), None)
        if time_name is None:
            raise
        time = raw.get_trace(time_name).get_wave(0)
    # LTspice は重複点で時間に符号を付けることがあるため絶対値を取る
    time = np.abs(np.asarray(time, dtype=float))

    # 出力したい信号（存在するものだけ）。名前は LTspice の表記に合わせる。
    wanted = ["V(out)", "V(n002)", "V(n001)", "I(L1)", "I(C1)", "I(R1)"]
    available = {n.lower(): n for n in names}
    cols = {}
    for w in wanted:
        key = w.lower()
        if key in available:
            cols[w] = raw.get_trace(available[key]).get_wave(0)

    if not cols:  # 想定名が無ければ time 以外を全部出す
        for n in names:
            if n.lower() != "time":
                cols[n] = raw.get_trace(n).get_wave(0)

    os.makedirs(os.path.dirname(os.path.abspath(out_csv)), exist_ok=True)
    header = ",".join(["時間[s]"] + list(cols.keys()))
    data = np.column_stack([np.asarray(time, dtype=float)]
                           + [np.asarray(v, dtype=float) for v in cols.values()])
    np.savetxt(out_csv, data, delimiter=",", header=header, comments="",
               fmt="%.6e", encoding="utf-8-sig")
    return out_csv, len(time), list(cols.keys())


def main():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    p = argparse.ArgumentParser(description="LTspice 連携で波形CSVを生成")
    p.add_argument("--out", default=os.path.join(here, "サンプルデータ", "LTspice_RLC減衰振動.csv"))
    p.add_argument("--work-dir", default=os.path.join(here, "tools", "ltspice_work"))
    p.add_argument("--R", default="2")
    p.add_argument("--L", default="1m")
    p.add_argument("--C", default="1u")
    p.add_argument("--tstop", default="10m")
    p.add_argument("--maxstep", default="50n")
    p.add_argument("--exe", default=None, help="LTspice 実行ファイルのパス（自動検出されない場合）")
    args = p.parse_args()

    try:
        out, n, cols = run_and_export(
            args.out, args.work_dir, args.R, args.L, args.C,
            args.tstop, args.maxstep, exe=args.exe,
        )
    except Exception as e:  # noqa: BLE001
        print(f"[エラー] LTspice 連携に失敗しました: {e}", file=sys.stderr)
        print("LTspice が未インストール／検出できない場合は "
              "tools/generate_waveforms.py（合成波形）をお使いください。", file=sys.stderr)
        sys.exit(1)

    size = os.path.getsize(out)
    print(f"生成: {out}")
    print(f"  点数: {n}  列: {cols}  サイズ: {size/1e6:.1f} MB")


if __name__ == "__main__":
    main()
