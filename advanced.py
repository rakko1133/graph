"""高度解析：マスク/リミット合否、アイダイアグラム、ジッタ、シリアルプロトコル解読。

ハイエンドオシロ相当の解析機能を後処理で提供する。プロトコル解読は
UART（1線）、I2C（SCL/SDA）、SPI（SCK/MOSI[/CS]）、
CAN（1線・標準/拡張ID・デスタッフィング・CRC15検証）、
LIN（1線・break/sync/PID/チェックサム検証）、1-Wire（1線・標準速度）に対応。
"""

import numpy as np

import analysis


# ----------------------------------------------------------------- 共通
def auto_threshold(y):
    """ロジック判定のしきい値（Top/Base の中点。取れなければ平均）。"""
    level = analysis.mid_level(y, require_span=False)
    return float(np.nanmean(y)) if level is None else level


def _logic(y, threshold):
    """しきい値で 0/1 のロジック列に変換。"""
    return (np.asarray(y, dtype=float) > threshold).astype(np.int8)


def crossings(t, y, level, edge="both"):
    """level を横切る時刻（線形補間）を返す。edge: rising/falling/both。"""
    return analysis.crossing_times(t, y, level, edge=edge)


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


# ----------------------------------------------------------------- CAN
def _can_crc15(bits):
    """CAN の CRC-15（多項式 0x4599）。SOF〜データ末尾のデスタッフ後ビット列に対して計算。"""
    crc = 0
    for b in bits:
        inv = (b & 1) ^ ((crc >> 14) & 1)
        crc = (crc << 1) & 0x7FFF
        if inv:
            crc ^= 0x4599
    return crc


def decode_can(t, y, bitrate, threshold=None, dominant="low"):
    """CAN（1線）を解読してフレーム一覧を返す。

    dominant="low": RXピン等でドミナント=Low の信号（既定）。
    dominant="high": CANH-CANL の差動などドミナント=High の信号。
    標準(11bit)・拡張(29bit)ID、ビットスタッフィング除去、CRC-15検証に対応。
    各要素 {time, id, ext, rtr, dlc, data(list), hex, crc_ok}。
    """
    t = np.asarray(t, dtype=float)
    y = np.asarray(y, dtype=float)
    if threshold is None:
        threshold = auto_threshold(y)
    logic = _logic(y, threshold)
    dom = (1 - logic) if dominant == "low" else logic   # 1=ドミナント
    bit_t = 1.0 / float(bitrate)
    tend = t[-1]
    n = len(t)
    frames = []
    i = 0
    while i < n - 1:
        if not (dom[i] == 0 and dom[i + 1] == 1):   # recessive→dominant = SOF候補
            i += 1
            continue
        sof_t = t[i + 1]
        frame, end_t = _read_can_frame(t, dom, sof_t, bit_t, tend)
        if frame is not None:
            frames.append(frame)
            i = max(int(np.searchsorted(t, end_t)), i + 1)
        else:
            i += 1
    return frames


def _read_can_frame(t, dom, sof_t, bit_t, tend):
    """SOF位置から1フレームを読む。失敗時は (None, _)。戻り値 (frame, フレーム終端時刻)。"""
    state = {"k": 0, "run_val": None, "run_len": 0}
    crc_bits = []   # CRC計算対象（SOF〜データ末尾のデスタッフ後ビット）

    def read_raw():
        bt = sof_t + (state["k"] + 0.5) * bit_t
        state["k"] += 1
        if bt > tend:
            return None
        idx = min(int(np.searchsorted(t, bt)), len(dom) - 1)
        return 0 if dom[idx] else 1   # CAN値（0=ドミナント）

    def next_bit():
        """デスタッフィング付きで1ビット読む（スタッフ相はSOF〜CRC末尾）。"""
        b = read_raw()
        if b is None:
            return None
        if state["run_len"] == 5:      # 直前5連続 → これはスタッフビット
            if b == state["run_val"]:
                return None            # スタッフエラー（フォーム崩れ）
            state["run_val"], state["run_len"] = b, 1
            b = read_raw()
            if b is None:
                return None
        if b == state["run_val"]:
            state["run_len"] += 1
        else:
            state["run_val"], state["run_len"] = b, 1
        return b

    def take(nbits, into_crc=True):
        v = 0
        for _ in range(nbits):
            b = next_bit()
            if b is None:
                return None
            if into_crc:
                crc_bits.append(b)
            v = (v << 1) | b
        return v

    # SOF（ドミナント=0）はビット位置0。読み出しはID先頭（位置1）から始める
    state["k"] = 1
    state["run_val"], state["run_len"] = 0, 1
    crc_bits.append(0)
    ident = take(11)
    b1 = take(1)          # RTR（標準）または SRR（拡張）
    ide = take(1)
    if None in (ident, b1, ide):
        return None, sof_t
    if ide:               # 拡張フレーム
        id_ext = take(18)
        rtr = take(1)
        take(2)           # r1, r0
        if None in (id_ext, rtr):
            return None, sof_t
        full_id = (ident << 18) | id_ext
    else:
        rtr = b1
        take(1)           # r0
        full_id = ident
    dlc = take(4)
    if dlc is None:
        return None, sof_t
    ndata = 0 if rtr else min(dlc, 8)
    data = []
    for _ in range(ndata):
        v = take(8)
        if v is None:
            return None, sof_t
        data.append(v)
    crc_calc = _can_crc15(crc_bits)
    crc = take(15, into_crc=False)
    if crc is None:
        return None, sof_t
    read_raw()            # CRCデリミタ（以降スタッフなし）
    read_raw()            # ACKスロット（受信ノードが居ないと recessive のまま＝判定しない）
    end_t = sof_t + (state["k"] + 10) * bit_t   # ACKデリミタ＋EOF(7)+IFS(3)ぶん進める
    frame = {"time": float(sof_t), "id": int(full_id), "ext": bool(ide),
             "rtr": bool(rtr), "dlc": int(dlc), "data": [int(d) for d in data],
             "hex": " ".join(f"{d:02X}" for d in data),
             "crc_ok": bool(crc_calc == crc)}
    return frame, end_t


# ----------------------------------------------------------------- LIN
def decode_lin(t, y, baud=19200, threshold=None):
    """LIN（1線）を解読。break→sync(0x55)→PID→データ→チェックサムを返す。

    チェックサムは classic（データのみ）/ enhanced（PID込み）の両方式で照合し、
    どちらかが一致すれば ok とする。各要素 {time, type, ...}。
    """
    t = np.asarray(t, dtype=float)
    y = np.asarray(y, dtype=float)
    if threshold is None:
        threshold = auto_threshold(y)
    logic = _logic(y, threshold)
    bit_t = 1.0 / float(baud)
    events = []
    n = len(t)
    i = 0
    while i < n - 1:
        if not (logic[i] == 1 and logic[i + 1] == 0):
            i += 1
            continue
        low_start = t[i + 1]
        j = i + 1
        while j < n - 1 and logic[j + 1] == 0:
            j += 1
        low_len = t[min(j + 1, n - 1)] - low_start
        if low_len < 11 * bit_t:      # breakは11ビット時間以上のLow
            i += 1
            continue
        events.append({"time": float(low_start), "type": "BREAK"})
        # break後のバイト列をUARTとして読む（次のbreakまたは終端まで）
        seg_start = t[min(j + 1, n - 1)]
        seg_bytes = _lin_read_bytes(t, logic, seg_start, bit_t)
        if not seg_bytes:
            i = j + 1
            continue
        vals = [b["value"] for b in seg_bytes]
        k = 0
        if vals and vals[0] == 0x55:
            events.append({"time": seg_bytes[0]["time"], "type": "SYNC", "value": 0x55})
            k = 1
        if k < len(vals):
            pid = vals[k]
            fid = pid & 0x3F
            p0 = (fid ^ (fid >> 1) ^ (fid >> 2) ^ (fid >> 4)) & 1
            p1 = (~((fid >> 1) ^ (fid >> 3) ^ (fid >> 4) ^ (fid >> 5))) & 1
            pid_ok = pid == (fid | (p0 << 6) | (p1 << 7))
            events.append({"time": seg_bytes[k]["time"], "type": "PID",
                           "value": fid, "ok": bool(pid_ok)})
            data = vals[k + 1:-1]
            if data or len(vals) > k + 1:
                csum = vals[-1]

                def _lin_sum(vals0):
                    """LINのチェックサム＝キャリー巻き込み加算の反転。"""
                    s = 0
                    for v in vals0:
                        s += v
                        if s > 0xFF:
                            s = (s & 0xFF) + 1
                    return (~s) & 0xFF

                classic = _lin_sum(data) if data else None
                enhanced = _lin_sum([pid] + data)
                ok = csum in (classic, enhanced)
                for bi, v in zip(seg_bytes[k + 1:-1], data):
                    events.append({"time": bi["time"], "type": "data", "value": v})
                events.append({"time": seg_bytes[-1]["time"], "type": "CSUM",
                               "value": csum, "ok": bool(ok)})
        i = max(int(np.searchsorted(t, seg_bytes[-1]["time"] + 10 * bit_t)), j + 1)
    return events


def _lin_read_bytes(t, logic, start_t, bit_t, max_bytes=12):
    """start_t 以降のUART(8N1)バイトを、アイドルが2バイト時間続くまで読む。"""
    out = []
    tend = t[-1]
    cur = start_t
    n = len(t)
    while len(out) < max_bytes:
        # 次のスタートビット（立下り）を探す
        i = int(np.searchsorted(t, cur))
        while i < n - 1 and not (logic[i] == 1 and logic[i + 1] == 0):
            i += 1
        if i >= n - 1:
            break
        st = t[i + 1]
        if st - cur > 20 * bit_t and out:   # フレーム間ギャップで打ち切り
            break
        if st + 10 * bit_t > tend:
            break
        val = 0
        for k in range(8):
            idx = min(int(np.searchsorted(t, st + (1.5 + k) * bit_t)), n - 1)
            val |= (int(logic[idx]) & 1) << k
        out.append({"time": float(st), "value": val})
        cur = st + 10 * bit_t
    return out


# ----------------------------------------------------------------- 1-Wire
def decode_onewire(t, y, threshold=None, time_scale=1.0):
    """1-Wire（標準速度）を解読。リセット/プレゼンス/バイト列を返す。

    Lowパルス幅で判定: >480µs=リセット、<20µs=1、20〜120µs=0（LSBファースト）。
    time_scale: 時間軸が秒でない場合の倍率（例: msの列なら1e-3）。
    """
    t = np.asarray(t, dtype=float) * float(time_scale)
    y = np.asarray(y, dtype=float)
    if threshold is None:
        threshold = auto_threshold(y)
    logic = _logic(y, threshold)
    n = len(t)
    # Lowパルス（立下り→立上り）を列挙
    pulses = []
    i = 0
    while i < n - 1:
        if logic[i] == 1 and logic[i + 1] == 0:
            start = t[i + 1]
            j = i + 1
            while j < n - 1 and logic[j + 1] == 0:
                j += 1
            end = t[min(j + 1, n - 1)]
            pulses.append((start, end - start))
            i = j + 1
        else:
            i += 1
    events = []
    bits, bit_t0 = [], None
    last_reset_end = None
    for start, width in pulses:
        if width >= 480e-6:              # リセットパルス
            if bits:                      # 中途半端なビットは破棄
                bits, bit_t0 = [], None
            events.append({"time": float(start), "type": "RESET"})
            last_reset_end = start + width
            continue
        # リセット直後の最初のLow（60µs級）はスレーブのプレゼンス応答
        if (last_reset_end is not None and not bits
                and start - last_reset_end < 500e-6 and width >= 40e-6):
            events.append({"time": float(start), "type": "PRESENCE"})
            last_reset_end = None
            continue
        last_reset_end = None
        bit = 1 if width < 20e-6 else 0   # スロットのLow幅で0/1判定
        if not bits:
            bit_t0 = start
        bits.append(bit)
        if len(bits) == 8:
            val = 0
            for k, b in enumerate(bits):  # LSBファースト
                val |= (b & 1) << k
            events.append({"time": float(bit_t0), "type": "data", "value": int(val)})
            bits, bit_t0 = [], None
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
