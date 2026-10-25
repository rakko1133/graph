# [10/30] analysis_common.py の仕様

## 指示

- **この仕様だけを読んで `analysis_common.py` を完全な形で実装し、出力すること。**
- `pass`・`TODO`・「…省略…」・要約・部分実装は**一切禁止**。すべての関数を実際に動く完全な本体で書くこと。
- 出力が途中で切れたら、続けて「続き」と入力されたら**最後まで**残りを出力すること。
- 本ファイルは GUI を含まない純粋な数値解析ユーティリティ。Qt も matplotlib も import しない。

### アプリ全体の前提（本ファイルに関係する分のみ）

- Python 3.10+ 環境。本モジュールは **PySide6/Qt に一切依存しない**純粋な解析プリミティブ集である（GUI レイヤーから呼ばれる下位ライブラリ）。
- **scipy は遅延 import ＋ numpy フォールバック**。モジュール先頭で `importlib.util.find_spec("scipy")` により有無を判定するが、scipy 本体はトップレベルで import しない（起動を軽くするため、必要になった関数内でのみ import する）。scipy が存在しなくても全関数が numpy だけで動作すること。
- `batch_render`（別ファイル）が安全に spawn できるよう、本モジュールは Qt を import してはならない。

---

## ファイルの役割・責務

モジュール docstring（先頭行）は次のとおり（**この文字列をそのまま使う**）:

```
解析の共通プリミティブ（窓関数・ピーク検出・ゼロ交差・Top/Base 等）。
```

このモジュールは、FFT/オシロ風解析で共通利用される下位プリミティブを提供する:

- サンプリング周波数の推定
- 信号の平滑化（Savitzky-Golay 優先）
- ピーク（極大・谷）検出
- ゼロ交差による周期推定
- 立上り/立下りエッジの 10%-90% 遷移時間
- 窓関数の生成
- dB 変換
- ヒストグラム法による Top/Base 推定
- 中央レベルの上下交差位置

scipy が利用可能なら高精度な実装（`savgol_filter`, `find_peaks`, `scipy.signal.windows`）を使い、無ければ numpy だけのフォールバックに切り替える。

---

## 先頭の import と モジュールレベル定義

ファイル先頭は以下の順・内容で書く（**1 行目はエンコーディング宣言**）:

1. 1 行目: `# -*- coding: utf-8 -*-`
2. 2 行目: モジュール docstring（上記文字列）
3. `import importlib.util as _ilu`
4. （空行）
5. `import numpy as np`

### モジュールレベルの定数・変数

| 名前 | 定義 | 説明 |
|---|---|---|
| `_trapz` | `getattr(np, "trapezoid", None) or np.trapz` | numpy の積分関数。新しい numpy の `trapezoid` を優先、無ければ非推奨 `trapz` にフォールバック（本ファイル内では未使用だが**必ず定義する**）。 |
| `_HAVE_SCIPY` | `_ilu.find_spec("scipy") is not None` | scipy が import 可能かどうかの真偽値。各関数の遅延 import 前のガードに使う。 |
| `WINDOWS` | リスト（下記） | サポートする窓関数名の一覧。 |

`WINDOWS` の**正確な値**（順序も厳守）:

```python
WINDOWS = ["hann", "hamming", "blackman", "blackmanharris", "flattop",
           "kaiser", "gaussian", "rect"]
```

---

## 公開 API（全関数の完全仕様）

以下の順序で定義する。引数名・デフォルト値・docstring 文言を正確に守る。

### 1. `sampling_rate(t)`

- docstring: `時間軸 t[s] から平均サンプリング周波数[Hz]を推定する。`
- 処理:
  1. `t = np.asarray(t, dtype=float)`
  2. `t.size < 2` なら `None` を返す。
  3. `dt = np.median(np.diff(t))`（隣接差分の中央値）。
  4. `dt > 0` なら `1.0 / dt`、そうでなければ `None` を返す。
- 戻り値: `float`（Hz）または `None`。

### 2. `_simple_peaks(sig, distance=1)`

- docstring: `scipy が無い場合の素朴な極大検出。`
- 処理: 内部 3 点比較で極大インデックスを返す。
  - `idx = np.where((sig[1:-1] > sig[:-2]) & (sig[1:-1] >= sig[2:]))[0] + 1`
  - 左隣より**真に大きく**、右隣**以上**（`>=`）の点を極大とする（フラットなピークの左端を拾う非対称比較に注意）。
- 戻り値: 極大インデックスの `np.ndarray`。
- 注意: `distance` 引数は受け取るが**本実装では使用しない**（シグネチャ互換のため残す）。

### 3. `smooth_signal(y, window)`

- docstring: `移動窓で平滑化（Savitzky-Golay 優先、無ければ移動平均）。ノイズ低減用。`
- 処理:
  1. `y = np.asarray(y, dtype=float)`、`w = int(window)`。
  2. `w < 3` または `w > y.size` なら、平滑化せず `y` をそのまま返す。
  3. `w` が偶数なら `w += 1`（窓長を奇数に強制）。
  4. `try`: `from scipy.signal import savgol_filter` して `return savgol_filter(y, w, min(2, w - 1))` を返す（多項式次数は 2 と `w-1` の小さい方）。
  5. `except Exception`: 移動平均にフォールバック。`k = np.ones(w) / w`、`return np.convolve(y, k, mode="same")`。
- 戻り値: 平滑化後の `np.ndarray`（または条件未達時は入力そのまま）。

### 4. `find_signal_peaks(y, t=None, n=5, prominence_frac=0.05, distance=None, mode="max", smooth=0)`

- docstring（**そのまま使用**）:
```
信号の主要ピークを上位 n 個、顕著さ(prominence)順で返す。

第1ピーク・第2ピーク…のように rank 付きで返す。mode="min" で谷を検出。
smooth>=3 で平滑化してからピーク検出し、ノイズの偽ピークを抑える。

Returns: list of dict {rank, index, time, value, prominence}
```
- 処理:
  1. `y = np.asarray(y, dtype=float)`。`y.size < 3` なら `[]` を返す。
  2. `smooth` が真かつ `smooth >= 3` なら `y = smooth_signal(y, smooth)`（平滑化後の信号でピークを評価する）。
  3. `sig = y if mode == "max" else -y`（`mode="min"` のとき符号反転して谷を極大として扱う）。
  4. `span = float(np.nanmax(y) - np.nanmin(y))`。
  5. `prom = prominence_frac * span if span > 0 else None`（顕著さの絶対しきい値）。
  6. **scipy 分岐**: `_HAVE_SCIPY` が真なら:
     - `from scipy.signal import find_peaks`（遅延 import。コメント「遅延import（起動を軽くする）」）。
     - `kwargs = {}`。`prom` が真なら `kwargs["prominence"] = prom`。`distance` が真なら `kwargs["distance"] = int(distance)`。
     - `idx, props = find_peaks(sig, **kwargs)`。`proms = props.get("prominences")`。
  7. **フォールバック分岐**: scipy 無しなら `idx = _simple_peaks(sig, distance or 1)`、`proms = None`。
  8. `len(idx) == 0` なら `[]` を返す。
  9. **並び替え**:
     - `proms` が `None` でなく長さがあるなら、`order = np.argsort(proms)[::-1]`（顕著さ降順）。
     - そうでなければ、`order = np.argsort(sig[idx])[::-1]`（信号値降順）とし、`proms = np.full(len(idx), np.nan)`（全 NaN で埋める）。
  10. `idx_sorted = idx[order][:n]`、`prom_sorted = np.asarray(proms)[order][:n]`（上位 n 件）。
  11. 各ピークを `rank`（1 始まり）付き dict にして `peaks` リストに append:
      ```python
      {
          "rank": rank,
          "index": int(i),
          "time": float(t[i]) if t is not None else None,
          "value": float(y[i]),
          "prominence": float(pr) if pr == pr else None,  # NaN 判定（pr==pr が False なら NaN）
      }
      ```
      - **辞書キーは `rank`, `index`, `time`, `value`, `prominence` の 5 つ、この順**。
      - `prominence` は `pr == pr`（NaN でない）なら `float(pr)`、NaN なら `None`。
- 戻り値: dict のリスト（最大 n 件、顕著さ/値の降順）。

### 5. `_zero_crossing_period(t, y)`

- docstring: `平均を引いた信号の上昇ゼロ交差から周期[s]を推定する。`
- 処理:
  1. `t = np.asarray(t, dtype=float)`、`yv = np.asarray(y, dtype=float)`。
  2. `np.isfinite(yv).sum() < 3` なら `None`。
  3. `y0 = yv - np.nanmean(yv)`（直流成分除去）。
  4. `sign = np.signbit(y0)`（`True`=負）。**上昇ゼロ交差のみ**を取る: `cross = np.where(np.diff(sign.astype(np.int8)) == -1)[0]`（符号ビットが `True`(負)→`False`(非負) に変わる位置、すなわち負→非負の立上り交差だけ）。
  5. `cross.size < 2` なら `None`（周期を 1 つ測るには上昇交差が 2 個以上必要）。
  6. 交差点での**線形補間をベクトル化**して交差時刻 `tc` を求める:
     - `i = cross`、`y1, y2 = y0[i], y0[i + 1]`。
     - `mask = y2 != y1`（タイ点 `y2==y1` を除外）。`i, y1, y2 = i[mask], y1[mask], y2[mask]`。
     - `tc = t[i] + (-y1) * (t[i + 1] - t[i]) / (y2 - y1)`。
  7. `tc.size < 2` なら `None`。
  8. `per = np.diff(tc)`、`per = per[per > 0]`（連続する上昇交差の間隔＝1 周期。正のもののみ）。`per.size == 0` なら `None`。
  9. `period = float(np.median(per))`（上昇→上昇間隔の中央値）。
  10. `period > 0` なら `period`、そうでなければ `None`。
- 戻り値: `float`（秒）または `None`。
- エッジケース注意: 隣接交差が同値（`y2==y1`）の点は除外。**上昇ゼロ交差（負→非負）だけ**を集め、連続する上昇交差の間隔をそのまま 1 周期として扱う（`np.diff(tc)` が上昇→上昇の間隔＝1 周期）。立上り・立下りの両交差を混ぜて「半周期 ×2」とする設計ではない: デューティ比が 50% でない波形（PWM/パルス等）では上昇間隔と下降間隔が交互に並び、半周期の中央値 ×2 が真の周期からずれてしまうためである。上昇交差のみなら任意のデューティ比で正しく 1 周期が得られる。

### 6. `_edge_time(t, y, rising=True, lo=0.1, hi=0.9)`

- docstring（**そのまま使用**）:
```
最初の立上り（または立下り）エッジの 10%-90% 遷移時間を返す。

0%/100% の基準は実機オシロ標準どおりヒストグラム法の Top/Base（settledした
高/低レベル）を用い、過渡（オーバーシュート/リンギング）に影響されにくくする。
ヒストグラムで決められない場合は 5%/95% パーセンタイルにフォールバック。
10%・90% の交差は「同じエッジ上」で対応付ける（周期信号でも正しく、
立下りも常に算出できる）。
```
- 処理:
  1. `t = np.asarray(t, dtype=float)`、`y = np.asarray(y, dtype=float)`。
  2. `np.isfinite(y).sum() < 3` なら `None`。
  3. `top, base = histogram_top_base(y)`（後述）で 100%/0% 基準を取得。
  4. **フォールバック判定**: `top is None or base is None or not np.isfinite(top - base) or (top - base) <= 0` のいずれかなら:
     - `base = np.nanpercentile(y, 5)`、`top = np.nanpercentile(y, 95)`。
  5. `span = top - base`。`not np.isfinite(span) or span <= 0` なら `None`。
  6. `y_lo = base + lo * span`、`y_hi = base + hi * span`（既定 lo=0.1, hi=0.9 → 10%/90%）。
  7. まず両端 NaN を弾くためのマスク `fin = np.isfinite(y)` を作る（NaN は「下」「上」どちらの状態でもないものとして扱い、偽の交差を防ぐ）。続いてローカル関数 2 つを定義:
     - `up_cross(level)`: `below = y < level; return np.where(below[:-1] & ~below[1:] & fin[:-1] & fin[1:])[0]`（下→上に横切る位置。交差の両端サンプルがともに有限のときだけ採用）。
     - `down_cross(level)`: `above = y > level; return np.where(above[:-1] & ~above[1:] & fin[:-1] & fin[1:])[0]`（上→下に横切る位置。同じく両端が有限のときのみ）。
     - **両端の `fin` チェックが必要な理由**: `y < level` / `y > level` は NaN に対し常に `False` を返す。`below`（下にいる）状態では NaN は `False`＝「下にいない」に化け、`above`（上にいる）状態でも NaN は `False`＝「上にいない」に化ける。つまり NaN は反対の状態として現れ、それ単体で `below[:-1] & ~below[1:]` の境界条件を満たす偽の交差点を作ってしまう。比較が `False` になる性質だけでは NaN を除外できないため、交差候補の両端サンプルが有限（`fin[:-1] & fin[1:]`）であることを明示的に要求する。
  8. **rising=True** の場合:
     - `lo_idx = up_cross(y_lo)`。`lo_idx.size == 0` なら `None`。
     - `i_lo = int(lo_idx[0])`（最初の 10% 上昇交差）。
     - `after = up_cross(y_hi)`、`after = after[after > i_lo]`（同じ立上り上で 90% に到達する点）。
     - `after.size == 0` なら `None`。`return float(t[int(after[0])] - t[i_lo])`。
  9. **rising=False**（立下り）の場合:
     - `hi_idx = down_cross(y_hi)`。`hi_idx.size == 0` なら `None`。
     - `i_hi = int(hi_idx[0])`（最初の 90% 下降交差）。
     - `after = down_cross(y_lo)`、`after = after[after > i_hi]`（同じ立下り上で 10% に到達する点）。
     - `after.size == 0` なら `None`。`return float(t[int(after[0])] - t[i_hi])`。
- 戻り値: 遷移時間 `float`（秒）または `None`。

### 7. `_window(name, n)`

- docstring なし。窓関数配列を返す。
- 処理:
  1. `name = (name or "hann").lower()`。
  2. 名前ごとに分岐（**以下の対応表を厳守**）:

| `name`（小文字化後） | 返す配列 | フォールバック（scipy 無し or 例外時） |
|---|---|---|
| `"hamming"` | `np.hamming(n)` | — |
| `"blackman"` | `np.blackman(n)` | — |
| `"blackmanharris"` / `"blackman-harris"` / `"bharris"` | `scipy.signal.windows.blackmanharris(n)` | `np.blackman(n)` |
| `"flattop"` | `scipy.signal.windows.flattop(n)` | `np.hanning(n)` |
| `"kaiser"` | `np.kaiser(n, 14.0)`（β=14 ≈ -100dB サイドローブ） | — |
| `"gaussian"` | `scipy.signal.windows.gaussian(n, std=n / 6.0)` | `np.hanning(n)` |
| `"none"` / `"rect"` / `"rectangular"` | `np.ones(n)` | — |
| 上記以外（既定） | `np.hanning(n)` | — |

  - scipy 系（blackmanharris/flattop/gaussian）は各分岐内で `try: from scipy.signal.windows import ...` し、`except Exception:` で上表のフォールバックへ。
  - **`"hann"` は明示分岐が無く、末尾の `return np.hanning(n)` に落ちる**（つまり既定も Hann）。
  - コメント: kaiser 行に `# β=14 ≈ -100dB サイドローブ`、gaussian の std は `n / 6.0`。
- 戻り値: 長さ `n` の窓配列。

### 8. `to_db(amp, ref=1.0, floor_db=-200.0)`

- docstring: `振幅を dB（20·log10(amp/ref)）に変換。0 は floor_db に。`
- 処理:
  1. `amp = np.asarray(amp, dtype=float)`。
  2. `out = np.full(amp.shape, floor_db)`（全要素を floor_db で初期化）。
  3. `nz = amp > 0`（正の要素のみ）。
  4. `out[nz] = 20.0 * np.log10(amp[nz] / ref)`。
  5. `return np.maximum(out, floor_db)`（floor_db で下限クリップ）。
- 戻り値: dB 値の `np.ndarray`。
- 注意: 0 や負の振幅は `floor_db`（既定 -200.0 dB）になる。係数は **20**（振幅 dB）。

### 9. `histogram_top_base(y, bins=256)`

- docstring: `ヒストグラム法で Top(上位の最頻値)・Base(下位の最頻値) を求める。`
- 処理:
  1. `y = np.asarray(y, dtype=float)`、`y = y[np.isfinite(y)]`（有限値のみ残す）。
  2. `y.size < 4` なら `(None, None)`。
  3. `vmin, vmax = float(y.min()), float(y.max())`。
  4. `vmax <= vmin` なら `(vmin, vmin)`（定数信号）。
  5. `hist, edges = np.histogram(y, bins=bins)`（既定 bins=256）。
  6. `centers = (edges[:-1] + edges[1:]) / 2.0`（ビン中心）。
  7. `mid = (vmin + vmax) / 2.0`（中央値しきい）。
  8. `up, lo = centers >= mid, centers < mid`（上半分・下半分のマスク）。
  9. `top`: 上半分にヒストグラム値があれば `float(centers[up][np.argmax(hist[up])])`、無ければ `vmax`。
  10. `base`: 下半分にヒストグラム値があれば `float(centers[lo][np.argmax(hist[lo])])`、無ければ `vmin`。
  11. `return top, base`。
- 戻り値: `(top, base)` のタプル。データ不足時は `(None, None)`。
- 注意: 「最頻値」は上半分/下半分それぞれで最大度数のビン中心。`.any()` で空ガード。

### 10. `_mid_crossings(t, y, level)`

- docstring: `level を上下に横切る位置（上昇・下降）を返す。`
- 処理:
  1. `below = y < level`。
  2. `up = np.where(below[:-1] & ~below[1:])[0]`（下→上の上昇交差）。
  3. `down = np.where(~below[:-1] & below[1:])[0]`（上→下の下降交差）。
  4. `return up, down`。
- 戻り値: `(up, down)` のインデックス配列タプル。
- 注意: `t` は受け取るが**本実装では未使用**（シグネチャ互換のため残す）。

---

## 再現に必須の細部・エッジケース

- **scipy ガード**: トップレベルでは scipy を import しない。`_HAVE_SCIPY` で有無判定し、各関数内で必要時のみ遅延 import。例外時は必ず numpy フォールバックへ（`smooth_signal`, `find_signal_peaks`, `_window` の各分岐）。
- **NaN の扱い**:
  - `find_signal_peaks` の `span` は `np.nanmax/np.nanmin`。`prominence` の NaN 判定は `pr == pr`（NaN なら False → `None`）。
  - `_zero_crossing_period`/`_edge_time`/`histogram_top_base` は有限値カウントや `np.isfinite` で NaN をガード。`_edge_time` の `up_cross`/`down_cross` では、比較 `y < level` / `y > level` が NaN に対し常に False になる性質「だけ」では NaN を除外できない（NaN が反対の状態として現れ偽の交差を作る）ため、`fin = np.isfinite(y)` を作り交差候補の両端が有限のとき（`fin[:-1] & fin[1:]`）だけ交差と認める。
- **窓長の奇数化**: `smooth_signal` は偶数窓を +1 して奇数に。
- **`_simple_peaks` の非対称比較**: 左は `>`、右は `>=`（フラット頂点で左端を拾う）。
- **`_window` の `"hann"`**: 明示分岐なしで末尾 `np.hanning(n)` に落ちる設計。`(name or "hann")` で `None`/空文字も Hann になる。
- **`_trapz` は未使用でも定義必須**（他モジュールからの参照互換）。
- **戻り値の型**: 周期/時間/レート系は明示的に `float(...)` でスカラ化し、無効時は `None` を返す（呼び出し側が `None` ガードを前提）。
- **辞書キー名の厳守**: ピーク dict は `rank/index/time/value/prominence`（5 キー）。
- 本ファイルは Qt6 列挙・Mixin 規約・facade・monospace・grid linewidth=None などの GUI 落とし穴とは**無関係**（GUI 非依存のため）。ただし**Qt/matplotlib を import してはならない**点だけは厳守（spawn 安全・起動軽量化のため）。

---

## 実装上の注意（落とし穴まとめ）

- scipy を**遅延 import** にすること。トップレベル import すると scipy 未インストール環境で起動不能になる。
- `find_peaks` の `prominence`/`distance` は**真のとき（None/0 でないとき）だけ** kwargs に入れる（None を渡すと scipy がエラー/不正動作）。
- `_zero_crossing_period` でタイ点（`y2==y1`）をマスク除外しないとゼロ除算する。
- `to_db` で 0/負値を `np.log10` に渡さないよう `nz = amp > 0` でマスクすること。
- `histogram_top_base` は `y.size < 4` と `vmax <= vmin` の早期 return を必ず入れる。
