# [14/30] advanced.py の仕様

## 指示

- この仕様**だけ**を読んで、`advanced.py` を**完全な形**で実装し、ソースコードとして出力してください。
- `pass`・`TODO`・「省略」・「要約」・「以下同様」・ダミー実装は**禁止**です。全関数の本体を完全に書き切ってください。
- 出力が途中で切れた場合は、続けて「続き」と入力されたら**最後まで**残りを出力してください。
- このファイルは GUI を含みません（純粋な数値処理・解析モジュール）。ただしアプリ全体の前提として、本プロジェクトは Python 3.10+ / GUI=PySide6(Qt6) 上で動作し、Qt は必ず matplotlib 経由（`from matplotlib.backends.qt_compat import QtCore, QtGui, QtWidgets`）で取得します。本ファイル自体は Qt を import しません。
- `scipy` は使いません（このファイルは `numpy` のみに依存）。`analysis` モジュールの関数を 1 つだけ利用します。

---

## 1. ファイルの役割 / 責務

モジュール docstring（先頭の三重引用符文字列）は次の趣旨をそのまま記載すること:

```
"""高度解析：マスク/リミット合否、アイダイアグラム、ジッタ、シリアルプロトコル解読。

ハイエンドオシロ相当の解析機能を後処理で提供する。プロトコル解読は
UART（1線）、I2C（SCL/SDA）、SPI（SCK/MOSI[/CS]）に対応。
"""
```

責務:
- **マスク試験**（上限/下限超過の合否判定）
- **アイダイアグラム**生成と、構造化アイ測定（アイ振幅/高さ、Q factor、消光比、S/N、ジッタ、アイ幅）
- **ジッタ解析**（しきい値交差からの TIE / RMS / pp）
- **シリアルプロトコル解読**：UART（1線）、I2C（SCL/SDA）、SPI（SCK/MOSI[/CS]）
- 共通のヘルパ：自動しきい値、ロジック化、レベル交差検出、時刻におけるレベル取得

すべて後処理（取得済み波形配列に対する解析）として実装する。リアルタイム処理や Qt 連携はしない。

---

## 2. 依存（import するもの）

ファイル冒頭の import は次の 2 つのみ（この順序・形式）:

```python
import numpy as np

import analysis
```

- `numpy` は `np` として使用。
- `analysis` モジュールから `analysis.histogram_top_base(y)` を使用する（トップ/ベースのヒストグラムレベル推定）。これは `(top, base)` のタプルを返し、推定不能時は `top is None` となる想定。
- Qt / matplotlib / scipy は **import しない**。

---

## 3. 公開API（全関数・完全シグネチャ）

関数はファイル内で以下の順序・セクションコメント付きで定義する。セクション区切りコメントは次の形（行頭から `# ` のあとにダッシュ65個＋空白＋見出し）:

- `# ----------------------------------------------------------------- 共通`
- `# ----------------------------------------------------------------- マスク試験`
- `# ----------------------------------------------------------------- アイダイアグラム`
- `# ----------------------------------------------------------------- ジッタ`
- `# ----------------------------------------------------------------- UART`
- `# ----------------------------------------------------------------- I2C`
- `# ----------------------------------------------------------------- SPI`

### 3.1 共通

#### `def auto_threshold(y):`
- 役割: 波形の自動しきい値（中央レベル）を返す。
- アルゴリズム:
  1. `top, base = analysis.histogram_top_base(y)`
  2. `top is None` のとき（推定不能）→ `float(np.nanmean(y))` を返す（NaN を無視した平均）。
  3. それ以外 → `(top + base) / 2.0` を返す。
- 戻り値: `float`。

#### `def _logic(y, threshold):`
- docstring: `"""しきい値で 0/1 のロジック列に変換。"""`
- 役割: しきい値超過を 1、以下を 0 とする `int8` 配列に変換。
- 実装: `return (np.asarray(y, dtype=float) > threshold).astype(np.int8)`
- 注意: 厳密に `>`（しきい値ちょうどは 0）。戻り値 dtype は `np.int8`。

#### `def crossings(t, y, level, edge="both"):`
- docstring: `"""level を横切る時刻（線形補間）を返す。edge: rising/falling/both。"""`
- 役割: 波形が `level` を横切る時刻を、隣接 2 サンプル間の**線形補間**で求めて返す。
- アルゴリズム:
  1. `t`, `y` を `float` 配列化。
  2. `below = y < level`（`level` 未満を True）。
  3. 立上り交差インデックス `up = np.where(below[:-1] & ~below[1:])[0]`（前が below、次が below でない）。
  4. 立下り交差インデックス `dn = np.where(~below[:-1] & below[1:])[0]`。
  5. 内部関数 `interp(idx)`:
     - `idx` を `int` 配列化。`idx.size == 0` なら `np.asarray([], dtype=float)` を返す。
     - `y1, y2 = y[idx], y[idx + 1]`、`denom = y2 - y1`。
     - `frac = np.where(denom != 0.0, (level - y1) / np.where(denom != 0.0, denom, 1.0), 0.0)`
       （ゼロ除算回避：分母 0 の箇所は分母を 1 に置換しつつ最終的に frac=0 にする二重ガード）。
     - `return t[idx] + frac * (t[idx + 1] - t[idx])`。
  6. `edge == "rising"` → `interp(up)`。
  7. `edge == "falling"` → `interp(dn)`。
  8. それ以外（`"both"` 含む）→ `np.sort(np.concatenate([interp(up), interp(dn)]))`（昇順に結合ソート）。
- 戻り値: `float` の numpy 配列（交差時刻）。

#### `def _level_at(t, logic, time):`
- 役割: 指定時刻 `time` における `logic` 配列の値（0/1 等）を返す。
- 実装:
  1. `i = int(np.searchsorted(t, time))`（`time` を挿入すべき位置）。
  2. `i = min(max(i, 0), len(logic) - 1)`（範囲クランプ）。
  3. `return int(logic[i])`。

### 3.2 マスク試験

#### `def mask_test(t, y, upper=None, lower=None):`
- docstring: `"""上限/下限を超えたサンプルを検出して合否を返す。"""`
- アルゴリズム:
  1. `t`, `y` を `float` 配列化。
  2. `viol = np.zeros(y.shape, dtype=bool)`。
  3. `upper is not None` のとき `viol |= y > upper`。
  4. `lower is not None` のとき `viol |= y < lower`。
  5. `n = int(viol.sum())`。
- 戻り値（辞書、キー名厳守）:
  ```python
  {"passed": n == 0, "violations": n, "mask": viol, "violation_times": t[viol]}
  ```
  - `"passed"`: `bool`（違反 0 で True）
  - `"violations"`: 違反サンプル数 `int`
  - `"mask"`: 違反位置の bool 配列
  - `"violation_times"`: 違反した時刻配列 `t[viol]`

### 3.3 アイダイアグラム

#### `def eye_diagram(t, y, symbol_period, n_ui=2):`
- docstring: `"""シンボル周期で折り返した (phase, y) を返す（重ね描きでアイになる）。"""`
- アルゴリズム:
  1. `t`, `y` を `float` 配列化。
  2. `symbol_period <= 0` のとき `return None, None`（早期リターン、タプル）。
  3. `span = n_ui * symbol_period`。
  4. `phase = ((t - t[0]) % span)`（先頭時刻基準で `span` の剰余）。
  5. `return phase, y`。
- 戻り値: `(phase, y)` の 2 値タプル。各 numpy 配列。

#### `def eye_measurements(t, y, symbol_period):`
- docstring（趣旨をそのまま）:
  ```
  """構造化アイ測定。symbol_period[s]=1UI。

  アイ中央のサンプルから上下レベル(μ1,σ1 / μ0,σ0)を推定し、
  eye amplitude/height、Q factor、消光比(ER)、S/N、クロス点ジッタ、アイ幅を返す。
  Returns dict（計算不能な項目は欠落）。
  """
  ```
- アルゴリズム:
  1. `t`, `y` を `float` 配列化。`ui = float(symbol_period)`。
  2. `ui <= 0 or t.size < 8` なら `return {}`。
  3. `phase = ((t - t[0]) % ui) / ui`（0..1 に正規化、1UI 単位）。
  4. アイ中央サンプル選別: `center = (np.abs(phase - 0.5) < 0.06) & np.isfinite(y)`（位相 0.5±0.06、かつ有限値）。
  5. `yc = y[center]`。`yc.size < 8` なら `return {}`。
  6. `mid = (np.nanmax(y) + np.nanmin(y)) / 2.0`（中央レベル）。
  7. `hi = yc[yc >= mid]`、`lo = yc[yc < mid]`。`hi.size < 2 or lo.size < 2` なら `return {}`。
  8. `mu1, s1 = float(hi.mean()), float(hi.std())`、`mu0, s0 = float(lo.mean()), float(lo.std())`。
  9. `amp = mu1 - mu0`。
  10. 結果辞書 `out` を次の通り構築（キー名・式厳守）:
      ```python
      out = {
          "eye_amplitude": amp,
          "level1": mu1, "level0": mu0,
          "eye_height": (mu1 - 3 * s1) - (mu0 + 3 * s0),
          "q_factor": (amp / (s1 + s0)) if (s1 + s0) > 0 else None,
          "snr_db": (20 * np.log10(amp / (s1 + s0))) if (s1 + s0) > 0 and amp > 0 else None,
          "extinction_ratio_db": (10 * np.log10(mu1 / mu0)) if mu0 > 0 else None,
      }
      ```
  11. クロス点ジッタ（アイ幅）:
      - `cr = np.asarray(crossings(t, y, (mu1 + mu0) / 2.0, "both"), dtype=float)`（中央レベル交差時刻）。
      - `cr.size >= 4` のとき:
        - `cph = (cr - t[0]) % ui`（位相に折り返し）。
        - `cph = np.where(cph > ui / 2, cph - ui, cph)`（-UI/2..UI/2 に集約）。
        - `out["jitter_pp"] = float(cph.max() - cph.min())`
        - `out["jitter_rms"] = float(np.std(cph))`
        - `out["eye_width"] = float(max(ui - out["jitter_pp"], 0.0))`（負にならないようクランプ）。
  12. `return out`。
- エッジケース: サンプル不足やレベル分離不能のとき空辞書 `{}`。Q factor/SNR/ER は条件未満で `None`（キーは存在）。jitter 系キーは交差 4 点未満で**欠落**（キー自体が無い）。

### 3.4 ジッタ

#### `def jitter_tie(t, y, threshold=None, edge="rising"):`
- docstring: `"""しきい値交差から TIE（時間間隔誤差）と RMS/pp ジッタを求める。"""`
- アルゴリズム:
  1. `t`, `y` を `float` 配列化。
  2. `threshold is None` なら `threshold = auto_threshold(y)`。
  3. `cr = crossings(t, y, threshold, edge)`。
  4. `len(cr) < 3` なら `return {}`。
  5. `idx = np.arange(len(cr))`。
  6. `a, b = np.polyfit(idx, cr, 1)`（理想クロック直線フィット、`ideal = a*idx + b`）。
  7. `ideal = a * idx + b`、`tie = cr - ideal`。
- 戻り値（辞書、キー名厳守）:
  ```python
  {"tie": tie, "crossings": cr,
   "rms": float(np.std(tie)), "pp": float(tie.max() - tie.min()),
   "period": float(a), "freq": float(1.0 / a) if a else None,
   "edges": int(len(cr))}
  ```
  - `"period"`: フィット傾き `a`（理想周期）
  - `"freq"`: `a` が偽値（0）なら `None`、それ以外 `1.0 / a`
  - `"edges"`: 交差点数

### 3.5 UART

#### `def decode_uart(t, y, baud, threshold=None, bits=8, parity="none", stop_bits=1, idle="high", lsb_first=True):`
- docstring: `"""UART（1線）を解読してバイト列を返す。各要素 {time, value, hex, char, ok}。"""`
- アルゴリズム:
  1. `t`, `y` を `float` 配列化。`threshold is None` なら `auto_threshold(y)`。
  2. `logic = _logic(y, threshold)`。
  3. `idle == "low"` のとき `logic = 1 - logic`（反転論理＝アイドル Low）。
  4. `bit_t = 1.0 / float(baud)`（1 ビット時間）。`tend = t[-1]`。`results = []`。
  5. ループ `i = 0`、`n = len(t)`、`while i < n - 1:`:
     - スタートビット検出: `logic[i] == 1 and logic[i + 1] == 0`（立下り）でなければ `i += 1` で次へ。
     - `start_t = t[i + 1]`。
     - スタートビット中央確認: `_level_at(t, logic, start_t + 0.5 * bit_t) != 0` なら（誤検出）`i += 1; continue`。
     - `val = 0`、`ok = True`、`data_bits = []`。
     - データビット読取り（`for k in range(bits):`）:
       - `bt = start_t + (1.5 + k) * bit_t`（各ビット中央）。
       - `bt > tend` なら `ok = False; break`（範囲外）。
       - `data_bits.append(_level_at(t, logic, bt))`。
     - 全ビット読めたら（`len(data_bits) == bits`）ビット合成:
       - `for k, bitval in enumerate(data_bits):` `pos = k if lsb_first else (bits - 1 - k)`、`val |= (bitval & 1) << pos`。
     - パリティ（`ppos = bits`、`parity in ("even", "odd")` のとき）:
       - `pb = _level_at(t, logic, start_t + (1.5 + ppos) * bit_t)`。
       - `ones = bin(val).count("1") + pb`。
       - `parity == "even" and ones % 2 != 0` → `ok = False`。
       - `parity == "odd" and ones % 2 != 1` → `ok = False`。
       - `ppos += 1`。
     - ストップビット確認: `sb = _level_at(t, logic, start_t + (1.5 + ppos) * bit_t)`、`sb != 1` なら `ok = False`。
     - 文字化: `ch = chr(val) if 32 <= val < 127 else ""`（印字可能 ASCII のみ）。
     - 結果追加:
       ```python
       results.append({"time": float(start_t), "value": int(val),
                       "hex": f"0x{val:02X}", "char": ch, "ok": bool(ok)})
       ```
     - 次フレームへ前進: `adv_t = start_t + (0.5 + ppos + stop_bits) * bit_t`、`j = int(np.searchsorted(t, adv_t))`、`i = max(j, i + 1)`（次のスタート立下りを取りこぼさない）。
     - スタート検出に該当しない `else:` 分岐では `i += 1`。
  6. `return results`。
- 重要細部:
  - `hex` フォーマットは `f"0x{val:02X}"`（大文字 2 桁ゼロ詰め）。
  - `ppos` はデータビット末尾位置からの相対オフセット（パリティ有無で 1 増える）。ストップビット位置は `(1.5 + ppos)` 番目。
  - 前進時刻 `adv_t` の係数 `(0.5 + ppos + stop_bits)` に注意（`ppos` はパリティ込みのビット数）。

### 3.6 I2C

#### `def decode_i2c(t, scl, sda, threshold=None):`
- docstring: `"""I2C（SCL/SDA）を解読。START/STOP/アドレス/データ/ACK を返す。"""`
- アルゴリズム:
  1. `t`, `scl`, `sda` を `float` 配列化。
  2. しきい値: `th = threshold if threshold is not None else auto_threshold(np.concatenate([scl, sda]))`（両線結合で自動推定）。
  3. `Lscl = _logic(scl, th)`、`Lsda = _logic(sda, th)`。
  4. `events = []`。
  5. エッジ検出:
     - `scl_rise = np.where((Lscl[:-1] == 0) & (Lscl[1:] == 1))[0] + 1`（SCL 立上り＝ビットサンプル点）。
     - `sda_fall = np.where((Lsda[:-1] == 1) & (Lsda[1:] == 0))[0] + 1`。
     - `sda_rise = np.where((Lsda[:-1] == 0) & (Lsda[1:] == 1))[0] + 1`。
  6. 内部 `def scl_high(i): return Lscl[min(i, len(Lscl) - 1)] == 1`。
  7. START/STOP: `starts = [i for i in sda_fall if scl_high(i)]`（SCL High 中の SDA 立下り）、`stops = [i for i in sda_rise if scl_high(i)]`（SCL High 中の SDA 立上り）。
  8. `markers = sorted([(i, "S") for i in starts] + [(i, "P") for i in stops])`（インデックス昇順、"S"=START、"P"=STOP）。
  9. `bits, bit_times = [], []`、`first_byte = True`。
  10. 内部 `def flush_byte():`（`nonlocal bits, bit_times, first_byte`）:
      - `len(bits) >= 9` のときのみ処理:
        - `data = bits[:8]`、`ack = bits[8]`。
        - `val = 0`、`for bv in data: val = (val << 1) | (bv & 1)`（**MSB first** で 8 ビット合成）。
        - `first_byte` なら（アドレスバイト）:
          - `addr = val >> 1`、`rw = "R" if (val & 1) else "W"`。
          - events に追加:
            ```python
            {"time": float(t[bit_times[0]]), "type": "addr",
             "value": addr, "hex": f"0x{addr:02X}", "rw": rw,
             "ack": "ACK" if ack == 0 else "NACK"}
            ```
          - `first_byte = False`。
        - それ以外（データバイト）:
          ```python
          {"time": float(t[bit_times[0]]), "type": "data",
           "value": val, "hex": f"0x{val:02X}",
           "ack": "ACK" if ack == 0 else "NACK"}
          ```
      - 最後に `bits, bit_times = [], []`（**処理可否に関わらずクリア**）。
  11. メインループ `mi = 0`、`for i in scl_rise:`:
      - この SCL 立上り前のマーカー処理: `while mi < len(markers) and markers[mi][0] <= i:`
        - `idx, kind = markers[mi]`。
        - `kind == "S"` なら: `flush_byte()` → events に `{"time": float(t[idx]), "type": "START"}` 追加 → `first_byte = True` → `bits, bit_times = [], []`。
        - それ以外（STOP）なら: `flush_byte()` → events に `{"time": float(t[idx]), "type": "STOP"}` 追加 → `bits, bit_times = [], []`。
        - `mi += 1`。
      - `bits.append(_level_at(t, Lsda, t[i]))`（SCL 立上り時の SDA 値）。
      - `bit_times.append(i)`。
      - `if len(bits) == 9: flush_byte()`（9 ビット＝8 データ＋ACK 揃ったら確定）。
  12. 残マーカー処理: `for idx, kind in markers[mi:]:` `flush_byte()` → events に `{"time": float(t[idx]), "type": "START" if kind == "S" else "STOP"}`。
  13. `return events`。
- 重要細部:
  - イベント種別文字列: `"START"`, `"STOP"`, `"addr"`, `"data"`。`type` キーは厳守。
  - `ack` 値: ロジック 0 のとき `"ACK"`、それ以外 `"NACK"`。
  - アドレスは `val >> 1`、最下位ビットが R/W（`1`→`"R"`、`0`→`"W"`）。
  - I2C のビット合成は **MSB first 固定**（左シフト）。
  - `hex` は `f"0x{addr:02X}"` / `f"0x{val:02X}"`。

### 3.7 SPI

#### `def decode_spi(t, sck, mosi, cs=None, threshold=None, cpol=0, cpha=0, bits=8, msb_first=True):`
- docstring: `"""SPI（SCK/MOSI[/CS]）を解読してバイト列を返す。"""`
- アルゴリズム:
  1. `t`, `sck`, `mosi` を `float` 配列化。
  2. しきい値: `th = threshold if threshold is not None else auto_threshold(np.concatenate([sck, mosi]))`。
  3. `Lsck = _logic(sck, th)`、`Lmosi = _logic(mosi, th)`、`Lcs = _logic(cs, th) if cs is not None else None`。
  4. クロックエッジ:
     - `rising = np.where((Lsck[:-1] == 0) & (Lsck[1:] == 1))[0] + 1`。
     - `falling = np.where((Lsck[:-1] == 1) & (Lsck[1:] == 0))[0] + 1`。
     - `sample_edges = rising if (cpol == cpha) else falling`（CPOL==CPHA なら立上り、異なれば立下りでサンプル）。
     - `sample_edges = np.sort(sample_edges)`。
  5. `results = []`、`cur, nbits, start_idx = 0, 0, None`。
  6. `for i in sample_edges:`:
     - CS ガード: `Lcs is not None and Lcs[min(i, len(Lcs) - 1)] == 1` なら（非選択中）`cur, nbits, start_idx = 0, 0, None; continue`。
     - `start_idx is None` なら `start_idx = i`（バイト先頭エッジ記録）。
     - `bit = _level_at(t, Lmosi, t[i])`。
     - `msb_first` なら `cur = (cur << 1) | (bit & 1)`、そうでなければ `cur |= (bit & 1) << nbits`。
     - `nbits += 1`。
     - `nbits == bits` のとき確定:
       ```python
       results.append({"time": float(t[start_idx]), "value": cur,
                       "hex": f"0x{cur:0{(bits + 3) // 4}X}"})
       cur, nbits, start_idx = 0, 0, None
       ```
  7. `return results`。
- 重要細部:
  - `hex` の桁数は動的に `(bits + 3) // 4`（ビット数を 4 で切り上げた 16 進桁数）。例: bits=8 → 2 桁、bits=12 → 3 桁、bits=16 → 4 桁。フォーマットは `f"0x{cur:0{(bits + 3) // 4}X}"`。
  - サンプルエッジ選択則: `cpol == cpha` → 立上り（rising）、否なら立下り（falling）。
  - CS は **アクティブ Low**（ロジック 1＝非選択）。CS Low（=0）でのみビット蓄積。CS High でカウンタ全リセット。

---

## 4. 再現に必須の細部・エッジケース・ガード

- **しきい値の符号**: `_logic` は厳密 `>`（しきい値ちょうどは 0 とみなす）。`crossings` の `below` は `y < level`（厳密小なり）。
- **線形補間のゼロ除算ガード**: `crossings.interp` で `denom == 0` の箇所は `frac = 0`（`np.where` 二重で安全化）。連続同値サンプルでも例外を出さない。
- **配列空判定**: `interp(idx)` は `idx.size == 0` で空 `float` 配列を返す（`np.where(...)[0]` が空でも安全）。
- **`_level_at` のクランプ**: `searchsorted` の結果を `[0, len(logic)-1]` にクランプ。範囲外時刻でも index error を出さない。
- **空辞書/None リターン**:
  - `eye_diagram`: `symbol_period <= 0` で `(None, None)`。
  - `eye_measurements`: 早期 `{}` を 3 箇所（`ui<=0 or t.size<8` / `yc.size<8` / `hi.size<2 or lo.size<2`）。
  - `jitter_tie`: `len(cr) < 3` で `{}`。
- **条件付きキー**:
  - `eye_measurements` の `q_factor`/`snr_db`/`extinction_ratio_db` は条件未満で値 `None`（キーは存在）。`snr_db` は `(s1+s0)>0 and amp>0` の両方が必要。`extinction_ratio_db` は `mu0 > 0` が必要。
  - `jitter`/`eye_width` 系キー（`jitter_pp`/`jitter_rms`/`eye_width`）は交差 4 点未満で**辞書に追加されない**（キー欠落）。
  - `jitter_tie` の `freq` は `a`（傾き）が偽値（0）なら `None`。
- **辞書キー名は厳守**（呼び出し側が参照）:
  - `mask_test`: `passed, violations, mask, violation_times`。
  - `jitter_tie`: `tie, crossings, rms, pp, period, freq, edges`。
  - `decode_uart` 各要素: `time, value, hex, char, ok`。
  - `decode_i2c` 各イベント: `time, type`（`type` は `START`/`STOP`/`addr`/`data`）＋ addr/data は `value, hex, ack`、addr のみ `rw`。
  - `decode_spi` 各要素: `time, value, hex`。
- **数値の型**: `time`/`rms`/`pp`/`period`/`freq` 等は明示的に `float()`、`value`/`violations`/`edges` 等は `int()`。`value` の `bool`化（`ok`）も明示。
- **UART の前進ロジック**: `adv_t` の係数は `(0.5 + ppos + stop_bits)`。`ppos` はパリティ込みのビット数（`parity` が none なら `bits`、even/odd なら `bits+1`）。前進後 `i = max(j, i + 1)` で最低 1 進める（無限ループ防止）。
- **I2C の `flush_byte` は必ず末尾でバッファをクリア**（9 ビット未満でも `bits, bit_times = [], []` 実行）。START 時は `first_byte=True` に戻す。
- **I2C のビット順は MSB first 固定**（オプションなし）。SPI は `msb_first` 引数で可変。
- **SPI の CS 非選択リセット**: CS High を見たら蓄積中バイトを破棄（部分ビットは捨てる）。
- **hex フォーマット差**: UART/I2C は固定 2 桁 `02X`、SPI は `bits` 連動 `(bits+3)//4` 桁。

---

## 5. このファイルに関係する落とし穴

- **facade ではない側**: `analysis.py` は facade だが、本ファイルは `analysis` を**通常 import** して `histogram_top_base` を呼ぶだけ。公開名 `histogram_top_base` を保つ前提に依存する。
- **Qt を import しない**: 本ファイルは純粋な数値処理モジュール。Qt6 列挙・matplotlib 経由 import 等は**不要**（書かないこと）。`batch_render` 同様、Qt 非依存であるべきモジュール群の一員。
- **scipy 非依存**: `numpy` のみで完結（`np.polyfit`/`np.searchsorted`/`np.where`/`np.nanmean`/`np.nanmax`/`np.nanmin` を使用）。scipy を import しない。
- **`np.std` はデフォルト母標準偏差（ddof=0）**: `eye_measurements`/`jitter_tie` で `np.std` を ddof 指定なしで使用（変更しない）。`hi.std()`/`lo.std()` も同様。
- **`f"0x{val:02X}"` の大文字 X**: 16 進は**大文字**。`0x` プレフィックス付き。
- **`crossings` の戻りは `"both"` のみソート済み**: `rising`/`falling` 単独はインデックス順（時系列順とほぼ一致だが厳密ソートはしない）。
- **`monospace`/日本語フォント問題は無関係**（GUI なし）。grid linewidth=None 問題も無関係。
- **早期リターンの戻り値型の違い**: `eye_diagram` は `(None, None)` タプル、他の解析関数は `{}`（空辞書）。混同しないこと。
- **整数シフトのビットマスク**: `(bitval & 1)` / `(bit & 1)` で確実に 0/1 に丸めてからシフト（ロジック配列が int8 でも安全）。
