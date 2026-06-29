# [14/30] ファイル `advanced.py` を作成

あなたは PySide6 + matplotlib 製のデスクトップアプリ「CSV / TSV / 波形 グラフ・解析ツール」を、複数ファイルに分けて再現しています。
これはその **14 番目** のファイルです（全 30 ファイル）。

## 指示（厳守）
- 下のコードブロックの内容で、ファイル `advanced.py` を**新規作成**してください。
- **一字一句そのまま・省略なし**で出力すること。`pass` だけの空クラス／`# TODO`／`… 省略 …`／要約・解説への置き換えは**禁止**。
- 出力が途中で切れたら、こちらが「続き」と言うので、**最後の行まで**出力してください。
- 前置き・後書き・他ファイルの説明は不要。**このファイルの完全な中身だけ**を返してください。
- 文字コードは UTF-8。フォルダ付きパス（例 `graph_app_mixins/...`）はその階層に作成してください。

## `advanced.py` の中身（このまま出力）
```python
"""高度解析：マスク/リミット合否、アイダイアグラム、ジッタ、シリアルプロトコル解読。

ハイエンドオシロ相当の解析機能を後処理で提供する。プロトコル解読は
UART（1線）、I2C（SCL/SDA）、SPI（SCK/MOSI[/CS]）に対応。
"""

import numpy as np

import analysis


# ----------------------------------------------------------------- 共通
def auto_threshold(y):
    top, base = analysis.histogram_top_base(y)
    if top is None:
        return float(np.nanmean(y))
    return (top + base) / 2.0


def _logic(y, threshold):
    """しきい値で 0/1 のロジック列に変換。"""
    return (np.asarray(y, dtype=float) > threshold).astype(np.int8)


def crossings(t, y, level, edge="both"):
    """level を横切る時刻（線形補間）を返す。edge: rising/falling/both。"""
    t = np.asarray(t, dtype=float)
    y = np.asarray(y, dtype=float)
    below = y < level
    up = np.where(below[:-1] & ~below[1:])[0]
    dn = np.where(~below[:-1] & below[1:])[0]

    def interp(idx):
        idx = np.asarray(idx, dtype=int)
        if idx.size == 0:
            return np.asarray([], dtype=float)
        y1, y2 = y[idx], y[idx + 1]
        denom = y2 - y1
        frac = np.where(denom != 0.0, (level - y1) / np.where(denom != 0.0, denom, 1.0), 0.0)
        return t[idx] + frac * (t[idx + 1] - t[idx])

    if edge == "rising":
        return interp(up)
    if edge == "falling":
        return interp(dn)
    return np.sort(np.concatenate([interp(up), interp(dn)]))


def _level_at(t, logic, time):
    i = int(np.searchsorted(t, time))
    i = min(max(i, 0), len(logic) - 1)
    return int(logic[i])


# ----------------------------------------------------------------- マスク試験
def mask_test(t, y, upper=None, lower=None):
    """上限/下限を超えたサンプルを検出して合否を返す。"""
    t = np.asarray(t, dtype=float)
    y = np.asarray(y, dtype=float)
    viol = np.zeros(y.shape, dtype=bool)
    if upper is not None:
        viol |= y > upper
    if lower is not None:
        viol |= y < lower
    n = int(viol.sum())
    return {"passed": n == 0, "violations": n, "mask": viol,
            "violation_times": t[viol]}


# ----------------------------------------------------------------- アイダイアグラム
def eye_diagram(t, y, symbol_period, n_ui=2):
    """シンボル周期で折り返した (phase, y) を返す（重ね描きでアイになる）。"""
    t = np.asarray(t, dtype=float)
    y = np.asarray(y, dtype=float)
    if symbol_period <= 0:
        return None, None
    span = n_ui * symbol_period
    phase = ((t - t[0]) % span)
    return phase, y


def eye_measurements(t, y, symbol_period):
    """構造化アイ測定。symbol_period[s]=1UI。

    アイ中央のサンプルから上下レベル(μ1,σ1 / μ0,σ0)を推定し、
    eye amplitude/height、Q factor、消光比(ER)、S/N、クロス点ジッタ、アイ幅を返す。
    Returns dict（計算不能な項目は欠落）。
    """
    t = np.asarray(t, dtype=float)
    y = np.asarray(y, dtype=float)
    ui = float(symbol_period)
    if ui <= 0 or t.size < 8:
        return {}
    phase = ((t - t[0]) % ui) / ui                 # 0..1（1UIで正規化）
    center = (np.abs(phase - 0.5) < 0.06) & np.isfinite(y)
    yc = y[center]
    if yc.size < 8:
        return {}
    mid = (np.nanmax(y) + np.nanmin(y)) / 2.0
    hi = yc[yc >= mid]
    lo = yc[yc < mid]
    if hi.size < 2 or lo.size < 2:
        return {}
    mu1, s1 = float(hi.mean()), float(hi.std())
    mu0, s0 = float(lo.mean()), float(lo.std())
    amp = mu1 - mu0
    out = {
        "eye_amplitude": amp,
        "level1": mu1, "level0": mu0,
        "eye_height": (mu1 - 3 * s1) - (mu0 + 3 * s0),
        "q_factor": (amp / (s1 + s0)) if (s1 + s0) > 0 else None,
        "snr_db": (20 * np.log10(amp / (s1 + s0))) if (s1 + s0) > 0 and amp > 0 else None,
        "extinction_ratio_db": (10 * np.log10(mu1 / mu0)) if mu0 > 0 else None,
    }
    # クロスレベルでのジッタ → アイ幅 = UI − ジッタpp
    cr = np.asarray(crossings(t, y, (mu1 + mu0) / 2.0, "both"), dtype=float)
    if cr.size >= 4:
        cph = (cr - t[0]) % ui
        cph = np.where(cph > ui / 2, cph - ui, cph)   # -UI/2..UI/2 に集約
        out["jitter_pp"] = float(cph.max() - cph.min())
        out["jitter_rms"] = float(np.std(cph))
        out["eye_width"] = float(max(ui - out["jitter_pp"], 0.0))
    return out


# ----------------------------------------------------------------- ジッタ
def jitter_tie(t, y, threshold=None, edge="rising"):
    """しきい値交差から TIE（時間間隔誤差）と RMS/pp ジッタを求める。"""
    t = np.asarray(t, dtype=float)
    y = np.asarray(y, dtype=float)
    if threshold is None:
        threshold = auto_threshold(y)
    cr = crossings(t, y, threshold, edge)
    if len(cr) < 3:
        return {}
    idx = np.arange(len(cr))
    a, b = np.polyfit(idx, cr, 1)   # 理想クロック = a*idx + b
    ideal = a * idx + b
    tie = cr - ideal
    return {"tie": tie, "crossings": cr,
            "rms": float(np.std(tie)), "pp": float(tie.max() - tie.min()),
            "period": float(a), "freq": float(1.0 / a) if a else None,
            "edges": int(len(cr))}


# ----------------------------------------------------------------- UART
def decode_uart(t, y, baud, threshold=None, bits=8, parity="none",
                stop_bits=1, idle="high", lsb_first=True):
    """UART（1線）を解読してバイト列を返す。各要素 {time, value, hex, char, ok}。"""
    t = np.asarray(t, dtype=float)
    y = np.asarray(y, dtype=float)
    if threshold is None:
        threshold = auto_threshold(y)
    logic = _logic(y, threshold)
    if idle == "low":   # 反転論理（アイドルLow）
        logic = 1 - logic
    bit_t = 1.0 / float(baud)
    tend = t[-1]
    results = []
    # アイドル(=1)→0 への立下りをスタートビットとみなす
    i = 0
    n = len(t)
    while i < n - 1:
        if logic[i] == 1 and logic[i + 1] == 0:   # 立下り
            start_t = t[i + 1]
            # スタートビット中央で 0 を確認
            if _level_at(t, logic, start_t + 0.5 * bit_t) != 0:
                i += 1
                continue
            val = 0
            ok = True
            data_bits = []
            for k in range(bits):
                bt = start_t + (1.5 + k) * bit_t
                if bt > tend:
                    ok = False
                    break
                data_bits.append(_level_at(t, logic, bt))
            if len(data_bits) == bits:
                for k, bitval in enumerate(data_bits):
                    pos = k if lsb_first else (bits - 1 - k)
                    val |= (bitval & 1) << pos
            # パリティ
            ppos = bits
            if parity in ("even", "odd"):
                pb = _level_at(t, logic, start_t + (1.5 + ppos) * bit_t)
                ones = bin(val).count("1") + pb
                if parity == "even" and ones % 2 != 0:
                    ok = False
                if parity == "odd" and ones % 2 != 1:
                    ok = False
                ppos += 1
            # ストップビット（=1 のはず）
            sb = _level_at(t, logic, start_t + (1.5 + ppos) * bit_t)
            if sb != 1:
                ok = False
            ch = chr(val) if 32 <= val < 127 else ""
            results.append({"time": float(start_t), "value": int(val),
                            "hex": f"0x{val:02X}", "char": ch, "ok": bool(ok)})
            # 次フレーム直前まで進める（次のスタート立下りは取りこぼさない）
            adv_t = start_t + (0.5 + ppos + stop_bits) * bit_t
            j = int(np.searchsorted(t, adv_t))
            i = max(j, i + 1)
        else:
            i += 1
    return results


# ----------------------------------------------------------------- I2C
def decode_i2c(t, scl, sda, threshold=None):
    """I2C（SCL/SDA）を解読。START/STOP/アドレス/データ/ACK を返す。"""
    t = np.asarray(t, dtype=float)
    scl = np.asarray(scl, dtype=float)
    sda = np.asarray(sda, dtype=float)
    th = threshold if threshold is not None else auto_threshold(
        np.concatenate([scl, sda]))
    Lscl = _logic(scl, th)
    Lsda = _logic(sda, th)

    events = []
    # SCL 立上り（ビットサンプル点）と SDA 遷移（START/STOP 検出）
    scl_rise = np.where((Lscl[:-1] == 0) & (Lscl[1:] == 1))[0] + 1
    sda_fall = np.where((Lsda[:-1] == 1) & (Lsda[1:] == 0))[0] + 1
    sda_rise = np.where((Lsda[:-1] == 0) & (Lsda[1:] == 1))[0] + 1

    def scl_high(i):
        return Lscl[min(i, len(Lscl) - 1)] == 1

    starts = [i for i in sda_fall if scl_high(i)]
    stops = [i for i in sda_rise if scl_high(i)]
    markers = sorted([(i, "S") for i in starts] + [(i, "P") for i in stops])

    bits, bit_times = [], []
    first_byte = True

    def flush_byte():
        nonlocal bits, bit_times, first_byte
        if len(bits) >= 9:
            data = bits[:8]
            ack = bits[8]
            val = 0
            for bv in data:
                val = (val << 1) | (bv & 1)
            if first_byte:
                addr = val >> 1
                rw = "R" if (val & 1) else "W"
                events.append({"time": float(t[bit_times[0]]), "type": "addr",
                               "value": addr, "hex": f"0x{addr:02X}", "rw": rw,
                               "ack": "ACK" if ack == 0 else "NACK"})
                first_byte = False
            else:
                events.append({"time": float(t[bit_times[0]]), "type": "data",
                               "value": val, "hex": f"0x{val:02X}",
                               "ack": "ACK" if ack == 0 else "NACK"})
        bits, bit_times = [], []

    mi = 0
    for i in scl_rise:
        # この SCL 立上り前に START/STOP があれば処理
        while mi < len(markers) and markers[mi][0] <= i:
            idx, kind = markers[mi]
            if kind == "S":
                flush_byte()
                events.append({"time": float(t[idx]), "type": "START"})
                first_byte = True
                bits, bit_times = [], []
            else:
                flush_byte()
                events.append({"time": float(t[idx]), "type": "STOP"})
                bits, bit_times = [], []
            mi += 1
        bits.append(_level_at(t, Lsda, t[i]))
        bit_times.append(i)
        if len(bits) == 9:
            flush_byte()
    # 最後の SCL 立上り以降に残った START/STOP を処理
    for idx, kind in markers[mi:]:
        flush_byte()
        events.append({"time": float(t[idx]),
                       "type": "START" if kind == "S" else "STOP"})
    return events


# ----------------------------------------------------------------- SPI
def decode_spi(t, sck, mosi, cs=None, threshold=None, cpol=0, cpha=0,
               bits=8, msb_first=True):
    """SPI（SCK/MOSI[/CS]）を解読してバイト列を返す。"""
    t = np.asarray(t, dtype=float)
    sck = np.asarray(sck, dtype=float)
    mosi = np.asarray(mosi, dtype=float)
    th = threshold if threshold is not None else auto_threshold(
        np.concatenate([sck, mosi]))
    Lsck = _logic(sck, th)
    Lmosi = _logic(mosi, th)
    Lcs = _logic(cs, th) if cs is not None else None

    # サンプルするクロックエッジ（CPOL/CPHA から決定）
    rising = np.where((Lsck[:-1] == 0) & (Lsck[1:] == 1))[0] + 1
    falling = np.where((Lsck[:-1] == 1) & (Lsck[1:] == 0))[0] + 1
    sample_edges = rising if (cpol == cpha) else falling
    sample_edges = np.sort(sample_edges)

    results = []
    cur, nbits, start_idx = 0, 0, None
    for i in sample_edges:
        if Lcs is not None and Lcs[min(i, len(Lcs) - 1)] == 1:
            cur, nbits, start_idx = 0, 0, None   # CS 非選択中は無視
            continue
        if start_idx is None:
            start_idx = i
        bit = _level_at(t, Lmosi, t[i])
        if msb_first:
            cur = (cur << 1) | (bit & 1)
        else:
            cur |= (bit & 1) << nbits
        nbits += 1
        if nbits == bits:
            results.append({"time": float(t[start_idx]), "value": cur,
                            "hex": f"0x{cur:0{(bits + 3) // 4}X}"})
            cur, nbits, start_idx = 0, 0, None
    return results
```
