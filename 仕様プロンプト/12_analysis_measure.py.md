# [12/30] analysis_measure.py の仕様

## 指示

- **この仕様だけを読んで `analysis_measure.py` を完全な形（全関数の本体まで）で実装し、出力すること。**
- **`pass` での放置・`TODO`・省略・要約・「以下同様」等は一切禁止。** すべての関数を、説明された分岐・式・戻り値の形どおりに実装しきること。
- **出力が長くて途中で切れた場合は、続けて「続き」と促されたら最後まで出力すること。** コードを省略してはならない。
- 戻り値の辞書キー名・要素名・単位文字列・日本語ラベルは、本仕様に書かれた**正確な値そのまま**を使うこと（呼び出し側がこれらのキー/ラベルに依存する）。

### アプリ全体の前提（本ファイル関係分）

- Python 3.10+。本ファイルは **純粋な数値解析モジュール**であり、GUI（PySide6/Qt）には一切依存しない。Qt の import は禁止。
- 数値計算は `numpy` を主体に行う。`scipy` は本ファイルでは直接 import しない（依存先 `analysis_common` / `analysis_spectrum` が必要に応じて遅延 import＋numpy フォールバックを内部で処理する）。
- このモジュールは `analysis.py`（facade）から `import *` 等で再公開される側の実体ファイルの 1 つ。公開関数名は変更しないこと。

---

## ファイルの役割／責務

ファイル先頭の docstring は次のとおり（1 行）:

```
"""自動測定（Vpp/RMS・立上り・パルス幅・サイクル統計・位相差・一括 analyze）。"""
```

オシロスコープ的な**自動測定値**を計算するモジュール。波形 `(t, y)` を受け取り、以下を提供する:

- `measurements(t, y)` … 表示用の主要測定値リスト（各要素 `{name, value, unit}`）。
- スルーレート / サイクル統計 / ヒストグラム由来統計 / エッジ間時間 / パルス測定 / サイクルごとの測定配列・統計。
- 2 チャンネル間の位相差・遅延（相互相関）。
- `analyze(t, y, ...)` … ピーク・測定・スペクトルピークを 1 つの辞書にまとめる便利関数。

ファイル冒頭は `# -*- coding: utf-8 -*-` のエンコーディング宣言で始める。

---

## 依存（import するもの）

```python
import numpy as np

from analysis_common import (sampling_rate, find_signal_peaks, _trapz,
                             _zero_crossing_period, _edge_time,
                             histogram_top_base, _mid_crossings)
from analysis_spectrum import dominant_frequency, find_spectral_peaks
```

import の意味（依存関数の契約。本ファイルで再実装しないこと）:

- `sampling_rate(t)` → 平均サンプリング周波数 [Hz]（`float` または `None`）。
- `find_signal_peaks(y, t=None, n=5, prominence_frac=0.05, distance=None, mode="max", smooth=0)` → 信号ピーク上位 n 個のリスト。
- `_trapz(y, x)` → 台形積分値（`np.trapz` 相当）。
- `_zero_crossing_period(t, y)` → 平均を引いた信号の上昇ゼロ交差から周期 [s]（推定不能なら `None`）。
- `_edge_time(t, y, rising=True, lo=0.1, hi=0.9)` → 最初のエッジの 10%-90%（または 90%-10%）遷移時間 [s]。
- `histogram_top_base(y, bins=256)` → ヒストグラム法による `(top, base)`。`has` でない/判定不能なら `(None, None)`。
- `_mid_crossings(t, y, level)` → `level` を横切る `(up, down)` インデックス配列（up=上昇交差、down=下降交差）。
- `dominant_frequency(t, y)` → FFT による支配周波数 [Hz]（`None` あり）。
- `find_spectral_peaks(t, y, n=5, prominence_frac=0.02)` → スペクトルピーク上位 n 個のリスト。

---

## 公開 API（完全シグネチャと挙動）

すべてモジュール直下の関数（クラス無し）。定義順は以下のとおり。

### 1. `measurements(t, y)`

役割: 主要測定値のリストを返す。各要素は辞書 `{"name": <str>, "value": <float|None>, "unit": <str>}`。

戻り値: `list[dict]`（順序が重要。下記の追加順そのまま）。

実装詳細:

1. 先頭で `t = np.asarray(t, dtype=float)`、`y = np.asarray(y, dtype=float)`。`rows = []` を用意。
2. 内部ヘルパ `add(name, value, unit="")` を定義し、`rows.append({"name": name, "value": value, "unit": unit})` する。
3. `finite = np.isfinite(y)`、`has = bool(finite.any())`。
4. `vmax = float(np.nanmax(y)) if has else None`、`vmin = float(np.nanmin(y)) if has else None`。
5. 以下を**この順序で** `add` する（左がラベル文字列、丸括弧内が value 式、右が unit）:

   | # | name（正確に） | value 式 | unit |
   |---|---|---|---|
   | 1 | `最大値 Vmax` | `vmax` | `V` |
   | 2 | `最小値 Vmin` | `vmin` | `V` |
   | 3 | `P-P値 Vpp` | `(vmax - vmin) if has else None` | `V` |
   | 4 | `平均 Vmean` | `float(np.nanmean(y)) if has else None` | `V` |
   | 5 | `実効値 Vrms` | `float(np.sqrt(np.nanmean(y ** 2))) if has else None` | `V` |
   | 6 | `標準偏差 σ` | `float(np.nanstd(y)) if has else None` | `V` |

6. `period = _zero_crossing_period(t, y)`。続けて add:
   - `周期` = `period`、unit `s`
   - `周波数(ゼロ交差)` = `(1.0 / period) if period else None`、unit `Hz`
   - `周波数(FFT)` = `dominant_frequency(t, y)`、unit `Hz`
7. Top/Base 系（コメント `# Top/Base（ヒストグラム法）と振幅・オーバーシュート等`）:
   - `top, base = histogram_top_base(y) if has else (None, None)`
   - add `Top` = `top` (V)、`Base` = `base` (V)
   - `amp = (top - base) if (top is not None and base is not None) else None`
   - add `振幅 Vamp(Top-Base)` = `amp` (V)
   - `if amp and amp > 0:`（`amp` が真かつ正のとき）
     - add `オーバーシュート` = `(vmax - top) / amp * 100.0` (`%`)
     - add `アンダーシュート` = `(base - vmin) / amp * 100.0` (`%`)
   - `else:`
     - add `オーバーシュート` = `None` (`%`)、`アンダーシュート` = `None` (`%`)
8. 立上り/立下り時間:
   - add `立上り時間 (10-90%)` = `_edge_time(t, y, rising=True)` (s)
   - add `立下り時間 (90-10%)` = `_edge_time(t, y, rising=False)` (s)
9. パルス測定（`pm = pulse_metrics(t, y)`、コメント `# パルス幅・デューティ・エッジ/サイクル数（中央しきい値）`）。`pm.get(...)` で取り出し add:
   - `+パルス幅` = `pm.get("pos_width")` (s)
   - `-パルス幅` = `pm.get("neg_width")` (s)
   - `+デューティ比` = `pm.get("pos_duty")` (%)
   - `-デューティ比` = `pm.get("neg_duty")` (%)
   - `立上りエッジ数` = `pm.get("rising_edges")` (unit `""`)
   - `サイクル数` = `pm.get("cycles")` (unit `""`)
10. エッジ間時間（`ei = edge_intervals(t, y)`、コメント `# エッジ間時間（立上り→立上り 等）`）:
    - `立上り→立上り` = `ei.get("rise_to_rise")` (s)
    - `立下り→立下り` = `ei.get("fall_to_fall")` (s)
    - `立上り→立下り(High幅)` = `ei.get("rise_to_fall")` (s)
    - `立下り→立上り(Low幅)` = `ei.get("fall_to_rise")` (s)
11. ピーク到達時刻・面積（コメント `# ピーク到達時刻・面積`）:
    - `if has:`
      - add `Time@Max` = `float(t[int(np.nanargmax(y))])` (s)
      - add `Time@Min` = `float(t[int(np.nanargmin(y))])` (s)
      - `fin = np.isfinite(y) & np.isfinite(t)`
      - `if fin.sum() >= 2:` → add `面積 ∫y dt` = `float(_trapz(y[fin], t[fin]))` (`V·s`)
      - `else:` → add `面積 ∫y dt` = `None` (`V·s`)
    - `else:`
      - add `Time@Max` = `None` (s)、`Time@Min` = `None` (s)、`面積 ∫y dt` = `None` (`V·s`)
      （元コードでは `Time@Max`/`Time@Min` を `;` 区切り 1 行で記述しているが、改行で 3 文に分けても等価で可）
12. add `サンプル数` = `float(y.size)`、unit `点`
13. add `サンプリング周波数` = `sampling_rate(t)`、unit `Hz`
14. 追加測定（コメント `# --- 追加測定（中央値/リプル/スルーレート/サイクル統計/ヒストグラム由来）---`）:
    - add `中央値 Median` = `float(np.nanmedian(y)) if has else None` (V)
    - add `リプル(AC RMS)` = `float(np.nanstd(y)) if has else None` (V)
    - `sr = slew_rate(t, y)`:
      - add `スルーレート(立上り最大)` = `sr.get("rise")` (`V/s`)
      - add `スルーレート(立下り最大)` = `sr.get("fall")` (`V/s`)
    - `cs = cycle_stats(t, y)`:
      - add `サイクル平均` = `cs.get("cycle_mean")` (V)
      - add `サイクルRMS` = `cs.get("cycle_rms")` (V)
      - add `Cycle-Cycleジッタ` = `cs.get("cc_jitter")` (s)
    - `pd_ = pm.get("pos_duty")`、add `デューティ誤差(50%基準)` = `(pd_ - 50.0) if pd_ is not None else None` (%)
    - `hb = histogram_box_stats(y) if has else {}`:
      - add `最頻ビン点数 PEAKHits` = `hb.get("peak_hits")` (`点`)
      - add `±1σ以内` = `hb.get("sigma1")` (%)
      - add `±2σ以内` = `hb.get("sigma2")` (%)
      - add `±3σ以内` = `hb.get("sigma3")` (%)
15. `return rows`。

エッジケース/注意:
- `has=False`（全要素が非有限）でも例外を投げず、各値を `None` にして全行を必ず追加する（行数は不変）。
- `period` が `0` または `None`/falsy のとき `周波数(ゼロ交差)` は `None`。
- `vmax`/`vmin` は `np.nanmax`/`np.nanmin`、平均・RMS・std はすべて `nan*` 系を使用（NaN 混在に頑健）。

### 2. `slew_rate(t, y)`

役割: 最大の立上り/立下りスルーレート [V/s]（隣接サンプル間の傾きの最大/最小）。

戻り値: `dict`。算出可能なら `{"rise": float, "fall": float}`、不能なら `{}`（空辞書）。

実装:
1. `t`, `y` を `float` の `np.asarray` 化。
2. `if t.size < 2: return {}`。
3. `dt = np.diff(t)`、`dy = np.diff(y)`。
4. `sl = np.divide(dy, dt, out=np.full_like(dy, np.nan), where=dt != 0)`（0 除算位置は NaN）。
5. `sl = sl[np.isfinite(sl)]`。`if sl.size == 0: return {}`。
6. `return {"rise": float(np.max(sl)), "fall": float(np.min(sl))}`。

### 3. `cycle_stats(t, y)`

役割: サイクル（上昇ゼロ交差〜次の上昇ゼロ交差）単位の平均/RMS と、Cycle-Cycle ジッタ（隣り合う周期長の差の標準偏差）を返す。docstring は 2 行（上記趣旨）。

戻り値: `dict`。キーは存在するもののみ（`cycle_mean` / `cycle_rms` / `cc_jitter`）。条件未達なら `{}`。

実装:
1. `t`, `y` を float 配列化。`if t.size < 8: return {}`。
2. `y0 = y - np.nanmean(y)`、`below = y0 < 0`。
3. `up = np.where(below[:-1] & ~below[1:])[0]`（上昇ゼロ交差インデックス。コメント `# 上昇ゼロ交差`）。
4. `if up.size < 3: return {}`。
5. `periods = np.diff(t[up])`。
6. `means, rmss = [], []`。`for a, b in zip(up[:-1], up[1:]):`:
   - `seg = y[a:b]`、`seg = seg[np.isfinite(seg)]`。
   - `if seg.size:` → `means.append(float(seg.mean()))`、`rmss.append(float(np.sqrt(np.mean(seg ** 2))))`。
7. `out = {}`。
8. `if means:` → `out["cycle_mean"] = float(np.mean(means))`、`out["cycle_rms"] = float(np.mean(rmss))`。
9. `if periods.size >= 2:` → `out["cc_jitter"] = float(np.std(np.diff(periods)))`。
10. `return out`。

### 4. `histogram_box_stats(y, bins=256)`

役割: ヒストグラム由来の測定：最頻ビンの点数 PEAKHits、平均±1/2/3σ内の割合 [%]。

戻り値: `dict`（`peak_hits`, `sigma1`, `sigma2`, `sigma3`）。データ不足なら `{}`。

実装:
1. `y = np.asarray(y, dtype=float)`、`y = y[np.isfinite(y)]`。
2. `if y.size < 4: return {}`。
3. `hist, _ = np.histogram(y, bins=bins)`。
4. `mean = float(y.mean())`、`std = float(y.std())`。
5. 内部関数 `within(k)`: `return float(np.mean(np.abs(y - mean) <= k * std) * 100.0) if std > 0 else None`（`std<=0` のとき `None`）。
6. `return {"peak_hits": float(hist.max()), "sigma1": within(1), "sigma2": within(2), "sigma3": within(3)}`。

### 5. `cycle_statistics(t, y)`

役割: サイクルごとの 周波数/周期/振幅/Vpp の統計（min/max/mean/std/count）を返す。

戻り値: `dict`。キーは日本語ラベル `周波数 [Hz]` / `周期 [s]` / `振幅 [V]` / `Vpp [V]`。各値は `measurement_stats(...)` の返す統計辞書。

実装:
1. `cm = cycle_measurements(t, y)`。`out = {}`。
2. `freq = np.asarray(cm.get("freq", []), dtype=float)`。
3. `out["周波数 [Hz]"] = measurement_stats(freq)`。
4. `if freq.size:` → `out["周期 [s]"] = measurement_stats(1.0 / freq[freq > 0])`（周波数が正の要素だけ逆数。`freq.size==0` のときは周期キー自体を追加しない）。
5. `out["振幅 [V]"] = measurement_stats(np.asarray(cm.get("amp", []), dtype=float))`。
6. `out["Vpp [V]"] = measurement_stats(np.asarray(cm.get("vpp", []), dtype=float))`。
7. `return out`。

注意: 辞書キーのラベルは半角スペースと角括弧を含む正確な文字列（`周波数 [Hz]` 等）であること。

### 6. `edge_intervals(t, y, level=None)`

役割: エッジ間時間（立上り→立上り/立下り→立下り/立上り→立下り/立下り→立上り）の平均 [s]。

戻り値: `dict`。存在するキーのみ（`rise_to_rise` / `fall_to_fall` / `rise_to_fall` / `fall_to_rise`）。条件未達なら `{}`。

実装:
1. `t`, `y` を float 配列化。`if np.isfinite(y).sum() < 4: return {}`。
2. `if level is None:`
   - `top, base = histogram_top_base(y)`。
   - `if top is None or top <= base: return {}`。
   - `level = (top + base) / 2.0`（中央しきい値）。
3. `up, dn = _mid_crossings(t, y, level)`。
4. 内部関数 `cross_times(idx)`: 交差点の**線形補間**による正確な時刻を返す:
   - `idx = np.asarray(idx, dtype=int)`。`if idx.size == 0: return np.asarray([], dtype=float)`。
   - `y1, y2 = y[idx], y[idx + 1]`、`denom = y2 - y1`。
   - `f = np.where(denom != 0.0, (level - y1) / np.where(denom != 0.0, denom, 1.0), 0.0)`（0 除算回避のため分母を 1 に差し替えてから比率を作り、`denom==0` の位置は最終的に `0.0`）。
   - `return t[idx] + f * (t[idx + 1] - t[idx])`。
5. `ut, dt_ = cross_times(up), cross_times(dn)`。`res = {}`。
6. `if ut.size >= 2:` → `res["rise_to_rise"] = float(np.mean(np.diff(ut)))`。
7. `if dt_.size >= 2:` → `res["fall_to_fall"] = float(np.mean(np.diff(dt_)))`。
8. High 幅（立上り→次の立下り）: `rf = [dt_[dt_ > u][0] - u for u in ut if (dt_ > u).any()]`（各上昇交差時刻 `u` の直後の下降交差時刻との差）。
9. Low 幅（立下り→次の立上り）: `fr = [ut[ut > d][0] - d for d in dt_ if (ut > d).any()]`。
10. `if rf:` → `res["rise_to_fall"] = float(np.mean(rf))`。`if fr:` → `res["fall_to_rise"] = float(np.mean(fr))`。
11. `return res`。

### 7. `pulse_metrics(t, y, level=None)`

役割: +/- パルス幅・デューティ・エッジ数・サイクル数を返す。

戻り値: `dict`。キー: `rising_edges`, `pos_width`, `neg_width`, （両方非0なら）`pos_duty`/`neg_duty`, `cycles`。条件未達なら空辞書のことがある。

実装:
1. `t`, `y` を float 配列化。`out = {}`。
2. `finite = np.isfinite(y)`。`if finite.sum() < 4: return out`。
3. `if level is None:`
   - `top, base = histogram_top_base(y)`。
   - `if top is None or top <= base: return out`。
   - `level = (top + base) / 2.0`。
4. `up, down = _mid_crossings(t, y, level)`。
5. `out["rising_edges"] = float(len(up))`。
6. `highs, lows = [], []`（コメント `# 高区間（up→次のdown）と低区間（down→次のup）の幅`）:
   - `for u in up:` → `nxt = down[down > u]`、`if nxt.size: highs.append(t[nxt[0]] - t[u])`。
   - `for d in down:` → `nxt = up[up > d]`、`if nxt.size: lows.append(t[nxt[0]] - t[d])`。
   - ※ こちらの幅はサンプルインデックスでの時刻差（補間なし）であり、`edge_intervals` の補間版とは別物。
7. `pw = float(np.mean(highs)) if highs else None`、`nw = float(np.mean(lows)) if lows else None`。
8. `out["pos_width"] = pw`、`out["neg_width"] = nw`。
9. `if pw and nw:` → `out["pos_duty"] = pw / (pw + nw) * 100.0`、`out["neg_duty"] = nw / (pw + nw) * 100.0`。
10. `out["cycles"] = float(min(len(up), len(down))) if (len(up) and len(down)) else float(len(up))`。
11. `return out`。

### 8. `cycle_measurements(t, y)`

役割: サイクルごとの周波数・振幅の配列を返す（トレンド/統計用）。docstring に `Returns dict: {cycle_time, freq, amp, vpp}（各配列）`。

戻り値: `dict`、キー `cycle_time` / `freq` / `amp` / `vpp`、各値は `np.ndarray(dtype=float)`（空でも numpy 配列）。

実装:
1. `t`, `y` を float 配列化。
2. `y0 = y - np.nanmean(y)`、`below = y0 < 0`、`up = np.where(below[:-1] & ~below[1:])[0]`（上昇ゼロ交差）。
3. `res = {"cycle_time": [], "freq": [], "amp": [], "vpp": []}`（最初は list）。
4. `for a, b in zip(up[:-1], up[1:]):`:
   - `period = t[b] - t[a]`。`if period <= 0: continue`。
   - `seg = y[a:b]`、`seg = seg[np.isfinite(seg)]`。`if seg.size == 0: continue`。
   - `res["cycle_time"].append((t[a] + t[b]) / 2.0)`。
   - `res["freq"].append(1.0 / period)`。
   - `res["vpp"].append(float(seg.max() - seg.min()))`。
   - `res["amp"].append(float((seg.max() - seg.min()) / 2.0))`（振幅は Vpp の半分）。
5. `for k in res: res[k] = np.asarray(res[k], dtype=float)`（最後に全リストを numpy 配列化）。
6. `return res`。

### 9. `measurement_stats(values)`

役割: 測定値配列の min/max/mean/σ/数 を返す。

戻り値: `dict`。常にキー `min`, `max`, `mean`, `std`, `count` を持つ。空なら値は `None`（count は `0`）。

実装:
1. `v = np.asarray(values, dtype=float)`、`v = v[np.isfinite(v)]`。
2. `if v.size == 0: return {"min": None, "max": None, "mean": None, "std": None, "count": 0}`。
3. `return {"min": float(v.min()), "max": float(v.max()), "mean": float(v.mean()), "std": float(v.std()), "count": int(v.size)}`。

### 10. `phase_delay(t, y1, y2)`

役割: 2 チャンネル間の遅延 [s] と位相差 [deg] を相互相関で求める。

戻り値: `tuple (delay, phase)`。`delay` は `float` または `None`、`phase` は `float` または `None`。

実装:
1. `t = np.asarray(t, dtype=float)`、`a = np.asarray(y1, dtype=float)`、`b = np.asarray(y2, dtype=float)`。
2. `n = min(a.size, b.size)`。`if n < 4: return None, None`。
3. `a, b = a[:n], b[:n]`（長さを揃える）。
4. `a = a - np.nanmean(a)`、`b = b - np.nanmean(b)`（DC 除去）。
5. `a = np.nan_to_num(a)`、`b = np.nan_to_num(b)`（NaN を 0 に）。
6. `corr = np.correlate(a, b, mode="full")`。
7. `lag = int(np.argmax(corr)) - (n - 1)`（相互相関ピークのラグ。中心 `n-1` を引く）。
8. `dt = np.median(np.diff(t[:n]))`。
9. `delay = -lag * dt`（コメント `# y2 が遅れていれば正`）。
10. `period = _zero_crossing_period(t, a)`。
11. `phase = (-delay / period * 360.0) if period else None`（コメント `# 遅れは負位相`）。
12. `if phase is not None: phase = ((phase + 180.0) % 360.0) - 180.0`（コメント `# -180..180 に正規化`）。
13. `return float(delay), (float(phase) if phase is not None else None)`。

注意: `period` が falsy（`None`/`0`）のとき `phase` は `None`。`delay` は常に float（`n>=4` の場合）。

### 11. `analyze(t, y, n_peaks=5, smooth=0)`

役割: ピーク・測定・FFT をまとめて返す便利関数。`smooth` で平滑化してピーク検出。

戻り値: 次の 4 キーを持つ `dict`:

```python
{
    "peaks":          find_signal_peaks(y, t=t, n=n_peaks, smooth=smooth),
    "troughs":        find_signal_peaks(y, t=t, n=n_peaks, mode="min", smooth=smooth),
    "measurements":   measurements(t, y),
    "spectral_peaks": find_spectral_peaks(t, y, n=n_peaks),
}
```

- `peaks` は上向きピーク（既定 `mode="max"`）、`troughs` は `mode="min"`（谷）。両方に `smooth=smooth` を渡す。
- `find_spectral_peaks` には `smooth` を渡さない（`n=n_peaks` のみ）。

---

## 再現に必須の細部・落とし穴

- **辞書キー名・ラベル文字列は外部依存契約**。`measurements` の `name` 文字列（例: `P-P値 Vpp`、`周波数(ゼロ交差)`、`立上り→立下り(High幅)`、`最頻ビン点数 PEAKHits`、`±1σ以内` 等）、`cycle_statistics` のキー（`周波数 [Hz]` 等）、各 sub-metric の英字キー（`pos_width` / `neg_width` / `pos_duty` / `neg_duty` / `rising_edges` / `cycles` / `rise_to_rise` / `fall_to_fall` / `rise_to_fall` / `fall_to_rise` / `rise` / `fall` / `cycle_mean` / `cycle_rms` / `cc_jitter` / `peak_hits` / `sigma1..3` / `cycle_time` / `freq` / `amp` / `vpp` / `min` / `max` / `mean` / `std` / `count`）は一字一句変えない。
- **単位文字列**も正確に: `V` / `s` / `Hz` / `%` / `V·s`（中黒は U+00B7 の `·`）/ `V/s` / `点` / 空文字 `""`。
- **measurements の行は条件にかかわらず常に全行追加**（`has=False` でも `value=None` で同数の行が出る）。表示側がインデックス/件数に依存しうるため、行の増減や順序変更は不可。
- **0 除算ガード**: `slew_rate` の `np.divide(..., where=dt!=0)`、`edge_intervals.cross_times` の二重 `np.where(denom!=0.0, ...)`。これらを省略すると NaN/警告でクラッシュしうる。
- **しきい値レベル**: `pulse_metrics` / `edge_intervals` は `level=None` のとき `histogram_top_base` の Top/Base の中点 `(top+base)/2.0`。`top is None or top <= base` のときは早期 return（`pulse_metrics` は `out`(空 dict 相当)、`edge_intervals` は `{}`）。
- **最小サンプル数ガード**: `slew_rate` は `t.size<2`、`cycle_stats` は `t.size<8`、`histogram_box_stats` は有限 `y.size<4`、`edge_intervals`/`pulse_metrics` は有限 `y.sum()<4`、`phase_delay` は `n<4`。閾値を厳密に再現すること。
- **上昇ゼロ交差の判定式** `np.where(below[:-1] & ~below[1:])[0]` は `cycle_stats` と `cycle_measurements` で共通（平均を引いた信号に対して `below = (y - mean) < 0`）。
- **`cycle_measurements` の戻り値は numpy 配列**（最後に `np.asarray(..., dtype=float)` で変換）。空でもリストではなく空 numpy 配列で返す。`amp` は `(max-min)/2`、`vpp` は `(max-min)`。
- **`measurement_stats` は空でも常に 5 キーを持つ辞書**を返す（`count` は `0`、他は `None`）。`std` は母標準偏差（`np.std` 既定 `ddof=0`）。
- **`phase_delay` のラグ符号**: `delay = -lag * dt`、位相は `-delay/period*360`、最後に `[-180, 180)` 正規化（`((phase+180)%360)-180`）。コメントの「y2 が遅れていれば正」「遅れは負位相」を保持。
- **Qt 非依存**: このモジュールに PySide6/matplotlib/Qt の import を入れないこと（spawn 安全・facade 経由公開の前提）。`monospace`・`grid linewidth=None`・Qt6 列挙などの GUI 落とし穴は本ファイルには無関係（描画はしない）。
- **`scipy` を直接 import しない**: FFT/ピークは `analysis_spectrum`/`analysis_common` 側に委譲済み。
- コメント文（`# 上昇ゼロ交差`、`# y2 が遅れていれば正`、`# -180..180 に正規化` 等）は再現しても省略しても動作上等価だが、可読性のため極力残すこと。
