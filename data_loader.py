"""表・波形データファイルの読み込み。

- CSV/TSV/TXT: 文字コード（UTF-8 / BOM付き / CP932 など）と区切り文字を自動判定
- Excel (.xlsx/.xlsm/.xls): シート指定可（既定は先頭シート）
- WAV (.wav): 音声波形を 時間[s]＋ch列 として読む（標準ライブラリのみ）
- LTspice (.raw): 過渡解析のバイナリ/ASCII波形（AC複素・fastaccessは未対応）
- TDMS (.tdms): 要 npTDMS ／ MDF (.mf4/.mdf): 要 asammdf ／ HDF5 (.h5/.hdf5): 要 tables か h5py
  （任意依存。未インストール時は pip コマンド入りの分かりやすいエラーを出す）
"""

import csv
import os

import pandas as pd

# 試行する文字コード（日本語環境でよくある順）。
# UTF-8 系を先に試し、最後に必ず成功する latin-1 をフォールバックに置く。
_ENCODINGS = ["utf-8-sig", "utf-8", "cp932", "shift_jis", "euc-jp", "latin-1"]

# 自動判定で候補とする区切り文字
_DELIMITERS = [",", "\t", ";", "|"]

DELIMITER_LABELS = {
    ",": "カンマ ( , )",
    "\t": "タブ ( \\t )",
    ";": "セミコロン ( ; )",
    "|": "パイプ ( | )",
}

# 扱える拡張子の一覧。**ここが唯一の定義**。
# 以前は「ドラッグ&ドロップの受付」「ファイルダイアログのフィルタ文字列」
# 「フォルダ読み込みの対象」が別々に書かれており、実際にダイアログのフィルタ
# だけ .net が抜けていた（D&Dでは開けるのに、参照ボタンからは選べない）。
EXT_GROUPS = (
    ("CSV/TSV", (".csv", ".tsv", ".txt")),
    ("Excel", (".xlsx", ".xls", ".xlsm")),
    ("波形/計測", (".wav", ".raw", ".tdms", ".mf4", ".mdf", ".h5", ".hdf5")),
    ("LTspice回路", (".asc", ".net")),
)
# 読み込むのではなく「実行して結果を読む」もの（回路図・ネットリスト）
RUNNABLE_EXTS = (".asc", ".net")
# 受け付ける全拡張子
ACCEPT_EXTS = tuple(e for _name, exts in EXT_GROUPS for e in exts)
# 表データとして直接開ける拡張子（フォルダ一括読み込みの対象）
TABLE_EXTS = tuple(e for e in ACCEPT_EXTS if e not in RUNNABLE_EXTS)


def file_dialog_filter():
    """QFileDialog 用のフィルタ文字列を EXT_GROUPS から組み立てる。"""
    def pat(exts):
        return " ".join("*" + e for e in exts)
    parts = ["データ (" + pat(ACCEPT_EXTS) + ")"]
    parts += [f"{name} ({pat(exts)})" for name, exts in EXT_GROUPS]
    parts.append("すべて (*.*)")
    return ";;".join(parts)


def _japanese_score(text):
    """テキスト中の日本語文字数と、壊れた文字（私用領域・置換文字）数を返す。"""
    jp = bad = 0
    for ch in text:
        o = ord(ch)
        if (0x3040 <= o <= 0x30FF) or (0x4E00 <= o <= 0x9FFF) or (0xFF00 <= o <= 0xFFEF):
            jp += 1
        elif (0xE000 <= o <= 0xF8FF) or ch == "�":
            bad += 1
    return jp, bad


def detect_encoding(path):
    """ファイルの文字コードを推定して返す。

    BOM を最優先で判定し、なければ候補を順に decode して最初に成功したものを返す。
    どれも失敗した場合は何でも復号できる latin-1 を返す（最終フォールバック）。
    """
    with open(path, "rb") as f:
        raw = f.read()

    if raw.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return "utf-16"

    # 2) UTF-8 として厳密に解釈できればそれを採用（日本語 UTF-8 はここで確定）。
    try:
        raw.decode("utf-8")
        return "utf-8-sig"
    except UnicodeDecodeError:
        pass

    # 3) 日本語候補(cp932/euc-jp)を実際に復号し、日本語文字を含み壊れていない
    #    （私用領域・置換文字が出ない）ものを優先する。これにより欧文ファイルへの
    #    cp932 強制や、euc-jp の big5 等への誤判定を防ぐ。
    best_jp = None
    for enc in ("cp932", "euc-jp"):
        try:
            text = raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
        jp, bad = _japanese_score(text[:100000])
        if bad == 0 and jp > 0 and (best_jp is None or jp > best_jp[1]):
            best_jp = (enc, jp)
    if best_jp:
        return best_jp[0]

    # 4) charset-normalizer のヒント。日本語系(iso-2022-jp 等)のみ採用する。
    jp_names = {"cp932", "shift-jis", "shift_jis", "sjis", "ms932",
                "windows-31j", "euc-jp", "euc_jp", "iso-2022-jp"}
    alias = {"shift-jis": "cp932", "shift_jis": "cp932", "sjis": "cp932",
             "ms932": "cp932", "windows-31j": "cp932", "euc_jp": "euc-jp"}
    try:
        from charset_normalizer import from_bytes

        best = from_bytes(raw).best()
        if best is not None and best.encoding:
            enc = best.encoding.lower().replace("_", "-")
            if enc in jp_names or "jp" in enc or "932" in enc:
                return alias.get(enc, enc)
    except Exception:
        pass

    # 5) 欧文・その他（cp1252 → latin-1 は必ず成功する）
    for enc in ("cp1252", "latin-1"):
        try:
            raw.decode(enc)
            return enc
        except (UnicodeDecodeError, LookupError):
            continue
    return "latin-1"


def detect_delimiter(path, encoding):
    """区切り文字を推定して返す。拡張子を優先し、なければ内容から判定する。"""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".tsv":
        return "\t"

    # 先頭部分を読んで csv.Sniffer と出現回数から推定
    try:
        with open(path, encoding=encoding, errors="replace") as f:
            sample = f.read(8192)
    except (OSError, LookupError):
        return "," if ext == ".csv" else "\t"

    if not sample:
        return "," if ext == ".csv" else "\t"

    try:
        dialect = csv.Sniffer().sniff(sample, delimiters="".join(_DELIMITERS))
        if dialect.delimiter in _DELIMITERS:
            return dialect.delimiter
    except csv.Error:
        pass

    # Sniffer が失敗したら、先頭行での出現回数が最多の区切り文字を採用
    first_line = sample.splitlines()[0] if sample.splitlines() else sample
    counts = {d: first_line.count(d) for d in _DELIMITERS}
    best = max(counts, key=counts.get)
    if counts[best] > 0:
        return best
    return "," if ext == ".csv" else "\t"


def _normalize_columns(df):
    """列名を文字列化・前後空白除去し、重複は ".1" 付与で一意化（CSV/Excel共通）。"""
    used, new_cols = set(), []
    for c in df.columns:
        base = str(c).strip() or "列"
        name, k = base, 1
        while name in used:
            name = f"{base}.{k}"
            k += 1
        used.add(name)
        new_cols.append(name)
    df.columns = new_cols
    return df


def excel_sheet_names(path):
    """Excelブックのシート名一覧を返す（読めない場合は空リスト）。"""
    try:
        return list(pd.ExcelFile(path).sheet_names)
    except Exception:
        return []


def _load_wav(path):
    """WAV音声を 時間[s]＋ch1..chN のDataFrameにする（8/16/32bit PCM対応）。"""
    import wave
    import numpy as np
    with wave.open(path, "rb") as w:
        ch, sw, fr, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        raw = w.readframes(n)
    dtype = {1: np.uint8, 2: np.dtype("<i2"), 4: np.dtype("<i4")}.get(sw)
    if dtype is None:
        raise ValueError(f"未対応のサンプル幅です: {sw * 8}bit（8/16/32bit PCMに対応）")
    a = np.frombuffer(raw, dtype=dtype).astype(float)
    if sw == 1:
        a -= 128.0   # 8bitは無符号なので中心を0に
    a = a.reshape(-1, ch)
    cols = {"時間[s]": np.arange(a.shape[0], dtype=float) / fr}
    for i in range(ch):
        cols[f"ch{i + 1}"] = a[:, i]
    return pd.DataFrame(cols)


def _load_ltspice_raw(path):
    """LTspice の .raw 波形（過渡解析）を読む。バイナリ/ASCII両対応。

    ヘッダはASCIIまたはUTF-16LE（LTspice XVII）。複素数（AC解析）と
    fastaccess形式は未対応で、その旨を案内するエラーを出す。"""
    import numpy as np
    with open(path, "rb") as f:
        data = f.read()
    enc = "utf-16-le" if (data[:2] == b"\xff\xfe" or data[1:2] == b"\x00") else "latin-1"
    marker = body = None
    for m in ("Binary:", "Values:"):
        mb = (m + "\n").encode(enc)
        i = data.find(mb)
        if i < 0:
            mb = (m + "\r\n").encode(enc)
            i = data.find(mb)
        if i >= 0:
            marker, hdr_end, body = m, i, i + len(mb)
            break
    if marker is None:
        raise ValueError("LTspiceの .raw 形式として解釈できません（Binary:/Values: が見つかりません）。")
    header = data[:hdr_end].decode(enc, errors="replace")
    nvars = npts = 0
    flags = ""
    names = []
    in_vars = False
    for line in header.splitlines():
        low = line.strip()
        if low.startswith("No. Variables:"):
            nvars = int(low.split(":")[1])
        elif low.startswith("No. Points:"):
            npts = int(low.split(":")[1])
        elif low.startswith("Flags:"):
            flags = low.split(":", 1)[1].lower()
        elif low.startswith("Variables:"):
            in_vars = True
        elif in_vars and low:
            parts = low.split("\t") if "\t" in line else low.split()
            if len(parts) >= 2 and parts[0].strip().isdigit():
                names.append(parts[1].strip())
    if not nvars or not npts or len(names) != nvars:
        raise ValueError("LTspice .raw のヘッダを解釈できませんでした。")
    if "complex" in flags:
        raise ValueError("AC解析（複素数）の .raw は未対応です。過渡解析(.tran)の .raw を読み込んでください。")
    if "fastaccess" in flags:
        raise ValueError(".raw が fastaccess 形式です。LTspiceの設定で fastaccess を無効にして再保存してください。")
    if marker == "Binary:":
        if "double" in flags:   # 全変数 float64
            arr = np.frombuffer(data[body:body + 8 * nvars * npts], dtype="<f8")
            table = arr.reshape(npts, nvars)
        else:                    # 時間=float64、他=float32（LTspice標準）
            rec = np.dtype([("t", "<f8")] + [(f"v{i}", "<f4") for i in range(1, nvars)])
            arr = np.frombuffer(data[body:body + rec.itemsize * npts], dtype=rec)
            table = np.column_stack([arr["t"]] + [arr[f"v{i}"] for i in range(1, nvars)])
    else:                        # ASCII (Values:)
        text = data[body:].decode(enc, errors="replace")
        vals = [float(tok) for tok in text.split() if _is_float(tok)]
        # 各点は「点番号 v0 v1 ...」の並び。点番号を除いて詰め直す
        table = np.array(vals, dtype=float).reshape(npts, nvars + 1)[:, 1:]
    table[:, 0] = np.abs(table[:, 0])   # LTspiceは圧縮マーカーで時間が負になることがある
    return pd.DataFrame({names[i]: table[:, i] for i in range(nvars)})


def _is_float(tok):
    try:
        float(tok)
        return True
    except ValueError:
        return False


def _load_tdms(path):
    """NI TDMS を読む（要 npTDMS）。グループ/チャンネルを列に展開する。"""
    try:
        from nptdms import TdmsFile
    except ImportError as e:
        raise ValueError("TDMS の読み込みには npTDMS が必要です（pip install npTDMS）。") from e
    td = TdmsFile.read(path)
    groups = td.groups()
    cols = {}
    for g in groups:
        for chan in g.channels():
            name = f"{g.name}/{chan.name}" if len(groups) > 1 else str(chan.name)
            try:   # 波形属性があれば時間軸も作る（最初の1本だけ）
                if "時間[s]" not in cols:
                    cols["時間[s]"] = chan.time_track()
            except (KeyError, ValueError):
                pass
            cols[name] = chan[:]
    if not cols:
        raise ValueError("TDMS内にチャンネルが見つかりません。")
    return pd.DataFrame({k: pd.Series(v) for k, v in cols.items()})


def _load_mdf(path):
    """車載計測 MDF (.mf4/.mdf) を読む（要 asammdf）。"""
    try:
        from asammdf import MDF
    except ImportError as e:
        raise ValueError("MDF の読み込みには asammdf が必要です（pip install asammdf）。") from e
    with MDF(path) as m:
        df = m.to_dataframe()
    df = df.reset_index()
    if df.columns[0] in ("timestamps", "time", "index"):
        df = df.rename(columns={df.columns[0]: "時間[s]"})
    return df


def _load_hdf5(path):
    """HDF5 を読む。pandas形式（要 tables）→ 汎用h5py（1D/2D数値データセット）の順に試す。"""
    try:
        df = pd.read_hdf(path)
        if hasattr(df, "to_frame"):
            df = df.to_frame()
        return df.reset_index(drop=False)
    except Exception:
        pass
    try:
        import h5py
    except ImportError as e:
        raise ValueError("HDF5 の読み込みには tables または h5py が必要です"
                         "（pip install h5py）。") from e
    cols = {}
    with h5py.File(path, "r") as f:
        def visit(name, obj):
            if not isinstance(obj, h5py.Dataset) or obj.dtype.kind not in "fiu":
                return
            short = name.split("/")[-1]
            key = short if short not in cols else name
            if obj.ndim == 1:
                cols[key] = obj[...]
            elif obj.ndim == 2 and obj.shape[1] <= 64:   # 2Dは列に展開
                arr = obj[...]
                for j in range(arr.shape[1]):
                    cols[f"{key}[{j}]"] = arr[:, j]
        f.visititems(visit)
    if not cols:
        raise ValueError("HDF5 内に数値データセット（1D/2D）が見つかりません。")
    return pd.DataFrame({k: pd.Series(v) for k, v in cols.items()})


def load_table(path, encoding=None, delimiter=None, sheet=None):
    """表・波形ファイルを読み込み (DataFrame, 使用encoding, 使用delimiter) を返す。

    encoding / delimiter は CSV/TSV系のみ意味を持ち、None なら自動判定。
    sheet は Excel のシート名/番号（None=先頭）。その他の形式は拡張子で自動判別。
    """
    if not os.path.isfile(path):
        raise FileNotFoundError(f"ファイルが見つかりません: {path}")

    ext = os.path.splitext(path)[1].lower()
    # --- Excel ---
    if ext in (".xlsx", ".xlsm", ".xls"):
        try:
            df = pd.read_excel(path, sheet_name=sheet if sheet is not None else 0)
        except ImportError as e:
            if ext == ".xls":   # 旧形式 .xls は openpyxl では読めず xlrd が必要
                raise ValueError('.xls の読み込みには xlrd が必要です'
                                 '（pip install "xlrd>=2.0.1"）。') from e
            raise ValueError("Excel(.xlsx) の読み込みには openpyxl が必要です"
                             "（pip install openpyxl）。") from e
        if df.shape[1] == 0:
            raise ValueError("シートから列を読み取れませんでした。")
        return _normalize_columns(df), "excel", "excel"
    # --- 波形・計測形式 ---
    if ext == ".wav":
        return _normalize_columns(_load_wav(path)), "wav", ""
    if ext == ".raw":
        return _normalize_columns(_load_ltspice_raw(path)), "ltspice", ""
    if ext == ".tdms":
        return _normalize_columns(_load_tdms(path)), "tdms", ""
    if ext in (".mf4", ".mdf"):
        return _normalize_columns(_load_mdf(path)), "mdf", ""
    if ext in (".h5", ".hdf5"):
        return _normalize_columns(_load_hdf5(path)), "hdf5", ""

    if encoding is None:
        encoding = detect_encoding(path)
    if delimiter is None:
        delimiter = detect_delimiter(path, encoding)

    # 単一文字区切りは高速な C エンジンで読み、失敗時のみ柔軟な python エンジンへ
    # フォールバックする（C は python の約7倍速い）。複数文字区切り等は python。
    use_c = bool(delimiter) and len(delimiter) == 1
    base_kwargs = dict(sep=delimiter, skip_blank_lines=True)

    def _read(**extra):
        if use_c:
            try:
                return pd.read_csv(path, engine="c", **base_kwargs, **extra)
            except (pd.errors.ParserError, ValueError):
                pass  # 不整列・特殊ケースは python エンジンで再試行
        return pd.read_csv(path, engine="python", **base_kwargs, **extra)

    try:
        df = _read(encoding=encoding)
    except UnicodeDecodeError:
        # 判定した文字コードで読めなければ置換しながら強制的に読み込む
        df = _read(encoding=encoding, encoding_errors="replace")
    except pd.errors.EmptyDataError:
        raise ValueError("ファイルが空か、データ行がありません。")

    if df.shape[1] == 0:
        raise ValueError("列を読み取れませんでした。区切り文字を確認してください。")

    return _normalize_columns(df), encoding, delimiter


def numeric_columns(df):
    """数値として扱える列名の一覧を返す（グラフの値軸候補）。"""
    cols = []
    for c in df.columns:
        s = pd.to_numeric(df[c], errors="coerce")
        if s.notna().mean() >= 0.8:  # 8割以上が数値なら数値列とみなす
            cols.append(c)
    return cols
