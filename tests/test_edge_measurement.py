# -*- coding: utf-8 -*-
"""エッジ測定の回帰。

issue #4: _mid_crossings が NaN 非対応で、欠測が1点あると偽の立上り/立下りを作る。
issue #5: _edge_time が交差時刻を補間せず、立上り/立下り時間が ±dt 量子化される。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import numpy as np  # noqa: E402
import analysis_common as ac  # noqa: E402


# ---------------- #4 NaN で偽エッジを作らない ----------------
def test_mid_crossings_ignores_nan_gap():
    """全点が閾値未満で、途中に NaN が1点あっても交差は0本（偽エッジなし）。"""
    t = np.arange(10, dtype=float)
    y = np.full(10, -1.0)
    y[5] = np.nan                      # 欠測1点
    up, down = ac._mid_crossings(t, y, 0.0)
    assert up.size == 0 and down.size == 0, (up, down)


def test_mid_crossings_keeps_real_edge_with_nan_elsewhere():
    """本物の立上りは検出しつつ、別の場所の NaN では偽エッジを作らない。"""
    t = np.arange(8, dtype=float)
    y = np.array([-1, -1, -1, 1, 1, np.nan, 1, 1], dtype=float)
    up, down = ac._mid_crossings(t, y, 0.0)
    assert up.tolist() == [2], up       # 2→3 の本物の立上りだけ
    assert down.size == 0, down          # NaN 近傍の偽の立下りは出ない


# ---------------- #5 立上り/立下り時間を線形補間する ----------------
def test_edge_time_is_interpolated_not_quantized():
    """オフグリッドの遷移で、交差を線形補間した時間を返す（±dt 量子化でない）。

    旧実装は交差直前サンプルの時刻差を返したので、結果は必ず dt の整数倍だった。
    補間後は格子に乗らず、解析値（立上り時間≒0.152）に十分近い。"""
    t = np.linspace(0.0, 1.0, 101)                 # dt = 0.01
    dt = t[1] - t[0]
    y = np.clip((t - 0.405) / 0.19, 0.0, 1.0)       # 0.405〜0.595 を直線で 0→1
    rt = ac._edge_time(t, y, rising=True)
    assert rt is not None
    k = rt / dt
    assert abs(k - round(k)) > 1e-3, f"dt の整数倍＝量子化されている: {rt}"
    assert abs(rt - 0.152) < 5e-3, rt               # 解析値 0.152（Top/Base推定誤差ぶん許容）

    fy = 1.0 - y                                    # 対称な立下り
    ft = ac._edge_time(t, fy, rising=False)
    assert ft is not None
    kf = ft / dt
    assert abs(kf - round(kf)) > 1e-3, f"量子化されている: {ft}"
    assert abs(ft - 0.152) < 5e-3, ft


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    ok = 0
    for fn in fns:
        try:
            fn(); ok += 1; print(f"  [PASS] {fn.__name__}")
        except Exception:
            traceback.print_exc(); print(f"  [FAIL] {fn.__name__}")
    print(f"総合: {ok}/{len(fns)} PASS")
    sys.exit(0 if ok == len(fns) else 1)
