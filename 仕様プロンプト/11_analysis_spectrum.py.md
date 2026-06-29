# [11/30] analysis_spectrum.py の仕様

## 指示

- この仕様だけを読んで `analysis_spectrum.py` を**完全な形**で実装し、ファイル全体を出力してください。
- `pass` でのお茶濁し・`TODO`・省略・「以下同様」等の要約は**禁止**です。すべての関数を実体まで書き切ってください。
- 出力が長くて途中で切れた場合は、ユーザーが「続き」と言うので、続きを最後まで（モジュール末尾まで）出力してください。

### アプリ全体の前提（本ファイル関連分のみ）

- Python 3.10+。本ファイルは純粋な数値解析モジュールで、**GUI/Qt は一切 import しない**（spawn 安全・バッチ描画安全）。
- `scipy` は**遅延 import ＋ numpy フォールバック**。scipy が無くても `import` 時にエラーにならず、scipy 必須の関数だけが `None` 等を返す。
- 数値演算は `numpy` のみが常時依存。NaN を含むデータでも落ちないようガードを入れる。

---

## ファイルの役割 / 責務

スペクトル系の解析関数群を提供するモジュール。先頭 docstring（モジュール docstring）は次の通り：

```
"""スペクトル系（FFT・スペクトルピーク・THD/SNR/SINAD/ENOB/SFDR・STFT）。"""
```

提供機能：片側 FFT 振幅スペクトル、支配的（基本波）周波数推定、スペクトルピーク検出、オーディオ系メトリクス（THD/SNR/SINAD/ENOB/SFDR）、スペクトログラム（STFT）、帯域電力、占有帯域幅、高調波探索。

ファイル先頭行は `# -*- coding: utf-8 -*-`（エンコーディング宣言）を置く。

---

## 依存（import するもの）

```python
# -*- coding: utf-8 -*-
"""スペクトル系（FFT・スペクトルピーク・THD/SNR/SINAD/ENOB/SFDR・STFT）。"""
import numpy as np

from analysis_common import sampling_rate, find_signal_peaks, _window
```

- `numpy as np`：常時依存。
- `analysis_common` から 3 つを import：
  - `sampling_rate(t)`：時間軸 `t[s]` から平均サンプリング周波数[Hz]を返す。`t.size < 2` で `None`、`dt = np.median(np.diff(t))` を用い `dt > 0` のとき `1.0 / dt`、それ以外 `None`。
  - `find_signal_peaks(y, t=None, n=5, prominence_frac=0.05, distance=None, mode="max", smooth=0)`：信号の主要ピークを上位 `n` 個、`prominence` 順に返す。返り値は dict のリストで各 dict は `{"rank", "index", "time", "value", "prominence"}` を持つ（`t` を渡すとその値が `"time"` に入る、渡さなければインデックス値）。
  - `_window(name, n)`：窓関数の `np.ndarray`（長さ `n`）を返すヘルパ。`hamming/blackman/blackmanharris/flattop/hann`（既定 hann）等。scipy 窓は遅延 import＋numpy フォールバック。
- **scipy は本ファイル冒頭では import しない。** `spectrogram` 関数内でのみ `from scipy.signal import spectrogram as _spec` を遅延 import し、失敗時は `None` 系を返す。

---

## 公開 API（完全シグネチャと挙動）

すべてモジュールトップレベルの関数。クラスは無い。以下の順序で定義すること。

---

### 1. `def fft_spectrum(t, y, window="hann", detrend=True):`

片側振幅スペクトル `(freqs[Hz], amplitude)` のタプルを返す。一様サンプリングを仮定し時間軸から `fs` を推定する。

docstring：
```
"""片側振幅スペクトル (freqs[Hz], amplitude) を返す。

一様サンプリングを仮定し、時間軸からサンプリング周波数を推定する。
"""
```

アルゴリズム：
1. `t = np.asarray(t, dtype=float)`、`y = np.asarray(y, dtype=float)`。
2. `n = y.size`。`n < 4` なら `return None, None`。
3. `fs = sampling_rate(t)`。`if not fs:` なら `return None, None`（`fs` が `None` または 0 の両方をガード）。
4. `yw = y - np.mean(y) if detrend else y.copy()`（detrend=True で平均除去、False でもコピーを取り元配列を破壊しない）。
5. `w = _window(window, n)`、`yw = yw * w`。
6. `spec = np.fft.rfft(yw)`、`freqs = np.fft.rfftfreq(n, d=1.0 / fs)`。
7. 単側振幅を**窓のコヒーレントゲイン**で正規化：`amp = np.abs(spec) / (np.sum(w) / 2.0)`。
8. **DC とナイキストの半減**：`np.sum(w) / 2.0` での正規化は負側の共役対をたたみ込んだ片側化（実質 ×2）を含むが、DC ビン（`amp[0]`）と、`n` が偶数のときの末尾＝ナイキストビン（`amp[-1]`）には対になる負側成分が存在しない。そのまま ×2 すると 2 倍に過大評価されるため、これらだけ半分に戻す：
   ```python
   if amp.size:
       amp[0] *= 0.5
       if n % 2 == 0:
           amp[-1] *= 0.5
   ```
   （`n` が奇数のときは rfft の末尾はナイキストに達しないので末尾の補正は行わない。）
9. `return freqs, amp`。

戻り値の形：成功時 `(freqs: np.ndarray, amp: np.ndarray)`。失敗時 `(None, None)`。

---

### 2. `def dominant_frequency(t, y):`

FFT で最大振幅の周波数[Hz]を返す（基本周波数の推定）。

docstring：`"""FFT で最大振幅の周波数[Hz]を返す（基本周波数の推定）。"""`

アルゴリズム：
1. `freqs, mag = fft_spectrum(t, y)`。
2. `if freqs is None or len(freqs) < 2:` → `return None`。
3. `m = mag[1:]`（DC を除く）。
4. `if m.size == 0 or not np.isfinite(m).any():` → `return None`（全 NaN スペクトルのガード）。
5. `if np.nanmax(m) <= 0:` → `return None`（平坦・定数の信号では周波数を返さない）。
6. `return float(freqs[int(np.nanargmax(m)) + 1])`（DC を除いた分の `+1` オフセットを必ず付ける）。

戻り値：`float` または `None`。

---

### 3. `def find_spectral_peaks(t, y, n=5, prominence_frac=0.02):`

FFT スペクトルの主要ピーク（基本波・高調波など）を上位 `n` 個返す。

docstring：
```
"""FFT スペクトルの主要ピーク（基本波・高調波など）を上位 n 個返す。

Returns: list of dict {rank, frequency, amplitude}
"""
```

アルゴリズム：
1. `freqs, amp = fft_spectrum(t, y)`。
2. `if freqs is None:` → `return []`。
3. `peaks = find_signal_peaks(amp[1:], t=freqs[1:], n=n, prominence_frac=prominence_frac, mode="max")`
   - DC ビンを除いた振幅 `amp[1:]` をピーク検出対象に、`freqs[1:]` を `t=` に渡して周波数値を `"time"` フィールドへ載せる。
4. 各 `p` を辞書化して `out` に追加：
   - `"rank": p["rank"]`
   - `"frequency": p["time"]`（コメント：`find_signal_peaks` の `time` に `freqs` を入れたため）
   - `"amplitude": p["value"]`
5. `return out`。

戻り値：dict のリスト（キーは厳密に `rank`, `frequency`, `amplitude` の順）。空なら `[]`。

---

### 4. `def spectrum_metrics(t, y, n_harm=6, window="hann", half_bins=3):`

THD / SNR / SINAD / ENOB / SFDR と基本波周波数を返す。各成分はリーク対策として基本波・各高調波バンドのパワーを近傍ビンで合算する。

docstring：
```
"""THD / SNR / SINAD / ENOB / SFDR と基本波周波数を返す。

各成分はリーク対策として基本波・各高調波バンドのパワーを近傍ビンで合算する。
"""
```

アルゴリズム（精密に再現すること）：
1. `t`, `y` を `np.asarray(..., dtype=float)`。`n = y.size`。
2. `if n < 16:` → `return {}`（最小サンプル数ガード。FFT より厳しめ）。
3. `fs = sampling_rate(t)`。`if not fs:` → `return {}`。
4. `w = _window(window, n)`、`yw = (y - np.mean(y)) * w`（必ず平均除去）。
5. `spec = np.fft.rfft(yw)`、`power = (np.abs(spec) ** 2)`（パワースペクトル）。
6. `if power.size < 4 or not np.isfinite(power).any():` → `return {}`。
7. 基本波ビン：`k0 = int(np.argmax(power[1:]) + 1)`（DC 除外の `+1` オフセット）。`f0 = k0 * fs / n`。
8. 近傍ビン合算用の内部関数を定義：
   ```python
   def band(kc):
       a = max(1, kc - half_bins)
       b = min(power.size, kc + half_bins + 1)
       return a, b
   ```
   （下限は最低でも 1＝DC を含めない、上限は `power.size` でクリップ。返すのは Python の `[a:b)` スライス用の半開区間。）
9. 基本波バンド：`fa, fb = band(k0)`、`p_fund = float(power[fa:fb].sum())`。`if p_fund <= 0:` → `return {}`。
10. 高調波パワー合算（**重複ビン除外つき**）：基本波バンドのビン集合を `claimed = set(range(fa, fb))`、`harm_power = 0.0` で初期化。`for h in range(2, n_harm + 1):`
    - `kc = int(round(k0 * h))`
    - `if kc >= power.size - 1:` → `break`（ナイキスト超過で打ち切り）
    - `a, b = band(kc)`
    - 既に基本波／下位高調波で計上済みのビンを除外：`bins = sorted(set(range(a, b)) - claimed)`
    - `claimed |= set(range(a, b))`（今回のバンド全体を計上済みに加える）
    - `if bins: harm_power += float(power[bins].sum())`
    - **理由**：`k0` が小さい（＝短時間しか信号を捕捉できていない）と高調波バンド `±half_bins` が基本波バンドや隣の高調波バンドと重なる。素朴に毎回 `power[a:b].sum()` を足すと重なったビンを二重計上し、`harm_power` が過大になる。すると `noise_only = total - p_fund - harm_power` が負になり `1e-30` にクランプされ、`SNR = 10·log10(p_fund / noise_only)` が物理的にあり得ない巨大値に破綻する。`claimed` 集合で各ビンを高々一度しか計上しないことで、`p_fund` と `harm_power` のビン集合が必ず排他になり、二重計上を防ぐ。
11. `total = float(power[1:].sum())`（DC 除く全パワー）。
12. `noise_only = max(total - p_fund - harm_power, 1e-30)`（ノイズのみ。下限クランプで log の発散防止）。
13. `nd = max(total - p_fund, 1e-30)`（ノイズ＋歪み）。
14. 各メトリクス：
    - `thd = float(np.sqrt(harm_power / p_fund) * 100.0)`（%、振幅比×100）
    - `thd_db = float(10 * np.log10(harm_power / p_fund)) if harm_power > 0 else None`
    - `snr = float(10 * np.log10(p_fund / noise_only))`
    - `sinad = float(10 * np.log10(p_fund / nd))`
    - `enob = float((sinad - 1.76) / 6.02)`（理想 ADC の ENOB 公式。係数 `1.76` と `6.02` を厳密に使う）
15. SFDR（スプリアスフリーダイナミックレンジ）：
    - `spur = power.copy()`
    - `spur[0] = 0`（DC を除外）
    - `spur[fa:fb] = 0`（基本波バンドを除外。`fa:fb` は手順 9 と同じ）
    - `sfdr = float(10 * np.log10(p_fund / spur.max())) if spur.max() > 0 else None`
16. 戻り値辞書（キー名・並び順を厳密に）：
    ```python
    return {"f0": f0, "THD_pct": thd, "THD_dB": thd_db, "SNR_dB": snr,
            "SINAD_dB": sinad, "ENOB_bits": enob, "SFDR_dB": sfdr}
    ```

戻り値：上記キーの dict。各種ガードに掛かった場合は空 dict `{}`。`THD_dB` と `SFDR_dB` は条件次第で `None` を取り得る。

> 注意：`claimed`（計上済みビン集合）は計算過程でのみ使い、戻り値には含めない。仕様再現時も戻り値辞書には入れないこと。

---

### 5. `def spectrogram(t, y, nperseg=256, window="hann"):`

STFT のスペクトログラム `(f, time, Sxx[dB])` を返す。**scipy 使用**。

docstring：`"""STFT のスペクトログラム (f, time, Sxx[dB]) を返す。scipy 使用。"""`

アルゴリズム：
1. `fs = sampling_rate(t)`。`if not fs:` → `return None, None, None`。
2. 遅延 import：
   ```python
   try:
       from scipy.signal import spectrogram as _spec
   except Exception:
       return None, None, None
   ```
   （scipy 無し環境では 3 つの `None` を返す。numpy フォールバックは無い＝STFT は scipy 必須。）
3. `y = np.asarray(y, dtype=float)`、`y = np.nan_to_num(y - np.nanmean(y))`（平均除去＋NaN を 0 に置換）。
4. `nperseg = int(min(nperseg, len(y)))`（信号長でクリップ）。`if nperseg < 16:` → `return None, None, None`。
5. STFT 実行（引数を厳密に）：
   ```python
   f, tt, Sxx = _spec(y, fs=fs, window=window, nperseg=nperseg,
                      noverlap=nperseg // 2, scaling="spectrum")
   ```
   （オーバーラップは半分、スケーリングは `"spectrum"`。）
6. `Sxx_db = 10.0 * np.log10(Sxx + 1e-20)`（dB 変換、`+1e-20` で log の発散防止）。
7. 時間軸を元データの開始時刻にオフセット：`return f, tt + (t[0] if len(t) else 0.0), Sxx_db`。

戻り値：成功時 `(f: ndarray, time: ndarray, Sxx_db: ndarray)`。失敗時は 3 つの `None`。

---

### 6. `def channel_power(t, y, f_lo=None, f_hi=None, window="hann"):`

指定帯域 `[f_lo, f_hi]` の電力（振幅²の総和）。帯域未指定なら全帯域（DC 除く）。

docstring：`"""指定帯域 [f_lo, f_hi] の電力（振幅²の総和）。帯域未指定なら全帯域（DC除く）。"""`

アルゴリズム：
1. `freqs, amp = fft_spectrum(t, y, window=window)`。
2. `if freqs is None:` → `return None`。
3. `p = np.asarray(amp, dtype=float) ** 2`。
4. `lo = freqs[1] if f_lo is None else f_lo`（未指定時の下限は `freqs[1]`＝DC を除く最初のビン）。
5. `hi = freqs[-1] if f_hi is None else f_hi`（未指定時の上限はナイキスト＝最終ビン）。
6. `band = (freqs >= lo) & (freqs <= hi)`（両端含むブール mask）。
7. `return float(p[band].sum())`。

戻り値：`float` または `None`。

---

### 7. `def occupied_bandwidth(t, y, frac=0.99, window="hann"):`

全電力の `frac`（既定 99%）が収まる占有帯域幅[Hz]。DC は除く。

docstring：`"""全電力の frac（既定99%）が収まる占有帯域幅[Hz]。DC は除く。"""`

アルゴリズム：
1. `freqs, amp = fft_spectrum(t, y, window=window)`。
2. `if freqs is None or freqs.size < 3:` → `return None`。
3. `p = np.asarray(amp, dtype=float) ** 2`、`p[0] = 0.0`（DC 除外）。
4. `tot = p.sum()`。`if tot <= 0:` → `return None`。
5. `c = np.cumsum(p) / tot`（累積電力の正規化）。
6. 両側 `(1 - frac)/2` ずつを切り落とした境界インデックスを `searchsorted` で求める：
   - `lo_i = int(np.searchsorted(c, (1.0 - frac) / 2.0))`
   - `hi_i = int(np.searchsorted(c, 1.0 - (1.0 - frac) / 2.0))`
   - `hi_i = min(hi_i, freqs.size - 1)`（範囲外クリップ）。
7. `return float(freqs[hi_i] - freqs[lo_i])`。

戻り値：占有帯域幅 `float`[Hz] または `None`。

---

### 8. `def harmonic_search(t, y, n_harm=5, window="hann"):`

基本波と高調波（基本波の整数倍に最も近いビン）の周波数・振幅を返す。

docstring：
```
"""基本波と高調波（基本波の整数倍に最も近いビン）の周波数・振幅を返す。

Returns: list of dict {harmonic, frequency, amplitude}
"""
```

アルゴリズム：
1. `freqs, amp = fft_spectrum(t, y, window=window)`。
2. `if freqs is None or freqs.size < 3:` → `return []`。
3. `k0 = int(np.argmax(amp[1:]) + 1)`（基本波ビン、DC 除く `+1`）。`f0 = float(freqs[k0])`。
4. `if f0 <= 0:` → `return []`。
5. **基本波振幅のガード**：`if not np.isfinite(amp[k0]) or amp[k0] <= 0:` → `return []`。平坦／全ゼロ／定数信号では基本波が存在せず `amp[k0]` が非有限または 0 以下になる。`dominant_frequency` と同様にここで弾き、振幅ゼロの偽の高調波行を並べない（`compute_fft_metrics` の表に矛盾行が出るのを防ぐ）。
6. `for h in range(1, n_harm + 1):`（`h=1` が基本波そのもの）
   - `k = int(np.argmin(np.abs(freqs - f0 * h)))`（`f0*h` に最も近い周波数ビン）
   - `out.append({"harmonic": h, "frequency": float(freqs[k]), "amplitude": float(amp[k])})`
7. `return out`。

戻り値：dict のリスト（キー順 `harmonic`, `frequency`, `amplitude`）。空なら `[]`。

---

## 再現に必須の細部・エッジケース

- **DC 除去の `+1` オフセット**：`argmax`/`argmin`/`nanargmax` を `power[1:]` や `mag[1:]` に適用したら、必ず `+1` して元配列のインデックスに戻す。`dominant_frequency`・`spectrum_metrics`・`harmonic_search` の全てで一貫させる。
- **`if not fs:` ガード**：`sampling_rate` は `None` か正の値を返す設計だが、`if not fs:` で `None` も 0 もまとめて弾く。`fs is None` と書かないこと。
- **detrend のコピー安全性**：`fft_spectrum` の `detrend=False` 時も `y.copy()` を取り、その後 `yw = yw * w` で元の `y` を破壊しない。
- **窓のコヒーレントゲイン正規化**：振幅は `np.sum(w) / 2.0` で割る（`fft_spectrum`）。これが片側振幅の正規化係数。ただし DC（`amp[0]`）と、`n` 偶数時のナイキスト（`amp[-1]`）は負側共役対が無く片側化の ×2 が掛からないため、それぞれ `*= 0.5` で半減する。
- **パワー vs 振幅**：`fft_spectrum` は**振幅**（`np.abs`）。`spectrum_metrics` は内部で別途 `power = np.abs(spec)**2`（窓正規化なし、相対比でしか使わないため）。`channel_power`/`occupied_bandwidth` は `fft_spectrum` の振幅を二乗してパワー化。
- **log 発散ガード**：`spectrum_metrics` の `noise_only`/`nd` は `max(..., 1e-30)`、`spectrogram` の dB は `Sxx + 1e-20`。これらの定数値を厳密に使う。
- **`spectrum_metrics` の最小サンプル数は 16**（`fft_spectrum` の 4 とは異なる）。`spectrogram` の `nperseg` 下限も 16。
- **高調波ループの打ち切り**：`spectrum_metrics` は `kc >= power.size - 1` で `break`、`harmonic_search` は `np.argmin` で常に範囲内ビンに丸める（打ち切らない）。両者の挙動差に注意。
- **高調波バンドの重複ビン除外**：`spectrum_metrics` は `claimed` 集合で既計上ビンを除外し、`p_fund` と `harm_power` が排他なビン集合になるよう合算する。小さい `k0` でバンドが重なっても二重計上せず、`noise_only` が負になって `SNR` が破綻するのを防ぐ。
- **`harmonic_search` の基本波振幅ガード**：`f0 <= 0` に加え、`not np.isfinite(amp[k0]) or amp[k0] <= 0` でも `[]` を返す。平坦／全ゼロ／定数信号で振幅ゼロの偽の高調波行を出さない（`dominant_frequency` のガードと同趣旨）。
- **NaN 対策**：`dominant_frequency` は `np.isfinite(m).any()` と `np.nanmax`/`np.nanargmax` を使う。`spectrogram` は `np.nan_to_num`。
- **`occupied_bandwidth` の対称トリム**：左右それぞれ `(1-frac)/2` を捨てるので、両側合わせて `1-frac`（既定 1%）が帯域外。
- **戻り値辞書のキー名・並び順は厳密に固定**（呼び出し側 GUI が文字列キーで参照するため）。特に `spectrum_metrics` のキー：`f0`, `THD_pct`, `THD_dB`, `SNR_dB`, `SINAD_dB`, `ENOB_bits`, `SFDR_dB`。
- **ENOB 係数**：`(sinad - 1.76) / 6.02` を厳密に。

---

## 数値定数の一覧（仕様データ・厳密値）

| 箇所 | 定数 | 意味 |
|---|---|---|
| `fft_spectrum` 最小サンプル | `4` | これ未満で `(None, None)` |
| `fft_spectrum` 正規化 | `np.sum(w) / 2.0` | 片側振幅のコヒーレントゲイン |
| `fft_spectrum` DC/ナイキスト | `amp[0]*=0.5`、`n` 偶数で `amp[-1]*=0.5` | 片側化の ×2 を打ち消し半減 |
| `find_spectral_peaks` 既定 | `n=5`, `prominence_frac=0.02` | |
| `spectrum_metrics` 既定 | `n_harm=6`, `window="hann"`, `half_bins=3` | |
| `spectrum_metrics` 最小サンプル | `16` | |
| `spectrum_metrics` THD% | `np.sqrt(harm_power / p_fund) * 100.0` | |
| `spectrum_metrics` ENOB | `(sinad - 1.76) / 6.02` | |
| `spectrum_metrics` クランプ | `1e-30` | noise_only / nd の下限 |
| `spectrogram` 既定 | `nperseg=256`, `window="hann"` | |
| `spectrogram` noverlap | `nperseg // 2` | |
| `spectrogram` scaling | `"spectrum"` | scipy 引数 |
| `spectrogram` dBガード | `+1e-20`、係数 `10.0` | |
| `spectrogram` 最小 nperseg | `16` | |
| `occupied_bandwidth` 既定 | `frac=0.99` | |
| `harmonic_search` 既定 | `n_harm=5`, `window="hann"` | |

---

## 落とし穴・規約（本ファイル該当分）

- **Qt を import しない**：本ファイルは解析専用で `batch_render`/`spawn` 経路からも読まれ得る。`matplotlib`/`PySide6`/Qt の import を絶対に入れない。
- **facade 規約**：本ファイルの公開関数は `analysis.py`（facade）が `import *` ＋アンダースコア名の明示 import で再公開する想定。公開名（上記関数名）を変えないこと。アンダースコア始まりの内部名はここには無いが、import している `_window` を**再エクスポートしない**（先頭アンダースコアなので `import *` には載らない＝そのままで良い）。
- **scipy 遅延 import**：`spectrogram` 内のみで `try/except Exception` 付き。モジュールトップで scipy を import しない（起動を軽くし、無環境でも壊さない）。
- **`_window` は `analysis_common` から import**：自前で窓関数を定義し直さない。
- **monospace 回避・grid linewidth=None 回避**：本ファイルは描画コードを含まないため直接は無関係だが、解析結果を描画する側でこれらの規約が効く。本ファイルでは matplotlib に一切触れない。
- **`numpy` だけで完結**：`scipy` が無くても `fft_spectrum`/`dominant_frequency`/`find_spectral_peaks`/`spectrum_metrics`/`channel_power`/`occupied_bandwidth`/`harmonic_search` は全て動く（`find_signal_peaks` 側が scipy フォールバックを持つ）。`spectrogram` だけが scipy 必須。
