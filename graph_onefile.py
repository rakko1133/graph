# -*- coding: utf-8 -*-
"""CSV / TSV / 波形 グラフ・オシロ解析ツール（単一ファイル版）。

全モジュールを結合した版。これ1ファイルだけで動作する（依存: requirements.txt）。
tools/build_onefile.py で再生成できる。使い方:  python graph_onefile.py
"""
import logging
import logging.handlers
import os
import sys
import json
import matplotlib
import matplotlib.font_manager as fm
import csv
import pandas as pd
import numpy as np
import warnings
import warnings  # noqa: F401
import pandas as pd  # noqa: F401
import importlib.util as _ilu
import ast as _ast
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg
import re
from matplotlib.backends.qt_compat import QtCore, QtGui, QtWidgets
from matplotlib.backends.backend_qtagg import (
    FigureCanvasQTAgg as FigureCanvas,
    NavigationToolbar2QT as NavigationToolbar,
)

"""アプリのロギング設定（Qt 非依存）。

ファイル（~/.csv_graph_tool/app.log・ローテーション付き）とコンソールへ出力し、
未捕捉の例外も記録する。pythonw（コンソール無し）で無言終了しても、原因が
app.log に残るようにするのが目的。
"""

LOG_DIR = os.path.join(os.path.expanduser("~"), ".csv_graph_tool")
LOG_FILE = os.path.join(LOG_DIR, "app.log")
_logger = None


def setup_logging(level=logging.INFO):
    """ロガーを構成して返す（多重構成しない）。"""
    global _logger
    if _logger is not None:
        return _logger
    logger = logging.getLogger("graphtool")
    logger.setLevel(level)
    logger.handlers.clear()
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(
            LOG_FILE, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except OSError:
        pass  # 書き込めない環境でもアプリは動かす
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    logger.addHandler(ch)
    logger.propagate = False
    _logger = logger
    return logger


def get_logger():
    """構成済みロガー（未構成なら構成して返す）。"""
    return _logger or setup_logging()


def install_excepthook(on_error=None):
    """未捕捉例外を app.log に記録する。on_error(text) があれば併せて呼ぶ（GUI通知用）。"""
    logger = get_logger()

    def _hook(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        logger.critical("未捕捉の例外", exc_info=(exc_type, exc, tb))
        if on_error is not None:
            try:
                on_error(f"{exc_type.__name__}: {exc}")
            except Exception:  # noqa: BLE001  通知失敗でフックを壊さない
                pass

    sys.excepthook = _hook

# ======================================================================
# ↑ py
# ======================================================================
"""設定（グラフ・解析・表示状態）の保存と読み込み。

UI の状態を 1 つの dict にまとめ、JSON で保存／読込する。
アプリ終了時の自動保存・起動時の自動復元にも使う。
"""


# 自動保存先（ユーザーごとの設定フォルダ）
APP_DIR = os.path.join(os.path.expanduser("~"), ".csv_graph_tool")
LAST_CONFIG = os.path.join(APP_DIR, "last_session.json")

CONFIG_VERSION = 1


def ensure_app_dir():
    os.makedirs(APP_DIR, exist_ok=True)
    return APP_DIR


def save_config(config, path):
    """設定 dict を JSON で保存する。"""
    data = dict(config)
    data["_version"] = CONFIG_VERSION
    folder = os.path.dirname(os.path.abspath(path))
    if folder:
        os.makedirs(folder, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def load_config(path):
    """JSON から設定 dict を読み込む。失敗時は None。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def save_last_session(config):
    """終了時の自動保存。"""
    try:
        ensure_app_dir()
        return save_config(config, LAST_CONFIG)
    except OSError:
        return None


def load_last_session():
    """起動時の自動復元。無ければ None。"""
    if os.path.isfile(LAST_CONFIG):
        return load_config(LAST_CONFIG)
    return None

# ======================================================================
# ↑ py
# ======================================================================
"""matplotlib に日本語フォントを設定するユーティリティ。

OS にインストールされている一般的な日本語フォントを優先順に探し、
最初に見つかったものを matplotlib の既定フォントに設定する。
タイトル・軸ラベル・凡例の日本語が文字化け（□□□）しないようにする。
"""


# 優先順位（上から順に探す）。Windows / macOS / Linux の代表的な日本語フォント。
_CANDIDATES = [
    # Windows
    "Yu Gothic", "Meiryo", "BIZ UDGothic", "MS Gothic", "MS PGothic", "Yu Mincho",
    # macOS
    "Hiragino Sans", "Hiragino Kaku Gothic Pro", "Hiragino Maru Gothic Pro",
    # Linux（インストールされていれば）
    "Noto Sans CJK JP", "IPAexGothic", "IPAGothic", "TakaoGothic", "VL Gothic",
]


def available_japanese_fonts():
    """利用可能な日本語フォント名の一覧を優先順で返す。"""
    installed = {f.name for f in fm.fontManager.ttflist}
    return [name for name in _CANDIDATES if name in installed]


def setup_japanese_font(preferred=None):
    """日本語フォントを matplotlib に設定し、採用したフォント名を返す。

    Parameters
    ----------
    preferred : str | None
        明示的に使いたいフォント名。利用可能ならこれを最優先で採用する。

    Returns
    -------
    str | None
        採用したフォント名。見つからなければ None。
    """
    installed = {f.name for f in fm.fontManager.ttflist}

    order = []
    if preferred:
        order.append(preferred)
    order.extend(_CANDIDATES)

    for name in order:
        if name in installed:
            # sans-serif の先頭に入れておくと未指定箇所でも日本語が出る
            matplotlib.rcParams["font.family"] = "sans-serif"
            current = matplotlib.rcParams.get("font.sans-serif", [])
            matplotlib.rcParams["font.sans-serif"] = [name] + [
                f for f in current if f != name
            ]
            matplotlib.rcParams["axes.unicode_minus"] = False  # マイナス記号の文字化け防止
            return name

    # 日本語フォントが見つからない場合も、最低限マイナス記号の化けだけは防ぐ
    matplotlib.rcParams["axes.unicode_minus"] = False
    return None

# ======================================================================
# ↑ py
# ======================================================================
"""CSV / TSV ファイルの読み込み。

文字コード（UTF-8 / UTF-8 BOM付き / Shift_JIS(CP932) など）と
区切り文字（カンマ / タブ / セミコロン）を自動判定して
pandas.DataFrame として読み込む。日本語 CSV を想定。
"""



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


def load_table(path, encoding=None, delimiter=None):
    """CSV/TSV/Excel を読み込み (DataFrame, 使用した encoding, 使用した delimiter) を返す。

    encoding / delimiter を None にすると自動判定する。.xlsx/.xls/.xlsm は Excel として読む。
    """
    if not os.path.isfile(path):
        raise FileNotFoundError(f"ファイルが見つかりません: {path}")

    # --- Excel（先頭シート）---
    if os.path.splitext(path)[1].lower() in (".xlsx", ".xlsm", ".xls"):
        try:
            df = pd.read_excel(path)
        except ImportError as e:
            raise ValueError("Excel(.xlsx) の読み込みには openpyxl が必要です"
                             "（pip install openpyxl）。") from e
        if df.shape[1] == 0:
            raise ValueError("シートから列を読み取れませんでした。")
        return _normalize_columns(df), "excel", "excel"

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

# ======================================================================
# ↑ py
# ======================================================================
"""SI接頭辞つき数値フォーマット（format_eng / parse_eng / eng_125_sequence）。"""


def _eng(x):
    """工学接頭辞付きの簡易表記。"""
    if x == 0:
        return "0"
    units = [(1e-12, "p"), (1e-9, "n"), (1e-6, "µ"), (1e-3, "m"),
             (1, ""), (1e3, "k"), (1e6, "M"), (1e9, "G")]
    for factor, suf in units:
        if abs(x) < factor * 1000:
            return f"{x / factor:.3g}{suf}"
    return f"{x:.3g}"


format_eng = _eng  # 公開名


_ENG_MULT = {"p": 1e-12, "n": 1e-9, "u": 1e-6, "µ": 1e-6, "m": 1e-3,
             "k": 1e3, "M": 1e6, "G": 1e9}


def parse_eng(text, default=None):
    """'1ms' '500us' '2.5' '1e-3' のような入力を float へ変換する。"""
    s = (text or "").strip()
    if not s:
        return default
    try:
        return float(s)  # 1e-3 などはここで確定
    except ValueError:
        pass
    import re
    m = re.match(r"^\s*([+-]?[\d.]+)\s*([a-zA-Zµ]*)", s)
    if not m:
        return default
    try:
        num = float(m.group(1))
    except ValueError:
        return default
    for ch in m.group(2):           # 単位中の SI 接頭辞を探す
        if ch in _ENG_MULT:
            return num * _ENG_MULT[ch]
    return num                       # 単位のみ（例 '2V'）は倍率なし


def eng_125_sequence(lo, hi, suffix=""):
    """lo〜hi を 1-2-5 刻みで並べた表示文字列のリストを返す（オシロのプリセット用）。"""
    seq, dec = [], -12
    while 10.0 ** dec <= hi * 1.0001:
        for m in (1, 2, 5):
            v = m * 10.0 ** dec
            if lo * 0.9999 <= v <= hi * 1.0001:
                seq.append(format_eng(v) + suffix)
        dec += 1
    return seq

# ======================================================================
# ↑ py
# ======================================================================
"""低レベル描画（各グラフ種別の _draw_*・近似曲線・間引き・オシロ格子）。"""




DEFAULT_STYLE = {
    "color": None,        # None なら matplotlib の既定カラーサイクル
    "linestyle": "-",
    "linewidth": 1.5,
    "marker": "",
    "markersize": 4.0,
    "alpha": 1.0,
}


def style_for(series):
    s = dict(DEFAULT_STYLE)
    s.update(series.get("style") or {})
    return s


def _coerce_x(values):
    """X 軸の値を数値 / 日時 / カテゴリへ変換し (values, kind) を返す。"""
    s = pd.Series(values)
    num = pd.to_numeric(s, errors="coerce")
    if num.notna().mean() >= 0.8:
        return num.to_numpy(dtype=float), "numeric"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            dt = pd.to_datetime(s, errors="coerce")
        except Exception:
            dt = pd.Series([pd.NaT] * len(s))
    if dt.notna().mean() >= 0.8:
        return dt.to_numpy(), "datetime"
    return s.astype(str).to_numpy(), "category"


def _num(values):
    return pd.to_numeric(pd.Series(values), errors="coerce").to_numpy(dtype=float)


def fit_trendline(x, y, kind, degree=2, window=5):
    """近似曲線を計算する。

    戻り値: (xfit, yfit, equation, r2) または None
      equation は数式文字列、r2 は決定係数（移動平均は None）。
    """
    x = np.asarray(_num(x), dtype=float)
    y = np.asarray(_num(y), dtype=float)
    m = np.isfinite(x) & np.isfinite(y)
    x, y = x[m], y[m]
    if len(x) < 2:
        return None
    order = np.argsort(x)
    x, y = x[order], y[order]
    eq = ""
    try:
        if kind == "線形":
            c = np.polyfit(x, y, 1)
            yf = np.polyval(c, x)
            eq = f"y={c[0]:.4g}x{c[1]:+.4g}"
        elif kind == "多項式":
            deg = int(max(1, min(degree, 6)))
            if len(x) <= deg:
                return None
            c = np.polyfit(x, y, deg)
            yf = np.polyval(c, x)
            terms = [f"{cc:+.3g}x^{deg - i}" for i, cc in enumerate(c[:-1])]
            eq = "y=" + "".join(terms) + f"{c[-1]:+.3g}"
        elif kind == "指数":              # y = a*exp(b x)
            pos = y > 0
            if pos.sum() < 2:
                return None
            # log線形回帰で初期値 → scipy.optimize.curve_fit で非線形最小二乗に精密化。
            # （log線形だけだと小さいyを過大評価して偏るため。scipy無し時は初期値を使う）
            c = np.polyfit(x[pos], np.log(y[pos]), 1)
            a, b = float(np.exp(c[1])), float(c[0])
            try:
                from scipy.optimize import curve_fit
                (a, b), _ = curve_fit(lambda xx, A, B: A * np.exp(B * xx), x, y,
                                      p0=(a, b), maxfev=10000)
                a, b = float(a), float(b)
            except Exception:
                pass
            yf = a * np.exp(b * x)
            eq = f"y={a:.4g}·e^({b:.4g}x)"
        elif kind == "対数":              # y = a*ln(x) + b（x>0）
            pos = x > 0
            if pos.sum() < 2:
                return None
            x, y = x[pos], y[pos]
            c = np.polyfit(np.log(x), y, 1)
            yf = c[0] * np.log(x) + c[1]
            eq = f"y={c[0]:.4g}·ln(x){c[1]:+.4g}"
        elif kind == "移動平均":
            w = int(max(2, min(window, len(y))))
            kern = np.ones(w) / w
            yf = np.convolve(y, kern, mode="same")
            return x, yf, f"移動平均(窓={w})", None
        elif kind in ("ガウシアン", "ローレンツ", "シグモイド"):
            # 非線形最小二乗（scipy 必須）。滑らかな曲線で返す。R² は実データ点で算出。
            try:
                from scipy.optimize import curve_fit
            except Exception:
                return None
            if len(x) < 4:
                return None
            span = float(x.max() - x.min()) or 1.0
            ymin, ymax = float(np.min(y)), float(np.max(y))
            amp = (ymax - ymin) or 1.0
            xpeak = float(x[int(np.argmax(y))])
            if kind == "ガウシアン":
                def model(xx, a, mu, sg, c):
                    return a * np.exp(-((xx - mu) ** 2) / (2.0 * sg * sg)) + c
                p0 = (amp, xpeak, span / 6.0, ymin)
            elif kind == "ローレンツ":
                def model(xx, a, x0, g, c):
                    return a / (1.0 + ((xx - x0) / g) ** 2) + c
                p0 = (amp, xpeak, span / 6.0, ymin)
            else:  # シグモイド
                def model(xx, L, k, x0, c):
                    return L / (1.0 + np.exp(-k * (xx - x0))) + c
                slope = 4.0 / span * (1.0 if y[-1] >= y[0] else -1.0)
                p0 = (amp, slope, float(np.median(x)), ymin)
            try:
                popt, _ = curve_fit(model, x, y, p0=p0, maxfev=20000)
            except Exception:
                return None
            yf_d = model(x, *popt)
            ss_res = float(np.sum((y - yf_d) ** 2))
            ss_tot = float(np.sum((y - np.mean(y)) ** 2))
            r2 = (1 - ss_res / ss_tot) if ss_tot > 0 else None
            xfit = np.linspace(float(x.min()), float(x.max()), 200)
            if kind == "ガウシアン":
                eq = f"ガウシアン μ={popt[1]:.3g} σ={abs(popt[2]):.3g}"
            elif kind == "ローレンツ":
                eq = f"ローレンツ x0={popt[1]:.3g} γ={abs(popt[2]):.3g}"
            else:
                eq = f"シグモイド x0={popt[2]:.3g} k={popt[1]:.3g}"
            return xfit, model(xfit, *popt), eq, r2
        else:
            return None
    except Exception:
        return None
    ss_res = float(np.sum((y - yf) ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    r2 = (1 - ss_res / ss_tot) if ss_tot > 0 else None
    return x, yf, eq, r2


def _data_labels(ax, xx, yy, color, fontsize, cap=40, fmt="{:.3g}"):
    """各データ点に値ラベルを付ける（点数が多い場合は間引き）。"""
    xx = np.asarray(xx, dtype=float)
    yy = np.asarray(yy, dtype=float)
    n = len(yy)
    step = max(1, int(np.ceil(n / cap)))
    for i in range(0, n, step):
        if not (np.isfinite(xx[i]) and np.isfinite(yy[i])):
            continue
        ax.annotate(fmt.format(yy[i]), (xx[i], yy[i]),
                    textcoords="offset points", xytext=(0, 5),
                    ha="center", fontsize=max(7, fontsize - 1), color=color or "#333")


def _remove_twin(ax):
    """前回作った第2軸(twinx)を図から取り除く。"""
    ax2 = getattr(ax, "_twin_secondary", None)
    if ax2 is not None:
        try:
            ax2.remove()
        except Exception:
            pass
    ax._twin_secondary = None


def _bar_width(xx):
    """数値Xに棒を描くときの適切な幅。"""
    xx = np.asarray(xx, dtype=float)
    xx = xx[np.isfinite(xx)]
    if len(xx) < 2:
        return 0.8
    d = np.diff(np.sort(xx))
    d = d[d > 0]
    return float(np.min(d) * 0.8) if len(d) else 0.8


def _draw_xy(ax, series, line=True, max_points=0, ax2=None, data_labels=False,
             trendline=None, fonts=None):
    # 各系列の X を評価し、カテゴリがあれば全系列で共有する位置マッピングを作る
    # （系列ごとに目盛りラベルを上書きして取り違える不具合を防ぐ）。
    fonts = fonts or {}
    fs = fonts.get("tick", 9)
    prepared = []
    cat_order, cat_pos = [], {}
    for sr in series:
        x_raw = sr.get("x")
        y = _num(sr["y"])
        if x_raw is None:
            prepared.append(("index", None, y, sr))
            continue
        x, kind = _coerce_x(x_raw)
        if kind == "category":
            for lab in x:
                if lab not in cat_pos:
                    cat_pos[lab] = len(cat_order)
                    cat_order.append(lab)
        prepared.append((kind, x, y, sr))

    # 棒の本数（複合グラフで棒が複数あるとき横に並べる）
    bar_series = [sr for *_unused, sr in prepared
                  if (sr.get("kind") or "") == "bar"]
    n_bars = max(1, len(bar_series))
    bar_idx = 0
    any_decimated = False

    for kind, x, y, sr in prepared:
        st = style_for(sr)
        target = ax2 if (ax2 is not None and sr.get("axis") == "secondary") else ax
        skind = sr.get("kind") or ("line" if line else "scatter")
        yerr = sr.get("yerr")
        yerr = _num(yerr) if yerr is not None else None
        if kind == "index":
            xx = np.arange(len(y))
        elif kind == "category":
            xx = np.array([cat_pos[lab] for lab in x], dtype=float)
        else:
            xx = np.asarray(x, dtype=float)
        # 大容量データの間引き（カテゴリ以外・誤差バー無し・線/散布のみ）
        decim = (max_points and kind != "category" and yerr is None
                 and skind in ("line", "scatter") and len(y) > max_points)
        if decim:
            if skind == "line":
                xx, yv = decimate_minmax(xx, y, max_points)
            else:
                step = max(1, len(y) // max_points)
                xx, yv = np.asarray(xx)[::step], np.asarray(y)[::step]
            any_decimated = True
        else:
            yv = y

        if skind == "bar":
            w = _bar_width(xx) / n_bars
            off = (bar_idx - (n_bars - 1) / 2) * w
            bar_idx += 1
            target.bar(np.asarray(xx, float) + off, yv, width=w, label=sr["label"],
                       color=st["color"], alpha=min(st["alpha"], 0.85),
                       yerr=yerr if yerr is not None else None, capsize=3)
        elif skind == "area":
            target.fill_between(xx, yv, color=st["color"], alpha=min(st["alpha"], 0.4))
            target.plot(xx, yv, label=sr["label"], color=st["color"],
                        linewidth=st["linewidth"], alpha=st["alpha"])
        elif skind == "scatter":
            target.scatter(xx, yv, label=sr["label"], color=st["color"],
                           s=st["markersize"] ** 2, marker=st["marker"] or "o",
                           alpha=st["alpha"])
            if yerr is not None:
                target.errorbar(xx, yv, yerr=yerr[:len(yv)], fmt="none",
                                 ecolor=st["color"], alpha=st["alpha"], capsize=3)
        else:   # line
            if yerr is not None:
                target.errorbar(xx, yv, yerr=yerr[:len(yv)], label=sr["label"],
                                color=st["color"], linestyle=st["linestyle"],
                                linewidth=st["linewidth"], marker=st["marker"],
                                markersize=st["markersize"], alpha=st["alpha"], capsize=3)
            else:
                target.plot(xx, yv, label=sr["label"], color=st["color"],
                            linestyle=st["linestyle"], linewidth=st["linewidth"],
                            marker=st["marker"], markersize=st["markersize"],
                            alpha=st["alpha"])

        if data_labels:
            _data_labels(target, xx, yv, st["color"], fs)

        # --- 近似曲線（線/散布/面のみ。数値X限定）---
        if (trendline and trendline.get("type") not in (None, "なし")
                and kind in ("numeric", "index") and skind != "bar"):
            fit = fit_trendline(xx, yv, trendline["type"],
                                degree=trendline.get("degree", 2),
                                window=trendline.get("window", 5))
            if fit is not None:
                xf, yf, eq, r2 = fit
                lab = f"{sr['label']} 近似: {eq}"
                if r2 is not None and trendline.get("show_eq"):
                    lab += f"  (R²={r2:.4f})"
                elif not trendline.get("show_eq"):
                    lab = None
                tcolor = trendline.get("color") or st["color"] or "#444"
                target.plot(xf, yf, color=tcolor, linestyle="--",
                            linewidth=1.3, alpha=0.9, label=lab)

    if any_decimated:  # 間引きしたことを示す（軸ラベルは GUI 側で付与）
        ax._decimated = True

    if cat_order:
        ax.set_xticks(range(len(cat_order)))
        ax.set_xticklabels(cat_order, rotation=45 if len(cat_order) > 6 else 0,
                           ha="right" if len(cat_order) > 6 else "center")


def _draw_hist(ax, series, bins):
    data, labels, colors = [], [], []
    for sr in series:
        y = _num(sr["y"])
        y = y[~np.isnan(y)]
        if len(y):
            data.append(y)
            labels.append(sr["label"])
            colors.append(style_for(sr)["color"])
    if not data:
        raise ValueError("ヒストグラムに使える数値データがありません。")
    colors = colors if all(c for c in colors) else None
    ax.hist(data, bins=int(bins), alpha=0.6, label=labels, color=colors)


def _draw_box(ax, series):
    data, labels = [], []
    for sr in series:
        y = _num(sr["y"])
        y = y[~np.isnan(y)]
        if len(y):
            data.append(y)
            labels.append(sr["label"])
    if not data:
        raise ValueError("箱ひげ図に使える数値データがありません。")
    try:
        ax.boxplot(data, tick_labels=labels)
    except TypeError:
        ax.boxplot(data, labels=labels)


def _draw_bar(ax, series, categories, horizontal=False, stacked=False,
              data_labels=False, fonts=None):
    fs = (fonts or {}).get("tick", 9)
    labels = np.asarray([str(c) for c in categories])
    pos = np.arange(len(labels))
    data = [(sr["label"], _num(sr["y"]), style_for(sr)) for sr in series]

    def _label_bars(bars, vals):
        if not data_labels:
            return
        for b, v in zip(bars, vals):
            if not np.isfinite(v):
                continue
            if horizontal:
                ax.annotate(f"{v:.3g}", (b.get_width(), b.get_y() + b.get_height() / 2),
                            textcoords="offset points", xytext=(3, 0),
                            va="center", ha="left", fontsize=max(7, fs - 1))
            else:
                ax.annotate(f"{v:.3g}", (b.get_x() + b.get_width() / 2, b.get_height()),
                            textcoords="offset points", xytext=(0, 3),
                            va="bottom", ha="center", fontsize=max(7, fs - 1))

    if stacked or len(data) == 1:
        bottom = np.zeros(len(labels))
        for name, vals, st in data:
            vals = np.nan_to_num(vals[:len(labels)])
            if horizontal:
                bars = ax.barh(pos, vals, left=bottom, label=name, color=st["color"], alpha=st["alpha"])
            else:
                bars = ax.bar(pos, vals, bottom=bottom, label=name, color=st["color"], alpha=st["alpha"])
            if not stacked:
                _label_bars(bars, vals)
            bottom = bottom + vals
    else:
        n = len(data)
        width = 0.8 / n
        for i, (name, vals, st) in enumerate(data):
            vals = np.nan_to_num(vals[:len(labels)])
            off = (i - (n - 1) / 2) * width
            if horizontal:
                bars = ax.barh(pos + off, vals, height=width, label=name, color=st["color"], alpha=st["alpha"])
            else:
                bars = ax.bar(pos + off, vals, width=width, label=name, color=st["color"], alpha=st["alpha"])
            _label_bars(bars, vals)

    if horizontal:
        ax.set_yticks(pos)
        ax.set_yticklabels(labels)
    else:
        ax.set_xticks(pos)
        ax.set_xticklabels(labels, rotation=45 if len(labels) > 6 else 0,
                           ha="right" if len(labels) > 6 else "center")


def _draw_pie(ax, sr, categories, pct=False):
    labels = np.asarray([str(c) for c in categories])
    values = np.nan_to_num(_num(sr["y"]))
    n = min(len(labels), len(values))
    labels, values = labels[:n], values[:n]
    mask = values > 0
    labels, values = labels[mask], values[mask]
    if len(values) == 0:
        raise ValueError("円グラフに使える正の数値データがありません。")
    ax.pie(values, labels=labels, autopct="%1.1f%%" if pct else None,
           startangle=90, counterclock=False)
    ax.axis("equal")


def _is_dark(color):
    """色（名前/HEX）が暗いか（相対輝度<0.45）。目盛り色などの自動切替に使う。"""
    try:
        from matplotlib.colors import to_rgb
        r, g, b = to_rgb(color)
        return (0.299 * r + 0.587 * g + 0.114 * b) < 0.45
    except Exception:
        return True


def _apply_scope(ax, scope, bg_color=""):
    """オシロスコープ風の div グリッドと表示範囲を設定する。

    背景色は bg_color（空なら従来の濃色 #0b0f0b）。背景の明暗に応じて
    目盛り・グリッド・情報文字の色を自動で見やすく切り替える。
    """
    xd = int(scope.get("x_divs", 10))
    yd = int(scope.get("y_divs", 8))
    tpd = float(scope.get("t_per_div", 1.0))
    vpd = float(scope.get("v_per_div", 1.0))
    xc = float(scope.get("x_pos", 0.0))
    yc = float(scope.get("y_pos", 0.0))

    x0, x1 = xc - xd / 2 * tpd, xc + xd / 2 * tpd
    y0, y1 = yc - yd / 2 * vpd, yc + yd / 2 * vpd
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.set_xticks(np.linspace(x0, x1, xd + 1))
    ax.set_yticks(np.linspace(y0, y1, yd + 1))
    bg = bg_color or "#0b0f0b"
    dark = _is_dark(bg)
    ax.grid(True, which="major", color=("#888" if dark else "#aaa"),
            linestyle="-", linewidth=0.6, alpha=0.5)
    ax.set_facecolor(bg)
    ax.tick_params(colors=("#888" if dark else "#555"), labelsize=8)
    # スコープ情報（背景の明暗で文字/箱の色を切替）
    info_fg = "#7CFC00" if dark else "#0a7a30"
    info_bg = "black" if dark else "white"
    ax.text(0.01, 0.99, f"{_eng(tpd)}s/div   {_eng(vpd)}V/div",
            transform=ax.transAxes, va="top", ha="left",
            color=info_fg, fontsize=9,
            bbox=dict(facecolor=info_bg, alpha=0.4, edgecolor="none"))


def decimate_minmax(x, y, max_points):
    """点数が多い波形を min/max エンベロープで間引く（見た目を保ったまま高速化）。

    各ビンの最小値・最大値の点を時間順に残すので、波形の包絡が保たれる。
    等幅ビンを reshape して per-bin の最小/最大インデックスを numpy でベクトル化
    （旧 Python ループ比 約30倍高速）。端数は最後のビンに併合する。
    """
    x = np.asarray(x)
    y = np.asarray(y, dtype=float)
    n = len(y)
    if n <= max_points or max_points < 4:
        return x, y
    n_bins = max(1, max_points // 2)
    bin_size = n // n_bins
    if bin_size < 1:
        return x, y
    main = bin_size * n_bins
    Y = y[:main].reshape(n_bins, bin_size)
    starts = np.arange(n_bins) * bin_size
    if np.isfinite(Y).all():   # NaN/inf 無し（一般ケース）は素の argmin/argmax で最速
        lo = starts + np.argmin(Y, axis=1)
        hi = starts + np.argmax(Y, axis=1)
    else:                      # NaN/inf は finite 優先で除外（全NaN行は先頭=0）
        lo = starts + np.argmin(np.where(np.isfinite(Y), Y, np.inf), axis=1)
        hi = starts + np.argmax(np.where(np.isfinite(Y), Y, -np.inf), axis=1)
    if main < n:   # 末尾の端数は最後のビンに併合して取り直す
        base = int(starts[-1])
        seg = y[base:n]
        fin = np.isfinite(seg)
        lo[-1] = base + int(np.argmin(np.where(fin, seg, np.inf)))
        hi[-1] = base + int(np.argmax(np.where(fin, seg, -np.inf)))
    first = np.minimum(lo, hi)     # 時間順（先のインデックス→後のインデックス）
    second = np.maximum(lo, hi)
    idx = np.empty(2 * n_bins, dtype=np.int64)
    idx[0::2] = first
    idx[1::2] = second
    return x[idx], y[idx]

# ======================================================================
# ↑ py
# ======================================================================
"""グラフ描画ロジック（系列ベース）。

複数ファイル由来の系列をまとめて描画でき、系列ごとに色・線種・線幅・マーカーを
指定できる。軸範囲・対数軸・凡例位置などの編集にも対応。さらにオシロスコープ風の
div グリッド表示（time/div・V/div・位置オフセット）をサポートする。

GUI から独立しているので単体でも利用・テストできる。
"""




# plot_series が直接呼ぶ低レベル描画（アンダースコア）を取り込む


CHART_TYPES = [
    "折れ線",
    "棒",
    "横棒",
    "積み上げ棒",
    "散布図",
    "ヒストグラム",
    "箱ひげ",
    "円",
]


CHART_INFO = {
    "折れ線": {"use_x": True, "multi_y": True, "multi_file": True,
              "hint": "X軸に1列、Y軸に1列以上。複数ファイルの重ね描き可"},
    "棒": {"use_x": True, "multi_y": True, "multi_file": False,
          "hint": "X軸にカテゴリ列、Y軸に1列以上（単一ファイル）"},
    "横棒": {"use_x": True, "multi_y": True, "multi_file": False,
            "hint": "X軸にカテゴリ列、Y軸に1列以上（単一ファイル）"},
    "積み上げ棒": {"use_x": True, "multi_y": True, "multi_file": False,
                "hint": "X軸にカテゴリ列、Y軸に2列以上（単一ファイル）"},
    "散布図": {"use_x": True, "multi_y": True, "multi_file": True,
            "hint": "X軸に1列、Y軸に1列以上。複数ファイル可"},
    "ヒストグラム": {"use_x": False, "multi_y": True, "multi_file": True,
                "hint": "Y軸に値の列を1列以上（分布を表示）。複数ファイル可"},
    "箱ひげ": {"use_x": False, "multi_y": True, "multi_file": True,
            "hint": "Y軸に値の列を1列以上。複数ファイル可"},
    "円": {"use_x": True, "multi_y": False, "multi_file": False,
          "hint": "X軸にラベル列、Y軸に値の列を1つ（単一ファイル）"},
}


LINESTYLES = {"実線": "-", "破線": "--", "一点鎖線": "-.", "点線": ":", "なし": "None"}


MARKERS = {"なし": "", "丸": "o", "四角": "s", "三角": "^", "菱形": "D",
           "× ": "x", "＋": "+", "点": "."}


LEGEND_LOCS = ["best", "upper right", "upper left", "lower left",
               "lower right", "right", "center left", "center right",
               "lower center", "upper center", "center"]


TRENDLINES = ["なし", "線形", "多項式", "指数", "対数", "移動平均",
              "ガウシアン", "ローレンツ", "シグモイド"]


SERIES_KINDS = {"自動": "", "折れ線": "line", "棒": "bar", "面": "area",
                "散布図": "scatter"}


SERIES_AXES = {"主軸": "primary", "第2軸": "secondary"}


def plot_series(
    ax,
    series,
    chart_type,
    *,
    categories=None,
    bins=10,
    title="",
    xlabel="",
    ylabel="",
    grid=True,
    legend=True,
    legend_loc="best",
    xlim=None,
    ylim=None,
    xlog=False,
    ylog=False,
    pct=False,
    fonts=None,
    scope=None,
    markers=None,
    max_points=0,
    trendline=None,
    data_labels=False,
    secondary_label="",
    xscale=1.0,
    yscale=1.0,
    xunit="",
    yunit="",
    bg_color="",
    grid_width=None,
    frame_width=None,
    xinvert=False,
    yinvert=False,
):
    """ax に系列群を描画する。

    series : list of dict
        折れ線/散布図: {label, x, y, style}
        ヒストグラム/箱ひげ: {label, y, style}
        棒/横棒/積み上げ棒: {label, y, style}（categories に X ラベル配列）
        円: {label, y, style}（categories にラベル、y[0] を使用）
    """
    info = CHART_INFO.get(chart_type)
    if info is None:
        raise ValueError(f"未知のグラフ種別です: {chart_type}")
    if not series:
        raise ValueError("Y軸（値）の系列を選択してください。")
    fonts = fonts or {}

    # --- 単位換算: 軸の数値を倍率でスケール（X=全系列の共有軸、Y=主軸の系列のみ）。
    #     系列dictは描画ごとに作り直されるが、念のためコピーしてから掛ける。
    if xscale != 1.0 or yscale != 1.0:
        scaled = []
        for sr in series:
            sr = dict(sr)
            if xscale != 1.0 and sr.get("x") is not None:
                sr["x"] = np.asarray(sr["x"], dtype=float) * xscale
            if yscale != 1.0 and sr.get("axis") != "secondary" and sr.get("y") is not None:
                sr["y"] = np.asarray(sr["y"], dtype=float) * yscale
                if sr.get("yerr") is not None:
                    sr["yerr"] = np.asarray(sr["yerr"], dtype=float) * yscale
            scaled.append(sr)
        series = scaled

    ax.clear()
    _remove_twin(ax)               # 前回の第2軸を掃除
    ax.set_aspect("auto")          # 円グラフの equal を持ち越さない
    ax.set_facecolor(bg_color or "white")   # 背景色（空=白）。オシロは下で上書き
    ax.tick_params(colors="black")  # オシロ表示の目盛り色を既定へ戻す

    ax2 = None
    if chart_type in ("折れ線", "散布図"):
        if any((sr.get("axis") == "secondary") for sr in series):
            ax2 = ax.twinx()
            ax._twin_secondary = ax2
            if secondary_label:
                ax2.set_ylabel(secondary_label, fontsize=(fonts or {}).get("label", 10))
        _draw_xy(ax, series, line=(chart_type == "折れ線"),
                 max_points=max_points, ax2=ax2, data_labels=data_labels,
                 trendline=trendline, fonts=fonts)
    elif chart_type == "ヒストグラム":
        _draw_hist(ax, series, bins)
    elif chart_type == "箱ひげ":
        _draw_box(ax, series)
    elif chart_type in ("棒", "横棒", "積み上げ棒"):
        if categories is None:
            raise ValueError("X軸（カテゴリ）の列を選択してください。")
        _draw_bar(ax, series, categories,
                  horizontal=(chart_type == "横棒"),
                  stacked=(chart_type == "積み上げ棒"),
                  data_labels=data_labels, fonts=fonts)
    elif chart_type == "円":
        if categories is None:
            raise ValueError("X軸（ラベル）の列を選択してください。")
        _draw_pie(ax, series[0], categories, pct=pct)

    # --- タイトル・ラベル ---
    if title:
        ax.set_title(title, fontsize=fonts.get("title", 12))
    if chart_type != "円":
        xl = (f"{xlabel} [{xunit}]".strip() if xunit else xlabel)
        yl_base = ylabel or ("頻度" if chart_type == "ヒストグラム" else "")
        yl = (f"{yl_base} [{yunit}]".strip() if yunit else yl_base)
        ax.set_xlabel(xl, fontsize=fonts.get("label", 10))
        ax.set_ylabel(yl, fontsize=fonts.get("label", 10))
        ax.tick_params(labelsize=fonts.get("tick", 9))

    # --- 対数軸・軸範囲 ---
    # min/max は片側だけの指定でも反映する（例: min=0 のみ → 左端を0に詰め、
    # 自動の5%余白を消す。両方そろわないと無視する旧仕様が「0でも余白が残る」原因だった）。
    if chart_type != "円":
        if xlog:
            ax.set_xscale("log")
        if ylog:
            ax.set_yscale("log")
        if xlim:
            if xlim[0] is not None:
                ax.set_xlim(left=xlim[0])
            if xlim[1] is not None:
                ax.set_xlim(right=xlim[1])
        if ylim:
            if ylim[0] is not None:
                ax.set_ylim(bottom=ylim[0])
            if ylim[1] is not None:
                ax.set_ylim(top=ylim[1])

    # --- オシロスコープ表示（折れ線/散布図のみ）---
    if scope and scope.get("enabled") and chart_type in ("折れ線", "散布図"):
        _apply_scope(ax, scope, bg_color=bg_color)
        grid = True

    # --- 凡例・グリッド ---
    if legend and chart_type != "円":
        handles, labels = ax.get_legend_handles_labels()
        if ax2 is not None:                       # 第2軸の系列も凡例に統合
            h2, l2 = ax2.get_legend_handles_labels()
            handles = handles + h2
            labels = labels + l2
        if handles:
            ax.legend(handles, labels, loc=legend_loc,
                      fontsize=(fonts.get("legend") or fonts.get("tick", 9)))
    if grid and chart_type != "円":
        # grid_width=None は「既定の太さ」。matplotlib は linewidth=None を float(None) に
        # 渡してしまうため、指定があるときだけ linewidth を渡す。
        gkw = {} if grid_width is None else {"linewidth": grid_width}
        ax.grid(True, linestyle="--", alpha=0.4, **gkw)

    # 枠線（spine）の太さ。0 以下なら枠を消す。None なら既定のまま
    if frame_width is not None:
        for sp in ax.spines.values():
            sp.set_linewidth(frame_width)
            sp.set_visible(frame_width > 0)
        if ax2 is not None:
            for sp in ax2.spines.values():
                sp.set_linewidth(frame_width)
                sp.set_visible(frame_width > 0)

    # --- マーカー（ピーク等の注記）---
    if markers:
        for m in markers:
            ax.plot(m["x"], m["y"], m.get("symbol", "v"),
                    color=m.get("color", "red"), markersize=8)
            if m.get("text"):
                ax.annotate(m["text"], (m["x"], m["y"]),
                            textcoords="offset points", xytext=(0, 8),
                            ha="center", color=m.get("color", "red"),
                            fontsize=fonts.get("tick", 9))

    # --- 軸の向き反転（最後に適用。範囲指定・オシロ表示の後でも効く）---
    if chart_type != "円":
        if xinvert and not ax.xaxis_inverted():
            ax.invert_xaxis()
        if yinvert and not ax.yaxis_inverted():
            ax.invert_yaxis()
    return ax


def build_series_from_df(df, chart_type, x_col, y_cols):
    """単一 DataFrame から系列リストと categories を作る（後方互換・簡易用途）。"""
    info = CHART_INFO[chart_type]
    y_cols = list(y_cols or [])
    categories = None
    series = []
    if chart_type in ("棒", "横棒", "積み上げ棒", "円"):
        categories = df[x_col].to_numpy()
        for c in y_cols:
            series.append({"label": c, "y": df[c].to_numpy()})
    elif chart_type in ("折れ線", "散布図"):
        xv = df[x_col].to_numpy()
        for c in y_cols:
            series.append({"label": c, "x": xv, "y": df[c].to_numpy()})
    else:  # ヒストグラム / 箱ひげ
        for c in y_cols:
            series.append({"label": c, "y": df[c].to_numpy()})
    return series, categories


def plot(ax, df, chart_type, x_col=None, y_cols=None, *, bins=10, title="",
         xlabel="", ylabel="", grid=True, legend=True, pct=False):
    """単一 DataFrame 版の簡易インターフェース（テスト・後方互換用）。"""
    info = CHART_INFO.get(chart_type)
    if info is None:
        raise ValueError(f"未知のグラフ種別です: {chart_type}")
    if info["use_x"] and not x_col:
        raise ValueError("X軸の列を選択してください。")
    if not y_cols:
        raise ValueError("Y軸（値）の列を選択してください。")
    series, categories = build_series_from_df(df, chart_type, x_col, y_cols)
    return plot_series(ax, series, chart_type, categories=categories, bins=bins,
                       title=title, xlabel=xlabel or (x_col or ""), ylabel=ylabel,
                       grid=grid, legend=legend, pct=pct)

# ======================================================================
# ↑ py
# ======================================================================
"""解析の共通プリミティブ（窓関数・ピーク検出・ゼロ交差・Top/Base 等）。"""


_trapz = getattr(np, "trapezoid", None) or np.trapz
_HAVE_SCIPY = _ilu.find_spec("scipy") is not None
WINDOWS = ["hann", "hamming", "blackman", "blackmanharris", "flattop",
           "kaiser", "gaussian", "rect"]


def sampling_rate(t):
    """時間軸 t[s] から平均サンプリング周波数[Hz]を推定する。"""
    t = np.asarray(t, dtype=float)
    if t.size < 2:
        return None
    dt = np.median(np.diff(t))
    return 1.0 / dt if dt > 0 else None


def _simple_peaks(sig, distance=1):
    """scipy が無い場合の素朴な極大検出。"""
    idx = np.where((sig[1:-1] > sig[:-2]) & (sig[1:-1] >= sig[2:]))[0] + 1
    return idx


def smooth_signal(y, window):
    """移動窓で平滑化（Savitzky-Golay 優先、無ければ移動平均）。ノイズ低減用。"""
    y = np.asarray(y, dtype=float)
    w = int(window)
    if w < 3 or w > y.size:
        return y
    if w % 2 == 0:
        w += 1
    try:
        from scipy.signal import savgol_filter
        return savgol_filter(y, w, min(2, w - 1))
    except Exception:
        k = np.ones(w) / w
        return np.convolve(y, k, mode="same")


def find_signal_peaks(y, t=None, n=5, prominence_frac=0.05, distance=None,
                      mode="max", smooth=0):
    """信号の主要ピークを上位 n 個、顕著さ(prominence)順で返す。

    第1ピーク・第2ピーク…のように rank 付きで返す。mode="min" で谷を検出。
    smooth>=3 で平滑化してからピーク検出し、ノイズの偽ピークを抑える。

    Returns: list of dict {rank, index, time, value, prominence}
    """
    y = np.asarray(y, dtype=float)
    if y.size < 3:
        return []
    if smooth and smooth >= 3:
        y = smooth_signal(y, smooth)   # 平滑化後の信号でピークを評価
    sig = y if mode == "max" else -y
    span = float(np.nanmax(y) - np.nanmin(y))
    prom = prominence_frac * span if span > 0 else None

    if _HAVE_SCIPY:
        from scipy.signal import find_peaks   # 遅延import（起動を軽くする）
        kwargs = {}
        if prom:
            kwargs["prominence"] = prom
        if distance:
            kwargs["distance"] = int(distance)
        idx, props = find_peaks(sig, **kwargs)
        proms = props.get("prominences")
    else:
        idx = _simple_peaks(sig, distance or 1)
        proms = None

    if len(idx) == 0:
        return []

    if proms is not None and len(proms):
        order = np.argsort(proms)[::-1]
    else:
        order = np.argsort(sig[idx])[::-1]
        proms = np.full(len(idx), np.nan)

    idx_sorted = idx[order][:n]
    prom_sorted = np.asarray(proms)[order][:n]

    peaks = []
    for rank, (i, pr) in enumerate(zip(idx_sorted, prom_sorted), start=1):
        peaks.append({
            "rank": rank,
            "index": int(i),
            "time": float(t[i]) if t is not None else None,
            "value": float(y[i]),
            "prominence": float(pr) if pr == pr else None,  # NaN 判定
        })
    return peaks


def _zero_crossing_period(t, y):
    """平均を引いた信号の上昇ゼロ交差から周期[s]を推定する。"""
    t = np.asarray(t, dtype=float)
    yv = np.asarray(y, dtype=float)
    if np.isfinite(yv).sum() < 3:
        return None
    y0 = yv - np.nanmean(yv)
    sign = np.signbit(y0)                       # True=負
    # 上昇ゼロ交差のみ（負→非負）。立上り/立下りを混ぜると、デューティ比が
    # 50%でない波形（PWM/パルス等）で「上昇間隔」と「下降間隔」が交互に並び、
    # 2×median(半周期) が真の周期からずれてしまう。上昇のみなら全デューティで正しい。
    cross = np.where(np.diff(sign.astype(np.int8)) == -1)[0]
    if cross.size < 2:
        return None
    # 交差点での線形補間をベクトル化（y2==y1 のタイ点は従来同様に除外）
    i = cross
    y1, y2 = y0[i], y0[i + 1]
    mask = y2 != y1
    i, y1, y2 = i[mask], y1[mask], y2[mask]
    tc = t[i] + (-y1) * (t[i + 1] - t[i]) / (y2 - y1)
    if tc.size < 2:
        return None
    per = np.diff(tc)                            # 上昇→上昇 = 1周期
    per = per[per > 0]
    if per.size == 0:
        return None
    period = float(np.median(per))
    return period if period > 0 else None


def _edge_time(t, y, rising=True, lo=0.1, hi=0.9):
    """最初の立上り（または立下り）エッジの 10%-90% 遷移時間を返す。

    0%/100% の基準は実機オシロ標準どおりヒストグラム法の Top/Base（settledした
    高/低レベル）を用い、過渡（オーバーシュート/リンギング）に影響されにくくする。
    ヒストグラムで決められない場合は 5%/95% パーセンタイルにフォールバック。
    10%・90% の交差は「同じエッジ上」で対応付ける（周期信号でも正しく、
    立下りも常に算出できる）。
    """
    t = np.asarray(t, dtype=float)
    y = np.asarray(y, dtype=float)
    if np.isfinite(y).sum() < 3:
        return None
    top, base = histogram_top_base(y)      # 標準: Top/Base を 100%/0% 基準に
    if (top is None or base is None or not np.isfinite(top - base) or (top - base) <= 0):
        base = np.nanpercentile(y, 5)      # フォールバック
        top = np.nanpercentile(y, 95)
    span = top - base
    if not np.isfinite(span) or span <= 0:
        return None
    y_lo = base + lo * span
    y_hi = base + hi * span

    fin = np.isfinite(y)       # NaN は「下」「上」どちらでもない扱いにし、偽の交差を防ぐ
    #   注意: y<level / y>level は NaN に対し常に False になる。両端が有限のときだけ
    #   交差とみなすことで、NaN がエッジ内にあっても偽の交差点を作らない。

    def up_cross(level):       # level を下から上へ横切る位置
        below = y < level
        return np.where(below[:-1] & ~below[1:] & fin[:-1] & fin[1:])[0]

    def down_cross(level):     # level を上から下へ横切る位置
        above = y > level
        return np.where(above[:-1] & ~above[1:] & fin[:-1] & fin[1:])[0]

    if rising:
        lo_idx = up_cross(y_lo)
        if lo_idx.size == 0:
            return None
        i_lo = int(lo_idx[0])
        after = up_cross(y_hi)
        after = after[after > i_lo]     # 同じ立上りで 90% に到達する点
        if after.size == 0:
            return None
        return float(t[int(after[0])] - t[i_lo])
    else:
        hi_idx = down_cross(y_hi)
        if hi_idx.size == 0:
            return None
        i_hi = int(hi_idx[0])
        after = down_cross(y_lo)
        after = after[after > i_hi]     # 同じ立下りで 10% に到達する点
        if after.size == 0:
            return None
        return float(t[int(after[0])] - t[i_hi])


def _window(name, n):
    name = (name or "hann").lower()
    if name == "hamming":
        return np.hamming(n)
    if name == "blackman":
        return np.blackman(n)
    if name in ("blackmanharris", "blackman-harris", "bharris"):
        try:
            from scipy.signal.windows import blackmanharris
            return blackmanharris(n)
        except Exception:
            return np.blackman(n)
    if name == "flattop":
        try:
            from scipy.signal.windows import flattop
            return flattop(n)
        except Exception:
            return np.hanning(n)
    if name == "kaiser":
        return np.kaiser(n, 14.0)            # β=14 ≈ -100dB サイドローブ
    if name == "gaussian":
        try:
            from scipy.signal.windows import gaussian
            return gaussian(n, std=n / 6.0)
        except Exception:
            return np.hanning(n)
    if name in ("none", "rect", "rectangular"):
        return np.ones(n)
    return np.hanning(n)


def to_db(amp, ref=1.0, floor_db=-200.0):
    """振幅を dB（20·log10(amp/ref)）に変換。0 は floor_db に。"""
    amp = np.asarray(amp, dtype=float)
    out = np.full(amp.shape, floor_db)
    nz = amp > 0
    out[nz] = 20.0 * np.log10(amp[nz] / ref)
    return np.maximum(out, floor_db)


def histogram_top_base(y, bins=256):
    """ヒストグラム法で Top(上位の最頻値)・Base(下位の最頻値) を求める。"""
    y = np.asarray(y, dtype=float)
    y = y[np.isfinite(y)]
    if y.size < 4:
        return None, None
    vmin, vmax = float(y.min()), float(y.max())
    if vmax <= vmin:
        return vmin, vmin
    hist, edges = np.histogram(y, bins=bins)
    centers = (edges[:-1] + edges[1:]) / 2.0
    mid = (vmin + vmax) / 2.0
    up, lo = centers >= mid, centers < mid
    top = float(centers[up][np.argmax(hist[up])]) if hist[up].any() else vmax
    base = float(centers[lo][np.argmax(hist[lo])]) if hist[lo].any() else vmin
    return top, base


def _mid_crossings(t, y, level):
    """level を上下に横切る位置（上昇・下降）を返す。"""
    below = y < level
    up = np.where(below[:-1] & ~below[1:])[0]
    down = np.where(~below[:-1] & below[1:])[0]
    return up, down

# ======================================================================
# ↑ py
# ======================================================================
"""スペクトル系（FFT・スペクトルピーク・THD/SNR/SINAD/ENOB/SFDR・STFT）。"""



def fft_spectrum(t, y, window="hann", detrend=True):
    """片側振幅スペクトル (freqs[Hz], amplitude) を返す。

    一様サンプリングを仮定し、時間軸からサンプリング周波数を推定する。
    """
    t = np.asarray(t, dtype=float)
    y = np.asarray(y, dtype=float)
    n = y.size
    if n < 4:
        return None, None
    fs = sampling_rate(t)
    if not fs:
        return None, None

    yw = y - np.mean(y) if detrend else y.copy()
    w = _window(window, n)
    yw = yw * w

    spec = np.fft.rfft(yw)
    freqs = np.fft.rfftfreq(n, d=1.0 / fs)
    # 単側振幅（窓のコヒーレントゲインで正規化）
    amp = np.abs(spec) / (np.sum(w) / 2.0)
    # DC とナイキスト（n が偶数のとき rfft の末尾）は負側の共役対が無いため、
    # 片側化の ×2 を掛けてはいけない（掛けると 2 倍に過大評価される）。半分に戻す。
    if amp.size:
        amp[0] *= 0.5
        if n % 2 == 0:
            amp[-1] *= 0.5
    return freqs, amp


def dominant_frequency(t, y):
    """FFT で最大振幅の周波数[Hz]を返す（基本周波数の推定）。"""
    freqs, mag = fft_spectrum(t, y)
    if freqs is None or len(freqs) < 2:
        return None
    m = mag[1:]  # DC を除く
    if m.size == 0 or not np.isfinite(m).any():
        return None  # 全 NaN スペクトル
    if np.nanmax(m) <= 0:
        return None  # 平坦・定数の信号では周波数を返さない
    return float(freqs[int(np.nanargmax(m)) + 1])


def find_spectral_peaks(t, y, n=5, prominence_frac=0.02):
    """FFT スペクトルの主要ピーク（基本波・高調波など）を上位 n 個返す。

    Returns: list of dict {rank, frequency, amplitude}
    """
    freqs, amp = fft_spectrum(t, y)
    if freqs is None:
        return []
    peaks = find_signal_peaks(amp[1:], t=freqs[1:], n=n,
                              prominence_frac=prominence_frac, mode="max")
    out = []
    for p in peaks:
        out.append({
            "rank": p["rank"],
            "frequency": p["time"],     # find_signal_peaks の time に freqs を入れた
            "amplitude": p["value"],
        })
    return out


def spectrum_metrics(t, y, n_harm=6, window="hann", half_bins=3):
    """THD / SNR / SINAD / ENOB / SFDR と基本波周波数を返す。

    各成分はリーク対策として基本波・各高調波バンドのパワーを近傍ビンで合算する。
    """
    t = np.asarray(t, dtype=float)
    y = np.asarray(y, dtype=float)
    n = y.size
    if n < 16:
        return {}
    fs = sampling_rate(t)
    if not fs:
        return {}
    w = _window(window, n)
    yw = (y - np.mean(y)) * w
    spec = np.fft.rfft(yw)
    power = (np.abs(spec) ** 2)
    if power.size < 4 or not np.isfinite(power).any():
        return {}

    k0 = int(np.argmax(power[1:]) + 1)  # 基本波ビン（DC除く）
    f0 = k0 * fs / n

    def band(kc):
        a = max(1, kc - half_bins)
        b = min(power.size, kc + half_bins + 1)
        return a, b

    fa, fb = band(k0)
    p_fund = float(power[fa:fb].sum())
    if p_fund <= 0:
        return {}

    # 高調波バンドが基本波や他の高調波と重なる場合（k0 が小さい＝短時間捕捉で起こる）、
    # 同じビンを二重計上すると harm_power が過大になり noise_only が負→クランプされて
    # SNR が物理的にあり得ない巨大値になる。既取得ビンを除外して重複なく合算する。
    claimed = set(range(fa, fb))
    harm_power = 0.0
    for h in range(2, n_harm + 1):
        kc = int(round(k0 * h))
        if kc >= power.size - 1:
            break
        a, b = band(kc)
        bins = sorted(set(range(a, b)) - claimed)
        claimed |= set(range(a, b))
        if bins:
            harm_power += float(power[bins].sum())

    total = float(power[1:].sum())  # DC 除く全パワー
    noise_only = max(total - p_fund - harm_power, 1e-30)
    nd = max(total - p_fund, 1e-30)  # ノイズ＋歪み

    thd = float(np.sqrt(harm_power / p_fund) * 100.0)         # %
    thd_db = float(10 * np.log10(harm_power / p_fund)) if harm_power > 0 else None
    snr = float(10 * np.log10(p_fund / noise_only))
    sinad = float(10 * np.log10(p_fund / nd))
    enob = float((sinad - 1.76) / 6.02)

    spur = power.copy()
    spur[0] = 0
    spur[fa:fb] = 0
    sfdr = float(10 * np.log10(p_fund / spur.max())) if spur.max() > 0 else None

    return {"f0": f0, "THD_pct": thd, "THD_dB": thd_db, "SNR_dB": snr,
            "SINAD_dB": sinad, "ENOB_bits": enob, "SFDR_dB": sfdr}


def spectrogram(t, y, nperseg=256, window="hann"):
    """STFT のスペクトログラム (f, time, Sxx[dB]) を返す。scipy 使用。"""
    fs = sampling_rate(t)
    if not fs:
        return None, None, None
    try:
        from scipy.signal import spectrogram as _spec
    except Exception:
        return None, None, None
    y = np.asarray(y, dtype=float)
    y = np.nan_to_num(y - np.nanmean(y))
    nperseg = int(min(nperseg, len(y)))
    if nperseg < 16:
        return None, None, None
    f, tt, Sxx = _spec(y, fs=fs, window=window, nperseg=nperseg,
                       noverlap=nperseg // 2, scaling="spectrum")
    Sxx_db = 10.0 * np.log10(Sxx + 1e-20)
    return f, tt + (t[0] if len(t) else 0.0), Sxx_db


def channel_power(t, y, f_lo=None, f_hi=None, window="hann"):
    """指定帯域 [f_lo, f_hi] の電力（振幅²の総和）。帯域未指定なら全帯域（DC除く）。"""
    freqs, amp = fft_spectrum(t, y, window=window)
    if freqs is None:
        return None
    p = np.asarray(amp, dtype=float) ** 2
    lo = freqs[1] if f_lo is None else f_lo   # DC を除く
    hi = freqs[-1] if f_hi is None else f_hi
    band = (freqs >= lo) & (freqs <= hi)
    return float(p[band].sum())


def occupied_bandwidth(t, y, frac=0.99, window="hann"):
    """全電力の frac（既定99%）が収まる占有帯域幅[Hz]。DC は除く。"""
    freqs, amp = fft_spectrum(t, y, window=window)
    if freqs is None or freqs.size < 3:
        return None
    p = np.asarray(amp, dtype=float) ** 2
    p[0] = 0.0                                 # DC 除外
    tot = p.sum()
    if tot <= 0:
        return None
    c = np.cumsum(p) / tot
    lo_i = int(np.searchsorted(c, (1.0 - frac) / 2.0))
    hi_i = int(np.searchsorted(c, 1.0 - (1.0 - frac) / 2.0))
    hi_i = min(hi_i, freqs.size - 1)
    return float(freqs[hi_i] - freqs[lo_i])


def harmonic_search(t, y, n_harm=5, window="hann"):
    """基本波と高調波（基本波の整数倍に最も近いビン）の周波数・振幅を返す。

    Returns: list of dict {harmonic, frequency, amplitude}
    """
    freqs, amp = fft_spectrum(t, y, window=window)
    if freqs is None or freqs.size < 3:
        return []
    k0 = int(np.argmax(amp[1:]) + 1)           # 基本波ビン（DC除く）
    f0 = float(freqs[k0])
    if f0 <= 0:
        return []
    # 平坦/全ゼロ/定数信号では基本波が存在しない。dominant_frequency と同様にガードし、
    # 振幅ゼロの偽の高調波を並べない（compute_fft_metrics の表に矛盾行が出るのを防ぐ）。
    if not np.isfinite(amp[k0]) or amp[k0] <= 0:
        return []
    out = []
    for h in range(1, n_harm + 1):
        k = int(np.argmin(np.abs(freqs - f0 * h)))
        out.append({"harmonic": h, "frequency": float(freqs[k]),
                    "amplitude": float(amp[k])})
    return out

# ======================================================================
# ↑ py
# ======================================================================
"""自動測定（Vpp/RMS・立上り・パルス幅・サイクル統計・位相差・一括 analyze）。"""



def measurements(t, y):
    """主要測定値のリストを返す。各要素は {name, value, unit}。"""
    t = np.asarray(t, dtype=float)
    y = np.asarray(y, dtype=float)
    rows = []

    def add(name, value, unit=""):
        rows.append({"name": name, "value": value, "unit": unit})

    finite = np.isfinite(y)
    has = bool(finite.any())
    vmax = float(np.nanmax(y)) if has else None
    vmin = float(np.nanmin(y)) if has else None
    add("最大値 Vmax", vmax, "V")
    add("最小値 Vmin", vmin, "V")
    add("P-P値 Vpp", (vmax - vmin) if has else None, "V")
    add("平均 Vmean", float(np.nanmean(y)) if has else None, "V")
    add("実効値 Vrms", float(np.sqrt(np.nanmean(y ** 2))) if has else None, "V")
    add("標準偏差 σ", float(np.nanstd(y)) if has else None, "V")

    period = _zero_crossing_period(t, y)
    add("周期", period, "s")
    add("周波数(ゼロ交差)", (1.0 / period) if period else None, "Hz")
    add("周波数(FFT)", dominant_frequency(t, y), "Hz")

    # Top/Base（ヒストグラム法）と振幅・オーバーシュート等
    top, base = histogram_top_base(y) if has else (None, None)
    add("Top", top, "V")
    add("Base", base, "V")
    amp = (top - base) if (top is not None and base is not None) else None
    add("振幅 Vamp(Top-Base)", amp, "V")
    if amp and amp > 0:
        add("オーバーシュート", (vmax - top) / amp * 100.0, "%")
        add("アンダーシュート", (base - vmin) / amp * 100.0, "%")
    else:
        add("オーバーシュート", None, "%")
        add("アンダーシュート", None, "%")

    add("立上り時間 (10-90%)", _edge_time(t, y, rising=True), "s")
    add("立下り時間 (90-10%)", _edge_time(t, y, rising=False), "s")

    # パルス幅・デューティ・エッジ/サイクル数（中央しきい値）
    pm = pulse_metrics(t, y)
    add("+パルス幅", pm.get("pos_width"), "s")
    add("-パルス幅", pm.get("neg_width"), "s")
    add("+デューティ比", pm.get("pos_duty"), "%")
    add("-デューティ比", pm.get("neg_duty"), "%")
    add("立上りエッジ数", pm.get("rising_edges"), "")
    add("サイクル数", pm.get("cycles"), "")

    # エッジ間時間（立上り→立上り 等）
    ei = edge_intervals(t, y)
    add("立上り→立上り", ei.get("rise_to_rise"), "s")
    add("立下り→立下り", ei.get("fall_to_fall"), "s")
    add("立上り→立下り(High幅)", ei.get("rise_to_fall"), "s")
    add("立下り→立上り(Low幅)", ei.get("fall_to_rise"), "s")

    # ピーク到達時刻・面積
    if has:
        add("Time@Max", float(t[int(np.nanargmax(y))]), "s")
        add("Time@Min", float(t[int(np.nanargmin(y))]), "s")
        fin = np.isfinite(y) & np.isfinite(t)
        if fin.sum() >= 2:
            add("面積 ∫y dt", float(_trapz(y[fin], t[fin])), "V·s")
        else:
            add("面積 ∫y dt", None, "V·s")
    else:
        add("Time@Max", None, "s"); add("Time@Min", None, "s")
        add("面積 ∫y dt", None, "V·s")

    add("サンプル数", float(y.size), "点")
    add("サンプリング周波数", sampling_rate(t), "Hz")

    # --- 追加測定（中央値/リプル/スルーレート/サイクル統計/ヒストグラム由来）---
    add("中央値 Median", float(np.nanmedian(y)) if has else None, "V")
    add("リプル(AC RMS)", float(np.nanstd(y)) if has else None, "V")
    sr = slew_rate(t, y)
    add("スルーレート(立上り最大)", sr.get("rise"), "V/s")
    add("スルーレート(立下り最大)", sr.get("fall"), "V/s")
    cs = cycle_stats(t, y)
    add("サイクル平均", cs.get("cycle_mean"), "V")
    add("サイクルRMS", cs.get("cycle_rms"), "V")
    add("Cycle-Cycleジッタ", cs.get("cc_jitter"), "s")
    pd_ = pm.get("pos_duty")
    add("デューティ誤差(50%基準)", (pd_ - 50.0) if pd_ is not None else None, "%")
    hb = histogram_box_stats(y) if has else {}
    add("最頻ビン点数 PEAKHits", hb.get("peak_hits"), "点")
    add("±1σ以内", hb.get("sigma1"), "%")
    add("±2σ以内", hb.get("sigma2"), "%")
    add("±3σ以内", hb.get("sigma3"), "%")
    return rows


def slew_rate(t, y):
    """最大の立上り/立下りスルーレート [V/s]（隣接サンプル間の傾きの最大/最小）。"""
    t = np.asarray(t, dtype=float)
    y = np.asarray(y, dtype=float)
    if t.size < 2:
        return {}
    dt = np.diff(t)
    dy = np.diff(y)
    sl = np.divide(dy, dt, out=np.full_like(dy, np.nan), where=dt != 0)
    sl = sl[np.isfinite(sl)]
    if sl.size == 0:
        return {}
    return {"rise": float(np.max(sl)), "fall": float(np.min(sl))}


def cycle_stats(t, y):
    """サイクル（上昇ゼロ交差〜次の上昇ゼロ交差）単位の平均/RMS と、
    Cycle-Cycle ジッタ（隣り合う周期長の差の標準偏差）を返す。"""
    t = np.asarray(t, dtype=float)
    y = np.asarray(y, dtype=float)
    if t.size < 8:
        return {}
    y0 = y - np.nanmean(y)
    below = y0 < 0
    up = np.where(below[:-1] & ~below[1:])[0]   # 上昇ゼロ交差
    if up.size < 3:
        return {}
    periods = np.diff(t[up])
    means, rmss = [], []
    for a, b in zip(up[:-1], up[1:]):
        seg = y[a:b]
        seg = seg[np.isfinite(seg)]
        if seg.size:
            means.append(float(seg.mean()))
            rmss.append(float(np.sqrt(np.mean(seg ** 2))))
    out = {}
    if means:
        out["cycle_mean"] = float(np.mean(means))
        out["cycle_rms"] = float(np.mean(rmss))
    if periods.size >= 2:
        out["cc_jitter"] = float(np.std(np.diff(periods)))
    return out


def histogram_box_stats(y, bins=256):
    """ヒストグラム由来の測定：最頻ビンの点数 PEAKHits、平均±1/2/3σ内の割合[%]。"""
    y = np.asarray(y, dtype=float)
    y = y[np.isfinite(y)]
    if y.size < 4:
        return {}
    hist, _ = np.histogram(y, bins=bins)
    mean = float(y.mean())
    std = float(y.std())

    def within(k):
        return float(np.mean(np.abs(y - mean) <= k * std) * 100.0) if std > 0 else None

    return {"peak_hits": float(hist.max()),
            "sigma1": within(1), "sigma2": within(2), "sigma3": within(3)}


def cycle_statistics(t, y):
    """サイクルごとの 周波数/周期/振幅/Vpp の統計（min/max/mean/std/count）を返す。
    Returns dict: {param名: {min, max, mean, std, count}}。"""
    cm = cycle_measurements(t, y)
    out = {}
    freq = np.asarray(cm.get("freq", []), dtype=float)
    out["周波数 [Hz]"] = measurement_stats(freq)
    if freq.size:
        out["周期 [s]"] = measurement_stats(1.0 / freq[freq > 0])
    out["振幅 [V]"] = measurement_stats(np.asarray(cm.get("amp", []), dtype=float))
    out["Vpp [V]"] = measurement_stats(np.asarray(cm.get("vpp", []), dtype=float))
    return out


def edge_intervals(t, y, level=None):
    """エッジ間時間（立上り→立上り/立下り→立下り/立上り→立下り/立下り→立上り）の平均[s]。"""
    t = np.asarray(t, dtype=float)
    y = np.asarray(y, dtype=float)
    if np.isfinite(y).sum() < 4:
        return {}
    if level is None:
        top, base = histogram_top_base(y)
        if top is None or top <= base:
            return {}
        level = (top + base) / 2.0
    up, dn = _mid_crossings(t, y, level)

    def cross_times(idx):
        idx = np.asarray(idx, dtype=int)
        if idx.size == 0:
            return np.asarray([], dtype=float)
        y1, y2 = y[idx], y[idx + 1]
        denom = y2 - y1
        f = np.where(denom != 0.0, (level - y1) / np.where(denom != 0.0, denom, 1.0), 0.0)
        return t[idx] + f * (t[idx + 1] - t[idx])

    ut, dt_ = cross_times(up), cross_times(dn)
    res = {}
    if ut.size >= 2:
        res["rise_to_rise"] = float(np.mean(np.diff(ut)))
    if dt_.size >= 2:
        res["fall_to_fall"] = float(np.mean(np.diff(dt_)))
    rf = [dt_[dt_ > u][0] - u for u in ut if (dt_ > u).any()]   # 立上り→次の立下り=High幅
    fr = [ut[ut > d][0] - d for d in dt_ if (ut > d).any()]     # 立下り→次の立上り=Low幅
    if rf:
        res["rise_to_fall"] = float(np.mean(rf))
    if fr:
        res["fall_to_rise"] = float(np.mean(fr))
    return res


def pulse_metrics(t, y, level=None):
    """+/- パルス幅・デューティ・エッジ数・サイクル数を返す。"""
    t = np.asarray(t, dtype=float)
    y = np.asarray(y, dtype=float)
    out = {}
    finite = np.isfinite(y)
    if finite.sum() < 4:
        return out
    if level is None:
        top, base = histogram_top_base(y)
        if top is None or top <= base:
            return out
        level = (top + base) / 2.0
    up, down = _mid_crossings(t, y, level)
    out["rising_edges"] = float(len(up))
    # 高区間（up→次のdown）と低区間（down→次のup）の幅
    highs, lows = [], []
    for u in up:
        nxt = down[down > u]
        if nxt.size:
            highs.append(t[nxt[0]] - t[u])
    for d in down:
        nxt = up[up > d]
        if nxt.size:
            lows.append(t[nxt[0]] - t[d])
    pw = float(np.mean(highs)) if highs else None
    nw = float(np.mean(lows)) if lows else None
    out["pos_width"] = pw
    out["neg_width"] = nw
    if pw and nw:
        out["pos_duty"] = pw / (pw + nw) * 100.0
        out["neg_duty"] = nw / (pw + nw) * 100.0
    out["cycles"] = float(min(len(up), len(down))) if (len(up) and len(down)) else float(len(up))
    return out


def cycle_measurements(t, y):
    """サイクルごとの周波数・振幅の配列を返す（トレンド/統計用）。

    Returns dict: {cycle_time, freq, amp, vpp}（各配列）
    """
    t = np.asarray(t, dtype=float)
    y = np.asarray(y, dtype=float)
    y0 = y - np.nanmean(y)
    below = y0 < 0
    up = np.where(below[:-1] & ~below[1:])[0]  # 上昇ゼロ交差
    res = {"cycle_time": [], "freq": [], "amp": [], "vpp": []}
    for a, b in zip(up[:-1], up[1:]):
        period = t[b] - t[a]
        if period <= 0:
            continue
        seg = y[a:b]
        seg = seg[np.isfinite(seg)]
        if seg.size == 0:
            continue
        res["cycle_time"].append((t[a] + t[b]) / 2.0)
        res["freq"].append(1.0 / period)
        res["vpp"].append(float(seg.max() - seg.min()))
        res["amp"].append(float((seg.max() - seg.min()) / 2.0))
    for k in res:
        res[k] = np.asarray(res[k], dtype=float)
    return res


def measurement_stats(values):
    """測定値配列の min/max/mean/σ/数 を返す。"""
    v = np.asarray(values, dtype=float)
    v = v[np.isfinite(v)]
    if v.size == 0:
        return {"min": None, "max": None, "mean": None, "std": None, "count": 0}
    return {"min": float(v.min()), "max": float(v.max()),
            "mean": float(v.mean()), "std": float(v.std()), "count": int(v.size)}


def phase_delay(t, y1, y2):
    """2チャンネル間の遅延[s]と位相差[deg]を相互相関で求める。"""
    t = np.asarray(t, dtype=float)
    a = np.asarray(y1, dtype=float)
    b = np.asarray(y2, dtype=float)
    n = min(a.size, b.size)
    if n < 4:
        return None, None
    a, b = a[:n], b[:n]
    a = a - np.nanmean(a)
    b = b - np.nanmean(b)
    a = np.nan_to_num(a)
    b = np.nan_to_num(b)
    corr = np.correlate(a, b, mode="full")
    lag = int(np.argmax(corr)) - (n - 1)
    dt = np.median(np.diff(t[:n]))
    delay = -lag * dt              # y2 が遅れていれば正
    period = _zero_crossing_period(t, a)
    phase = (-delay / period * 360.0) if period else None  # 遅れは負位相
    if phase is not None:
        phase = ((phase + 180.0) % 360.0) - 180.0  # -180..180 に正規化
    return float(delay), (float(phase) if phase is not None else None)


def analyze(t, y, n_peaks=5, smooth=0):
    """ピーク・測定・FFT をまとめて返す便利関数。smooth で平滑化してピーク検出。"""
    return {
        "peaks": find_signal_peaks(y, t=t, n=n_peaks, smooth=smooth),
        "troughs": find_signal_peaks(y, t=t, n=n_peaks, mode="min", smooth=smooth),
        "measurements": measurements(t, y),
        "spectral_peaks": find_spectral_peaks(t, y, n=n_peaks),
    }

# ======================================================================
# ↑ py
# ======================================================================
"""高度解析：マスク/リミット合否、アイダイアグラム、ジッタ、シリアルプロトコル解読。

ハイエンドオシロ相当の解析機能を後処理で提供する。プロトコル解読は
UART（1線）、I2C（SCL/SDA）、SPI（SCK/MOSI[/CS]）に対応。
"""




# ----------------------------------------------------------------- 共通
def auto_threshold(y):
    top, base = histogram_top_base(y)
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

# ======================================================================
# ↑ py
# ======================================================================
"""数学チャンネル（波形演算）。

2系列の四則演算（A±B / A×B / A÷B）と、単一系列の積分・微分・絶対値・
二乗・移動平均・ローパスフィルタを計算して新しい波形を作る。
X（時間軸）が異なる場合は B を A の時間軸へ補間して揃える。
"""



_HAVE_SCIPY = _ilu.find_spec("scipy") is not None  # lfilter があれば IIR をベクトル化

BINARY_OPS = ["A+B", "A-B", "A×B", "A÷B"]

# 任意数式で使える関数・定数（ホワイトリスト。eval は使わず AST を自前評価する）
_EXPR_FUNCS = {
    "sin": np.sin, "cos": np.cos, "tan": np.tan, "asin": np.arcsin, "acos": np.arccos,
    "atan": np.arctan, "atan2": np.arctan2, "sinh": np.sinh, "cosh": np.cosh,
    "tanh": np.tanh, "exp": np.exp, "log": np.log, "log10": np.log10, "log2": np.log2,
    "sqrt": np.sqrt, "abs": np.abs, "sign": np.sign, "clip": np.clip,
    "min": np.minimum, "max": np.maximum, "where": np.where,
}
_EXPR_CONSTS = {"pi": np.pi, "e": np.e}


def eval_expr(expr, variables):
    """安全な数式評価（A,B,VAR1,VAR2,t 等の変数と許可関数のみ）。

    Python の eval は使わず AST をホワイトリストで評価するので任意コード実行は不可。
    許可：四則・** ・% ・単項± ・括弧 ・許可関数 ・定数(pi,e) ・数値リテラル。
    variables: dict（name -> ndarray/scalar）。
    """
    try:
        node = _ast.parse(expr, mode="eval").body
    except SyntaxError as e:
        raise ValueError(f"式の構文エラー: {e}")

    def ev(n):
        if isinstance(n, _ast.BinOp):
            l, r = ev(n.left), ev(n.right)
            op = n.op
            if isinstance(op, _ast.Add):
                return l + r
            if isinstance(op, _ast.Sub):
                return l - r
            if isinstance(op, _ast.Mult):
                return l * r
            if isinstance(op, _ast.Div):
                return l / r
            if isinstance(op, _ast.Pow):
                return l ** r
            if isinstance(op, _ast.Mod):
                return l % r
            raise ValueError("使用できない演算子です")
        if isinstance(n, _ast.UnaryOp):
            v = ev(n.operand)
            if isinstance(n.op, _ast.UAdd):
                return +v
            if isinstance(n.op, _ast.USub):
                return -v
            raise ValueError("使用できない単項演算子です")
        if isinstance(n, _ast.Call):
            name = getattr(n.func, "id", None)
            if name not in _EXPR_FUNCS:
                raise ValueError(f"使用できない関数です: {name}")
            return _EXPR_FUNCS[name](*[ev(a) for a in n.args])
        if isinstance(n, _ast.Name):
            if n.id in variables:
                return variables[n.id]
            if n.id in _EXPR_CONSTS:
                return _EXPR_CONSTS[n.id]
            raise ValueError(f"未知の変数です: {n.id}（A, B, VAR1, VAR2, t が使えます）")
        if isinstance(n, _ast.Constant) and isinstance(n.value, (int, float)):
            return n.value
        if isinstance(n, _ast.Num):           # Python 3.7 互換
            return n.n
        raise ValueError("この式は評価できません")

    return ev(node)
UNARY_OPS = ["積分 ∫A dt", "微分 dA/dt", "絶対値 |A|", "二乗 A²",
             "移動平均", "ローパス(RC)", "ローパス(Butterworth)",
             "ハイパス(Butterworth)", "包絡線(Hilbert)", "自己相関"]


def _sorted_xy(x, y):
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    order = np.argsort(x)
    return x[order], y[order]


def _resample(xa, xb, yb):
    """B系列を A の時間軸 xa へ補間。3次スプライン優先、無ければ線形(np.interp)。"""
    xa = np.asarray(xa, dtype=float)
    xbs, ybs = _sorted_xy(xb, yb)
    uniq = np.concatenate(([True], np.diff(xbs) > 0))   # 重複xを除去（CubicSpline要件）
    xbs, ybs = xbs[uniq], ybs[uniq]
    if xbs.size >= 4:
        try:
            from scipy.interpolate import CubicSpline
            cs = CubicSpline(xbs, ybs, extrapolate=False)
            # B の範囲外は端点へクランプ（np.interp と同じ）。3次スプラインの外挿は
            # 範囲外で発散して A±B 等が誤った値になるため、外挿はさせない。
            xc = np.clip(xa, xbs[0], xbs[-1])
            return cs(xc)
        except Exception:
            pass
    return np.interp(xa, xbs, ybs)


def _rc_lowpass(y, alpha):
    """1次IIRローパス  r[i] = (1-α)·r[i-1] + α·y[i],  r[0] = y[0]。

    再帰なので単純なnumpy要素演算では書けない。scipy があれば lfilter で
    まとめて計算し（大波形で桁違いに速い）、無ければ従来の逐次ループにフォールバック。
    どちらも数値的に同一の結果になる。
    """
    if y.size == 0:
        return y.copy()
    if _HAVE_SCIPY:
        try:
            from scipy.signal import lfilter   # 遅延import（起動を軽くする）
            zi = [(1.0 - alpha) * float(y[0])]  # y[-1]=y[0] 相当の初期状態
            r, _ = lfilter([alpha], [1.0, -(1.0 - alpha)], y, zi=zi)
            return np.asarray(r, dtype=float)
        except Exception:                       # noqa: BLE001  scipy不調→逐次へ
            pass
    r = np.empty_like(y)
    acc = y[0]
    for i in range(y.size):
        acc += alpha * (y[i] - acc)
        r[i] = acc
    return r


def binary(xa, ya, xb, yb, op):
    """2系列の四則演算。B は A の時間軸に線形補間して揃える。"""
    xa = np.asarray(xa, dtype=float)
    ya = np.asarray(ya, dtype=float)
    yb_i = _resample(xa, xb, yb)    # A の各点での B の値（3次補間優先・無ければ線形）
    with np.errstate(divide="ignore", invalid="ignore"):
        if op == "A+B":
            r = ya + yb_i
        elif op == "A-B":
            r = ya - yb_i
        elif op == "A×B":
            r = ya * yb_i
        elif op == "A÷B":
            r = np.where(yb_i != 0, ya / yb_i, np.nan)
        else:
            raise ValueError(f"未知の演算: {op}")
    return xa, r


def unary(x, y, op, param=None):
    """単一系列の演算。param は移動平均の窓長やローパスのカットオフ[Hz]。"""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if op == "積分 ∫A dt":
        try:
            from scipy.integrate import cumulative_trapezoid
            r = cumulative_trapezoid(y, x, initial=0.0)
        except Exception:
            dx = np.diff(x, prepend=x[0])
            r = np.cumsum(y * dx)
        return x, r
    if op == "微分 dA/dt":
        return x, np.gradient(y, x)
    if op == "絶対値 |A|":
        return x, np.abs(y)
    if op == "二乗 A²":
        return x, y * y
    if op == "移動平均":
        win = int(param or 5)
        win = max(1, win)
        kernel = np.ones(win) / win
        r = np.convolve(y, kernel, mode="same")
        return x, r
    if op == "ローパス(RC)":
        # 1次 RC ローパス（カットオフ param[Hz]）を前進差分で適用
        fc = float(param or 1000.0)
        dt = np.median(np.diff(x)) if x.size > 1 else 1.0
        if dt <= 0 or fc <= 0:
            return x, y.copy()
        alpha = dt / (dt + 1.0 / (2 * np.pi * fc))
        return x, _rc_lowpass(y, alpha)
    if op in ("ローパス(Butterworth)", "ハイパス(Butterworth)"):
        # 4次 Butterworth ＋ filtfilt（零位相）。出来合い関数を使用。
        fc = float(param or 1000.0)
        dt = np.median(np.diff(x)) if x.size > 1 else 1.0
        fs = (1.0 / dt) if dt > 0 else None
        if not fs or fc <= 0 or fc >= fs / 2 or y.size < 13:
            return x, y.copy()
        btype = "low" if "ロー" in op else "high"
        try:
            from scipy.signal import butter, filtfilt
            b, a = butter(4, fc, btype=btype, fs=fs)
            return x, filtfilt(b, a, y)
        except Exception:                       # noqa: BLE001 scipy無し→RCで近似
            alpha = dt / (dt + 1.0 / (2 * np.pi * fc))
            lp = _rc_lowpass(y, alpha)
            return x, (lp if btype == "low" else y - lp)
    if op == "包絡線(Hilbert)":
        # 振幅包絡線 = |解析信号| = |hilbert(y)|。出来合い関数を使用。
        try:
            from scipy.signal import hilbert
            return x, np.abs(hilbert(np.nan_to_num(y)))
        except Exception:                       # noqa: BLE001 フォールバック（粗い）
            return x, np.abs(y - np.nanmean(y))
    if op == "自己相関":
        a = np.nan_to_num(y - np.nanmean(y))
        try:
            from scipy.signal import correlate
            r = correlate(a, a, mode="full", method="fft")
        except Exception:                       # noqa: BLE001
            r = np.correlate(a, a, mode="full")
        r = r[r.size // 2:]                      # 非負ラグのみ
        if r.size and r[0] != 0:
            r = r / r[0]                         # ラグ0で正規化
        # 横軸はラグ（0始まり）。元の時刻 x[:r.size] をそのまま使うと、開始時刻
        # x[0]≠0 のデータでラグ0が x[0] にずれて表示されるため、原点を引く。
        x0 = float(x[0]) if x.size else 0.0
        return x[:r.size] - x0, r
    raise ValueError(f"未知の演算: {op}")

# ======================================================================
# ↑ py
# ======================================================================
"""データサイエンス系の計算（GUI から独立）。

線形回帰（線形性）・記述統計・相関・正規性検定など、データ解析でよく使う指標を計算する。
scipy があればそれを使い、無くても numpy だけで主要な指標を返せるようフォールバックする。
入力は 1 次元配列（x, y）。NaN/inf は自動で除外する。
"""


def _clean_xy(x, y):
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    n = min(x.size, y.size)
    x, y = x[:n], y[:n]
    m = np.isfinite(x) & np.isfinite(y)
    return x[m], y[m]


def _clean(y):
    y = np.asarray(y, dtype=float)
    return y[np.isfinite(y)]


def linear_regression(x, y):
    """最小二乗の直線当てはめ。線形性（R²・相関 r）と直線性誤差を返す。

    戻り dict のキー:
      n, slope(傾き), intercept(切片), r(ピアソン相関), r2(決定係数),
      p_value(傾き=0 の検定。scipy 時のみ), std_err(傾きの標準誤差。scipy 時のみ),
      rmse(残差二乗平均平方根), linearity_error_pct(最大残差/Yの全幅×100[%FS])
    """
    x, y = _clean_xy(x, y)
    n = int(x.size)
    if n < 2:
        return {}
    slope = intercept = rval = pval = stderr = None
    try:
        from scipy import stats
        res = stats.linregress(x, y)
        slope, intercept = float(res.slope), float(res.intercept)
        rval, pval, stderr = float(res.rvalue), float(res.pvalue), float(res.stderr)
    except Exception:
        slope, intercept = (float(v) for v in np.polyfit(x, y, 1))
    yhat = slope * x + intercept
    resid = y - yhat
    ss_res = float(np.sum(resid ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    r2 = (1.0 - ss_res / ss_tot) if ss_tot > 0 else None
    if rval is None:
        rval = (float(np.sign(slope) * np.sqrt(r2)) if (r2 is not None and r2 >= 0) else None)
    rmse = float(np.sqrt(np.mean(resid ** 2)))
    yspan = float(np.max(y) - np.min(y))
    inl_pct = float(np.max(np.abs(resid)) / yspan * 100.0) if yspan > 0 else None
    return {
        "n": n, "slope": slope, "intercept": intercept,
        "r": rval, "r2": r2, "p_value": pval, "std_err": stderr,
        "rmse": rmse, "linearity_error_pct": inl_pct,
    }


def describe(y):
    """記述統計。count/mean/median/std/var/min/max/range/CV/歪度/尖度/四分位 など。"""
    y = _clean(y)
    if y.size == 0:
        return {}
    n = int(y.size)
    mean = float(np.mean(y))
    std = float(np.std(y, ddof=1)) if n > 1 else 0.0
    p25, p50, p75 = (float(np.percentile(y, q)) for q in (25, 50, 75))
    d = {
        "count": n, "mean": mean, "median": float(np.median(y)),
        "std": std, "var": float(np.var(y, ddof=1)) if n > 1 else 0.0,
        "min": float(np.min(y)), "max": float(np.max(y)),
        "range": float(np.max(y) - np.min(y)),
        "cv": (float(std / mean) if mean != 0 else None),
        "p25": p25, "p50": p50, "p75": p75, "iqr": p75 - p25,
    }
    try:
        from scipy import stats
        if std > 0:                                # 定数データは scipy が nan を返すため除外
            d["skew"] = float(stats.skew(y))
            d["kurtosis"] = float(stats.kurtosis(y))   # 過剰尖度（正規分布=0）
        else:
            d["skew"] = 0.0
            d["kurtosis"] = 0.0
    except Exception:
        if std > 0:
            z = (y - mean) / std
            d["skew"] = float(np.mean(z ** 3))
            d["kurtosis"] = float(np.mean(z ** 4) - 3.0)
        else:
            d["skew"] = 0.0
            d["kurtosis"] = 0.0
    return d


def correlation(x, y, method="pearson"):
    """2系列の相関係数と p 値（scipy 時）。method: 'pearson' | 'spearman'。"""
    x, y = _clean_xy(x, y)
    if x.size < 2:
        return None
    try:
        from scipy import stats
        if method == "spearman":
            r, p = stats.spearmanr(x, y)
        else:
            r, p = stats.pearsonr(x, y)
        return {"r": float(r), "p_value": float(p)}
    except Exception:
        return {"r": float(np.corrcoef(x, y)[0, 1]), "p_value": None}


def correlation_matrix(named_series, method="pearson"):
    """複数系列の相関行列。named_series: [(名前, y配列), ...]。

    各系列を共通長に切り、全系列で有限な点だけを使って相関行列を計算する。
    戻り値: (names, matrix[ndarray])。系列が2未満や有効点不足なら (names, None)。
    """
    names = [str(nm) for nm, _ in named_series]
    arrs = [np.asarray(a, dtype=float) for _, a in named_series]
    if len(arrs) < 2:
        return names, None
    L = min(a.size for a in arrs)
    if L < 2:
        return names, None
    M = np.vstack([a[:L] for a in arrs])
    mask = np.all(np.isfinite(M), axis=0)
    M = M[:, mask]
    if M.shape[1] < 2:
        return names, None
    try:
        if method == "spearman":
            from scipy import stats
            mat, _ = stats.spearmanr(M, axis=1)
            mat = np.atleast_2d(np.asarray(mat, dtype=float))
            if mat.shape != (len(arrs), len(arrs)):   # 2系列時は scalar を 2x2 へ
                r = float(mat.ravel()[0])             # scipy が返した Spearman 値を使う
                mat = np.array([[1.0, r], [r, 1.0]])  # （np.corrcoef は Pearson なので不可）
        else:
            mat = np.corrcoef(M)
    except Exception:
        mat = np.corrcoef(M)
    return names, np.asarray(mat, dtype=float)


def normality(y):
    """Shapiro-Wilk 正規性検定（scipy 必須）。W 統計量・p 値・5%有意で正規かを返す。
    scipy が無ければ空 dict。"""
    y = _clean(y)
    if y.size < 3:
        return {}
    try:
        from scipy import stats
        w, p = stats.shapiro(y[:5000])   # shapiro は大標本で重いため上限を設ける
        return {"W": float(w), "p_value": float(p), "normal_5pct": bool(p > 0.05)}
    except Exception:
        return {}

# ======================================================================
# ↑ py
# ======================================================================
"""一括出力のワーカー（Qt非依存・別プロセスでも実行可能）。

ProcessPoolExecutor から呼ぶため、ここでは Qt や graph_app を import しない。
matplotlib は Agg バックエンド固定。タスクは完全に picklable な dict 1個で渡す。
"""


_FONT_DONE = False


def _ensure_font(font_name):
    """ワーカープロセスごとに1回だけ日本語フォントを設定（□□□化を防ぐ）。"""
    global _FONT_DONE
    if not _FONT_DONE:
        try:
            import jp_font
            setup_japanese_font(font_name)
        except Exception:        # noqa: BLE001  フォント未検出でも既定で続行
            pass
        _FONT_DONE = True


def render_one(task):
    """1ファイル分を描画して保存し、保存パスを返す。task は picklable な dict。

    画面描画・逐次出力と同一の plot_series 経路を使うため、出力はピクセル一致する。
    """
    _ensure_font(task.get("font_name"))
    fig = Figure(figsize=task["figsize"], dpi=task["dpi"])
    FigureCanvasAgg(fig)
    ax = fig.add_subplot(111)
    plot_series(
        ax, task["series"], task["ctype"], categories=task["categories"],
        title=task["title"], xlabel=task["xlabel"], ylabel=task["ylabel"],
        xlim=task["xlim"], ylim=task["ylim"],
        secondary_label=task["sec_label"], max_points=task["max_points"],
        **task["fmt"])
    ratio = task.get("ratio")
    if ratio:
        ax.set_box_aspect(ratio)
        ax2 = getattr(ax, "_twin_secondary", None)
        if ax2 is not None:
            ax2.set_box_aspect(ratio)
    tight = task.get("tight", True)
    if not tight:                       # 図サイズ＝画像比率。ラベルが収まるよう整える
        try:
            fig.tight_layout()
        except Exception:
            pass
    fig.savefig(task["path"], dpi=task["dpi"],
                bbox_inches=("tight" if tight else None),
                transparent=task["transparent"])
    return task["path"]


def render_sequential(tasks):
    """逐次出力（図を1つ再利用）。並列が使えない/不要なときのフォールバック。
    戻り値 (saved_paths, skipped_msgs)。"""
    import os
    saved, skipped = [], []
    if not tasks:
        return saved, skipped
    fig = Figure(figsize=tasks[0]["figsize"], dpi=tasks[0]["dpi"])
    FigureCanvasAgg(fig)
    ax = fig.add_subplot(111)
    for t in tasks:
        try:
            ax.clear()
            plot_series(
                ax, t["series"], t["ctype"], categories=t["categories"],
                title=t["title"], xlabel=t["xlabel"], ylabel=t["ylabel"],
                xlim=t["xlim"], ylim=t["ylim"],
                secondary_label=t["sec_label"], max_points=t["max_points"],
                **t["fmt"])
            ratio = t.get("ratio")
            if ratio:
                ax.set_box_aspect(ratio)
                ax2 = getattr(ax, "_twin_secondary", None)
                if ax2 is not None:
                    ax2.set_box_aspect(ratio)
            tight = t.get("tight", True)
            if not tight:
                try:
                    fig.tight_layout()
                except Exception:
                    pass
            fig.savefig(t["path"], dpi=t["dpi"],
                        bbox_inches=("tight" if tight else None),
                        transparent=t["transparent"])
            saved.append(t["path"])
        except Exception as e:  # noqa: BLE001
            skipped.append(f"{os.path.basename(t['path'])}（{e}）")
    return saved, skipped

# ======================================================================
# ↑ py
# ======================================================================
"""GraphApp と各 Mixin が共有する import・定数・補助クラス。"""



PREVIEW_ROWS = 100
UserRole = QtCore.Qt.ItemDataRole.UserRole
DECIMATE_TARGET = 8000   # 折れ線/散布図でこの点数を超えたら間引いて表示
BUSY_ROWS = 200_000      # この行数を超える読み込みは待機カーソルを出す
BATCH_PARALLEL_THRESHOLD = 10**9   # 一括出力でこの枚数以上なら別プロセス並列を試みる


def _parse_float(text, default=None):
    text = (text or "").strip()
    if text == "":
        return default
    try:
        return float(text)        # 1e-6 / 0.000001 / 1000 などはそのまま
    except ValueError:
        pass
    # 『底^指数』表記も許可: 10^-6 → 1e-6, 2^10 → 1024（^ は累乗）
    m = re.fullmatch(r"([+-]?[\d.]+)\s*\^\s*([+-]?[\d.]+)", text)
    if m:
        try:
            return float(m.group(1)) ** float(m.group(2))
        except (ValueError, OverflowError, ZeroDivisionError):
            return default
    return default


class CheckListWidget(QtWidgets.QListWidget):
    """行のどこをクリックしてもチェックがトグルするリスト。

    チェックボックスの小さな枠だけでなく、行全体が当たり判定になる。
    （Qt 標準のインジケータ自動トグルと二重にならないよう、ここで一括処理）
    """

    def mousePressEvent(self, event):
        item = self.itemAt(event.position().toPoint())
        if item is not None and (item.flags() & QtCore.Qt.ItemFlag.ItemIsUserCheckable):
            checked = item.checkState() == QtCore.Qt.CheckState.Checked
            item.setCheckState(QtCore.Qt.CheckState.Unchecked if checked
                               else QtCore.Qt.CheckState.Checked)
            event.accept()
            return
        super().mousePressEvent(event)


class LazyColumnCombo(QtWidgets.QComboBox):
    """誤差列の選択コンボ。列一覧は初回オープン時に遅延展開する。

    多系列でスタイル表を作り直すとき、各行のコンボへ全列を addItems すると重い
    （多系列で支配的コスト）。最初は『なし』＋現在値だけを持ち、ユーザーが
    ドロップダウンを開いた時に初めて全列を読み込む。"""

    def __init__(self, get_cols, current, parent=None):
        super().__init__(parent)
        self._get_cols = get_cols
        self._loaded = False
        self.addItem("なし")
        if current:
            self.addItem(str(current))
            self.setCurrentText(str(current))

    def showPopup(self):
        if not self._loaded:
            self._loaded = True
            cur = self.currentText()
            self.blockSignals(True)
            self.clear()
            self.addItem("なし")
            for c in self._get_cols():
                s = str(c)
                if s != "なし":
                    self.addItem(s)
            i = self.findText(cur)
            self.setCurrentIndex(i if i >= 0 else 0)
            self.blockSignals(False)
        super().showPopup()

__all__ = [
    "os",
    "sys",
    "QtCore",
    "QtGui",
    "QtWidgets",
    "FigureCanvas",
    "NavigationToolbar",
    "Figure",
    "advanced",
    "analysis",
    "applog",
    "config_io",
    "data_loader",
    "datasci",
    "jp_font",
    "mathchan",
    "plotter",
    "PREVIEW_ROWS",
    "UserRole",
    "DECIMATE_TARGET",
    "BUSY_ROWS",
    "BATCH_PARALLEL_THRESHOLD",
    "_parse_float",
    "CheckListWidget",
    "LazyColumnCombo",
]

# ======================================================================
# ↑ graph_app_common.py
# ======================================================================
"""UIBuildMixin: GraphApp から分離した UIBuildMixin 群（挙動は本体と同一）。"""


class UIBuildMixin:
    # ------------------------------------------------------------ UI 構築
    def _menu_action(self, menu, label, slot, shortcut=None, tip=None):
        act = QtGui.QAction(label, self)
        if shortcut:
            act.setShortcut(shortcut)
        if tip:
            act.setStatusTip(tip)
        act.triggered.connect(slot)
        menu.addAction(act)
        return act

    def _build_menu(self):
        m = self.menuBar()
        # ファイル
        fm = m.addMenu("ファイル(&F)")
        self._menu_action(fm, "ファイル追加...", self.add_file, "Ctrl+O")
        self._menu_action(fm, "クリップボードから貼り付け", self.paste_from_clipboard, "Ctrl+Shift+V",
                          tip="Excel等からコピーした表を新規データとして読み込む")
        self.recent_menu = fm.addMenu("最近使ったファイル")
        self._rebuild_recent_menu()
        fm.addSeparator()
        self._menu_action(fm, "グラフ画像を保存...", self.save_figure, "Ctrl+S")
        self._menu_action(fm, "ファイルごとに一括画像出力...", self.batch_export, "Ctrl+B")
        self._menu_action(fm, "クリップボードにコピー", self.copy_figure, "Ctrl+Shift+C")
        fm.addSeparator()
        self._menu_action(fm, "設定を保存...", self.save_config_dialog, "Ctrl+Shift+S")
        self._menu_action(fm, "設定を読み込み...", self.load_config_dialog, None)
        fm.addSeparator()
        self._menu_action(fm, "終了", self.close, "Ctrl+Q")
        # 編集
        em = m.addMenu("編集(&E)")
        self._menu_action(em, "元に戻す", self.undo, "Ctrl+Z", tip="書式・設定の変更を1つ戻す")
        self._menu_action(em, "やり直す", self.redo, "Ctrl+Y", tip="戻した変更をやり直す")
        # 表示
        vm = m.addMenu("表示(&V)")
        self._menu_action(vm, "グラフを描画", self.draw_graph, "F5")
        self._menu_action(vm, "全データに合わせる（オートスケール）", self.auto_scale_scope, None)
        # 解析
        am = m.addMenu("解析(&A)")
        self._menu_action(am, "解析実行（ピーク・測定）", self.run_analysis, "Ctrl+R",
                          tip="選択中の解析対象系列のピーク・測定値を計算")
        self._menu_action(am, "FFTスペクトル表示", self.show_fft, None)
        # ヘルプ
        hm = m.addMenu("ヘルプ(&H)")
        self._menu_action(hm, "使い方", self.show_help, "F1")
        self._menu_action(hm, "バージョン情報", self.show_about, None)

    def _build_central(self):
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        outer = QtWidgets.QHBoxLayout(central)
        outer.setContentsMargins(6, 6, 6, 6)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        outer.addWidget(splitter)

        # 左：入力・解析タブ（データ読込 / オシロ / 高度解析）
        tabs = QtWidgets.QTabWidget()
        self.tabs = tabs
        tabs.setMinimumWidth(220)   # 下限を下げ、境界線ドラッグで幅を広く/狭くしやすく
        tabs.addTab(self._build_tab_data(), "1. データ")
        tabs.addTab(self._build_tab_scope(), "2. オシロ/解析")
        tabs.addTab(self._build_tab_advanced(), "3. 高度解析")
        tabs.addTab(self._build_tab_datasci(), "4. データサイエンス")
        splitter.addWidget(tabs)

        # 中央：グラフ表示＋データ編集
        center = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
        center.addWidget(self._build_plot_area())
        center.addWidget(self._build_preview())
        center.setStretchFactor(0, 4)
        center.setStretchFactor(1, 1)
        splitter.addWidget(center)

        # 右端：グラフ書式調整パネル（書式コントロール＋系列スタイル表）
        splitter.addWidget(self._build_format_panel())

        splitter.setStretchFactor(0, 0)   # 左タブ：固定気味
        splitter.setStretchFactor(1, 1)   # 中央グラフ：伸びる
        splitter.setStretchFactor(2, 0)   # 右書式：固定気味
        splitter.setSizes([360, 680, 400])

        self._wire_live_signals()
        self._add_tooltips()

    # ---- データタブ ----
    def _build_tab_data(self):
        w = QtWidgets.QWidget()
        outer = QtWidgets.QVBoxLayout(w); outer.setContentsMargins(0, 0, 0, 0)
        vsplit = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
        outer.addWidget(vsplit)

        # === 上段：読み込み済みファイル一覧（縦幅は下の境界線ドラッグで調整可）===
        top = QtWidgets.QWidget(); tv = QtWidgets.QVBoxLayout(top)
        tv.setContentsMargins(2, 2, 2, 2)
        tv.addWidget(self._bold("読み込み済みファイル"))
        hint = QtWidgets.QLabel("ファイルを追加（ここにドラッグ&ドロップも可）→ X/Y を選び「グラフを描画」")
        hint.setWordWrap(True); hint.setStyleSheet("color:#666;")
        tv.addWidget(hint)
        self.file_list = QtWidgets.QListWidget()
        self.file_list.setMinimumHeight(60)   # 下限。下の境界線ドラッグで縦幅を自由に変更
        self.file_list.setToolTip("読み込んだファイル一覧。選択するとプレビューを表示します。\n"
                                  "長い名前は横スクロール／ホバーで全体を表示。\n"
                                  "縦幅は下の境界線、横幅は左パネルとグラフの境界線をドラッグで変えられます。")
        # 長いファイル名を省略せず表示し、横スクロールで全体を読めるようにする
        self.file_list.setTextElideMode(QtCore.Qt.TextElideMode.ElideNone)
        self.file_list.setWordWrap(False)
        self.file_list.setHorizontalScrollMode(
            QtWidgets.QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.file_list.setHorizontalScrollBarPolicy(
            QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        # 複数選択可（Ctrl/Shift＋クリック）。選択したものをまとめて削除できる
        self.file_list.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.file_list.currentRowChanged.connect(self._on_file_selected)
        tv.addWidget(self.file_list, 1)

        row = QtWidgets.QHBoxLayout()
        b_add = QtWidgets.QPushButton("ファイル追加...")
        b_add.clicked.connect(self.add_file)
        b_paste = QtWidgets.QPushButton("貼り付け")
        b_paste.setToolTip("Excel等からコピーした表を新規データとして読み込む（Ctrl+Shift+V）")
        b_paste.clicked.connect(self.paste_from_clipboard)
        b_del = QtWidgets.QPushButton("削除")
        b_del.setToolTip("選択中のファイルを削除（Ctrl/Shift＋クリックで複数選択→まとめて削除）")
        b_del.clicked.connect(self.remove_file)
        b_clear = QtWidgets.QPushButton("全削除")
        b_clear.setToolTip("読み込み済みファイルをすべて一覧から削除します。")
        b_clear.clicked.connect(self.clear_all_files)
        row.addWidget(b_add); row.addWidget(b_paste)
        tv.addLayout(row)
        row_b = QtWidgets.QHBoxLayout()
        row_b.addWidget(b_del); row_b.addWidget(b_clear)
        tv.addLayout(row_b)
        vsplit.addWidget(top)

        # === 下段：読み込み設定・X/Y選択・描画 ===
        bottom = QtWidgets.QWidget(); v = QtWidgets.QVBoxLayout(bottom)
        v.setContentsMargins(2, 2, 2, 2)
        # 区切り・文字コード（自動含む）
        grid = QtWidgets.QGridLayout()
        grid.addWidget(QtWidgets.QLabel("区切り:"), 0, 0)
        self.delim_combo = QtWidgets.QComboBox()
        self.delim_combo.addItem("自動判別")
        for lbl in DELIMITER_LABELS.values():
            self.delim_combo.addItem(lbl)
        grid.addWidget(self.delim_combo, 0, 1)
        self.delim_combo.setToolTip("区切り文字。変更後は「選択中ファイルを再読込」を押してください。")
        grid.addWidget(QtWidgets.QLabel("文字コード:"), 1, 0)
        self.enc_combo = QtWidgets.QComboBox()
        self.enc_combo.addItems(["自動判別", "utf-8-sig", "utf-8", "cp932",
                                 "shift_jis", "euc-jp", "utf-16"])
        self.enc_combo.setToolTip("文字化けする場合はここで指定し、「選択中ファイルを再読込」を押します。")
        grid.addWidget(self.enc_combo, 1, 1)
        b_reload = QtWidgets.QPushButton("選択中ファイルを再読込")
        b_reload.setToolTip("区切り・文字コードの変更を反映して読み直します。")
        b_reload.clicked.connect(self.reload_current)
        grid.addWidget(b_reload, 2, 0, 1, 2)
        v.addLayout(grid)

        v.addWidget(self._hline())
        v.addWidget(QtWidgets.QLabel("X軸（横軸 / ラベル）"))
        self.xleft_check = QtWidgets.QCheckBox("一番左の列をX軸にする（位置で固定）")
        self.xleft_check.setToolTip(
            "ONにすると各ファイルの『一番左の列』をX軸に使います（列名が違っても適用）。\n"
            "複数ファイル／バッチ出力でX軸を固定したいときに便利。\n"
            "OFFなら下のコンボで列名を指定します。")
        self.xleft_check.toggled.connect(self._on_xleft_toggled)
        v.addWidget(self.xleft_check)
        self.x_combo = QtWidgets.QComboBox()
        self.x_combo.setToolTip("横軸に使う列（列名で指定）。波形なら時間列を選びます。")
        self.x_combo.currentTextChanged.connect(self._on_x_changed)
        v.addWidget(self.x_combo)

        ylab = QtWidgets.QLabel("Y軸（値）※チェックした系列を描画（行クリックでON/OFF）")
        ylab.setWordWrap(True)
        v.addWidget(ylab)
        self.y_list = CheckListWidget()
        self.y_list.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.NoSelection)
        self.y_list.setToolTip("描画したい系列にチェック。ダブルクリック=その系列だけ表示／"
                               "右クリック=表示メニュー（この系列だけ／非表示／すべて表示）")
        self.y_list.setStyleSheet("QListWidget::indicator { width:16px; height:16px; }")
        self.y_list.itemChanged.connect(self._on_y_check_changed)
        self.y_list.itemDoubleClicked.connect(self._on_y_double_clicked)
        self.y_list.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.y_list.customContextMenuRequested.connect(self._y_list_menu)
        v.addWidget(self.y_list, 1)
        ybtns = QtWidgets.QHBoxLayout()
        for text, fn in (("全選択", lambda: self._check_all_y(True)),
                         ("全解除", lambda: self._check_all_y(False)),
                         ("反転", self._invert_y)):
            btn = QtWidgets.QPushButton(text); btn.clicked.connect(fn)
            ybtns.addWidget(btn)
        v.addLayout(ybtns)

        # リアルタイム更新 / 間引き / 描画ボタン（データタブからも描けるように）
        self.live_check = QtWidgets.QCheckBox("リアルタイム更新（変更を即反映）")
        self.live_check.setChecked(True)
        self.live_check.setToolTip("オンにすると設定変更が自動で描画に反映されます。大容量データではオフ推奨。")
        v.addWidget(self.live_check)
        self.decimate_check = QtWidgets.QCheckBox("大容量データを間引き表示")
        self.decimate_check.setChecked(True)
        self.decimate_check.setToolTip("折れ線/散布図で点数が多いとき、見た目を保ったまま間引いて高速描画します"
                                       "（ズーム時は自動で再サンプルします）。")
        v.addWidget(self.decimate_check)
        drow = QtWidgets.QHBoxLayout()
        b_draw = QtWidgets.QPushButton("グラフを描画 (F5)")
        b_draw.setStyleSheet("font-weight:bold; padding:6px;")
        b_draw.clicked.connect(self.draw_graph)
        b_batch2 = QtWidgets.QPushButton("一括画像保存...")
        b_batch2.setStyleSheet("padding:6px;")
        b_batch2.setToolTip("読み込んだ各ファイルを個別に描画し、ファイル名ごとの画像として一括保存します"
                            "（タイトル・形式・DPI等は次の画面で調整できます）。")
        b_batch2.clicked.connect(self.batch_export)
        drow.addWidget(b_draw, 2); drow.addWidget(b_batch2, 1)
        v.addLayout(drow)
        vsplit.addWidget(bottom)
        vsplit.setStretchFactor(0, 0)
        vsplit.setStretchFactor(1, 1)
        vsplit.setSizes([140, 520])
        return w

    # ---- 右側：グラフ書式調整パネル ----
    def _build_style_box(self):
        """系列スタイル表（色/線種/軸/種別/誤差列）。書式調整パネルの下段に置く。"""
        box = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(box); v.setContentsMargins(4, 4, 4, 4)
        v.addWidget(self._bold("系列スタイル（系列名はダブルクリックで変更可）"))
        self.style_table = QtWidgets.QTableWidget(0, 9)
        self.style_table.setHorizontalHeaderLabels(
            ["系列名", "色", "線種", "幅", "マーカー", "サイズ", "軸", "種別", "誤差列"])
        self.style_table.horizontalHeader().setStretchLastSection(True)
        self.style_table.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.DoubleClicked
            | QtWidgets.QAbstractItemView.EditTrigger.EditKeyPressed)
        self.style_table.itemChanged.connect(self._on_style_label_edited)
        v.addWidget(self.style_table, 1)
        return box

    def _build_format_panel(self):
        """右端のグラフ書式調整パネル（上：グラフ書式コントロール／下：系列スタイル表）。"""
        split = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
        split.setMinimumWidth(360)
        scroll = QtWidgets.QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        scroll.setWidget(self._build_tab_graph())   # 種別/タイトル/軸/近似曲線/縦横比/画像出力
        split.addWidget(scroll)
        split.addWidget(self._build_style_box())     # 系列スタイル表
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        return split

    # ---- グラフ書式コントロール（右パネル上段）----
    def _build_tab_graph(self):
        w = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(w)

        # 書式プリセット（今の見た目に名前を付けて保存・呼び出し）
        pre = QtWidgets.QHBoxLayout()
        pre.addWidget(QtWidgets.QLabel("書式プリセット"))
        self.preset_combo = QtWidgets.QComboBox()
        self.preset_combo.setToolTip("保存した書式（フォント・グリッド・凡例・色・軸など）を呼び出します。")
        pre.addWidget(self.preset_combo, 1)
        b_pa = QtWidgets.QPushButton("適用"); b_pa.clicked.connect(self.apply_preset)
        b_ps = QtWidgets.QPushButton("保存"); b_ps.clicked.connect(self.save_preset)
        b_ps.setToolTip("現在の書式設定に名前を付けて保存")
        b_pd = QtWidgets.QPushButton("削除"); b_pd.clicked.connect(self.delete_preset)
        pre.addWidget(b_pa); pre.addWidget(b_ps); pre.addWidget(b_pd)
        v.addLayout(pre)
        self._refresh_preset_combo()

        v.addWidget(self._bold("グラフ種別"))
        self.chart_combo = QtWidgets.QComboBox()
        self.chart_combo.addItems(CHART_TYPES)
        self.chart_combo.currentTextChanged.connect(self._on_chart_type_change)
        v.addWidget(self.chart_combo)
        self.hint_label = QtWidgets.QLabel()
        self.hint_label.setWordWrap(True)
        self.hint_label.setStyleSheet("color:#0a7a55;")
        v.addWidget(self.hint_label)

        # タイトル・ラベル・フォント
        form = QtWidgets.QGridLayout()
        form.addWidget(QtWidgets.QLabel("タイトル"), 0, 0)
        self.title_edit = QtWidgets.QLineEdit()
        form.addWidget(self.title_edit, 0, 1, 1, 3)
        form.addWidget(QtWidgets.QLabel("X軸名"), 1, 0)
        self.xlabel_edit = QtWidgets.QLineEdit()
        form.addWidget(self.xlabel_edit, 1, 1)
        form.addWidget(QtWidgets.QLabel("Y軸名"), 1, 2)
        self.ylabel_edit = QtWidgets.QLineEdit()
        form.addWidget(self.ylabel_edit, 1, 3)
        form.addWidget(QtWidgets.QLabel("文字サイズ 題/軸/目盛"), 2, 0)
        self.fs_title = QtWidgets.QSpinBox(); self.fs_title.setRange(6, 40); self.fs_title.setValue(12)
        self.fs_label = QtWidgets.QSpinBox(); self.fs_label.setRange(6, 40); self.fs_label.setValue(10)
        self.fs_tick = QtWidgets.QSpinBox(); self.fs_tick.setRange(6, 40); self.fs_tick.setValue(9)
        form.addWidget(self.fs_title, 2, 1); form.addWidget(self.fs_label, 2, 2); form.addWidget(self.fs_tick, 2, 3)
        # 文字サイズ 凡例 / 注記（グラフ上の測定値・統計の注記ボックス）
        form.addWidget(QtWidgets.QLabel("文字サイズ 凡例/注記"), 5, 0)
        self.fs_legend = QtWidgets.QSpinBox(); self.fs_legend.setRange(6, 40); self.fs_legend.setValue(9)
        self.fs_legend.setToolTip("凡例の文字サイズ")
        self.fs_annot = QtWidgets.QSpinBox(); self.fs_annot.setRange(6, 40); self.fs_annot.setValue(9)
        self.fs_annot.setToolTip("グラフ上に表示する注記（データサイエンス・測定値のチェック表示）の文字サイズ")
        form.addWidget(self.fs_legend, 5, 1); form.addWidget(self.fs_annot, 5, 2)
        # 軸の単位と倍率（単位を変える＝数値も換算）。倍率1・単位空なら無効。
        form.addWidget(QtWidgets.QLabel("X単位"), 3, 0)
        self.xunit_edit = QtWidgets.QLineEdit(); self.xunit_edit.setPlaceholderText("例: ms")
        self.xunit_edit.setToolTip("X軸ラベルに付ける単位。右の倍率で軸の数値も換算されます。")
        form.addWidget(self.xunit_edit, 3, 1)
        form.addWidget(QtWidgets.QLabel("X倍率"), 3, 2)
        self.xscale_edit = QtWidgets.QLineEdit("1")
        self.xscale_edit.setToolTip("X軸の数値に掛ける倍率。例: 秒→ミリ秒は 1000。")
        form.addWidget(self.xscale_edit, 3, 3)
        form.addWidget(QtWidgets.QLabel("Y単位"), 4, 0)
        self.yunit_edit = QtWidgets.QLineEdit(); self.yunit_edit.setPlaceholderText("例: mV")
        self.yunit_edit.setToolTip("Y軸ラベルに付ける単位。右の倍率で軸の数値も換算されます（主軸）。")
        form.addWidget(self.yunit_edit, 4, 1)
        form.addWidget(QtWidgets.QLabel("Y倍率"), 4, 2)
        self.yscale_edit = QtWidgets.QLineEdit("1")
        self.yscale_edit.setToolTip("Y軸の数値に掛ける倍率。例: V→mV は 1000。")
        form.addWidget(self.yscale_edit, 4, 3)
        v.addLayout(form)

        # オプション行
        opt = QtWidgets.QHBoxLayout()
        self.grid_check = QtWidgets.QCheckBox("グリッド"); self.grid_check.setChecked(True)
        self.legend_check = QtWidgets.QCheckBox("凡例"); self.legend_check.setChecked(True)
        opt.addWidget(self.grid_check); opt.addWidget(self.legend_check)
        opt.addWidget(QtWidgets.QLabel("凡例位置"))
        self.legend_loc = QtWidgets.QComboBox(); self.legend_loc.addItems(LEGEND_LOCS)
        opt.addWidget(self.legend_loc)
        # 凡例の系列名にファイル名を含めるか／拡張子を含めるか（複数ファイル時に有効）
        self.show_filename_check = QtWidgets.QCheckBox("凡例にファイル名"); self.show_filename_check.setChecked(True)
        self.show_filename_check.setToolTip("複数ファイル時、凡例の系列名に『ファイル名 | 列名』のように\n"
                                            "ファイル名を含めます。オフにすると列名だけになります。")
        self.show_ext_check = QtWidgets.QCheckBox("拡張子"); self.show_ext_check.setChecked(True)
        self.show_ext_check.setToolTip("凡例に表示するファイル名に拡張子（.csv など）を含めます。\n"
                                       "オフにすると拡張子を除いた名前になります。")
        opt.addWidget(self.show_filename_check); opt.addWidget(self.show_ext_check)
        # 背景色（空=自動: 通常は白・オシロは濃色。指定すると両方その色になる）
        self.bg_color = ""
        self.bg_btn = QtWidgets.QPushButton("背景色: 自動")
        self.bg_btn.setToolTip("プロット領域の背景色。クリックで色を選択／右クリックで自動に戻す。\n"
                               "『自動』は通常=白・オシロ=濃色。オシロでも好きな色にできます。")
        self.bg_btn.clicked.connect(self._pick_bg_color)
        self.bg_btn.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.bg_btn.customContextMenuRequested.connect(lambda *_: self._reset_bg_color())
        opt.addWidget(self.bg_btn)
        opt.addStretch(1)
        v.addLayout(opt)

        # 線の太さ（枠線＝プロットの外枠／グリッド線）
        lw = QtWidgets.QHBoxLayout()
        lw.addWidget(QtWidgets.QLabel("線の太さ  枠線"))
        self.frame_width = QtWidgets.QDoubleSpinBox()
        self.frame_width.setRange(0.0, 6.0); self.frame_width.setSingleStep(0.2); self.frame_width.setValue(0.8)
        self.frame_width.setToolTip("グラフの外枠（軸の枠線）の太さ。0 で枠を消します。")
        lw.addWidget(self.frame_width)
        lw.addWidget(QtWidgets.QLabel("グリッド線"))
        self.grid_width = QtWidgets.QDoubleSpinBox()
        self.grid_width.setRange(0.2, 6.0); self.grid_width.setSingleStep(0.2); self.grid_width.setValue(0.8)
        self.grid_width.setToolTip("グリッド線の太さ（「グリッド」オン時）。")
        lw.addWidget(self.grid_width)
        lw.addStretch(1)
        v.addLayout(lw)

        # 軸範囲・対数
        ax = QtWidgets.QGridLayout()
        ax.addWidget(QtWidgets.QLabel("X範囲 min/max"), 0, 0)
        self.xmin = QtWidgets.QLineEdit(); self.xmin.setPlaceholderText("自動")
        self.xmax = QtWidgets.QLineEdit(); self.xmax.setPlaceholderText("自動")
        ax.addWidget(self.xmin, 0, 1); ax.addWidget(self.xmax, 0, 2)
        self.xlog = QtWidgets.QCheckBox("X対数"); ax.addWidget(self.xlog, 0, 3)
        ax.addWidget(QtWidgets.QLabel("Y範囲 min/max"), 1, 0)
        self.ymin = QtWidgets.QLineEdit(); self.ymin.setPlaceholderText("自動")
        self.ymax = QtWidgets.QLineEdit(); self.ymax.setPlaceholderText("自動")
        ax.addWidget(self.ymin, 1, 1); ax.addWidget(self.ymax, 1, 2)
        self.ylog = QtWidgets.QCheckBox("Y対数"); ax.addWidget(self.ylog, 1, 3)
        # 目盛り間隔（メモリ間隔）。空欄=自動。折れ線/散布図の数値軸で有効（対数軸は除く）
        ax.addWidget(QtWidgets.QLabel("目盛り間隔 X/Y"), 2, 0)
        self.xtick_edit = QtWidgets.QLineEdit(); self.xtick_edit.setPlaceholderText("自動")
        self.xtick_edit.setToolTip("X軸の目盛り間隔（1メモリの値）。空欄=自動。例: 0.5。\n"
                                   "折れ線/散布図の数値軸で有効。対数軸・カテゴリ軸では無効。")
        self.ytick_edit = QtWidgets.QLineEdit(); self.ytick_edit.setPlaceholderText("自動")
        self.ytick_edit.setToolTip("Y軸の目盛り間隔（1メモリの値）。空欄=自動。例: 10。対数軸では無効。")
        ax.addWidget(self.xtick_edit, 2, 1); ax.addWidget(self.ytick_edit, 2, 2)
        # 軸の向き反転（0→1 を 1→0 のように）
        ax.addWidget(QtWidgets.QLabel("軸反転"), 3, 0)
        self.xinvert_check = QtWidgets.QCheckBox("X軸反転")
        self.xinvert_check.setToolTip("X軸の向きを反転します（例: 0→1 を 1→0 に）。")
        self.yinvert_check = QtWidgets.QCheckBox("Y軸反転")
        self.yinvert_check.setToolTip("Y軸の向きを反転します（例: 下→上 を 上→下 に）。")
        ax.addWidget(self.xinvert_check, 3, 1); ax.addWidget(self.yinvert_check, 3, 2)
        v.addLayout(ax)

        # 近似曲線（トレンドライン）・データラベル（折れ線/散布図向け）
        tl = QtWidgets.QHBoxLayout()
        tl.addWidget(QtWidgets.QLabel("近似曲線"))
        self.trend_combo = QtWidgets.QComboBox(); self.trend_combo.addItems(TRENDLINES)
        self.trend_combo.setToolTip("折れ線/散布図の各系列に近似曲線を重ねる")
        tl.addWidget(self.trend_combo)
        tl.addWidget(QtWidgets.QLabel("次数"))
        self.trend_degree = QtWidgets.QSpinBox(); self.trend_degree.setRange(1, 6); self.trend_degree.setValue(2)
        self.trend_degree.setToolTip("多項式近似の次数")
        tl.addWidget(self.trend_degree)
        tl.addWidget(QtWidgets.QLabel("窓"))
        self.trend_window = QtWidgets.QSpinBox(); self.trend_window.setRange(2, 9999); self.trend_window.setValue(5)
        self.trend_window.setToolTip("移動平均の窓幅")
        tl.addWidget(self.trend_window)
        # 近似曲線の色（空=自動: 系列と同じ色）。クリックで選択／右クリックで自動に戻す
        self.trend_color = ""
        self.trend_color_btn = QtWidgets.QPushButton("色: 自動")
        self.trend_color_btn.setToolTip("近似曲線の色。クリックで色を選択／右クリックで自動（系列と同じ色）に戻す。")
        self.trend_color_btn.clicked.connect(self._pick_trend_color)
        self.trend_color_btn.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.trend_color_btn.customContextMenuRequested.connect(lambda *_: self._reset_trend_color())
        tl.addWidget(self.trend_color_btn)
        self.trend_eq = QtWidgets.QCheckBox("数式/R²"); self.trend_eq.setChecked(True)
        tl.addWidget(self.trend_eq)
        self.data_labels_check = QtWidgets.QCheckBox("データラベル")
        self.data_labels_check.setToolTip("各データ点/棒に値を表示（点数が多い場合は間引き）")
        tl.addWidget(self.data_labels_check)
        tl.addStretch(1)
        v.addLayout(tl)

        # ビン数・パーセント
        extra = QtWidgets.QHBoxLayout()
        self.bins_caption = QtWidgets.QLabel("ビン数:")
        extra.addWidget(self.bins_caption)
        self.bins_spin = QtWidgets.QSpinBox(); self.bins_spin.setRange(1, 500); self.bins_spin.setValue(30)
        extra.addWidget(self.bins_spin)
        self.pct_check = QtWidgets.QCheckBox("円グラフ％表示"); self.pct_check.setChecked(True)
        extra.addWidget(self.pct_check); extra.addStretch(1)
        v.addLayout(extra)

        # 縦横比（プロット領域のアスペクト比を固定）
        ar = QtWidgets.QHBoxLayout()
        ar.addWidget(QtWidgets.QLabel("縦横比"))
        self.aspect_combo = QtWidgets.QComboBox()
        self.aspect_combo.addItems(["自動（画面に合わせる）", "16:9", "4:3", "3:2", "1:1",
                                    "9:16（縦）", "A4横", "A4縦", "カスタム"])
        self.aspect_combo.setToolTip("プロット領域の縦横比を固定します（画面表示・画像出力の両方に反映）。"
                                     "「自動」はウィンドウに合わせます。")
        ar.addWidget(self.aspect_combo)
        ar.addWidget(QtWidgets.QLabel("カスタム W:H"))
        self.aspect_w = QtWidgets.QSpinBox(); self.aspect_w.setRange(1, 100); self.aspect_w.setValue(16)
        self.aspect_h = QtWidgets.QSpinBox(); self.aspect_h.setRange(1, 100); self.aspect_h.setValue(9)
        ar.addWidget(self.aspect_w); ar.addWidget(QtWidgets.QLabel(":")); ar.addWidget(self.aspect_h)
        ar.addStretch(1)
        v.addLayout(ar)
        self.aspect_combo.currentTextChanged.connect(self._on_aspect_changed)
        self._on_aspect_changed()

        # 画像出力（解像度・背景透過つき）
        v.addWidget(self._hline())
        v.addWidget(self._bold("画像出力"))
        exp = QtWidgets.QHBoxLayout()
        exp.addWidget(QtWidgets.QLabel("解像度 DPI"))
        self.dpi_spin = QtWidgets.QSpinBox()
        self.dpi_spin.setRange(50, 1200); self.dpi_spin.setSingleStep(50); self.dpi_spin.setValue(150)
        exp.addWidget(self.dpi_spin)
        self.transparent_check = QtWidgets.QCheckBox("背景透過")
        exp.addWidget(self.transparent_check)
        exp.addStretch(1)
        v.addLayout(exp)
        exp2 = QtWidgets.QHBoxLayout()
        b_save = QtWidgets.QPushButton("画像を保存...")
        b_save.clicked.connect(self.save_figure)
        b_copy = QtWidgets.QPushButton("クリップボードにコピー")
        b_copy.clicked.connect(self.copy_figure)
        exp2.addWidget(b_save); exp2.addWidget(b_copy)
        v.addLayout(exp2)
        b_batch = QtWidgets.QPushButton("ファイルごとに一括出力...")
        b_batch.setToolTip("読み込んだ各ファイルを、現在の設定（種別・選択列名・スタイル等）で"
                           "個別に描画し、ファイル名ごとの画像として一括保存します。")
        b_batch.clicked.connect(self.batch_export)
        v.addWidget(b_batch)
        v.addStretch(1)   # 余白を下にまとめ、各行の不自然な隙間をなくす
        return w

    # ---- オシロ/解析タブ ----
    def _build_tab_scope(self):
        w = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(w)

        self.scope_check = QtWidgets.QCheckBox("オシロスコープ表示（折れ線/散布図）")
        v.addWidget(self.scope_check)
        g = QtWidgets.QGridLayout()
        g.addWidget(QtWidgets.QLabel("time/div [s]"), 0, 0)
        self.tdiv = QtWidgets.QComboBox(); self.tdiv.setEditable(True)
        self.tdiv.addItems(eng_125_sequence(1e-9, 1.0, "s"))
        self.tdiv.setCurrentText("1ms")
        g.addWidget(self.tdiv, 0, 1)
        g.addWidget(QtWidgets.QLabel("V/div"), 0, 2)
        self.vdiv = QtWidgets.QComboBox(); self.vdiv.setEditable(True)
        self.vdiv.addItems(eng_125_sequence(1e-3, 100.0, ""))
        self.vdiv.setCurrentText("500m")
        g.addWidget(self.vdiv, 0, 3)
        g.addWidget(QtWidgets.QLabel("X位置(中心)"), 1, 0)
        self.xpos = QtWidgets.QLineEdit("0"); g.addWidget(self.xpos, 1, 1)
        g.addWidget(QtWidgets.QLabel("Y位置(中心)"), 1, 2)
        self.ypos = QtWidgets.QLineEdit("0"); g.addWidget(self.ypos, 1, 3)
        g.addWidget(QtWidgets.QLabel("X div数"), 2, 0)
        self.xdivs = QtWidgets.QSpinBox(); self.xdivs.setRange(2, 20); self.xdivs.setValue(10)
        g.addWidget(self.xdivs, 2, 1)
        g.addWidget(QtWidgets.QLabel("Y div数"), 2, 2)
        self.ydivs = QtWidgets.QSpinBox(); self.ydivs.setRange(2, 20); self.ydivs.setValue(8)
        g.addWidget(self.ydivs, 2, 3)
        v.addLayout(g)
        b_auto = QtWidgets.QPushButton("自動スケール（解析対象に合わせる）")
        b_auto.clicked.connect(self.auto_scale_scope)
        v.addWidget(b_auto)
        scope_hint = QtWidgets.QLabel(
            "💡 オシロ表示中はグラフを直接操作可：左ドラッグ=位置移動／右ドラッグ=time/V/div／"
            "ホイール=time/div・Shift+ホイール=V/div（ドラッグ中は数値を表示）")
        scope_hint.setWordWrap(True); scope_hint.setStyleSheet("color:#0a7a55; font-size:11px;")
        v.addWidget(scope_hint)

        v.addWidget(self._hline())
        # 解析対象
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("解析対象:"))
        self.analysis_target = QtWidgets.QComboBox()
        row.addWidget(self.analysis_target, 1)
        v.addLayout(row)
        row2 = QtWidgets.QHBoxLayout()
        row2.addWidget(QtWidgets.QLabel("ピーク数 N:"))
        self.npeaks = QtWidgets.QSpinBox(); self.npeaks.setRange(1, 50); self.npeaks.setValue(5)
        row2.addWidget(self.npeaks)
        row2.addWidget(QtWidgets.QLabel("平滑化(点):"))
        self.smooth_spin = QtWidgets.QSpinBox(); self.smooth_spin.setRange(0, 501)
        self.smooth_spin.setSingleStep(2); self.smooth_spin.setValue(0)
        self.smooth_spin.setToolTip("ノイズの多い実測データで偽ピークを抑える。0=平滑化なし。窓の点数（奇数推奨）。")
        row2.addWidget(self.smooth_spin); row2.addStretch(1)
        v.addLayout(row2)
        self.show_peaks_check = QtWidgets.QCheckBox("ピークをグラフに表示"); self.show_peaks_check.setChecked(False)
        v.addWidget(self.show_peaks_check)
        self.window_meas_check = QtWidgets.QCheckBox("表示範囲のみ測定（ズーム/オシロ窓に追従）")
        self.window_meas_check.setToolTip("オンにすると、画面に見えているX範囲だけを対象に解析します。")
        v.addWidget(self.window_meas_check)
        # 解析アクションは4個。1行に詰めると見切れるので2段に分ける
        b_an = QtWidgets.QPushButton("解析実行"); b_an.clicked.connect(self.run_analysis)
        b_an.setToolTip("解析対象コンボで選んだ1系列のピーク・測定を下の表に表示")
        b_all = QtWidgets.QPushButton("全系列を解析…")
        b_all.setToolTip("選択中の全系列のピーク・測定を別ウィンドウに一覧表示（CSV保存可）")
        b_all.clicked.connect(self.analyze_all_series)
        b_fft = QtWidgets.QPushButton("FFTスペクトル表示"); b_fft.clicked.connect(self.show_fft)
        b_fft.setToolTip("選択中の全系列のFFTを1枚に重ね描き（系列ごとに色分け）")
        b_cur = QtWidgets.QPushButton("カーソル測定"); b_cur.setCheckable(True)
        b_cur.setToolTip("グラフを2回クリックして Δt・ΔV・1/Δt を測ります")
        b_cur.toggled.connect(self.toggle_cursors)
        self.cursor_btn = b_cur
        brow = QtWidgets.QHBoxLayout()
        brow.addWidget(b_an); brow.addWidget(b_all)
        v.addLayout(brow)
        brow2 = QtWidgets.QHBoxLayout()
        brow2.addWidget(b_fft); brow2.addWidget(b_cur)
        v.addLayout(brow2)

        v.addWidget(self._bold("ピーク（第1=最大）"))
        self.peak_table = QtWidgets.QTableWidget(0, 3)
        self.peak_table.setHorizontalHeaderLabels(["順位", "時間/周波数", "値"])
        self.peak_table.horizontalHeader().setStretchLastSection(True)
        self.peak_table.setMaximumHeight(160)
        v.addWidget(self.peak_table)

        v.addWidget(self._bold("測定値（右端「表示」でグラフに注記）"))
        self.meas_table = QtWidgets.QTableWidget(0, 3)
        self.meas_table.setHorizontalHeaderLabels(["項目", "値", "表示"])
        mh = self.meas_table.horizontalHeader()
        mh.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        mh.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Stretch)
        mh.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        self.meas_table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        v.addWidget(self.meas_table, 1)
        # 統計・トレンド・位相
        srow = QtWidgets.QHBoxLayout()
        b_stat = QtWidgets.QPushButton("サイクル統計"); b_stat.clicked.connect(self.show_cycle_stats)
        b_trend = QtWidgets.QPushButton("トレンド表示"); b_trend.clicked.connect(self.show_trend)
        b_pstat = QtWidgets.QPushButton("パラメータ統計…")
        b_pstat.setToolTip("サイクルごとの統計（平均/最大/最小/σ）とパラメータ間演算を別ウィンドウで表示")
        b_pstat.clicked.connect(self.show_param_stats)
        srow.addWidget(b_stat); srow.addWidget(b_trend); srow.addWidget(b_pstat)
        v.addLayout(srow)
        prow = QtWidgets.QHBoxLayout()
        prow.addWidget(QtWidgets.QLabel("位相差 対象2:"))
        self.phase_target2 = QtWidgets.QComboBox(); prow.addWidget(self.phase_target2, 1)
        b_phase = QtWidgets.QPushButton("位相差/遅延"); b_phase.clicked.connect(self.show_phase)
        prow.addWidget(b_phase)
        v.addLayout(prow)
        return w

    # ---- 高度解析タブ ----
    def _build_tab_advanced(self):
        outer = QtWidgets.QScrollArea(); outer.setWidgetResizable(True)
        w = QtWidgets.QWidget(); outer.setWidget(w)
        v = QtWidgets.QVBoxLayout(w)

        # --- 数学チャンネル ---
        v.addWidget(self._bold("数学チャンネル（演算で新しい波形を作成）"))
        mg = QtWidgets.QGridLayout()
        mg.addWidget(QtWidgets.QLabel("演算"), 0, 0)
        self.math_op = QtWidgets.QComboBox()
        self.math_op.addItems(BINARY_OPS + UNARY_OPS)
        self.math_op.currentTextChanged.connect(self._on_math_op_change)
        mg.addWidget(self.math_op, 0, 1, 1, 3)
        mg.addWidget(QtWidgets.QLabel("A"), 1, 0)
        self.math_a = QtWidgets.QComboBox(); mg.addWidget(self.math_a, 1, 1)
        self.math_b_label = QtWidgets.QLabel("B"); mg.addWidget(self.math_b_label, 1, 2)
        self.math_b = QtWidgets.QComboBox(); mg.addWidget(self.math_b, 1, 3)
        self.math_param_label = QtWidgets.QLabel("パラメータ"); mg.addWidget(self.math_param_label, 2, 0)
        self.math_param = QtWidgets.QLineEdit("5"); self.math_param.setToolTip("移動平均=窓長(点)、ローパス=カットオフ[Hz]")
        mg.addWidget(self.math_param, 2, 1)
        b_math = QtWidgets.QPushButton("数学チャンネルを作成"); b_math.clicked.connect(self.create_math_channel)
        mg.addWidget(b_math, 2, 2, 1, 2)
        v.addLayout(mg)
        # 任意数式（A,B,VAR1,VAR2,t と関数で自由に演算）
        eg = QtWidgets.QGridLayout()
        eg.addWidget(QtWidgets.QLabel("数式"), 0, 0)
        self.math_expr = QtWidgets.QLineEdit()
        self.math_expr.setPlaceholderText("例: sqrt(A**2+B**2) / sin(2*pi*t)*VAR1 / A-VAR1")
        self.math_expr.setToolTip("変数: A=対象A, B=対象B, t=時間, VAR1, VAR2, 定数 pi/e。\n"
                                  "関数: sin/cos/tan/asin/.../exp/log/log10/log2/sqrt/abs/sign/min/max/clip/where。")
        eg.addWidget(self.math_expr, 0, 1, 1, 3)
        eg.addWidget(QtWidgets.QLabel("VAR1"), 1, 0)
        self.math_var1 = QtWidgets.QLineEdit("1"); eg.addWidget(self.math_var1, 1, 1)
        eg.addWidget(QtWidgets.QLabel("VAR2"), 1, 2)
        self.math_var2 = QtWidgets.QLineEdit("0"); eg.addWidget(self.math_var2, 1, 3)
        b_expr = QtWidgets.QPushButton("数式でチャンネル作成"); b_expr.clicked.connect(self.create_math_expr)
        eg.addWidget(b_expr, 2, 0, 1, 4)
        v.addLayout(eg)
        v.addWidget(self._hline())

        # --- FFT 詳細 ---
        v.addWidget(self._bold("FFT 詳細（窓・dB・THD/SNR・スペクトログラム）"))
        fg = QtWidgets.QGridLayout()
        fg.addWidget(QtWidgets.QLabel("窓関数"), 0, 0)
        self.fft_window = QtWidgets.QComboBox(); self.fft_window.addItems(WINDOWS)
        self.fft_window.setCurrentText("hann"); fg.addWidget(self.fft_window, 0, 1)
        self.fft_db = QtWidgets.QCheckBox("dB表示"); fg.addWidget(self.fft_db, 0, 2)
        b_m = QtWidgets.QPushButton("THD/SNR等を計算"); b_m.clicked.connect(self.compute_fft_metrics)
        fg.addWidget(b_m, 1, 0, 1, 2)
        b_sp = QtWidgets.QPushButton("スペクトログラム"); b_sp.clicked.connect(self.show_spectrogram)
        fg.addWidget(b_sp, 1, 2, 1, 1)
        v.addLayout(fg)
        self.fft_metrics = QtWidgets.QTableWidget(0, 2)
        self.fft_metrics.setHorizontalHeaderLabels(["指標", "値"])
        self.fft_metrics.horizontalHeader().setStretchLastSection(True)
        self.fft_metrics.setMaximumHeight(170)
        v.addWidget(self.fft_metrics)
        v.addWidget(self._hline())

        # --- マスク試験 / アイ / ジッタ ---
        v.addWidget(self._bold("マスク試験 / アイダイアグラム / ジッタ"))
        mk = QtWidgets.QGridLayout()
        mk.addWidget(QtWidgets.QLabel("上限"), 0, 0)
        self.mask_upper = QtWidgets.QLineEdit(); self.mask_upper.setPlaceholderText("なし")
        mk.addWidget(self.mask_upper, 0, 1)
        mk.addWidget(QtWidgets.QLabel("下限"), 0, 2)
        self.mask_lower = QtWidgets.QLineEdit(); self.mask_lower.setPlaceholderText("なし")
        mk.addWidget(self.mask_lower, 0, 3)
        b_mask = QtWidgets.QPushButton("マスク判定"); b_mask.clicked.connect(self.run_mask_test)
        mk.addWidget(b_mask, 1, 0, 1, 2)
        mk.addWidget(QtWidgets.QLabel("シンボルレート[Hz]/周期[s]"), 2, 0, 1, 2)
        self.eye_rate = QtWidgets.QLineEdit("1e6"); mk.addWidget(self.eye_rate, 2, 2)
        b_eye = QtWidgets.QPushButton("アイダイアグラム"); b_eye.clicked.connect(self.show_eye_diagram)
        mk.addWidget(b_eye, 2, 3)
        b_jit = QtWidgets.QPushButton("ジッタ解析(TIE)"); b_jit.clicked.connect(self.run_jitter)
        mk.addWidget(b_jit, 1, 2, 1, 2)
        v.addLayout(mk)
        self.adv_result = QtWidgets.QLabel(""); self.adv_result.setWordWrap(True)
        self.adv_result.setStyleSheet("color:#0a3;")
        v.addWidget(self.adv_result)
        v.addWidget(self._hline())

        # --- プロトコル解読 ---
        v.addWidget(self._bold("シリアルプロトコル解読"))
        pg = QtWidgets.QGridLayout()
        pg.addWidget(QtWidgets.QLabel("プロトコル"), 0, 0)
        self.proto_combo = QtWidgets.QComboBox(); self.proto_combo.addItems(["UART", "I2C", "SPI"])
        self.proto_combo.currentTextChanged.connect(self._on_proto_change)
        pg.addWidget(self.proto_combo, 0, 1)
        pg.addWidget(QtWidgets.QLabel("ボーレート/不使用"), 0, 2)
        self.proto_baud = QtWidgets.QLineEdit("115200"); pg.addWidget(self.proto_baud, 0, 3)
        self.proto_ch_labels = [QtWidgets.QLabel("Ch1"), QtWidgets.QLabel("Ch2"), QtWidgets.QLabel("Ch3")]
        self.proto_ch = [QtWidgets.QComboBox(), QtWidgets.QComboBox(), QtWidgets.QComboBox()]
        for i in range(3):
            pg.addWidget(self.proto_ch_labels[i], 1 + i, 0)
            pg.addWidget(self.proto_ch[i], 1 + i, 1, 1, 3)
        b_dec = QtWidgets.QPushButton("解読"); b_dec.clicked.connect(self.decode_protocol)
        pg.addWidget(b_dec, 4, 0, 1, 4)
        v.addLayout(pg)
        self.proto_table = QtWidgets.QTableWidget(0, 4)
        self.proto_table.setHorizontalHeaderLabels(["時刻", "種別", "値(hex)", "備考"])
        self.proto_table.horizontalHeader().setStretchLastSection(True)
        v.addWidget(self.proto_table, 1)

        self._on_math_op_change(self.math_op.currentText())
        self._on_proto_change("UART")
        return outer

    # ---- データサイエンスタブ ----
    def _build_tab_datasci(self):
        outer = QtWidgets.QScrollArea(); outer.setWidgetResizable(True)
        w = QtWidgets.QWidget(); outer.setWidget(w)
        v = QtWidgets.QVBoxLayout(w)

        v.addWidget(self._bold("データサイエンス（回帰・統計・相関）"))
        info = QtWidgets.QLabel("選択中のY系列を、現在のX軸列に対して解析します。"
                                "データタブでX軸とY系列を選んでから実行してください。")
        info.setWordWrap(True); info.setStyleSheet("color:#555;")
        v.addWidget(info)

        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("対象:"))
        self.ds_target = QtWidgets.QComboBox()
        self.ds_target.setToolTip("解析するY系列。データタブでY系列を選ぶと候補に出ます")
        row.addWidget(self.ds_target, 1)
        v.addLayout(row)

        # 回帰（線形性）
        b_reg = QtWidgets.QPushButton("線形回帰（Y vs X）")
        b_reg.setToolTip("傾き・切片・R²・相関r・直線性誤差[%FS] を計算（線形性の評価）")
        b_reg.clicked.connect(self.run_regression)
        self.ds_fit_check = QtWidgets.QCheckBox("回帰直線をグラフに重ねる")
        self.ds_fit_check.setToolTip("回帰実行時に近似曲線（線形）をグラフへ重ねて表示します")
        reg_row = QtWidgets.QHBoxLayout()
        reg_row.addWidget(b_reg); reg_row.addWidget(self.ds_fit_check); reg_row.addStretch(1)
        v.addLayout(reg_row)

        # 統計・正規性・相関行列
        brow = QtWidgets.QHBoxLayout()
        b_desc = QtWidgets.QPushButton("記述統計"); b_desc.clicked.connect(self.show_describe)
        b_desc.setToolTip("平均/中央値/標準偏差/分散/歪度/尖度/四分位 など")
        b_norm = QtWidgets.QPushButton("正規性検定"); b_norm.clicked.connect(self.run_normality)
        b_norm.setToolTip("Shapiro-Wilk 検定（scipy 必要）")
        b_corr = QtWidgets.QPushButton("相関行列（選択系列）"); b_corr.clicked.connect(self.show_corr_matrix)
        b_corr.setToolTip("選択中の全Y系列どうしのピアソン相関を行列で表示")
        brow.addWidget(b_desc); brow.addWidget(b_norm); brow.addWidget(b_corr)
        v.addLayout(brow)

        self.ds_title = self._bold("結果")
        v.addWidget(self.ds_title)
        hint = QtWidgets.QLabel("右端の「表示」にチェックした項目は、その値をグラフに注記表示します。")
        hint.setWordWrap(True); hint.setStyleSheet("color:#555;")
        v.addWidget(hint)
        self.ds_table = QtWidgets.QTableWidget(0, 3)
        self.ds_table.setHorizontalHeaderLabels(["項目", "値", "表示"])
        hh = self.ds_table.horizontalHeader()
        hh.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        self.ds_table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        v.addWidget(self.ds_table, 1)
        return outer

    def _build_plot_area(self):
        wrap = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(wrap); lay.setContentsMargins(0, 0, 0, 0)
        # グラフ上部の系列ON/OFFバー（折れ線/散布図の表示切替）
        self.series_bar = QtWidgets.QScrollArea()
        self.series_bar.setWidgetResizable(True)
        self.series_bar.setFixedHeight(34)
        self.series_bar.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self.series_bar.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.series_bar.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        bar_inner = QtWidgets.QWidget()
        self.series_bar_layout = QtWidgets.QHBoxLayout(bar_inner)
        self.series_bar_layout.setContentsMargins(6, 2, 6, 2)
        self.series_bar.setWidget(bar_inner)
        self.series_bar.setVisible(False)
        lay.addWidget(self.series_bar)

        self.fig = Figure(figsize=(6, 4.4), dpi=100)
        self.ax = self.fig.add_subplot(111)
        self.canvas = FigureCanvas(self.fig)
        self.toolbar = NavigationToolbar(self.canvas, wrap)
        lay.addWidget(self.toolbar)
        lay.addWidget(self.canvas, 1)
        self._plotted_artists = []   # [(label, artist), ...] 系列バー連携用
        self._style_artists = {}     # skey -> Line2D（単純な折れ線のみ：スタイル即時反映用）
        self._drawing = False        # draw_graph 再入防止フラグ
        # オシロ表示のドラッグ操作（パン/スケール）＋ホイール
        self._scope_drag = None
        self._scope_ov = None
        self.canvas.mpl_connect("button_press_event", self._scope_on_press)
        self.canvas.mpl_connect("motion_notify_event", self._scope_on_motion)
        self.canvas.mpl_connect("button_release_event", self._scope_on_release)
        self.canvas.mpl_connect("scroll_event", self._scope_on_scroll)
        self._draw_placeholder()
        return wrap

    def _rebuild_series_bar(self, chart_type=None):
        """グラフ上部の系列選択バーを作り直す（折れ線/散布図のみ）。

        利用可能な全Y系列をチェックボックスで表示し、ここでON/OFFすると左の
        Y軸選択と同期して描画される。左でチェックしなくても、データを読み込めば
        上のバーに系列が並ぶ（＝上のバーだけで系列を選べる）。"""
        chart_type = chart_type or self.chart_combo.currentText()
        lay = self.series_bar_layout
        while lay.count():
            it = lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        if chart_type not in ("折れ線", "散布図"):
            self.series_bar.setVisible(False)
            return
        items = [(self.y_list.item(i),) for i in range(self.y_list.count())]
        if not items:
            self.series_bar.setVisible(False)
            return
        self._series_bar_building = True
        for (it,) in items:
            fl, col = it.data(UserRole)
            st = self.series_styles.get(self._style_key(fl, col)) or {}
            checked = it.checkState() == QtCore.Qt.CheckState.Checked
            label = st.get("label") or it.text()
            color = st.get("color") or ("#333" if checked else "#888")
            cb = QtWidgets.QCheckBox(label)
            cb.setChecked(checked)
            cb.setToolTip("右クリック=この系列だけ表示／非表示／すべて表示")
            cb.setStyleSheet(f"QCheckBox {{ color:{color}; "
                             f"font-weight:{'bold' if checked else 'normal'}; }}")
            cb.toggled.connect(lambda on, item=it: self._toggle_series_select(item, on))
            cb.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
            cb.customContextMenuRequested.connect(
                lambda pos, item=it, wdg=cb: self._series_menu(item).exec(wdg.mapToGlobal(pos)))
            lay.addWidget(cb)
        lay.addStretch(1)
        self._series_bar_building = False
        self.series_bar.setVisible(True)

    def _toggle_series_select(self, item, on):
        """系列バーのチェックで左Yリストの選択を切り替える（→自動再描画）。"""
        if getattr(self, "_series_bar_building", False):
            return
        item.setCheckState(QtCore.Qt.CheckState.Checked if on
                           else QtCore.Qt.CheckState.Unchecked)

    def _build_preview(self):
        box = QtWidgets.QGroupBox("データ編集（選択中ファイル・先頭100行）")
        lay = QtWidgets.QVBoxLayout(box); lay.setContentsMargins(4, 4, 4, 4)
        self._preview_label = None
        self._preview_loading = False
        bar = QtWidgets.QHBoxLayout()
        self.edit_check = QtWidgets.QCheckBox("編集可")
        self.edit_check.setToolTip("セルをダブルクリックで編集。値はその場でDataFrameに反映され、グラフにも反映されます。")
        self.edit_check.toggled.connect(self._on_edit_toggle)
        bar.addWidget(self.edit_check)
        for text, slot, tip in [
                ("行追加", self._row_add, "末尾に空行を追加"),
                ("行削除", self._row_del, "選択した行を削除"),
                ("列追加", self._col_add, "新しい数値列を追加"),
                ("CSV保存", self._save_csv, "編集後のデータをCSV/TSVに書き出し")]:
            b = QtWidgets.QPushButton(text); b.setToolTip(tip)
            b.clicked.connect(slot); bar.addWidget(b)
        bar.addStretch(1)
        lay.addLayout(bar)
        self.table = QtWidgets.QTableWidget()
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.itemChanged.connect(self._on_cell_edited)
        lay.addWidget(self.table)
        return box

    def _build_statusbar(self):
        self.status = self.statusBar()
        fi = f"日本語: {self.font_name}" if self.font_name else "日本語フォント未検出"
        self.status.addPermanentWidget(QtWidgets.QLabel(fi))

    @staticmethod
    def _bold(text):
        l = QtWidgets.QLabel(text); f = l.font(); f.setBold(True); l.setFont(f); return l

    @staticmethod
    def _hline():
        ln = QtWidgets.QFrame()
        ln.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        ln.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
        return ln

    # ------------------------------------------------------------ ライブ更新
    def _wire_live_signals(self):
        """各コントロールの変更を（リアルタイム更新ON時に）自動再描画へつなぐ。"""
        r = self._request_redraw
        self.chart_combo.currentTextChanged.connect(r)
        for e in (self.title_edit, self.xlabel_edit, self.ylabel_edit,
                  self.xunit_edit, self.yunit_edit, self.xscale_edit, self.yscale_edit):
            e.textChanged.connect(r)
        for s in (self.fs_title, self.fs_label, self.fs_tick, self.fs_legend, self.fs_annot,
                  self.bins_spin, self.frame_width, self.grid_width):
            s.valueChanged.connect(r)
        for c in (self.grid_check, self.legend_check, self.pct_check,
                  self.xlog, self.ylog, self.show_filename_check, self.show_ext_check,
                  self.xinvert_check, self.yinvert_check):
            c.toggled.connect(r)
        self.legend_loc.currentTextChanged.connect(r)
        # 近似曲線・データラベル
        self.trend_combo.currentTextChanged.connect(r)
        for s in (self.trend_degree, self.trend_window):
            s.valueChanged.connect(r)
        for c in (self.trend_eq, self.data_labels_check):
            c.toggled.connect(r)
        # 縦横比（コンボは _on_aspect_changed 経由で再描画。W/H は直接）
        for s in (self.aspect_w, self.aspect_h):
            s.valueChanged.connect(r)
        for le in (self.xmin, self.xmax, self.ymin, self.ymax,
                   self.xtick_edit, self.ytick_edit):
            le.editingFinished.connect(r)
        # オシロのつまみ
        self.scope_check.toggled.connect(r)
        for cb in (self.tdiv, self.vdiv):
            cb.currentTextChanged.connect(r)
        for le in (self.xpos, self.ypos):
            le.editingFinished.connect(r)
        for s in (self.xdivs, self.ydivs):
            s.valueChanged.connect(r)
        self.show_peaks_check.toggled.connect(r)
        self.npeaks.valueChanged.connect(r)
        self.smooth_spin.valueChanged.connect(r)

    def _add_tooltips(self):
        tips = {
            self.legend_loc: "凡例の表示位置",
            self.xlog: "X軸を対数目盛に（0以下の値は表示できません）",
            self.ylog: "Y軸を対数目盛に（0以下の値は表示できません）",
            self.bins_spin: "ヒストグラムの区間数（ヒストグラム選択時のみ有効）",
            self.pct_check: "円グラフでパーセント表示（円グラフ選択時のみ有効）",
            self.xmin: "X軸の最小値。空欄で自動。指数表記(1e-3)も可",
            self.xmax: "X軸の最大値。空欄で自動",
            self.ymin: "Y軸の最小値。空欄で自動", self.ymax: "Y軸の最大値。空欄で自動",
            self.dpi_spin: "保存画像の解像度。印刷向けは300以上",
            self.transparent_check: "保存時に背景を透明にします（PNG/PDF/SVG）",
            self.analysis_target: "解析するY系列。データタブでY系列を選ぶと候補に出ます",
            self.npeaks: "検出するピークの個数（第1〜第N）",
            self.show_peaks_check: "検出ピークを折れ線/散布図に重ねて表示",
            self.scope_check: "オシロスコープ風のdiv表示（折れ線/散布図）",
            self.tdiv: "1目盛りあたりの時間。1e-3 のような指数表記も可",
            self.vdiv: "1目盛りあたりの値。1e-3 のような指数表記も可",
            self.xpos: "表示の中心時間", self.ypos: "表示の中心値",
        }
        for w, t in tips.items():
            w.setToolTip(t)

# ======================================================================
# ↑ graph_app_mixins/ui_build.py
# ======================================================================
"""DataIOMixin: GraphApp から分離した DataIOMixin 群（挙動は本体と同一）。"""


class DataIOMixin:
    # ------------------------------------------------------------ D&D
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = []
        for url in event.mimeData().urls():
            p = url.toLocalFile()
            if p and os.path.splitext(p)[1].lower() in (".csv", ".tsv", ".txt", ".xlsx", ".xlsm", ".xls"):
                paths.append(p)
        if not paths:
            return
        for p in paths:
            self._load_file(p)
        self.last_dir = os.path.dirname(paths[-1])
        self._refresh_columns()
        if self._has_drawn:
            self.draw_graph()

    # ------------------------------------------------------------ ファイル
    def add_file(self):
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self, "ファイルを追加（複数選択可）", self.last_dir,
            "データ (*.csv *.tsv *.txt *.xlsx *.xls *.xlsm);;Excel (*.xlsx *.xls *.xlsm);;"
            "CSV/TSV (*.csv *.tsv *.txt);;すべて (*.*)")
        for p in paths:
            self._load_file(p)
        if paths:
            self.last_dir = os.path.dirname(paths[-1])
            self._refresh_columns()

    def paste_from_clipboard(self):
        """クリップボードの表データ（Excel等からのコピー＝TSV/CSV）を新規データとして読み込む。"""
        import io
        import pandas as pd
        text = QtWidgets.QApplication.clipboard().text()
        if not text or not text.strip():
            QtWidgets.QMessageBox.information(self, "貼り付け", "クリップボードに表データがありません。")
            return
        first = text.splitlines()[0]
        sep = "\t" if first.count("\t") >= first.count(",") else ","   # Excelコピーはタブ区切り
        try:
            df = pd.read_csv(io.StringIO(text), sep=sep, engine="python", skip_blank_lines=True)
            df = _normalize_columns(df)
        except Exception as e:  # noqa: BLE001
            QtWidgets.QMessageBox.warning(self, "貼り付け", f"表として読み取れませんでした:\n{e}")
            return
        if df.shape[1] == 0 or len(df) == 0:
            QtWidgets.QMessageBox.warning(self, "貼り付け", "表として読み取れませんでした。")
            return
        label, i = "貼り付け", 2
        while label in self.datasets:
            label = f"貼り付け ({i})"; i += 1
        self.datasets[label] = df
        self.meta[label] = {"path": "(clipboard)", "enc": "clipboard", "delim": sep}
        self._add_file_item(label)
        self.file_list.setCurrentRow(self.file_list.count() - 1)
        self._refresh_columns()
        self._set_status(f"クリップボードから {len(df)}行 × {len(df.columns)}列 を貼り付けました。")

    def _load_file(self, path):
        enc = self.enc_combo.currentText()
        enc = None if enc.startswith("自動") else enc
        delim = None
        dt = self.delim_combo.currentText()
        if not dt.startswith("自動"):
            for ch, lbl in DELIMITER_LABELS.items():
                if lbl == dt:
                    delim = ch
                    break
        size = os.path.getsize(path) if os.path.isfile(path) else 0
        busy = size > 5_000_000   # 5MB 超は待機カーソル＋進捗
        if busy:
            QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
            self._set_status(f"読み込み中… {os.path.basename(path)}")
            QtWidgets.QApplication.processEvents()
        try:
            df, used_enc, used_delim = load_table(path, encoding=enc, delimiter=delim)
        except Exception as e:  # noqa: BLE001
            QtWidgets.QMessageBox.critical(self, "読み込みエラー", f"{os.path.basename(path)}\n\n{e}")
            return
        finally:
            if busy:
                QtWidgets.QApplication.restoreOverrideCursor()
        label = os.path.basename(path)
        base, i = label, 2
        while label in self.datasets and self.meta.get(label, {}).get("path") != path:
            label = f"{base} ({i})"; i += 1
        self.datasets[label] = df
        self.meta[label] = {"path": path, "enc": used_enc, "delim": used_delim}
        if not self._find_file_item(label):
            self._add_file_item(label)
        self._push_recent(path)
        self._set_status(f"{label} を読み込み（{len(df)}行 × {len(df.columns)}列, {used_enc}）")

    def _find_file_item(self, label):
        for i in range(self.file_list.count()):
            if self.file_list.item(i).text() == label:
                return self.file_list.item(i)
        return None

    def _add_file_item(self, label):
        """ファイル一覧へ項目を追加（ホバーで全名を出すツールチップ付き）。"""
        it = QtWidgets.QListWidgetItem(label)
        it.setToolTip(label)
        self.file_list.addItem(it)

    def _push_recent(self, path):
        if path in self.recent_files:
            self.recent_files.remove(path)
        self.recent_files.insert(0, path)
        del self.recent_files[12:]
        self._rebuild_recent_menu()

    def _rebuild_recent_menu(self):
        self.recent_menu.clear()
        if not self.recent_files:
            act = self.recent_menu.addAction("（履歴なし）"); act.setEnabled(False)
            return
        for p in self.recent_files:
            self.recent_menu.addAction(os.path.basename(p),
                                       lambda checked=False, q=p: self._open_recent(q))

    def _open_recent(self, path):
        if not os.path.isfile(path):
            QtWidgets.QMessageBox.information(self, "情報", f"ファイルが見つかりません:\n{path}")
            self.recent_files = [q for q in self.recent_files if q != path]
            self._rebuild_recent_menu()
            return
        self._load_file(path)
        self._refresh_columns()
        if self._has_drawn:
            self.draw_graph()

    def remove_file(self):
        """選択中のファイルを削除（複数選択していればまとめて削除）。"""
        items = self.file_list.selectedItems()
        if not items and self.file_list.currentItem():
            items = [self.file_list.currentItem()]
        labels = [it.text() for it in items]
        if not labels:
            QtWidgets.QMessageBox.information(self, "情報", "削除するファイルを選択してください。")
            return
        if len(labels) > 1:
            ret = QtWidgets.QMessageBox.question(
                self, "一括削除", f"{len(labels)} 個のファイルを一覧から削除しますか？")
            if ret != QtWidgets.QMessageBox.StandardButton.Yes:
                return
        self._remove_labels(labels)
        self._set_status(f"{len(labels)} 個のファイルを削除しました。")

    def clear_all_files(self):
        """読み込み済みファイルをすべて削除する。"""
        if not self.datasets:
            QtWidgets.QMessageBox.information(self, "情報", "読み込み済みファイルがありません。")
            return
        ret = QtWidgets.QMessageBox.question(
            self, "全削除", f"読み込み済みの {len(self.datasets)} 個すべてを一覧から削除しますか？")
        if ret != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        n = len(self.datasets)
        self._remove_labels(list(self.datasets.keys()))
        self._set_status(f"すべて（{n} 個）のファイルを削除しました。")

    def _remove_labels(self, labels):
        """指定ラベルのファイルをデータ・一覧・スタイルから取り除き、表示を更新する。"""
        labelset = set(labels)
        # ズーム再サンプル用に保持していた全解像度データの参照を解放（メモリリーク防止）
        self._clear_dynamic_resample()
        for label in labels:
            self.datasets.pop(label, None)
            self.meta.pop(label, None)
        # 該当ファイルの系列スタイルも掃除（"file\tcol" キー）
        for key in [k for k in self.series_styles if k.split("\t", 1)[0] in labelset]:
            self.series_styles.pop(key, None)
        # 削除したデータに紐づく解析注記・解析表をクリア（古い注記が次の描画に残らないように）
        self._meas_annotations = []
        self._ds_annotations = []
        if hasattr(self, "meas_table"):
            self.meas_table.setRowCount(0)
        if hasattr(self, "ds_table"):
            self.ds_table.setRowCount(0)
        self.file_list.blockSignals(True)
        for i in range(self.file_list.count() - 1, -1, -1):
            if self.file_list.item(i).text() in labelset:
                self.file_list.takeItem(i)
        self.file_list.blockSignals(False)
        self._refresh_columns()
        if self.datasets:
            self.file_list.setCurrentRow(0)   # プレビューを残りの先頭へ
        else:
            self._preview_label = None
            self.table.clearContents()
            self.table.setRowCount(0)
            self.table.setColumnCount(0)
            self._draw_placeholder()

    def reload_current(self):
        it = self.file_list.currentItem()
        if not it:
            QtWidgets.QMessageBox.information(self, "情報", "ファイルを選択してください。")
            return
        path = self.meta[it.text()]["path"]
        self.datasets.pop(it.text(), None)
        self.meta.pop(it.text(), None)
        self.file_list.takeItem(self.file_list.row(it))
        self._load_file(path)
        self._refresh_columns()

    def _on_file_selected(self, _row):
        it = self.file_list.currentItem()
        if it and it.text() in self.datasets:
            self._populate_preview(self.datasets[it.text()], label=it.text())
            meta = self.meta[it.text()]
            self.enc_combo.setCurrentText(meta["enc"]) if self.enc_combo.findText(meta["enc"]) >= 0 else None

    def _refresh_columns(self):
        # X軸候補（全ファイルの列名の和集合、出現順）
        seen, xcols = set(), []
        for df in self.datasets.values():
            for c in df.columns:
                if c not in seen:
                    seen.add(c); xcols.append(c)
        cur_x = self.x_combo.currentText()
        self.x_combo.blockSignals(True)
        self.x_combo.clear(); self.x_combo.addItems(xcols)
        if cur_x in xcols:
            self.x_combo.setCurrentText(cur_x)
        self.x_combo.blockSignals(False)

        # Y軸候補（ファイル｜列）。選択状態は表示名ではなく安定した
        # (ファイル, 列) 識別子で保持する（ファイル数で表示名が変わっても消えない）。
        checked = QtCore.Qt.CheckState.Checked
        unchecked = QtCore.Qt.CheckState.Unchecked
        prev = {self.y_list.item(i).data(UserRole)
                for i in range(self.y_list.count())
                if self.y_list.item(i).checkState() == checked}
        self.y_list.blockSignals(True)   # 構築中のチェック変更で何度も再描画しない
        self.y_list.clear()
        multi = len(self.datasets) > 1
        use_left = self._use_leftmost_x()
        for label, df in self.datasets.items():
            for ci, c in enumerate(df.columns):
                if use_left and ci == 0:   # 先頭列はX軸なのでY軸候補から除外
                    continue
                disp = f"{label} | {c}" if multi else c
                item = QtWidgets.QListWidgetItem(disp)
                item.setData(UserRole, (label, c))
                item.setFlags(QtCore.Qt.ItemFlag.ItemIsUserCheckable
                              | QtCore.Qt.ItemFlag.ItemIsEnabled)
                item.setCheckState(checked if (label, c) in prev else unchecked)
                self.y_list.addItem(item)
        self.y_list.blockSignals(False)
        self._on_y_selection_changed()   # スタイル表・解析候補をまとめて更新

    def _selected_series_items(self):
        """チェック済みの (file_label, column, display_label) のリスト（並び順保持）。"""
        out = []
        for i in range(self.y_list.count()):
            it = self.y_list.item(i)
            if it.checkState() == QtCore.Qt.CheckState.Checked:
                fl, col = it.data(UserRole)
                out.append((fl, col, it.text()))
        return out

    def _populate_preview(self, df, label=None):
        import pandas as pd
        self._preview_loading = True   # 構築中の itemChanged を書き戻さない
        try:
            head = df.head(PREVIEW_ROWS)
            cols = list(df.columns)
            self.table.clear()
            self.table.setColumnCount(len(cols))
            self.table.setRowCount(len(head))
            self.table.setHorizontalHeaderLabels([str(c) for c in cols])
            for r in range(len(head)):
                for c in range(len(cols)):
                    v = head.iat[r, c]
                    self.table.setItem(r, c, QtWidgets.QTableWidgetItem("" if pd.isna(v) else str(v)))
            self.table.resizeColumnsToContents()
            if label is not None:
                self._preview_label = label
        finally:
            self._preview_loading = False

    # ------------------------------------------------------------ データ編集
    def _on_edit_toggle(self, on):
        ET = QtWidgets.QAbstractItemView.EditTrigger
        self.table.setEditTriggers(
            (ET.DoubleClicked | ET.EditKeyPressed | ET.AnyKeyPressed)
            if on else ET.NoEditTriggers)

    def _on_cell_edited(self, item):
        if self._preview_loading or not getattr(self, "_preview_label", None):
            return
        import pandas as pd
        df = self.datasets.get(self._preview_label)
        if df is None:
            return
        r, c = item.row(), item.column()
        if r >= len(df) or c >= df.shape[1]:
            return
        col = df.columns[c]
        text = item.text()
        if pd.api.types.is_numeric_dtype(df[col]):
            val = pd.to_numeric(text, errors="coerce")   # 数値列は数値化（不可ならNaN）
        else:
            val = text
        df.iat[r, c] = val
        self._set_status(f"編集: {self._preview_label} 行{r}「{col}」= {text}")
        self._request_redraw()

    def _edit_target(self):
        lbl = getattr(self, "_preview_label", None)
        if not lbl or lbl not in self.datasets:
            QtWidgets.QMessageBox.information(self, "情報", "左の一覧でファイルを選択してください。")
            return None
        return lbl

    def _row_add(self):
        import numpy as np
        lbl = self._edit_target()
        if not lbl:
            return
        df = self.datasets[lbl]
        df.loc[len(df)] = [np.nan] * df.shape[1]
        df.reset_index(drop=True, inplace=True)
        self._populate_preview(df, label=lbl)
        if len(df) > PREVIEW_ROWS:
            self._set_status(f"行を追加（全{len(df)}行。表示は先頭{PREVIEW_ROWS}行）")
        self._request_redraw()

    def _row_del(self):
        lbl = self._edit_target()
        if not lbl:
            return
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        if not rows:
            self._set_status("削除する行を選択してください。")
            return
        df = self.datasets[lbl]
        df.drop(df.index[rows], inplace=True)
        df.reset_index(drop=True, inplace=True)
        self._populate_preview(df, label=lbl)
        self._request_redraw()

    def _col_add(self):
        lbl = self._edit_target()
        if not lbl:
            return
        name, ok = QtWidgets.QInputDialog.getText(self, "列追加", "新しい列名:")
        name = (name or "").strip()
        if not ok or not name:
            return
        df = self.datasets[lbl]
        if name in df.columns:
            QtWidgets.QMessageBox.warning(self, "列追加", "同名の列が既にあります。")
            return
        df[name] = 0.0
        self._populate_preview(df, label=lbl)
        self._refresh_columns()      # X/Y軸の候補へ反映
        self._set_status(f"列「{name}」を追加（値0.0で初期化）")

    def _save_csv(self):
        lbl = self._edit_target()
        if not lbl:
            return
        default = lbl if lbl.lower().endswith((".csv", ".tsv")) else lbl + ".csv"
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "CSV/TSVとして保存", default,
            "CSV (*.csv);;TSV (*.tsv);;全てのファイル (*.*)")
        if not path:
            return
        try:
            sep = "\t" if path.lower().endswith(".tsv") else ","
            self.datasets[lbl].to_csv(path, index=False, sep=sep, encoding="utf-8-sig")
            self._set_status(f"保存しました: {path}（全{len(self.datasets[lbl])}行）")
        except Exception as e:  # noqa: BLE001
            QtWidgets.QMessageBox.critical(self, "保存エラー", str(e))

# ======================================================================
# ↑ graph_app_mixins/data_io.py
# ======================================================================
"""StyleTableMixin: GraphApp から分離した StyleTableMixin 群（挙動は本体と同一）。"""


class StyleTableMixin:
    def _on_x_changed(self, *_):
        self._request_redraw()

    def _on_xleft_toggled(self, on):
        """『一番左の列をX軸』ON時は名前コンボを無効化し、先頭列をY候補から除外/復帰。"""
        self._refresh_columns()        # Y軸候補を作り直し（先頭列の除外/復帰）＋再描画予約
        self._update_x_combo_enabled()  # 有効/無効は最後に確定

    def _update_x_combo_enabled(self):
        """X名コンボの有効状態を、グラフ種別と『一番左の列をX軸』から決める。"""
        info = CHART_INFO.get(self.chart_combo.currentText(), {})
        self.x_combo.setEnabled(info.get("use_x", True) and not self._use_leftmost_x())

    def _use_leftmost_x(self):
        return bool(getattr(self, "xleft_check", None) and self.xleft_check.isChecked())

    def _x_values(self, df):
        """X軸データ列。『一番左の列』ONなら位置0、OFFなら選択名（無ければ先頭列）。"""
        if self._use_leftmost_x():
            return df.iloc[:, 0].to_numpy()
        xname = self.x_combo.currentText()
        return df[xname].to_numpy() if xname in df.columns else df.iloc[:, 0].to_numpy()

    def _effective_x_label(self):
        """既定のX軸ラベル（『一番左の列』ONなら先頭列名、OFFなら選択名）。"""
        if self._use_leftmost_x():
            items = self._selected_series_items()
            if items:
                df = self.datasets.get(items[0][0])
                if df is not None and len(df.columns):
                    return str(df.columns[0])
            return ""
        return self.x_combo.currentText()

    @staticmethod
    def _auto_y_label(names, ctype):
        """系列名からY軸の既定ラベルを作る。1つならその名前、複数は ' / ' で結合
        （長すぎる場合は先頭＋ほかN系列）。ヒストグラムはY軸が頻度なので空。"""
        if ctype == "ヒストグラム":
            return ""
        uniq = list(dict.fromkeys(n for n in names if n))
        if not uniq:
            return ""
        if len(uniq) == 1:
            return uniq[0]
        joined = " / ".join(uniq)
        return joined if len(joined) <= 40 else f"{uniq[0]} ほか{len(uniq) - 1}系列"

    def _file_display_name(self, fl):
        """ファイル名（『拡張子』トグルがオフなら拡張子を除く）。"""
        if hasattr(self, "show_ext_check") and not self.show_ext_check.isChecked():
            return os.path.splitext(fl)[0]
        return fl

    def _series_label(self, fl, col):
        """凡例に使う系列ラベル。ユーザー上書き＞ファイル名表示オプション。
        単一ファイル、または『凡例にファイル名』オフのときは列名のみ。"""
        st = self.series_styles.get(self._style_key(fl, col)) or {}
        if st.get("label"):
            return st["label"]
        multi = len(self.datasets) > 1
        show_fn = (not hasattr(self, "show_filename_check")) or self.show_filename_check.isChecked()
        if multi and show_fn:
            return f"{self._file_display_name(fl)} | {col}"
        return col

    def _effective_y_label(self):
        """既定のY軸ラベル（Y軸名欄が空のとき使用）。主軸の選択系列の『列名』から作る。
        軸名はファイル名を含めず列名ベースにし、全系列が同じ列名ならその1つだけにする
        （第2軸の系列は右側ラベルになるので除外）。"""
        names = []
        for fl, col, disp in self._selected_series_items():
            st = self.series_styles.get(self._style_key(fl, col)) or {}
            if st.get("axis", "primary") == "secondary":
                continue
            names.append(st.get("label") or col)
        return self._auto_y_label(names, self.chart_combo.currentText())

    def _on_y_check_changed(self, _item):
        if self._suspend_redraw:
            return
        self._on_y_selection_changed()

    def _set_all_checks(self, func):
        """func(item) -> bool で各行のチェック状態を一括設定し、まとめて更新。"""
        ck = QtCore.Qt.CheckState.Checked
        un = QtCore.Qt.CheckState.Unchecked
        self.y_list.blockSignals(True)
        for i in range(self.y_list.count()):
            it = self.y_list.item(i)
            it.setCheckState(ck if func(it) else un)
        self.y_list.blockSignals(False)
        self._on_y_selection_changed()

    def _check_all_y(self, checked):
        self._set_all_checks(lambda it: checked)

    def _invert_y(self):
        ck = QtCore.Qt.CheckState.Checked
        self._set_all_checks(lambda it: it.checkState() != ck)

    def _on_y_double_clicked(self, item):
        """Y行をダブルクリック → その系列だけにして描画。"""
        self._set_all_checks(lambda it: it is item)
        self.draw_graph()

    def _maybe_draw(self):
        if self.datasets:
            self.draw_graph()

    def _series_menu(self, item):
        """系列の表示/非表示メニュー（Yリスト・上部系列バー共通）。"""
        menu = QtWidgets.QMenu(self)
        if item is not None:
            menu.addAction("この系列だけ表示", lambda: self._solo_series(item))
            menu.addAction("この系列を非表示", lambda: self._hide_series(item))
            menu.addSeparator()
        menu.addAction("すべて表示", lambda: (self._check_all_y(True), self._maybe_draw()))
        menu.addAction("すべて非表示", lambda: (self._check_all_y(False), self._maybe_draw()))
        return menu

    def _y_list_menu(self, pos):
        """Yリスト右クリックの表示メニュー。"""
        item = self.y_list.itemAt(pos)
        self._series_menu(item).exec(self.y_list.viewport().mapToGlobal(pos))

    def _solo_series(self, item):
        """指定系列だけ表示（他をすべて非表示）。"""
        self._set_all_checks(lambda it: it is item)
        self._maybe_draw()

    def _hide_series(self, item):
        """指定系列を非表示にする（他はそのまま）。"""
        item.setCheckState(QtCore.Qt.CheckState.Unchecked)
        self._maybe_draw()

    def _on_style_label_edited(self, item):
        """系列名（凡例ラベル）の編集を保存して再描画。"""
        if self._suspend_redraw or item.column() != 0:
            return
        key = item.data(UserRole)
        if not key:
            return
        text = item.text().strip()
        st = self.series_styles.setdefault(key, dict(DEFAULT_STYLE))
        st["label"] = text or None
        self._request_redraw()

    # ------------------------------------------------------------ 系列スタイル
    def _on_y_selection_changed(self):
        self._rebuild_style_table()
        self._rebuild_series_bar()        # 上部の系列選択バーも同期
        self._update_analysis_targets()
        self._request_redraw()

    def _update_analysis_targets(self):
        names = [d for _, _, d in self._selected_series_items()]
        combos = [self.analysis_target]
        # 高度解析・データサイエンスタブの系列コンボも更新（構築済みなら）
        for attr in ("phase_target2", "math_a", "math_b", "ds_target"):
            if hasattr(self, attr):
                combos.append(getattr(self, attr))
        if hasattr(self, "proto_ch"):
            combos.extend(self.proto_ch)
        for cb in combos:
            cur = cb.currentText()
            cb.blockSignals(True)
            cb.clear()
            cb.addItems(names)
            idx = cb.findText(cur)
            if idx >= 0:
                cb.setCurrentIndex(idx)
            cb.blockSignals(False)

    @staticmethod
    def _style_key(fl, col):
        # スタイルを安定キー（ファイル, 列）で保持。表示名の変化に影響されない。
        return f"{fl}\t{col}"

    def _rebuild_style_table(self):
        # 差分更新: 先頭から一致する行は触らず、最初に異なる行以降だけ作り直す
        # （多系列で1系列だけ増減したとき、全行の再生成を避けて高速化）。
        items = self._selected_series_items()
        new_keys = [self._style_key(fl, col) for fl, col, _ in items]
        old_keys = [
            (self.style_table.item(r, 0).data(UserRole)
             if self.style_table.item(r, 0) else None)
            for r in range(self.style_table.rowCount())]
        if new_keys == old_keys:
            return                       # 変化なし: 何もしない
        i = 0
        m = min(len(new_keys), len(old_keys))
        while i < m and new_keys[i] == old_keys[i]:
            i += 1
        prev_suspend = self._suspend_redraw
        self._suspend_redraw = True      # 構築中の signal で再描画/上書きしない
        vbar = self.style_table.verticalScrollBar().value()
        self.style_table.setUpdatesEnabled(False)
        self.style_table.setRowCount(len(items))   # 末尾の増減を反映
        for r in range(i, len(items)):
            fl, col, disp = items[r]
            self._build_style_row(r, fl, col, disp)
        self.style_table.setUpdatesEnabled(True)
        self.style_table.verticalScrollBar().setValue(vbar)
        self._suspend_redraw = prev_suspend

    def _build_style_row(self, r, fl, col, disp):
        """スタイル表の1行（系列名/色/線種/幅/マーカー/軸/種別/誤差列）を作る。"""
        key = self._style_key(fl, col)
        st = self.series_styles.setdefault(key, dict(DEFAULT_STYLE))
        # 系列名（編集で凡例ラベルを上書き）。キーを UserRole に保持。
        name_item = QtWidgets.QTableWidgetItem(st.get("label") or disp)
        name_item.setData(UserRole, key)
        name_item.setFlags(name_item.flags() | QtCore.Qt.ItemFlag.ItemIsEditable)
        self.style_table.setItem(r, 0, name_item)
        # 色ボタン
        btn = QtWidgets.QPushButton(st.get("color") or "自動")
        if st.get("color"):
            btn.setStyleSheet(f"background:{st['color']};")
        btn.clicked.connect(lambda _=False, k=key, b=btn: self._pick_color(k, b))
        self.style_table.setCellWidget(r, 1, btn)
        # 線種
        cb = QtWidgets.QComboBox(); cb.addItems(list(LINESTYLES.keys()))
        cur_ls = next((k2 for k2, vv in LINESTYLES.items() if vv == st["linestyle"]), "実線")
        cb.setCurrentText(cur_ls)
        cb.currentTextChanged.connect(lambda v, k=key: self._set_style(k, "linestyle", LINESTYLES[v]))
        self.style_table.setCellWidget(r, 2, cb)
        # 幅
        sp = QtWidgets.QDoubleSpinBox(); sp.setRange(0.2, 10); sp.setSingleStep(0.5); sp.setValue(st["linewidth"])
        sp.valueChanged.connect(lambda v, k=key: self._set_style(k, "linewidth", v))
        self.style_table.setCellWidget(r, 3, sp)
        # マーカー
        mb = QtWidgets.QComboBox(); mb.addItems(list(MARKERS.keys()))
        cur_mk = next((k2 for k2, vv in MARKERS.items() if vv == st["marker"]), "なし")
        mb.setCurrentText(cur_mk)
        mb.currentTextChanged.connect(lambda v, k=key: self._set_style(k, "marker", MARKERS[v]))
        self.style_table.setCellWidget(r, 4, mb)
        # マーカーサイズ
        msp = QtWidgets.QDoubleSpinBox(); msp.setRange(1, 50); msp.setSingleStep(1); msp.setDecimals(1)
        msp.setValue(st.get("markersize", 4.0))
        msp.setToolTip("マーカーの大きさ（マーカーを「なし」以外にすると反映）")
        msp.valueChanged.connect(lambda v, k=key: self._set_style(k, "markersize", v))
        self.style_table.setCellWidget(r, 5, msp)
        # 軸（主/第2）── 折れ線/散布図で有効
        axb = QtWidgets.QComboBox(); axb.addItems(list(SERIES_AXES.keys()))
        axb.setCurrentText(next((k2 for k2, vv in SERIES_AXES.items()
                                 if vv == st.get("axis", "primary")), "主軸"))
        axb.currentTextChanged.connect(
            lambda v, k=key: self._set_style(k, "axis", SERIES_AXES[v]))
        self.style_table.setCellWidget(r, 6, axb)
        # 種別（複合グラフ：自動/線/棒/面/散布）
        kb = QtWidgets.QComboBox(); kb.addItems(list(SERIES_KINDS.keys()))
        kb.setCurrentText(next((k2 for k2, vv in SERIES_KINDS.items()
                                if vv == st.get("kind", "")), "自動"))
        kb.currentTextChanged.connect(
            lambda v, k=key: self._set_style(k, "kind", SERIES_KINDS[v]))
        self.style_table.setCellWidget(r, 7, kb)
        # 誤差列（エラーバー）── 同ファイルの列から選択。列一覧は開いた時に遅延展開
        cur_e = st.get("errcol")
        eb = LazyColumnCombo(
            (lambda fl=fl: list(self.datasets[fl].columns) if fl in self.datasets else []),
            cur_e if cur_e is not None else None)
        eb.currentTextChanged.connect(
            lambda v, k=key: self._set_style(k, "errcol", None if v == "なし" else v))
        self.style_table.setCellWidget(r, 8, eb)

    def _pick_color(self, skey, btn):
        col = QtWidgets.QColorDialog.getColor(parent=self)
        if col.isValid():
            hexc = col.name()
            self._set_style(skey, "color", hexc)
            btn.setText(hexc); btn.setStyleSheet(f"background:{hexc};")

    def _pick_bg_color(self):
        """プロット領域の背景色を選ぶ（オシロ表示の濃色固定も上書きできる）。"""
        col = QtWidgets.QColorDialog.getColor(parent=self)
        if col.isValid():
            self.bg_color = col.name()
            self.bg_btn.setText("背景色: " + self.bg_color)
            self.bg_btn.setStyleSheet(f"background:{self.bg_color};")
            self._request_redraw()

    def _reset_bg_color(self):
        """背景色を自動（通常=白・オシロ=濃色）に戻す。"""
        self.bg_color = ""
        self.bg_btn.setText("背景色: 自動")
        self.bg_btn.setStyleSheet("")
        self._request_redraw()

    def _pick_trend_color(self):
        """近似曲線の色を選ぶ（空=自動: 各系列と同じ色）。"""
        col = QtWidgets.QColorDialog.getColor(parent=self)
        if col.isValid():
            self.trend_color = col.name()
            self.trend_color_btn.setText("色: " + self.trend_color)
            self.trend_color_btn.setStyleSheet(f"background:{self.trend_color};")
            self._request_redraw()

    def _reset_trend_color(self):
        """近似曲線の色を自動（系列と同じ色）に戻す。"""
        self.trend_color = ""
        self.trend_color_btn.setText("色: 自動")
        self.trend_color_btn.setStyleSheet("")
        self._request_redraw()

    # 純視覚スタイル（全再描画せず該当アーティストへ直接反映できるもの）
    _STYLE_VISUAL = frozenset({"color", "linewidth", "linestyle", "marker", "markersize"})

    def _set_style(self, skey, attr, value):
        self.series_styles.setdefault(skey, dict(DEFAULT_STYLE))[attr] = value
        # スタイルのみの変更は、可能なら全再描画せずアーティストを直接更新（高速・ちらつき無し）。
        # 少しでも不確実なら従来どおりデバウンス全再描画にフォールバックする。
        if not self._try_style_fastpath(skey, attr, value):
            self._request_redraw()

    def _build_style_artist_map(self, series, ctype, decimated):
        """skey -> Line2D。スタイルのみ変更を即時反映できる『単純な折れ線』だけを対象にする。
        散布図/誤差バー/棒・面/間引き/混在があれば空dictを返し、全再描画にフォールバックさせる。"""
        m = {}
        if ctype != "折れ線" or decimated:
            return m
        items = self._selected_series_items()
        if len(items) != len(series):
            return m
        for sr in series:                       # 1つでも非・単純線があれば諦める（安全側）
            if (sr.get("kind") or "") not in ("", "line") or sr.get("yerr") is not None:
                return m
        from matplotlib.lines import Line2D

        def _data_lines(axx):
            # データ系列の線だけを順序どおり抽出。近似曲線（'近似'）やピークマーカー等の
            # 自動ラベル線（'_child'…＝ラベル未指定）は除外する。
            return [ln for ln in axx.get_lines()
                    if isinstance(ln, Line2D)
                    and not str(ln.get_label()).startswith("_")
                    and "近似" not in str(ln.get_label())]
        ax = self.ax
        ax2 = getattr(ax, "_twin_secondary", None)
        prim = _data_lines(ax)
        sec = _data_lines(ax2) if ax2 is not None else []
        prim_items = [it for it, sr in zip(items, series) if sr.get("axis") != "secondary"]
        sec_items = [it for it, sr in zip(items, series) if sr.get("axis") == "secondary"]
        if len(prim_items) != len(prim) or len(sec_items) != len(sec):
            return m                            # 本数が一致しない＝対応が取れない → 諦める
        for (fl, col, _disp), ln in zip(prim_items, prim):
            m[self._style_key(fl, col)] = ln
        for (fl, col, _disp), ln in zip(sec_items, sec):
            m[self._style_key(fl, col)] = ln
        return m

    def _try_style_fastpath(self, skey, attr, value):
        """純視覚スタイルの変更を全再描画せず該当Line2Dへ反映できればして True。
        少しでも不確実なら False を返し、呼び出し側が通常の全再描画を行う。"""
        if attr not in self._STYLE_VISUAL:
            return False
        if self._suspend_redraw or not self._has_drawn:
            return False
        if not getattr(self, "live_check", None) or not self.live_check.isChecked():
            return False
        if self._redraw_timer.isActive():
            return False                        # 全再描画が予約済み → そちらに任せる
        if self.chart_combo.currentText() != "折れ線":
            return False
        if attr == "color" and not value:
            return False                        # 色を自動へ戻す等は全再描画に任せる
        ln = self._style_artists.get(skey)
        if ln is None or ln.axes is None:       # 対応Line2Dが無い/外れている → 全再描画
            return False
        try:
            if attr == "color":
                ln.set_color(value)
            elif attr == "linewidth":
                ln.set_linewidth(float(value))
            elif attr == "linestyle":
                ln.set_linestyle(value)
            elif attr == "marker":
                ln.set_marker(value or "")
            elif attr == "markersize":
                ln.set_markersize(float(value))
        except Exception:                       # noqa: BLE001  予期せぬ値 → 全再描画
            return False
        if attr == "color":
            if self.legend_check.isChecked():
                self._rebuild_legend_inplace()  # 凡例スウォッチの色を更新
            self._rebuild_series_bar(self.chart_combo.currentText())  # 上部バーの色も更新
        self.canvas.draw_idle()
        return True

    def _rebuild_legend_inplace(self):
        """色変更後、凡例を plot_series と同じ loc/フォントで作り直してスウォッチを更新。"""
        ax = self.ax
        handles, labels = ax.get_legend_handles_labels()
        ax2 = getattr(ax, "_twin_secondary", None)
        if ax2 is not None:
            h2, l2 = ax2.get_legend_handles_labels()
            handles = handles + h2; labels = labels + l2
        if handles:
            f = self._fonts()
            ax.legend(handles, labels, loc=self.legend_loc.currentText(),
                      fontsize=(f.get("legend") or f.get("tick", 9)))

# ======================================================================
# ↑ graph_app_mixins/style_table.py
# ======================================================================
"""PlotMixin: GraphApp から分離した PlotMixin 群（挙動は本体と同一）。"""


class PlotMixin:
    def _request_redraw(self, *args):
        """リアルタイム更新ON・描画済みのときだけ、デバウンスして再描画予約。"""
        if self._suspend_redraw or not self._has_drawn:
            return
        if not getattr(self, "live_check", None) or not self.live_check.isChecked():
            return
        self._redraw_timer.start(180)

    def _do_live_redraw(self):
        if self.datasets and self._has_drawn:
            self.draw_graph()

    # ------------------------------------------------------------ 描画
    def _on_chart_type_change(self, *_):
        ctype = self.chart_combo.currentText()
        info = CHART_INFO.get(ctype, {})
        self.hint_label.setText("➤ " + info.get("hint", ""))
        self._update_x_combo_enabled()
        self.bins_spin.setEnabled(ctype == "ヒストグラム")
        self.bins_caption.setEnabled(ctype == "ヒストグラム")
        self.pct_check.setEnabled(ctype == "円")
        if hasattr(self, "series_bar"):
            self._rebuild_series_bar(ctype)   # 折れ線/散布図でのみ上部バーを出す

    def _build_series(self, chart_type):
        info = CHART_INFO[chart_type]
        items = self._selected_series_items()
        if not items:
            raise ValueError("Y軸（値）の系列を選択してください。")
        xname = self.x_combo.currentText()
        categories = None
        series = []

        def lbl(fl, col, disp, default):
            st = self.series_styles.get(self._style_key(fl, col)) or {}
            return st.get("label") or default

        if chart_type in ("棒", "横棒", "積み上げ棒", "円"):
            # 単一ファイル（最初に選んだ系列のファイル）を使う
            src = items[0][0]
            df = self.datasets[src]
            if not self._use_leftmost_x() and xname not in df.columns:
                raise ValueError(f"X軸の列『{xname}』が『{src}』にありません。")
            categories = self._x_values(df)
            for fl, col, disp in items:
                if fl != src:
                    continue
                series.append({"label": lbl(fl, col, disp, col), "y": self.datasets[fl][col].to_numpy(),
                               "style": self.series_styles.get(self._style_key(fl, col))})
        elif chart_type in ("折れ線", "散布図"):
            for fl, col, disp in items:
                df = self.datasets[fl]
                xv = self._x_values(df)
                stmap = self.series_styles.get(self._style_key(fl, col)) or {}
                errcol = stmap.get("errcol")
                yerr = df[errcol].to_numpy() if (errcol and errcol in df.columns) else None
                series.append({"label": self._series_label(fl, col), "x": xv, "y": df[col].to_numpy(),
                               "style": stmap,
                               "axis": stmap.get("axis", "primary"),
                               "kind": stmap.get("kind", ""),
                               "yerr": yerr})
        else:  # ヒストグラム / 箱ひげ
            for fl, col, disp in items:
                series.append({"label": self._series_label(fl, col), "y": self.datasets[fl][col].to_numpy(),
                               "style": self.series_styles.get(self._style_key(fl, col))})
        return series, categories

    def _scope_dict(self):
        return {
            "enabled": self.scope_check.isChecked(),
            "t_per_div": parse_eng(self.tdiv.currentText(), 1e-3),
            "v_per_div": parse_eng(self.vdiv.currentText(), 1.0),
            "x_pos": _parse_float(self.xpos.text(), 0.0),
            "y_pos": _parse_float(self.ypos.text(), 0.0),
            "x_divs": self.xdivs.value(),
            "y_divs": self.ydivs.value(),
        }

    def _fonts(self):
        return {"title": self.fs_title.value(), "label": self.fs_label.value(),
                "tick": self.fs_tick.value(),
                "legend": self.fs_legend.value(),
                "annot": self.fs_annot.value()}

    def _on_aspect_changed(self, *_):
        custom = self.aspect_combo.currentText() == "カスタム"
        self.aspect_w.setEnabled(custom)
        self.aspect_h.setEnabled(custom)
        self._request_redraw()

    def _aspect_ratio(self):
        """選択中の縦横比から box aspect（高さ/幅）を返す。自動は None。"""
        t = self.aspect_combo.currentText()
        presets = {"16:9": (16, 9), "4:3": (4, 3), "3:2": (3, 2), "1:1": (1, 1),
                   "9:16（縦）": (9, 16), "A4横": (297, 210), "A4縦": (210, 297)}
        if t in presets:
            w, h = presets[t]
        elif t == "カスタム":
            w, h = self.aspect_w.value(), self.aspect_h.value()
        else:
            return None
        return (h / w) if w else None

    def _apply_aspect(self):
        """プロット領域の縦横比を固定（None で解除）。第2軸にも適用。画面プレビュー用。"""
        ratio = self._aspect_ratio()
        try:
            self.ax.set_box_aspect(ratio)
            ax2 = getattr(self.ax, "_twin_secondary", None)
            if ax2 is not None:
                ax2.set_box_aspect(ratio)
        except Exception:
            pass

    def _export_figsize(self, base=7.0):
        """出力画像のサイズ(インチ)。選択比率があれば画像そのものをその比率にする。
        自動なら現在の図サイズ。ratio は高さ/幅。"""
        ratio = self._aspect_ratio()
        if not ratio:
            return tuple(self.fig.get_size_inches())
        if ratio <= 1.0:                 # 横長: 幅を base に
            return (base, base * ratio)
        return (base / ratio, base)      # 縦長: 高さを base に

    @staticmethod
    def _field_float(le):
        """QLineEdit を (値 or None, 妥当か) で返す。空欄は (None, True)。"""
        t = le.text().strip()
        if t == "":
            return None, True
        try:
            return float(t), True
        except ValueError:
            return None, False

    def _range_pair(self, le_min, le_max, name, issues):
        vmin, ok1 = self._field_float(le_min)
        vmax, ok2 = self._field_float(le_max)
        if not ok1:
            issues.append(f"{name}軸 最小値を数値として読めません")
        if not ok2:
            issues.append(f"{name}軸 最大値を数値として読めません")
        if vmin is not None and vmax is not None and vmin >= vmax:
            issues.append(f"{name}軸 最小≥最大のため範囲指定を無視しました")
            return (None, None)
        return (vmin, vmax)

    @staticmethod
    def _has_nonpositive(arrays):
        import numpy as np
        import pandas as pd
        for a in arrays:
            if a is None:
                continue
            v = pd.to_numeric(pd.Series(a), errors="coerce").to_numpy(dtype=float)
            v = v[np.isfinite(v)]
            if v.size and v.min() <= 0:
                return True
        return False

    def _plot_format_kwargs(self):
        """draw_graph と batch_export で共通の描画フォーマット設定を1か所に集約。
        新しい書式オプションはここに足せば両方（画面描画／一括出力）へ自動反映される。"""
        return dict(
            bins=self.bins_spin.value(),
            grid=self.grid_check.isChecked(),
            legend=self.legend_check.isChecked(),
            legend_loc=self.legend_loc.currentText(),
            xlog=self.xlog.isChecked(), ylog=self.ylog.isChecked(),
            pct=self.pct_check.isChecked(), fonts=self._fonts(),
            trendline={"type": self.trend_combo.currentText(),
                       "degree": self.trend_degree.value(),
                       "window": self.trend_window.value(),
                       "show_eq": self.trend_eq.isChecked(),
                       "color": getattr(self, "trend_color", "") or ""},
            data_labels=self.data_labels_check.isChecked(),
            xscale=_parse_float(self.xscale_edit.text(), 1.0) or 1.0,
            yscale=_parse_float(self.yscale_edit.text(), 1.0) or 1.0,
            xunit=self.xunit_edit.text().strip(),
            yunit=self.yunit_edit.text().strip(),
            bg_color=getattr(self, "bg_color", "") or "",
            grid_width=self.grid_width.value(),
            frame_width=self.frame_width.value(),
            xinvert=self.xinvert_check.isChecked(),
            yinvert=self.yinvert_check.isChecked(),
        )

    def draw_graph(self):
        # 再入防止: busy描画中の processEvents() からデバウンス再描画が割り込むと、
        # 軸が中途半端な状態のまま再描画され不正なアーティストが残る。1回に直列化する。
        if getattr(self, "_drawing", False):
            return
        self._drawing = True
        try:
            self._draw_graph_body()
        finally:
            self._drawing = False

    def _draw_graph_body(self):
        if not self.datasets:
            QtWidgets.QMessageBox.information(self, "情報", "先にファイルを追加してください。")
            return
        # Y系列未選択は正常な一時状態。エラーのポップアップは出さず、空表示＋案内のみ。
        if not self._selected_series_items():
            self._draw_placeholder()
            self._rebuild_series_bar(self.chart_combo.currentText())
            self._set_status("Y軸（値）の系列をチェックするとグラフを表示します。")
            return
        ctype = self.chart_combo.currentText()
        issues = []
        xlim = self._range_pair(self.xmin, self.xmax, "X", issues)
        ylim = self._range_pair(self.ymin, self.ymax, "Y", issues)

        scope = self._scope_dict()
        if scope["enabled"] and ctype in ("折れ線", "散布図"):
            if not (scope["t_per_div"] and scope["t_per_div"] > 0
                    and scope["v_per_div"] and scope["v_per_div"] > 0):
                issues.append("time/div・V/div は正の値が必要（オシロ表示を無効化）")
                scope = dict(scope, enabled=False)

        self._clear_dynamic_resample()
        self._reset_figure_axes()   # スペクトログラム等のカラーバー軸を除去
        self._cursor_pts = []; self._cursor_artists = []  # 再描画で軸がクリアされる
        self._cursors = []; self._cursor_drag = None; self._cursor_text = None
        try:
            series, categories = self._build_series(ctype)
            if self.ylog.isChecked() and self._has_nonpositive([s["y"] for s in series]):
                issues.append("Y対数: 0以下の値は表示されません")
            if (self.xlog.isChecked() and ctype in ("折れ線", "散布図")
                    and self._has_nonpositive([s.get("x") for s in series])):
                issues.append("X対数: 0以下の値は表示されません")

            # 大容量データの間引き（折れ線/散布図のみ）
            total = sum(len(s.get("y", [])) for s in series)
            max_points = (DECIMATE_TARGET if (self.decimate_check.isChecked()
                          and ctype in ("折れ線", "散布図") and total > DECIMATE_TARGET) else 0)

            busy = total > BUSY_ROWS
            if busy:
                QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
                self._set_status(f"描画中…（{total:,} 点）"); QtWidgets.QApplication.processEvents()
            try:
                markers = self._peak_markers() if self.show_peaks_check.isChecked() else None
                sec_label = " / ".join(s["label"] for s in series
                                       if s.get("axis") == "secondary")
                plot_series(
                    self.ax, series, ctype, categories=categories,
                    title=self.title_edit.text(),
                    xlabel=self.xlabel_edit.text() or self._effective_x_label(),
                    ylabel=self.ylabel_edit.text() or self._effective_y_label(),
                    xlim=xlim, ylim=ylim,
                    scope=scope, markers=markers, max_points=max_points,
                    secondary_label=sec_label,
                    **self._plot_format_kwargs(),
                )
                self._apply_aspect()   # 縦横比の固定（自動なら解除）
                self._apply_tick_spacing(ctype, scope)   # 目盛り間隔（指定時）
                self._draw_ds_annotations()              # データサイエンス注記（選択時）
                try:
                    self.fig.tight_layout()
                except Exception:
                    pass
                self.canvas.draw()
            finally:
                if busy:
                    QtWidgets.QApplication.restoreOverrideCursor()

            if max_points:
                self._setup_dynamic_resample(series, ctype, max_points)
            self._rebuild_series_bar(ctype)   # グラフ上部の系列選択バー
            # カーソル追従用に、実際に描画されたデータ線を保持（近似曲線は除く）
            self._plotted_artists = [
                (ln.get_label(), ln) for ln in self.ax.get_lines()
                if "近似" not in str(ln.get_label())]
            # スタイルのみ変更を即時反映するための skey->Line2D マップ（安全な場合のみ）
            self._style_artists = self._build_style_artist_map(series, ctype, bool(max_points))
            self._has_drawn = True
            self._snapshot()   # Undo/Redo 用に設定の履歴を記録
            msg = f"「{ctype}」を描画しました（系列 {len(series)}）。"
            if max_points:
                msg += f"（{total:,}点を間引き表示）"
            if issues:
                msg += "  ⚠ " + " / ".join(issues)
            self._set_status(msg)
        except Exception as e:  # noqa: BLE001
            get_logger().exception("描画エラー")
            QtWidgets.QMessageBox.critical(self, "描画エラー", str(e))

    def _apply_tick_spacing(self, ctype, scope):
        """目盛り間隔（メモリ間隔）の手動指定を適用する。
        空欄や非対応（オシロdiv表示中・対数軸・カテゴリ軸・円）では何もしない。"""
        if ctype == "円":
            return
        if scope.get("enabled") and ctype in ("折れ線", "散布図"):
            return   # オシロ表示中は div 目盛りを優先
        from matplotlib.ticker import MultipleLocator
        dx = _parse_float(self.xtick_edit.text())
        dy = _parse_float(self.ytick_edit.text())

        def _too_many(lo, hi, step):
            # 間隔が範囲に対して小さすぎると数千の目盛りを生成し matplotlib が
            # MAXTICKS 警告を連発する。目盛りが多すぎる指定は無視する（暴走防止）。
            try:
                return abs(hi - lo) / step > 1000
            except (ZeroDivisionError, TypeError):
                return True

        # X目盛りは数値X（折れ線/散布図）でのみ意味を持つ。カテゴリ軸（棒/円）は対象外
        if (dx and dx > 0 and ctype in ("折れ線", "散布図")
                and self.ax.get_xscale() != "log"):
            x0, x1 = self.ax.get_xlim()
            if not _too_many(x0, x1, dx):
                try:
                    self.ax.xaxis.set_major_locator(MultipleLocator(dx))
                except Exception:
                    pass
        if dy and dy > 0 and self.ax.get_yscale() != "log":
            y0, y1 = self.ax.get_ylim()
            if not _too_many(y0, y1, dy):
                try:
                    self.ax.yaxis.set_major_locator(MultipleLocator(dy))
                except Exception:
                    pass

    def _draw_ds_annotations(self):
        """『表示』にチェックした指標をグラフへ注記する。
        データサイエンス＝左上、オシロ/解析の測定値＝右上に分けて描く。"""
        self._draw_annotation_box(getattr(self, "_ds_annotations", None), "tl")
        self._draw_annotation_box(getattr(self, "_meas_annotations", None), "tr")

    def _draw_annotation_box(self, anns, corner):
        """注記テキストボックスを指定コーナーに描く（注記フォントサイズを使用）。"""
        if not anns:
            return
        fs = self.fs_annot.value() if hasattr(self, "fs_annot") else 9
        x, y, ha, va = {"tl": (0.02, 0.98, "left", "top"),
                        "tr": (0.98, 0.98, "right", "top")}[corner]
        try:
            self.ax.text(
                x, y, "\n".join(anns), transform=self.ax.transAxes,
                ha=ha, va=va, fontsize=fs, zorder=20,
                bbox=dict(boxstyle="round", facecolor="white", alpha=0.8, edgecolor="#888"))
        except Exception:
            pass

    def _reset_figure_axes(self):
        """メイン軸以外（カラーバー等）を図から取り除く。"""
        for a in list(self.fig.axes):
            if a is not self.ax:
                try:
                    a.remove()
                except Exception:
                    pass
        # 系列選択バーの表示/非表示は _rebuild_series_bar が管理する（ここでは触らない）

    # ------------------------------------------------------------ ズーム再サンプル
    def _clear_dynamic_resample(self):
        if self._dyn_cid is not None:
            try:
                self.ax.callbacks.disconnect(self._dyn_cid)
            except Exception:
                pass
            self._dyn_cid = None
        self._dyn = []

    def _setup_dynamic_resample(self, series, ctype, max_points):
        """折れ線（数値X）について、間引き元の全データと描画線を保持し、
        ズーム時に表示範囲だけ再サンプルできるようにする。"""
        if ctype != "折れ線":
            return
        import numpy as np
        import pandas as pd
        # 描画線は単位換算後（x×xscale, 主軸yは×yscale）の座標を持つ。再サンプル元データにも
        # 同じ倍率を掛けておかないと、ズーム時に未換算座標へ戻り曲線が誤った位置/大きさに飛ぶ。
        xscale = _parse_float(self.xscale_edit.text(), 1.0) or 1.0
        yscale = _parse_float(self.yscale_edit.text(), 1.0) or 1.0
        lines = self.ax.get_lines()
        for i, s in enumerate(series):
            if i >= len(lines) or s.get("x") is None:
                continue
            fx = pd.to_numeric(pd.Series(s["x"]), errors="coerce").to_numpy(dtype=float)
            if np.isfinite(fx).mean() < 0.8:    # 数値Xのみ対象
                continue
            fy = pd.to_numeric(pd.Series(s["y"]), errors="coerce").to_numpy(dtype=float)
            if xscale != 1.0:
                fx = fx * xscale
            if yscale != 1.0 and s.get("axis") != "secondary":   # Y換算は主軸のみ（描画と同じ）
                fy = fy * yscale
            order = np.argsort(fx)
            self._dyn.append((lines[i], fx[order], fy[order], max_points))
        if self._dyn:
            self._dyn_cid = self.ax.callbacks.connect("xlim_changed", self._on_xlim_changed)

    def _on_xlim_changed(self, _ax):
        if self._resampling or not self._dyn:
            return
        self._resample_timer.start(120)

    def _do_resample(self):
        if not self._dyn:
            return
        import numpy as np
        x0, x1 = self.ax.get_xlim()
        if x1 < x0:
            x0, x1 = x1, x0
        margin = (x1 - x0) * 0.05
        self._resampling = True
        try:
            for line, fx, fy, mp in self._dyn:
                lo = np.searchsorted(fx, x0 - margin)
                hi = np.searchsorted(fx, x1 + margin)
                vx, vy = fx[lo:hi], fy[lo:hi]
                if vx.size == 0:
                    continue
                dx, dy = decimate_minmax(vx, vy, mp)
                line.set_data(dx, dy)
            self.canvas.draw_idle()
        finally:
            self._resampling = False

    def _draw_placeholder(self):
        self._reset_figure_axes()
        self.ax.clear()
        self.ax.set_facecolor("white"); self.ax.tick_params(colors="black")
        self.ax.text(0.5, 0.5, "『データ』タブでファイルを追加し、\n列を選んで「グラフを描画」",
                     ha="center", va="center", fontsize=12, color="#888",
                     transform=self.ax.transAxes)
        self.ax.set_xticks([]); self.ax.set_yticks([])
        self.canvas.draw()

    def _set_status(self, text):
        self.status.showMessage(text)

# ======================================================================
# ↑ graph_app_mixins/plotting.py
# ======================================================================
"""ScopeCursorMixin: GraphApp から分離した ScopeCursorMixin 群（挙動は本体と同一）。"""


class ScopeCursorMixin:
    # ------------------------------------------------------------ カーソル測定
    def toggle_cursors(self, on):
        if on:
            self._cursors = []          # [{x, vline, marker}, ...] 最大2本
            self._cursor_drag = None
            self._cursor_text = None
            self._clear_cursor_artists()
            self._cursor_cid = (
                self.canvas.mpl_connect("button_press_event", self._on_cursor_press),
                self.canvas.mpl_connect("motion_notify_event", self._on_cursor_motion),
                self.canvas.mpl_connect("button_release_event", self._on_cursor_release),
            )
            self._set_status("カーソル: クリックで2本設置 → 線をドラッグで微調整（波形に追従）")
        else:
            if self._cursor_cid:
                for c in self._cursor_cid:
                    self.canvas.mpl_disconnect(c)
                self._cursor_cid = None
            self._clear_cursor_artists()
            self.canvas.draw_idle()

    def _clear_cursor_artists(self):
        for a in self._cursor_artists:
            try:
                a.remove()
            except Exception:
                pass
        self._cursor_artists = []
        self._cursors = []
        self._cursor_text = None

    def _cursor_track_y(self, x):
        """最初に描画した線の x における y を補間（カーソルを波形に追従させる）。"""
        if not self._plotted_artists:
            return 0.0
        try:
            import numpy as np
            line = self._plotted_artists[0][1]
            xd = np.asarray(line.get_xdata(), float)
            yd = np.asarray(line.get_ydata(), float)
            order = np.argsort(xd)
            return float(np.interp(x, xd[order], yd[order]))
        except Exception:
            return 0.0

    def _add_cursor(self, x):
        y = self._cursor_track_y(x)
        vl = self.ax.axvline(x, color="#e6194b", lw=0.9, ls="--")
        mk, = self.ax.plot([x], [y], "o", color="#e6194b", ms=6)
        self._cursors.append({"x": x, "vline": vl, "marker": mk})
        self._cursor_artists += [vl, mk]

    def _cursor_near(self, event):
        """クリック位置に近い既存カーソルの index を返す（無ければ None）。"""
        for i, c in enumerate(self._cursors):
            try:
                cx_px = self.ax.transData.transform((c["x"], 0))[0]
                if abs(event.x - cx_px) < 8:
                    return i
            except Exception:
                pass
        return None

    def _on_cursor_press(self, event):
        if event.inaxes is not self.ax or event.xdata is None:
            return
        near = self._cursor_near(event)
        if near is not None:                       # 既存カーソルを掴んで微調整
            self._cursor_drag = near
            return
        if len(self._cursors) >= 2:                # 3本目で計測リセット
            self._clear_cursor_artists()
        self._add_cursor(event.xdata)
        self._update_cursor_readout()
        self.canvas.draw_idle()

    def _on_cursor_motion(self, event):
        if self._cursor_drag is None or event.inaxes is not self.ax or event.xdata is None:
            return
        c = self._cursors[self._cursor_drag]
        c["x"] = event.xdata
        c["vline"].set_xdata([event.xdata, event.xdata])
        c["marker"].set_data([event.xdata], [self._cursor_track_y(event.xdata)])
        self._update_cursor_readout()
        self.canvas.draw_idle()

    def _on_cursor_release(self, event):
        self._cursor_drag = None

    def _update_cursor_readout(self):
        if self._cursor_text is not None:
            try:
                self._cursor_text.remove()
            except Exception:
                pass
            self._cursor_text = None
        if len(self._cursors) == 2:
            x1, x2 = self._cursors[0]["x"], self._cursors[1]["x"]
            y1, y2 = self._cursor_track_y(x1), self._cursor_track_y(x2)
            dt, dv = x2 - x1, y2 - y1
            freq = (1.0 / dt) if dt else float("inf")
            txt = (f"Δt={format_eng(abs(dt))}  ΔV={format_eng(abs(dv))}"
                   f"  1/Δt={format_eng(abs(freq))}Hz")
            self._cursor_text = self.ax.text(
                0.5, 0.98, txt, transform=self.ax.transAxes, ha="center", va="top",
                color="#e6194b", fontsize=9,
                bbox=dict(facecolor="white", alpha=0.75, edgecolor="#e6194b"))
            self._cursor_artists.append(self._cursor_text)
            self._set_status("カーソル  " + txt)

    # ------------------------------------------------------ オシロ ドラッグ操作
    def _scope_active(self):
        """オシロのドラッグ操作が有効か（オシロ表示ON・折れ線/散布図・他モード非競合）。"""
        return (self.scope_check.isChecked()
                and self.chart_combo.currentText() in ("折れ線", "散布図")
                and self._has_drawn
                and self._cursor_cid is None
                and not getattr(self.toolbar, "mode", ""))

    def _scope_overlay(self, text):
        self._remove_scope_overlay()
        # family="monospace" は日本語グリフを持たず「位置/中心」等が文字化けするため指定しない
        # （rcParams の日本語フォントを使う）。
        self._scope_ov = self.ax.text(
            0.99, 0.02, text, transform=self.ax.transAxes, ha="right", va="bottom",
            color="#7CFC00", fontsize=11,
            bbox=dict(facecolor="black", alpha=0.65, edgecolor="#7CFC00"))

    def _remove_scope_overlay(self):
        if self._scope_ov is not None:
            try:
                self._scope_ov.remove()
            except Exception:
                pass
            self._scope_ov = None

    def _shift_held(self, event=None):
        """Shift押下を判定。matplotlibの event.key はバックエンドによりスクロール時に
        Shiftを取りこぼすため、Qtのキーボード修飾キー状態を優先して見る。"""
        try:
            mods = QtWidgets.QApplication.keyboardModifiers()
            if bool(mods & QtCore.Qt.KeyboardModifier.ShiftModifier):
                return True
        except Exception:
            pass
        return bool(event is not None and event.key and "shift" in str(event.key))

    def _scope_on_press(self, event):
        if (not self._scope_active() or event.inaxes is not self.ax
                or event.button not in (1, 3) or event.x is None):
            return
        bbox = self.ax.get_window_extent()
        self._scope_drag = {
            "button": event.button, "shift": self._shift_held(event),
            "px": (event.x, event.y),
            "xlim": self.ax.get_xlim(), "ylim": self.ax.get_ylim(),
            "tdiv": parse_eng(self.tdiv.currentText(), 1e-3) or 1e-3,
            "vdiv": parse_eng(self.vdiv.currentText(), 1.0) or 1.0,
            "w": max(bbox.width, 1.0), "h": max(bbox.height, 1.0),
        }

    def _scope_on_motion(self, event):
        d = self._scope_drag
        if not d or event.x is None:
            return
        dxpx = event.x - d["px"][0]
        dypx = event.y - d["px"][1]
        xd, yd = self.xdivs.value(), self.ydivs.value()
        if d["button"] == 1 and not d["shift"]:   # 左ドラッグ = パン（位置移動）
            x0, x1 = d["xlim"]; y0, y1 = d["ylim"]
            dpx = (x1 - x0) / d["w"]; dpy = (y1 - y0) / d["h"]
            nx0, nx1 = x0 - dxpx * dpx, x1 - dxpx * dpx
            ny0, ny1 = y0 - dypx * dpy, y1 - dypx * dpy
            self.ax.set_xlim(nx0, nx1); self.ax.set_ylim(ny0, ny1)
            self._scope_overlay(f"位置  X中心={format_eng((nx0+nx1)/2)}  "
                                f"Y中心={format_eng((ny0+ny1)/2)}")
        else:                                       # 右ドラッグ/Shift = スケール（div）
            xc = (d["xlim"][0] + d["xlim"][1]) / 2
            yc = (d["ylim"][0] + d["ylim"][1]) / 2
            ntdiv = d["tdiv"] * (2 ** (dxpx / 150.0))
            nvdiv = d["vdiv"] * (2 ** (-dypx / 150.0))
            self.ax.set_xlim(xc - xd / 2 * ntdiv, xc + xd / 2 * ntdiv)
            self.ax.set_ylim(yc - yd / 2 * nvdiv, yc + yd / 2 * nvdiv)
            self._scope_overlay(f"{format_eng(ntdiv)}s/div   "
                                f"{format_eng(nvdiv)}/div")
        self.canvas.draw_idle()

    def _scope_on_release(self, event):
        if not self._scope_drag:
            return
        self._scope_drag = None
        self._remove_scope_overlay()
        x0, x1 = self.ax.get_xlim(); y0, y1 = self.ax.get_ylim()
        xd, yd = self.xdivs.value(), self.ydivs.value()
        self._suspend_redraw = True
        self.xpos.setText(f"{(x0+x1)/2:.6g}"); self.ypos.setText(f"{(y0+y1)/2:.6g}")
        self.tdiv.setCurrentText(format_eng((x1 - x0) / xd) + "s")
        self.vdiv.setCurrentText(format_eng((y1 - y0) / yd))
        self._suspend_redraw = False
        self.draw_graph()   # グラティクル等を正式に再構築

    def _scope_on_scroll(self, event):
        if event.inaxes is not self.ax:
            return
        if self._scope_active():
            step = 0.8 if event.button == "up" else 1.25   # up=ズームイン(div小)
            self._suspend_redraw = True
            if self._shift_held(event):
                cur = parse_eng(self.vdiv.currentText(), 1.0) or 1.0
                self.vdiv.setCurrentText(format_eng(cur * step))
            else:
                cur = parse_eng(self.tdiv.currentText(), 1e-3) or 1e-3
                self.tdiv.setCurrentText(format_eng(cur * step) + "s")
            self._suspend_redraw = False
            self.draw_graph()
            return
        # オシロ表示以外でもホイールで拡大縮小（カーソル位置を中心に）
        self._wheel_zoom(event)

    def _wheel_zoom(self, event):
        """通常グラフのマウスホイール拡大縮小。カーソル位置を中心にズームする。
        Shift+ホイールはX方向のみ（波形の横拡大）。"""
        # カーソル測定中・ツールバーのパン/ズーム中・未描画・円グラフでは無効
        if (self._cursor_cid is not None
                or getattr(self.toolbar, "mode", "")
                or not getattr(self, "_has_drawn", False)
                or self.chart_combo.currentText() == "円"):
            return
        factor = 0.8 if event.button == "up" else 1.25   # up=拡大（範囲を狭める）
        x0, x1 = self.ax.get_xlim()
        y0, y1 = self.ax.get_ylim()
        xc = event.xdata if event.xdata is not None else (x0 + x1) / 2.0
        yc = event.ydata if event.ydata is not None else (y0 + y1) / 2.0
        xlog = self.ax.get_xscale() == "log"
        ylog = self.ax.get_yscale() == "log"
        self.ax.set_xlim(*self._zoom_pair(x0, x1, xc, factor, xlog))
        if not self._shift_held(event):     # Shift押下時はYを保持（横方向のみ拡大）
            self.ax.set_ylim(*self._zoom_pair(y0, y1, yc, factor, ylog))
        self.canvas.draw_idle()

    @staticmethod
    def _zoom_pair(lo, hi, center, factor, log=False):
        """[lo, hi] を center を中心に factor 倍に拡縮した新しい範囲を返す（log軸対応）。"""
        import numpy as np
        if log and lo > 0 and hi > 0 and center > 0:
            l0, l1, lc = np.log10(lo), np.log10(hi), np.log10(center)
            return 10.0 ** (lc - (lc - l0) * factor), 10.0 ** (lc + (l1 - lc) * factor)
        return center - (center - lo) * factor, center + (hi - center) * factor

    def auto_scale_scope(self):
        """選択中の全系列が収まるように time/div・V/div・中心を自動設定する。"""
        import numpy as np
        import pandas as pd
        items = self._selected_series_items()
        if not items:
            QtWidgets.QMessageBox.information(self, "情報", "データタブでY系列を選択してください。")
            return
        xname = self.x_combo.currentText()
        tmins, tmaxs, ymins, ymaxs = [], [], [], []
        for fl, col, _ in items:
            df = self.datasets[fl]
            raw = df[xname].to_numpy() if xname in df.columns else df.iloc[:, 0].to_numpy()
            tt = pd.to_numeric(pd.Series(raw), errors="coerce").to_numpy(dtype=float)
            if np.isnan(tt).mean() > 0.5:
                tt = np.arange(len(tt), dtype=float)
            yy = pd.to_numeric(pd.Series(df[col].to_numpy()), errors="coerce").to_numpy(dtype=float)
            tt, yy = tt[np.isfinite(tt)], yy[np.isfinite(yy)]
            if tt.size:
                tmins.append(tt.min()); tmaxs.append(tt.max())
            if yy.size:
                ymins.append(yy.min()); ymaxs.append(yy.max())
        if not tmins or not ymins:
            QtWidgets.QMessageBox.information(self, "情報", "数値データがありません。")
            return
        tmin, tmax = min(tmins), max(tmaxs)
        ymin, ymax = min(ymins), max(ymaxs)
        xd, yd = self.xdivs.value(), self.ydivs.value()
        tpd = (tmax - tmin) / xd if tmax > tmin else 1e-3
        vpd = (ymax - ymin) / (yd - 1) if ymax > ymin else 1.0
        self._suspend_redraw = True
        self.tdiv.setCurrentText(format_eng(tpd) + "s")
        self.vdiv.setCurrentText(format_eng(vpd))
        self.xpos.setText(f"{(tmin+tmax)/2:.4g}"); self.ypos.setText(f"{(ymin+ymax)/2:.4g}")
        self.scope_check.setChecked(True)
        self._suspend_redraw = False
        self.draw_graph()

# ======================================================================
# ↑ graph_app_mixins/scope_cursor.py
# ======================================================================
"""AnalysisMixin: GraphApp から分離した AnalysisMixin 群（挙動は本体と同一）。"""


class AnalysisMixin:
    # ------------------------------------------------------------ 解析
    def _xy_for(self, fl, col):
        """指定系列(fl,col)の (t, y) を返す。時間軸は数値化（非数値ならインデックス）。
        「表示範囲のみ測定」ONなら画面のX範囲に絞る。"""
        import numpy as np
        import pandas as pd
        df = self.datasets[fl]
        xname = self.x_combo.currentText()
        raw = df[xname].to_numpy() if xname in df.columns else df.iloc[:, 0].to_numpy()
        t = pd.to_numeric(pd.Series(raw), errors="coerce").to_numpy(dtype=float)
        if np.isnan(t).mean() > 0.5:  # 非数値Xはインデックスを時間軸とみなす
            t = np.arange(len(t), dtype=float)
        y = pd.to_numeric(pd.Series(df[col].to_numpy()), errors="coerce").to_numpy(dtype=float)
        if self.window_meas_check.isChecked() and self._has_drawn:
            x0, x1 = self.ax.get_xlim()
            if x1 < x0:
                x0, x1 = x1, x0
            mask = (t >= x0) & (t <= x1)
            if int(mask.sum()) >= 3:
                t, y = t[mask], y[mask]
        return t, y

    def _analysis_xy(self):
        """解析対象（解析対象コンボで選んだ1系列）の (t, y, label) を返す。"""
        disp = self.analysis_target.currentText()
        for fl, col, d in self._selected_series_items():
            if d == disp:
                t, y = self._xy_for(fl, col)
                return t, y, d
        return None, None, None

    def _peak_markers(self):
        if self.chart_combo.currentText() not in ("折れ線", "散布図"):
            return None
        t, y, _ = self._analysis_xy()
        if t is None:
            return None
        try:
            peaks = find_signal_peaks(y, t=t, n=self.npeaks.value(),
                                               smooth=self.smooth_spin.value())
        except Exception:
            return None
        return [{"x": p["time"], "y": p["value"], "text": f"第{p['rank']}",
                 "color": "#ff3030"} for p in peaks if p["time"] is not None]

    def run_analysis(self):
        t, y, label = self._analysis_xy()
        if t is None:
            QtWidgets.QMessageBox.information(self, "情報", "解析対象の系列を選択してください。")
            return
        import numpy as np
        y = np.asarray(y, float)
        res = analyze(t, y, n_peaks=self.npeaks.value(),
                               smooth=self.smooth_spin.value())

        self.peak_table.setRowCount(len(res["peaks"]))
        for r, p in enumerate(res["peaks"]):
            self.peak_table.setItem(r, 0, QtWidgets.QTableWidgetItem(f"第{p['rank']}"))
            tv = "-" if p["time"] is None else f"{p['time']*1e3:.4g} ms"
            self.peak_table.setItem(r, 1, QtWidgets.QTableWidgetItem(tv))
            self.peak_table.setItem(r, 2, QtWidgets.QTableWidgetItem(f"{p['value']:.4g}"))

        rows = res["measurements"]
        had_ann = bool(getattr(self, "_meas_annotations", None))
        self._meas_annotations = []   # 新しい解析を表示したら前回の注記はリセット
        self.meas_table.setRowCount(len(rows))
        for r, m in enumerate(rows):
            val = m["value"]
            txt = "-" if val is None else f"{val:.6g} {m['unit']}"
            self.meas_table.setItem(r, 0, QtWidgets.QTableWidgetItem(m["name"]))
            self.meas_table.setItem(r, 1, QtWidgets.QTableWidgetItem(txt))
            cb = QtWidgets.QCheckBox()
            cb.setToolTip("チェックすると、この測定値をグラフ上に注記表示します。")
            cb.toggled.connect(self._refresh_meas_annotations)
            self.meas_table.setCellWidget(r, 2, cb)

        if self.show_peaks_check.isChecked() or had_ann:
            self.draw_graph()   # ピーク表示中、または前回の注記を消すため
        self._set_status(f"解析しました: {label}")

    def _refresh_meas_annotations(self, *_):
        """測定値表で『表示』にチェックした行を集めてグラフへ注記表示する。"""
        anns = []
        for r in range(self.meas_table.rowCount()):
            cb = self.meas_table.cellWidget(r, 2)
            if cb is not None and cb.isChecked():
                k = self.meas_table.item(r, 0)
                val = self.meas_table.item(r, 1)
                if k is not None and val is not None:
                    anns.append(f"{k.text()} = {val.text()}")
        self._meas_annotations = anns
        if self.datasets:   # 特殊表示(スペクトログラム等)直後でも通常グラフへ再描画して反映
            self.draw_graph()

    def show_fft(self):
        """選択中の全系列のFFTスペクトルを1枚に重ね描き（系列ごとに色分け・凡例）。"""
        items = self._selected_series_items()
        if not items:
            QtWidgets.QMessageBox.information(self, "情報", "解析する系列を選択してください。")
            return
        import numpy as np
        win = self.fft_window.currentText() if hasattr(self, "fft_window") else "hann"
        use_db = hasattr(self, "fft_db") and self.fft_db.isChecked()
        ylab = "振幅 [dBV]" if use_db else "振幅"
        series, markers, drawn = [], [], 0
        for idx, (fl, col, disp) in enumerate(items):
            t, y = self._xy_for(fl, col)
            if t is None or len(np.asarray(y)) < 4:
                continue
            freqs, amp = fft_spectrum(t, np.asarray(y, float), window=win)
            if freqs is None:
                continue
            color = (self.series_styles.get(self._style_key(fl, col)) or {}).get("color") \
                or f"C{idx % 10}"        # 系列の指定色、無ければ既定カラーサイクル
            disp_amp = to_db(amp) if use_db else amp
            series.append({"label": f"FFT: {disp}", "x": freqs, "y": disp_amp,
                           "style": {"color": color, "linewidth": 1.0}})
            for p in find_spectral_peaks(t, np.asarray(y, float), n=self.npeaks.value()):
                yv = to_db(np.array([p["amplitude"]]))[0] if use_db else p["amplitude"]
                markers.append({"x": p["frequency"], "y": yv,
                                "text": f"{p['frequency']:.0f}Hz", "color": color})
            drawn += 1
        if drawn == 0:
            QtWidgets.QMessageBox.warning(self, "FFT", "FFT を計算できませんでした。")
            return
        self._reset_figure_axes()
        plot_series(
            self.ax, series, "折れ線",
            title=f"FFTスペクトル（{win}窓・{drawn}系列）", xlabel="周波数 [Hz]", ylabel=ylab,
            grid=True, legend=(drawn > 1), markers=markers, fonts=self._fonts())
        self._apply_aspect()   # 縦横比の設定をFFT表示にも適用（自動なら解除）
        try:
            self.fig.tight_layout()
        except Exception:
            pass
        self.canvas.draw()
        self._set_status(f"FFT表示: {drawn}系列を重ね描き")

    # -------------------------------------------------- 全系列の一括解析（別ウィンドウ・CSV保存）
    def analyze_all_series(self):
        """選択中の全系列のピーク＋測定を計算し、別ウィンドウ（表＋CSV保存）で表示する。"""
        items = self._selected_series_items()
        if not items:
            QtWidgets.QMessageBox.information(self, "情報", "解析する系列を選択してください。")
            return
        import numpy as np
        peak_rows, meas_rows = [], []
        for fl, col, disp in items:
            t, y = self._xy_for(fl, col)
            if t is None or len(np.asarray(y)) < 2:
                continue
            r = analyze(t, np.asarray(y, float),
                                 n_peaks=self.npeaks.value(), smooth=self.smooth_spin.value())
            for p in r["peaks"]:
                tv = None if p["time"] is None else p["time"] * 1e3
                peak_rows.append((disp, f"第{p['rank']}", tv, p["value"]))
            for m in r["measurements"]:
                meas_rows.append((disp, m["name"], m["value"], m["unit"]))
        if not peak_rows and not meas_rows:
            QtWidgets.QMessageBox.information(self, "情報", "解析できる系列がありません。")
            return
        self._show_analysis_window(peak_rows, meas_rows)

    def _show_analysis_window(self, peak_rows, meas_rows):
        """系列ごとのピーク・測定を2つの表で別ウィンドウ表示。CSV保存ボタン付き。"""
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("全系列の解析結果")
        dlg.resize(760, 600)
        lay = QtWidgets.QVBoxLayout(dlg)
        no_edit = QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers

        lay.addWidget(QtWidgets.QLabel("■ ピーク（系列ごと）"))
        pk = QtWidgets.QTableWidget(len(peak_rows), 4)
        pk.setHorizontalHeaderLabels(["系列", "順位", "時刻", "値"])
        pk.setEditTriggers(no_edit)
        for r, (s, rank, tv, val) in enumerate(peak_rows):
            pk.setItem(r, 0, QtWidgets.QTableWidgetItem(str(s)))
            pk.setItem(r, 1, QtWidgets.QTableWidgetItem(str(rank)))
            pk.setItem(r, 2, QtWidgets.QTableWidgetItem("-" if tv is None else f"{tv:.4g} ms"))
            pk.setItem(r, 3, QtWidgets.QTableWidgetItem(f"{val:.6g}"))
        pk.resizeColumnsToContents()
        lay.addWidget(pk)

        lay.addWidget(QtWidgets.QLabel("■ 測定（系列ごと）"))
        ms = QtWidgets.QTableWidget(len(meas_rows), 4)
        ms.setHorizontalHeaderLabels(["系列", "項目", "値", "単位"])
        ms.setEditTriggers(no_edit)
        for r, (s, name, val, unit) in enumerate(meas_rows):
            ms.setItem(r, 0, QtWidgets.QTableWidgetItem(str(s)))
            ms.setItem(r, 1, QtWidgets.QTableWidgetItem(str(name)))
            ms.setItem(r, 2, QtWidgets.QTableWidgetItem("-" if val is None else f"{val:.6g}"))
            ms.setItem(r, 3, QtWidgets.QTableWidgetItem(str(unit)))
        ms.resizeColumnsToContents()
        lay.addWidget(ms, 1)

        brow = QtWidgets.QHBoxLayout()
        b_save = QtWidgets.QPushButton("CSVで保存…")
        b_save.clicked.connect(lambda: self._save_analysis_csv(peak_rows, meas_rows))
        b_close = QtWidgets.QPushButton("閉じる")
        b_close.clicked.connect(dlg.close)
        brow.addStretch(1); brow.addWidget(b_save); brow.addWidget(b_close)
        lay.addLayout(brow)
        self._analysis_window = dlg   # 参照保持（GCで即閉じしないように）
        dlg.show()

    def _save_analysis_csv(self, peak_rows, meas_rows):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "解析結果をCSVで保存", self.last_dir, "CSV (*.csv)")
        if not path:
            return
        import csv
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                w.writerow(["# ピーク"])
                w.writerow(["系列", "順位", "時刻[ms]", "値"])
                for s, rank, tv, val in peak_rows:
                    w.writerow([s, rank, "" if tv is None else f"{tv:.6g}", f"{val:.6g}"])
                w.writerow([])
                w.writerow(["# 測定"])
                w.writerow(["系列", "項目", "値", "単位"])
                for s, name, val, unit in meas_rows:
                    w.writerow([s, name, "" if val is None else f"{val:.6g}", unit])
            self.last_dir = os.path.dirname(path)
            self._set_status(f"解析結果を保存しました: {path}")
        except Exception as e:  # noqa: BLE001
            QtWidgets.QMessageBox.critical(self, "保存エラー", str(e))

# ======================================================================
# ↑ graph_app_mixins/analysis_peaks.py
# ======================================================================
"""AdvancedMixin: GraphApp から分離した AdvancedMixin 群（挙動は本体と同一）。"""


class AdvancedMixin:
    # ------------------------------------------------------------ 高度解析
    def _xy_by_disp(self, disp):
        """選択中系列の表示名から (t, y) を取得（時間軸は数値化）。"""
        import numpy as np
        import pandas as pd
        for fl, col, d in self._selected_series_items():
            if d == disp:
                df = self.datasets[fl]
                xname = self.x_combo.currentText()
                raw = df[xname].to_numpy() if xname in df.columns else df.iloc[:, 0].to_numpy()
                t = pd.to_numeric(pd.Series(raw), errors="coerce").to_numpy(dtype=float)
                if np.isnan(t).mean() > 0.5:
                    t = np.arange(len(t), dtype=float)
                y = pd.to_numeric(pd.Series(df[col].to_numpy()), errors="coerce").to_numpy(dtype=float)
                return t, y
        return None, None

    def _on_math_op_change(self, op):
        binary = op in BINARY_OPS
        self.math_b.setEnabled(binary); self.math_b_label.setEnabled(binary)
        needs_param = op in ("移動平均", "ローパス(RC)",
                             "ローパス(Butterworth)", "ハイパス(Butterworth)")
        self.math_param.setEnabled(needs_param); self.math_param_label.setEnabled(needs_param)

    def create_math_channel(self):
        import numpy as np
        op = self.math_op.currentText()
        ta, ya = self._xy_by_disp(self.math_a.currentText())
        if ta is None:
            QtWidgets.QMessageBox.information(self, "情報", "演算対象Aをデータタブで選択してください。")
            return
        try:
            if op in BINARY_OPS:
                tb, yb = self._xy_by_disp(self.math_b.currentText())
                if tb is None:
                    QtWidgets.QMessageBox.information(self, "情報", "演算対象Bを選択してください。")
                    return
                x, r = binary(ta, ya, tb, yb, op)
            else:
                param = parse_eng(self.math_param.text(), None)
                x, r = unary(ta, ya, op, param)
        except Exception as e:  # noqa: BLE001
            QtWidgets.QMessageBox.critical(self, "演算エラー", str(e)); return
        import pandas as pd
        col = f"{op}"
        label = f"Math: {op}"
        base, i = label, 2
        while label in self.datasets:
            label = f"{base} ({i})"; i += 1
        self.datasets[label] = pd.DataFrame({"時間[s]": x, col: r})
        self.meta[label] = {"path": label, "enc": "-", "delim": "-"}
        self._add_file_item(label)
        self._refresh_columns()
        self._set_status(f"数学チャンネルを作成: {label} ▸ {col}")

    def create_math_expr(self):
        """任意数式（A,B,VAR1,VAR2,t と許可関数）で新チャンネルを作成。"""
        import numpy as np
        import pandas as pd
        expr = self.math_expr.text().strip()
        if not expr:
            QtWidgets.QMessageBox.information(self, "情報", "数式を入力してください。")
            return
        ta, ya = self._xy_by_disp(self.math_a.currentText())
        if ta is None:
            QtWidgets.QMessageBox.information(self, "情報", "変数Aの系列をデータタブで選択してください。")
            return
        variables = {"A": ya, "t": ta,
                     "VAR1": parse_eng(self.math_var1.text(), 0.0) or 0.0,
                     "VAR2": parse_eng(self.math_var2.text(), 0.0) or 0.0}
        tb, yb = self._xy_by_disp(self.math_b.currentText())
        if tb is not None and yb is not None:
            variables["B"] = yb if len(yb) == len(ya) else np.interp(ta, tb, yb)
        try:
            r = eval_expr(expr, variables)
            r = np.broadcast_to(np.asarray(r, dtype=float), ya.shape).astype(float)
        except Exception as e:  # noqa: BLE001
            QtWidgets.QMessageBox.critical(self, "数式エラー", str(e))
            return
        label = f"Expr: {expr[:24]}"
        base, i = label, 2
        while label in self.datasets:
            label = f"{base} ({i})"; i += 1
        self.datasets[label] = pd.DataFrame({"時間[s]": ta, "結果": r})
        self.meta[label] = {"path": label, "enc": "-", "delim": "-"}
        self._add_file_item(label)
        self._refresh_columns()
        self._set_status(f"数式チャンネルを作成: {label}")

    def show_param_stats(self):
        """解析対象チャンネルのサイクル統計表＋パラメータ間演算を別ウィンドウで表示。"""
        import numpy as np
        t, y, label = self._analysis_xy()
        if t is None:
            QtWidgets.QMessageBox.information(self, "情報", "解析対象の系列を選択してください。")
            return
        yv = np.asarray(y, float)
        self._show_param_stats_window(label, cycle_statistics(t, yv),
                                      measurements(t, yv))

    def _show_param_stats_window(self, label, stats, meas):
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle(f"パラメータ統計: {label}")
        dlg.resize(700, 560)
        lay = QtWidgets.QVBoxLayout(dlg)
        no_edit = QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers

        lay.addWidget(QtWidgets.QLabel("■ サイクル統計（周期ごとに測り、平均/最大/最小/σ で集計）"))
        tb = QtWidgets.QTableWidget(len(stats), 6)
        tb.setEditTriggers(no_edit)
        tb.setHorizontalHeaderLabels(["パラメータ", "平均", "最大", "最小", "σ", "数"])
        for r, (pname, s) in enumerate(stats.items()):
            tb.setItem(r, 0, QtWidgets.QTableWidgetItem(str(pname)))
            for c, k in enumerate(["mean", "max", "min", "std"], start=1):
                v = s.get(k)
                tb.setItem(r, c, QtWidgets.QTableWidgetItem("-" if v is None else f"{v:.5g}"))
            tb.setItem(r, 5, QtWidgets.QTableWidgetItem(str(s.get("count", 0))))
        tb.resizeColumnsToContents()
        lay.addWidget(tb)

        lay.addWidget(QtWidgets.QLabel("■ パラメータ間演算（測定値どうしを四則）"))
        vals = {m["name"]: m["value"] for m in meas if m["value"] is not None}
        names = list(vals.keys())
        prow = QtWidgets.QHBoxLayout()
        ca = QtWidgets.QComboBox(); ca.addItems(names)
        op = QtWidgets.QComboBox(); op.addItems(["+", "-", "×", "÷"])
        cb = QtWidgets.QComboBox(); cb.addItems(names)
        out = QtWidgets.QLabel("= ?")

        def compute():
            a = vals.get(ca.currentText()); b = vals.get(cb.currentText())
            o = op.currentText()
            try:
                r = {"+": a + b, "-": a - b, "×": a * b,
                     "÷": (a / b if b else float("nan"))}[o]
                out.setText(f"= {r:.6g}")
            except Exception:  # noqa: BLE001
                out.setText("= -")
        bcalc = QtWidgets.QPushButton("計算"); bcalc.clicked.connect(compute)
        prow.addWidget(ca); prow.addWidget(op); prow.addWidget(cb)
        prow.addWidget(bcalc); prow.addWidget(out, 1)
        lay.addLayout(prow)
        bclose = QtWidgets.QPushButton("閉じる"); bclose.clicked.connect(dlg.close)
        lay.addWidget(bclose)
        self._param_stats_window = dlg
        dlg.show()

    def compute_fft_metrics(self):
        import numpy as np
        t, y, label = self._analysis_xy()
        if t is None:
            QtWidgets.QMessageBox.information(self, "情報", "解析対象の系列を選択してください。")
            return
        win = self.fft_window.currentText()
        yv = np.asarray(y, float)
        m = spectrum_metrics(t, yv, window=win)
        rows = [
            ("基本波 f0", m.get("f0"), "Hz"),
            ("THD", m.get("THD_pct"), "%"),
            ("THD", m.get("THD_dB"), "dB"),
            ("SNR", m.get("SNR_dB"), "dB"),
            ("SINAD", m.get("SINAD_dB"), "dB"),
            ("ENOB", m.get("ENOB_bits"), "bit"),
            ("SFDR", m.get("SFDR_dB"), "dB"),
            ("占有帯域幅(99%)", occupied_bandwidth(t, yv, window=win), "Hz"),
            ("チャネル電力(全)", channel_power(t, yv, window=win), "V²"),
        ]
        for h in harmonic_search(t, yv, n_harm=5, window=win):
            rows.append((f"第{h['harmonic']}高調波", h["frequency"], "Hz"))
        self.fft_metrics.setRowCount(len(rows))
        for r, (name, val, unit) in enumerate(rows):
            self.fft_metrics.setItem(r, 0, QtWidgets.QTableWidgetItem(name))
            txt = "-" if val is None else f"{val:.4g} {unit}"
            self.fft_metrics.setItem(r, 1, QtWidgets.QTableWidgetItem(txt))
        self._set_status(f"スペクトル指標を計算: {label}")

    def show_spectrogram(self):
        import numpy as np
        t, y, label = self._analysis_xy()
        if t is None:
            QtWidgets.QMessageBox.information(self, "情報", "解析対象の系列を選択してください。")
            return
        f, tt, S = spectrogram(t, np.asarray(y, float),
                                        window=self.fft_window.currentText())
        if S is None:
            QtWidgets.QMessageBox.warning(self, "スペクトログラム", "計算できませんでした。")
            return
        self._reset_figure_axes()
        self.ax.clear()
        self.ax.set_facecolor("white"); self.ax.tick_params(colors="black")
        mesh = self.ax.pcolormesh(tt, f, S, shading="auto", cmap="viridis")
        self.ax.set_xlabel("時間 [s]"); self.ax.set_ylabel("周波数 [Hz]")
        self.ax.set_title(f"スペクトログラム: {label}")
        try:
            self.fig.colorbar(mesh, ax=self.ax, label="dB")
        except Exception:
            pass
        self._apply_aspect()   # 縦横比の設定をスペクトログラムにも適用
        try:
            self.fig.tight_layout()
        except Exception:
            pass
        self.canvas.draw()
        self._has_drawn = False  # カラーバー付き特殊表示。次のdrawで作り直す
        self._set_status(f"スペクトログラム表示: {label}")

    def run_mask_test(self):
        import numpy as np
        t, y, label = self._analysis_xy()
        if t is None:
            QtWidgets.QMessageBox.information(self, "情報", "解析対象の系列を選択してください。")
            return
        up = parse_eng(self.mask_upper.text(), None)
        lo = parse_eng(self.mask_lower.text(), None)
        if up is None and lo is None:
            QtWidgets.QMessageBox.information(self, "情報", "上限または下限を入力してください。")
            return
        res = mask_test(t, np.asarray(y, float), upper=up, lower=lo)
        # マスク線と違反点を重畳
        self.draw_graph()
        if up is not None:
            self.ax.axhline(up, color="#d00", ls="--", lw=0.8)
        if lo is not None:
            self.ax.axhline(lo, color="#d00", ls="--", lw=0.8)
        if res["violations"]:
            vt = res["violation_times"]
            yv = np.asarray(y, float)[res["mask"]]
            self.ax.plot(vt, yv, ".", color="#d00", ms=3)
        self.canvas.draw()
        verdict = "PASS ✅" if res["passed"] else f"FAIL ❌（{res['violations']}点 超過）"
        self.adv_result.setText(f"マスク判定: {verdict}")
        self._set_status(f"マスク判定 {label}: {verdict}")

    def show_eye_diagram(self):
        import numpy as np
        t, y, label = self._analysis_xy()
        if t is None:
            QtWidgets.QMessageBox.information(self, "情報", "解析対象の系列を選択してください。")
            return
        val = parse_eng(self.eye_rate.text(), 1e6)
        # シンボルレート[Hz] と解釈（>1 ならレート、<1 なら周期[s]とみなす）
        sym_period = (1.0 / val) if val and val > 1 else (val or 1e-6)
        phase, yy = eye_diagram(t, np.asarray(y, float), sym_period, n_ui=2)
        self._reset_figure_axes()
        self.ax.clear()
        self.ax.set_facecolor("white"); self.ax.tick_params(colors="black")
        self.ax.plot(phase * 1e6, yy, ".", ms=0.5, alpha=0.3, color="#1f77b4")
        self.ax.set_xlabel("UI内時間 [µs]"); self.ax.set_ylabel("電圧")
        self.ax.set_title(f"アイダイアグラム: {label}")
        self.ax.grid(True, alpha=0.3)
        em = eye_measurements(t, np.asarray(y, float), sym_period)
        if em:
            self.ax.axhline(em["level1"], color="#2ca02c", ls=":", lw=0.9)
            self.ax.axhline(em["level0"], color="#2ca02c", ls=":", lw=0.9)

            def _g(k):
                v = em.get(k)
                return float("nan") if v is None else v
            self.adv_result.setText(
                "アイ測定: 振幅={:.4g} 高さ={:.4g} 幅={:.4g}µs Q={:.3g} "
                "ER={:.3g}dB ジッタpp={:.3g}ns".format(
                    _g("eye_amplitude"), _g("eye_height"), _g("eye_width") * 1e6,
                    _g("q_factor"), _g("extinction_ratio_db"), _g("jitter_pp") * 1e9))
        try:
            self.fig.tight_layout()
        except Exception:
            pass
        self.canvas.draw()
        self._has_drawn = False
        self._set_status(f"アイダイアグラム表示: {label}")

    def run_jitter(self):
        import numpy as np
        t, y, label = self._analysis_xy()
        if t is None:
            QtWidgets.QMessageBox.information(self, "情報", "解析対象の系列を選択してください。")
            return
        jr = jitter_tie(t, np.asarray(y, float))
        if not jr:
            QtWidgets.QMessageBox.warning(self, "ジッタ", "エッジが不足し計算できませんでした。")
            return
        msg = (f"ジッタ: RMS={format_eng(jr['rms'])}s  "
               f"pp={format_eng(jr['pp'])}s  "
               f"クロック≈{format_eng(jr['freq'])}Hz  エッジ{jr['edges']}本")
        self.adv_result.setText(msg)
        self._set_status(msg)

    def show_cycle_stats(self):
        import numpy as np
        t, y, label = self._analysis_xy()
        if t is None:
            QtWidgets.QMessageBox.information(self, "情報", "解析対象の系列を選択してください。")
            return
        cm = cycle_measurements(t, np.asarray(y, float))
        fs = measurement_stats(cm["freq"])
        amps = measurement_stats(cm["vpp"])
        lines = []
        if fs["count"]:
            lines.append(f"周波数: 平均{format_eng(fs['mean'])}Hz σ={format_eng(fs['std'])} "
                         f"min{format_eng(fs['min'])}〜max{format_eng(fs['max'])} ({fs['count']}サイクル)")
        if amps["count"]:
            lines.append(f"Vpp: 平均{amps['mean']:.4g} σ={amps['std']:.3g} "
                         f"min{amps['min']:.4g}〜max{amps['max']:.4g}")
        self.adv_result.setText("　".join(lines) or "サイクルを検出できませんでした。")
        self._set_status(f"サイクル統計: {label}")

    def show_trend(self):
        import numpy as np
        t, y, label = self._analysis_xy()
        if t is None:
            QtWidgets.QMessageBox.information(self, "情報", "解析対象の系列を選択してください。")
            return
        cm = cycle_measurements(t, np.asarray(y, float))
        if len(cm["cycle_time"]) < 2:
            QtWidgets.QMessageBox.warning(self, "トレンド", "サイクルが不足しています。")
            return
        self._reset_figure_axes()
        self.ax.clear()
        self.ax.set_facecolor("white"); self.ax.tick_params(colors="black")
        self.ax.plot(cm["cycle_time"], cm["freq"], "-o", ms=3, color="#1f77b4")
        self.ax.set_xlabel("時間 [s]"); self.ax.set_ylabel("周波数 [Hz]")
        self.ax.set_title(f"周波数トレンド（サイクルごと）: {label}")
        self.ax.grid(True, alpha=0.3)
        try:
            self.fig.tight_layout()
        except Exception:
            pass
        self.canvas.draw()
        self._has_drawn = False
        self._set_status(f"トレンド表示: {label}")

    def show_phase(self):
        import numpy as np
        t1, y1, l1 = self._analysis_xy()
        t2, y2 = self._xy_by_disp(self.phase_target2.currentText())
        if t1 is None or t2 is None:
            QtWidgets.QMessageBox.information(self, "情報", "解析対象と対象2を選択してください。")
            return
        delay, phase = phase_delay(t1, np.asarray(y1, float), np.asarray(y2, float))
        if delay is None:
            QtWidgets.QMessageBox.warning(self, "位相差", "計算できませんでした。")
            return
        ph = "-" if phase is None else f"{phase:.1f}°"
        msg = f"位相差/遅延（{l1} vs {self.phase_target2.currentText()}）: 遅延={format_eng(delay)}s  位相={ph}"
        self.adv_result.setText(msg); self._set_status(msg)

    def _on_proto_change(self, proto):
        cfg = {
            "UART": (["信号線", "", ""], "ボーレート", "115200"),
            "I2C": (["SCL", "SDA", ""], "不使用", ""),
            "SPI": (["SCK", "MOSI", "CS(任意)"], "不使用", ""),
        }[proto]
        labels, baud_lbl, baud_val = cfg
        for i in range(3):
            show = labels[i] != ""
            self.proto_ch_labels[i].setText(labels[i]); self.proto_ch_labels[i].setVisible(show)
            self.proto_ch[i].setVisible(show)
        self.proto_baud.setEnabled(proto == "UART")
        if baud_val:
            self.proto_baud.setText(baud_val)

    def decode_protocol(self):
        import numpy as np
        proto = self.proto_combo.currentText()
        t1, y1 = self._xy_by_disp(self.proto_ch[0].currentText())
        if t1 is None:
            QtWidgets.QMessageBox.information(self, "情報", "Ch1（信号線）をデータタブで選択してください。")
            return
        try:
            if proto == "UART":
                baud = parse_eng(self.proto_baud.text(), 115200)
                ev = decode_uart(t1, np.asarray(y1, float), baud=baud)
                rows = [(e["time"], "data", e["hex"], (e["char"] + ("" if e["ok"] else " ⚠")).strip()) for e in ev]
            elif proto == "I2C":
                t2, y2 = self._xy_by_disp(self.proto_ch[1].currentText())
                if t2 is None:
                    QtWidgets.QMessageBox.information(self, "情報", "SDA(Ch2)も選択してください。"); return
                ev = decode_i2c(t1, np.asarray(y1, float), np.asarray(y2, float))
                rows = []
                for e in ev:
                    if e["type"] in ("START", "STOP"):
                        rows.append((e["time"], e["type"], "", ""))
                    else:
                        rows.append((e["time"], e["type"], e["hex"],
                                     f"{e.get('rw','')} {e.get('ack','')}".strip()))
            else:  # SPI
                t2, y2 = self._xy_by_disp(self.proto_ch[1].currentText())
                if t2 is None:
                    QtWidgets.QMessageBox.information(self, "情報", "MOSI(Ch2)も選択してください。"); return
                cs = None
                if self.proto_ch[2].currentText():
                    _, cs = self._xy_by_disp(self.proto_ch[2].currentText())
                    cs = np.asarray(cs, float) if cs is not None else None
                ev = decode_spi(t1, np.asarray(y1, float), np.asarray(y2, float), cs=cs)
                rows = [(e["time"], "data", e["hex"], "") for e in ev]
        except Exception as e:  # noqa: BLE001
            QtWidgets.QMessageBox.critical(self, "解読エラー", str(e)); return

        self.proto_table.setRowCount(len(rows))
        for r, (tm, kind, hexv, note) in enumerate(rows):
            self.proto_table.setItem(r, 0, QtWidgets.QTableWidgetItem(f"{tm*1e3:.4g} ms"))
            self.proto_table.setItem(r, 1, QtWidgets.QTableWidgetItem(str(kind)))
            self.proto_table.setItem(r, 2, QtWidgets.QTableWidgetItem(str(hexv)))
            self.proto_table.setItem(r, 3, QtWidgets.QTableWidgetItem(str(note)))
        self._set_status(f"{proto} 解読: {len(rows)} 件")

# ======================================================================
# ↑ graph_app_mixins/advanced_tools.py
# ======================================================================
"""DataSciMixin: 「データサイエンス」タブの解析アクション。

選択中のY系列に対し、線形回帰（線形性）・記述統計・相関・正規性検定などを計算して表で表示する。
実体の計算は datasci モジュール（GUI 非依存）に置き、ここは取得→計算→表示の橋渡しに徹する。
"""


class DataSciMixin:
    # ---- 共通: 解析対象 (t, y) の取得 ----
    def _ds_xy(self):
        """データサイエンスタブの対象コンボから (x, y) を取得。x は現在のX軸列。"""
        disp = self.ds_target.currentText()
        if not disp:
            QtWidgets.QMessageBox.information(self, "情報", "データタブでY系列を選択してください。")
            return None, None, None
        t, y = self._xy_by_disp(disp)   # AdvancedMixin と共用（同一クラスのメソッド）
        if t is None:
            QtWidgets.QMessageBox.information(self, "情報", "対象の数値データが取得できません。")
            return None, None, None
        return disp, t, y

    def _ds_show(self, title, rows):
        """[(項目, 値文字列), ...] を結果テーブルに表示する。各行に「表示」チェックを付ける。"""
        had = bool(getattr(self, "_ds_annotations", None))
        self._ds_annotations = []   # 新しい解析を表示したら前回の注記はリセット
        self.ds_title.setText(title)
        self.ds_table.setRowCount(len(rows))
        for r, (k, v) in enumerate(rows):
            self.ds_table.setItem(r, 0, QtWidgets.QTableWidgetItem(str(k)))
            self.ds_table.setItem(r, 1, QtWidgets.QTableWidgetItem(str(v)))
            cb = QtWidgets.QCheckBox()
            cb.setToolTip("チェックすると、この項目の値をグラフ上に注記表示します。")
            cb.toggled.connect(self._refresh_ds_annotations)
            self.ds_table.setCellWidget(r, 2, cb)
        if had and getattr(self, "_has_drawn", False):
            self.draw_graph()   # 前回の注記を消す

    def _refresh_ds_annotations(self, *_):
        """「表示」にチェックされた行を集めてグラフへ注記表示する。"""
        anns = []
        for r in range(self.ds_table.rowCount()):
            cb = self.ds_table.cellWidget(r, 2)
            if cb is not None and cb.isChecked():
                k = self.ds_table.item(r, 0)
                v = self.ds_table.item(r, 1)
                if k is not None and v is not None:
                    anns.append(f"{k.text()} = {v.text()}")
        self._ds_annotations = anns
        if self.datasets:   # 特殊表示直後でも通常グラフへ再描画して反映
            self.draw_graph()

    @staticmethod
    def _fmt(v):
        if v is None:
            return "—"
        if isinstance(v, bool):
            return "はい" if v else "いいえ"
        if isinstance(v, int):
            return str(v)
        try:
            return f"{float(v):.6g}"
        except (TypeError, ValueError):
            return str(v)

    # ---- 線形回帰（線形性） ----
    def run_regression(self):
        disp, t, y = self._ds_xy()
        if t is None:
            return
        d = linear_regression(t, y)
        if not d:
            QtWidgets.QMessageBox.information(self, "情報", "回帰に十分なデータがありません。")
            return
        f = self._fmt
        rows = [
            ("点数 n", f(d["n"])),
            ("傾き slope", f(d["slope"])),
            ("切片 intercept", f(d["intercept"])),
            ("相関 r (ピアソン)", f(d["r"])),
            ("決定係数 R²", f(d["r2"])),
            ("p値 (傾き=0)", f(d["p_value"])),
            ("傾きの標準誤差", f(d["std_err"])),
            ("RMSE (残差)", f(d["rmse"])),
            ("直線性誤差 [%FS]", f(d["linearity_error_pct"])),
        ]
        sp = correlation(t, y, "spearman")
        if sp:
            rows.append(("相関 (スピアマン)", f(sp["r"])))
        self._ds_show(f"線形回帰: {disp}（Y vs X）", rows)
        if self.ds_fit_check.isChecked():
            # 既存の近似曲線(線形)機能でグラフに直線を重ねる
            self.trend_combo.setCurrentText("線形")
            self.draw_graph()

    # ---- 記述統計 ----
    def show_describe(self):
        disp, t, y = self._ds_xy()
        if t is None:
            return
        d = describe(y)
        if not d:
            QtWidgets.QMessageBox.information(self, "情報", "数値データがありません。")
            return
        f = self._fmt
        order = [
            ("件数", "count"), ("平均", "mean"), ("中央値", "median"),
            ("標準偏差 σ", "std"), ("分散", "var"), ("最小", "min"), ("最大", "max"),
            ("範囲", "range"), ("変動係数 CV", "cv"), ("歪度 skew", "skew"),
            ("尖度 kurtosis", "kurtosis"), ("第1四分位 Q1", "p25"),
            ("中央 Q2", "p50"), ("第3四分位 Q3", "p75"), ("四分位範囲 IQR", "iqr"),
        ]
        self._ds_show(f"記述統計: {disp}", [(lbl, f(d.get(k))) for lbl, k in order])

    # ---- 正規性検定 ----
    def run_normality(self):
        disp, t, y = self._ds_xy()
        if t is None:
            return
        d = normality(y)
        if not d:
            QtWidgets.QMessageBox.information(
                self, "情報", "正規性検定には scipy が必要です（または点数不足）。")
            return
        f = self._fmt
        rows = [
            ("W統計量", f(d["W"])),
            ("p値", f(d["p_value"])),
            ("5%有意で正規とみなせる", f(d["normal_5pct"])),
        ]
        self._ds_show(f"正規性検定 (Shapiro-Wilk): {disp}", rows)

    # ---- 相関行列（選択中の全系列） ----
    def show_corr_matrix(self):
        items = self._selected_series_items()
        if len(items) < 2:
            QtWidgets.QMessageBox.information(
                self, "情報", "相関行列には2系列以上をデータタブで選択してください。")
            return
        named = []
        for fl, col, disp in items:
            t, y = self._xy_by_disp(disp)
            if y is not None:
                named.append((disp, y))
        names, mat = correlation_matrix(named, "pearson")
        if mat is None:
            QtWidgets.QMessageBox.information(self, "情報", "相関行列を計算できませんでした。")
            return
        self._show_corr_window(names, mat)

    def _show_corr_window(self, names, mat):
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("相関行列（ピアソン）")
        dlg.resize(min(120 + 90 * len(names), 900), min(120 + 30 * len(names), 700))
        lay = QtWidgets.QVBoxLayout(dlg)
        n = len(names)
        tbl = QtWidgets.QTableWidget(n, n)
        tbl.setHorizontalHeaderLabels(names)
        tbl.setVerticalHeaderLabels(names)
        for i in range(n):
            for j in range(n):
                v = float(mat[i, j])
                it = QtWidgets.QTableWidgetItem(f"{v:.3f}")
                it.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
                # 相関の強さで色付け（赤=正・青=負）
                a = max(0.0, min(1.0, abs(v)))
                if v >= 0:
                    it.setBackground(QtGui.QColor(255, int(255 * (1 - a)), int(255 * (1 - a))))
                else:
                    it.setBackground(QtGui.QColor(int(255 * (1 - a)), int(255 * (1 - a)), 255))
                tbl.setItem(i, j, it)
        lay.addWidget(tbl)
        btn = QtWidgets.QPushButton("閉じる")
        btn.clicked.connect(dlg.accept)
        lay.addWidget(btn)
        dlg.exec()

# ======================================================================
# ↑ graph_app_mixins/datasci_tools.py
# ======================================================================
"""BatchMixin: GraphApp から分離した BatchMixin 群（挙動は本体と同一）。"""


class BatchMixin:
    # ------------------------------------------------------------ 補助
    def _save_current_figure(self, target, dpi, transparent, fmt=None):
        """現在のグラフを保存。縦横比の指定があれば画像そのものをその比率にする
        （図を比率サイズにして bbox トリミングせず保存）。自動なら従来どおり tight 保存。"""
        ratio = self._aspect_ratio()
        if not ratio:
            self.fig.savefig(target, dpi=dpi, bbox_inches="tight",
                             transparent=transparent, format=fmt)
            return
        orig = self.fig.get_size_inches()
        try:
            self.fig.set_size_inches(self._export_figsize())
            self.ax.set_box_aspect(None)          # 図いっぱいに描く（枠固定を一時解除）
            ax2 = getattr(self.ax, "_twin_secondary", None)
            if ax2 is not None:
                ax2.set_box_aspect(None)
            try:
                self.fig.tight_layout()
            except Exception:
                pass
            self.fig.savefig(target, dpi=dpi, transparent=transparent, format=fmt)
        finally:
            self.fig.set_size_inches(orig)        # 画面表示用に元のサイズへ戻す
            self._apply_aspect()
            try:
                self.fig.tight_layout()
            except Exception:
                pass
            self.canvas.draw_idle()

    def save_figure(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "グラフ画像を保存", os.path.join(self.last_dir, "graph.png"),
            "PNG (*.png);;JPEG (*.jpg);;PDF (*.pdf);;SVG (*.svg);;EPS (*.eps)")
        if not path:
            return
        try:
            dpi = self.dpi_spin.value()
            transparent = self.transparent_check.isChecked()
            self._save_current_figure(path, dpi, transparent)
            self.last_dir = os.path.dirname(path)
            self._set_status(f"保存しました: {path}（{dpi} DPI{'・背景透過' if transparent else ''}）")
        except Exception as e:  # noqa: BLE001
            QtWidgets.QMessageBox.critical(self, "保存エラー", str(e))

    def copy_figure(self):
        """現在のグラフを画像としてクリップボードにコピーする。"""
        import io
        try:
            buf = io.BytesIO()
            self._save_current_figure(buf, self.dpi_spin.value(),
                                      self.transparent_check.isChecked(), fmt="png")
            buf.seek(0)
            img = QtGui.QImage.fromData(buf.getvalue(), "PNG")
            if img.isNull():
                raise RuntimeError("画像の生成に失敗しました。")
            QtWidgets.QApplication.clipboard().setImage(img)
            self._set_status("グラフをクリップボードにコピーしました。")
        except Exception as e:  # noqa: BLE001
            QtWidgets.QMessageBox.critical(self, "コピーエラー", str(e))

    # ------------------------------------------------------------ 一括出力
    @staticmethod
    def _safe_filename(name):
        import re
        return re.sub(r'[\\/:*?"<>|]+', "_", str(name)).strip() or "graph"

    def _build_series_for_file(self, label, x_name, y_names, chart_type, style_by_col):
        """1ファイルから、指定した列名テンプレートで系列を作る（一括出力用）。
        『一番左の列をX軸』ONなら、各ファイルの先頭列を位置でX軸に使う。"""
        df = self.datasets[label]
        series, categories = [], None
        leftmost = self._use_leftmost_x()
        xv = (df.iloc[:, 0].to_numpy() if leftmost
              else (df[x_name].to_numpy() if x_name in df.columns else df.iloc[:, 0].to_numpy()))
        if chart_type in ("棒", "横棒", "積み上げ棒", "円"):
            categories = xv
            for c in y_names:
                series.append({"label": c, "y": df[c].to_numpy(),
                               "style": style_by_col.get(c)})
        elif chart_type in ("折れ線", "散布図"):
            for c in y_names:
                st = style_by_col.get(c) or {}
                errcol = st.get("errcol")
                yerr = df[errcol].to_numpy() if (errcol and errcol in df.columns) else None
                series.append({"label": c, "x": xv, "y": df[c].to_numpy(), "style": st,
                               "axis": st.get("axis", "primary"),
                               "kind": st.get("kind", ""), "yerr": yerr})
        else:  # ヒストグラム / 箱ひげ
            for c in y_names:
                series.append({"label": c, "y": df[c].to_numpy(),
                               "style": style_by_col.get(c)})
        return series, categories

    def _batch_options_dialog(self):
        """一括出力の調整（タイトル・形式・DPI・透過）。OKで dict、キャンセルで None。"""
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("一括画像保存の設定")
        form = QtWidgets.QFormLayout(dlg)
        info = QtWidgets.QLabel("各ファイルを現在のグラフ設定で1枚ずつ保存します。\n"
                                "軸名・凡例・近似曲線・縦横比などは右の書式パネルの値を使います。")
        info.setStyleSheet("color:#666;"); form.addRow(info)
        title_edit = QtWidgets.QLineEdit(self.title_edit.text() or "{name}")
        title_edit.setToolTip("グラフタイトル。{name} はファイル名（拡張子なし）に置き換わります。")
        form.addRow("グラフタイトル", title_edit)
        fmt_combo = QtWidgets.QComboBox(); fmt_combo.addItems(["png", "jpg", "pdf", "svg"])
        form.addRow("出力形式", fmt_combo)
        dpi_spin = QtWidgets.QSpinBox(); dpi_spin.setRange(50, 1200)
        dpi_spin.setSingleStep(50); dpi_spin.setValue(self.dpi_spin.value())
        form.addRow("解像度 DPI", dpi_spin)
        trans = QtWidgets.QCheckBox(); trans.setChecked(self.transparent_check.isChecked())
        form.addRow("背景透過", trans)
        bb = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        bb.button(QtWidgets.QDialogButtonBox.StandardButton.Ok).setText("フォルダを選んで保存...")
        bb.accepted.connect(dlg.accept); bb.rejected.connect(dlg.reject)
        form.addRow(bb)
        if dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return None
        title = title_edit.text().strip() or "{name}"
        return {"title": title, "fmt": fmt_combo.currentText(),
                "dpi": dpi_spin.value(), "transparent": trans.isChecked()}

    def batch_export(self):
        """読み込んだ各ファイルを、現在の設定で個別に描画してファイル名ごとに一括保存する。"""
        if not self.datasets:
            QtWidgets.QMessageBox.information(self, "情報", "先にファイルを追加してください。")
            return
        ctype = self.chart_combo.currentText()
        # テンプレート＝選択中Y系列の「列名」（順序保持・重複除去）とそのスタイル
        y_names, style_by_col = [], {}
        for fl, col, disp in self._selected_series_items():
            if col not in y_names:
                y_names.append(col)
            style_by_col.setdefault(col, self.series_styles.get(self._style_key(fl, col)))
        # Y軸名が空なら主軸の列名から自動生成（画面描画と同じ規則）
        prim_y = [c for c in y_names
                  if (style_by_col.get(c) or {}).get("axis", "primary") != "secondary"]
        auto_ylabel = self.ylabel_edit.text() or self._auto_y_label(prim_y, ctype)
        if not y_names:
            QtWidgets.QMessageBox.information(
                self, "情報",
                "Y軸（値）の系列を1つ以上選んでください。\n"
                "その列名を各ファイルに適用し、ファイルごとに1枚ずつ出力します。")
            return
        x_name = self.x_combo.currentText()
        opts = self._batch_options_dialog()   # タイトル・形式・DPI・透過を調整
        if opts is None:
            return
        out_dir = QtWidgets.QFileDialog.getExistingDirectory(
            self, "一括出力フォルダを選択", self.last_dir)
        if not out_dir:
            return

        dpi = opts["dpi"]
        transparent = opts["transparent"]
        title_tpl = opts["title"]
        ext = opts["fmt"]
        ratio = self._aspect_ratio()
        fmt = self._plot_format_kwargs()   # 共通フォーマット（bins/grid/凡例/対数/近似/ラベル等）
        # 縦横比の指定があれば画像そのものをその比率に（図サイズで決め、bboxトリミングしない）
        if ratio:
            figsize = self._export_figsize()
            tight = False
        else:
            figsize = self.fig.get_size_inches()
            tight = True
        issues = []
        xlim = self._range_pair(self.xmin, self.xmax, "X", issues)
        ylim = self._range_pair(self.ymin, self.ymax, "Y", issues)
        max_points = (DECIMATE_TARGET if (self.decimate_check.isChecked()
                      and ctype in ("折れ線", "散布図")) else 0)

        # ---- 各ファイルのタスク（picklableなdict）を構築。ファイル名の重複解決は
        #      順序依存なのでここで逐次に確定させ、各タスクに最終パスを持たせる ----
        tasks, skipped, used = [], [], set()
        for label, df in self.datasets.items():
            cols = [c for c in y_names if c in df.columns]
            if not cols:
                skipped.append(f"{label}（対象列なし）")
                continue
            try:
                series, categories = self._build_series_for_file(
                    label, x_name, cols, ctype, style_by_col)
            except Exception as e:  # noqa: BLE001
                skipped.append(f"{label}（{e}）")
                continue
            stem = os.path.splitext(label)[0]
            sec_label = " / ".join(s["label"] for s in series
                                   if s.get("axis") == "secondary")
            xlab = self.xlabel_edit.text() or (
                str(df.columns[0]) if self._use_leftmost_x() else x_name)
            base = self._safe_filename(stem)
            name, k = base, 2
            while name in used:
                name = f"{base}_{k}"; k += 1
            used.add(name)
            tasks.append({
                "series": series, "categories": categories, "ctype": ctype,
                "title": title_tpl.replace("{name}", stem),
                "xlabel": xlab, "ylabel": auto_ylabel,
                "xlim": xlim, "ylim": ylim, "sec_label": sec_label,
                "max_points": max_points, "fmt": fmt, "ratio": None,
                "figsize": tuple(figsize), "tight": tight,
                "dpi": dpi, "transparent": transparent,
                "path": os.path.join(out_dir, f"{name}.{ext}"),
                "font_name": getattr(self, "font_name", None),
            })

        import batch_render
        saved = []
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
        try:
            # ファイル数が多いときだけ別プロセス並列（spawn/ピクル/フォント設定の
            # 固定費があるので少数では逆効果）。失敗時は必ず逐次へフォールバックする。
            use_pool = len(tasks) >= BATCH_PARALLEL_THRESHOLD
            if use_pool:
                try:
                    import concurrent.futures as _cf
                    workers = min(8, (os.cpu_count() or 1))
                    with _cf.ProcessPoolExecutor(max_workers=workers) as ex:
                        futs = {ex.submit(render_one, t): t for t in tasks}
                        for fut in _cf.as_completed(futs):
                            try:
                                saved.append(fut.result())
                            except Exception as e:  # noqa: BLE001
                                skipped.append(
                                    f"{os.path.basename(futs[fut]['path'])}（{e}）")
                            QtWidgets.QApplication.processEvents()
                except Exception as e:  # noqa: BLE001  プール作成失敗/壊れ→逐次へ
                    self._set_status(f"並列出力に失敗、逐次に切替: {e}")
                    use_pool = False
                    saved = []        # 部分結果は破棄し、逐次で全件作り直す
            if not use_pool:
                saved, seq_skipped = render_sequential(tasks)
                skipped.extend(seq_skipped)
                QtWidgets.QApplication.processEvents()
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

        self.last_dir = out_dir
        msg = f"一括出力: {len(saved)} 件を保存しました。\n{out_dir}"
        if skipped:
            head = " / ".join(str(s) for s in skipped[:5])
            msg += f"\n\nスキップ {len(skipped)} 件: {head}" + (" ほか" if len(skipped) > 5 else "")
        QtWidgets.QMessageBox.information(self, "一括出力", msg)
        self._set_status(f"一括出力: {len(saved)} 件保存（{out_dir}）")

# ======================================================================
# ↑ graph_app_mixins/batch.py
# ======================================================================
"""PersistenceMixin: GraphApp から分離した PersistenceMixin 群（挙動は本体と同一）。"""


class PersistenceMixin:
    def show_help(self):
        QtWidgets.QMessageBox.information(
            self, "使い方",
            "【基本の流れ】\n"
            "1. 『データ』タブで「ファイル追加」（ドラッグ&ドロップ可）\n"
            "2. X軸の列を選び、Y軸（値）は描きたい系列にチェック（行クリックでON/OFF・全選択ボタンあり）\n"
            "3. 「グラフを描画」(F5)。『リアルタイム更新』ONなら設定変更が即反映\n"
            "4. 右端の『グラフ書式調整』パネルで種別・色・軸範囲・系列スタイルなどを編集\n"
            "5. 波形は『オシロ/解析』タブで「解析実行」「FFT表示」「オシロスコープ表示」\n\n"
            "【出力】右端パネルの画像出力、またはメニュー「ファイル」から保存／コピー\n"
            "【グラフ種別と列】棒/円は1ファイル、折れ線/散布図は複数ファイル重ね描き可")

    def show_about(self):
        QtWidgets.QMessageBox.about(
            self, "バージョン情報",
            "CSV / TSV / 波形 グラフ・解析ツール\n"
            "PySide6 + matplotlib 製\n"
            f"日本語フォント: {self.font_name or '未検出'}")

    # ------------------------------------------------------------ 設定保存
    def _collect_config(self):
        return {
            "files": [self.meta[l]["path"] for l in self.datasets],
            "x_col": self.x_combo.currentText(),
            "x_leftmost": self.xleft_check.isChecked(),
            "selected_y": [[fl, col] for fl, col, _ in self._selected_series_items()],
            "chart_type": self.chart_combo.currentText(),
            "title": self.title_edit.text(),
            "xlabel": self.xlabel_edit.text(), "ylabel": self.ylabel_edit.text(),
            "fonts": self._fonts(),
            "grid": self.grid_check.isChecked(), "legend": self.legend_check.isChecked(),
            "legend_loc": self.legend_loc.currentText(),
            "show_filename": self.show_filename_check.isChecked(),
            "show_ext": self.show_ext_check.isChecked(),
            "frame_width": self.frame_width.value(), "grid_width": self.grid_width.value(),
            "xmin": self.xmin.text(), "xmax": self.xmax.text(),
            "ymin": self.ymin.text(), "ymax": self.ymax.text(),
            "xtick": self.xtick_edit.text(), "ytick": self.ytick_edit.text(),
            "xunit": self.xunit_edit.text(), "yunit": self.yunit_edit.text(),
            "xscale": self.xscale_edit.text(), "yscale": self.yscale_edit.text(),
            "xlog": self.xlog.isChecked(), "ylog": self.ylog.isChecked(),
            "xinvert": self.xinvert_check.isChecked(), "yinvert": self.yinvert_check.isChecked(),
            "bins": self.bins_spin.value(), "pct": self.pct_check.isChecked(),
            "trend": self.trend_combo.currentText(),
            "trend_degree": self.trend_degree.value(),
            "trend_window": self.trend_window.value(),
            "trend_eq": self.trend_eq.isChecked(),
            "trend_color": getattr(self, "trend_color", ""),
            "data_labels": self.data_labels_check.isChecked(),
            "aspect": self.aspect_combo.currentText(),
            "aspect_w": self.aspect_w.value(), "aspect_h": self.aspect_h.value(),
            "bg_color": getattr(self, "bg_color", ""),
            "export_dpi": self.dpi_spin.value(), "transparent": self.transparent_check.isChecked(),
            "recent_files": self.recent_files,
            "styles": self.series_styles,
            "scope": self._scope_dict(),
            "npeaks": self.npeaks.value(),
        }

    def _apply_config(self, cfg, load_files=True):
        prev_suspend = self._suspend_redraw
        self._suspend_redraw = True  # 復元中の連鎖再描画を抑制
        try:
            self._apply_config_inner(cfg, load_files)
        finally:
            self._suspend_redraw = prev_suspend

    def _apply_config_inner(self, cfg, load_files=True):
        rec = cfg.get("recent_files")
        if isinstance(rec, list):
            self.recent_files = [p for p in rec if isinstance(p, str)][:12]
            self._rebuild_recent_menu()
        if load_files:
            for p in cfg.get("files", []):
                if os.path.isfile(p):
                    self._load_file(p)
            self._refresh_columns()
        if cfg.get("x_col"):
            i = self.x_combo.findText(cfg["x_col"])
            if i >= 0:
                self.x_combo.setCurrentIndex(i)
        self.xleft_check.setChecked(bool(cfg.get("x_leftmost", False)))
        self._refresh_columns()
        # Y 選択を復元（安定した (ファイル, 列) 識別子で照合）
        want = set()
        for p in cfg.get("selected_y", []):
            if isinstance(p, (list, tuple)) and len(p) == 2:
                want.add((p[0], p[1]))
        self.y_list.blockSignals(True)
        for i in range(self.y_list.count()):
            it = self.y_list.item(i)
            it.setCheckState(QtCore.Qt.CheckState.Checked if it.data(UserRole) in want
                             else QtCore.Qt.CheckState.Unchecked)
        self.y_list.blockSignals(False)
        self.series_styles.update(cfg.get("styles", {}) or {})
        self.chart_combo.setCurrentText(cfg.get("chart_type", "折れ線"))
        self.title_edit.setText(cfg.get("title", ""))
        self.xlabel_edit.setText(cfg.get("xlabel", "")); self.ylabel_edit.setText(cfg.get("ylabel", ""))
        f = cfg.get("fonts", {})
        self.fs_title.setValue(f.get("title", 12)); self.fs_label.setValue(f.get("label", 10)); self.fs_tick.setValue(f.get("tick", 9))
        self.fs_legend.setValue(f.get("legend", 9)); self.fs_annot.setValue(f.get("annot", 9))
        self.grid_check.setChecked(cfg.get("grid", True)); self.legend_check.setChecked(cfg.get("legend", True))
        self.legend_loc.setCurrentText(cfg.get("legend_loc", "best"))
        self.show_filename_check.setChecked(cfg.get("show_filename", True))
        self.show_ext_check.setChecked(cfg.get("show_ext", True))
        self.frame_width.setValue(cfg.get("frame_width", 0.8))
        self.grid_width.setValue(cfg.get("grid_width", 0.8))
        self.xmin.setText(cfg.get("xmin", "")); self.xmax.setText(cfg.get("xmax", ""))
        self.ymin.setText(cfg.get("ymin", "")); self.ymax.setText(cfg.get("ymax", ""))
        self.xtick_edit.setText(cfg.get("xtick", "")); self.ytick_edit.setText(cfg.get("ytick", ""))
        self.xunit_edit.setText(cfg.get("xunit", "")); self.yunit_edit.setText(cfg.get("yunit", ""))
        self.xscale_edit.setText(cfg.get("xscale", "1")); self.yscale_edit.setText(cfg.get("yscale", "1"))
        self.xlog.setChecked(cfg.get("xlog", False)); self.ylog.setChecked(cfg.get("ylog", False))
        self.xinvert_check.setChecked(cfg.get("xinvert", False)); self.yinvert_check.setChecked(cfg.get("yinvert", False))
        self.bins_spin.setValue(cfg.get("bins", 30)); self.pct_check.setChecked(cfg.get("pct", True))
        self.trend_combo.setCurrentText(cfg.get("trend", "なし"))
        self.trend_degree.setValue(cfg.get("trend_degree", 2))
        self.trend_window.setValue(cfg.get("trend_window", 5))
        self.trend_eq.setChecked(cfg.get("trend_eq", True))
        tc = cfg.get("trend_color", "")
        if tc:
            self.trend_color = tc
            self.trend_color_btn.setText("色: " + tc)
            self.trend_color_btn.setStyleSheet(f"background:{tc};")
        else:
            self._reset_trend_color()
        self.data_labels_check.setChecked(cfg.get("data_labels", False))
        self.aspect_w.setValue(int(cfg.get("aspect_w", 16)))
        self.aspect_h.setValue(int(cfg.get("aspect_h", 9)))
        self.aspect_combo.setCurrentText(cfg.get("aspect", "自動（画面に合わせる）"))
        bgc = cfg.get("bg_color", "")
        if bgc:
            self.bg_color = bgc
            self.bg_btn.setText("背景色: " + bgc)
            self.bg_btn.setStyleSheet(f"background:{bgc};")
        else:
            self._reset_bg_color()
        self.dpi_spin.setValue(cfg.get("export_dpi", 150)); self.transparent_check.setChecked(cfg.get("transparent", False))
        sc = cfg.get("scope", {})
        self.scope_check.setChecked(sc.get("enabled", False))
        self.tdiv.setCurrentText(format_eng(sc.get("t_per_div") or 1e-3) + "s")
        self.vdiv.setCurrentText(format_eng(sc.get("v_per_div") or 0.5))
        self.xpos.setText(str(sc.get("x_pos", 0))); self.ypos.setText(str(sc.get("y_pos", 0)))
        self.xdivs.setValue(sc.get("x_divs", 10)); self.ydivs.setValue(sc.get("y_divs", 8))
        self.npeaks.setValue(cfg.get("npeaks", 5))
        self._rebuild_style_table()
        self._on_chart_type_change()

    def save_config_dialog(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "設定を保存", os.path.join(self.last_dir, "graph_config.json"),
            "JSON (*.json)")
        if not path:
            return
        try:
            save_config(self._collect_config(), path)
            self._set_status(f"設定を保存: {path}")
        except Exception as e:  # noqa: BLE001
            QtWidgets.QMessageBox.critical(self, "保存エラー", str(e))

    def load_config_dialog(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "設定を読み込み", self.last_dir, "JSON (*.json)")
        if not path:
            return
        cfg = load_config(path)
        if not cfg:
            QtWidgets.QMessageBox.warning(self, "読込エラー", "設定を読み込めませんでした。")
            return
        self._apply_config(cfg)
        self.draw_graph()
        self._set_status(f"設定を読み込み: {path}")

    def _try_restore_session(self):
        cfg = load_last_session()
        if not cfg or not cfg.get("files"):
            return False
        try:
            self._apply_config(cfg)
            if self.datasets:
                self.draw_graph()
            self._set_status("前回のセッションを復元しました。")
            return True
        except Exception:
            return False

    # ------------------------------------------------------------ 書式プリセット
    # 「データ/ファイル選択」に依存しない“見た目”だけを名前付きで保存・呼び出す。
    _PRESET_KEYS = ("chart_type", "fonts", "grid", "legend", "legend_loc",
                    "show_filename", "show_ext", "frame_width", "grid_width",
                    "xlog", "ylog", "xinvert", "yinvert", "bins", "pct", "data_labels",
                    "trend", "trend_degree", "trend_window", "trend_eq", "trend_color",
                    "bg_color", "aspect", "aspect_w", "aspect_h")

    def _presets_dir(self):
        d = os.path.join(APP_DIR, "presets")
        try:
            os.makedirs(d, exist_ok=True)
        except OSError:
            pass
        return d

    def _list_presets(self):
        import glob
        return sorted(os.path.splitext(os.path.basename(p))[0]
                      for p in glob.glob(os.path.join(self._presets_dir(), "*.json")))

    def _refresh_preset_combo(self, select=None):
        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()
        self.preset_combo.addItems(self._list_presets())
        if select:
            i = self.preset_combo.findText(select)
            if i >= 0:
                self.preset_combo.setCurrentIndex(i)
        self.preset_combo.blockSignals(False)

    def save_preset(self):
        import json
        name, ok = QtWidgets.QInputDialog.getText(self, "書式プリセット保存", "プリセット名:")
        name = (name or "").strip()
        if not ok or not name:
            return
        data = {k: v for k, v in self._collect_config().items() if k in self._PRESET_KEYS}
        try:
            with open(os.path.join(self._presets_dir(), name + ".json"), "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except OSError as e:  # noqa: BLE001
            QtWidgets.QMessageBox.warning(self, "保存", str(e))
            return
        self._refresh_preset_combo(select=name)
        self._set_status(f"書式プリセット「{name}」を保存しました。")

    def apply_preset(self):
        import json
        name = self.preset_combo.currentText()
        if not name:
            return
        try:
            with open(os.path.join(self._presets_dir(), name + ".json"), encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            QtWidgets.QMessageBox.warning(self, "適用", "プリセットを読み込めませんでした。")
            return
        self._apply_format(data)
        self._set_status(f"書式プリセット「{name}」を適用しました。")

    def delete_preset(self):
        name = self.preset_combo.currentText()
        if not name:
            return
        try:
            os.remove(os.path.join(self._presets_dir(), name + ".json"))
        except OSError:
            pass
        self._refresh_preset_combo()

    def _apply_format(self, d):
        """プリセット（見た目のみ）を現在のウィジェットへ適用。データ選択には触れない。"""
        prev = self._suspend_redraw
        self._suspend_redraw = True
        try:
            if "chart_type" in d:
                self.chart_combo.setCurrentText(d["chart_type"])
            f = d.get("fonts") or {}
            if f:
                self.fs_title.setValue(f.get("title", 12)); self.fs_label.setValue(f.get("label", 10))
                self.fs_tick.setValue(f.get("tick", 9)); self.fs_legend.setValue(f.get("legend", 9))
                self.fs_annot.setValue(f.get("annot", 9))
            for key, widget, kind in (
                    ("grid", self.grid_check, "chk"), ("legend", self.legend_check, "chk"),
                    ("legend_loc", self.legend_loc, "txt"),
                    ("show_filename", self.show_filename_check, "chk"),
                    ("show_ext", self.show_ext_check, "chk"),
                    ("frame_width", self.frame_width, "val"), ("grid_width", self.grid_width, "val"),
                    ("xlog", self.xlog, "chk"), ("ylog", self.ylog, "chk"),
                    ("xinvert", self.xinvert_check, "chk"), ("yinvert", self.yinvert_check, "chk"),
                    ("bins", self.bins_spin, "val"), ("pct", self.pct_check, "chk"),
                    ("data_labels", self.data_labels_check, "chk"),
                    ("trend", self.trend_combo, "txt"), ("trend_degree", self.trend_degree, "val"),
                    ("trend_window", self.trend_window, "val"), ("trend_eq", self.trend_eq, "chk")):
                if key in d:
                    if kind == "chk":
                        widget.setChecked(bool(d[key]))
                    elif kind == "txt":
                        widget.setCurrentText(d[key])
                    else:
                        widget.setValue(d[key])
            tc = d.get("trend_color", "")
            if tc:
                self.trend_color = tc; self.trend_color_btn.setText("色: " + tc)
                self.trend_color_btn.setStyleSheet(f"background:{tc};")
            bgc = d.get("bg_color", "")
            if bgc:
                self.bg_color = bgc; self.bg_btn.setText("背景色: " + bgc)
                self.bg_btn.setStyleSheet(f"background:{bgc};")
            if "aspect" in d:
                self.aspect_w.setValue(int(d.get("aspect_w", 16)))
                self.aspect_h.setValue(int(d.get("aspect_h", 9)))
                self.aspect_combo.setCurrentText(d["aspect"])
        finally:
            self._suspend_redraw = prev
        if self.datasets:
            self.draw_graph()

    # ------------------------------------------------------------ Undo / Redo
    def _snapshot(self):
        """現在の設定を履歴に記録（Undo/Redo 用）。直前と同じなら積まない。"""
        if getattr(self, "_restoring_undo", False):
            return
        import json
        cfg = self._collect_config()
        hist = getattr(self, "_hist", None)
        if hist is None:
            self._hist, self._hist_i = [cfg], 0
            return
        if json.dumps(cfg, ensure_ascii=False, sort_keys=True) == \
                json.dumps(self._hist[self._hist_i], ensure_ascii=False, sort_keys=True):
            return
        del self._hist[self._hist_i + 1:]      # redo 分岐を捨てる
        self._hist.append(cfg)
        if len(self._hist) > 50:               # 上限
            self._hist.pop(0)
        self._hist_i = len(self._hist) - 1

    def _apply_snapshot(self, cfg):
        self._restoring_undo = True
        try:
            self._apply_config(cfg, load_files=False)
            self.draw_graph()
        finally:
            self._restoring_undo = False

    def undo(self):
        hist = getattr(self, "_hist", None)
        if not hist or self._hist_i <= 0:
            self._set_status("これ以上戻せません。")
            return
        self._hist_i -= 1
        self._apply_snapshot(self._hist[self._hist_i])
        self._set_status("元に戻しました。")

    def redo(self):
        hist = getattr(self, "_hist", None)
        if not hist or self._hist_i >= len(hist) - 1:
            self._set_status("これ以上やり直せません。")
            return
        self._hist_i += 1
        self._apply_snapshot(self._hist[self._hist_i])
        self._set_status("やり直しました。")

# ======================================================================
# ↑ graph_app_mixins/persistence.py
# ======================================================================
"""CSV / TSV / 波形データ グラフ・解析ツール（PySide6 / Qt）。

使い方:
    python graph_app.py

機能:
    - 複数の CSV/TSV/波形ファイルをまとめて読み込み、系列を重ねて描画
    - 文字コード・区切りの自動判定（手動指定も可）
    - 8種のグラフ＋系列ごとの色/線種/線幅/マーカー、軸範囲/対数軸/凡例位置
    - Excel相当のグラフ編集：近似曲線（線形/多項式/指数/対数/移動平均＋R²）、
      データラベル、第2軸・複合グラフ（系列ごと主/第2軸＋線/棒/面の混在）、エラーバー
    - データのセル編集（表を直接編集→DataFrameへ反映、行/列追加・削除、CSV保存）
    - オシロスコープ表示（time/div・V/div・位置・divグリッド）
    - オシロ相当の解析（第1/第2…ピーク検出、各種測定、FFT）
    - 設定の保存／読み込み（終了時自動保存・起動時復元）

GUI は matplotlib の qt_compat 経由で実装しており、PySide6 / PyQt6（Qt6系）で動作する。
"""



class GraphApp(UIBuildMixin, DataIOMixin, StyleTableMixin, PlotMixin,
               ScopeCursorMixin, AnalysisMixin, AdvancedMixin, DataSciMixin,
               BatchMixin, PersistenceMixin, QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.datasets = {}      # label -> DataFrame
        self.meta = {}          # label -> {"path","enc","delim"}
        self.series_styles = {} # "file\tcol" -> style dict（label 上書きも保持）
        self.last_dir = os.path.expanduser("~")

        self._suspend_redraw = True   # 構築・設定適用中は自動再描画を抑制
        self._has_drawn = False       # 一度でも描画したか（リアルタイム更新の発火条件）

        self.font_name = setup_japanese_font()
        get_logger().info("GraphApp 起動（フォント: %s）", self.font_name or "未検出")
        self.setWindowTitle("CSV / TSV / 波形 グラフ・解析ツール")
        self.resize(1280, 800)
        self.setAcceptDrops(True)     # Explorer からのドラッグ&ドロップ読み込み

        # 変更を少し待ってからまとめて再描画するデバウンスタイマー
        self._redraw_timer = QtCore.QTimer(self)
        self._redraw_timer.setSingleShot(True)
        self._redraw_timer.timeout.connect(self._do_live_redraw)

        # ズーム時に表示範囲を再サンプルするための状態
        self._dyn = []            # [(line, full_x, full_y, max_points), ...]
        self._dyn_cid = None
        self._resampling = False
        self._resample_timer = QtCore.QTimer(self)
        self._resample_timer.setSingleShot(True)
        self._resample_timer.timeout.connect(self._do_resample)
        self.recent_files = []    # 最近使ったファイル（MRU）

        # カーソル測定の状態
        self._cursor_cid = None
        self._cursor_pts = []
        self._cursor_artists = []
        self._cursors = []          # [{x, vline, marker}] ドラッグ微調整対応
        self._cursor_drag = None
        self._cursor_text = None

        self._build_menu()
        self._build_central()
        self._build_statusbar()
        self._on_chart_type_change()

        restored = self._try_restore_session()
        if not restored:
            self._set_status("『データ』タブで「ファイル追加」、またはCSV/TSVファイルをドラッグ&ドロップして読み込んでください。")
        self._suspend_redraw = False  # 構築完了。以降は変更で自動再描画

    def closeEvent(self, event):
        try:
            save_last_session(self._collect_config())
        except Exception:
            get_logger().exception("終了時の設定保存に失敗")
        get_logger().info("GraphApp 終了")
        super().closeEvent(event)




def main():
    setup_logging()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

    def _notify(text):
        try:
            QtWidgets.QMessageBox.critical(None, "予期しないエラー",
                                           f"{text}\n\n詳細は app.log を確認してください:\n{LOG_FILE}")
        except Exception:  # noqa: BLE001
            pass

    install_excepthook(on_error=_notify)   # 未捕捉例外もログ＋通知（無言終了の防止）
    try:
        win = GraphApp()
        win.show()
        sys.exit(app.exec())
    except Exception:
        get_logger().exception("起動に失敗")
        raise


if __name__ == "__main__":
    main()

# ======================================================================
# ↑ graph_app.py
# ======================================================================
