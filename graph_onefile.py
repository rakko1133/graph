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
import warnings
import numpy as np
import warnings
import pandas as pd
import importlib.util as _ilu
import ast as _ast
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg
import re
import string
from matplotlib.backends.qt_compat import QtCore, QtGui, QtWidgets
from matplotlib.backends.backend_qtagg import ( FigureCanvasQTAgg as FigureCanvas, NavigationToolbar2QT as NavigationToolbar, )
"""アプリのロギング設定（Qt 非依存）。
ファイル（~/.csv_graph_tool/app.log・ローテーション付き）とコンソールへ出力し、
未捕捉の例外も記録する。pythonw（コンソール無し）で無言終了しても、原因が
app.log に残るようにするのが目的。
"""
LOG_DIR = os.path.join(os.path.expanduser("~"), ".csv_graph_tool")
LOG_FILE = os.path.join(LOG_DIR, "app.log")
_logger = None
_crash_file = None
class _TolerantRotatingFileHandler(logging.handlers.RotatingFileHandler):
 def doRollover(self):
  try:
   super().doRollover()
  except OSError:
   if self.stream is None:
    self.stream = self._open()
def setup_logging(level=logging.INFO):
 global _logger
 if _logger is not None:
  return _logger
 logger = logging.getLogger("graphtool")
 logger.setLevel(level)
 logger.handlers.clear()
 fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
 try:
  os.makedirs(LOG_DIR, exist_ok=True)
  fh = _TolerantRotatingFileHandler( LOG_FILE, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
  fh.setFormatter(fmt)
  logger.addHandler(fh)
 except OSError:
  pass
 ch = logging.StreamHandler()
 ch.setFormatter(fmt)
 logger.addHandler(ch)
 logger.propagate = False
 try:
  import faulthandler
  global _crash_file
  _crash_file = open(os.path.join(LOG_DIR, "crash.log"), "a", encoding="utf-8")
  _crash_file.write("\n==== 起動 ====\n")
  _crash_file.flush()
  faulthandler.enable(file=_crash_file)
 except OSError:
  pass
 _logger = logger
 return logger
def get_logger():
 return _logger or setup_logging()
def install_excepthook(on_error=None):
 logger = get_logger()
 def _hook(exc_type, exc, tb):
  if issubclass(exc_type, KeyboardInterrupt):
   sys.__excepthook__(exc_type, exc, tb)
   return
  logger.critical("未捕捉の例外", exc_info=(exc_type, exc, tb))
  if on_error is not None:
   try:
    on_error(f"{exc_type.__name__}: {exc}")
   except Exception:
    pass
 sys.excepthook = _hook
"""設定（グラフ・解析・表示状態）の保存と読み込み。
UI の状態を 1 つの dict にまとめ、JSON で保存／読込する。
アプリ終了時の自動保存・起動時の自動復元にも使う。
"""
APP_DIR = os.path.join(os.path.expanduser("~"), ".csv_graph_tool")
LAST_CONFIG = os.path.join(APP_DIR, "last_session.json")
CONFIG_VERSION = 1
def ensure_app_dir():
 os.makedirs(APP_DIR, exist_ok=True)
 return APP_DIR
def save_config(config, path):
 data = dict(config)
 data["_version"] = CONFIG_VERSION
 folder = os.path.dirname(os.path.abspath(path))
 if folder:
  os.makedirs(folder, exist_ok=True)
 with open(path, "w", encoding="utf-8") as f:
  json.dump(data, f, ensure_ascii=False, indent=2)
 return path
def load_config(path):
 try:
  with open(path, "r", encoding="utf-8") as f:
   return json.load(f)
 except (OSError, ValueError):
  return None
def save_last_session(config):
 try:
  ensure_app_dir()
  return save_config(config, LAST_CONFIG)
 except OSError:
  return None
def load_last_session():
 if os.path.isfile(LAST_CONFIG):
  return load_config(LAST_CONFIG)
 return None
"""matplotlib に日本語フォントを設定するユーティリティ。
OS にインストールされている一般的な日本語フォントを優先順に探し、
最初に見つかったものを matplotlib の既定フォントに設定する。
タイトル・軸ラベル・凡例の日本語が文字化け（□□□）しないようにする。
"""
_CANDIDATES = [ "Yu Gothic", "Meiryo", "BIZ UDGothic", "MS Gothic", "MS PGothic", "Yu Mincho", "Hiragino Sans", "Hiragino Kaku Gothic Pro", "Hiragino Maru Gothic Pro", "Noto Sans CJK JP", "IPAexGothic", "IPAGothic", "TakaoGothic", "VL Gothic", ]
def setup_japanese_font(preferred=None):
 installed = {f.name for f in fm.fontManager.ttflist}
 order = []
 if preferred:
  order.append(preferred)
 order.extend(_CANDIDATES)
 for name in order:
  if name in installed:
   matplotlib.rcParams["font.family"] = "sans-serif"
   current = matplotlib.rcParams.get("font.sans-serif", [])
   matplotlib.rcParams["font.sans-serif"] = [name] + [ f for f in current if f != name ]
   matplotlib.rcParams["axes.unicode_minus"] = False
   return name
 matplotlib.rcParams["axes.unicode_minus"] = False
 return None
"""表・波形データファイルの読み込み。
- CSV/TSV/TXT: 文字コード（UTF-8 / BOM付き / CP932 など）と区切り文字を自動判定
- Excel (.xlsx/.xlsm/.xls): シート指定可（既定は先頭シート）
- WAV (.wav): 音声波形を 時間[s]＋ch列 として読む（標準ライブラリのみ）
- LTspice (.raw): 過渡解析のバイナリ/ASCII波形（AC複素・fastaccessは未対応）
- TDMS (.tdms): 要 npTDMS ／ MDF (.mf4/.mdf): 要 asammdf ／ HDF5 (.h5/.hdf5): 要 tables か h5py
  （任意依存。未インストール時は pip コマンド入りの分かりやすいエラーを出す）
"""
_DELIMITERS = [",", "\t", ";", "|"]
DELIMITER_LABELS = { ",": "カンマ ( , )", "\t": "タブ ( \\t )", ";": "セミコロン ( ; )", "|": "パイプ ( | )", }
EXT_GROUPS = ( ("CSV/TSV", (".csv", ".tsv", ".txt")), ("Excel", (".xlsx", ".xls", ".xlsm")), ("波形/計測", (".wav", ".raw", ".tdms", ".mf4", ".mdf", ".h5", ".hdf5")), ("LTspice回路", (".asc", ".net")), )
RUNNABLE_EXTS = (".asc", ".net")
ACCEPT_EXTS = tuple(e for _name, exts in EXT_GROUPS for e in exts)
TABLE_EXTS = tuple(e for e in ACCEPT_EXTS if e not in RUNNABLE_EXTS)
def file_dialog_filter():
 def pat(exts):
  return " ".join("*" + e for e in exts)
 parts = ["データ (" + pat(ACCEPT_EXTS) + ")"]
 parts += [f"{name} ({pat(exts)})" for name, exts in EXT_GROUPS]
 parts.append("すべて (*.*)")
 return ";;".join(parts)
def _japanese_score(text):
 jp = bad = 0
 for ch in text:
  o = ord(ch)
  if (0x3040 <= o <= 0x30FF) or (0x4E00 <= o <= 0x9FFF) or (0xFF00 <= o <= 0xFFEF):
   jp += 1
  elif (0xE000 <= o <= 0xF8FF) or ch == "�":
   bad += 1
 return jp, bad
def detect_encoding(path):
 with open(path, "rb") as f:
  raw = f.read()
 if raw.startswith(b"\xef\xbb\xbf"):
  return "utf-8-sig"
 if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
  return "utf-16"
 try:
  raw.decode("utf-8")
  return "utf-8-sig"
 except UnicodeDecodeError:
  pass
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
 jp_names = {"cp932", "shift-jis", "shift_jis", "sjis", "ms932", "windows-31j", "euc-jp", "euc_jp", "iso-2022-jp"}
 alias = {"shift-jis": "cp932", "shift_jis": "cp932", "sjis": "cp932", "ms932": "cp932", "windows-31j": "cp932", "euc_jp": "euc-jp"}
 try:
  from charset_normalizer import from_bytes
  best = from_bytes(raw).best()
  if best is not None and best.encoding:
   enc = best.encoding.lower().replace("_", "-")
   if enc in jp_names or "jp" in enc or "932" in enc:
    return alias.get(enc, enc)
 except Exception:
  pass
 for enc in ("cp1252", "latin-1"):
  try:
   raw.decode(enc)
   return enc
  except (UnicodeDecodeError, LookupError):
   continue
 return "latin-1"
def detect_delimiter(path, encoding):
 ext = os.path.splitext(path)[1].lower()
 if ext == ".tsv":
  return "\t"
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
 first_line = sample.splitlines()[0] if sample.splitlines() else sample
 counts = {d: first_line.count(d) for d in _DELIMITERS}
 best = max(counts, key=counts.get)
 if counts[best] > 0:
  return best
 return "," if ext == ".csv" else "\t"
def _normalize_columns(df):
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
 try:
  return list(pd.ExcelFile(path).sheet_names)
 except Exception:
  return []
def _load_wav(path):
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
  a -= 128.0
 a = a.reshape(-1, ch)
 cols = {"時間[s]": np.arange(a.shape[0], dtype=float) / fr}
 for i in range(ch):
  cols[f"ch{i + 1}"] = a[:, i]
 return pd.DataFrame(cols)
def _load_ltspice_raw(path):
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
  if "double" in flags:
   arr = np.frombuffer(data[body:body + 8 * nvars * npts], dtype="<f8")
   table = arr.reshape(npts, nvars)
  else:
   rec = np.dtype([("t", "<f8")] + [(f"v{i}", "<f4") for i in range(1, nvars)])
   arr = np.frombuffer(data[body:body + rec.itemsize * npts], dtype=rec)
   table = np.column_stack([arr["t"]] + [arr[f"v{i}"] for i in range(1, nvars)])
 else:
  text = data[body:].decode(enc, errors="replace")
  vals = [float(tok) for tok in text.split() if _is_float(tok)]
  table = np.array(vals, dtype=float).reshape(npts, nvars + 1)[:, 1:]
 table[:, 0] = np.abs(table[:, 0])
 return pd.DataFrame({names[i]: table[:, i] for i in range(nvars)})
def _is_float(tok):
 try:
  float(tok)
  return True
 except ValueError:
  return False
def _load_tdms(path):
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
   try:
    if "時間[s]" not in cols:
     cols["時間[s]"] = chan.time_track()
   except (KeyError, ValueError):
    pass
   cols[name] = chan[:]
 if not cols:
  raise ValueError("TDMS内にチャンネルが見つかりません。")
 return pd.DataFrame({k: pd.Series(v) for k, v in cols.items()})
def _load_mdf(path):
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
  raise ValueError("HDF5 の読み込みには tables または h5py が必要です" "（pip install h5py）。") from e
 cols = {}
 with h5py.File(path, "r") as f:
  def visit(name, obj):
   if not isinstance(obj, h5py.Dataset) or obj.dtype.kind not in "fiu":
    return
   short = name.split("/")[-1]
   key = short if short not in cols else name
   if obj.ndim == 1:
    cols[key] = obj[...]
   elif obj.ndim == 2 and obj.shape[1] <= 64:
    arr = obj[...]
    for j in range(arr.shape[1]):
     cols[f"{key}[{j}]"] = arr[:, j]
  f.visititems(visit)
 if not cols:
  raise ValueError("HDF5 内に数値データセット（1D/2D）が見つかりません。")
 return pd.DataFrame({k: pd.Series(v) for k, v in cols.items()})
def load_table(path, encoding=None, delimiter=None, sheet=None):
 if not os.path.isfile(path):
  raise FileNotFoundError(f"ファイルが見つかりません: {path}")
 ext = os.path.splitext(path)[1].lower()
 if ext in (".xlsx", ".xlsm", ".xls"):
  try:
   df = pd.read_excel(path, sheet_name=sheet if sheet is not None else 0)
  except ImportError as e:
   if ext == ".xls":
    raise ValueError('.xls の読み込みには xlrd が必要です' '（pip install "xlrd>=2.0.1"）。') from e
   raise ValueError("Excel(.xlsx) の読み込みには openpyxl が必要です" "（pip install openpyxl）。") from e
  if df.shape[1] == 0:
   raise ValueError("シートから列を読み取れませんでした。")
  return _normalize_columns(df), "excel", "excel"
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
 use_c = bool(delimiter) and len(delimiter) == 1
 base_kwargs = dict(sep=delimiter, skip_blank_lines=True)
 def _read(**extra):
  if use_c:
   try:
    return pd.read_csv(path, engine="c", **base_kwargs, **extra)
   except (pd.errors.ParserError, ValueError):
    pass
  return pd.read_csv(path, engine="python", **base_kwargs, **extra)
 try:
  df = _read(encoding=encoding)
 except UnicodeDecodeError:
  df = _read(encoding=encoding, encoding_errors="replace")
 except pd.errors.EmptyDataError:
  raise ValueError("ファイルが空か、データ行がありません。")
 if df.shape[1] == 0:
  raise ValueError("列を読み取れませんでした。区切り文字を確認してください。")
 return _normalize_columns(df), encoding, delimiter
def numeric_columns(df):
 cols = []
 for c in df.columns:
  s = pd.to_numeric(df[c], errors="coerce")
  if s.notna().mean() >= 0.8:
   cols.append(c)
 return cols
"""SI接頭辞つき数値フォーマット（format_eng / parse_eng / eng_125_sequence）。"""
def _eng(x):
 if x == 0:
  return "0"
 units = [(1e-12, "p"), (1e-9, "n"), (1e-6, "µ"), (1e-3, "m"), (1, ""), (1e3, "k"), (1e6, "M"), (1e9, "G")]
 for factor, suf in units:
  if abs(x) < factor * 1000:
   return f"{x / factor:.3g}{suf}"
 return f"{x:.3g}"
format_eng = _eng
_ENG_MULT = {"p": 1e-12, "n": 1e-9, "u": 1e-6, "µ": 1e-6, "m": 1e-3, "k": 1e3, "M": 1e6, "G": 1e9}
def parse_eng(text, default=None):
 s = (text or "").strip()
 if not s:
  return default
 try:
  return float(s)
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
 for ch in m.group(2):
  if ch in _ENG_MULT:
   return num * _ENG_MULT[ch]
 return num
def is_dark_bg(color, threshold=0.5):
 try:
  from matplotlib.colors import to_rgb
  r, g, b = to_rgb(color)
 except Exception:
  return True
 return (0.299 * r + 0.587 * g + 0.114 * b) < threshold
def eng_125_sequence(lo, hi, suffix=""):
 seq, dec = [], -12
 while 10.0 ** dec <= hi * 1.0001:
  for m in (1, 2, 5):
   v = m * 10.0 ** dec
   if lo * 0.9999 <= v <= hi * 1.0001:
    seq.append(format_eng(v) + suffix)
  dec += 1
 return seq
"""低レベル描画（各グラフ種別の _draw_*・近似曲線・間引き・オシロ格子）。"""
DEFAULT_STYLE = { "color": None, "linestyle": "-", "linewidth": 1.5, "marker": "", "markersize": 4.0, "alpha": 1.0, }
def style_for(series):
 s = dict(DEFAULT_STYLE)
 s.update(series.get("style") or {})
 return s
def _coerce_x(values):
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
  elif kind == "指数":
   pos = y > 0
   if pos.sum() < 2:
    return None
   c = np.polyfit(x[pos], np.log(y[pos]), 1)
   a, b = float(np.exp(c[1])), float(c[0])
   try:
    from scipy.optimize import curve_fit
    (a, b), _ = curve_fit(lambda xx, A, B: A * np.exp(B * xx), x, y, p0=(a, b), maxfev=10000)
    a, b = float(a), float(b)
   except Exception:
    pass
   yf = a * np.exp(b * x)
   eq = f"y={a:.4g}·e^({b:.4g}x)"
  elif kind == "対数":
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
   else:
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
 xx = np.asarray(xx, dtype=float)
 yy = np.asarray(yy, dtype=float)
 n = len(yy)
 step = max(1, int(np.ceil(n / cap)))
 for i in range(0, n, step):
  if not (np.isfinite(xx[i]) and np.isfinite(yy[i])):
   continue
  ax.annotate(fmt.format(yy[i]), (xx[i], yy[i]), textcoords="offset points", xytext=(0, 5), ha="center", fontsize=max(7, fontsize - 1), color=color or "#333")
def _remove_twin(ax):
 ax2 = getattr(ax, "_twin_secondary", None)
 if ax2 is not None:
  try:
   ax2.remove()
  except Exception:
   pass
 ax._twin_secondary = None
def _remove_aux_axes(ax):
 fig = getattr(ax, "figure", None)
 if fig is None:
  return
 for a in list(fig.axes):
  if a is not ax and getattr(a, "_plotter_aux", False):
   try:
    a.remove()
   except Exception:
    pass
def _add_colorbar(ax, mappable, label=""):
 fig = getattr(ax, "figure", None)
 if fig is None:
  return
 try:
  cb = fig.colorbar(mappable, ax=ax, label=label)
  cb.ax._plotter_aux = True
 except Exception:
  pass
def _bar_width(xx):
 xx = np.asarray(xx, dtype=float)
 xx = xx[np.isfinite(xx)]
 if len(xx) < 2:
  return 0.8
 d = np.diff(np.sort(xx))
 d = d[d > 0]
 return float(np.min(d) * 0.8) if len(d) else 0.8
def _draw_xy(ax, series, line=True, max_points=0, ax2=None, data_labels=False, trendline=None, fonts=None, default_skind=None):
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
 bar_series = [sr for *_unused, sr in prepared if (sr.get("kind") or "") == "bar"]
 n_bars = max(1, len(bar_series))
 bar_idx = 0
 any_decimated = False
 for kind, x, y, sr in prepared:
  st = style_for(sr)
  target = ax2 if (ax2 is not None and sr.get("axis") == "secondary") else ax
  skind = sr.get("kind") or default_skind or ("line" if line else "scatter")
  yerr = sr.get("yerr")
  yerr = _num(yerr) if yerr is not None else None
  if kind == "index":
   xx = np.arange(len(y))
  elif kind == "category":
   xx = np.array([cat_pos[lab] for lab in x], dtype=float)
  else:
   xx = np.asarray(x, dtype=float)
  xx_full = xx
  decim = (max_points and kind != "category" and yerr is None and skind in ("line", "scatter", "step") and len(y) > max_points)
  if decim:
   if skind in ("line", "step"):
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
   target.bar(np.asarray(xx, float) + off, yv, width=w, label=sr["label"], color=st["color"], alpha=min(st["alpha"], 0.85), yerr=yerr if yerr is not None else None, capsize=3)
  elif skind == "area":
   target.fill_between(xx, yv, color=st["color"], alpha=min(st["alpha"], 0.4))
   target.plot(xx, yv, label=sr["label"], color=st["color"], linewidth=st["linewidth"], alpha=st["alpha"])
  elif skind == "step":
   target.step(xx, yv, where="post", label=sr["label"], color=st["color"], linestyle=st["linestyle"], linewidth=st["linewidth"], marker=st["marker"], markersize=st["markersize"], alpha=st["alpha"])
  elif skind == "stem":
   order = np.argsort(np.asarray(xx, dtype=float))
   markerline, stemlines, baseline = target.stem( np.asarray(xx, float)[order], np.asarray(yv, float)[order], label=sr["label"])
   col = st["color"]
   if col:
    markerline.set_color(col); stemlines.set_color(col)
   markerline.set_markersize(max(2.0, st["markersize"]))
   markerline.set_alpha(st["alpha"]); stemlines.set_alpha(st["alpha"])
   baseline.set_alpha(min(st["alpha"], 0.5))
  elif skind == "scatter":
   target.scatter(xx, yv, label=sr["label"], color=st["color"], s=st["markersize"] ** 2, marker=st["marker"] or "o", alpha=st["alpha"])
   if yerr is not None:
    target.errorbar(xx, yv, yerr=yerr[:len(yv)], fmt="none", ecolor=st["color"], alpha=st["alpha"], capsize=3)
  else:
   if yerr is not None:
    target.errorbar(xx, yv, yerr=yerr[:len(yv)], label=sr["label"], color=st["color"], linestyle=st["linestyle"], linewidth=st["linewidth"], marker=st["marker"], markersize=st["markersize"], alpha=st["alpha"], capsize=3)
   else:
    target.plot(xx, yv, label=sr["label"], color=st["color"], linestyle=st["linestyle"], linewidth=st["linewidth"], marker=st["marker"], markersize=st["markersize"], alpha=st["alpha"])
  if data_labels:
   _data_labels(target, xx, yv, st["color"], fs)
  if (trendline and trendline.get("type") not in (None, "なし") and kind in ("numeric", "index") and skind != "bar"):
   fit = fit_trendline(xx_full, y, trendline["type"], degree=trendline.get("degree", 2), window=trendline.get("window", 5))
   if fit is not None:
    xf, yf, eq, r2 = fit
    lab = f"{sr['label']} 近似: {eq}"
    if r2 is not None and trendline.get("show_eq"):
     lab += f"  (R²={r2:.4f})"
    elif not trendline.get("show_eq"):
     lab = None
    tcolor = trendline.get("color") or st["color"] or "#444"
    target.plot(xf, yf, color=tcolor, linestyle="--", linewidth=1.3, alpha=0.9, label=lab)
 if any_decimated:
  ax._decimated = True
 if cat_order:
  ax.set_xticks(range(len(cat_order)))
  ax.set_xticklabels(cat_order, rotation=45 if len(cat_order) > 6 else 0, ha="right" if len(cat_order) > 6 else "center")
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
def _draw_bar(ax, series, categories, horizontal=False, stacked=False, data_labels=False, fonts=None):
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
    ax.annotate(f"{v:.3g}", (b.get_width(), b.get_y() + b.get_height() / 2), textcoords="offset points", xytext=(3, 0), va="center", ha="left", fontsize=max(7, fs - 1))
   else:
    ax.annotate(f"{v:.3g}", (b.get_x() + b.get_width() / 2, b.get_height()), textcoords="offset points", xytext=(0, 3), va="bottom", ha="center", fontsize=max(7, fs - 1))
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
  ax.set_xticklabels(labels, rotation=45 if len(labels) > 6 else 0, ha="right" if len(labels) > 6 else "center")
def _draw_pie(ax, sr, categories, pct=False, donut=False):
 labels = np.asarray([str(c) for c in categories])
 values = np.nan_to_num(_num(sr["y"]))
 n = min(len(labels), len(values))
 labels, values = labels[:n], values[:n]
 mask = values > 0
 labels, values = labels[mask], values[mask]
 if len(values) == 0:
  raise ValueError(("ドーナツ" if donut else "円") + "グラフに使える正の数値データがありません。")
 wedgeprops = dict(width=0.42) if donut else None
 ax.pie(values, labels=labels, autopct="%1.1f%%" if pct else None, startangle=90, counterclock=False, wedgeprops=wedgeprops, pctdistance=0.78 if donut else 0.6)
 ax.axis("equal")
def _draw_area(ax, series, max_points=0, ax2=None, data_labels=False, trendline=None, fonts=None):
 _draw_xy(ax, series, line=True, max_points=max_points, ax2=ax2, data_labels=data_labels, trendline=trendline, fonts=fonts, default_skind="area")
def _prep_xy_numeric(sr, need_x=True):
 y = _num(sr["y"])
 x_raw = sr.get("x")
 if x_raw is None:
  if need_x:
   raise ValueError("この種別には X 軸の列が必要です。")
  x = np.arange(len(y), dtype=float)
 else:
  x = _num(x_raw)
 m = np.isfinite(x) & np.isfinite(y)
 return x[m], y[m]
def _draw_stack(ax, series):
 prepared = []
 for sr in series:
  y = _num(sr["y"])
  x_raw = sr.get("x")
  if x_raw is None:
   x = np.arange(len(y), dtype=float)
  else:
   x = _num(x_raw)
   if not np.isfinite(x).any():
    x = np.arange(len(y), dtype=float)
  m = np.isfinite(x) & np.isfinite(y)
  if m.sum() >= 1:
   prepared.append((x[m], y[m], sr))
 if not prepared:
  raise ValueError("積み上げ面に使える数値データがありません。")
 gx = np.unique(np.concatenate([p[0] for p in prepared]))
 ys, labels, colors = [], [], []
 for x, y, sr in prepared:
  order = np.argsort(x)
  ys.append(np.interp(gx, x[order], y[order]))
  labels.append(sr["label"]); colors.append(style_for(sr)["color"])
 colors = colors if all(colors) else None
 ax.stackplot(gx, ys, labels=labels, colors=colors, alpha=0.8)
def _draw_violin(ax, series):
 data, labels, colors = [], [], []
 for sr in series:
  y = _num(sr["y"]); y = y[np.isfinite(y)]
  if len(y):
   data.append(y); labels.append(sr["label"])
   colors.append(style_for(sr)["color"])
 if not data:
  raise ValueError("バイオリン図に使える数値データがありません。")
 parts = ax.violinplot(data, showmeans=True, showmedians=True)
 for body, col in zip(parts["bodies"], colors):
  if col:
   body.set_facecolor(col); body.set_alpha(0.55)
 ax.set_xticks(range(1, len(labels) + 1))
 ax.set_xticklabels(labels, rotation=45 if len(labels) > 6 else 0, ha="right" if len(labels) > 6 else "center")
def _draw_hist2d(ax, series, bins):
 x, y = _prep_xy_numeric(series[0], need_x=True)
 if len(x) < 2:
  raise ValueError("2Dヒストグラムに使える数値データが足りません。")
 b = max(2, int(bins))
 h = ax.hist2d(x, y, bins=b, cmap="viridis")
 _add_colorbar(ax, h[3], label="頻度")
def _draw_hexbin(ax, series, bins):
 x, y = _prep_xy_numeric(series[0], need_x=True)
 if len(x) < 2:
  raise ValueError("hexbin に使える数値データが足りません。")
 grid = max(6, int(bins) * 2)
 hb = ax.hexbin(x, y, gridsize=grid, cmap="viridis", mincnt=1)
 _add_colorbar(ax, hb, label="件数")
def _draw_heatmap(ax, series):
 rows, labels = [], []
 for sr in series:
  y = _num(sr["y"])
  rows.append(y); labels.append(sr["label"])
 if not rows:
  raise ValueError("ヒートマップに使える数値データがありません。")
 n = min(len(r) for r in rows)
 if n < 1:
  raise ValueError("ヒートマップに使える数値データが足りません。")
 mat = np.array([np.asarray(r[:n], dtype=float) for r in rows])
 im = ax.imshow(mat, aspect="auto", cmap="viridis", interpolation="nearest")
 ax.set_yticks(range(len(labels)))
 ax.set_yticklabels(labels)
 _add_colorbar(ax, im, label="値")
def _xyz_finite(sr):
 x = _num(sr.get("x")); y = _num(sr["y"]); z = _num(sr.get("z"))
 n = min(len(x), len(y), len(z))
 x, y, z = x[:n], y[:n], z[:n]
 m = np.isfinite(x) & np.isfinite(y) & np.isfinite(z)
 return x[m], y[m], z[m]
def _bar3d_size(v):
 v = np.asarray(v, dtype=float)
 v = v[np.isfinite(v)]
 if len(v) < 2:
  return 0.5
 d = np.diff(np.sort(v)); d = d[d > 0]
 return float(np.min(d) * 0.6) if len(d) else 0.5
def _data_labels_3d(ax, x, y, z, color, fs):
 if len(x) > 60:
  return
 for xi, yi, zi in zip(x, y, z):
  ax.text(xi, yi, zi, f"{zi:.3g}", color=color, fontsize=max(7, fs - 1))
def _draw_3d(ax, series, chart_type, fonts=None, data_labels=False, zlabel=""):
 fonts = fonts or {}
 fs = fonts.get("tick", 9)
 if chart_type == "曲面":
  x, y, z = _xyz_finite(series[0])
  if len(x) < 3:
   raise ValueError("3D曲面には有効な (X, Y, Z) が3点以上必要です。")
  if np.ptp(x) == 0 or np.ptp(y) == 0:
   raise ValueError("3D曲面は X と Y に広がりが必要です（一直線上では作れません）。")
  try:
   surf = ax.plot_trisurf(x, y, z, cmap="viridis", linewidth=0.2, antialiased=True)
  except (RuntimeError, ValueError) as e:
   raise ValueError("3D曲面を作成できませんでした（点が一直線上／不足の可能性）。") from e
  _add_colorbar(ax, surf, label=(zlabel or "Z"))
  return
 for sr in series:
  x, y, z = _xyz_finite(sr)
  if len(x) == 0:
   continue
  st = style_for(sr)
  if chart_type == "散布図":
   ax.scatter(x, y, z, label=sr["label"], color=st["color"], s=st["markersize"] ** 2, marker=st["marker"] or "o", alpha=st["alpha"])
  elif chart_type == "折れ線":
   ax.plot(x, y, z, label=sr["label"], color=st["color"], linestyle=st["linestyle"], linewidth=st["linewidth"], marker=st["marker"], markersize=st["markersize"], alpha=st["alpha"])
  elif chart_type == "棒":
   dx = _bar3d_size(x); dy = _bar3d_size(y)
   ax.bar3d(x - dx / 2, y - dy / 2, np.zeros(len(z)), dx, dy, z, color=st["color"], alpha=min(st["alpha"], 0.85), shade=True, label=sr["label"])
  if data_labels:
   _data_labels_3d(ax, x, y, z, st["color"], fs)
def _apply_scope(ax, scope, bg_color=""):
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
 dark = is_dark_bg(bg)
 ax.grid(True, which="major", color=("#888" if dark else "#aaa"), linestyle="-", linewidth=0.6, alpha=0.5)
 ax.set_facecolor(bg)
 ax.tick_params(colors=("#888" if dark else "#555"), labelsize=8)
 info_fg = "#7CFC00" if dark else "#0a7a30"
 info_bg = "black" if dark else "white"
 ax.text(0.01, 0.99, f"{_eng(tpd)}s/div   {_eng(vpd)}V/div", transform=ax.transAxes, va="top", ha="left", color=info_fg, fontsize=9, bbox=dict(facecolor=info_bg, alpha=0.4, edgecolor="none"))
def decimate_minmax(x, y, max_points):
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
 if np.isfinite(Y).all():
  lo = starts + np.argmin(Y, axis=1)
  hi = starts + np.argmax(Y, axis=1)
 else:
  lo = starts + np.argmin(np.where(np.isfinite(Y), Y, np.inf), axis=1)
  hi = starts + np.argmax(np.where(np.isfinite(Y), Y, -np.inf), axis=1)
 if main < n:
  base = int(starts[-1])
  seg = y[base:n]
  fin = np.isfinite(seg)
  lo[-1] = base + int(np.argmin(np.where(fin, seg, np.inf)))
  hi[-1] = base + int(np.argmax(np.where(fin, seg, -np.inf)))
 first = np.minimum(lo, hi)
 second = np.maximum(lo, hi)
 idx = np.empty(2 * n_bins, dtype=np.int64)
 idx[0::2] = first
 idx[1::2] = second
 return x[idx], y[idx]
"""グラフ描画ロジック（系列ベース）。
複数ファイル由来の系列をまとめて描画でき、系列ごとに色・線種・線幅・マーカーを
指定できる。軸範囲・対数軸・凡例位置などの編集にも対応。さらにオシロスコープ風の
div グリッド表示（time/div・V/div・位置オフセット）をサポートする。
GUI から独立しているので単体でも利用・テストできる。
"""
CHART_TYPES = [ "折れ線", "面", "積み上げ面", "ステップ", "ステム", "棒", "横棒", "積み上げ棒", "散布図", "ヒストグラム", "2Dヒストグラム", "hexbin", "箱ひげ", "バイオリン", "ヒートマップ", "円", "ドーナツ", "曲面", ]
CHART_INFO = { "折れ線": {"use_x": True, "multi_y": True, "multi_file": True, "dim3": "optional", "hint": "X軸に1列、Y軸に1列以上。複数ファイルの重ね描き可（『3D表示』でZ軸を使う3D線に）"}, "面": {"use_x": True, "multi_y": True, "multi_file": True, "hint": "X軸に1列、Y軸に1列以上を塗り面で重ね描き。複数ファイル可"}, "積み上げ面": {"use_x": True, "multi_y": True, "multi_file": True, "hint": "X軸に1列、Y軸に複数列を積み上げ（共通Xへ補間）。複数ファイル可"}, "ステップ": {"use_x": True, "multi_y": True, "multi_file": True, "hint": "X軸に1列、Y軸に1列以上を階段状に。複数ファイル可"}, "ステム": {"use_x": True, "multi_y": True, "multi_file": True, "hint": "X軸に1列、Y軸に1列以上を棒（幹）＋点で表示。複数ファイル可"}, "棒": {"use_x": True, "multi_y": True, "multi_file": False, "dim3": "optional", "hint": "X軸にカテゴリ列、Y軸に1列以上（単一ファイル）。『3D表示』で(X,Y)にZ高さの3D棒に"}, "横棒": {"use_x": True, "multi_y": True, "multi_file": False, "hint": "X軸にカテゴリ列、Y軸に1列以上（単一ファイル）"}, "積み上げ棒": {"use_x": True, "multi_y": True, "multi_file": False, "hint": "X軸にカテゴリ列、Y軸に2列以上（単一ファイル）"}, "散布図": {"use_x": True, "multi_y": True, "multi_file": True, "dim3": "optional", "hint": "X軸に1列、Y軸に1列以上。複数ファイル可（『3D表示』でZ軸を使う3D散布図に）"}, "ヒストグラム": {"use_x": False, "multi_y": True, "multi_file": True, "hint": "Y軸に値の列を1列以上（分布を表示）。複数ファイル可"}, "2Dヒストグラム": {"use_x": True, "multi_y": False, "multi_file": False, "hint": "X軸・Y軸に数値列を1つずつ（2次元の頻度を色で表示）"}, "hexbin": {"use_x": True, "multi_y": False, "multi_file": False, "hint": "X軸・Y軸に数値列を1つずつ（六角ビンで密度を表示）"}, "箱ひげ": {"use_x": False, "multi_y": True, "multi_file": True, "hint": "Y軸に値の列を1列以上。複数ファイル可"}, "バイオリン": {"use_x": False, "multi_y": True, "multi_file": True, "hint": "Y軸に値の列を1列以上（分布の密度を表示）。複数ファイル可"}, "ヒートマップ": {"use_x": False, "multi_y": True, "multi_file": True, "hint": "選んだ各Y列を1行として濃淡で表示。複数ファイル可"}, "円": {"use_x": True, "multi_y": False, "multi_file": False, "hint": "X軸にラベル列、Y軸に値の列を1つ（単一ファイル）"}, "ドーナツ": {"use_x": True, "multi_y": False, "multi_file": False, "hint": "X軸にラベル列、Y軸に値の列を1つ（中央が空いた円）"}, "曲面": {"use_x": True, "multi_y": False, "multi_file": False, "dim3": "always", "hint": "X軸・Y軸・Z軸に1列ずつ（散らばった点から曲面を生成・常に3D。ドラッグで回転）"}, }
_PIE_TYPES = ("円", "ドーナツ")
_XY_TYPES = ("折れ線", "散布図", "面", "ステップ", "ステム")
_XY_DEFAULT_KIND = {"折れ線": "line", "散布図": "scatter", "面": "area", "ステップ": "step", "ステム": "stem"}
_SCOPE_TYPES = ("折れ線", "散布図")
_SWAP_TYPES = ("折れ線", "散布図", "面", "積み上げ面", "ステップ", "ステム", "2Dヒストグラム", "hexbin")
_OLD_3D_ALIASES = {"3D散布図": "散布図", "3D折れ線": "折れ線", "3D棒": "棒", "3D曲面": "曲面"}
def always_3d(chart_type):
 return CHART_INFO.get(chart_type, {}).get("dim3") == "always"
def migrate_chart_type(name):
 if name in _OLD_3D_ALIASES:
  return _OLD_3D_ALIASES[name], True
 return name, None
LINESTYLES = {"実線": "-", "破線": "--", "一点鎖線": "-.", "点線": ":", "なし": "None"}
MARKERS = {"なし": "", "丸": "o", "四角": "s", "三角": "^", "菱形": "D", "× ": "x", "＋": "+", "点": "."}
LEGEND_LOCS = ["best", "upper right", "upper left", "lower left", "lower right", "right", "center left", "center right", "lower center", "upper center", "center"]
TRENDLINES = ["なし", "線形", "多項式", "指数", "対数", "移動平均", "ガウシアン", "ローレンツ", "シグモイド"]
SERIES_KINDS = {"自動": "", "折れ線": "line", "棒": "bar", "面": "area", "散布図": "scatter"}
SERIES_AXES = {"主軸": "primary", "第2軸": "secondary"}
def plot_series( ax, series, chart_type, *, categories=None, bins=10, title="", xlabel="", ylabel="", grid=True, legend=True, legend_loc="best", xlim=None, ylim=None, xlog=False, ylog=False, pct=False, fonts=None, scope=None, markers=None, max_points=0, trendline=None, data_labels=False, secondary_label="", xscale=1.0, yscale=1.0, xunit="", yunit="", bg_color="", grid_width=None, frame_width=None, xinvert=False, yinvert=False, zlabel="", view_init=None, threed=False, swap_xy=False, ):
 info = CHART_INFO.get(chart_type)
 if info is None:
  raise ValueError(f"未知のグラフ種別です: {chart_type}")
 if not series:
  raise ValueError("Y軸（値）の系列を選択してください。")
 fonts = fonts or {}
 if swap_xy and chart_type in _SWAP_TYPES:
  xlabel, ylabel = ylabel, xlabel
  xunit, yunit = yunit, xunit
  xlim, ylim = ylim, xlim
  xlog, ylog = ylog, xlog
  xscale, yscale = yscale, xscale
  xinvert, yinvert = yinvert, xinvert
  swapped = []
  for sr in series:
   if sr.get("x") is not None and sr.get("y") is not None:
    sr = dict(sr)
    sr["x"], sr["y"] = sr["y"], sr["x"]
    sr.pop("yerr", None)
   swapped.append(sr)
  series = swapped
 def _needs(spec):
  return not (spec is None or spec == 1.0 or (isinstance(spec, str) and spec.strip() in ("", "1")))
 if _needs(xscale) or _needs(yscale):
  scaled = []
  for sr in series:
   sr = dict(sr)
   if _needs(xscale) and sr.get("x") is not None:
    sr["x"] = axis_scale(sr["x"], xscale)
   if _needs(yscale) and sr.get("axis") != "secondary" and sr.get("y") is not None:
    yb = np.asarray(sr["y"], dtype=float)
    sr["y"] = axis_scale(yb, yscale)
    if sr.get("yerr") is not None:
     e = np.asarray(sr["yerr"], dtype=float)
     hi = axis_scale(yb + e, yscale)
     lo = axis_scale(yb - e, yscale)
     sr["yerr"] = np.abs(hi - lo) / 2.0
   scaled.append(sr)
  series = scaled
 is3d = bool(threed) or always_3d(chart_type)
 ax.clear()
 _remove_twin(ax)
 _remove_aux_axes(ax)
 if not is3d:
  ax.set_aspect("auto")
 ax.set_facecolor(bg_color or "white")
 ax.tick_params(colors="black")
 ax2 = None
 if is3d:
  _draw_3d(ax, series, chart_type, fonts=fonts, data_labels=data_labels, zlabel=zlabel)
 elif chart_type in _XY_TYPES:
  if chart_type != "積み上げ面" and any((sr.get("axis") == "secondary") for sr in series):
   ax2 = ax.twinx()
   ax._twin_secondary = ax2
   if secondary_label:
    ax2.set_ylabel(secondary_label, fontsize=(fonts or {}).get("label", 10))
  _draw_xy(ax, series, line=(chart_type == "折れ線"), max_points=max_points, ax2=ax2, data_labels=data_labels, trendline=trendline, fonts=fonts, default_skind=_XY_DEFAULT_KIND.get(chart_type))
 elif chart_type == "積み上げ面":
  _draw_stack(ax, series)
 elif chart_type == "ヒストグラム":
  _draw_hist(ax, series, bins)
 elif chart_type == "2Dヒストグラム":
  _draw_hist2d(ax, series, bins)
 elif chart_type == "hexbin":
  _draw_hexbin(ax, series, bins)
 elif chart_type == "箱ひげ":
  _draw_box(ax, series)
 elif chart_type == "バイオリン":
  _draw_violin(ax, series)
 elif chart_type == "ヒートマップ":
  _draw_heatmap(ax, series)
 elif chart_type in ("棒", "横棒", "積み上げ棒"):
  if categories is None:
   raise ValueError("X軸（カテゴリ）の列を選択してください。")
  _draw_bar(ax, series, categories, horizontal=(chart_type == "横棒"), stacked=(chart_type == "積み上げ棒"), data_labels=data_labels, fonts=fonts)
 elif chart_type in _PIE_TYPES:
  if categories is None:
   raise ValueError("X軸（ラベル）の列を選択してください。")
  _draw_pie(ax, series[0], categories, pct=pct, donut=(chart_type == "ドーナツ"))
 if title:
  ax.set_title(title, fontsize=fonts.get("title", 12))
 if chart_type not in _PIE_TYPES:
  xl = (f"{xlabel} [{xunit}]".strip() if xunit else xlabel)
  yl_base = ylabel or ("頻度" if chart_type == "ヒストグラム" else "")
  yl = (f"{yl_base} [{yunit}]".strip() if yunit else yl_base)
  ax.set_xlabel(xl, fontsize=fonts.get("label", 10))
  ax.set_ylabel(yl, fontsize=fonts.get("label", 10))
  ax.tick_params(labelsize=fonts.get("tick", 9))
  if is3d and zlabel:
   ax.set_zlabel(zlabel, fontsize=fonts.get("label", 10))
 if chart_type not in _PIE_TYPES:
  if xlog and not is3d:
   ax.set_xscale("log")
  if ylog and not is3d:
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
 if scope and scope.get("enabled") and chart_type in _SCOPE_TYPES:
  _apply_scope(ax, scope, bg_color=bg_color)
  grid = True
 if legend and chart_type not in _PIE_TYPES:
  handles, labels = ax.get_legend_handles_labels()
  if ax2 is not None:
   h2, l2 = ax2.get_legend_handles_labels()
   handles = handles + h2
   labels = labels + l2
  if handles:
   ax.legend(handles, labels, loc=legend_loc, fontsize=(fonts.get("legend") or fonts.get("tick", 9)))
 if grid and chart_type not in _PIE_TYPES:
  if is3d:
   ax.grid(True)
  else:
   gkw = {} if grid_width is None else {"linewidth": grid_width}
   ax.grid(True, linestyle="--", alpha=0.4, **gkw)
 if frame_width is not None and not is3d:
  for sp in ax.spines.values():
   sp.set_linewidth(frame_width)
   sp.set_visible(frame_width > 0)
  if ax2 is not None:
   for sp in ax2.spines.values():
    sp.set_linewidth(frame_width)
    sp.set_visible(frame_width > 0)
 if markers and not is3d:
  for m in markers:
   ax.plot(m["x"], m["y"], m.get("symbol", "v"), color=m.get("color", "red"), markersize=8)
   if m.get("text"):
    ax.annotate(m["text"], (m["x"], m["y"]), textcoords="offset points", xytext=(0, 8), ha="center", color=m.get("color", "red"), fontsize=fonts.get("tick", 9))
 if is3d and view_init is not None:
  try:
   ax.view_init(elev=view_init[0], azim=view_init[1])
  except Exception:
   pass
 if chart_type not in _PIE_TYPES and not is3d:
  if xinvert and not ax.xaxis_inverted():
   ax.invert_xaxis()
  if yinvert and not ax.yaxis_inverted():
   ax.invert_yaxis()
 return ax
def build_series_from_df(df, chart_type, x_col, y_cols):
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
 else:
  for c in y_cols:
   series.append({"label": c, "y": df[c].to_numpy()})
 return series, categories
def plot(ax, df, chart_type, x_col=None, y_cols=None, *, bins=10, title="", xlabel="", ylabel="", grid=True, legend=True, pct=False):
 info = CHART_INFO.get(chart_type)
 if info is None:
  raise ValueError(f"未知のグラフ種別です: {chart_type}")
 if info["use_x"] and not x_col:
  raise ValueError("X軸の列を選択してください。")
 if not y_cols:
  raise ValueError("Y軸（値）の列を選択してください。")
 series, categories = build_series_from_df(df, chart_type, x_col, y_cols)
 return plot_series(ax, series, chart_type, categories=categories, bins=bins, title=title, xlabel=xlabel or (x_col or ""), ylabel=ylabel, grid=grid, legend=legend, pct=pct)
"""解析の共通プリミティブ（窓関数・ピーク検出・ゼロ交差・Top/Base 等）。"""
_trapz = getattr(np, "trapezoid", None) or np.trapz
WINDOWS = ["hann", "hamming", "blackman", "blackmanharris", "flattop", "kaiser", "gaussian", "rect"]
def sampling_rate(t):
 t = np.asarray(t, dtype=float)
 if t.size < 2:
  return None
 dt = np.median(np.diff(t))
 return 1.0 / dt if dt > 0 else None
def _simple_peaks(sig, distance=1):
 idx = np.where((sig[1:-1] > sig[:-2]) & (sig[1:-1] >= sig[2:]))[0] + 1
 return idx
def smooth_signal(y, window):
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
def find_signal_peaks(y, t=None, n=5, prominence_frac=0.05, distance=None, mode="max", smooth=0):
 y = np.asarray(y, dtype=float)
 if y.size < 3:
  return []
 if smooth and smooth >= 3:
  y = smooth_signal(y, smooth)
 sig = y if mode == "max" else -y
 span = float(np.nanmax(y) - np.nanmin(y))
 prom = prominence_frac * span if span > 0 else None
 if _HAVE_SCIPY:
  from scipy.signal import find_peaks
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
  peaks.append({ "rank": rank, "index": int(i), "time": float(t[i]) if t is not None else None, "value": float(y[i]), "prominence": float(pr) if pr == pr else None, })
 return peaks
def _zero_crossing_period(t, y):
 t = np.asarray(t, dtype=float)
 yv = np.asarray(y, dtype=float)
 if np.isfinite(yv).sum() < 3:
  return None
 y0 = yv - np.nanmean(yv)
 sign = np.signbit(y0)
 cross = np.where(np.diff(sign.astype(np.int8)) == -1)[0]
 if cross.size < 2:
  return None
 i = cross
 y1, y2 = y0[i], y0[i + 1]
 mask = y2 != y1
 i, y1, y2 = i[mask], y1[mask], y2[mask]
 tc = t[i] + (-y1) * (t[i + 1] - t[i]) / (y2 - y1)
 if tc.size < 2:
  return None
 per = np.diff(tc)
 per = per[per > 0]
 if per.size == 0:
  return None
 period = float(np.median(per))
 return period if period > 0 else None
def _edge_time(t, y, rising=True, lo=0.1, hi=0.9):
 t = np.asarray(t, dtype=float)
 y = np.asarray(y, dtype=float)
 if np.isfinite(y).sum() < 3:
  return None
 top, base = histogram_top_base(y)
 if (top is None or base is None or not np.isfinite(top - base) or (top - base) <= 0):
  base = np.nanpercentile(y, 5)
  top = np.nanpercentile(y, 95)
 span = top - base
 if not np.isfinite(span) or span <= 0:
  return None
 y_lo = base + lo * span
 y_hi = base + hi * span
 fin = np.isfinite(y)
 def up_cross(level):
  below = y < level
  return np.where(below[:-1] & ~below[1:] & fin[:-1] & fin[1:])[0]
 def down_cross(level):
  above = y > level
  return np.where(above[:-1] & ~above[1:] & fin[:-1] & fin[1:])[0]
 if rising:
  lo_idx = up_cross(y_lo)
  if lo_idx.size == 0:
   return None
  i_lo = int(lo_idx[0])
  after = up_cross(y_hi)
  after = after[after > i_lo]
  if after.size == 0:
   return None
  return float(t[int(after[0])] - t[i_lo])
 else:
  hi_idx = down_cross(y_hi)
  if hi_idx.size == 0:
   return None
  i_hi = int(hi_idx[0])
  after = down_cross(y_lo)
  after = after[after > i_hi]
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
  return np.kaiser(n, 14.0)
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
 amp = np.asarray(amp, dtype=float)
 out = np.full(amp.shape, floor_db)
 nz = amp > 0
 out[nz] = 20.0 * np.log10(amp[nz] / ref)
 return np.maximum(out, floor_db)
def histogram_top_base(y, bins=256):
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
 below = np.asarray(y, dtype=float) < level
 up = np.where(below[:-1] & ~below[1:])[0]
 down = np.where(~below[:-1] & below[1:])[0]
 return up, down
def crossing_times(t, y, level, edge="both"):
 t = np.asarray(t, dtype=float)
 y = np.asarray(y, dtype=float)
 up, down = _mid_crossings(t, y, level)
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
  return interp(down)
 return np.sort(np.concatenate([interp(up), interp(down)]))
def mid_level(y, require_span=True):
 top, base = histogram_top_base(y)
 if top is None or base is None:
  return None
 if require_span and top <= base:
  return None
 return (top + base) / 2.0
"""スペクトル系（FFT・スペクトルピーク・THD/SNR/SINAD/ENOB/SFDR・STFT）。"""
def fft_spectrum(t, y, window="hann", detrend=True):
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
 amp = np.abs(spec) / (np.sum(w) / 2.0)
 if amp.size:
  amp[0] *= 0.5
  if n % 2 == 0:
   amp[-1] *= 0.5
 return freqs, amp
def dominant_frequency(t, y):
 freqs, mag = fft_spectrum(t, y)
 if freqs is None or len(freqs) < 2:
  return None
 m = mag[1:]
 if m.size == 0 or not np.isfinite(m).any():
  return None
 if np.nanmax(m) <= 0:
  return None
 return float(freqs[int(np.nanargmax(m)) + 1])
def find_spectral_peaks(t, y, n=5, prominence_frac=0.02):
 freqs, amp = fft_spectrum(t, y)
 if freqs is None:
  return []
 peaks = find_signal_peaks(amp[1:], t=freqs[1:], n=n, prominence_frac=prominence_frac, mode="max")
 out = []
 for p in peaks:
  out.append({ "rank": p["rank"], "frequency": p["time"], "amplitude": p["value"], })
 return out
def spectrum_metrics(t, y, n_harm=6, window="hann", half_bins=3):
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
 k0 = int(np.argmax(power[1:]) + 1)
 f0 = k0 * fs / n
 def band(kc):
  a = max(1, kc - half_bins)
  b = min(power.size, kc + half_bins + 1)
  return a, b
 fa, fb = band(k0)
 p_fund = float(power[fa:fb].sum())
 if p_fund <= 0:
  return {}
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
 total = float(power[1:].sum())
 noise_only = max(total - p_fund - harm_power, 1e-30)
 nd = max(total - p_fund, 1e-30)
 thd = float(np.sqrt(harm_power / p_fund) * 100.0)
 thd_db = float(10 * np.log10(harm_power / p_fund)) if harm_power > 0 else None
 snr = float(10 * np.log10(p_fund / noise_only))
 sinad = float(10 * np.log10(p_fund / nd))
 enob = float((sinad - 1.76) / 6.02)
 spur = power.copy()
 spur[0] = 0
 spur[fa:fb] = 0
 sfdr = float(10 * np.log10(p_fund / spur.max())) if spur.max() > 0 else None
 return {"f0": f0, "THD_pct": thd, "THD_dB": thd_db, "SNR_dB": snr, "SINAD_dB": sinad, "ENOB_bits": enob, "SFDR_dB": sfdr}
def spectrogram(t, y, nperseg=256, window="hann"):
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
 f, tt, Sxx = _spec(y, fs=fs, window=window, nperseg=nperseg, noverlap=nperseg // 2, scaling="spectrum")
 Sxx_db = 10.0 * np.log10(Sxx + 1e-20)
 return f, tt + (t[0] if len(t) else 0.0), Sxx_db
def channel_power(t, y, f_lo=None, f_hi=None, window="hann"):
 freqs, amp = fft_spectrum(t, y, window=window)
 if freqs is None:
  return None
 p = np.asarray(amp, dtype=float) ** 2
 lo = freqs[1] if f_lo is None else f_lo
 hi = freqs[-1] if f_hi is None else f_hi
 band = (freqs >= lo) & (freqs <= hi)
 return float(p[band].sum())
def occupied_bandwidth(t, y, frac=0.99, window="hann"):
 freqs, amp = fft_spectrum(t, y, window=window)
 if freqs is None or freqs.size < 3:
  return None
 p = np.asarray(amp, dtype=float) ** 2
 p[0] = 0.0
 tot = p.sum()
 if tot <= 0:
  return None
 c = np.cumsum(p) / tot
 lo_i = int(np.searchsorted(c, (1.0 - frac) / 2.0))
 hi_i = int(np.searchsorted(c, 1.0 - (1.0 - frac) / 2.0))
 hi_i = min(hi_i, freqs.size - 1)
 return float(freqs[hi_i] - freqs[lo_i])
def harmonic_search(t, y, n_harm=5, window="hann"):
 freqs, amp = fft_spectrum(t, y, window=window)
 if freqs is None or freqs.size < 3:
  return []
 k0 = int(np.argmax(amp[1:]) + 1)
 f0 = float(freqs[k0])
 if f0 <= 0:
  return []
 if not np.isfinite(amp[k0]) or amp[k0] <= 0:
  return []
 out = []
 for h in range(1, n_harm + 1):
  k = int(np.argmin(np.abs(freqs - f0 * h)))
  out.append({"harmonic": h, "frequency": float(freqs[k]), "amplitude": float(amp[k])})
 return out
"""自動測定（Vpp/RMS・立上り・パルス幅・サイクル統計・位相差・一括 analyze）。"""
def measurements(t, y):
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
 pm = pulse_metrics(t, y)
 add("+パルス幅", pm.get("pos_width"), "s")
 add("-パルス幅", pm.get("neg_width"), "s")
 add("+デューティ比", pm.get("pos_duty"), "%")
 add("-デューティ比", pm.get("neg_duty"), "%")
 add("立上りエッジ数", pm.get("rising_edges"), "")
 add("サイクル数", pm.get("cycles"), "")
 ei = edge_intervals(t, y)
 add("立上り→立上り", ei.get("rise_to_rise"), "s")
 add("立下り→立下り", ei.get("fall_to_fall"), "s")
 add("立上り→立下り(High幅)", ei.get("rise_to_fall"), "s")
 add("立下り→立上り(Low幅)", ei.get("fall_to_rise"), "s")
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
 add("中央値 Median", float(np.nanmedian(y)) if has else None, "V")
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
 t = np.asarray(t, dtype=float)
 y = np.asarray(y, dtype=float)
 if t.size < 8:
  return {}
 y0 = y - np.nanmean(y)
 below = y0 < 0
 up = np.where(below[:-1] & ~below[1:])[0]
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
 y = np.asarray(y, dtype=float)
 y = y[np.isfinite(y)]
 if y.size < 4:
  return {}
 hist, _ = np.histogram(y, bins=bins)
 mean = float(y.mean())
 std = float(y.std())
 def within(k):
  return float(np.mean(np.abs(y - mean) <= k * std) * 100.0) if std > 0 else None
 return {"peak_hits": float(hist.max()), "sigma1": within(1), "sigma2": within(2), "sigma3": within(3)}
def cycle_statistics(t, y):
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
 t = np.asarray(t, dtype=float)
 y = np.asarray(y, dtype=float)
 if np.isfinite(y).sum() < 4:
  return {}
 if level is None:
  level = mid_level(y)
  if level is None:
   return {}
 ut = crossing_times(t, y, level, edge="rising")
 dt_ = crossing_times(t, y, level, edge="falling")
 res = {}
 if ut.size >= 2:
  res["rise_to_rise"] = float(np.mean(np.diff(ut)))
 if dt_.size >= 2:
  res["fall_to_fall"] = float(np.mean(np.diff(dt_)))
 rf = [dt_[dt_ > u][0] - u for u in ut if (dt_ > u).any()]
 fr = [ut[ut > d][0] - d for d in dt_ if (ut > d).any()]
 if rf:
  res["rise_to_fall"] = float(np.mean(rf))
 if fr:
  res["fall_to_rise"] = float(np.mean(fr))
 return res
def pulse_metrics(t, y, level=None):
 t = np.asarray(t, dtype=float)
 y = np.asarray(y, dtype=float)
 out = {}
 finite = np.isfinite(y)
 if finite.sum() < 4:
  return out
 if level is None:
  level = mid_level(y)
  if level is None:
   return out
 up, down = _mid_crossings(t, y, level)
 out["rising_edges"] = float(len(up))
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
 t = np.asarray(t, dtype=float)
 y = np.asarray(y, dtype=float)
 y0 = y - np.nanmean(y)
 below = y0 < 0
 up = np.where(below[:-1] & ~below[1:])[0]
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
 v = np.asarray(values, dtype=float)
 v = v[np.isfinite(v)]
 if v.size == 0:
  return {"min": None, "max": None, "mean": None, "std": None, "count": 0}
 return {"min": float(v.min()), "max": float(v.max()), "mean": float(v.mean()), "std": float(v.std()), "count": int(v.size)}
def phase_delay(t, y1, y2):
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
 delay = -lag * dt
 period = _zero_crossing_period(t, a)
 phase = (-delay / period * 360.0) if period else None
 if phase is not None:
  phase = ((phase + 180.0) % 360.0) - 180.0
 return float(delay), (float(phase) if phase is not None else None)
def analyze(t, y, n_peaks=5, smooth=0):
 return { "peaks": find_signal_peaks(y, t=t, n=n_peaks, smooth=smooth), "measurements": measurements(t, y), }
"""高度解析：マスク/リミット合否、アイダイアグラム、ジッタ、シリアルプロトコル解読。
ハイエンドオシロ相当の解析機能を後処理で提供する。プロトコル解読は
UART（1線）、I2C（SCL/SDA）、SPI（SCK/MOSI[/CS]）、
CAN（1線・標準/拡張ID・デスタッフィング・CRC15検証）、
LIN（1線・break/sync/PID/チェックサム検証）、1-Wire（1線・標準速度）に対応。
"""
def auto_threshold(y):
 level = mid_level(y, require_span=False)
 return float(np.nanmean(y)) if level is None else level
def _logic(y, threshold):
 return (np.asarray(y, dtype=float) > threshold).astype(np.int8)
def crossings(t, y, level, edge="both"):
 return crossing_times(t, y, level, edge=edge)
def _level_at(t, logic, time):
 i = int(np.searchsorted(t, time))
 i = min(max(i, 0), len(logic) - 1)
 return int(logic[i])
def mask_test(t, y, upper=None, lower=None):
 t = np.asarray(t, dtype=float)
 y = np.asarray(y, dtype=float)
 viol = np.zeros(y.shape, dtype=bool)
 if upper is not None:
  viol |= y > upper
 if lower is not None:
  viol |= y < lower
 n = int(viol.sum())
 return {"passed": n == 0, "violations": n, "mask": viol, "violation_times": t[viol]}
def eye_diagram(t, y, symbol_period, n_ui=2):
 t = np.asarray(t, dtype=float)
 y = np.asarray(y, dtype=float)
 if symbol_period <= 0:
  return None, None
 span = n_ui * symbol_period
 phase = ((t - t[0]) % span)
 return phase, y
def eye_measurements(t, y, symbol_period):
 t = np.asarray(t, dtype=float)
 y = np.asarray(y, dtype=float)
 ui = float(symbol_period)
 if ui <= 0 or t.size < 8:
  return {}
 phase = ((t - t[0]) % ui) / ui
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
 out = { "eye_amplitude": amp, "level1": mu1, "level0": mu0, "eye_height": (mu1 - 3 * s1) - (mu0 + 3 * s0), "q_factor": (amp / (s1 + s0)) if (s1 + s0) > 0 else None, "snr_db": (20 * np.log10(amp / (s1 + s0))) if (s1 + s0) > 0 and amp > 0 else None, "extinction_ratio_db": (10 * np.log10(mu1 / mu0)) if mu0 > 0 else None, }
 cr = np.asarray(crossings(t, y, (mu1 + mu0) / 2.0, "both"), dtype=float)
 if cr.size >= 4:
  cph = (cr - t[0]) % ui
  cph = np.where(cph > ui / 2, cph - ui, cph)
  out["jitter_pp"] = float(cph.max() - cph.min())
  out["jitter_rms"] = float(np.std(cph))
  out["eye_width"] = float(max(ui - out["jitter_pp"], 0.0))
 return out
def jitter_tie(t, y, threshold=None, edge="rising"):
 t = np.asarray(t, dtype=float)
 y = np.asarray(y, dtype=float)
 if threshold is None:
  threshold = auto_threshold(y)
 cr = crossings(t, y, threshold, edge)
 if len(cr) < 3:
  return {}
 idx = np.arange(len(cr))
 a, b = np.polyfit(idx, cr, 1)
 ideal = a * idx + b
 tie = cr - ideal
 return {"tie": tie, "crossings": cr, "rms": float(np.std(tie)), "pp": float(tie.max() - tie.min()), "period": float(a), "freq": float(1.0 / a) if a else None, "edges": int(len(cr))}
def decode_uart(t, y, baud, threshold=None, bits=8, parity="none", stop_bits=1, idle="high", lsb_first=True):
 t = np.asarray(t, dtype=float)
 y = np.asarray(y, dtype=float)
 if threshold is None:
  threshold = auto_threshold(y)
 logic = _logic(y, threshold)
 if idle == "low":
  logic = 1 - logic
 bit_t = 1.0 / float(baud)
 tend = t[-1]
 results = []
 i = 0
 n = len(t)
 while i < n - 1:
  if logic[i] == 1 and logic[i + 1] == 0:
   start_t = t[i + 1]
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
   ppos = bits
   if parity in ("even", "odd"):
    pb = _level_at(t, logic, start_t + (1.5 + ppos) * bit_t)
    ones = bin(val).count("1") + pb
    if parity == "even" and ones % 2 != 0:
     ok = False
    if parity == "odd" and ones % 2 != 1:
     ok = False
    ppos += 1
   sb = _level_at(t, logic, start_t + (1.5 + ppos) * bit_t)
   if sb != 1:
    ok = False
   ch = chr(val) if 32 <= val < 127 else ""
   results.append({"time": float(start_t), "value": int(val), "hex": f"0x{val:02X}", "char": ch, "ok": bool(ok)})
   adv_t = start_t + (0.5 + ppos + stop_bits) * bit_t
   j = int(np.searchsorted(t, adv_t))
   i = max(j, i + 1)
  else:
   i += 1
 return results
def decode_i2c(t, scl, sda, threshold=None):
 t = np.asarray(t, dtype=float)
 scl = np.asarray(scl, dtype=float)
 sda = np.asarray(sda, dtype=float)
 th = threshold if threshold is not None else auto_threshold( np.concatenate([scl, sda]))
 Lscl = _logic(scl, th)
 Lsda = _logic(sda, th)
 events = []
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
    events.append({"time": float(t[bit_times[0]]), "type": "addr", "value": addr, "hex": f"0x{addr:02X}", "rw": rw, "ack": "ACK" if ack == 0 else "NACK"})
    first_byte = False
   else:
    events.append({"time": float(t[bit_times[0]]), "type": "data", "value": val, "hex": f"0x{val:02X}", "ack": "ACK" if ack == 0 else "NACK"})
  bits, bit_times = [], []
 mi = 0
 for i in scl_rise:
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
 for idx, kind in markers[mi:]:
  flush_byte()
  events.append({"time": float(t[idx]), "type": "START" if kind == "S" else "STOP"})
 return events
def _can_crc15(bits):
 crc = 0
 for b in bits:
  inv = (b & 1) ^ ((crc >> 14) & 1)
  crc = (crc << 1) & 0x7FFF
  if inv:
   crc ^= 0x4599
 return crc
def decode_can(t, y, bitrate, threshold=None, dominant="low"):
 t = np.asarray(t, dtype=float)
 y = np.asarray(y, dtype=float)
 if threshold is None:
  threshold = auto_threshold(y)
 logic = _logic(y, threshold)
 dom = (1 - logic) if dominant == "low" else logic
 bit_t = 1.0 / float(bitrate)
 tend = t[-1]
 n = len(t)
 frames = []
 i = 0
 while i < n - 1:
  if not (dom[i] == 0 and dom[i + 1] == 1):
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
 state = {"k": 0, "run_val": None, "run_len": 0}
 crc_bits = []
 def read_raw():
  bt = sof_t + (state["k"] + 0.5) * bit_t
  state["k"] += 1
  if bt > tend:
   return None
  idx = min(int(np.searchsorted(t, bt)), len(dom) - 1)
  return 0 if dom[idx] else 1
 def next_bit():
  b = read_raw()
  if b is None:
   return None
  if state["run_len"] == 5:
   if b == state["run_val"]:
    return None
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
 state["k"] = 1
 state["run_val"], state["run_len"] = 0, 1
 crc_bits.append(0)
 ident = take(11)
 b1 = take(1)
 ide = take(1)
 if None in (ident, b1, ide):
  return None, sof_t
 if ide:
  id_ext = take(18)
  rtr = take(1)
  take(2)
  if None in (id_ext, rtr):
   return None, sof_t
  full_id = (ident << 18) | id_ext
 else:
  rtr = b1
  take(1)
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
 read_raw()
 read_raw()
 end_t = sof_t + (state["k"] + 10) * bit_t
 frame = {"time": float(sof_t), "id": int(full_id), "ext": bool(ide), "rtr": bool(rtr), "dlc": int(dlc), "data": [int(d) for d in data], "hex": " ".join(f"{d:02X}" for d in data), "crc_ok": bool(crc_calc == crc)}
 return frame, end_t
def decode_lin(t, y, baud=19200, threshold=None):
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
  if low_len < 11 * bit_t:
   i += 1
   continue
  events.append({"time": float(low_start), "type": "BREAK"})
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
   events.append({"time": seg_bytes[k]["time"], "type": "PID", "value": fid, "ok": bool(pid_ok)})
   data = vals[k + 1:-1]
   if data or len(vals) > k + 1:
    csum = vals[-1]
    def _lin_sum(vals0):
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
    events.append({"time": seg_bytes[-1]["time"], "type": "CSUM", "value": csum, "ok": bool(ok)})
  i = max(int(np.searchsorted(t, seg_bytes[-1]["time"] + 10 * bit_t)), j + 1)
 return events
def _lin_read_bytes(t, logic, start_t, bit_t, max_bytes=12):
 out = []
 tend = t[-1]
 cur = start_t
 n = len(t)
 while len(out) < max_bytes:
  i = int(np.searchsorted(t, cur))
  while i < n - 1 and not (logic[i] == 1 and logic[i + 1] == 0):
   i += 1
  if i >= n - 1:
   break
  st = t[i + 1]
  if st - cur > 20 * bit_t and out:
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
def decode_onewire(t, y, threshold=None, time_scale=1.0):
 t = np.asarray(t, dtype=float) * float(time_scale)
 y = np.asarray(y, dtype=float)
 if threshold is None:
  threshold = auto_threshold(y)
 logic = _logic(y, threshold)
 n = len(t)
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
  if width >= 480e-6:
   if bits:
    bits, bit_t0 = [], None
   events.append({"time": float(start), "type": "RESET"})
   last_reset_end = start + width
   continue
  if (last_reset_end is not None and not bits and start - last_reset_end < 500e-6 and width >= 40e-6):
   events.append({"time": float(start), "type": "PRESENCE"})
   last_reset_end = None
   continue
  last_reset_end = None
  bit = 1 if width < 20e-6 else 0
  if not bits:
   bit_t0 = start
  bits.append(bit)
  if len(bits) == 8:
   val = 0
   for k, b in enumerate(bits):
    val |= (b & 1) << k
   events.append({"time": float(bit_t0), "type": "data", "value": int(val)})
   bits, bit_t0 = [], None
 return events
def decode_spi(t, sck, mosi, cs=None, threshold=None, cpol=0, cpha=0, bits=8, msb_first=True):
 t = np.asarray(t, dtype=float)
 sck = np.asarray(sck, dtype=float)
 mosi = np.asarray(mosi, dtype=float)
 th = threshold if threshold is not None else auto_threshold( np.concatenate([sck, mosi]))
 Lsck = _logic(sck, th)
 Lmosi = _logic(mosi, th)
 Lcs = _logic(cs, th) if cs is not None else None
 rising = np.where((Lsck[:-1] == 0) & (Lsck[1:] == 1))[0] + 1
 falling = np.where((Lsck[:-1] == 1) & (Lsck[1:] == 0))[0] + 1
 sample_edges = rising if (cpol == cpha) else falling
 sample_edges = np.sort(sample_edges)
 results = []
 cur, nbits, start_idx = 0, 0, None
 for i in sample_edges:
  if Lcs is not None and Lcs[min(i, len(Lcs) - 1)] == 1:
   cur, nbits, start_idx = 0, 0, None
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
   results.append({"time": float(t[start_idx]), "value": cur, "hex": f"0x{cur:0{(bits + 3) // 4}X}"})
   cur, nbits, start_idx = 0, 0, None
 return results
"""数学チャンネル（波形演算）。
2系列の四則演算（A±B / A×B / A÷B）と、単一系列の積分・微分・絶対値・
二乗・移動平均・ローパスフィルタを計算して新しい波形を作る。
X（時間軸）が異なる場合は B を A の時間軸へ補間して揃える。
"""
_HAVE_SCIPY = _ilu.find_spec("scipy") is not None
BINARY_OPS = ["A+B", "A-B", "A×B", "A÷B"]
_EXPR_FUNCS = { "sin": np.sin, "cos": np.cos, "tan": np.tan, "asin": np.arcsin, "acos": np.arccos, "atan": np.arctan, "atan2": np.arctan2, "sinh": np.sinh, "cosh": np.cosh, "tanh": np.tanh, "exp": np.exp, "log": np.log, "log10": np.log10, "log2": np.log2, "sqrt": np.sqrt, "abs": np.abs, "sign": np.sign, "clip": np.clip, "min": np.minimum, "max": np.maximum, "where": np.where, }
_EXPR_CONSTS = {"pi": np.pi, "e": np.e}
def eval_expr(expr, variables):
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
  if isinstance(n, _ast.Num):
   return n.n
  raise ValueError("この式は評価できません")
 return ev(node)
def axis_scale(x, spec):
 x = np.asarray(x, dtype=float)
 if spec is None:
  return x
 if isinstance(spec, (int, float)):
  return x if spec == 1 else x * float(spec)
 s = str(spec).strip()
 if s in ("", "1"):
  return x
 try:
  return x * float(s)
 except ValueError:
  pass
 m = _ast_re().fullmatch(s)
 if m:
  try:
   return x * (float(m.group(1)) ** float(m.group(2)))
  except (ValueError, OverflowError, ZeroDivisionError):
   return x
 try:
  r = np.asarray(eval_expr(s, {"x": x}), dtype=float)
  return np.where(np.isfinite(r), r, np.nan)
 except Exception:
  return x
def _ast_re():
 import re
 return re.compile(r"([+-]?[\d.]+)\s*\^\s*([+-]?[\d.]+)")
UNARY_OPS = ["積分 ∫A dt", "微分 dA/dt", "絶対値 |A|", "二乗 A²", "移動平均", "ローパス(RC)", "ローパス(Butterworth)", "ハイパス(Butterworth)", "包絡線(Hilbert)", "自己相関"]
def _sorted_xy(x, y):
 x = np.asarray(x, dtype=float)
 y = np.asarray(y, dtype=float)
 order = np.argsort(x)
 return x[order], y[order]
def _resample(xa, xb, yb):
 xa = np.asarray(xa, dtype=float)
 xbs, ybs = _sorted_xy(xb, yb)
 uniq = np.concatenate(([True], np.diff(xbs) > 0))
 xbs, ybs = xbs[uniq], ybs[uniq]
 if xbs.size >= 4:
  try:
   from scipy.interpolate import CubicSpline
   cs = CubicSpline(xbs, ybs, extrapolate=False)
   xc = np.clip(xa, xbs[0], xbs[-1])
   return cs(xc)
  except Exception:
   pass
 return np.interp(xa, xbs, ybs)
def _rc_lowpass(y, alpha):
 if y.size == 0:
  return y.copy()
 if _HAVE_SCIPY:
  try:
   from scipy.signal import lfilter
   zi = [(1.0 - alpha) * float(y[0])]
   r, _ = lfilter([alpha], [1.0, -(1.0 - alpha)], y, zi=zi)
   return np.asarray(r, dtype=float)
  except Exception:
   pass
 r = np.empty_like(y)
 acc = y[0]
 for i in range(y.size):
  acc += alpha * (y[i] - acc)
  r[i] = acc
 return r
def binary(xa, ya, xb, yb, op):
 xa = np.asarray(xa, dtype=float)
 ya = np.asarray(ya, dtype=float)
 yb_i = _resample(xa, xb, yb)
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
  fc = float(param or 1000.0)
  dt = np.median(np.diff(x)) if x.size > 1 else 1.0
  if dt <= 0 or fc <= 0:
   return x, y.copy()
  alpha = dt / (dt + 1.0 / (2 * np.pi * fc))
  return x, _rc_lowpass(y, alpha)
 if op in ("ローパス(Butterworth)", "ハイパス(Butterworth)"):
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
  except Exception:
   alpha = dt / (dt + 1.0 / (2 * np.pi * fc))
   lp = _rc_lowpass(y, alpha)
   return x, (lp if btype == "low" else y - lp)
 if op == "包絡線(Hilbert)":
  try:
   from scipy.signal import hilbert
   return x, np.abs(hilbert(np.nan_to_num(y)))
  except Exception:
   return x, np.abs(y - np.nanmean(y))
 if op == "自己相関":
  a = np.nan_to_num(y - np.nanmean(y))
  try:
   from scipy.signal import correlate
   r = correlate(a, a, mode="full", method="fft")
  except Exception:
   r = np.correlate(a, a, mode="full")
  r = r[r.size // 2:]
  if r.size and r[0] != 0:
   r = r / r[0]
  x0 = float(x[0]) if x.size else 0.0
  return x[:r.size] - x0, r
 raise ValueError(f"未知の演算: {op}")
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
 return { "n": n, "slope": slope, "intercept": intercept, "r": rval, "r2": r2, "p_value": pval, "std_err": stderr, "rmse": rmse, "linearity_error_pct": inl_pct, }
def describe(y):
 y = _clean(y)
 if y.size == 0:
  return {}
 n = int(y.size)
 mean = float(np.mean(y))
 std = float(np.std(y, ddof=1)) if n > 1 else 0.0
 p25, p50, p75 = (float(np.percentile(y, q)) for q in (25, 50, 75))
 d = { "count": n, "mean": mean, "median": float(np.median(y)), "std": std, "var": float(np.var(y, ddof=1)) if n > 1 else 0.0, "min": float(np.min(y)), "max": float(np.max(y)), "range": float(np.max(y) - np.min(y)), "cv": (float(std / mean) if mean != 0 else None), "p25": p25, "p50": p50, "p75": p75, "iqr": p75 - p25, }
 try:
  from scipy import stats
  if std > 0:
   d["skew"] = float(stats.skew(y))
   d["kurtosis"] = float(stats.kurtosis(y))
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
 mat = np.corrcoef(M)
 return names, np.asarray(mat, dtype=float)
def normality(y):
 y = _clean(y)
 if y.size < 3:
  return {}
 try:
  from scipy import stats
  w, p = stats.shapiro(y[:5000])
  return {"W": float(w), "p_value": float(p), "normal_5pct": bool(p > 0.05)}
 except Exception:
  return {}
def fit_custom(x, y, expr, params, p0):
 try:
  from scipy.optimize import curve_fit
 except ImportError:
  return {}
 x, y = _clean_xy(x, y)
 if x.size < len(params) + 2:
  return {}
 def f(xx, *vals):
  env = {"x": xx, "t": xx}
  env.update(dict(zip(params, vals)))
  return np.asarray(eval_expr(expr, env), dtype=float) * np.ones_like(xx)
 popt, pcov = curve_fit(f, x, y, p0=p0, maxfev=20000)
 yfit = f(x, *popt)
 ss_res = float(np.sum((y - yfit) ** 2))
 ss_tot = float(np.sum((y - np.mean(y)) ** 2))
 perr = np.sqrt(np.abs(np.diag(pcov)))
 return {"params": [(nm, float(v), float(e)) for nm, v, e in zip(params, popt, perr)], "r2": (1.0 - ss_res / ss_tot) if ss_tot > 0 else None, "rmse": float(np.sqrt(ss_res / x.size)), "n": int(x.size), "x": x, "yfit": yfit}
def t_test(a, b=None, mu=0.0, paired=False):
 try:
  from scipy import stats
 except ImportError:
  return {}
 a = _clean(a)
 if a.size < 2:
  return {}
 if b is None:
  res = stats.ttest_1samp(a, float(mu))
  mb = None
 else:
  b = _clean(b)
  if b.size < 2:
   return {}
  if paired:
   n = min(a.size, b.size)
   res = stats.ttest_rel(a[:n], b[:n])
   mb = float(np.mean(b[:n]))
  else:
   res = stats.ttest_ind(a, b, equal_var=False)
   mb = float(np.mean(b))
 df = getattr(res, "df", None)
 return {"t": float(res.statistic), "p_value": float(res.pvalue), "df": (float(df) if df is not None else None), "mean_a": float(np.mean(a)), "mean_b": mb, "sig_5pct": bool(res.pvalue < 0.05)}
def anova_oneway(groups):
 try:
  from scipy import stats
 except ImportError:
  return {}
 arrs = [(_clean(g)) for _n, g in groups]
 named = [(str(n), a) for (n, _g), a in zip(groups, arrs) if a.size >= 2]
 if len(named) < 2:
  return {}
 f, p = stats.f_oneway(*[a for _n, a in named])
 return {"F": float(f), "p_value": float(p), "sig_5pct": bool(p < 0.05), "groups": [(n, int(a.size), float(a.mean()), float(a.std(ddof=1))) for n, a in named]}
"""一括出力のワーカー（Qt非依存・別プロセスでも実行可能）。
ProcessPoolExecutor から呼ぶため、ここでは Qt や graph_app を import しない。
matplotlib は Agg バックエンド固定。タスクは完全に picklable な dict 1個で渡す。
"""
_FONT_DONE = False
def _make_ax(fig, threed):
 if threed:
  from mpl_toolkits.mplot3d import Axes3D
  return fig.add_subplot(111, projection="3d")
 return fig.add_subplot(111)
def _apply_ratio(ax, ratio, threed):
 if ratio and not threed:
  ax.set_box_aspect(ratio)
  ax2 = getattr(ax, "_twin_secondary", None)
  if ax2 is not None:
   ax2.set_box_aspect(ratio)
def _ensure_font(font_name):
 global _FONT_DONE
 if not _FONT_DONE:
  try:
   setup_japanese_font(font_name)
  except Exception:
   pass
  _FONT_DONE = True
def render_one(task):
 _ensure_font(task.get("font_name"))
 threed = task.get("threed", False)
 fig = Figure(figsize=task["figsize"], dpi=task["dpi"])
 FigureCanvasAgg(fig)
 ax = _make_ax(fig, threed)
 plot_series( ax, task["series"], task["ctype"], categories=task["categories"], title=task["title"], xlabel=task["xlabel"], ylabel=task["ylabel"], xlim=task["xlim"], ylim=task["ylim"], secondary_label=task["sec_label"], max_points=task["max_points"], zlabel=task.get("zlabel", ""), view_init=task.get("view_init"), threed=threed, **task["fmt"])
 _apply_ratio(ax, task.get("ratio"), threed)
 tight = task.get("tight", True)
 if not tight:
  try:
   fig.tight_layout()
  except Exception:
   pass
 fig.savefig(task["path"], dpi=task["dpi"], bbox_inches=("tight" if tight else None), transparent=task["transparent"])
 return task["path"]
"""GraphApp と各 Mixin が共有する import・定数・補助クラス。"""
PREVIEW_ROWS = 100
UserRole = QtCore.Qt.ItemDataRole.UserRole
DECIMATE_TARGET = 8000
BUSY_ROWS = 200_000
BATCH_PARALLEL_THRESHOLD = 64
ASYNC_LOAD_BYTES = 4_000_000
ASYNC_LOAD_COUNT = 8
SERIES_BAR_MAX = 60
HEAVY_SERIES = 60
MESSAGE_LOG_MAX = 500
NOTIFY_MS = 8000
UI_LEVEL_ORDER = ("基本", "標準", "全部")
class TabPlugin:
 key = ""
 title = ""
 order = 100
 min_level = "全部"
 def build(self, app):
  raise NotImplementedError(f"{type(self).__name__}.build を実装してください")
class _DelegatingTab(TabPlugin):
 def __init__(self, key, title, order, min_level, method):
  self.key, self.title, self.order = key, title, order
  self.min_level, self._method = min_level, method
 def build(self, app):
  return getattr(app, self._method)()
_TAB_REGISTRY = []
def register_tab(plugin):
 _TAB_REGISTRY[:] = [p for p in _TAB_REGISTRY if p.key != plugin.key]
 _TAB_REGISTRY.append(plugin)
 return plugin
def registered_tabs():
 return sorted(_TAB_REGISTRY, key=lambda p: (p.order, p.key))
def _parse_float(text, default=None):
 text = (text or "").strip()
 if text == "":
  return default
 try:
  return float(text)
 except ValueError:
  pass
 m = re.fullmatch(r"([+-]?[\d.]+)\s*\^\s*([+-]?[\d.]+)", text)
 if m:
  try:
   return float(m.group(1)) ** float(m.group(2))
  except (ValueError, OverflowError, ZeroDivisionError):
   return default
 return default
class CheckListWidget(QtWidgets.QListWidget):
 def mousePressEvent(self, event):
  item = self.itemAt(event.position().toPoint())
  if item is not None and (item.flags() & QtCore.Qt.ItemFlag.ItemIsUserCheckable):
   checked = item.checkState() == QtCore.Qt.CheckState.Checked
   item.setCheckState(QtCore.Qt.CheckState.Unchecked if checked else QtCore.Qt.CheckState.Checked)
   event.accept()
   return
  super().mousePressEvent(event)
class LazyColumnCombo(QtWidgets.QComboBox):
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
SERIES_MIME = "application/x-graphapp-series"
class ExplorerTree(QtWidgets.QTreeWidget):
 renameRequested = QtCore.Signal(object)
 deleteRequested = QtCore.Signal()
 def __init__(self, parent=None):
  super().__init__(parent)
  self._press_item = None
  self._press_pos = None
  self._dragged = False
 def keyPressEvent(self, event):
  if event.key() == QtCore.Qt.Key.Key_F2 and self.currentItem() is not None:
   self.renameRequested.emit(self.currentItem())
   event.accept()
   return
  if event.key() == QtCore.Qt.Key.Key_Delete:
   self.deleteRequested.emit()
   event.accept()
   return
  super().keyPressEvent(event)
 def paintEvent(self, event):
  super().paintEvent(event)
  painter = QtGui.QPainter(self.viewport())
  painter.setPen(QtGui.QColor(128, 128, 128, 60))
  ind = max(self.indentation(), 1)
  idx = self.indexAt(QtCore.QPoint(0, 0))
  limit = self.viewport().height()
  while idx.isValid():
   rect = self.visualRect(idx)
   if rect.top() > limit:
    break
   depth, p = 0, idx.parent()
   while p.isValid():
    depth += 1
    p = p.parent()
   for lv in range(depth):
    x = lv * ind + ind // 2
    painter.drawLine(x, rect.top(), x, rect.bottom())
   idx = self.indexBelow(idx)
  painter.end()
 @staticmethod
 def _is_check_leaf(item):
  if item is None:
   return False
  d = item.data(0, QtCore.Qt.ItemDataRole.UserRole)
  return bool(d and d[0] == "col" and item.flags() & QtCore.Qt.ItemFlag.ItemIsUserCheckable)
 @classmethod
 def _drag_payload(cls, item):
  data = item.data(0, QtCore.Qt.ItemDataRole.UserRole)
  if data and data[0] == "col":
   return f"{data[1]}\t{data[2]}"
  rows = []
  if data and data[0] in ("file", "folder"):
   for j in range(item.childCount()):
    sub = cls._drag_payload(item.child(j))
    if sub:
     rows.append(sub)
  return "\n".join(rows)
 def mousePressEvent(self, event):
  if event.button() == QtCore.Qt.MouseButton.LeftButton:
   item = self.itemAt(event.position().toPoint())
   self._press_item = item
   self._press_pos = event.position().toPoint()
   self._dragged = False
   if self._is_check_leaf(item):
    event.accept()
    return
  super().mousePressEvent(event)
 def mouseMoveEvent(self, event):
  if (self._press_item is not None and not self._dragged and event.buttons() & QtCore.Qt.MouseButton.LeftButton and (event.position().toPoint() - self._press_pos).manhattanLength() >= QtWidgets.QApplication.startDragDistance()):
   payload = self._drag_payload(self._press_item)
   if payload:
    self._dragged = True
    drag = QtGui.QDrag(self)
    mime = QtCore.QMimeData()
    mime.setData(SERIES_MIME, payload.encode("utf-8"))
    mime.setText(self._press_item.text(0))
    drag.setMimeData(mime)
    drag.exec(QtCore.Qt.DropAction.CopyAction)
    self._press_item = None
    return
  super().mouseMoveEvent(event)
 def mouseReleaseEvent(self, event):
  item, dragged = self._press_item, self._dragged
  self._press_item = None
  if (event.button() == QtCore.Qt.MouseButton.LeftButton and not dragged and self._is_check_leaf(item) and item is self.itemAt(event.position().toPoint())):
   checked = item.checkState(0) == QtCore.Qt.CheckState.Checked
   item.setCheckState(0, QtCore.Qt.CheckState.Unchecked if checked else QtCore.Qt.CheckState.Checked)
   event.accept()
   return
  super().mouseReleaseEvent(event)
 def mouseDoubleClickEvent(self, event):
  if event.button() == QtCore.Qt.MouseButton.LeftButton:
   item = self.itemAt(event.position().toPoint())
   if self._is_check_leaf(item):
    self.itemDoubleClicked.emit(item, 0)
    event.accept()
    return
  super().mouseDoubleClickEvent(event)
class CollapsibleBox(QtWidgets.QWidget):
 def __init__(self, title, expanded=True, parent=None):
  super().__init__(parent)
  self._btn = QtWidgets.QToolButton()
  self._btn.setText(title)
  self._btn.setCheckable(True)
  self._btn.setChecked(expanded)
  self._btn.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
  self._btn.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed)
  self._btn.setStyleSheet( "QToolButton { border:none; font-weight:bold; text-align:left; padding:2px; }")
  self._btn.toggled.connect(self._on_toggled)
  self.body = QtWidgets.QWidget()
  lay = QtWidgets.QVBoxLayout(self)
  lay.setContentsMargins(0, 2, 0, 2)
  lay.setSpacing(2)
  lay.addWidget(self._btn)
  lay.addWidget(self.body)
  self._on_toggled(expanded)
 def _on_toggled(self, on):
  self._btn.setArrowType(QtCore.Qt.ArrowType.DownArrow if on else QtCore.Qt.ArrowType.RightArrow)
  self.body.setVisible(on)
 def set_content_layout(self, layout):
  layout.setContentsMargins(8, 2, 2, 2)
  self.body.setLayout(layout)
 def is_expanded(self):
  return self._btn.isChecked()
 def set_expanded(self, on):
  self._btn.setChecked(bool(on))
 def title(self):
  return self._btn.text()
def _mix(c1, c2, ratio):
 r = max(0.0, min(1.0, float(ratio)))
 return QtGui.QColor( round(c1.red() * (1 - r) + c2.red() * r), round(c1.green() * (1 - r) + c2.green() * r), round(c1.blue() * (1 - r) + c2.blue() * r))
def palette_tokens(pal=None):
 if pal is None:
  app = QtWidgets.QApplication.instance()
  pal = app.palette() if app is not None else QtGui.QPalette()
 role = QtGui.QPalette.ColorRole
 win = pal.color(role.Window)
 base = pal.color(role.Base)
 text = pal.color(role.WindowText)
 button = pal.color(role.Button)
 accent = pal.color(role.Highlight)
 accent_text = pal.color(role.HighlightedText)
 dark = win.lightness() < 128
 return { "bg": win.name(), "fg": text.name(), "base": base.name(), "button": _mix(button, base, 0.35 if not dark else 0.15).name(), "button_hover": _mix(button, accent, 0.25).name(), "button_down": _mix(button, accent, 0.45).name(), "accent": accent.name(), "accent_fg": accent_text.name(), "accent_soft": _mix(win, accent, 0.22).name(), "border": _mix(win, text, 0.32).name(), "border_soft": _mix(win, text, 0.18).name(), "title_bg": _mix(win, text, 0.07).name(), "muted": _mix(win, text, 0.55).name(), "info_bg": _mix(win, QtGui.QColor("#1e88e5"), 0.18).name(), "warn_bg": _mix(win, QtGui.QColor("#f9a825"), 0.24).name(), "error_bg": _mix(win, QtGui.QColor("#e53935"), 0.22).name(), "info_fg": _mix(text, QtGui.QColor("#1565c0"), 0.0 if dark else 0.7).name(), "warn_fg": _mix(text, QtGui.QColor("#8d6e00"), 0.0 if dark else 0.7).name(), "error_fg": _mix(text, QtGui.QColor("#b71c1c"), 0.0 if dark else 0.7).name(), }
def is_dark_theme(pal=None):
 if pal is None:
  app = QtWidgets.QApplication.instance()
  pal = app.palette() if app is not None else QtGui.QPalette()
 return pal.color(QtGui.QPalette.ColorRole.Window).lightness() < 128
def render_qss(template, tokens=None):
 return string.Template(template).safe_substitute(tokens or palette_tokens())
class NotificationBar(QtWidgets.QFrame):
 def __init__(self, parent=None):
  super().__init__(parent)
  self.setObjectName("notify_bar")
  self.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
  lay = QtWidgets.QHBoxLayout(self)
  lay.setContentsMargins(8, 4, 4, 4)
  lay.setSpacing(6)
  self._icon = QtWidgets.QLabel()
  self._icon.setAccessibleName("通知の種類")
  lay.addWidget(self._icon)
  self._text = QtWidgets.QLabel()
  self._text.setWordWrap(True)
  self._text.setTextInteractionFlags( QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
  self._text.setAccessibleName("通知メッセージ")
  lay.addWidget(self._text, 1)
  self._detail_btn = QtWidgets.QToolButton()
  self._detail_btn.setText("詳細")
  self._detail_btn.setToolTip("メッセージの詳細を表示します")
  self._detail_btn.clicked.connect(self._show_detail)
  self._detail_btn.setVisible(False)
  lay.addWidget(self._detail_btn)
  close = QtWidgets.QToolButton()
  close.setText("✕")
  close.setToolTip("この通知を閉じます")
  close.setAccessibleName("通知を閉じる")
  close.clicked.connect(self.dismiss)
  lay.addWidget(close)
  self._detail = ""
  self._timer = QtCore.QTimer(self)
  self._timer.setSingleShot(True)
  self._timer.timeout.connect(self.dismiss)
  self.setVisible(False)
 def show_message(self, text, level="info", detail="", timeout_ms=NOTIFY_MS):
  icons = {"info": "ℹ", "warn": "⚠", "error": "✖", "ok": "✔"}
  tok = palette_tokens()
  colors = {"info": ("info_bg", "info_fg"), "ok": ("info_bg", "info_fg"), "warn": ("warn_bg", "warn_fg"), "error": ("error_bg", "error_fg")}
  bg, fg = colors.get(level, colors["info"])
  self.setStyleSheet( f"#notify_bar {{ background:{tok[bg]}; border:1px solid {tok['border_soft']};" f" border-radius:3px; }}" f"#notify_bar QLabel {{ color:{tok[fg]}; }}")
  self._icon.setText(icons.get(level, "ℹ"))
  self._text.setText(str(text))
  self._detail = str(detail or "")
  self._detail_btn.setVisible(bool(self._detail))
  self.setVisible(True)
  self._timer.stop()
  if level != "error" and timeout_ms:
   self._timer.start(int(timeout_ms))
 def dismiss(self):
  self._timer.stop()
  self.setVisible(False)
 def current_text(self):
  return self._text.text()
 def _show_detail(self):
  QtWidgets.QMessageBox.information(self, "詳細", self._detail or self._text.text())
class ProgressStrip(QtWidgets.QFrame):
 canceled = QtCore.Signal()
 def __init__(self, parent=None):
  super().__init__(parent)
  lay = QtWidgets.QHBoxLayout(self)
  lay.setContentsMargins(8, 2, 8, 2)
  lay.setSpacing(6)
  self._label = QtWidgets.QLabel("")
  self._label.setAccessibleName("処理の状況")
  lay.addWidget(self._label)
  self._bar = QtWidgets.QProgressBar()
  self._bar.setAccessibleName("進捗")
  self._bar.setMaximumHeight(14)
  lay.addWidget(self._bar, 1)
  self._cancel = QtWidgets.QPushButton("キャンセル")
  self._cancel.setToolTip("実行中の処理を中止します")
  self._cancel.clicked.connect(self.canceled.emit)
  lay.addWidget(self._cancel)
  self.setVisible(False)
 def start(self, text, total):
  self._label.setText(text)
  self._bar.setRange(0, max(1, int(total)))
  self._bar.setValue(0)
  self._cancel.setEnabled(True)
  self.setVisible(True)
 def update(self, value, text=None):
  self._bar.setValue(int(value))
  if text is not None:
   self._label.setText(text)
 def finish(self):
  self.setVisible(False)
class TableLoadThread(QtCore.QThread):
 one_done = QtCore.Signal(int, object, str)
 progressed = QtCore.Signal(int, str)
 def __init__(self, jobs, parent=None):
  super().__init__(parent)
  self.jobs = list(jobs)
  self._cancel = False
 def cancel(self):
  self._cancel = True
 def is_canceled(self):
  return self._cancel
 def run(self):
  for i, job in enumerate(self.jobs):
   if self._cancel:
    break
   self.progressed.emit(i, os.path.basename(job["path"]))
   try:
    res = load_table( job["path"], encoding=job.get("enc"), delimiter=job.get("delim"), sheet=job.get("sheet"))
    self.one_done.emit(i, res, "")
   except Exception as e:
    self.one_done.emit(i, None, str(e))
__all__ = [ "os", "sys", "QtCore", "QtGui", "QtWidgets", "FigureCanvas", "NavigationToolbar", "Figure", "advanced", "analysis", "applog", "config_io", "data_loader", "datasci", "jp_font", "mathchan", "plotter", "PREVIEW_ROWS", "UserRole", "DECIMATE_TARGET", "BUSY_ROWS", "BATCH_PARALLEL_THRESHOLD", "ASYNC_LOAD_BYTES", "ASYNC_LOAD_COUNT", "SERIES_BAR_MAX", "HEAVY_SERIES", "MESSAGE_LOG_MAX", "NOTIFY_MS", "_parse_float", "CheckListWidget", "LazyColumnCombo", "CollapsibleBox", "ExplorerTree", "SERIES_MIME", "palette_tokens", "is_dark_theme", "render_qss", "NotificationBar", "ProgressStrip", "TableLoadThread", "UI_LEVEL_ORDER", "TabPlugin", "register_tab", "registered_tabs", ]
"""DataIOMixin: GraphApp から分離した DataIOMixin 群（挙動は本体と同一）。"""
class DataIOMixin:
 def dragEnterEvent(self, event):
  if event.mimeData().hasUrls():
   event.acceptProposedAction()
 _ACCEPT_EXTS = ACCEPT_EXTS
 def dropEvent(self, event):
  paths = []
  for url in event.mimeData().urls():
   p = url.toLocalFile()
   if p and os.path.splitext(p)[1].lower() in self._ACCEPT_EXTS:
    paths.append(p)
  if not paths:
   return
  self.last_dir = os.path.dirname(paths[-1])
  self._load_files_async(paths)
 def add_file(self):
  paths, _ = QtWidgets.QFileDialog.getOpenFileNames( self, "ファイルを追加（複数選択可）", self.last_dir, file_dialog_filter())
  if paths:
   self.last_dir = os.path.dirname(paths[-1])
   self._load_files_async(paths)
 def paste_from_clipboard(self):
  import io
  import pandas as pd
  text = QtWidgets.QApplication.clipboard().text()
  if not text or not text.strip():
   self.notify("クリップボードに表データがありません。", "info")
   return
  first = text.splitlines()[0]
  sep = "\t" if first.count("\t") >= first.count(",") else ","
  try:
   df = pd.read_csv(io.StringIO(text), sep=sep, engine="python", skip_blank_lines=True)
   df = _normalize_columns(df)
  except Exception as e:
   self.notify(f"表として読み取れませんでした:\n{e}", "warn")
   return
  if df.shape[1] == 0 or len(df) == 0:
   self.notify("表として読み取れませんでした。", "warn")
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
 def _load_job(self, path):
  enc = self.enc_combo.currentText()
  enc = None if enc.startswith("自動") else enc
  delim = None
  dt = self.delim_combo.currentText()
  if not dt.startswith("自動"):
   for ch, lbl in DELIMITER_LABELS.items():
    if lbl == dt:
     delim = ch
     break
  sheet = None
  if os.path.splitext(path)[1].lower() in (".xlsx", ".xlsm", ".xls"):
   try:
    sheets = excel_sheet_names(path)
   except Exception as e:
    self.notify(f"{os.path.basename(path)} のシートを読めませんでした。", "error", str(e))
    return None
   if len(sheets) > 1:
    sheet, ok = QtWidgets.QInputDialog.getItem( self, "シートの選択", f"{os.path.basename(path)} のシート:", sheets, 0, False)
    if not ok:
     return None
  return {"path": path, "enc": enc, "delim": delim, "sheet": sheet}
 def _register_loaded(self, job, result):
  path, sheet = job["path"], job.get("sheet")
  df, used_enc, used_delim = result
  label = os.path.basename(path)
  if sheet:
   label = f"{label}[{sheet}]"
  base, i = label, 2
  while label in self.datasets and self.meta.get(label, {}).get("path") != path:
   label = f"{base} ({i})"; i += 1
  self.datasets[label] = df
  self.meta[label] = {"path": path, "enc": used_enc, "delim": used_delim, "sheet": sheet}
  if not self._find_file_item(label):
   self._add_file_item(label)
  self._push_recent(path)
  self._set_status(f"{label} を読み込み（{len(df)}行 × {len(df.columns)}列, {used_enc}）")
  return label
 def _load_file(self, path):
  if os.path.splitext(path)[1].lower() in RUNNABLE_EXTS:
   self.run_ltspice_asc(path)
   return
  job = self._load_job(path)
  if job is None:
   return
  size = os.path.getsize(path) if os.path.isfile(path) else 0
  busy = size > 5_000_000
  if busy:
   QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
   self._set_status(f"読み込み中… {os.path.basename(path)}")
   QtWidgets.QApplication.processEvents()
  try:
   result = load_table( path, encoding=job["enc"], delimiter=job["delim"], sheet=job["sheet"])
  except Exception as e:
   self.notify(f"{os.path.basename(path)} を読み込めませんでした。", "error", str(e))
   return
  finally:
   if busy:
    QtWidgets.QApplication.restoreOverrideCursor()
  self._register_loaded(job, result)
 def _load_files_async(self, paths, on_finished=None):
  paths = list(paths)
  for p in [p for p in paths if os.path.splitext(p)[1].lower() in RUNNABLE_EXTS]:
   self.run_ltspice_asc(p)
  targets = [p for p in paths if os.path.splitext(p)[1].lower() not in RUNNABLE_EXTS]
  jobs = []
  for p in targets:
   job = self._load_job(p)
   if job is not None:
    jobs.append(job)
  if not jobs:
   if on_finished:
    on_finished([])
   return None
  if getattr(self, "_load_thread", None) is not None:
   self.notify("前の読み込みが実行中です。終わるまでお待ちください。", "warn")
   return None
  loaded, errors = [], []
  total_bytes = 0
  for job in jobs:
   try:
    total_bytes += os.path.getsize(job["path"])
   except OSError:
    get_logger().debug("_load_files_async: 無視した例外", exc_info=True)
  if len(jobs) <= ASYNC_LOAD_COUNT and total_bytes <= ASYNC_LOAD_BYTES:
   for job in jobs:
    name = os.path.basename(job["path"])
    try:
     res = load_table( job["path"], encoding=job["enc"], delimiter=job["delim"], sheet=job["sheet"])
     loaded.append(self._register_loaded(job, res))
    except Exception as e:
     errors.append(f"{name}: {e}")
   self._refresh_columns()
   if loaded and self._has_drawn:
    self.draw_graph()
   if errors:
    self.notify(f"{len(errors)} 件のファイルを読み込めませんでした。", "error", "\n".join(errors))
   if on_finished:
    on_finished(loaded)
   return None
  def _on_one(index, result, err):
   job = jobs[index]
   name = os.path.basename(job["path"])
   if result is None:
    errors.append(f"{name}: {err}")
   else:
    try:
     loaded.append(self._register_loaded(job, result))
    except Exception as e:
     errors.append(f"{name}: {e}")
   self.progress_strip.update(index + 1)
  def _on_progress(done, name):
   self.progress_strip.update(done, f"読み込み中… {name}（{done + 1}/{len(jobs)}）")
  def _on_finished():
   thread = getattr(self, "_load_thread", None)
   canceled = bool(thread is not None and thread.is_canceled())
   self._load_thread = None
   self.progress_strip.finish()
   self._refresh_columns()
   if loaded and self._has_drawn:
    self.draw_graph()
   if errors:
    self.notify(f"{len(errors)} 件のファイルを読み込めませんでした。", "error", "\n".join(errors))
   elif canceled:
    self.notify(f"読み込みを中止しました（{len(loaded)} 件は読み込み済み）。", "warn")
   elif loaded:
    self.notify(f"{len(loaded)} 件のファイルを読み込みました。", "ok")
   if on_finished:
    on_finished(loaded)
  thread = TableLoadThread(jobs, self)
  self._load_thread = thread
  thread.one_done.connect(_on_one)
  thread.progressed.connect(_on_progress)
  thread.finished.connect(_on_finished)
  self.progress_strip.start(f"読み込み中…（0/{len(jobs)}）", len(jobs))
  thread.start()
  return thread
 def _cancel_background(self):
  thread = getattr(self, "_load_thread", None)
  if thread is not None:
   thread.cancel()
   self._set_status("読み込みの中止を要求しました（実行中の1件が終わり次第停止）。")
 def _stop_background_tasks(self):
  thread = getattr(self, "_load_thread", None)
  if thread is not None:
   thread.cancel()
   thread.wait(5000)
   self._load_thread = None
 def wait_for_loads(self, timeout_ms=30000):
  app = QtWidgets.QApplication.instance()
  deadline = QtCore.QElapsedTimer()
  deadline.start()
  while getattr(self, "_load_thread", None) is not None:
   if deadline.hasExpired(timeout_ms):
    return False
   if app is not None:
    app.processEvents(QtCore.QEventLoop.ProcessEventsFlag.AllEvents, 20)
  if app is not None:
   app.processEvents()
  return True
 def add_folder(self):
  d = QtWidgets.QFileDialog.getExistingDirectory(self, "フォルダを開く", self.last_dir)
  if d:
   self._load_folder(d)
 def _load_folder(self, d):
  exts = set(TABLE_EXTS)
  try:
   names = sorted(os.listdir(d))
  except OSError as e:
   QtWidgets.QMessageBox.critical(self, "フォルダを開く", str(e))
   return
  files = [os.path.join(d, f) for f in names if os.path.splitext(f)[1].lower() in exts and os.path.isfile(os.path.join(d, f))]
  if not files:
   self.notify("このフォルダに読み込めるデータファイルがありません。", "warn")
   return
  if len(files) > 40:
   ret = QtWidgets.QMessageBox.question( self, "フォルダを開く", f"{len(files)} 個のファイルが見つかりました。すべて読み込みますか？")
   if ret != QtWidgets.QMessageBox.StandardButton.Yes:
    return
  self.last_dir = d
  self._load_files_async( files, on_finished=lambda labels: self.notify( f"フォルダを読み込みました: {os.path.basename(d)}" f"（{len(labels)}/{len(files)} ファイル）", "ok"))
 _LTSPICE_CANDIDATES = ( r"C:\Program Files\ADI\LTspice\LTspice.exe", r"C:\Program Files\LTC\LTspiceXVII\XVIIx64.exe", r"C:\Program Files (x86)\LTC\LTspiceIV\scad3.exe", )
 def _ltspice_exe(self):
  p = self._ui_settings().value("ltspice/exe")
  if p and os.path.isfile(str(p)):
   return str(p)
  cands = list(self._LTSPICE_CANDIDATES) + [ os.path.expanduser(r"~\AppData\Local\Programs\ADI\LTspice\LTspice.exe")]
  for c in cands:
   if os.path.isfile(c):
    return c
  try:
   from spicelib.simulators.ltspice_simulator import LTspice
   for c in LTspice.spice_exe:
    if os.path.isfile(str(c)):
     return str(c)
  except Exception:
   get_logger().debug("_ltspice_exe: 無視した例外", exc_info=True)
  import shutil
  return shutil.which("LTspice") or shutil.which("XVIIx64")
 def set_ltspice_path(self):
  path, _ = QtWidgets.QFileDialog.getOpenFileName( self, "LTspice実行ファイルの場所", r"C:\Program Files", "LTspice (*.exe)")
  if path:
   self._ui_settings().setValue("ltspice/exe", path)
   self._set_status(f"LTspiceの場所を設定しました: {path}")
 def run_ltspice_asc(self, path=None):
  if getattr(self, "_lt_proc", None) is not None \
                and self._lt_proc.state() != QtCore.QProcess.ProcessState.NotRunning:
   self._set_status("LTspiceシミュレーションを実行中です。完了までお待ちください。")
   return
  if not path:
   path, _ = QtWidgets.QFileDialog.getOpenFileName( self, "LTspice回路を実行", self.last_dir, "LTspice回路/ネットリスト (*.asc *.net)")
   if not path:
    return
  exe = self._ltspice_exe()
  if not exe:
   ret = QtWidgets.QMessageBox.question( self, "LTspiceが見つかりません", "LTspice の実行ファイルが見つかりませんでした。\n場所を指定しますか？")
   if ret == QtWidgets.QMessageBox.StandardButton.Yes:
    self.set_ltspice_path()
    exe = self._ltspice_exe()
   if not exe:
    return
  self.last_dir = os.path.dirname(path)
  raw = os.path.splitext(path)[0] + ".raw"
  proc = QtCore.QProcess(self)
  self._lt_proc = proc
  proc.finished.connect( lambda code, _st, p=path, r=raw: self._on_ltspice_finished(code, p, r))
  proc.start(exe, ["-b", path])
  if not proc.waitForStarted(5000):
   self._lt_proc = None
   QtWidgets.QMessageBox.critical(self, "LTspice", f"起動できませんでした: {exe}")
   return
  self._set_status(f"LTspiceシミュレーション実行中… {os.path.basename(path)}" "（完了すると自動で波形を読み込みます）")
 def _on_ltspice_finished(self, code, asc_path, raw_path):
  self._lt_proc = None
  if not os.path.isfile(raw_path):
   self.notify(f"シミュレーションは終了しましたが .raw が見つかりません（終了コード {code}）。\n" f"回路にエラーがないか LTspice で確認してください:\n{asc_path}", "warn")
   return
  self._load_file(raw_path)
  self._refresh_columns()
  if self._has_drawn:
   self.draw_graph()
  note = ("（ファイル監視ONなので、LTspice側で再実行すると自動更新されます）" if self._watch_enabled() else "（メニュー『ファイル→ファイルの変更を監視』をONにすると、" "LTspice側の再実行で自動更新されます）")
  self._set_status(f"LTspice完了: {os.path.basename(raw_path)} を読み込みました {note}")
 def _watch_enabled(self):
  return bool(getattr(self, "_watch_action", None) and self._watch_action.isChecked())
 def toggle_file_watch(self, on):
  self._ui_settings().setValue("ui/watch_files", "1" if on else "0")
  if on:
   self._ensure_watcher()
   self._rebuild_watch_paths()
   self._set_status("ファイル監視: ON（監視中のファイルが更新されると自動で再読込・再描画します）")
  else:
   w = getattr(self, "_fs_watcher", None)
   if w is not None and w.files():
    w.removePaths(w.files())
   self._set_status("ファイル監視: OFF")
 def _ensure_watcher(self):
  if getattr(self, "_fs_watcher", None) is None:
   self._fs_watcher = QtCore.QFileSystemWatcher(self)
   self._fs_watcher.fileChanged.connect(self._on_watched_file_changed)
   self._watch_pending = set()
   self._watch_timer = QtCore.QTimer(self)
   self._watch_timer.setSingleShot(True)
   self._watch_timer.setInterval(600)
   self._watch_timer.timeout.connect(self._reload_watched)
 def _rebuild_watch_paths(self):
  if not self._watch_enabled():
   return
  self._ensure_watcher()
  w = self._fs_watcher
  if w.files():
   w.removePaths(w.files())
  paths = sorted({m.get("path") for m in self.meta.values() if m.get("path") and os.path.isfile(m.get("path"))})
  if paths:
   w.addPaths(paths)
 def _on_watched_file_changed(self, path):
  self._watch_pending.add(path)
  self._watch_timer.start()
 def _reload_watched(self):
  pending, self._watch_pending = set(self._watch_pending), set()
  labels = [l for l, m in self.meta.items() if m.get("path") in pending]
  reloaded = []
  for label in labels:
   if self._reload_label_inplace(label):
    reloaded.append(label)
  self._rebuild_watch_paths()
  if reloaded:
   self._refresh_columns()
   if self._has_drawn:
    self.draw_graph()
   self._set_status("自動再読込: " + ", ".join(reloaded))
 def _reload_all_files(self):
  reloaded = [l for l in list(self.datasets) if self._reload_label_inplace(l)]
  if reloaded:
   self._refresh_columns()
   if self._has_drawn:
    self.draw_graph()
   self._set_status(f"再読込しました: {len(reloaded)}ファイル")
  else:
   self._set_status("再読込できるファイルがありません（貼り付け・生成データのみ）。")
 def _reload_label_inplace(self, label):
  meta = self.meta.get(label) or {}
  path = meta.get("path")
  if not path or not os.path.isfile(path):
   return False
  enc = meta.get("enc")
  enc = None if (not enc or str(enc).startswith(("自動", "clipboard"))) else enc
  try:
   df, used_enc, used_delim = load_table( path, encoding=enc, delimiter=meta.get("delim"), sheet=meta.get("sheet"))
  except Exception:
   return False
  self.datasets[label] = df
  self.meta[label] = {"path": path, "enc": used_enc, "delim": used_delim, "sheet": meta.get("sheet")}
  if getattr(self, "_preview_label", None) == label:
   self._populate_preview(df, label=label)
  return True
 def _find_file_item(self, label):
  for i in range(self.file_list.count()):
   if self.file_list.item(i).text() == label:
    return self.file_list.item(i)
  return None
 def _add_file_item(self, label):
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
   self.recent_menu.addAction(os.path.basename(p), lambda checked=False, q=p: self._open_recent(q))
 def _open_recent(self, path):
  if not os.path.isfile(path):
   self.notify(f"ファイルが見つかりません:\n{path}", "warn")
   self.recent_files = [q for q in self.recent_files if q != path]
   self._rebuild_recent_menu()
   return
  self._load_file(path)
  self._refresh_columns()
  if self._has_drawn:
   self.draw_graph()
 def remove_file(self):
  items = self.file_list.selectedItems()
  if not items and self.file_list.currentItem():
   items = [self.file_list.currentItem()]
  labels = [it.text() for it in items]
  if not labels:
   self.notify("削除するファイルを選択してください。", "warn")
   return
  if len(labels) > 1:
   ret = QtWidgets.QMessageBox.question( self, "一括削除", f"{len(labels)} 個のファイルを一覧から削除しますか？")
   if ret != QtWidgets.QMessageBox.StandardButton.Yes:
    return
  self._remove_labels(labels)
  self._set_status(f"{len(labels)} 個のファイルを削除しました。")
 def clear_all_files(self):
  if not self.datasets:
   self.notify("読み込み済みファイルがありません。", "warn")
   return
  ret = QtWidgets.QMessageBox.question( self, "全削除", f"読み込み済みの {len(self.datasets)} 個すべてを一覧から削除しますか？")
  if ret != QtWidgets.QMessageBox.StandardButton.Yes:
   return
  n = len(self.datasets)
  self._remove_labels(list(self.datasets.keys()))
  self._set_status(f"すべて（{n} 個）のファイルを削除しました。")
 def _remove_labels(self, labels):
  labelset = set(labels)
  self._clear_dynamic_resample()
  for label in labels:
   self.datasets.pop(label, None)
   self.meta.pop(label, None)
  for key in [k for k in self.series_styles if k.split("\t", 1)[0] in labelset]:
   self.series_styles.pop(key, None)
  self._meas_annotations = []
  self._ds_annotations = []
  self._proto_annotations = None
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
   self.file_list.setCurrentRow(0)
  else:
   self._preview_label = None
   self.table.clearContents()
   self.table.setRowCount(0)
   self.table.setColumnCount(0)
   self._draw_placeholder()
 def reload_current(self):
  it = self.file_list.currentItem()
  if not it:
   self.notify("ファイルを選択してください。", "warn")
   return
  label = it.text()
  meta = dict(self.meta.get(label) or {})
  path = meta.get("path", "")
  if not path or not os.path.isfile(path):
   self.notify(f"『{label}』は読み込み元のファイルが無いので再読込できません。", "warn", "貼り付けたデータや、数学チャンネル・カーブフィットなどで" "作ったデータセットが該当します（データはそのまま残しました）。")
   return
  df = self.datasets.get(label)
  row = self.file_list.row(it)
  self.datasets.pop(label, None)
  self.meta.pop(label, None)
  self.file_list.takeItem(row)
  self._load_file(path)
  if label not in self.datasets and df is not None:
   self.datasets[label] = df
   self.meta[label] = meta
   if not self._find_file_item(label):
    self._add_file_item(label)
   self.notify(f"『{label}』を読み直せなかったので、元の内容を残しました。", "warn")
  self._refresh_columns()
 def _on_file_selected(self, _row):
  it = self.file_list.currentItem()
  if it and it.text() in self.datasets:
   self._populate_preview(self.datasets[it.text()], label=it.text())
   meta = self.meta[it.text()]
   self.enc_combo.setCurrentText(meta["enc"]) if self.enc_combo.findText(meta["enc"]) >= 0 else None
 def _refresh_columns(self):
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
  if hasattr(self, "z_combo"):
   cur_z = self.z_combo.currentText()
   self.z_combo.blockSignals(True)
   self.z_combo.clear(); self.z_combo.addItems(xcols)
   if cur_z in xcols:
    self.z_combo.setCurrentText(cur_z)
   elif xcols:
    self.z_combo.setCurrentText(xcols[-1])
   self.z_combo.blockSignals(False)
  checked = QtCore.Qt.CheckState.Checked
  unchecked = QtCore.Qt.CheckState.Unchecked
  if hasattr(self, "x_list"):
   prev_x = {self.x_list.item(i).data(UserRole) for i in range(self.x_list.count()) if self.x_list.item(i).checkState() == checked}
   self.x_list.blockSignals(True)
   self.x_list.clear()
   for c in xcols:
    it = QtWidgets.QListWidgetItem(str(c))
    it.setData(UserRole, c)
    it.setFlags(QtCore.Qt.ItemFlag.ItemIsUserCheckable | QtCore.Qt.ItemFlag.ItemIsEnabled)
    it.setCheckState(checked if c in prev_x else unchecked)
    self.x_list.addItem(it)
   self.x_list.blockSignals(False)
  prev = {self.y_list.item(i).data(UserRole) for i in range(self.y_list.count()) if self.y_list.item(i).checkState() == checked}
  self.y_list.blockSignals(True)
  self.y_list.clear()
  multi = len(self.datasets) > 1
  use_left = self._use_leftmost_x()
  for label, df in self.datasets.items():
   for ci, c in enumerate(df.columns):
    if use_left and ci == 0:
     continue
    disp = f"{label} | {c}" if multi else c
    item = QtWidgets.QListWidgetItem(disp)
    item.setData(UserRole, (label, c))
    item.setFlags(QtCore.Qt.ItemFlag.ItemIsUserCheckable | QtCore.Qt.ItemFlag.ItemIsEnabled)
    item.setCheckState(checked if (label, c) in prev else unchecked)
    self.y_list.addItem(item)
  self.y_list.blockSignals(False)
  if hasattr(self, "explorer"):
   self._rebuild_explorer()
  self._rebuild_watch_paths()
  self._on_y_selection_changed()
 def _selected_series_items(self):
  out = []
  for i in range(self.y_list.count()):
   it = self.y_list.item(i)
   if it.checkState() == QtCore.Qt.CheckState.Checked:
    fl, col = it.data(UserRole)
    out.append((fl, col, it.text()))
  return out
 def _populate_preview(self, df, label=None):
  import pandas as pd
  self._preview_loading = True
  try:
   head = df.head(PREVIEW_ROWS)
   cols = list(df.columns)
   self.table.clear()
   self.table.setColumnCount(len(cols))
   self.table.setRowCount(len(head))
   self.table.setHorizontalHeaderLabels([str(c) for c in cols])
   nan_bg = QtGui.QBrush(QtGui.QColor("#ffe4e1"))
   for r in range(len(head)):
    for c in range(len(cols)):
     v = head.iat[r, c]
     missing = pd.isna(v)
     it = QtWidgets.QTableWidgetItem("" if missing else str(v))
     if missing:
      it.setBackground(nan_bg)
      it.setToolTip("欠損値（NaN）")
     self.table.setItem(r, c, it)
   for c, col in enumerate(cols):
    s = df[col]
    n_nan = int(s.isna().sum())
    tip = [f"列: {col}", f"型: {s.dtype}", f"全 {len(s):,} 行"]
    if n_nan:
     tip.append(f"⚠ 欠損: {n_nan:,} 行（{n_nan / max(len(s), 1):.1%}）")
    if pd.api.types.is_numeric_dtype(s):
     v = s.dropna()
     if len(v):
      tip.append(f"範囲: {v.min():.6g} 〜 {v.max():.6g}")
    hi = QtWidgets.QTableWidgetItem(("⚠ " if n_nan else "") + str(col))
    hi.setToolTip("\n".join(tip))
    self.table.setHorizontalHeaderItem(c, hi)
   self.table.resizeColumnsToContents()
   if label is not None:
    self._preview_label = label
  finally:
   self._preview_loading = False
 def _on_edit_toggle(self, on):
  ET = QtWidgets.QAbstractItemView.EditTrigger
  self.table.setEditTriggers( (ET.DoubleClicked | ET.EditKeyPressed | ET.AnyKeyPressed) if on else ET.NoEditTriggers)
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
   val = pd.to_numeric(text, errors="coerce")
  else:
   val = text
  old = df.iat[r, c]
  df.iat[r, c] = val
  self._data_record({"kind": "cell", "label": self._preview_label, "row": r, "col": c, "old": old, "new": val})
  self._set_status(f"編集: {self._preview_label} 行{r}「{col}」= {text}")
  self._request_redraw()
 def _edit_target(self):
  lbl = getattr(self, "_preview_label", None)
  if not lbl or lbl not in self.datasets:
   self.notify("左の一覧でファイルを選択してください。", "warn")
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
  self._data_record({"kind": "row_add", "label": lbl})
  self._populate_preview(df, label=lbl)
  if len(df) > PREVIEW_ROWS:
   self._set_status(f"行を追加（全{len(df)}行。表示は先頭{PREVIEW_ROWS}行）")
  self._request_redraw()
 def _row_del(self):
  lbl = self._edit_target()
  if not lbl:
   return
  rows = sorted({i.row() for i in self.table.selectedIndexes()})
  if not rows:
   self._set_status("削除する行を選択してください。")
   return
  df = self.datasets[lbl]
  self._data_record({"kind": "row_del", "label": lbl, "rows": rows, "data": df.iloc[rows].copy()})
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
   self.notify("同名の列が既にあります。", "warn")
   return
  df[name] = 0.0
  self._data_record({"kind": "col_add", "label": lbl, "name": name})
  self._populate_preview(df, label=lbl)
  self._refresh_columns()
  self._set_status(f"列「{name}」を追加（値0.0で初期化）")
 def _data_record(self, op):
  if not hasattr(self, "_data_hist"):
   self._data_hist, self._data_hist_i = [], -1
  del self._data_hist[self._data_hist_i + 1:]
  self._data_hist.append(op)
  if len(self._data_hist) > 100:
   self._data_hist.pop(0)
  self._data_hist_i = len(self._data_hist) - 1
 def _data_undo(self):
  hist = getattr(self, "_data_hist", None)
  if not hist or self._data_hist_i < 0:
   self._set_status("戻せるデータ編集はありません。")
   return
  op = hist[self._data_hist_i]
  if self._data_apply(op, forward=False):
   self._data_hist_i -= 1
   self._set_status(f"データ編集を戻しました（{self._data_op_name(op)}）。")
 def _data_redo(self):
  hist = getattr(self, "_data_hist", None)
  if not hist or self._data_hist_i >= len(hist) - 1:
   self._set_status("やり直せるデータ編集はありません。")
   return
  op = hist[self._data_hist_i + 1]
  if self._data_apply(op, forward=True):
   self._data_hist_i += 1
   self._set_status(f"データ編集をやり直しました（{self._data_op_name(op)}）。")
 @staticmethod
 def _data_op_name(op):
  return {"cell": "セル編集", "row_add": "行追加", "row_del": "行削除", "col_add": "列追加"}.get(op["kind"], op["kind"])
 def _data_apply(self, op, forward):
  import pandas as pd
  label = op["label"]
  df = self.datasets.get(label)
  if df is None:
   self._set_status(f"対象ファイル「{label}」は読み込まれていません。")
   return False
  kind = op["kind"]
  if kind == "cell":
   r, c = op["row"], op["col"]
   if r >= len(df) or c >= df.shape[1]:
    return False
   df.iat[r, c] = op["new"] if forward else op["old"]
  elif kind == "row_add":
   if forward:
    import numpy as np
    df.loc[len(df)] = [np.nan] * df.shape[1]
    df.reset_index(drop=True, inplace=True)
   else:
    if not len(df):
     return False
    df.drop(df.index[-1], inplace=True)
    df.reset_index(drop=True, inplace=True)
  elif kind == "row_del":
   if forward:
    df.drop(df.index[op["rows"]], inplace=True)
    df.reset_index(drop=True, inplace=True)
   else:
    parts, prev = [], 0
    for j, r in enumerate(op["rows"]):
     cut = r - j
     parts.append(df.iloc[prev:cut])
     parts.append(op["data"].iloc[[j]])
     prev = cut
    parts.append(df.iloc[prev:])
    self.datasets[label] = pd.concat(parts, ignore_index=True)
  elif kind == "col_add":
   if forward:
    self.datasets[label][op["name"]] = 0.0
   else:
    self.datasets[label].drop(columns=[op["name"]], inplace=True, errors="ignore")
  df2 = self.datasets[label]
  if getattr(self, "_preview_label", None) == label:
   self._populate_preview(df2, label=label)
  if kind == "col_add":
   self._refresh_columns()
  self._request_redraw()
  return True
 def _save_csv(self):
  lbl = self._edit_target()
  if not lbl:
   return
  default = lbl if lbl.lower().endswith((".csv", ".tsv")) else lbl + ".csv"
  path, _ = QtWidgets.QFileDialog.getSaveFileName( self, "CSV/TSVとして保存", default, "CSV (*.csv);;TSV (*.tsv);;全てのファイル (*.*)")
  if not path:
   return
  try:
   sep = "\t" if path.lower().endswith(".tsv") else ","
   self.datasets[lbl].to_csv(path, index=False, sep=sep, encoding="utf-8-sig")
   self._set_status(f"保存しました: {path}（全{len(self.datasets[lbl])}行）")
  except Exception as e:
   QtWidgets.QMessageBox.critical(self, "保存エラー", str(e))
 def _build_tab_data(self):
  w = QtWidgets.QWidget()
  v = QtWidgets.QVBoxLayout(w)
  v.setContentsMargins(2, 2, 2, 2)
  note = QtWidgets.QLabel("Y系列の選択は「読み込み済みファイル」ウィンドウで行います" "（表示メニューから再表示できます）。")
  note.setWordWrap(True); note.setStyleSheet("color:#666;")
  v.addWidget(note)
  sec_axes = self._fmt_section("軸の選択（X・Z・3D）", "axes_sel", True)
  v.addWidget(sec_axes)
  av = QtWidgets.QVBoxLayout()
  av.addWidget(QtWidgets.QLabel("X軸（横軸 / ラベル）"))
  self.xleft_check = QtWidgets.QCheckBox("一番左の列をX軸にする（位置で固定）")
  self.xleft_check.setToolTip( "ONにすると各ファイルの『一番左の列』をX軸に使います（列名が違っても適用）。\n" "複数ファイル／バッチ出力でX軸を固定したいときに便利。\n" "OFFなら下のコンボで列名を指定します。")
  self.xleft_check.toggled.connect(self._on_xleft_toggled)
  av.addWidget(self.xleft_check)
  self.x_combo = QtWidgets.QComboBox()
  self.x_combo.setToolTip("横軸に使う列（列名で指定）。波形なら時間列を選びます。")
  self.x_combo.currentTextChanged.connect(self._on_x_changed)
  av.addWidget(self.x_combo)
  xrow = QtWidgets.QHBoxLayout()
  self.swap_xy_check = QtWidgets.QCheckBox("X↔Y 入れ替え")
  self.swap_xy_check.setToolTip("XとYを入れ替えて描く（軸の“向き反転”0→1↔1→0 とは別）。" "散布図・折れ線などの2D種別で有効。")
  self.swap_xy_check.toggled.connect(self._request_redraw)
  xrow.addWidget(self.swap_xy_check)
  self.multix_check = QtWidgets.QCheckBox("X軸を複数選択")
  self.multix_check.setToolTip("ONにすると下のリストでチェックした複数の列をXにし、" "各X×各Yの組み合わせを系列として描きます。")
  self.multix_check.setEnabled(False)
  self.multix_check.toggled.connect(self._on_multix_toggled)
  xrow.addWidget(self.multix_check); xrow.addStretch(1)
  av.addLayout(xrow)
  self.x_list = CheckListWidget()
  self.x_list.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.NoSelection)
  self.x_list.setToolTip("『X軸を複数選択』ON時に、Xに使う列をチェックします。")
  self.x_list.setStyleSheet("QListWidget::indicator { width:16px; height:16px; }")
  self.x_list.setMaximumHeight(90)
  self.x_list.itemChanged.connect(self._request_redraw)
  self.x_list.setEnabled(False)
  av.addWidget(self.x_list)
  self.z_label = QtWidgets.QLabel("Z軸（3Dの奥行き）")
  av.addWidget(self.z_label)
  self.z_combo = QtWidgets.QComboBox()
  self.z_combo.setToolTip("3Dグラフの奥行き（Z軸）に使う列。3D種別のときだけ有効になります。")
  self.z_combo.currentTextChanged.connect(self._on_x_changed)
  self.z_combo.setEnabled(False)
  av.addWidget(self.z_combo)
  self.threed_check = QtWidgets.QCheckBox("3D表示（Z軸を使う・ドラッグで回転）")
  self.threed_check.setToolTip( "散布図・折れ線・棒でONにするとZ軸を使った3D描画になります。\n" "曲面は常に3Dです。3D対応でない種別では選べません（種別は書式パネルで選択）。")
  self.threed_check.setEnabled(False)
  self.threed_check.toggled.connect(self._on_3d_toggled)
  av.addWidget(self.threed_check)
  view = QtWidgets.QHBoxLayout()
  view.addWidget(QtWidgets.QLabel("3D視点 仰角"))
  self.elev_spin = QtWidgets.QSpinBox(); self.elev_spin.setRange(-90, 90)
  self.elev_spin.setValue(30)
  self.elev_spin.setToolTip("3Dグラフの仰角（上下の見おろし角）。ドラッグでも回転できます。")
  self.elev_spin.valueChanged.connect(self._on_view_angle_changed)
  view.addWidget(self.elev_spin)
  view.addWidget(QtWidgets.QLabel("方位"))
  self.azim_spin = QtWidgets.QSpinBox(); self.azim_spin.setRange(-180, 180)
  self.azim_spin.setValue(-60)
  self.azim_spin.setToolTip("3Dグラフの方位（左右の回転角）。ドラッグでも回転できます。")
  self.azim_spin.valueChanged.connect(self._on_view_angle_changed)
  view.addWidget(self.azim_spin)
  view.addStretch(1)
  self.elev_spin.setEnabled(False); self.azim_spin.setEnabled(False)
  av.addLayout(view)
  sec_axes.set_content_layout(av)
  self.y_list = CheckListWidget()
  self.y_list.setVisible(False)
  self.y_list.itemChanged.connect(self._on_y_check_changed)
  self.y_list.itemDoubleClicked.connect(self._on_y_double_clicked)
  v.addStretch(1)
  return w
"""ScopeTabMixin: 「オシロ/解析」タブ（1タブ=1ファイル）。
旧 scope_cursor.py（オシロ表示・カーソル・区間測定・パン/ズーム）と
旧 analysis_peaks.py（ピーク検出・自動測定・FFT表示・全系列一括解析）を統合。
共通の系列取り出し等は HostMixin（host.py）にあり、このタブはそれに依存する。
"""
class ScopeTabMixin:
 def toggle_cursors(self, on):
  if on and getattr(self, "gate_btn", None) and self.gate_btn.isChecked():
   self.gate_btn.setChecked(False)
  if on:
   self._cursors = []
   self._cursor_drag = None
   self._cursor_text = None
   self._clear_cursor_artists()
   self._cursor_cid = ( self.canvas.mpl_connect("button_press_event", self._on_cursor_press), self.canvas.mpl_connect("motion_notify_event", self._on_cursor_motion), self.canvas.mpl_connect("button_release_event", self._on_cursor_release), )
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
    get_logger().debug("_clear_cursor_artists: 無視した例外", exc_info=True)
  self._cursor_artists = []
  self._cursors = []
  self._cursor_text = None
 def _cursor_track_y(self, x):
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
  for i, c in enumerate(self._cursors):
   try:
    cx_px = self.ax.transData.transform((c["x"], 0))[0]
    if abs(event.x - cx_px) < 8:
     return i
   except Exception:
    get_logger().debug("_cursor_near: 無視した例外", exc_info=True)
  return None
 def _on_cursor_press(self, event):
  if event.inaxes is not self.ax or event.xdata is None:
   return
  if getattr(self.ax, "name", None) == "3d":
   return
  near = self._cursor_near(event)
  if near is not None:
   self._cursor_drag = near
   return
  if len(self._cursors) >= 2:
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
    get_logger().debug("_update_cursor_readout: 無視した例外", exc_info=True)
   self._cursor_text = None
  if len(self._cursors) == 2:
   x1, x2 = self._cursors[0]["x"], self._cursors[1]["x"]
   y1, y2 = self._cursor_track_y(x1), self._cursor_track_y(x2)
   dt, dv = x2 - x1, y2 - y1
   freq = (1.0 / dt) if dt else float("inf")
   txt = (f"Δt={format_eng(abs(dt))}  ΔV={format_eng(abs(dv))}" f"  1/Δt={format_eng(abs(freq))}Hz")
   self._cursor_text = self.ax.text( 0.5, 0.98, txt, transform=self.ax.transAxes, ha="center", va="top", color="#e6194b", fontsize=9, bbox=dict(facecolor="white", alpha=0.75, edgecolor="#e6194b"))
   self._cursor_artists.append(self._cursor_text)
   self._set_status("カーソル  " + txt)
 def _scope_active(self):
  return (self.scope_check.isChecked() and self.chart_combo.currentText() in ("折れ線", "散布図") and self._has_drawn and self._cursor_cid is None and not getattr(self.toolbar, "mode", ""))
 def _scope_overlay(self, text):
  self._remove_scope_overlay()
  self._scope_ov = self.ax.text( 0.99, 0.02, text, transform=self.ax.transAxes, ha="right", va="bottom", color="#7CFC00", fontsize=11, bbox=dict(facecolor="black", alpha=0.65, edgecolor="#7CFC00"))
 def _remove_scope_overlay(self):
  if self._scope_ov is not None:
   try:
    self._scope_ov.remove()
   except Exception:
    get_logger().debug("_remove_scope_overlay: 無視した例外", exc_info=True)
   self._scope_ov = None
 def _shift_held(self, event=None):
  try:
   mods = QtWidgets.QApplication.keyboardModifiers()
   if bool(mods & QtCore.Qt.KeyboardModifier.ShiftModifier):
    return True
  except Exception:
   get_logger().debug("_shift_held: 無視した例外", exc_info=True)
  return bool(event is not None and event.key and "shift" in str(event.key))
 def _scope_on_press(self, event):
  if (event.dblclick and event.button == 1 and event.inaxes is not None and event.inaxes in self.fig.axes and self._cursor_cid is None and not getattr(self.toolbar, "mode", "") and getattr(event.inaxes, "name", None) != "3d" and event.inaxes.get_label() != "<colorbar>" and getattr(self, "_has_drawn", False)):
   self._autoscale_view()
   return
  if (not self._scope_active() or event.inaxes is not self.ax or event.button not in (1, 3) or event.x is None):
   return
  bbox = self.ax.get_window_extent()
  self._scope_drag = { "button": event.button, "shift": self._shift_held(event), "px": (event.x, event.y), "xlim": self.ax.get_xlim(), "ylim": self.ax.get_ylim(), "tdiv": parse_eng(self.tdiv.currentText(), 1e-3) or 1e-3, "vdiv": parse_eng(self.vdiv.currentText(), 1.0) or 1.0, "w": max(bbox.width, 1.0), "h": max(bbox.height, 1.0), }
 def _scope_on_motion(self, event):
  d = self._scope_drag
  if not d or event.x is None:
   return
  dxpx = event.x - d["px"][0]
  dypx = event.y - d["px"][1]
  xd, yd = self.xdivs.value(), self.ydivs.value()
  if d["button"] == 1 and not d["shift"]:
   x0, x1 = d["xlim"]; y0, y1 = d["ylim"]
   dpx = (x1 - x0) / d["w"]; dpy = (y1 - y0) / d["h"]
   nx0, nx1 = x0 - dxpx * dpx, x1 - dxpx * dpx
   ny0, ny1 = y0 - dypx * dpy, y1 - dypx * dpy
   self.ax.set_xlim(nx0, nx1); self.ax.set_ylim(ny0, ny1)
   self._scope_overlay(f"位置  X中心={format_eng((nx0+nx1)/2)}  " f"Y中心={format_eng((ny0+ny1)/2)}")
  else:
   xc = (d["xlim"][0] + d["xlim"][1]) / 2
   yc = (d["ylim"][0] + d["ylim"][1]) / 2
   ntdiv = d["tdiv"] * (2 ** (dxpx / 150.0))
   nvdiv = d["vdiv"] * (2 ** (-dypx / 150.0))
   self.ax.set_xlim(xc - xd / 2 * ntdiv, xc + xd / 2 * ntdiv)
   self.ax.set_ylim(yc - yd / 2 * nvdiv, yc + yd / 2 * nvdiv)
   self._scope_overlay(f"{format_eng(ntdiv)}s/div   " f"{format_eng(nvdiv)}/div")
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
  self.draw_graph()
 def _scope_on_scroll(self, event):
  if event.inaxes is not self.ax:
   return
  if self._scope_active():
   step = 0.8 if event.button == "up" else 1.25
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
  self._wheel_zoom(event)
 def _wheel_zoom(self, event):
  ax = event.inaxes if event.inaxes in self.fig.axes else self.ax
  if (self._cursor_cid is not None or getattr(self.toolbar, "mode", "") or not getattr(self, "_has_drawn", False) or self.chart_combo.currentText() == "円" or getattr(ax, "name", None) == "3d" or ax.get_label() == "<colorbar>"):
   return
  factor = 0.8 if event.button == "up" else 1.25
  x0, x1 = ax.get_xlim()
  y0, y1 = ax.get_ylim()
  xc = event.xdata if event.xdata is not None else (x0 + x1) / 2.0
  yc = event.ydata if event.ydata is not None else (y0 + y1) / 2.0
  xlog = ax.get_xscale() == "log"
  ylog = ax.get_yscale() == "log"
  ax.set_xlim(*self._zoom_pair(x0, x1, xc, factor, xlog))
  if not self._shift_held(event):
   ax.set_ylim(*self._zoom_pair(y0, y1, yc, factor, ylog))
  self.canvas.draw_idle()
 def toggle_gate(self, on):
  if on:
   if getattr(self.ax, "name", None) == "3d":
    self._set_status("区間測定は2Dグラフで使えます（3D表示では無効）。")
    self.gate_btn.setChecked(False)
    return
   if self.cursor_btn.isChecked():
    self.cursor_btn.setChecked(False)
   from matplotlib.widgets import SpanSelector
   self._gate_span = SpanSelector( self.ax, self._on_gate_select, "horizontal", useblit=True, props=dict(alpha=0.2, facecolor="#2b6cb0"), interactive=True)
   self._set_status("区間測定: グラフ上を横にドラッグしてX範囲を選ぶと、" "その区間だけの測定値を下の表に表示します。")
  else:
   sp = getattr(self, "_gate_span", None)
   if sp is not None:
    try:
     sp.set_visible(False)
     sp.disconnect_events()
    except Exception:
     get_logger().debug("toggle_gate: 無視した例外", exc_info=True)
   self._gate_span = None
   self.canvas.draw_idle()
 def _regate(self):
  if getattr(self, "gate_btn", None) and self.gate_btn.isChecked():
   self.toggle_gate(False)
   if getattr(self.ax, "name", None) == "3d":
    self.gate_btn.setChecked(False)
   else:
    self.toggle_gate(True)
 def _on_gate_select(self, x0, x1):
  if x1 < x0:
   x0, x1 = x1, x0
  if x0 == x1:
   return
  self._run_gated_analysis(float(x0), float(x1))
 def _autoscale_view(self):
  if (self.scope_check.isChecked() and self.chart_combo.currentText() in ("折れ線", "散布図")):
   self.auto_scale_scope()
   return
  self._suspend_redraw = True
  for le in (self.xmin, self.xmax, self.ymin, self.ymax):
   le.clear()
  self._suspend_redraw = False
  self.draw_graph()
  self._set_status("全体表示に戻しました（ダブルクリックでいつでも戻れます）。")
 def _hover_lines(self, ax):
  axs = [ax]
  twin = getattr(ax, "_twin_secondary", None)
  if twin is not None:
   axs.append(twin)
  if ax is getattr(self.ax, "_twin_secondary", None):
   axs.append(self.ax)
  return [(str(ln.get_label()), ln) for a in axs for ln in a.get_lines() if not str(ln.get_label()).startswith("_") and "近似" not in str(ln.get_label())]
 def _hover_values(self, ax, x_disp):
  import numpy as np
  out = []
  for label, ln in self._hover_lines(ax):
   try:
    xd = np.asarray(ln.get_xdata(), float)
    yd = np.asarray(ln.get_ydata(), float)
   except (TypeError, ValueError):
    continue
   if xd.size == 0 or xd.size != yd.size:
    continue
   m = np.isfinite(xd) & np.isfinite(yd)
   if not m.any():
    continue
   xs, ys = xd[m], yd[m]
   i = int(np.argmin(np.abs(xs - x_disp)))
   out.append((label, ln.get_color(), float(xs[i]), float(ys[i])))
  return out
 def _hover_readout(self, event):
  lbl = getattr(self, "_hover_label", None)
  if lbl is None:
   return
  ax = event.inaxes
  if (ax is None or ax not in self.fig.axes or event.x is None or event.xdata is None or not getattr(self, "_has_drawn", False) or getattr(ax, "name", None) == "3d" or ax.get_label() == "<colorbar>" or self._scope_drag or self._cursor_drag is not None):
   if lbl.text():
    lbl.setText("")
   self._hide_hover_ui()
   return
  import time
  now = time.monotonic()
  if now - getattr(self, "_hover_t", 0.0) < 0.05:
   return
  self._hover_t = now
  vals = self._hover_values(ax, float(event.xdata))
  best = None
  for label, _c, x, y in vals:
   pt = ax.transData.transform([[x, y]])[0]
   d2 = (pt[0] - event.x) ** 2 + (pt[1] - event.y) ** 2
   if best is None or d2 < best[0]:
    best = (d2, label, x, y)
  if best is not None and best[0] <= 20.0 ** 2:
   _, label, x, y = best
   lbl.setText(f"{label}:  X={format_eng(x)}  Y={format_eng(y)}  ")
  elif lbl.text():
   lbl.setText("")
  if vals:
   rows = [f"<b>X = {format_eng(float(event.xdata))}</b>"]
   for label, color, _x, y in vals[:12]:
    rows.append(f"<span style='color:{color}'>■</span> " f"{label}: <b>{format_eng(y)}</b>")
   if len(vals) > 12:
    rows.append(f"…他 {len(vals) - 12} 系列")
   QtWidgets.QToolTip.showText(QtGui.QCursor.pos(), "<br>".join(rows), self.canvas)
  else:
   QtWidgets.QToolTip.hideText()
  self._draw_crosshair(ax, event.xdata, event.ydata)
 def _hide_hover_ui(self):
  QtWidgets.QToolTip.hideText()
  if getattr(self, "_xhair_bg", None) is None:
   return
  size = (int(self.fig.bbox.width), int(self.fig.bbox.height), self.canvas.width(), self.canvas.height())
  if getattr(self, "_xhair_size", None) != size or getattr(self, "_drawing", False):
   self._xhair_bg = None
   return
  try:
   self.canvas.restore_region(self._xhair_bg)
   self.canvas.blit(self.fig.bbox)
  except Exception:
   get_logger().debug("_hide_hover_ui: 無視した例外", exc_info=True)
  self._xhair_bg = None
 def _invalidate_crosshair(self, *_):
  self._xhair_bg = None
 def _draw_crosshair(self, ax, x, y):
  if (x is None or y is None or (getattr(self, "gate_btn", None) and self.gate_btn.isChecked()) or self._cursor_cid is not None or getattr(self.toolbar, "mode", "")):
   return
  xh = getattr(self, "_xhair", None)
  if not xh or xh[0].axes is not ax:
   if xh:
    for a in xh:
     try:
      a.remove()
     except Exception:
      get_logger().debug("_draw_crosshair: 無視した例外", exc_info=True)
   v = ax.axvline(x, color="#888", lw=0.7, ls="--", animated=True, zorder=30)
   h = ax.axhline(y, color="#888", lw=0.7, ls="--", animated=True, zorder=30)
   self._xhair = (v, h)
   self._xhair_bg = None
  size = (int(self.fig.bbox.width), int(self.fig.bbox.height), self.canvas.width(), self.canvas.height())
  if getattr(self, "_xhair_size", None) != size:
   self._xhair_bg = None
  if getattr(self, "_drawing", False):
   return
  try:
   if getattr(self, "_xhair_bg", None) is None:
    self._xhair_bg = self.canvas.copy_from_bbox(self.fig.bbox)
    self._xhair_size = size
   self.canvas.restore_region(self._xhair_bg)
   self._xhair[0].set_xdata([x, x])
   self._xhair[1].set_ydata([y, y])
   ax.draw_artist(self._xhair[0])
   ax.draw_artist(self._xhair[1])
   self.canvas.blit(self.fig.bbox)
  except Exception:
   self._xhair_bg = None
 @staticmethod
 def _zoom_pair(lo, hi, center, factor, log=False):
  import numpy as np
  if log and lo > 0 and hi > 0 and center > 0:
   l0, l1, lc = np.log10(lo), np.log10(hi), np.log10(center)
   return 10.0 ** (lc - (lc - l0) * factor), 10.0 ** (lc + (l1 - lc) * factor)
  return center - (center - lo) * factor, center + (hi - center) * factor
 def auto_scale_scope(self):
  import numpy as np
  import pandas as pd
  items = self._selected_series_items()
  if not items:
   self.notify("データタブでY系列を選択してください。", "warn")
   return
  xname = self.x_combo.currentText()
  xspec = self.xscale_edit.text()
  yspec = self.yscale_edit.text()
  tmins, tmaxs, ymins, ymaxs = [], [], [], []
  for fl, col, _ in items:
   df = self.datasets[fl]
   raw = df[xname].to_numpy() if xname in df.columns else df.iloc[:, 0].to_numpy()
   tt = pd.to_numeric(pd.Series(raw), errors="coerce").to_numpy(dtype=float)
   if np.isnan(tt).mean() > 0.5:
    tt = np.arange(len(tt), dtype=float)
   yy = pd.to_numeric(pd.Series(df[col].to_numpy()), errors="coerce").to_numpy(dtype=float)
   tt = axis_scale(tt, xspec)
   yy = axis_scale(yy, yspec)
   tt, yy = tt[np.isfinite(tt)], yy[np.isfinite(yy)]
   if tt.size:
    tmins.append(tt.min()); tmaxs.append(tt.max())
   if yy.size:
    ymins.append(yy.min()); ymaxs.append(yy.max())
  if not tmins or not ymins:
   self.notify("数値データがありません。", "warn")
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
  scope_hint = QtWidgets.QLabel( "💡 オシロ表示中はグラフを直接操作可：左ドラッグ=位置移動／右ドラッグ=time/V/div／" "ホイール=time/div・Shift+ホイール=V/div（ドラッグ中は数値を表示）")
  scope_hint.setWordWrap(True); scope_hint.setStyleSheet("color:#0a7a55; font-size:11px;")
  v.addWidget(scope_hint)
  v.addWidget(self._hline())
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
  b_an = QtWidgets.QPushButton("解析実行"); b_an.clicked.connect(self.run_analysis)
  b_an.setToolTip("解析対象コンボで選んだ1系列のピーク・測定を下の表に表示")
  b_all = QtWidgets.QPushButton("全系列を解析…")
  b_all.setToolTip("選択中の全系列のピーク・測定を別ウィンドウに一覧表示（CSV保存可）")
  b_all.clicked.connect(self.analyze_all_series)
  b_fft = QtWidgets.QPushButton("FFT表示"); b_fft.setCheckable(True)
  b_fft.setToolTip("ONで全系列を周波数ドメイン（FFTスペクトル）へ切替。単位変換のように、" "ONの間は再描画してもFFT表示が続きます（もう一度押すと時間ドメインへ）。")
  b_fft.toggled.connect(self._on_fft_toggled)
  self.fft_btn = b_fft
  b_cur = QtWidgets.QPushButton("カーソル測定"); b_cur.setCheckable(True)
  b_cur.setToolTip("グラフを2回クリックして Δt・ΔV・1/Δt を測ります")
  b_cur.toggled.connect(self.toggle_cursors)
  self.cursor_btn = b_cur
  brow = QtWidgets.QHBoxLayout()
  brow.addWidget(b_an); brow.addWidget(b_all); brow.addWidget(b_fft)
  v.addLayout(brow)
  b_gate = QtWidgets.QPushButton("区間測定")
  b_gate.setCheckable(True)
  b_gate.setToolTip("ONにしてグラフ上を横にドラッグすると、選んだX区間だけの\n" "測定値（平均/RMS/周期など）を下の表に表示します。")
  b_gate.toggled.connect(self.toggle_gate)
  self.gate_btn = b_gate
  brow2 = QtWidgets.QHBoxLayout()
  brow2.addWidget(b_cur); brow2.addWidget(b_gate)
  v.addLayout(brow2)
  v.addWidget(self._bold("ピーク（第1=最大）"))
  self.peak_table = QtWidgets.QTableWidget(0, 3)
  self.peak_table.setHorizontalHeaderLabels(["順位", "時間/周波数", "値"])
  self.peak_table.horizontalHeader().setStretchLastSection(True)
  self.peak_table.setMaximumHeight(160)
  self._wire_table_export(self.peak_table, "ピーク")
  v.addWidget(self.peak_table)
  v.addWidget(self._bold("測定値（右端「表示」でグラフに注記）"))
  self.meas_table = QtWidgets.QTableWidget(0, 3)
  self.meas_table.setHorizontalHeaderLabels(["項目", "値", "表示"])
  mh = self.meas_table.horizontalHeader()
  mh.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
  mh.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Stretch)
  mh.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
  self.meas_table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
  self._wire_table_export(self.meas_table, "測定値")
  v.addWidget(self.meas_table, 1)
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
 def _peak_markers(self):
  if self.chart_combo.currentText() not in ("折れ線", "散布図"):
   return None
  t, y, _ = self._analysis_xy()
  if t is None:
   return None
  try:
   peaks = find_signal_peaks(y, t=t, n=self.npeaks.value(), smooth=self.smooth_spin.value())
  except Exception:
   return None
  xspec, yspec = self.xscale_edit.text(), self.yscale_edit.text()
  out = []
  for p in peaks:
   if p["time"] is None:
    continue
   out.append({"x": float(axis_scale([p["time"]], xspec)[0]), "y": float(axis_scale([p["value"]], yspec)[0]), "text": f"第{p['rank']}", "color": "#ff3030"})
  return out
 def run_analysis(self):
  got = self.analysis_xy_or_warn()
  if got is None:
   return
  t, y, label = got
  import numpy as np
  y = np.asarray(y, float)
  res = analyze(t, y, n_peaks=self.npeaks.value(), smooth=self.smooth_spin.value())
  self._show_analysis_result(res, f"解析しました: {label}")
 def _run_gated_analysis(self, x0, x1):
  import numpy as np
  t, y, label = self._analysis_xy()
  if t is None:
   self._set_status("区間測定: 『オシロ/解析』の解析対象で系列を選択してください。")
   return
  t = np.asarray(t, float)
  t_disp = axis_scale(t, self.xscale_edit.text())
  mask = (t_disp >= x0) & (t_disp <= x1)
  if int(mask.sum()) < 3:
   self._set_status("区間測定: 選択した区間のデータ点が少なすぎます（3点以上必要）。")
   return
  res = analyze(t[mask], np.asarray(y, float)[mask], n_peaks=self.npeaks.value(), smooth=self.smooth_spin.value())
  self._show_analysis_result( res, f"区間測定 [{format_eng(x0)} 〜 {format_eng(x1)}]: " f"{label}（{int(mask.sum()):,}点）", redraw_ok=False)
 def _show_analysis_result(self, res, status, redraw_ok=True):
  self.peak_table.setRowCount(len(res["peaks"]))
  for r, p in enumerate(res["peaks"]):
   self.peak_table.setItem(r, 0, QtWidgets.QTableWidgetItem(f"第{p['rank']}"))
   tv = "-" if p["time"] is None else f"{p['time']*1e3:.4g} ms"
   self.peak_table.setItem(r, 1, QtWidgets.QTableWidgetItem(tv))
   self.peak_table.setItem(r, 2, QtWidgets.QTableWidgetItem(f"{p['value']:.4g}"))
  rows = res["measurements"]
  had_ann = bool(getattr(self, "_meas_annotations", None))
  self._meas_annotations = []
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
  if redraw_ok and (self.show_peaks_check.isChecked() or had_ann):
   self.draw_graph()
  self._set_status(status)
 def _refresh_meas_annotations(self, *_):
  anns = []
  for r in range(self.meas_table.rowCount()):
   cb = self.meas_table.cellWidget(r, 2)
   if cb is not None and cb.isChecked():
    k = self.meas_table.item(r, 0)
    val = self.meas_table.item(r, 1)
    if k is not None and val is not None:
     anns.append(f"{k.text()} = {val.text()}")
  self._meas_annotations = anns
  if self.datasets:
   self.draw_graph()
 def _fft_mode_on(self):
  return bool(getattr(self, "fft_btn", None) and self.fft_btn.isChecked())
 def _on_fft_toggled(self, on):
  if on and getattr(self, "scope_check", None) and self.scope_check.isChecked():
   self.scope_check.setChecked(False)
  self._set_status("FFT表示: ON（周波数ドメイン）" if on else "FFT表示: OFF（時間ドメインへ戻す）")
  if self.datasets:
   self.draw_graph()
 def show_fft(self):
  if getattr(self, "fft_btn", None) and not self.fft_btn.isChecked():
   self.fft_btn.setChecked(True)
  else:
   self.draw_graph()
 def _draw_fft_view(self):
  import numpy as np
  items = self._selected_series_items()
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
                or f"C{idx % 10}"
   disp_amp = to_db(amp) if use_db else amp
   series.append({"label": f"FFT: {disp}", "x": freqs, "y": disp_amp, "style": {"color": color, "linewidth": 1.0}})
   for pk in find_spectral_peaks(t, np.asarray(y, float), n=self.npeaks.value()):
    yv = to_db(np.array([pk["amplitude"]]))[0] if use_db else pk["amplitude"]
    markers.append({"x": pk["frequency"], "y": yv, "text": f"{pk['frequency']:.0f}Hz", "color": color})
   drawn += 1
  if drawn == 0:
   self.ax.set_xlabel("周波数 [Hz]"); self.ax.set_ylabel(ylab)
   self.canvas.draw()
   self.notify("FFT を計算できる系列がありません（点数が少ない可能性）。", "warn")
   return
  plot_series( self.ax, series, "折れ線", title=f"FFTスペクトル（{win}窓・{drawn}系列）", xlabel="周波数 [Hz]", ylabel=ylab, grid=True, legend=(drawn > 1), markers=markers, fonts=self._fonts())
  self._apply_aspect()
  self._apply_figure_theme(redraw=False)
  try:
   self.fig.tight_layout()
  except Exception:
   get_logger().debug("_draw_fft_view: 無視した例外", exc_info=True)
  self.canvas.draw()
 def analyze_all_series(self):
  items = self._selected_series_items()
  if not items:
   self.notify("解析する系列を選択してください。", "warn")
   return
  import numpy as np
  peak_rows, meas_rows = [], []
  for fl, col, disp in items:
   t, y = self._xy_for(fl, col)
   if t is None or len(np.asarray(y)) < 2:
    continue
   r = analyze(t, np.asarray(y, float), n_peaks=self.npeaks.value(), smooth=self.smooth_spin.value())
   for p in r["peaks"]:
    tv = None if p["time"] is None else p["time"] * 1e3
    peak_rows.append((disp, f"第{p['rank']}", tv, p["value"]))
   for m in r["measurements"]:
    meas_rows.append((disp, m["name"], m["value"], m["unit"]))
  if not peak_rows and not meas_rows:
   self.notify("解析できる系列がありません。", "warn")
   return
  self._show_analysis_window(peak_rows, meas_rows)
 def _show_analysis_window(self, peak_rows, meas_rows):
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
  self._wire_table_export(pk, "全系列ピーク")
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
  self._wire_table_export(ms, "全系列測定")
  lay.addWidget(ms, 1)
  brow = QtWidgets.QHBoxLayout()
  b_save = QtWidgets.QPushButton("CSVで保存…")
  b_save.clicked.connect(lambda: self._save_analysis_csv(peak_rows, meas_rows))
  b_close = QtWidgets.QPushButton("閉じる")
  b_close.clicked.connect(dlg.close)
  brow.addStretch(1); brow.addWidget(b_save); brow.addWidget(b_close)
  lay.addLayout(brow)
  self._analysis_window = dlg
  dlg.show()
 def _save_analysis_csv(self, peak_rows, meas_rows):
  path, _ = QtWidgets.QFileDialog.getSaveFileName( self, "解析結果をCSVで保存", self.last_dir, "CSV (*.csv)")
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
  except Exception as e:
   QtWidgets.QMessageBox.critical(self, "保存エラー", str(e))
"""AdvancedMixin: GraphApp から分離した AdvancedMixin 群（挙動は本体と同一）。"""
class AdvancedMixin:
 def _on_math_op_change(self, op):
  binary = op in BINARY_OPS
  self.math_b.setEnabled(binary); self.math_b_label.setEnabled(binary)
  needs_param = op in ("移動平均", "ローパス(RC)", "ローパス(Butterworth)", "ハイパス(Butterworth)")
  self.math_param.setEnabled(needs_param); self.math_param_label.setEnabled(needs_param)
 def create_math_channel(self):
  op = self.math_op.currentText()
  ta, ya = self._xy_by_disp(self.math_a.currentText())
  if ta is None:
   self.notify("演算対象Aをデータタブで選択してください。", "warn")
   return
  try:
   if op in BINARY_OPS:
    tb, yb = self._xy_by_disp(self.math_b.currentText())
    if tb is None:
     self.notify("演算対象Bを選択してください。", "warn")
     return
    x, r = binary(ta, ya, tb, yb, op)
   else:
    param = parse_eng(self.math_param.text(), None)
    x, r = unary(ta, ya, op, param)
  except Exception as e:
   QtWidgets.QMessageBox.critical(self, "演算エラー", str(e)); return
  import pandas as pd
  col = f"{op}"
  self.register_dataset(f"Math: {op}", pd.DataFrame({"時間[s]": x, col: r}), status=f"数学チャンネルを作成: {{label}} ▸ {col}")
 def create_math_expr(self):
  import numpy as np
  import pandas as pd
  expr = self.math_expr.text().strip()
  if not expr:
   self.notify("数式を入力してください。", "warn")
   return
  ta, ya = self._xy_by_disp(self.math_a.currentText())
  if ta is None:
   self.notify("変数Aの系列をデータタブで選択してください。", "warn")
   return
  variables = {"A": ya, "t": ta, "VAR1": parse_eng(self.math_var1.text(), 0.0) or 0.0, "VAR2": parse_eng(self.math_var2.text(), 0.0) or 0.0}
  tb, yb = self._xy_by_disp(self.math_b.currentText())
  if tb is not None and yb is not None:
   variables["B"] = yb if len(yb) == len(ya) else np.interp(ta, tb, yb)
  try:
   r = eval_expr(expr, variables)
   r = np.broadcast_to(np.asarray(r, dtype=float), ya.shape).astype(float)
  except Exception as e:
   QtWidgets.QMessageBox.critical(self, "数式エラー", str(e))
   return
  self.register_dataset(f"Expr: {expr[:24]}", pd.DataFrame({"時間[s]": ta, "結果": r}), status="数式チャンネルを作成: {label}")
 def show_param_stats(self):
  import numpy as np
  got = self.analysis_xy_or_warn()
  if got is None:
   return
  t, y, label = got
  yv = np.asarray(y, float)
  self._show_param_stats_window(label, cycle_statistics(t, yv), measurements(t, yv))
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
    r = {"+": a + b, "-": a - b, "×": a * b, "÷": (a / b if b else float("nan"))}[o]
    out.setText(f"= {r:.6g}")
   except Exception:
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
  got = self.analysis_xy_or_warn()
  if got is None:
   return
  t, y, label = got
  win = self.fft_window.currentText()
  yv = np.asarray(y, float)
  m = spectrum_metrics(t, yv, window=win)
  rows = [ ("基本波 f0", m.get("f0"), "Hz"), ("THD", m.get("THD_pct"), "%"), ("THD", m.get("THD_dB"), "dB"), ("SNR", m.get("SNR_dB"), "dB"), ("SINAD", m.get("SINAD_dB"), "dB"), ("ENOB", m.get("ENOB_bits"), "bit"), ("SFDR", m.get("SFDR_dB"), "dB"), ("占有帯域幅(99%)", occupied_bandwidth(t, yv, window=win), "Hz"), ("チャネル電力(全)", channel_power(t, yv, window=win), "V²"), ]
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
  got = self.analysis_xy_or_warn()
  if got is None:
   return
  t, y, label = got
  f, tt, S = spectrogram(t, np.asarray(y, float), window=self.fft_window.currentText())
  if S is None:
   self.notify("計算できませんでした。", "warn")
   return
  self.prepare_view_axes()
  mesh = self.ax.pcolormesh(tt, f, S, shading="auto", cmap="viridis")
  self.ax.set_xlabel("時間 [s]"); self.ax.set_ylabel("周波数 [Hz]")
  self.ax.set_title(f"スペクトログラム: {label}")
  try:
   self.fig.colorbar(mesh, ax=self.ax, label="dB")
  except Exception:
   get_logger().debug("show_spectrogram: 無視した例外", exc_info=True)
  self._apply_aspect()
  try:
   self.fig.tight_layout()
  except Exception:
   get_logger().debug("show_spectrogram: 無視した例外", exc_info=True)
  self.canvas.draw()
  self._has_drawn = False
  self._set_status(f"スペクトログラム表示: {label}")
 def show_waterfall(self):
  import numpy as np
  got = self.analysis_xy_or_warn()
  if got is None:
   return
  t, y, label = got
  f, tt, S = spectrogram(t, np.asarray(y, float), window=self.fft_window.currentText())
  if S is None:
   self.notify("計算できませんでした。", "warn")
   return
  self.prepare_view_axes(three_d=True, white_bg=False)
  from matplotlib import cm
  n = S.shape[1]
  step = max(1, n // 60)
  f = np.asarray(f, float)
  for i in range(0, n, step):
   self.ax.plot(f, np.full_like(f, tt[i]), S[:, i], lw=0.8, color=cm.viridis(i / max(n - 1, 1)))
  self.ax.set_xlabel("周波数 [Hz]")
  self.ax.set_ylabel("時間 [s]")
  self.ax.set_zlabel("振幅 [dB]")
  self.ax.set_title(f"FFTウォーターフォール: {label}")
  try:
   self.ax.view_init(elev=self.elev_spin.value(), azim=self.azim_spin.value())
  except Exception:
   get_logger().debug("show_waterfall: 無視した例外", exc_info=True)
  try:
   self.fig.tight_layout()
  except Exception:
   get_logger().debug("show_waterfall: 無視した例外", exc_info=True)
  self.canvas.draw()
  self._has_drawn = False
  self._set_status(f"FFTウォーターフォール表示: {label}（{(n + step - 1) // step}スライス・" "ドラッグで回転）")
 def run_mask_test(self):
  import numpy as np
  got = self.analysis_xy_or_warn()
  if got is None:
   return
  t, y, label = got
  up = parse_eng(self.mask_upper.text(), None)
  lo = parse_eng(self.mask_lower.text(), None)
  if up is None and lo is None:
   self.notify("上限または下限を入力してください。", "warn")
   return
  res = mask_test(t, np.asarray(y, float), upper=up, lower=lo)
  self.draw_graph()
  if getattr(self.ax, "name", None) != "3d":
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
  got = self.analysis_xy_or_warn()
  if got is None:
   return
  t, y, label = got
  val = parse_eng(self.eye_rate.text(), 1e6)
  sym_period = (1.0 / val) if val and val > 1 else (val or 1e-6)
  phase, yy = eye_diagram(t, np.asarray(y, float), sym_period, n_ui=2)
  self.prepare_view_axes()
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
   self.adv_result.setText( "アイ測定: 振幅={:.4g} 高さ={:.4g} 幅={:.4g}µs Q={:.3g} " "ER={:.3g}dB ジッタpp={:.3g}ns".format( _g("eye_amplitude"), _g("eye_height"), _g("eye_width") * 1e6, _g("q_factor"), _g("extinction_ratio_db"), _g("jitter_pp") * 1e9))
  try:
   self.fig.tight_layout()
  except Exception:
   get_logger().debug("show_eye_diagram: 無視した例外", exc_info=True)
  self.canvas.draw()
  self._has_drawn = False
  self._set_status(f"アイダイアグラム表示: {label}")
 def run_jitter(self):
  import numpy as np
  got = self.analysis_xy_or_warn()
  if got is None:
   return
  t, y, label = got
  jr = jitter_tie(t, np.asarray(y, float))
  if not jr:
   self.notify("エッジが不足し計算できませんでした。", "warn")
   return
  msg = (f"ジッタ: RMS={format_eng(jr['rms'])}s  " f"pp={format_eng(jr['pp'])}s  " f"クロック≈{format_eng(jr['freq'])}Hz  エッジ{jr['edges']}本")
  self.adv_result.setText(msg)
  self._set_status(msg)
 def show_cycle_stats(self):
  import numpy as np
  got = self.analysis_xy_or_warn()
  if got is None:
   return
  t, y, label = got
  cm = cycle_measurements(t, np.asarray(y, float))
  fs = measurement_stats(cm["freq"])
  amps = measurement_stats(cm["vpp"])
  lines = []
  if fs["count"]:
   lines.append(f"周波数: 平均{format_eng(fs['mean'])}Hz σ={format_eng(fs['std'])} " f"min{format_eng(fs['min'])}〜max{format_eng(fs['max'])} ({fs['count']}サイクル)")
  if amps["count"]:
   lines.append(f"Vpp: 平均{amps['mean']:.4g} σ={amps['std']:.3g} " f"min{amps['min']:.4g}〜max{amps['max']:.4g}")
  self.adv_result.setText("　".join(lines) or "サイクルを検出できませんでした。")
  self._set_status(f"サイクル統計: {label}")
 def show_trend(self):
  import numpy as np
  got = self.analysis_xy_or_warn()
  if got is None:
   return
  t, y, label = got
  cm = cycle_measurements(t, np.asarray(y, float))
  if len(cm["cycle_time"]) < 2:
   self.notify("サイクルが不足しています。", "warn")
   return
  self.prepare_view_axes()
  self.ax.plot(cm["cycle_time"], cm["freq"], "-o", ms=3, color="#1f77b4")
  self.ax.set_xlabel("時間 [s]"); self.ax.set_ylabel("周波数 [Hz]")
  self.ax.set_title(f"周波数トレンド（サイクルごと）: {label}")
  self.ax.grid(True, alpha=0.3)
  try:
   self.fig.tight_layout()
  except Exception:
   get_logger().debug("show_trend: 無視した例外", exc_info=True)
  self.canvas.draw()
  self._has_drawn = False
  self._set_status(f"トレンド表示: {label}")
 def show_phase(self):
  import numpy as np
  t1, y1, l1 = self._analysis_xy()
  t2, y2 = self._xy_by_disp(self.phase_target2.currentText())
  if t1 is None or t2 is None:
   self.notify("解析対象と対象2を選択してください。", "warn")
   return
  delay, phase = phase_delay(t1, np.asarray(y1, float), np.asarray(y2, float))
  if delay is None:
   self.notify("計算できませんでした。", "warn")
   return
  ph = "-" if phase is None else f"{phase:.1f}°"
  msg = f"位相差/遅延（{l1} vs {self.phase_target2.currentText()}）: 遅延={format_eng(delay)}s  位相={ph}"
  self.adv_result.setText(msg); self._set_status(msg)
 def _on_proto_change(self, proto):
  cfg = { "UART": (["信号線", "", ""], "ボーレート", "115200"), "I2C": (["SCL", "SDA", ""], "不使用", ""), "SPI": (["SCK", "MOSI", "CS(任意)"], "不使用", ""), "CAN": (["CAN(RXまたは差動)", "", ""], "ビットレート", "500k"), "LIN": (["信号線", "", ""], "ボーレート", "19200"), "1-Wire": (["信号線", "", ""], "不使用", ""), }[proto]
  labels, baud_lbl, baud_val = cfg
  for i in range(3):
   show = labels[i] != ""
   self.proto_ch_labels[i].setText(labels[i]); self.proto_ch_labels[i].setVisible(show)
   self.proto_ch[i].setVisible(show)
  self.proto_baud.setEnabled(proto in ("UART", "CAN", "LIN"))
  if baud_val:
   self.proto_baud.setText(baud_val)
 def decode_protocol(self):
  import numpy as np
  proto = self.proto_combo.currentText()
  t1, y1 = self._xy_by_disp(self.proto_ch[0].currentText())
  if t1 is None:
   self.notify("Ch1（信号線）をデータタブで選択してください。", "warn")
   return
  try:
   if proto == "UART":
    baud = parse_eng(self.proto_baud.text(), 115200)
    ev = decode_uart(t1, np.asarray(y1, float), baud=baud)
    rows = [(e["time"], "data", e["hex"], (e["char"] + ("" if e["ok"] else " ⚠")).strip()) for e in ev]
   elif proto == "I2C":
    t2, y2 = self._xy_by_disp(self.proto_ch[1].currentText())
    if t2 is None:
     self.notify("SDA(Ch2)も選択してください。", "warn"); return
    ev = decode_i2c(t1, np.asarray(y1, float), np.asarray(y2, float))
    rows = []
    for e in ev:
     if e["type"] in ("START", "STOP"):
      rows.append((e["time"], e["type"], "", ""))
     else:
      rows.append((e["time"], e["type"], e["hex"], f"{e.get('rw','')} {e.get('ack','')}".strip()))
   elif proto == "SPI":
    t2, y2 = self._xy_by_disp(self.proto_ch[1].currentText())
    if t2 is None:
     self.notify("MOSI(Ch2)も選択してください。", "warn"); return
    cs = None
    if self.proto_ch[2].currentText():
     _, cs = self._xy_by_disp(self.proto_ch[2].currentText())
     cs = np.asarray(cs, float) if cs is not None else None
    ev = decode_spi(t1, np.asarray(y1, float), np.asarray(y2, float), cs=cs)
    rows = [(e["time"], "data", e["hex"], "") for e in ev]
   elif proto == "CAN":
    rate = parse_eng(self.proto_baud.text(), 500e3)
    ev = decode_can(t1, np.asarray(y1, float), bitrate=rate)
    rows = []
    for e in ev:
     idw = f"{e['id']:08X}" if e["ext"] else f"{e['id']:03X}"
     kind = ("CANx" if e["ext"] else "CAN") + ("/RTR" if e["rtr"] else "")
     note = f"DLC={e['dlc']}" + ("" if e["crc_ok"] else " CRC⚠")
     rows.append((e["time"], kind, f"ID={idw} [{e['hex']}]", note))
   elif proto == "LIN":
    baud = parse_eng(self.proto_baud.text(), 19200)
    ev = decode_lin(t1, np.asarray(y1, float), baud=baud)
    rows = []
    for e in ev:
     if e["type"] == "BREAK":
      rows.append((e["time"], "BREAK", "", ""))
     elif e["type"] == "PID":
      rows.append((e["time"], "PID", f"0x{e['value']:02X}", "" if e.get("ok") else "パリティ⚠"))
     elif e["type"] == "CSUM":
      rows.append((e["time"], "CSUM", f"0x{e['value']:02X}", "OK" if e.get("ok") else "不一致⚠"))
     else:
      rows.append((e["time"], e["type"], f"0x{e['value']:02X}", ""))
   else:
    ev = decode_onewire(t1, np.asarray(y1, float))
    rows = [(e["time"], e["type"], f"0x{e['value']:02X}" if e["type"] == "data" else "", "") for e in ev]
  except Exception as e:
   QtWidgets.QMessageBox.critical(self, "解読エラー", str(e)); return
  self.proto_table.setRowCount(len(rows))
  for r, (tm, kind, hexv, note) in enumerate(rows):
   self.proto_table.setItem(r, 0, QtWidgets.QTableWidgetItem(f"{tm*1e3:.4g} ms"))
   self.proto_table.setItem(r, 1, QtWidgets.QTableWidgetItem(str(kind)))
   self.proto_table.setItem(r, 2, QtWidgets.QTableWidgetItem(str(hexv)))
   self.proto_table.setItem(r, 3, QtWidgets.QTableWidgetItem(str(note)))
  self._proto_annotations = {"rows": rows, "proto": proto}
  if (getattr(self, "proto_overlay_check", None) and self.proto_overlay_check.isChecked() and self._has_drawn):
   self.draw_graph()
  self._set_status(f"{proto} 解読: {len(rows)} 件")
 def _on_proto_overlay_toggled(self, *_):
  if self.datasets and self._has_drawn:
   self.draw_graph()
 def _build_tab_advanced(self):
  outer = QtWidgets.QScrollArea(); outer.setWidgetResizable(True)
  w = QtWidgets.QWidget(); outer.setWidget(w)
  v = QtWidgets.QVBoxLayout(w)
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
  eg = QtWidgets.QGridLayout()
  eg.addWidget(QtWidgets.QLabel("数式"), 0, 0)
  self.math_expr = QtWidgets.QLineEdit()
  self.math_expr.setPlaceholderText("例: sqrt(A**2+B**2) / sin(2*pi*t)*VAR1 / A-VAR1")
  self.math_expr.setToolTip("変数: A=対象A, B=対象B, t=時間, VAR1, VAR2, 定数 pi/e。\n" "関数: sin/cos/tan/asin/.../exp/log/log10/log2/sqrt/abs/sign/min/max/clip/where。")
  eg.addWidget(self.math_expr, 0, 1, 1, 3)
  eg.addWidget(QtWidgets.QLabel("VAR1"), 1, 0)
  self.math_var1 = QtWidgets.QLineEdit("1"); eg.addWidget(self.math_var1, 1, 1)
  eg.addWidget(QtWidgets.QLabel("VAR2"), 1, 2)
  self.math_var2 = QtWidgets.QLineEdit("0"); eg.addWidget(self.math_var2, 1, 3)
  b_expr = QtWidgets.QPushButton("数式でチャンネル作成"); b_expr.clicked.connect(self.create_math_expr)
  eg.addWidget(b_expr, 2, 0, 1, 4)
  v.addLayout(eg)
  v.addWidget(self._hline())
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
  b_wf = QtWidgets.QPushButton("ウォーターフォール")
  b_wf.setToolTip("STFTの時間スライスを3Dに重ねて表示（周波数成分の時間変化を見る）。" "ドラッグで回転できます。")
  b_wf.clicked.connect(self.show_waterfall)
  fg.addWidget(b_wf, 1, 3, 1, 1)
  v.addLayout(fg)
  self.fft_metrics = QtWidgets.QTableWidget(0, 2)
  self.fft_metrics.setHorizontalHeaderLabels(["指標", "値"])
  self.fft_metrics.horizontalHeader().setStretchLastSection(True)
  self.fft_metrics.setMaximumHeight(170)
  self._wire_table_export(self.fft_metrics, "FFT指標")
  v.addWidget(self.fft_metrics)
  v.addWidget(self._hline())
  v.addWidget(self._bold("マスク試験 / アイダイアグラム / ジッタ"))
  mk = QtWidgets.QGridLayout()
  mk.addWidget(QtWidgets.QLabel("上限"), 0, 0)
  self.mask_upper = QtWidgets.QLineEdit(); self.mask_upper.setPlaceholderText("なし")
  self.mask_upper.setAccessibleName("マスク上限")
  mk.addWidget(self.mask_upper, 0, 1)
  mk.addWidget(QtWidgets.QLabel("下限"), 0, 2)
  self.mask_lower = QtWidgets.QLineEdit(); self.mask_lower.setPlaceholderText("なし")
  self.mask_lower.setAccessibleName("マスク下限")
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
  v.addWidget(self._bold("シリアルプロトコル解読"))
  pg = QtWidgets.QGridLayout()
  pg.addWidget(QtWidgets.QLabel("プロトコル"), 0, 0)
  self.proto_combo = QtWidgets.QComboBox()
  self.proto_combo.addItems(["UART", "I2C", "SPI", "CAN", "LIN", "1-Wire"])
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
  self.proto_overlay_check = QtWidgets.QCheckBox("解読結果をグラフに注記表示")
  self.proto_overlay_check.setToolTip( "解読したフレームの値を波形の上に直接注記します（Saleae風・先頭80件まで）。\n" "CRC/パリティ等の不一致は赤で表示。折れ線/散布図の2D表示で有効。")
  self.proto_overlay_check.toggled.connect(self._on_proto_overlay_toggled)
  pg.addWidget(self.proto_overlay_check, 5, 0, 1, 4)
  v.addLayout(pg)
  self.proto_table = QtWidgets.QTableWidget(0, 4)
  self.proto_table.setHorizontalHeaderLabels(["時刻", "種別", "値(hex)", "備考"])
  self.proto_table.horizontalHeader().setStretchLastSection(True)
  self._wire_table_export(self.proto_table, "プロトコル解読")
  v.addWidget(self.proto_table, 1)
  self._on_math_op_change(self.math_op.currentText())
  self._on_proto_change("UART")
  return outer
"""DataSciMixin: 「データサイエンス」タブの解析アクション。
選択中のY系列に対し、線形回帰（線形性）・記述統計・相関・正規性検定などを計算して表で表示する。
実体の計算は datasci モジュール（GUI 非依存）に置き、ここは取得→計算→表示の橋渡しに徹する。
"""
class DataSciMixin:
 def _ds_xy(self):
  disp = self.ds_target.currentText()
  if not disp:
   self.notify("データタブでY系列を選択してください。", "warn")
   return None, None, None
  t, y = self._xy_by_disp(disp)
  if t is None:
   self.notify("対象の数値データが取得できません。", "warn")
   return None, None, None
  return disp, t, y
 def _ds_show(self, title, rows):
  had = bool(getattr(self, "_ds_annotations", None))
  self._ds_annotations = []
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
   self.draw_graph()
 def _refresh_ds_annotations(self, *_):
  anns = []
  for r in range(self.ds_table.rowCount()):
   cb = self.ds_table.cellWidget(r, 2)
   if cb is not None and cb.isChecked():
    k = self.ds_table.item(r, 0)
    v = self.ds_table.item(r, 1)
    if k is not None and v is not None:
     anns.append(f"{k.text()} = {v.text()}")
  self._ds_annotations = anns
  if self.datasets:
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
 def run_regression(self):
  disp, t, y = self._ds_xy()
  if t is None:
   return
  d = linear_regression(t, y)
  if not d:
   self.notify("回帰に十分なデータがありません。", "warn")
   return
  f = self._fmt
  rows = [ ("点数 n", f(d["n"])), ("傾き slope", f(d["slope"])), ("切片 intercept", f(d["intercept"])), ("相関 r (ピアソン)", f(d["r"])), ("決定係数 R²", f(d["r2"])), ("p値 (傾き=0)", f(d["p_value"])), ("傾きの標準誤差", f(d["std_err"])), ("RMSE (残差)", f(d["rmse"])), ("直線性誤差 [%FS]", f(d["linearity_error_pct"])), ]
  sp = correlation(t, y, "spearman")
  if sp:
   rows.append(("相関 (スピアマン)", f(sp["r"])))
  self._ds_show(f"線形回帰: {disp}（Y vs X）", rows)
  if self.ds_fit_check.isChecked():
   self.trend_combo.setCurrentText("線形")
   self.draw_graph()
 def show_describe(self):
  disp, t, y = self._ds_xy()
  if t is None:
   return
  d = describe(y)
  if not d:
   self.notify("数値データがありません。", "warn")
   return
  f = self._fmt
  order = [ ("件数", "count"), ("平均", "mean"), ("中央値", "median"), ("標準偏差 σ", "std"), ("分散", "var"), ("最小", "min"), ("最大", "max"), ("範囲", "range"), ("変動係数 CV", "cv"), ("歪度 skew", "skew"), ("尖度 kurtosis", "kurtosis"), ("第1四分位 Q1", "p25"), ("中央 Q2", "p50"), ("第3四分位 Q3", "p75"), ("四分位範囲 IQR", "iqr"), ]
  self._ds_show(f"記述統計: {disp}", [(lbl, f(d.get(k))) for lbl, k in order])
 def run_normality(self):
  disp, t, y = self._ds_xy()
  if t is None:
   return
  d = normality(y)
  if not d:
   self.notify("正規性検定には scipy が必要です（または点数不足）。", "warn")
   return
  f = self._fmt
  rows = [ ("W統計量", f(d["W"])), ("p値", f(d["p_value"])), ("5%有意で正規とみなせる", f(d["normal_5pct"])), ]
  self._ds_show(f"正規性検定 (Shapiro-Wilk): {disp}", rows)
 def show_corr_matrix(self):
  items = self._selected_series_items()
  if len(items) < 2:
   self.notify("相関行列には2系列以上をデータタブで選択してください。", "warn")
   return
  named = []
  for fl, col, disp in items:
   t, y = self._xy_by_disp(disp)
   if y is not None:
    named.append((disp, y))
  names, mat = correlation_matrix(named, "pearson")
  if mat is None:
   self.notify("相関行列を計算できませんでした。", "warn")
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
 def run_custom_fit(self):
  disp, t, y = self._ds_xy()
  if t is None:
   return
  dlg = QtWidgets.QDialog(self)
  dlg.setWindowTitle(f"任意関数フィット: {disp}")
  form = QtWidgets.QFormLayout(dlg)
  last = getattr(self, "_fit_last", {})
  e_expr = QtWidgets.QLineEdit(last.get("expr", "a*exp(-x/b)+c"))
  e_expr.setToolTip("変数 x とパラメータ名で書くモデル式。\n" "使える関数: sin/cos/tan/exp/log/log10/sqrt/abs など" "（数学チャンネルの数式と同じ）。")
  e_par = QtWidgets.QLineEdit(last.get("params", "a, b, c"))
  e_par.setToolTip("フィットするパラメータ名（カンマ区切り）")
  e_p0 = QtWidgets.QLineEdit(last.get("p0", "1, 1, 0"))
  e_p0.setToolTip("各パラメータの初期値（カンマ区切り・パラメータ名と同順）")
  c_add = QtWidgets.QCheckBox("フィット曲線を新しいデータとして追加（グラフに重ねられる）")
  c_add.setChecked(True)
  form.addRow("モデル式 f(x) =", e_expr)
  form.addRow("パラメータ", e_par)
  form.addRow("初期値", e_p0)
  form.addRow(c_add)
  bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
  bb.accepted.connect(dlg.accept); bb.rejected.connect(dlg.reject)
  form.addRow(bb)
  if not dlg.exec():
   return
  expr = e_expr.text().strip()
  params = [p.strip() for p in e_par.text().split(",") if p.strip()]
  try:
   p0 = [float(v) for v in e_p0.text().split(",")]
  except ValueError:
   self.notify("初期値は数値をカンマ区切りで入力してください。", "warn")
   return
  if not expr or not params or len(p0) != len(params):
   self.notify("式・パラメータ名・初期値（同数）を入力してください。", "warn")
   return
  self._fit_last = {"expr": expr, "params": e_par.text(), "p0": e_p0.text()}
  try:
   d = fit_custom(t, y, expr, params, p0)
  except Exception as e:
   self.notify(f"フィットできませんでした:\n{e}\n\n" "初期値を変える・式を見直すと収束することがあります。", "warn")
   return
  if not d:
   self.notify("フィットに十分なデータがありません（要scipy・点数>パラメータ数+1）。", "warn")
   return
  f = self._fmt
  rows = [("モデル式", f"f(x) = {expr}"), ("点数 n", f(d["n"]))]
  for nm, v, err in d["params"]:
   rows.append((f"{nm}", f"{v:.6g} ± {err:.3g}"))
  rows += [("決定係数 R²", f(d["r2"])), ("RMSE (残差)", f(d["rmse"]))]
  self._ds_show(f"任意関数フィット: {disp}", rows)
  if c_add.isChecked():
   import pandas as pd
   xname = self.x_combo.currentText() or "x"
   df = pd.DataFrame({xname: d["x"], f"fit({disp})": d["yfit"]})
   self.register_dataset( f"FIT: {disp}", df, status=(f"フィット完了: R²={f(d['r2'])}。曲線を『{{label}}』として追加しました" "（ツリーでチェックすると重ね描きできます）。"))
  else:
   self._set_status(f"フィット完了: R²={f(d['r2'])}")
 def run_t_test(self):
  disp, t, y = self._ds_xy()
  if t is None:
   return
  others = [d for _fl, _c, d in self._selected_series_items() if d != disp]
  dlg = QtWidgets.QDialog(self)
  dlg.setWindowTitle(f"t検定: {disp}")
  form = QtWidgets.QFormLayout(dlg)
  kind = QtWidgets.QComboBox()
  kind.addItems(["1標本（母平均μ0と比較）", "対応なし2標本（Welch）", "対応あり2標本"])
  e_mu = QtWidgets.QLineEdit("0")
  cb_b = QtWidgets.QComboBox(); cb_b.addItems(others)
  form.addRow("種類", kind)
  form.addRow("μ0（1標本のとき）", e_mu)
  form.addRow("対象B（2標本のとき）", cb_b)
  bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
  bb.accepted.connect(dlg.accept); bb.rejected.connect(dlg.reject)
  form.addRow(bb)
  if not dlg.exec():
   return
  ki = kind.currentIndex()
  b = None
  if ki > 0:
   if not cb_b.currentText():
    self.notify("2標本の検定には対象Bの系列もデータタブで選択してください。", "warn")
    return
   _tb, b = self._xy_by_disp(cb_b.currentText())
  d = t_test(y, b=b, mu=_parse_float(e_mu.text(), 0.0) or 0.0, paired=(ki == 2))
  if not d:
   self.notify("t検定を計算できませんでした（要scipy・点数を確認）。", "warn")
   return
  f = self._fmt
  name = ["1標本", "対応なし(Welch)", "対応あり"][ki]
  rows = [("種類", name), ("平均 A", f(d["mean_a"]))]
  if d["mean_b"] is not None:
   rows.append(("平均 B", f(d["mean_b"])))
  rows += [("t統計量", f(d["t"])), ("p値", f(d["p_value"]))]
  if d["df"] is not None:
   rows.append(("自由度", f(d["df"])))
  rows.append(("5%有意差あり", f(d["sig_5pct"])))
  self._ds_show(f"t検定（{name}）: {disp}" + (f" vs {cb_b.currentText()}" if ki > 0 else ""), rows)
 def run_anova(self):
  items = self._selected_series_items()
  if len(items) < 2:
   self.notify("分散分析には2系列以上をデータタブで選択してください。", "warn")
   return
  groups = []
  for _fl, _c, disp in items:
   _t, y = self._xy_by_disp(disp)
   if y is not None:
    groups.append((disp, y))
  d = anova_oneway(groups)
  if not d:
   self.notify("分散分析を計算できませんでした（要scipy）。", "warn")
   return
  f = self._fmt
  rows = [("F統計量", f(d["F"])), ("p値", f(d["p_value"])), ("5%有意差あり", f(d["sig_5pct"]))]
  for name, n, mean, std in d["groups"]:
   rows.append((f"{name}", f"n={n}, 平均={mean:.6g}, σ={std:.6g}"))
  self._ds_show(f"一元配置ANOVA（{len(d['groups'])}群）", rows)
 def _build_tab_datasci(self):
  outer = QtWidgets.QScrollArea(); outer.setWidgetResizable(True)
  w = QtWidgets.QWidget(); outer.setWidget(w)
  v = QtWidgets.QVBoxLayout(w)
  v.addWidget(self._bold("統計解析（回帰・記述統計・相関・正規性）"))
  info = QtWidgets.QLabel("選択中のY系列を、現在のX軸列に対して解析します。" "データタブでX軸とY系列を選んでから実行してください。")
  info.setWordWrap(True); info.setStyleSheet("color:#555;")
  v.addWidget(info)
  row = QtWidgets.QHBoxLayout()
  row.addWidget(QtWidgets.QLabel("対象:"))
  self.ds_target = QtWidgets.QComboBox()
  self.ds_target.setToolTip("解析するY系列。データタブでY系列を選ぶと候補に出ます")
  row.addWidget(self.ds_target, 1)
  v.addLayout(row)
  b_reg = QtWidgets.QPushButton("線形回帰（Y vs X）")
  b_reg.setToolTip("傾き・切片・R²・相関r・直線性誤差[%FS] を計算（線形性の評価）")
  b_reg.clicked.connect(self.run_regression)
  self.ds_fit_check = QtWidgets.QCheckBox("回帰直線を重ねる")
  self.ds_fit_check.setToolTip("回帰実行時に近似曲線（線形）をグラフへ重ねて表示します")
  reg_row = QtWidgets.QHBoxLayout()
  reg_row.addWidget(b_reg); reg_row.addWidget(self.ds_fit_check); reg_row.addStretch(1)
  v.addLayout(reg_row)
  brow = QtWidgets.QHBoxLayout()
  b_desc = QtWidgets.QPushButton("記述統計"); b_desc.clicked.connect(self.show_describe)
  b_desc.setToolTip("平均/中央値/標準偏差/分散/歪度/尖度/四分位 など")
  b_norm = QtWidgets.QPushButton("正規性検定"); b_norm.clicked.connect(self.run_normality)
  b_norm.setToolTip("Shapiro-Wilk 検定（scipy 必要）")
  b_corr = QtWidgets.QPushButton("相関行列"); b_corr.clicked.connect(self.show_corr_matrix)
  b_corr.setToolTip("選択中の全Y系列どうしのピアソン相関を行列で表示")
  brow.addWidget(b_desc); brow.addWidget(b_norm); brow.addWidget(b_corr)
  v.addLayout(brow)
  brow2 = QtWidgets.QHBoxLayout()
  b_cfit = QtWidgets.QPushButton("任意関数フィット…")
  b_cfit.setToolTip("モデル式（例: a*exp(-x/b)+c）とパラメータ初期値を指定して\n" "非線形フィット。パラメータ±標準誤差とR²を表示し、\n" "フィット曲線を新データとして重ね描きできます（scipy 必要）。")
  b_cfit.clicked.connect(self.run_custom_fit)
  b_tt = QtWidgets.QPushButton("t検定…")
  b_tt.setToolTip("1標本（母平均と比較）／対応なし2標本（Welch）／対応あり2標本（scipy 必要）")
  b_tt.clicked.connect(self.run_t_test)
  b_an = QtWidgets.QPushButton("ANOVA")
  b_an.setToolTip("一元配置分散分析。選択中の全Y系列を群として比較します（scipy 必要）")
  b_an.clicked.connect(self.run_anova)
  brow2.addWidget(b_cfit); brow2.addWidget(b_tt); brow2.addWidget(b_an)
  v.addLayout(brow2)
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
  self._wire_table_export(self.ds_table, "統計解析")
  v.addWidget(self.ds_table, 1)
  return outer
class ThresholdTab(TabPlugin):
 key = "threshold"
 title = "5. しきい値"
 order = 50
 min_level = "全部"
 def build(self, app):
  w = QtWidgets.QWidget()
  lay = QtWidgets.QFormLayout(w)
  self.enabled = QtWidgets.QCheckBox("表示する")
  self.enabled.setChecked(True)
  self.enabled.toggled.connect(lambda: app.draw_graph())
  self.thr = QtWidgets.QLineEdit()
  self.thr.setPlaceholderText("例: 0.5")
  self.thr.editingFinished.connect(lambda: app.draw_graph())
  self.style = QtWidgets.QComboBox()
  self.style.addItems(["破線", "点線", "実線"])
  self.style.currentTextChanged.connect(lambda _text: app.draw_graph())
  lay.addRow("しきい値ライン", self.enabled)
  lay.addRow("Y値", self.thr)
  lay.addRow("線種", self.style)
  return w
 def draw_overlay(self, app, ax):
  if not getattr(self, "enabled", None) or not self.enabled.isChecked():
   return
  if not hasattr(ax, "axhline"):
   return
  text = self.thr.text().strip()
  if not text:
   return
  try:
   y = float(text)
  except ValueError:
   return
  style_map = { "破線": "--", "点線": ":", "実線": "-", }
  linestyle = style_map.get(self.style.currentText(), "--")
  ax.axhline(y, color="tab:red", linestyle=linestyle)
 def collect_config(self, app):
  return { "enabled": self.enabled.isChecked(), "thr": self.thr.text(), "style": self.style.currentText(), }
 def apply_config(self, app, cfg):
  self.enabled.blockSignals(True)
  self.thr.blockSignals(True)
  self.style.blockSignals(True)
  self.enabled.setChecked(bool(cfg.get("enabled", True)))
  self.thr.setText(str(cfg.get("thr", "")))
  style = str(cfg.get("style", "破線"))
  idx = self.style.findText(style)
  if idx >= 0:
   self.style.setCurrentIndex(idx)
  self.enabled.blockSignals(False)
  self.thr.blockSignals(False)
  self.style.blockSignals(False)
register_tab(ThresholdTab())
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
class HostMixin:
 def _tab_hook(self, name, *args, default=None):
  fn = getattr(self, name, None)
  return fn(*args) if callable(fn) else default
 def _draw_plugin_overlays(self):
  for plugin in registered_tabs():
   fn = getattr(plugin, "draw_overlay", None)
   if callable(fn):
    try:
     fn(self, self.ax)
    except Exception:
     get_logger().debug( "draw_overlay 失敗: %s", getattr(plugin, "key", "?"), exc_info=True)
 def _collect_plugin_config(self):
  out = {}
  for plugin in registered_tabs():
   fn = getattr(plugin, "collect_config", None)
   if callable(fn):
    try:
     out[plugin.key] = fn(self)
    except Exception:
     get_logger().debug( "collect_config 失敗: %s", getattr(plugin, "key", "?"), exc_info=True)
  return out
 def _apply_plugin_config(self, saved):
  if not isinstance(saved, dict):
   return
  for plugin in registered_tabs():
   fn = getattr(plugin, "apply_config", None)
   if callable(fn):
    try:
     fn(self, saved.get(plugin.key, {}))
    except Exception:
     get_logger().debug( "apply_config 失敗: %s", getattr(plugin, "key", "?"), exc_info=True)
 def series_xy(self, fl, col, gated=False):
  import numpy as np
  import pandas as pd
  df = self.datasets[fl]
  xname = self.x_combo.currentText()
  raw = df[xname].to_numpy() if xname in df.columns else df.iloc[:, 0].to_numpy()
  t = pd.to_numeric(pd.Series(raw), errors="coerce").to_numpy(dtype=float)
  if np.isnan(t).mean() > 0.5:
   t = np.arange(len(t), dtype=float)
  y = pd.to_numeric(pd.Series(df[col].to_numpy()), errors="coerce").to_numpy(dtype=float)
  if gated:
   t, y = self._apply_measure_window(t, y)
  return t, y
 def _xy_for(self, fl, col):
  return self.series_xy(fl, col, gated=True)
 def analysis_xy_or_warn(self, msg="解析対象の系列を選択してください。"):
  t, y, label = self._analysis_xy()
  if t is None:
   self.notify(msg, "warn")
   return None
  return t, y, label
 def prepare_view_axes(self, three_d=False, white_bg=True):
  self._ensure_axes_projection(three_d)
  self._reset_figure_axes()
  self.ax.clear()
  if white_bg:
   self.ax.set_facecolor("white")
   self.ax.tick_params(colors="black")
  return self.ax
 def _apply_measure_window(self, t, y):
  import numpy as np
  if self.window_meas_check.isChecked() and self._has_drawn:
   x0, x1 = self.ax.get_xlim()
   if x1 < x0:
    x0, x1 = x1, x0
   t_disp = axis_scale(t, self.xscale_edit.text())
   mask = (t_disp >= x0) & (t_disp <= x1)
   if int(mask.sum()) >= 3:
    t, y = t[mask], y[mask]
  return t, y
 def _analysis_xy(self):
  disp = self.analysis_target.currentText()
  for fl, col, d in self._selected_series_items():
   if d == disp:
    t, y = self._xy_for(fl, col)
    return t, y, d
  return None, None, None
 def _xy_by_disp(self, disp):
  for fl, col, d in self._selected_series_items():
   if d == disp:
    return self.series_xy(fl, col, gated=False)
  return None, None
 def register_dataset(self, base_label, df, *, path=None, enc="-", delim="-", status=None):
  label, i = base_label, 2
  while label in self.datasets:
   label = f"{base_label} ({i})"
   i += 1
  self.datasets[label] = df
  self.meta[label] = {"path": path if path is not None else label, "enc": enc, "delim": delim}
  self._add_file_item(label)
  self._refresh_columns()
  if status:
   self._set_status(status.format(label=label))
  return label
class UIBuildMixin:
 def _menu_action(self, menu, label, slot, shortcut=None, tip=None):
  act = QtGui.QAction(label, self)
  if shortcut:
   act.setShortcut(shortcut)
  if tip:
   act.setStatusTip(tip)
  act.triggered.connect(slot)
  menu.addAction(act)
  self._palette_register(menu.title(), label, act)
  return act
 def _palette_register(self, category, label, act):
  if not hasattr(self, "_all_actions"):
   self._all_actions = []
  if not isinstance(act, QtGui.QAction):
   get_logger().warning( "コマンドパレットに QAction 以外を登録しようとした: %s / %s (%s)", category, label, type(act).__name__)
   return
  cat = str(category).replace("&", "").replace("...", "").strip()
  self._all_actions.append((f"{cat} › {label.replace('&', '')}", act))
 def _build_menu(self):
  m = self.menuBar()
  fm = m.addMenu("ファイル(&F)")
  self._menu_action(fm, "ファイル追加...", self.add_file, "Ctrl+O")
  self._menu_action(fm, "フォルダを開く...", self.add_folder, "Ctrl+Shift+O", tip="フォルダ内の対応データファイルを一括読み込み。" "複数フォルダを開くとツリーがフォルダごとにグループ化されます")
  self._menu_action(fm, "クリップボードから貼り付け", self.paste_from_clipboard, "Ctrl+Shift+V", tip="Excel等からコピーした表を新規データとして読み込む")
  self.recent_menu = fm.addMenu("最近使ったファイル")
  self._rebuild_recent_menu()
  fm.addSeparator()
  self._watch_action = QtGui.QAction("ファイルの変更を監視して自動再読込", self)
  self._watch_action.setCheckable(True)
  self._watch_action.setStatusTip("読み込み済みファイルが外部で更新されたら自動で読み直して再描画します" "（測定器・ロガーのライブ監視向け）")
  self._watch_action.toggled.connect(self.toggle_file_watch)
  fm.addAction(self._watch_action)
  self._palette_register("ファイル", "ファイルの変更を監視して自動再読込", self._watch_action)
  fm.addSeparator()
  self._menu_action(fm, "グラフ画像を保存...", self.save_figure, "Ctrl+S")
  self._menu_action(fm, "ファイルごとに一括画像出力...", self.batch_export, "Ctrl+B")
  self._menu_action(fm, "Excelレポート出力...", self.export_excel_report, None, tip="現在のグラフ（ネイティブExcelグラフ）とデータ・解析結果の表を1つのExcelブックに出力")
  self._menu_action(fm, "クリップボードにコピー", self.copy_figure, "Ctrl+Shift+C")
  fm.addSeparator()
  self._menu_action(fm, "設定を保存...", self.save_config_dialog, "Ctrl+Shift+S")
  self._menu_action(fm, "設定を読み込み...", self.load_config_dialog, None)
  fm.addSeparator()
  self._menu_action(fm, "終了", self.close, "Ctrl+Q")
  em = m.addMenu("編集(&E)")
  self._menu_action(em, "元に戻す", self.undo, "Ctrl+Z", tip="書式・設定の変更を1つ戻す")
  self._menu_action(em, "やり直す", self.redo, "Ctrl+Y", tip="戻した変更をやり直す")
  vm = m.addMenu("表示(&V)")
  self.view_menu = vm
  level_menu = vm.addMenu("表示レベル")
  self._level_actions = {}
  level_group = QtGui.QActionGroup(self)
  level_group.setExclusive(True)
  _LEVEL_TIPS = { "基本": "読み込み→列選択→描画に必要な物だけを出す（隠れた設定も Ctrl+F で呼べます）", "標準": "基本＋オシロ/解析と主な書式", "全部": "すべてのパネル・設定を表示（従来と同じ）", }
  for lv in self.UI_LEVELS:
   act = QtGui.QAction(lv, self)
   act.setCheckable(True)
   act.setStatusTip(_LEVEL_TIPS[lv])
   act.triggered.connect(lambda _c=False, x=lv: self.set_ui_level(x))
   level_group.addAction(act)
   level_menu.addAction(act)
   self._level_actions[lv] = act
   self._palette_register("表示レベル", lv, act)
  vm.addSeparator()
  self._menu_action(vm, "コマンドパレット...", self.show_command_palette, "Ctrl+Shift+P", tip="すべてのメニュー操作を名前で検索して実行")
  self._menu_action(vm, "設定を検索...", self._focus_setting_search, "Ctrl+F", tip="設定名でパネルを横断検索し、その項目まで画面を移動します" "（設定はデータ・書式・描画バー・ツールバーに分かれているため）")
  vm.addSeparator()
  self._menu_action(vm, "グラフを描画", self.draw_graph, "F5")
  self._menu_action(vm, "新しいグラフウィンドウ（現在のグラフを複製）", self.open_graph_window, "Ctrl+G", tip="現在のグラフを独立ウィンドウに複製。選択・書式を変えて何枚も並べて比較できます")
  self._menu_action(vm, "全データに合わせる（オートスケール）", self.auto_scale_scope, None)
  am = m.addMenu("解析(&A)")
  self._menu_action(am, "解析実行（ピーク・測定）", self.run_analysis, "Ctrl+R", tip="選択中の解析対象系列のピーク・測定値を計算")
  self._menu_action(am, "FFTスペクトル表示", self.show_fft, None)
  tm = m.addMenu("ツール(&T)")
  self._menu_action(tm, "LTspiceシミュレーション実行(.asc)...", self.run_ltspice_asc, tip="LTspice回路をバッチ実行し、生成された .raw 波形を自動で読み込みます。" "回路(.asc)のドラッグ&ドロップでも実行できます")
  self._menu_action(tm, "LTspiceの場所を設定...", self.set_ltspice_path, tip="LTspice実行ファイル（LTspice.exe / XVIIx64.exe）の場所を指定")
  hm = m.addMenu("ヘルプ(&H)")
  self._menu_action(hm, "使い方", self.show_help, "F1")
  self._menu_action(hm, "バージョン情報", self.show_about, None)
 def show_command_palette(self):
  acts = list(getattr(self, "_all_actions", []))
  dlg = QtWidgets.QDialog(self)
  dlg.setWindowTitle("コマンドパレット")
  dlg.resize(560, 420)
  v = QtWidgets.QVBoxLayout(dlg)
  edit = QtWidgets.QLineEdit()
  edit.setPlaceholderText("コマンド名で検索（例: FFT ／ 保存 ／ 切り離し）")
  lst = QtWidgets.QListWidget()
  v.addWidget(edit)
  v.addWidget(lst, 1)
  def refill(text=""):
   tl = text.strip().lower()
   lst.clear()
   for name, a in acts:
    if tl and tl not in name.lower():
     continue
    try:
     if not a.isEnabled():
      continue
     sc = a.shortcut().toString()
    except RuntimeError:
     continue
    it = QtWidgets.QListWidgetItem(name + (f"　（{sc}）" if sc else ""))
    it.setData(UserRole, a)
    lst.addItem(it)
   if lst.count():
    lst.setCurrentRow(0)
  def run_current():
   it = lst.currentItem()
   if it is not None:
    act = it.data(UserRole)
    dlg.accept()
    try:
     act.trigger()
    except RuntimeError:
     self._set_status("この操作は現在実行できません。")
  edit.textChanged.connect(refill)
  edit.returnPressed.connect(run_current)
  lst.itemActivated.connect(lambda *_: run_current())
  class _Nav(QtCore.QObject):
   def eventFilter(self, _obj, ev):
    if (ev.type() == QtCore.QEvent.Type.KeyPress and ev.key() in (QtCore.Qt.Key.Key_Down, QtCore.Qt.Key.Key_Up)):
     step = 1 if ev.key() == QtCore.Qt.Key.Key_Down else -1
     lst.setCurrentRow(max(0, min(lst.count() - 1, lst.currentRow() + step)))
     return True
    return False
  nav = _Nav(dlg)
  edit.installEventFilter(nav)
  refill()
  edit.setFocus()
  self._palette_dlg = dlg
  dlg.exec()
 _UI_STYLES = {
 "standard": {
 "qss": """
QPushButton { padding: 4px 10px; min-height: 22px; }
QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox { min-height: 22px; }
""",
 "tb_style": "beside", "tb_icon": 24, "indent": 20},
 }
 def _apply_ui_style(self, name):
  style = self._UI_STYLES.get(name)
  if style is None:
   name = "standard"
   style = self._UI_STYLES.get(name)
  if style is None:
   return
  self._ui_style_name = name
  self._applying_ui_style = True
  try:
   self.setStyleSheet(render_qss(style["qss"]))
  finally:
   self._applying_ui_style = False
  tb = getattr(self, "main_toolbar", None)
  if tb is not None:
   tb.setIconSize(QtCore.QSize(style["tb_icon"], style["tb_icon"]))
   tb.setToolButtonStyle( QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon if style["tb_style"] == "beside" else QtCore.Qt.ToolButtonStyle.ToolButtonIconOnly)
  if hasattr(self, "explorer"):
   self.explorer.setIndentation(style["indent"])
  self._ui_settings().setValue("ui/style", name)
  self._apply_figure_theme()
 UI_LEVELS = ("基本", "標準", "全部")
 DEFAULT_UI_LEVEL = "全部"
 UI_LEVEL_KEY = "ui/level"
 _LEVEL_SECTIONS = { "基本": ("axes_sel", "labels", "legend"), "標準": ("file_ops", "axes_sel", "labels", "legend", "axis", "trend", "bins", "aspect", "export"), }
 _ALWAYS_DOCKS = ("dock_files", "dock_format")
 def ui_level(self):
  return getattr(self, "_ui_level", "全部")
 def set_ui_level(self, level, announce=True):
  if level not in self.UI_LEVELS:
   return
  self._apply_ui_level(level)
  self._ui_settings().setValue(self.UI_LEVEL_KEY, level)
  if announce:
   self.notify( f"表示レベル: {level}" + ("（隠れている設定も Ctrl+F で名前を入れれば出てきます）" if level != "全部" else ""), "info")
 def _apply_ui_level(self, level):
  if level not in self.UI_LEVELS:
   level = "全部"
  self._ui_level = level
  docks = self._all_docks()
  visible_docks = self._visible_dock_names(level)
  visible_sections = self._visible_section_keys(level)
  for d in docks:
   d.setVisible(d.objectName() in visible_docks)
  for key, box in getattr(self, "_fmt_sections", {}).items():
   box.setVisible(key in visible_sections)
  for d in docks:
   if d.objectName() in visible_docks and not d.isFloating():
    d.raise_()
    break
  if level != "全部":
   self._restore_dock_sizes()
  self._sync_level_ui()
  return level
 def _level_reaches(self, min_level, level):
  order = UI_LEVEL_ORDER
  try:
   return order.index(level) >= order.index(min_level)
  except ValueError:
   return True
 def _visible_dock_names(self, level=None):
  level = level or self.ui_level()
  if level == "全部":
   return {d.objectName() for d in self._all_docks()}
  names = set(self._ALWAYS_DOCKS)
  for oname, plugin in getattr(self, "_tab_plugins", {}).items():
   if self._level_reaches(plugin.min_level, level):
    names.add(oname)
  return names
 def _visible_section_keys(self, level=None):
  level = level or self.ui_level()
  if level not in self._LEVEL_SECTIONS:
   return set(getattr(self, "_fmt_sections", {}))
  return set(self._LEVEL_SECTIONS[level])
 def _all_docks(self):
  docks = [getattr(self, "files_dock", None)]
  docks += list(getattr(self, "left_docks", []))
  docks.append(getattr(self, "format_dock", None))
  return [d for d in docks if d is not None]
 def _restore_dock_sizes(self):
  try:
   left = getattr(self, "left_docks", None)
   if left:
    self.resizeDocks([left[0]], [360], QtCore.Qt.Orientation.Horizontal)
   fdock = getattr(self, "format_dock", None)
   if fdock is not None and not fdock.isHidden():
    self.resizeDocks([fdock], [400], QtCore.Qt.Orientation.Horizontal)
  except Exception:
   get_logger().debug("ドック幅の再設定に失敗", exc_info=True)
 def _sync_level_ui(self):
  for lv, act in getattr(self, "_level_actions", {}).items():
   act.blockSignals(True)
   act.setChecked(lv == self._ui_level)
   act.blockSignals(False)
  btn = getattr(self, "_level_button", None)
  if btn is not None:
   btn.setText(f"表示: {self._ui_level} ▾")
 def _effective_bg_color(self):
  user_bg = (getattr(self, "bg_color", "") or "").strip()
  if user_bg:
   return user_bg
  return palette_tokens()["base"] if is_dark_theme() else ""
 def _apply_figure_theme(self, redraw=True):
  fig = getattr(self, "fig", None)
  if fig is None:
   return
  try:
   face = self._effective_bg_color() or "white"
   fg = "#e6e6e6" if is_dark_bg(face) else "black"
   fig.set_facecolor(face)
   for ax in fig.get_axes():
    ax.tick_params(colors=fg, which="both")
    for spine in getattr(ax, "spines", {}).values():
     spine.set_color(fg)
    axes = [ax.xaxis, ax.yaxis] + ([ax.zaxis] if hasattr(ax, "zaxis") else [])
    for a in axes:
     a.label.set_color(fg)
    if ax.get_title():
     ax.title.set_color(fg)
    legend = ax.get_legend()
    if legend is not None:
     frame = legend.get_frame()
     frame.set_facecolor(face)
     frame.set_edgecolor(fg)
     for text in legend.get_texts():
      text.set_color(fg)
     title = legend.get_title()
     if title is not None:
      title.set_color(fg)
   canvas = getattr(self, "canvas", None)
   if canvas is not None and redraw:
    canvas.draw_idle()
  except Exception:
   get_logger().debug("グラフ配色の適用に失敗", exc_info=True)
 def _on_palette_changed(self, event_type):
  if event_type not in (QtCore.QEvent.Type.PaletteChange, QtCore.QEvent.Type.ThemeChange):
   return
  if getattr(self, "_applying_ui_style", False):
   return
  if not getattr(self, "_ui_style_name", None):
   return
  QtCore.QTimer.singleShot( 0, lambda: self._apply_ui_style(getattr(self, "_ui_style_name", None)))
 def _build_toolbar(self):
  tb = QtWidgets.QToolBar("メイン")
  tb.setObjectName("main_toolbar")
  tb.setMovable(False)
  tb.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
  self.main_toolbar = tb
  self.addToolBar(tb)
  SP = QtWidgets.QStyle.StandardPixmap
  def act(text, slot, tip, icon=None):
   if icon is not None:
    a = QtGui.QAction(self.style().standardIcon(icon), text, self)
   else:
    a = QtGui.QAction(text, self)
   a.setToolTip(tip)
   a.triggered.connect(slot)
   tb.addAction(a)
   return a
  act("ファイル追加", self.add_file, "CSV/TSV/波形ファイルを読み込む（Ctrl+O）。ウィンドウへのドラッグ&ドロップも可", SP.SP_DialogOpenButton)
  act("フォルダ", self.add_folder, "フォルダ内のデータファイルを一括読み込み（Ctrl+Shift+O）", SP.SP_DirOpenIcon)
  act("貼り付け", self.paste_from_clipboard, "Excel等からコピーした表を新規データとして読み込む（Ctrl+Shift+V）")
  tb.addSeparator()
  act("描画", self.draw_graph, "グラフを描画（F5）", SP.SP_BrowserReload)
  act("＋グラフ", self.open_graph_window, "現在のグラフを独立ウィンドウに複製（Ctrl+G）。何枚も並べて比較できます")
  tb.addSeparator()
  act("画像保存", self.save_figure, "グラフを画像ファイルに保存（Ctrl+S）", SP.SP_DialogSaveButton)
  act("コピー", self.copy_figure, "グラフ画像をクリップボードにコピー（Ctrl+Shift+C）")
  act("一括出力", self.batch_export, "読み込んだ各ファイルを個別に描画してまとめて画像保存（Ctrl+B）")
  tb.addSeparator()
  act("戻す", self.undo, "書式・設定の変更を1つ戻す（Ctrl+Z）", SP.SP_ArrowBack)
  act("やり直す", self.redo, "戻した変更をやり直す（Ctrl+Y）", SP.SP_ArrowForward)
 def _build_central(self):
  self.setDockOptions( QtWidgets.QMainWindow.DockOption.AnimatedDocks | QtWidgets.QMainWindow.DockOption.AllowTabbedDocks | QtWidgets.QMainWindow.DockOption.AllowNestedDocks)
  self.setTabPosition(QtCore.Qt.DockWidgetArea.LeftDockWidgetArea, QtWidgets.QTabWidget.TabPosition.North)
  left = QtCore.Qt.DockWidgetArea.LeftDockWidgetArea
  files_dock = QtWidgets.QDockWidget("読み込み済みファイル", self)
  files_dock.setObjectName("dock_files")
  files_dock.setWidget(self._scrollable(self._build_files_panel()))
  self.addDockWidget(left, files_dock)
  self.files_dock = files_dock
  self.left_docks = []
  self._tab_plugins = {}
  for plugin in registered_tabs():
   dock = QtWidgets.QDockWidget(plugin.title, self)
   dock.setObjectName("dock_" + plugin.key)
   w = plugin.build(self)
   if not isinstance(w, QtWidgets.QScrollArea):
    w = self._scrollable(w)
   dock.setWidget(w)
   self.addDockWidget(left, dock)
   self.left_docks.append(dock)
   self._tab_plugins[dock.objectName()] = plugin
  for d in self.left_docks[1:]:
   self.tabifyDockWidget(self.left_docks[0], d)
  center = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
  self.center_splitter = center
  center.addWidget(self._build_plot_area())
  center.addWidget(self._build_preview())
  center.setStretchFactor(0, 4)
  center.setStretchFactor(1, 1)
  holder = QtWidgets.QWidget()
  hlay = QtWidgets.QVBoxLayout(holder)
  hlay.setContentsMargins(0, 0, 0, 0)
  hlay.setSpacing(2)
  self.notify_bar = NotificationBar(holder)
  hlay.addWidget(self.notify_bar)
  self.progress_strip = ProgressStrip(holder)
  self.progress_strip.canceled.connect(self._cancel_background)
  hlay.addWidget(self.progress_strip)
  hlay.addWidget(center, 1)
  self.setCentralWidget(holder)
  fdock = QtWidgets.QDockWidget("グラフ書式調整", self)
  fdock.setObjectName("dock_format")
  fdock.setWidget(self._build_format_panel())
  self.addDockWidget(QtCore.Qt.DockWidgetArea.RightDockWidgetArea, fdock)
  self.format_dock = fdock
  self.left_docks[0].raise_()
  self.resizeDocks([self.left_docks[0]], [360], QtCore.Qt.Orientation.Horizontal)
  self.resizeDocks([fdock], [400], QtCore.Qt.Orientation.Horizontal)
  vm = self.view_menu
  vm.addSeparator()
  for d in [self.files_dock, *self.left_docks, fdock]:
   act = d.toggleViewAction()
   act.setStatusTip(f"{d.windowTitle()} パネルの表示/非表示")
   vm.addAction(act)
   self._palette_register("表示", f"{d.windowTitle()} パネルの表示/非表示", act)
  vm.addSeparator()
  float_menu = vm.addMenu("別ウィンドウで表示（切り離し）")
  self._float_actions = {}
  for d in [self.files_dock, *self.left_docks, fdock]:
   a = QtGui.QAction(d.windowTitle(), self)
   a.setCheckable(True)
   a.setStatusTip(f"{d.windowTitle()} を独立ウィンドウとして切り離す／チェックを外すと元の位置へ戻す")
   a.toggled.connect(lambda on, dd=d: self._set_dock_floating(dd, on))
   d.topLevelChanged.connect(lambda floating, aa=a: self._sync_float_action(aa, floating))
   d.topLevelChanged.connect(lambda floating, dd=d: self._native_float_frame(dd, floating))
   self._install_dock_native_filter(d)
   d.topLevelChanged.connect(self._wire_dock_tabbars)
   d.dockLocationChanged.connect(self._wire_dock_tabbars)
   float_menu.addAction(a)
   self._palette_register("表示", f"{d.windowTitle()} を別ウィンドウで表示", a)
   self._float_actions[d.objectName()] = a
  lay_menu = vm.addMenu("画面の配置")
  self._menu_action(lay_menu, "標準（3ペイン）", lambda: self._apply_layout_preset("standard"), tip="左パネル＋中央グラフ＋右書式の標準配置・標準の外観に戻す")
  self._menu_action(lay_menu, "グラフ集中（Saleae風）", lambda: self._apply_layout_preset("graph"), tip="パネルを全部たたみ、グラフをほぼ全画面に（波形をじっくり見る）")
  self._menu_action(lay_menu, "解析中心（オシロ）", lambda: self._apply_layout_preset("analysis"), tip="オシロ/解析パネル＋大きなグラフ＋データ表（測定作業向け）")
  self._menu_action(lay_menu, "データ整備", lambda: self._apply_layout_preset("data"), tip="データパネル＋大きなデータ編集表（読み込み・クレンジング向け）")
  vm.addSeparator()
  self._menu_action(vm, "メッセージ履歴…", self.show_message_log, tip="これまでのメッセージ・警告・エラーを一覧で見る")
  self._menu_action(vm, "パネル配置をリセット", self._reset_panel_layout, tip="パネルのドッキング配置・表示状態を初期状態に戻す")
  self.files_dock.setFloating(True)
  self.files_dock.resize(400, 620)
  self.files_dock.move(self.x() + 40, self.y() + 120)
  self._default_window_state = self.saveState()
  self._wire_dock_tabbars()
  self._wire_live_signals()
  self._add_tooltips()
  self._build_setting_index()
  self._apply_accessibility()
 def _install_dock_native_filter(self, dock):
  if not hasattr(self, "_dock_native_filter"):
   app = self
   class _F(QtCore.QObject):
    def eventFilter(self, obj, ev):
     t = ev.type()
     if (t == QtCore.QEvent.Type.NonClientAreaMouseButtonDblClick and isinstance(obj, QtWidgets.QDockWidget) and obj.isFloating()):
      app._redock(obj)
      return True
     if (t == QtCore.QEvent.Type.Move and isinstance(obj, QtWidgets.QDockWidget) and obj.isFloating()):
      app._note_float_move(obj)
     return False
   self._dock_native_filter = _F(self)
  dock.installEventFilter(self._dock_native_filter)
 def _redock(self, dock):
  area = self.dockWidgetArea(dock)
  if area == QtCore.Qt.DockWidgetArea.NoDockWidgetArea:
   area = QtCore.Qt.DockWidgetArea.LeftDockWidgetArea
  self.addDockWidget(area, dock)
  dock.setFloating(False)
  self._set_status(f"{dock.windowTitle()} をドッキングに戻しました。")
 def _note_float_move(self, dock):
  if getattr(self, "_float_move_dock", None) is not dock:
   self._float_move_dock = dock
   self._float_move_count = 0
  self._float_move_count += 1
  if not hasattr(self, "_float_move_timer"):
   self._float_move_timer = QtCore.QTimer(self)
   self._float_move_timer.setSingleShot(True)
   self._float_move_timer.timeout.connect( lambda: self._maybe_dock_on_drop(self._float_move_dock, QtGui.QCursor.pos()))
  self._float_move_timer.start(300)
 def _maybe_dock_on_drop(self, dock, pos):
  if (dock is None or not dock.isFloating() or getattr(self, "_float_move_count", 0) < 3):
   self._float_move_count = 0
   return
  self._float_move_count = 0
  screen = QtGui.QGuiApplication.screenAt(pos)
  if screen is not None:
   sg = screen.geometry()
   if (pos.x() - sg.left() <= 12 or sg.right() - pos.x() <= 12 or pos.y() - sg.top() <= 12 or sg.bottom() - pos.y() <= 12):
    return
  fg = self.frameGeometry()
  if not fg.contains(pos):
   return
  if pos.x() - fg.left() <= 160:
   self.addDockWidget(QtCore.Qt.DockWidgetArea.LeftDockWidgetArea, dock)
  elif fg.right() - pos.x() <= 160:
   self.addDockWidget(QtCore.Qt.DockWidgetArea.RightDockWidgetArea, dock)
  else:
   return
  dock.setFloating(False)
  self._set_status(f"{dock.windowTitle()} をドッキングしました" "（切り離しはタブのダブルクリック／表示メニューから）。")
 def _native_float_frame(self, dock, floating):
  if floating:
   size = dock.size()
   dock.setWindowFlags(QtCore.Qt.WindowType.Window)
   dock.show()
   if size.width() < 220 or size.height() < 180:
    size = QtCore.QSize(380, 520)
   dock.resize(size)
 def _set_dock_floating(self, dock, on):
  if dock.isFloating() == bool(on):
   return
  dock.setVisible(True)
  dock.setFloating(bool(on))
  if on:
   dock.raise_()
   self._set_status(f"{dock.windowTitle()} を別ウィンドウにしました。" "画面端へドラッグ=Windowsスナップ／メインウィンドウの左右端へ" "ドロップ or タイトルをダブルクリック=ドッキングに戻す")
 @staticmethod
 def _sync_float_action(action, floating):
  action.blockSignals(True)
  action.setChecked(bool(floating))
  action.blockSignals(False)
 def _wire_dock_tabbars(self, *_):
  for tb in self.findChildren(QtWidgets.QTabBar):
   if tb.parent() is not self or tb.property("_dock_dbl"):
    continue
   tb.setProperty("_dock_dbl", True)
   tb.setToolTip("ドラッグ=パネルの移動・切り離し／ダブルクリック=別ウィンドウ化")
   tb.tabBarDoubleClicked.connect( lambda i, bar=tb: self._float_dock_by_tab(bar, i))
 def _float_dock_by_tab(self, bar, index):
  title = bar.tabText(index)
  for d in [self.files_dock, *self.left_docks, self.format_dock]:
   if d.windowTitle() == title:
    d.setFloating(True)
    d.raise_()
    self._set_status(f"{title} を別ウィンドウにしました。" "画面端へドラッグ=Windowsスナップ／メインウィンドウの左右端へ" "ドロップ or タイトルをダブルクリック=ドッキングに戻す")
    return
 def _apply_layout_preset(self, name):
  if self.ui_level() != "全部":
   self._apply_ui_level("全部")
   self._ui_settings().setValue(self.UI_LEVEL_KEY, "全部")
  total = max(sum(self.center_splitter.sizes()), 400)
  for d in [self.files_dock, *self.left_docks, self.format_dock]:
   d.setFloating(False)
  tb = getattr(self, "main_toolbar", None)
  if tb is not None:
   self.addToolBar(QtCore.Qt.ToolBarArea.TopToolBarArea, tb)
  if name == "standard":
   self._reset_panel_layout()
   self.center_splitter.setSizes([int(total * 0.8), int(total * 0.2)])
   return
  if name == "graph":
   for d in [self.files_dock, *self.left_docks, self.format_dock]:
    d.hide()
   self.center_splitter.setSizes([total, 0])
   self._set_status("レイアウト: グラフ集中（パネルは表示メニュー、または" "レイアウト→標準 で戻せます）")
  elif name == "analysis":
   for d in [self.files_dock, *self.left_docks, self.format_dock]:
    d.hide()
   scope = self.left_docks[1]
   scope.show()
   self.addDockWidget(QtCore.Qt.DockWidgetArea.LeftDockWidgetArea, scope)
   self.resizeDocks([scope], [330], QtCore.Qt.Orientation.Horizontal)
   self.center_splitter.setSizes([int(total * 0.85), int(total * 0.15)])
   self._set_status("レイアウト: 解析中心（オシロ/解析＋グラフ）")
  elif name == "data":
   for d in [*self.left_docks, self.format_dock]:
    d.hide()
   self.files_dock.show()
   self.addDockWidget(QtCore.Qt.DockWidgetArea.LeftDockWidgetArea, self.files_dock)
   self.resizeDocks([self.files_dock], [380], QtCore.Qt.Orientation.Horizontal)
   self.center_splitter.setSizes([int(total * 0.45), int(total * 0.55)])
   self._set_status("レイアウト: データ整備（ファイルツリー＋データ編集表）")
 def _reset_panel_layout(self):
  if getattr(self, "_default_window_state", None) is not None:
   self.restoreState(self._default_window_state)
  for d in [*self.left_docks, self.format_dock]:
   d.setFloating(False)
   d.setVisible(True)
  self.files_dock.setVisible(True)
  tb = getattr(self, "main_toolbar", None)
  if tb is not None:
   self.addToolBar(QtCore.Qt.ToolBarArea.TopToolBarArea, tb)
   tb.show()
  self.left_docks[0].raise_()
  self._set_status("パネル配置を初期状態に戻しました。")
 def _build_files_panel(self):
  top = QtWidgets.QWidget(); tv = QtWidgets.QVBoxLayout(top)
  tv.setContentsMargins(4, 4, 4, 4)
  head = QtWidgets.QHBoxLayout()
  head.addWidget(self._bold("エクスプローラー"))
  head.addStretch(1)
  SP = QtWidgets.QStyle.StandardPixmap
  def tool(icon, tip, slot):
   b = QtWidgets.QToolButton()
   b.setIcon(self.style().standardIcon(icon))
   b.setToolTip(tip)
   b.setAutoRaise(True)
   b.clicked.connect(slot)
   head.addWidget(b)
  tool(SP.SP_FileIcon, "ファイルを追加（Ctrl+O）", self.add_file)
  tool(SP.SP_DirOpenIcon, "フォルダを開く（Ctrl+Shift+O）", self.add_folder)
  tool(SP.SP_BrowserReload, "すべてのファイルを再読込（ディスクの最新内容に更新）", self._reload_all_files)
  tool(SP.SP_TitleBarShadeButton, "すべて折りたたむ", lambda: self.explorer.collapseAll())
  tv.addLayout(head)
  hint = QtWidgets.QLabel("ファイルを追加（ここにドラッグ&ドロップも可）→ 描きたい列（Y軸）を" "チェック、または列をグラフへドラッグ →「グラフを描画」")
  hint.setWordWrap(True); hint.setStyleSheet("color:#666;")
  tv.addWidget(hint)
  self.file_list = QtWidgets.QListWidget()
  self.file_list.setVisible(False)
  self.file_list.setSelectionMode( QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
  self.file_list.currentRowChanged.connect(self._on_file_selected)
  self.file_list.currentRowChanged.connect(self._sync_explorer_current)
  self._explorer_building = False
  self.explorer = ExplorerTree()
  self.explorer.setColumnCount(2)
  self.explorer.setHeaderHidden(True)
  self.explorer.setSelectionMode( QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
  self.explorer.setAllColumnsShowFocus(True)
  self.explorer.setMinimumHeight(60)
  hdr = self.explorer.header()
  hdr.setStretchLastSection(False)
  hdr.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
  hdr.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
  self.explorer.setToolTip( "読み込んだファイルの一覧。▶で展開すると列（Y系列）が出ます。\n" "列の行クリック=チェックON/OFF／ダブルクリック=その列だけ表示／\n" "列やファイルを【グラフへドラッグ】=系列を追加して描画。\n" "ファイルのチェック=全列を一括ON/OFF。右クリックでメニュー\n" "（X軸にする・再読込・削除・エクスプローラーで表示など）。\n" "ファイル行はCtrl/Shift＋クリックで複数選択→「削除」でまとめて削除。\n" "F2=名前の変更／Delete=一覧から削除（ディスクのファイルは消しません）。")
  self.explorer.renameRequested.connect(self._on_tree_rename)
  self.explorer.deleteRequested.connect(self.remove_file)
  self.explorer.setStyleSheet( "QTreeWidget::item:hover { background: rgba(90, 93, 94, 0.10); }")
  self.explorer.itemChanged.connect(self._on_explorer_item_changed)
  self.explorer.itemDoubleClicked.connect(self._on_explorer_double_clicked)
  self.explorer.itemSelectionChanged.connect(self._on_explorer_selection_changed)
  self.explorer.currentItemChanged.connect(self._on_explorer_current_changed)
  self.explorer.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
  self.explorer.customContextMenuRequested.connect(self._explorer_menu)
  tv.addWidget(self.explorer, 1)
  row = QtWidgets.QHBoxLayout()
  b_add = QtWidgets.QPushButton("追加...")
  b_add.setToolTip("ファイル追加（Ctrl+O）。CSV/Excel/波形などを複数選択で読み込みます。\n" "ウィンドウへのドラッグ&ドロップ、フォルダごと開く（Ctrl+Shift+O）も可。")
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
  row.addWidget(b_del); row.addWidget(b_clear)
  tv.addLayout(row)
  yf = QtWidgets.QHBoxLayout()
  self.y_filter = QtWidgets.QLineEdit()
  self.y_filter.setPlaceholderText("名前で選択（例: 電圧）")
  self.y_filter.setToolTip("入力した名前を含む列（系列）だけを選択します（他は解除）。Enter でも実行。\n" "複数ファイルで同じ列名だけ選びたいときに便利です。")
  self.y_filter.returnPressed.connect(self.select_by_name)
  b_yf = QtWidgets.QPushButton("名前で選択"); b_yf.clicked.connect(self.select_by_name)
  yf.addWidget(self.y_filter, 1); yf.addWidget(b_yf)
  tv.addLayout(yf)
  ybtns = QtWidgets.QHBoxLayout()
  for text, fn in (("全選択", lambda: self._check_all_y(True)), ("全解除", lambda: self._check_all_y(False)), ("反転", self._invert_y)):
   btn = QtWidgets.QPushButton(text); btn.clicked.connect(fn)
   ybtns.addWidget(btn)
  tv.addLayout(ybtns)
  sec_load = self._fmt_section("読み込み設定（区切り・文字コード）", "file_ops", False)
  file_v = QtWidgets.QVBoxLayout()
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
  self.enc_combo.addItems(["自動判別", "utf-8-sig", "utf-8", "cp932", "shift_jis", "euc-jp", "utf-16"])
  self.enc_combo.setToolTip("文字化けする場合はここで指定し、「選択中ファイルを再読込」を押します。")
  grid.addWidget(self.enc_combo, 1, 1)
  b_reload = QtWidgets.QPushButton("選択中ファイルを再読込")
  b_reload.setToolTip("区切り・文字コードの変更を反映して読み直します。")
  b_reload.clicked.connect(self.reload_current)
  grid.addWidget(b_reload, 2, 0, 1, 2)
  file_v.addLayout(grid)
  sec_load.set_content_layout(file_v)
  tv.addWidget(sec_load)
  return top
 def _find_y_item(self, fl, col):
  for i in range(self.y_list.count()):
   it = self.y_list.item(i)
   if it.data(UserRole) == (fl, col):
    return it
  return None
 def _iter_file_nodes(self):
  tree = self.explorer
  for i in range(tree.topLevelItemCount()):
   top = tree.topLevelItem(i)
   d = top.data(0, UserRole)
   if d and d[0] == "file":
    yield top
   elif d and d[0] == "folder":
    for j in range(top.childCount()):
     yield top.child(j)
 def _rebuild_explorer(self):
  if not hasattr(self, "explorer"):
   return
  tree = self.explorer
  collapsed = set()
  def _collect_collapsed(item):
   d = item.data(0, UserRole)
   if d and not item.isExpanded():
    collapsed.add(d[:2])
   for j in range(item.childCount()):
    _collect_collapsed(item.child(j))
  for i in range(tree.topLevelItemCount()):
   _collect_collapsed(tree.topLevelItem(i))
  self._explorer_building = True
  tree.blockSignals(True)
  tree.clear()
  by_file = {}
  for i in range(self.y_list.count()):
   it = self.y_list.item(i)
   fl, _c = it.data(UserRole)
   by_file.setdefault(fl, []).append(it)
  ficon = self.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_FileIcon)
  dicon = self.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_DirIcon)
  gray = QtGui.QBrush(QtGui.QColor("#808080"))
  flags_file = (QtCore.Qt.ItemFlag.ItemIsEnabled | QtCore.Qt.ItemFlag.ItemIsSelectable | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
  flags_col = (QtCore.Qt.ItemFlag.ItemIsEnabled | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
  labels = [self.file_list.item(r).text() for r in range(self.file_list.count())]
  dirs = {os.path.dirname(self.meta.get(l, {}).get("path", "")) for l in labels}
  dirs.discard("")
  grouped = len(dirs) >= 2
  if not hasattr(self, "_icon_provider"):
   self._icon_provider = QtWidgets.QFileIconProvider()
  def make_file_node(label):
   df = self.datasets.get(label)
   path = self.meta.get(label, {}).get("path", "")
   node = QtWidgets.QTreeWidgetItem([label, ""])
   node.setData(0, UserRole, ("file", label))
   icon = ficon
   if path and os.path.isfile(path):
    try:
     icon = self._icon_provider.icon(QtCore.QFileInfo(path))
    except Exception:
     get_logger().debug("make_file_node: 無視した例外", exc_info=True)
   node.setIcon(0, icon)
   node.setFlags(flags_file)
   node.setCheckState(0, QtCore.Qt.CheckState.Unchecked)
   info = f"{len(df):,}×{len(df.columns)}" if df is not None else ""
   folder = "" if grouped else (os.path.basename(os.path.dirname(path)) if path else "")
   node.setText(1, f"{info}  {folder}".strip())
   node.setForeground(1, gray)
   tip = (path or label) + (f"\n{info.replace('×', ' 行 × ')} 列" if info else "")
   node.setToolTip(0, tip); node.setToolTip(1, tip)
   for yit in by_file.get(label, []):
    _fl, col = yit.data(UserRole)
    child = QtWidgets.QTreeWidgetItem([str(col), ""])
    child.setData(0, UserRole, ("col", label, col))
    child.setFlags(flags_col)
    child.setCheckState(0, yit.checkState())
    child.setToolTip(0, "クリック=チェックON/OFF／ダブルクリック=この列だけ表示／" "ドラッグ=グラフへ追加／右クリック=表示・X軸メニュー")
    node.addChild(child)
   node.setExpanded(("file", label) not in collapsed)
   return node
  def _dir_of(label):
   return os.path.dirname(self.meta.get(label, {}).get("path", ""))
  if grouped:
   nodir = sorted([l for l in labels if not _dir_of(l)], key=str.lower)
   bydir = {}
   for label in labels:
    dp = _dir_of(label)
    if dp:
     bydir.setdefault(dp, []).append(label)
   for dirpath in sorted(bydir, key=str.lower):
    fold = QtWidgets.QTreeWidgetItem( [os.path.basename(dirpath) or dirpath, ""])
    fold.setData(0, UserRole, ("folder", dirpath))
    fold.setIcon(0, dicon)
    fold.setFlags(QtCore.Qt.ItemFlag.ItemIsEnabled | QtCore.Qt.ItemFlag.ItemIsSelectable)
    fold.setToolTip(0, dirpath)
    fold.setForeground(1, gray)
    tree.addTopLevelItem(fold)
    for label in sorted(bydir[dirpath], key=str.lower):
     fnode = make_file_node(label)
     fold.addChild(fnode)
     fnode.setExpanded(("file", label) not in collapsed)
    fold.setText(1, f"{fold.childCount()}ファイル")
    fold.setExpanded(("folder", dirpath) not in collapsed)
   for label in nodir:
    node = make_file_node(label)
    tree.addTopLevelItem(node)
    node.setExpanded(("file", label) not in collapsed)
  else:
   for label in sorted(labels, key=str.lower):
    node = make_file_node(label)
    tree.addTopLevelItem(node)
    node.setExpanded(("file", label) not in collapsed)
  tree.blockSignals(False)
  self._explorer_building = False
  self._sync_explorer_checks()
  self._sync_explorer_current()
  self._on_explorer_selection_changed()
 def _sync_explorer_checks(self):
  if not hasattr(self, "explorer") or getattr(self, "_explorer_building", False):
   return
  self._explorer_building = True
  try:
   ymap = {}
   for i in range(self.y_list.count()):
    it = self.y_list.item(i)
    ymap[it.data(UserRole)] = it
   ck = QtCore.Qt.CheckState.Checked
   for node in self._iter_file_nodes():
    n_ck = 0
    for j in range(node.childCount()):
     child = node.child(j)
     _k, fl, col = child.data(0, UserRole)
     yit = ymap.get((fl, col))
     if yit is None:
      continue
     checked = yit.checkState() == ck
     child.setCheckState(0, ck if checked else QtCore.Qt.CheckState.Unchecked)
     n_ck += checked
     st = self.series_styles.get(self._style_key(fl, col)) or {}
     color = st.get("color") if checked else None
     child.setForeground(0, QtGui.QBrush(QtGui.QColor(color)) if color else QtGui.QBrush())
     f = child.font(0); f.setBold(checked); child.setFont(0, f)
    total = node.childCount()
    node.setCheckState(0, ck if (total and n_ck == total) else (QtCore.Qt.CheckState.PartiallyChecked if n_ck else QtCore.Qt.CheckState.Unchecked))
  finally:
   self._explorer_building = False
 def _sync_explorer_current(self, *_):
  if not hasattr(self, "explorer") or getattr(self, "_explorer_building", False):
   return
  it = self.file_list.currentItem()
  label = it.text() if it else None
  self._explorer_building = True
  try:
   for node in self._iter_file_nodes():
    if node.data(0, UserRole)[1] == label:
     if self.explorer.currentItem() is not node:
      self.explorer.setCurrentItem(node)
     break
  finally:
   self._explorer_building = False
 def _on_explorer_item_changed(self, item, column):
  if getattr(self, "_explorer_building", False) or column != 0:
   return
  data = item.data(0, UserRole)
  if not data:
   return
  if data[0] == "col":
   _k, fl, col = data
   yit = self._find_y_item(fl, col)
   if yit is not None and yit.checkState() != item.checkState(0):
    yit.setCheckState(item.checkState(0))
  else:
   label = data[1]
   on = item.checkState(0) == QtCore.Qt.CheckState.Checked
   ck = QtCore.Qt.CheckState.Checked
   self._set_all_checks(lambda it: on if it.data(UserRole)[0] == label else it.checkState() == ck)
 def _on_explorer_double_clicked(self, item, _column):
  data = item.data(0, UserRole)
  if data and data[0] == "col":
   yit = self._find_y_item(data[1], data[2])
   if yit is not None:
    self._on_y_double_clicked(yit)
 def _on_explorer_selection_changed(self):
  if getattr(self, "_explorer_building", False):
   return
  labels = {it.data(0, UserRole)[1] for it in self.explorer.selectedItems() if (it.data(0, UserRole) or ("",))[0] == "file"}
  self._explorer_building = True
  try:
   for i in range(self.file_list.count()):
    it = self.file_list.item(i)
    it.setSelected(it.text() in labels)
  finally:
   self._explorer_building = False
 def _on_explorer_current_changed(self, current, _previous):
  if getattr(self, "_explorer_building", False) or current is None:
   return
  data = current.data(0, UserRole)
  if not data or data[0] != "file":
   return
  it = self._find_file_item(data[1])
  if it is not None:
   row = self.file_list.row(it)
   if row != self.file_list.currentRow():
    self.file_list.setCurrentRow(row)
 def _explorer_menu(self, pos):
  item = self.explorer.itemAt(pos)
  if item is None:
   return
  gpos = self.explorer.viewport().mapToGlobal(pos)
  data = item.data(0, UserRole)
  if not data:
   return
  if data and data[0] == "col":
   _k, fl, col = data
   menu = self._series_menu(self._find_y_item(fl, col))
   menu.addSeparator()
   menu.addAction("この列をX軸にする", lambda: self._set_x_from_tree(col))
   menu.addAction("名前の変更（凡例ラベル）\tF2", lambda: self._on_tree_rename(item))
   menu.exec(gpos)
   return
  if data[0] == "folder":
   dirpath = data[1]
   labels = [item.child(j).data(0, UserRole)[1] for j in range(item.childCount())]
   menu = QtWidgets.QMenu(self)
   menu.addAction("フォルダ内を全チェック", lambda: self._check_labels_cols(labels, True))
   menu.addAction("フォルダ内を全解除", lambda: self._check_labels_cols(labels, False))
   menu.addSeparator()
   menu.addAction("フォルダ内のファイルを削除", lambda: (self._remove_labels(labels), self._set_status(f"{len(labels)}ファイルを削除しました。")))
   if os.path.isdir(dirpath):
    menu.addAction("エクスプローラーで開く", lambda: self._reveal_in_explorer(dirpath))
   menu.exec(gpos)
   return
  label = data[1]
  path = self.meta.get(label, {}).get("path", "")
  menu = QtWidgets.QMenu(self)
  menu.addAction("全列をチェック", lambda: self._check_file_cols(label, True))
  menu.addAction("全列を解除", lambda: self._check_file_cols(label, False))
  menu.addSeparator()
  menu.addAction("名前の変更...\tF2", lambda: self._on_tree_rename(item))
  menu.addAction("再読込", lambda: self._reload_label(label))
  menu.addAction("削除（一覧から）\tDel", lambda: (self._remove_labels([label]), self._set_status(f"{label} を削除しました。")))
  if path and os.path.isfile(path):
   menu.addSeparator()
   menu.addAction("エクスプローラーで表示", lambda: self._reveal_in_explorer(path))
   menu.addAction("パスをコピー", lambda: QtWidgets.QApplication.clipboard().setText(path))
  menu.exec(gpos)
 def _check_file_cols(self, label, on):
  self._check_labels_cols([label], on)
 def _check_labels_cols(self, labels, on):
  labelset = set(labels)
  ck = QtCore.Qt.CheckState.Checked
  self._set_all_checks(lambda it: on if it.data(UserRole)[0] in labelset else it.checkState() == ck)
  self._maybe_draw()
 def _reload_label(self, label):
  it = self._find_file_item(label)
  if it is not None:
   self.file_list.setCurrentRow(self.file_list.row(it))
   self.reload_current()
 def _set_x_from_tree(self, col):
  if self._use_leftmost_x():
   self._set_status("『一番左の列をX軸にする』がONのため、X軸は先頭列固定です。")
   return
  i = self.x_combo.findText(str(col))
  if i >= 0:
   self.x_combo.setCurrentIndex(i)
   self._set_status(f"X軸を「{col}」にしました。")
 def _drop_series(self, payload):
  added = []
  ck = QtCore.Qt.CheckState.Checked
  for line in payload.splitlines():
   if "\t" not in line:
    continue
   fl, col = line.split("\t", 1)
   yit = self._find_y_item(fl, col)
   if yit is not None and yit.checkState() != ck:
    yit.setCheckState(ck)
    added.append(str(col))
  if added:
   self.draw_graph()
   self._set_status("ドロップで追加: " + ", ".join(added[:8]) + (" ほか" if len(added) > 8 else ""))
  else:
   self._set_status("ドロップされた系列は既に表示されています。")
 def _on_tree_rename(self, item):
  data = item.data(0, UserRole)
  if not data:
   return
  if data[0] == "col":
   _k, fl, col = data
   skey = self._style_key(fl, col)
   st = self.series_styles.setdefault(skey, {})
   cur = st.get("label") or str(col)
   new, ok = QtWidgets.QInputDialog.getText( self, "系列名の変更", "凡例に表示する名前:", text=cur)
   new = (new or "").strip()
   if not ok or not new:
    return
   if new == str(col):
    st.pop("label", None)
   else:
    st["label"] = new
   self._on_y_selection_changed()
   if self._has_drawn:
    self.draw_graph()
  elif data[0] == "file":
   old = data[1]
   new, ok = QtWidgets.QInputDialog.getText( self, "名前の変更", "一覧に表示する名前（ディスクのファイル名は変わりません）:", text=old)
   new = (new or "").strip()
   if ok and new and new != old:
    self._rename_dataset_label(old, new)
 def _rename_dataset_label(self, old, new):
  if new in self.datasets:
   self.notify("同名のデータが既にあります。", "warn")
   return
  if old not in self.datasets:
   return
  checked = {(fl, c) for fl, c, _d in self._selected_series_items()}
  self.datasets[new] = self.datasets.pop(old)
  self.meta[new] = self.meta.pop(old, {"path": new, "enc": "-", "delim": "-"})
  prefix = old + "\t"
  for k in [k for k in self.series_styles if k.startswith(prefix)]:
   self.series_styles[new + "\t" + k.split("\t", 1)[1]] = self.series_styles.pop(k)
  it = self._find_file_item(old)
  if it is not None:
   it.setText(new)
  if getattr(self, "_preview_label", None) == old:
   self._preview_label = new
  self._refresh_columns()
  ck = QtCore.Qt.CheckState.Checked
  un = QtCore.Qt.CheckState.Unchecked
  self.y_list.blockSignals(True)
  for i in range(self.y_list.count()):
   yit = self.y_list.item(i)
   fl, c = yit.data(UserRole)
   key = (old, c) if fl == new else (fl, c)
   yit.setCheckState(ck if key in checked else un)
  self.y_list.blockSignals(False)
  self._on_y_selection_changed()
  if self._has_drawn:
   self.draw_graph()
  self._set_status(f"名前を変更しました: {old} → {new}（表示名のみ）")
 def _reveal_in_explorer(self, path):
  import subprocess
  try:
   subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
  except OSError:
   self._set_status("エクスプローラーを開けませんでした。")
 def _build_style_box(self):
  box = QtWidgets.QWidget()
  v = QtWidgets.QVBoxLayout(box); v.setContentsMargins(4, 4, 4, 4)
  hdr = self._bold("系列スタイル（系列名はダブルクリックで変更可）")
  hdr.setWordWrap(True)
  v.addWidget(hdr)
  self.style_table = QtWidgets.QTableWidget(0, 9)
  self.style_table.setHorizontalHeaderLabels( ["系列名", "色", "線種", "幅", "マーカー", "サイズ", "軸", "種別", "誤差列"])
  self.style_table.horizontalHeader().setStretchLastSection(True)
  self.style_table.setEditTriggers( QtWidgets.QAbstractItemView.EditTrigger.DoubleClicked | QtWidgets.QAbstractItemView.EditTrigger.EditKeyPressed)
  self.style_table.itemChanged.connect(self._on_style_label_edited)
  v.addWidget(self.style_table, 1)
  return box
 def _build_format_panel(self):
  wrap = QtWidgets.QWidget()
  outer = QtWidgets.QVBoxLayout(wrap)
  outer.setContentsMargins(0, 0, 0, 0)
  outer.setSpacing(2)
  self.setting_search = QtWidgets.QLineEdit()
  self.setting_search.setPlaceholderText("設定を検索（例: 凡例, 対数, DPI）")
  self.setting_search.setToolTip( "設定名の一部を入力して Enter。該当のパネルを開いて、その項目まで移動します。")
  self.setting_search.setAccessibleName("設定の検索")
  self.setting_search.setClearButtonEnabled(True)
  self.setting_search.returnPressed.connect(self._jump_to_setting)
  outer.addWidget(self.setting_search)
  split = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
  self.format_splitter = split
  scroll = QtWidgets.QScrollArea(); scroll.setWidgetResizable(True)
  scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
  scroll.setWidget(self._build_tab_graph())
  split.addWidget(scroll)
  split.addWidget(self._build_style_box())
  split.setStretchFactor(0, 3)
  split.setStretchFactor(1, 2)
  outer.addWidget(split, 1)
  return wrap
 def _build_setting_index(self):
  self._setting_index = []
  docks = [getattr(self, "files_dock", None), *getattr(self, "left_docks", []), getattr(self, "format_dock", None)]
  for dock in [d for d in docks if d is not None]:
   if dock.widget() is not None:
    self._index_widget(dock.widget(), dock, "", ["", None])
  for holder, section in ((getattr(self, "series_bar", None), "描画バー"), (getattr(self, "_preview_bar_host", None), "データ編集")):
   if holder is not None and holder.layout() is not None:
    self._index_layout(holder.layout(), None, section, ["", None])
  for w, name in ((getattr(self, "draw_button", None), "グラフを描画 (F5)"), (getattr(self, "live_check", None), "リアルタイム更新"), (getattr(self, "decimate_check", None), "間引き表示"), (getattr(self, "batch_button", None), "一括画像保存..."), (getattr(self, "_level_button", None), "表示レベルの切替"), (getattr(self, "_msg_button", None), "メッセージ履歴")):
   if w is not None and not any(e["widget"] is w for e in self._setting_index):
    self._setting_index.append( {"name": name, "section": "描画バー", "dock": None, "widget": w, "label": None})
  seen = {}
  for e in self._setting_index:
   label = f"{e['section']} › {e['name']}" if e["section"] else e["name"]
   seen[label] = seen.get(label, 0) + 1
   e["key"] = label if seen[label] == 1 else f"{label} ({seen[label]})"
  comp = QtWidgets.QCompleter([e["key"] for e in self._setting_index], self)
  comp.setCaseSensitivity(QtCore.Qt.CaseSensitivity.CaseInsensitive)
  comp.setFilterMode(QtCore.Qt.MatchFlag.MatchContains)
  comp.activated.connect(lambda text: QtCore.QTimer.singleShot( 0, lambda: self._jump_to_setting(text)))
  if hasattr(self, "setting_search"):
   self.setting_search.setCompleter(comp)
  return self._setting_index
 def _index_layout(self, layout, dock, section, last_label):
  for i in range(layout.count()):
   item = layout.itemAt(i)
   sub = item.layout()
   if sub is not None:
    self._index_layout(sub, dock, section, last_label)
    continue
   w = item.widget()
   if w is None:
    continue
   if isinstance(w, QtWidgets.QLabel) and w.property("section_header"):
    section = w.text().strip()
    last_label[0], last_label[1] = "", None
    continue
   self._index_widget(w, dock, section, last_label)
 def _index_widget(self, w, dock, section, last_label):
  controls = (QtWidgets.QAbstractButton, QtWidgets.QComboBox, QtWidgets.QLineEdit, QtWidgets.QAbstractSpinBox)
  if isinstance(w, QtWidgets.QLabel):
   text = w.text().strip()
   if text:
    last_label[0], last_label[1] = text, w
   return
  if isinstance(w, CollapsibleBox):
   if w.body.layout() is not None:
    self._index_layout(w.body.layout(), dock, w.title(), ["", None])
   return
  if isinstance(w, QtWidgets.QScrollArea):
   if w.widget() is not None:
    self._index_widget(w.widget(), dock, section, last_label)
   return
  if isinstance(w, QtWidgets.QSplitter):
   for i in range(w.count()):
    self._index_widget(w.widget(i), dock, section, last_label)
   return
  if isinstance(w, QtWidgets.QTabWidget):
   for i in range(w.count()):
    self._index_widget(w.widget(i), dock, w.tabText(i), ["", None])
   return
  if isinstance(w, QtWidgets.QGroupBox) and w.title().strip():
   section = w.title().strip()
  if isinstance(w, controls):
   own = ""
   if isinstance(w, QtWidgets.QAbstractButton):
    own = w.text()
   elif isinstance(w, QtWidgets.QLineEdit):
    own = w.placeholderText()
   name = (w.accessibleName() or own or last_label[0] or "").strip()
   name = name.replace("&", "").rstrip(":：") or name.replace("&", "").strip()
   if name:
    self._setting_index.append( {"name": name, "section": section, "dock": dock, "widget": w, "label": None if own else last_label[1]})
   return
  if w.layout() is not None:
   self._index_layout(w.layout(), dock, section, last_label)
 def _focus_setting_search(self):
  if not hasattr(self, "setting_search"):
   return
  if getattr(self, "format_dock", None) is not None:
   self.format_dock.show()
   self.format_dock.raise_()
  self.setting_search.setFocus()
  self.setting_search.selectAll()
 def _find_setting(self, text):
  needle = (text or "").strip().lower()
  if not needle:
   return None
  index = getattr(self, "_setting_index", None) or []
  for pred in (lambda e: e["key"].lower() == needle, lambda e: e["name"].lower() == needle, lambda e: e["name"].lower().startswith(needle), lambda e: needle in e["key"].lower()):
   for e in index:
    if pred(e):
     return e
  return None
 def _jump_to_setting(self, text=None):
  if text is None and hasattr(self, "setting_search"):
   text = self.setting_search.text()
  entry = self._find_setting(text)
  if entry is None:
   self.notify(f"「{text}」に一致する設定は見つかりませんでした。", "warn")
   return None
  w = entry["widget"]
  dock = entry["dock"]
  raised = self._raise_level_for(w)
  if dock is not None:
   dock.show()
   dock.raise_()
   if dock.isFloating():
    dock.activateWindow()
  p = w.parentWidget()
  while p is not None:
   if isinstance(p, CollapsibleBox):
    p.set_expanded(True)
   p = p.parentWidget()
  area = w.parentWidget()
  while area is not None and not isinstance(area, QtWidgets.QScrollArea):
   area = area.parentWidget()
  if isinstance(area, QtWidgets.QScrollArea):
   area.ensureWidgetVisible(w, 50, 50)
  w.setFocus(QtCore.Qt.FocusReason.ShortcutFocusReason)
  self._flash_widget(w)
  note = f"（表示レベルを「{self.ui_level()}」に上げました）" if raised else ""
  self._set_status(f"設定: {entry['key']}{note}")
  return entry
 def _raise_level_for(self, widget):
  if self.ui_level() == "全部":
   return False
  if widget.isVisibleTo(self):
   return False
  for level in self.UI_LEVELS[self.UI_LEVELS.index(self.ui_level()) + 1:]:
   self._apply_ui_level(level)
   self._ui_settings().setValue(self.UI_LEVEL_KEY, level)
   if widget.isVisibleTo(self):
    return True
  return True
 def _flash_widget(self, w, ms=1600):
  try:
   before = w.styleSheet()
   w.setStyleSheet(before + f"\nborder:2px solid {palette_tokens()['accent']};")
   QtCore.QTimer.singleShot(ms, lambda: w.setStyleSheet(before))
  except Exception:
   get_logger().debug("設定のハイライトに失敗", exc_info=True)
 _MNEMONICS = { "グラフを描画 (F5)": "D", "自動スケール": "A", "ファイル追加": "O", "フォルダを開く": "F", "解析実行": "R", "一括画像保存...": "B", "画像として保存": "S", }
 def _apply_accessibility(self):
  index = getattr(self, "_setting_index", None) or []
  per_dock = {}
  for e in index:
   w, label = e["widget"], e.get("label")
   if not w.accessibleName():
    w.setAccessibleName(e["key"])
   if not w.accessibleDescription() and w.toolTip():
    w.setAccessibleDescription(w.toolTip().replace("\n", " "))
   if label is not None and isinstance(label, QtWidgets.QLabel) \
                    and label.buddy() is None:
    label.setBuddy(w)
   if isinstance(w, QtWidgets.QAbstractButton):
    key = self._MNEMONICS.get(w.text())
    if key and "&" not in w.text():
     w.setText(f"{w.text()}(&{key})")
   per_dock.setdefault(id(e["dock"]), []).append(w)
  for widgets in per_dock.values():
   focusable = [w for w in widgets if w.focusPolicy() != QtCore.Qt.FocusPolicy.NoFocus]
   for prev, cur in zip(focusable, focusable[1:]):
    self.setTabOrder(prev, cur)
  canvas = getattr(self, "canvas", None)
  if canvas is not None:
   canvas.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
   canvas.setAccessibleName("グラフ")
   canvas.setAccessibleDescription( "描画したグラフ。ホイールで拡大縮小、ダブルクリックで全体表示。")
  for name, acc in (("explorer", "ファイルと列のツリー"), ("preview", "データ編集表"), ("style_table", "系列スタイル表"), ("y_list", "Y軸の系列一覧")):
   w = getattr(self, name, None)
   if w is not None and not w.accessibleName():
    w.setAccessibleName(acc)
  return index
 def _fmt_section(self, title, key, default_open):
  val = self._ui_settings().value("fmt_section/" + key)
  expanded = default_open if val is None else (str(val) in ("1", "true", "True"))
  box = CollapsibleBox(title, expanded=expanded)
  if not hasattr(self, "_fmt_sections"):
   self._fmt_sections = {}
  self._fmt_sections[key] = box
  return box
 def _build_tab_graph(self):
  w = QtWidgets.QWidget()
  v = QtWidgets.QVBoxLayout(w)
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
  self.stack_check = QtWidgets.QCheckBox("系列ごとに段を分ける（サブプロット）")
  self.stack_check.setToolTip( "各系列を上下の段に分けて描きます（X軸は共有・最大8段）。\n" "単位が違う系列の比較に便利。折れ線/散布図の2Dで有効。\n" "オシロ表示・第2軸・塗りつぶしとは併用できません（通常表示に戻ります）。\n" "一括画像出力には適用されません。")
  self.stack_check.setEnabled(False)
  v.addWidget(self.stack_check)
  sec_labels = self._fmt_section("タイトル・軸ラベル・文字", "labels", True)
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
  form.addWidget(QtWidgets.QLabel("文字サイズ 凡例/注記"), 5, 0)
  self.fs_legend = QtWidgets.QSpinBox(); self.fs_legend.setRange(6, 40); self.fs_legend.setValue(9)
  self.fs_legend.setToolTip("凡例の文字サイズ")
  self.fs_annot = QtWidgets.QSpinBox(); self.fs_annot.setRange(6, 40); self.fs_annot.setValue(9)
  self.fs_annot.setToolTip("グラフ上に表示する注記（統計解析・測定値のチェック表示）の文字サイズ")
  form.addWidget(self.fs_legend, 5, 1); form.addWidget(self.fs_annot, 5, 2)
  form.addWidget(QtWidgets.QLabel("X単位"), 3, 0)
  self.xunit_edit = QtWidgets.QLineEdit(); self.xunit_edit.setPlaceholderText("例: ms")
  self.xunit_edit.setToolTip("X軸ラベルに付ける単位。右の倍率で軸の数値も換算されます。")
  form.addWidget(self.xunit_edit, 3, 1)
  form.addWidget(QtWidgets.QLabel("X倍率/式"), 3, 2)
  self.xscale_edit = QtWidgets.QLineEdit("1")
  self.xscale_edit.setToolTip("X軸の数値変換。数値なら倍率（例: 1000）。\n" "x を使った式も可: x*9/5+32（℃→℉）, 20*log10(x), (x-273.15) など。")
  form.addWidget(self.xscale_edit, 3, 3)
  form.addWidget(QtWidgets.QLabel("Y単位"), 4, 0)
  self.yunit_edit = QtWidgets.QLineEdit(); self.yunit_edit.setPlaceholderText("例: mV")
  self.yunit_edit.setToolTip("Y軸ラベルに付ける単位。右の倍率で軸の数値も換算されます（主軸）。")
  form.addWidget(self.yunit_edit, 4, 1)
  form.addWidget(QtWidgets.QLabel("Y倍率/式"), 4, 2)
  self.yscale_edit = QtWidgets.QLineEdit("1")
  self.yscale_edit.setToolTip("Y軸の数値変換（主軸）。数値なら倍率（例: 1000）。\n" "y の代わりに x を使った式も可: 20*log10(x), x**2, abs(x) など。")
  form.addWidget(self.yscale_edit, 4, 3)
  sec_labels.set_content_layout(form)
  v.addWidget(sec_labels)
  sec_leg = self._fmt_section("凡例・グリッド・背景・枠線", "legend", True)
  leg_v = QtWidgets.QVBoxLayout()
  opt = QtWidgets.QHBoxLayout()
  self.grid_check = QtWidgets.QCheckBox("グリッド"); self.grid_check.setChecked(True)
  self.legend_check = QtWidgets.QCheckBox("凡例"); self.legend_check.setChecked(True)
  opt.addWidget(self.grid_check); opt.addWidget(self.legend_check)
  opt.addWidget(QtWidgets.QLabel("凡例位置"))
  self.legend_loc = QtWidgets.QComboBox(); self.legend_loc.addItems(LEGEND_LOCS)
  opt.addWidget(self.legend_loc)
  self.show_filename_check = QtWidgets.QCheckBox("凡例にファイル名"); self.show_filename_check.setChecked(True)
  self.show_filename_check.setToolTip("複数ファイル時、凡例の系列名に『ファイル名 | 列名』のように\n" "ファイル名を含めます。オフにすると列名だけになります。")
  self.show_ext_check = QtWidgets.QCheckBox("拡張子"); self.show_ext_check.setChecked(True)
  self.show_ext_check.setToolTip("凡例に表示するファイル名に拡張子（.csv など）を含めます。\n" "オフにすると拡張子を除いた名前になります。")
  opt2 = QtWidgets.QHBoxLayout()
  opt2.addWidget(self.show_filename_check); opt2.addWidget(self.show_ext_check)
  self.bg_color = ""
  self.bg_btn = QtWidgets.QPushButton("背景色: 自動")
  self.bg_btn.setToolTip("プロット領域の背景色。クリックで色を選択／右クリックで自動に戻す。\n" "『自動』は通常=白・オシロ=濃色。オシロでも好きな色にできます。")
  self._wire_color_button("bg")
  opt2.addWidget(self.bg_btn)
  opt.addStretch(1); opt2.addStretch(1)
  leg_v.addLayout(opt); leg_v.addLayout(opt2)
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
  leg_v.addLayout(lw)
  sec_leg.set_content_layout(leg_v)
  v.addWidget(sec_leg)
  sec_axis = self._fmt_section("軸範囲・目盛り・対数・反転", "axis", False)
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
  ax.addWidget(QtWidgets.QLabel("目盛り間隔 X/Y"), 2, 0)
  self.xtick_edit = QtWidgets.QLineEdit(); self.xtick_edit.setPlaceholderText("自動")
  self.xtick_edit.setToolTip("X軸の目盛り間隔（1メモリの値）。空欄=自動。例: 0.5。\n" "折れ線/散布図の数値軸で有効。対数軸・カテゴリ軸では無効。")
  self.ytick_edit = QtWidgets.QLineEdit(); self.ytick_edit.setPlaceholderText("自動")
  self.ytick_edit.setToolTip("Y軸の目盛り間隔（1メモリの値）。空欄=自動。例: 10。対数軸では無効。")
  ax.addWidget(self.xtick_edit, 2, 1); ax.addWidget(self.ytick_edit, 2, 2)
  ax.addWidget(QtWidgets.QLabel("軸反転"), 3, 0)
  self.xinvert_check = QtWidgets.QCheckBox("X軸反転")
  self.xinvert_check.setToolTip("X軸の向きを反転します（例: 0→1 を 1→0 に）。")
  self.yinvert_check = QtWidgets.QCheckBox("Y軸反転")
  self.yinvert_check.setToolTip("Y軸の向きを反転します（例: 下→上 を 上→下 に）。")
  ax.addWidget(self.xinvert_check, 3, 1); ax.addWidget(self.yinvert_check, 3, 2)
  sec_axis.set_content_layout(ax)
  v.addWidget(sec_axis)
  sec_trend = self._fmt_section("近似曲線・データラベル", "trend", False)
  trend_v = QtWidgets.QVBoxLayout()
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
  tl2 = QtWidgets.QHBoxLayout()
  self.trend_color = ""
  self.trend_color_btn = QtWidgets.QPushButton("色: 自動")
  self.trend_color_btn.setToolTip("近似曲線の色。クリックで色を選択／右クリックで自動（系列と同じ色）に戻す。")
  self._wire_color_button("trend")
  tl2.addWidget(self.trend_color_btn)
  self.trend_eq = QtWidgets.QCheckBox("数式/R²"); self.trend_eq.setChecked(True)
  tl2.addWidget(self.trend_eq)
  self.data_labels_check = QtWidgets.QCheckBox("データラベル")
  self.data_labels_check.setToolTip("各データ点/棒に値を表示（点数が多い場合は間引き）")
  tl2.addWidget(self.data_labels_check)
  tl.addStretch(1); tl2.addStretch(1)
  trend_v.addLayout(tl); trend_v.addLayout(tl2)
  sec_trend.set_content_layout(trend_v)
  v.addWidget(sec_trend)
  sec_fill = self._fmt_section("系列間の塗りつぶし", "fill", False)
  fill_v = QtWidgets.QVBoxLayout()
  fl_ = QtWidgets.QHBoxLayout()
  self.fill_check = QtWidgets.QCheckBox("系列間を塗りつぶし")
  self.fill_check.setToolTip("2つの系列の間（または系列とX軸=0の間）を色で塗ります。折れ線/散布図で有効。")
  fl_.addWidget(self.fill_check)
  fl_.addWidget(QtWidgets.QLabel("A"))
  self.fill_a = QtWidgets.QComboBox(); fl_.addWidget(self.fill_a, 1)
  fl_.addWidget(QtWidgets.QLabel("B"))
  self.fill_b = QtWidgets.QComboBox(); fl_.addWidget(self.fill_b, 1)
  fl2 = QtWidgets.QHBoxLayout()
  self.fill_color = ""
  self.fill_color_btn = QtWidgets.QPushButton("色: 自動")
  self.fill_color_btn.setToolTip("塗りつぶしの色。クリックで選択／右クリックで自動（系列Aの色）に戻す。")
  self._wire_color_button("fill")
  fl2.addWidget(self.fill_color_btn)
  fl2.addWidget(QtWidgets.QLabel("濃さ"))
  self.fill_alpha = QtWidgets.QDoubleSpinBox()
  self.fill_alpha.setRange(0.05, 1.0); self.fill_alpha.setSingleStep(0.05); self.fill_alpha.setValue(0.3)
  self.fill_alpha.setToolTip("塗りつぶしの不透明度（0.05〜1.0）")
  fl2.addWidget(self.fill_alpha)
  fl2.addStretch(1)
  fill_v.addLayout(fl_); fill_v.addLayout(fl2)
  sec_fill.set_content_layout(fill_v)
  v.addWidget(sec_fill)
  sec_bins = self._fmt_section("ヒストグラム・円のオプション", "bins", False)
  extra = QtWidgets.QHBoxLayout()
  self.bins_caption = QtWidgets.QLabel("ビン数:")
  extra.addWidget(self.bins_caption)
  self.bins_spin = QtWidgets.QSpinBox(); self.bins_spin.setRange(1, 500); self.bins_spin.setValue(30)
  extra.addWidget(self.bins_spin)
  self.pct_check = QtWidgets.QCheckBox("円グラフ％表示"); self.pct_check.setChecked(True)
  extra.addWidget(self.pct_check); extra.addStretch(1)
  sec_bins.set_content_layout(extra)
  v.addWidget(sec_bins)
  sec_ar = self._fmt_section("縦横比", "aspect", False)
  ar = QtWidgets.QHBoxLayout()
  ar.addWidget(QtWidgets.QLabel("縦横比"))
  self.aspect_combo = QtWidgets.QComboBox()
  self.aspect_combo.addItems(["自動（画面に合わせる）", "16:9", "4:3", "3:2", "1:1", "9:16（縦）", "A4横", "A4縦", "カスタム"])
  self.aspect_combo.setToolTip("プロット領域の縦横比を固定します（画面表示・画像出力の両方に反映）。" "「自動」はウィンドウに合わせます。")
  ar.addWidget(self.aspect_combo)
  ar.addWidget(QtWidgets.QLabel("カスタム W:H"))
  self.aspect_w = QtWidgets.QSpinBox(); self.aspect_w.setRange(1, 100); self.aspect_w.setValue(16)
  self.aspect_w.setAccessibleName("縦横比 横")
  self.aspect_h = QtWidgets.QSpinBox(); self.aspect_h.setRange(1, 100); self.aspect_h.setValue(9)
  self.aspect_h.setAccessibleName("縦横比 縦")
  ar.addWidget(self.aspect_w); ar.addWidget(QtWidgets.QLabel(":")); ar.addWidget(self.aspect_h)
  ar.addStretch(1)
  sec_ar.set_content_layout(ar)
  v.addWidget(sec_ar)
  self.aspect_combo.currentTextChanged.connect(self._on_aspect_changed)
  self._on_aspect_changed()
  sec_exp = self._fmt_section("出力（画像・Excelレポート）", "export", True)
  exp_v = QtWidgets.QVBoxLayout()
  exp = QtWidgets.QHBoxLayout()
  exp.addWidget(QtWidgets.QLabel("解像度 DPI"))
  self.dpi_spin = QtWidgets.QSpinBox()
  self.dpi_spin.setRange(50, 1200); self.dpi_spin.setSingleStep(50); self.dpi_spin.setValue(150)
  exp.addWidget(self.dpi_spin)
  self.transparent_check = QtWidgets.QCheckBox("背景透過")
  exp.addWidget(self.transparent_check)
  exp.addStretch(1)
  exp_v.addLayout(exp)
  exp2 = QtWidgets.QHBoxLayout()
  b_save = QtWidgets.QPushButton("画像を保存...")
  b_save.clicked.connect(self.save_figure)
  b_copy = QtWidgets.QPushButton("クリップボードにコピー")
  b_copy.clicked.connect(self.copy_figure)
  exp2.addWidget(b_save); exp2.addWidget(b_copy)
  exp_v.addLayout(exp2)
  b_batch = QtWidgets.QPushButton("ファイルごとに一括出力...")
  b_batch.setToolTip("読み込んだ各ファイルを、現在の設定（種別・選択列名・スタイル等）で" "個別に描画し、ファイル名ごとの画像として一括保存します。")
  b_batch.clicked.connect(self.batch_export)
  exp_v.addWidget(b_batch)
  b_xlsx = QtWidgets.QPushButton("Excelレポート出力...")
  b_xlsx.setToolTip("現在のグラフ（ネイティブExcelグラフ）とデータ・解析結果の表を\n" "1つのExcelブックに出力します。")
  b_xlsx.clicked.connect(self.export_excel_report)
  exp_v.addWidget(b_xlsx)
  sec_exp.set_content_layout(exp_v)
  v.addWidget(sec_exp)
  v.addStretch(1)
  return w
 def _build_plot_area(self):
  wrap = QtWidgets.QWidget()
  lay = QtWidgets.QVBoxLayout(wrap); lay.setContentsMargins(0, 0, 0, 0)
  drawbar = QtWidgets.QHBoxLayout()
  drawbar.setContentsMargins(6, 4, 6, 0)
  b_draw = QtWidgets.QPushButton("グラフを描画 (F5)")
  b_draw.setStyleSheet("font-weight:bold;")
  b_draw.clicked.connect(self.draw_graph)
  self.draw_button = b_draw
  drawbar.addWidget(b_draw)
  self.live_check = QtWidgets.QCheckBox("リアルタイム更新")
  self.live_check.setChecked(True)
  self.live_check.setToolTip("オンにすると設定変更が自動で描画に反映されます。大容量データではオフ推奨。")
  drawbar.addWidget(self.live_check)
  self.decimate_check = QtWidgets.QCheckBox("間引き表示")
  self.decimate_check.setChecked(True)
  self.decimate_check.setToolTip("折れ線/散布図で点数が多いとき、見た目を保ったまま間引いて高速描画します" "（ズーム時は自動で再サンプルします）。")
  drawbar.addWidget(self.decimate_check)
  drawbar.addStretch(1)
  b_batch2 = QtWidgets.QPushButton("一括画像保存...")
  b_batch2.setToolTip("読み込んだ各ファイルを個別に描画し、ファイル名ごとの画像として一括保存します" "（タイトル・形式・DPI等は次の画面で調整できます）。")
  b_batch2.clicked.connect(self.batch_export)
  self.batch_button = b_batch2
  drawbar.addWidget(b_batch2)
  lay.addLayout(drawbar)
  self.series_bar = QtWidgets.QWidget()
  sb_lay = QtWidgets.QHBoxLayout(self.series_bar)
  sb_lay.setContentsMargins(6, 2, 6, 2)
  sb_lay.setSpacing(4)
  self.series_filter = QtWidgets.QLineEdit()
  self.series_filter.setPlaceholderText("系列を絞り込み")
  self.series_filter.setToolTip("入力した文字を含む系列だけをこのバーに表示します。")
  self.series_filter.setAccessibleName("系列の絞り込み")
  self.series_filter.setClearButtonEnabled(True)
  self.series_filter.setFixedWidth(140)
  self.series_filter.textChanged.connect(lambda _t: self._rebuild_series_bar())
  sb_lay.addWidget(self.series_filter)
  self._series_scroll = QtWidgets.QScrollArea()
  self._series_scroll.setWidgetResizable(True)
  self._series_scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
  self._series_scroll.setHorizontalScrollBarPolicy( QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
  self._series_scroll.setVerticalScrollBarPolicy( QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
  bar_inner = QtWidgets.QWidget()
  self.series_bar_layout = QtWidgets.QHBoxLayout(bar_inner)
  self.series_bar_layout.setContentsMargins(0, 0, 0, 0)
  self._series_scroll.setWidget(bar_inner)
  sb_lay.addWidget(self._series_scroll, 1)
  self.series_more_btn = QtWidgets.QPushButton("他0件…")
  self.series_more_btn.setToolTip("バーに収まらない系列を一覧から選びます。")
  self.series_more_btn.setAccessibleName("残りの系列を一覧から選ぶ")
  self.series_more_btn.clicked.connect(self.show_series_picker)
  self.series_more_btn.setVisible(False)
  sb_lay.addWidget(self.series_more_btn)
  self.series_bar.setFixedHeight(34)
  self.series_bar.setVisible(False)
  lay.addWidget(self.series_bar)
  self.fig = Figure(figsize=(6, 4.4), dpi=100)
  self.ax = self.fig.add_subplot(111)
  self.canvas = FigureCanvas(self.fig)
  self.toolbar = NavigationToolbar(self.canvas, wrap)
  lay.addWidget(self.toolbar)
  lay.addWidget(self.canvas, 1)
  self._plotted_artists = []
  self._style_artists = {}
  self._drawing = False
  self._scope_drag = None
  self._scope_ov = None
  self.canvas.mpl_connect("button_press_event", self._scope_on_press)
  self.canvas.mpl_connect("motion_notify_event", self._scope_on_motion)
  self.canvas.mpl_connect("button_release_event", self._scope_on_release)
  self.canvas.mpl_connect("scroll_event", self._scope_on_scroll)
  self.canvas.mpl_connect("motion_notify_event", self._hover_readout)
  self.canvas.mpl_connect("pick_event", self._on_legend_pick)
  self.canvas.mpl_connect("draw_event", self._invalidate_crosshair)
  self.canvas.mpl_connect("resize_event", self._invalidate_crosshair)
  self.canvas.mpl_connect("figure_leave_event", lambda e: self._hide_hover_ui())
  self.canvas.setAcceptDrops(True)
  app = self
  class _CanvasDrop(QtCore.QObject):
   def eventFilter(self, _obj, ev):
    et = ev.type()
    if et in (QtCore.QEvent.Type.DragEnter, QtCore.QEvent.Type.DragMove):
     if ev.mimeData().hasFormat(SERIES_MIME) or ev.mimeData().hasUrls():
      ev.acceptProposedAction()
      return True
    elif et == QtCore.QEvent.Type.Drop:
     md = ev.mimeData()
     if md.hasFormat(SERIES_MIME):
      app._drop_series(bytes(md.data(SERIES_MIME)).decode("utf-8"))
      ev.acceptProposedAction()
      return True
     if md.hasUrls():
      app.dropEvent(ev)
      return True
    return False
  self._canvas_drop_filter = _CanvasDrop(self.canvas)
  self.canvas.installEventFilter(self._canvas_drop_filter)
  self._draw_placeholder()
  return wrap
 def _rebuild_series_bar(self, chart_type=None):
  self._sync_explorer_checks()
  chart_type = chart_type or self.chart_combo.currentText()
  lay = self.series_bar_layout
  while lay.count():
   it = lay.takeAt(0)
   if it.widget():
    it.widget().deleteLater()
  if chart_type not in ("折れ線", "散布図"):
   self.series_bar.setVisible(False)
   return
  items = [self.y_list.item(i) for i in range(self.y_list.count())]
  if not items:
   self.series_bar.setVisible(False)
   return
  needle = ""
  if hasattr(self, "series_filter"):
   needle = self.series_filter.text().strip().lower()
  def _label_of(it):
   st = self.series_styles.get(self._style_key(*it.data(UserRole))) or {}
   return st.get("label") or it.text()
  matched = [it for it in items if not needle or needle in _label_of(it).lower()]
  checked_first = ([it for it in matched if it.checkState() == QtCore.Qt.CheckState.Checked] + [it for it in matched if it.checkState() != QtCore.Qt.CheckState.Checked])
  shown = checked_first[:SERIES_BAR_MAX]
  hidden = len(checked_first) - len(shown)
  tok = palette_tokens()
  self._series_bar_building = True
  for it in shown:
   st = self.series_styles.get(self._style_key(*it.data(UserRole))) or {}
   checked = it.checkState() == QtCore.Qt.CheckState.Checked
   color = st.get("color") or (tok["fg"] if checked else tok["muted"])
   cb = QtWidgets.QCheckBox(_label_of(it))
   cb.setChecked(checked)
   cb.setToolTip("右クリック=この系列だけ表示／非表示／すべて表示")
   cb.setAccessibleName(f"系列 {_label_of(it)} の表示")
   cb.setStyleSheet(f"QCheckBox {{ color:{color}; " f"font-weight:{'bold' if checked else 'normal'}; }}")
   cb.toggled.connect(lambda on, item=it: self._toggle_series_select(item, on))
   cb.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
   cb.customContextMenuRequested.connect( lambda pos, item=it, wdg=cb: self._series_menu(item).exec(wdg.mapToGlobal(pos)))
   lay.addWidget(cb)
  lay.addStretch(1)
  self._series_bar_building = False
  if hasattr(self, "series_more_btn"):
   self.series_more_btn.setText(f"他{hidden}件…")
   self.series_more_btn.setVisible(hidden > 0)
  if needle and not matched:
   self._set_status(f"「{needle}」に一致する系列はありません。")
  self.series_bar.setVisible(True)
 def show_series_picker(self):
  items = [self.y_list.item(i) for i in range(self.y_list.count())]
  dlg = QtWidgets.QDialog(self)
  dlg.setWindowTitle("系列の選択")
  dlg.resize(420, 520)
  lay = QtWidgets.QVBoxLayout(dlg)
  edit = QtWidgets.QLineEdit()
  edit.setPlaceholderText("絞り込み")
  edit.setAccessibleName("系列の絞り込み")
  lay.addWidget(edit)
  lst = QtWidgets.QListWidget()
  lst.setAccessibleName("系列の一覧")
  lay.addWidget(lst, 1)
  rows = []
  for it in items:
   st = self.series_styles.get(self._style_key(*it.data(UserRole))) or {}
   row = QtWidgets.QListWidgetItem(st.get("label") or it.text())
   row.setFlags(row.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
   row.setCheckState(it.checkState())
   lst.addItem(row)
   rows.append((row, it))
  edit.textChanged.connect(lambda t: [ r.setHidden(bool(t) and t.strip().lower() not in r.text().lower()) for r, _ in rows])
  btns = QtWidgets.QDialogButtonBox( QtWidgets.QDialogButtonBox.StandardButton.Ok | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
  btns.accepted.connect(dlg.accept)
  btns.rejected.connect(dlg.reject)
  lay.addWidget(btns)
  self._series_picker = dlg
  if dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted:
   for row, it in rows:
    if row.checkState() != it.checkState():
     it.setCheckState(row.checkState())
 def _toggle_series_select(self, item, on):
  if getattr(self, "_series_bar_building", False):
   return
  item.setCheckState(QtCore.Qt.CheckState.Checked if on else QtCore.Qt.CheckState.Unchecked)
 def _build_preview(self):
  box = QtWidgets.QGroupBox("データ編集（選択中ファイル・先頭100行）")
  self._preview_bar_host = box
  lay = QtWidgets.QVBoxLayout(box); lay.setContentsMargins(4, 4, 4, 4)
  self._preview_label = None
  self._preview_loading = False
  bar = QtWidgets.QHBoxLayout()
  self.edit_check = QtWidgets.QCheckBox("編集可")
  self.edit_check.setToolTip("セルをダブルクリックで編集。値はその場でDataFrameに反映され、グラフにも反映されます。")
  self.edit_check.toggled.connect(self._on_edit_toggle)
  bar.addWidget(self.edit_check)
  for text, slot, tip in [ ("行追加", self._row_add, "末尾に空行を追加"), ("行削除", self._row_del, "選択した行を削除"), ("列追加", self._col_add, "新しい数値列を追加"), ("編集を戻す", self._data_undo, "データ編集（セル・行・列）を1つ戻す"), ("やり直す", self._data_redo, "戻したデータ編集をやり直す"), ("CSV保存", self._save_csv, "編集後のデータをCSV/TSVに書き出し")]:
   b = QtWidgets.QPushButton(text); b.setToolTip(tip)
   b.clicked.connect(slot); bar.addWidget(b)
  bar.addStretch(1)
  lay.addLayout(bar)
  self.table = QtWidgets.QTableWidget()
  self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
  self.table.setAlternatingRowColors(True)
  self.table.itemChanged.connect(self._on_cell_edited)
  self.table.setToolTip("行を選択するとグラフ上の対応する点がリングで強調されます。\n" "逆にグラフの点（単純な折れ線）をクリックするとこの表の行が選ばれます。")
  self.table.itemSelectionChanged.connect(self._on_preview_selection_changed)
  lay.addWidget(self.table)
  return box
 def _build_statusbar(self):
  self.status = self.statusBar()
  self._hover_label = QtWidgets.QLabel("")
  self._hover_label.setStyleSheet(f"color:{palette_tokens()['accent']};")
  self._hover_label.setAccessibleName("カーソル位置の値")
  self.status.addPermanentWidget(self._hover_label)
  self._level_button = QtWidgets.QToolButton()
  self._level_button.setText(f"表示: {self.ui_level()} ▾")
  self._level_button.setToolTip("画面に出す設定の量を切り替えます。" "隠れた項目も Ctrl+F で名前を入れれば出てきます。")
  self._level_button.setAccessibleName("表示レベルの切替")
  self._level_button.setPopupMode( QtWidgets.QToolButton.ToolButtonPopupMode.InstantPopup)
  lv_menu = QtWidgets.QMenu(self._level_button)
  for lv, act in getattr(self, "_level_actions", {}).items():
   lv_menu.addAction(act)
  self._level_button.setMenu(lv_menu)
  self.status.addPermanentWidget(self._level_button)
  self._msg_button = QtWidgets.QToolButton()
  self._msg_button.setText("履歴")
  self._msg_button.setToolTip("これまでのメッセージ・警告・エラーの一覧を開きます")
  self._msg_button.setAccessibleName("メッセージ履歴を開く")
  self._msg_button.clicked.connect(self.show_message_log)
  self.status.addPermanentWidget(self._msg_button)
  fi = f"日本語: {self.font_name}" if self.font_name else "日本語フォント未検出"
  self.status.addPermanentWidget(QtWidgets.QLabel(fi))
 def _log_message(self, text, level="info", detail=""):
  log = getattr(self, "_message_log", None)
  if log is None:
   log = self._message_log = []
  stamp = QtCore.QDateTime.currentDateTime().toString("HH:mm:ss")
  log.append({"time": stamp, "level": level, "text": str(text), "detail": str(detail or "")})
  if len(log) > MESSAGE_LOG_MAX:
   del log[:len(log) - MESSAGE_LOG_MAX]
  logger = get_logger()
  {"error": logger.error, "warn": logger.warning}.get(level, logger.info)( "%s%s", text, f" / {detail}" if detail else "")
 def notify(self, text, level="info", detail="", timeout_ms=NOTIFY_MS):
  bar = getattr(self, "notify_bar", None)
  if bar is not None:
   bar.show_message(text, level, detail, timeout_ms)
  if getattr(self, "status", None) is not None:
   self._set_status(text, level, detail)
  else:
   self._log_message(text, level, detail)
 def show_message_log(self):
  log = getattr(self, "_message_log", None) or []
  dlg = QtWidgets.QDialog(self)
  dlg.setWindowTitle("メッセージ履歴")
  dlg.resize(760, 420)
  lay = QtWidgets.QVBoxLayout(dlg)
  table = QtWidgets.QTableWidget(len(log), 3)
  table.setHorizontalHeaderLabels(["時刻", "種別", "内容"])
  table.setAccessibleName("メッセージ履歴")
  table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
  names = {"info": "情報", "ok": "完了", "warn": "警告", "error": "エラー"}
  for r, m in enumerate(reversed(log)):
   body = m["text"] + (f"\n{m['detail']}" if m["detail"] else "")
   for c, v in enumerate((m["time"], names.get(m["level"], m["level"]), body)):
    table.setItem(r, c, QtWidgets.QTableWidgetItem(v))
  table.resizeColumnsToContents()
  table.horizontalHeader().setStretchLastSection(True)
  lay.addWidget(table)
  self._wire_table_export(table, "メッセージ履歴")
  bar = QtWidgets.QHBoxLayout()
  bar.addStretch(1)
  b_clear = QtWidgets.QPushButton("履歴を消去(&C)")
  b_clear.clicked.connect(lambda: (setattr(self, "_message_log", []), table.setRowCount(0)))
  bar.addWidget(b_clear)
  b_close = QtWidgets.QPushButton("閉じる(&X)")
  b_close.clicked.connect(dlg.accept)
  bar.addWidget(b_close)
  lay.addLayout(bar)
  self._message_log_dialog = dlg
  dlg.exec()
 def _wire_table_export(self, table, name):
  table.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
  table.customContextMenuRequested.connect( lambda pos, t=table, n=name: self._table_export_menu(t, n, pos))
 def _table_export_menu(self, table, name, pos):
  menu = QtWidgets.QMenu(table)
  if table.selectedIndexes():
   menu.addAction("選択範囲をコピー", lambda: self._copy_table(table, True))
  menu.addAction("表全体をコピー", lambda: self._copy_table(table, False))
  menu.addAction("CSVで保存…", lambda: self._save_table_csv(table, name))
  menu.exec(table.viewport().mapToGlobal(pos))
 @staticmethod
 def _table_rows(table, selected_only):
  if selected_only and table.selectedIndexes():
   rows = sorted({i.row() for i in table.selectedIndexes()})
   cols = sorted({i.column() for i in table.selectedIndexes()})
  else:
   rows = range(table.rowCount())
   cols = range(table.columnCount())
  def head(c):
   h = table.horizontalHeaderItem(c)
   return h.text() if h is not None else str(c)
  out = [[head(c) for c in cols]]
  for r in rows:
   line = []
   for c in cols:
    it = table.item(r, c)
    line.append(it.text() if it is not None else "")
   out.append(line)
  return out
 def _copy_table(self, table, selected_only):
  rows = self._table_rows(table, selected_only)
  text = "\n".join("\t".join(cells) for cells in rows)
  QtWidgets.QApplication.clipboard().setText(text)
  self._set_status(f"{len(rows) - 1} 行をコピーしました（Excel等にそのまま貼り付け可）。")
 def _save_table_csv(self, table, name):
  path, _ = QtWidgets.QFileDialog.getSaveFileName( self, f"{name}をCSVで保存", os.path.join(self.last_dir, f"{name}.csv"), "CSV (*.csv)")
  if not path:
   return
  import csv
  try:
   with open(path, "w", newline="", encoding="utf-8-sig") as f:
    csv.writer(f).writerows(self._table_rows(table, False))
   self.last_dir = os.path.dirname(path)
   self._set_status(f"{name}を保存しました: {path}")
  except OSError as e:
   QtWidgets.QMessageBox.critical(self, "保存エラー", str(e))
 @staticmethod
 def _scrollable(w):
  sc = QtWidgets.QScrollArea()
  sc.setWidgetResizable(True)
  sc.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
  sc.setWidget(w)
  return sc
 @staticmethod
 def _bold(text):
  l = QtWidgets.QLabel(text)
  f = l.font(); f.setBold(True); l.setFont(f)
  l.setProperty("section_header", True)
  l.setWordWrap(True)
  return l
 @staticmethod
 def _hline():
  ln = QtWidgets.QFrame()
  ln.setFrameShape(QtWidgets.QFrame.Shape.HLine)
  ln.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
  return ln
 def _wire_live_signals(self):
  r = self._request_redraw
  self.chart_combo.currentTextChanged.connect(r)
  for e in (self.title_edit, self.xlabel_edit, self.ylabel_edit, self.xunit_edit, self.yunit_edit, self.xscale_edit, self.yscale_edit):
   e.textChanged.connect(r)
  for s in (self.fs_title, self.fs_label, self.fs_tick, self.fs_legend, self.fs_annot, self.bins_spin, self.frame_width, self.grid_width):
   s.valueChanged.connect(r)
  for c in (self.grid_check, self.legend_check, self.pct_check, self.xlog, self.ylog, self.show_filename_check, self.show_ext_check, self.xinvert_check, self.yinvert_check, self.stack_check):
   c.toggled.connect(r)
  self.legend_loc.currentTextChanged.connect(r)
  self.trend_combo.currentTextChanged.connect(r)
  for s in (self.trend_degree, self.trend_window):
   s.valueChanged.connect(r)
  for c in (self.trend_eq, self.data_labels_check, self.fill_check):
   c.toggled.connect(r)
  self.fill_a.currentTextChanged.connect(r)
  self.fill_b.currentTextChanged.connect(r)
  self.fill_alpha.valueChanged.connect(r)
  for s in (self.aspect_w, self.aspect_h):
   s.valueChanged.connect(r)
  for le in (self.xmin, self.xmax, self.ymin, self.ymax, self.xtick_edit, self.ytick_edit):
   le.editingFinished.connect(r)
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
  tips = { self.legend_loc: "凡例の表示位置", self.xlog: "X軸を対数目盛に（0以下の値は表示できません）", self.ylog: "Y軸を対数目盛に（0以下の値は表示できません）", self.bins_spin: "ヒストグラムの区間数（ヒストグラム選択時のみ有効）", self.pct_check: "円グラフでパーセント表示（円グラフ選択時のみ有効）", self.xmin: "X軸の最小値。空欄で自動。指数表記(1e-3)も可", self.xmax: "X軸の最大値。空欄で自動", self.ymin: "Y軸の最小値。空欄で自動", self.ymax: "Y軸の最大値。空欄で自動", self.dpi_spin: "保存画像の解像度。印刷向けは300以上", self.transparent_check: "保存時に背景を透明にします（PNG/PDF/SVG）", self.analysis_target: "解析するY系列。データタブでY系列を選ぶと候補に出ます", self.npeaks: "検出するピークの個数（第1〜第N）", self.show_peaks_check: "検出ピークを折れ線/散布図に重ねて表示", self.scope_check: "オシロスコープ風のdiv表示（折れ線/散布図）", self.tdiv: "1目盛りあたりの時間。1e-3 のような指数表記も可", self.vdiv: "1目盛りあたりの値。1e-3 のような指数表記も可", self.xpos: "表示の中心時間", self.ypos: "表示の中心値", }
  for w, t in tips.items():
   w.setToolTip(t)
class PlotMixin:
 def _request_redraw(self, *args):
  if self._suspend_redraw or not self._has_drawn:
   return
  if not getattr(self, "live_check", None) or not self.live_check.isChecked():
   return
  self._redraw_timer.start(180)
 def _do_live_redraw(self):
  if self.datasets and self._has_drawn:
   self.draw_graph()
 def _on_chart_type_change(self, *_):
  ctype = self.chart_combo.currentText()
  info = CHART_INFO.get(ctype, {})
  self.hint_label.setText("➤ " + info.get("hint", ""))
  self._sync_3d_checkbox(info)
  self._update_x_combo_enabled()
  self._update_z_combo_enabled()
  self._update_x_multi_enabled()
  if hasattr(self, "swap_xy_check"):
   self.swap_xy_check.setEnabled(ctype in _SWAP_TYPES)
  uses_bins = ctype in ("ヒストグラム", "2Dヒストグラム", "hexbin")
  self.bins_spin.setEnabled(uses_bins)
  self.bins_caption.setEnabled(uses_bins)
  self.pct_check.setEnabled(ctype in ("円", "ドーナツ"))
  want3d = self._want_3d()
  if hasattr(self, "elev_spin"):
   self.elev_spin.setEnabled(want3d); self.azim_spin.setEnabled(want3d)
  if hasattr(self, "trend_combo"):
   xy_ok = (ctype in _XY_TYPES) and not want3d
   for w_ in (self.trend_combo, self.trend_degree, self.trend_window, self.trend_color_btn, self.trend_eq):
    w_.setEnabled(xy_ok)
  if hasattr(self, "fill_check"):
   fill_ok = ctype in ("折れ線", "散布図") and not want3d
   for w_ in (self.fill_check, self.fill_a, self.fill_b, self.fill_color_btn, self.fill_alpha):
    w_.setEnabled(fill_ok)
  if hasattr(self, "data_labels_check"):
   self.data_labels_check.setEnabled( ctype in _XY_TYPES or ctype in ("棒", "横棒", "積み上げ棒") or want3d)
  if hasattr(self, "stack_check"):
   self.stack_check.setEnabled(ctype in ("折れ線", "散布図") and not want3d)
  if hasattr(self, "series_bar"):
   self._rebuild_series_bar(ctype)
 def _sync_3d_checkbox(self, info):
  if not hasattr(self, "threed_check"):
   return
  d3 = info.get("dim3")
  self.threed_check.blockSignals(True)
  if d3 == "always":
   self.threed_check.setChecked(True); self.threed_check.setEnabled(False)
  elif d3 == "optional":
   self.threed_check.setEnabled(True)
  else:
   self.threed_check.setChecked(False); self.threed_check.setEnabled(False)
  self.threed_check.blockSignals(False)
 def _on_3d_toggled(self, *_):
  self._update_z_combo_enabled()
  self._update_x_multi_enabled()
  self._on_chart_type_change()
  self._request_redraw()
 def _on_multix_toggled(self, *_):
  self._update_x_multi_enabled()
  self._request_redraw()
 def _build_series(self, chart_type):
  items = self._selected_series_items()
  if not items:
   raise ValueError("Y軸（値）の系列を選択してください。")
  xname = self.x_combo.currentText()
  categories = None
  series = []
  def lbl(fl, col, disp, default):
   st = self.series_styles.get(self._style_key(fl, col)) or {}
   return st.get("label") or default
  if self._want_3d():
   for fl, col, disp in items:
    df = self.datasets[fl]
    stmap = self.series_styles.get(self._style_key(fl, col)) or {}
    series.append({"label": self._series_label(fl, col), "x": self._x_values(df), "y": df[col].to_numpy(), "z": self._z_values(df), "style": stmap, "kind": stmap.get("kind", "")})
  elif chart_type in ("棒", "横棒", "積み上げ棒", "円", "ドーナツ"):
   src = items[0][0]
   df = self.datasets[src]
   if not self._use_leftmost_x() and xname not in df.columns:
    raise ValueError(f"X軸の列『{xname}』が『{src}』にありません。")
   categories = self._x_values(df)
   for fl, col, disp in items:
    if fl != src:
     continue
    series.append({"label": lbl(fl, col, disp, col), "y": self.datasets[fl][col].to_numpy(), "style": self.series_styles.get(self._style_key(fl, col))})
  elif chart_type in ("折れ線", "散布図", "面", "積み上げ面", "ステップ", "ステム", "2Dヒストグラム", "hexbin"):
   xcols = self._selected_x_columns()
   multi_x = len(xcols) > 1
   for fl, col, disp in items:
    df = self.datasets[fl]
    stmap = self.series_styles.get(self._style_key(fl, col)) or {}
    errcol = stmap.get("errcol")
    yerr = df[errcol].to_numpy() if (errcol and errcol in df.columns) else None
    for xname_i in xcols:
     lab = self._series_label(fl, col)
     st_i = stmap
     if multi_x:
      xdisp = str(df.columns[0]) if xname_i is None else xname_i
      lab = f"{lab} [X:{xdisp}]"
      if stmap.get("color"):
       st_i = dict(stmap); st_i.pop("color", None)
     series.append({"label": lab, "x": self._x_values(df, xname_i), "y": df[col].to_numpy(), "style": st_i, "axis": st_i.get("axis", "primary"), "kind": st_i.get("kind", ""), "yerr": yerr})
  else:
   for fl, col, disp in items:
    series.append({"label": self._series_label(fl, col), "y": self.datasets[fl][col].to_numpy(), "style": self.series_styles.get(self._style_key(fl, col))})
  return series, categories
 def _scope_dict(self):
  return { "enabled": self.scope_check.isChecked(), "t_per_div": parse_eng(self.tdiv.currentText(), 1e-3), "v_per_div": parse_eng(self.vdiv.currentText(), 1.0), "x_pos": _parse_float(self.xpos.text(), 0.0), "y_pos": _parse_float(self.ypos.text(), 0.0), "x_divs": self.xdivs.value(), "y_divs": self.ydivs.value(), }
 def _fonts(self):
  return {"title": self.fs_title.value(), "label": self.fs_label.value(), "tick": self.fs_tick.value(), "legend": self.fs_legend.value(), "annot": self.fs_annot.value()}
 def _view_angles(self):
  elev = self.elev_spin.value() if hasattr(self, "elev_spin") else 30
  azim = self.azim_spin.value() if hasattr(self, "azim_spin") else -60
  return (elev, azim)
 def _on_view_angle_changed(self, *_):
  if self._is_3d() and getattr(self, "_has_drawn", False):
   try:
    self.ax.view_init(elev=self.elev_spin.value(), azim=self.azim_spin.value())
    self.canvas.draw_idle()
   except Exception:
    get_logger().debug("_on_view_angle_changed: 無視した例外", exc_info=True)
 def _on_aspect_changed(self, *_):
  custom = self.aspect_combo.currentText() == "カスタム"
  self.aspect_w.setEnabled(custom)
  self.aspect_h.setEnabled(custom)
  self._request_redraw()
 def _aspect_ratio(self):
  t = self.aspect_combo.currentText()
  presets = {"16:9": (16, 9), "4:3": (4, 3), "3:2": (3, 2), "1:1": (1, 1), "9:16（縦）": (9, 16), "A4横": (297, 210), "A4縦": (210, 297)}
  if t in presets:
   w, h = presets[t]
  elif t == "カスタム":
   w, h = self.aspect_w.value(), self.aspect_h.value()
  else:
   return None
  return (h / w) if w else None
 def _apply_aspect(self):
  if self._is_3d():
   return
  ratio = self._aspect_ratio()
  try:
   self.ax.set_box_aspect(ratio)
   ax2 = getattr(self.ax, "_twin_secondary", None)
   if ax2 is not None:
    ax2.set_box_aspect(ratio)
  except Exception:
   get_logger().debug("_apply_aspect: 無視した例外", exc_info=True)
 def _export_figsize(self, base=7.0):
  ratio = self._aspect_ratio()
  if not ratio:
   return tuple(self.fig.get_size_inches())
  if ratio <= 1.0:
   return (base, base * ratio)
  return (base / ratio, base)
 @staticmethod
 def _field_float(le):
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
  return dict( bins=self.bins_spin.value(), grid=self.grid_check.isChecked(), legend=self.legend_check.isChecked(), legend_loc=self.legend_loc.currentText(), xlog=self.xlog.isChecked(), ylog=self.ylog.isChecked(), pct=self.pct_check.isChecked(), fonts=self._fonts(), trendline={"type": self.trend_combo.currentText(), "degree": self.trend_degree.value(), "window": self.trend_window.value(), "show_eq": self.trend_eq.isChecked(), "color": getattr(self, "trend_color", "") or ""}, data_labels=self.data_labels_check.isChecked(), xscale=self.xscale_edit.text(), yscale=self.yscale_edit.text(), xunit=self.xunit_edit.text().strip(), yunit=self.yunit_edit.text().strip(), bg_color=self._effective_bg_color(), grid_width=self.grid_width.value(), frame_width=self.frame_width.value(), xinvert=self.xinvert_check.isChecked(), yinvert=self.yinvert_check.isChecked(), swap_xy=(self.swap_xy_check.isChecked() if hasattr(self, "swap_xy_check") else False), )
 def draw_graph(self):
  if getattr(self, "_drawing", False):
   return
  self._drawing = True
  try:
   self._draw_graph_body()
  finally:
   self._drawing = False
 def _confirm_heavy_draw(self, n):
  if n <= HEAVY_SERIES or getattr(self, "_heavy_draw_ok", False):
   return True
  ret = QtWidgets.QMessageBox.question( self, "系列数の確認", f"{n} 系列を一度に描画します。表示が終わるまで時間がかかり、" f"操作できなくなることがあります。\n\n続けますか？" f"\n（{HEAVY_SERIES} 系列以下に減らすと快適に操作できます）")
  if ret == QtWidgets.QMessageBox.StandardButton.Yes:
   self._heavy_draw_ok = True
   return True
  return False
 def _draw_graph_body(self):
  if not self.datasets:
   self.notify("先にファイルを追加してください。", "warn")
   return
  selected = self._selected_series_items()
  if not selected:
   self._draw_placeholder()
   self._rebuild_series_bar(self.chart_combo.currentText())
   self._set_status("Y軸（値）の系列をチェックするとグラフを表示します。")
   return
  if not self._confirm_heavy_draw(len(selected)):
   self._draw_placeholder()
   self._rebuild_series_bar(self.chart_combo.currentText())
   self.notify(f"描画を中止しました（{len(selected)} 系列）。" "系列バーの絞り込みでチェックを減らせます。", "warn")
   return
  ctype = self.chart_combo.currentText()
  issues = []
  xlim = self._range_pair(self.xmin, self.xmax, "X", issues)
  ylim = self._range_pair(self.ymin, self.ymax, "Y", issues)
  scope = self._scope_dict()
  if scope["enabled"] and ctype in ("折れ線", "散布図"):
   if not (scope["t_per_div"] and scope["t_per_div"] > 0 and scope["v_per_div"] and scope["v_per_div"] > 0):
    issues.append("time/div・V/div は正の値が必要（オシロ表示を無効化）")
    scope = dict(scope, enabled=False)
  self._ensure_axes_projection(self._want_3d())
  self._clear_dynamic_resample()
  self._reset_figure_axes()
  self._cursor_pts = []; self._cursor_artists = []
  self._cursors = []; self._cursor_drag = None; self._cursor_text = None
  self._link_artists = []
  try:
   if self._tab_hook("_fft_mode_on", default=False):
    self._ensure_axes_projection(False)
    self._reset_figure_axes()
    self._tab_hook("_draw_fft_view")
    self._rebuild_series_bar(ctype)
    self._plotted_artists = [(ln.get_label(), ln) for ln in self.ax.get_lines()]
    self._has_drawn = True
    self._snapshot()
    return
   series, categories = self._build_series(ctype)
   swap_on = (getattr(self, "swap_xy_check", None) and self.swap_xy_check.isChecked() and ctype in _SWAP_TYPES)
   yn, xn = ("X", "Y") if swap_on else ("Y", "X")
   if self.ylog.isChecked() and self._has_nonpositive([s["y"] for s in series]):
    issues.append(f"{yn}対数: 0以下の値は表示されません")
   if (self.xlog.isChecked() and ctype in ("折れ線", "散布図") and self._has_nonpositive([s.get("x") for s in series])):
    issues.append(f"{xn}対数: 0以下の値は表示されません")
   total = sum(len(s.get("y", [])) for s in series)
   max_points = (DECIMATE_TARGET if (self.decimate_check.isChecked() and ctype in ("折れ線", "散布図") and total > DECIMATE_TARGET) else 0)
   stack_now = (getattr(self, "stack_check", None) is not None and self.stack_check.isChecked() and ctype in ("折れ線", "散布図") and not self._want_3d() and not scope["enabled"])
   if stack_now and len(series) > 8:
    issues.append("段分け表示は8系列まで（9系列以上は通常表示に切替）")
    stack_now = False
   if stack_now:
    self._draw_stacked(series, ctype, xlim, ylim, max_points)
    self._rebuild_series_bar(ctype)
    self._has_drawn = True
    self._snapshot()
    msg = f"「{ctype}」を{len(series)}段に分けて描画しました。"
    if issues:
     msg += "  ⚠ " + " / ".join(issues)
    self._set_status(msg)
    return
   busy = total > BUSY_ROWS
   if busy:
    QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
    self._set_status(f"描画中…（{total:,} 点）"); QtWidgets.QApplication.processEvents()
   try:
    markers = self._tab_hook("_peak_markers") if self.show_peaks_check.isChecked() else None
    sec_label = " / ".join(s["label"] for s in series if s.get("axis") == "secondary")
    plot_series( self.ax, series, ctype, categories=categories, title=self.title_edit.text(), xlabel=self.xlabel_edit.text() or self._effective_x_label(), ylabel=self.ylabel_edit.text() or self._effective_y_label(), xlim=xlim, ylim=ylim, scope=scope, markers=markers, max_points=max_points, secondary_label=sec_label, zlabel=(self.z_combo.currentText() if self._want_3d() else ""), view_init=(self._view_angles() if self._want_3d() else None), threed=self._want_3d(), **self._plot_format_kwargs(), )
    self._apply_aspect()
    self._apply_tick_spacing(ctype, scope)
    self._apply_fill_between(ctype, series)
    self._tab_hook("_draw_ds_annotations")
    self._tab_hook("_draw_proto_overlay", ctype)
    self._draw_plugin_overlays()
    self._apply_figure_theme(redraw=False)
    try:
     self.fig.tight_layout()
    except Exception:
     get_logger().debug("_draw_graph_body: 無視した例外", exc_info=True)
    self.canvas.draw()
   finally:
    if busy:
     QtWidgets.QApplication.restoreOverrideCursor()
   if max_points and not swap_on:
    self._setup_dynamic_resample(series, ctype, max_points)
   self._rebuild_series_bar(ctype)
   self._plotted_artists = [ (ln.get_label(), ln) for ln in self.ax.get_lines() if "近似" not in str(ln.get_label())]
   self._style_artists = self._build_style_artist_map(series, ctype, bool(max_points))
   self._wire_legend_picking()
   self._tab_hook("_regate")
   self._has_drawn = True
   self._snapshot()
   msg = f"「{ctype}」を描画しました（系列 {len(series)}）。"
   if max_points:
    msg += f"（{total:,}点を間引き表示）"
   if issues:
    msg += "  ⚠ " + " / ".join(issues)
   self._set_status(msg)
  except Exception as e:
   get_logger().exception("描画エラー")
   QtWidgets.QMessageBox.critical(self, "描画エラー", str(e))
 def open_graph_window(self):
  if not self.datasets or not self._selected_series_items():
   self.notify("先にY系列を選択してください。", "warn")
   return
  dlg = QtWidgets.QDialog(self)
  dlg.setWindowFlags(QtCore.Qt.WindowType.Window)
  n = len(getattr(self, "_graph_windows", [])) + 1
  title = self.title_edit.text() or self.chart_combo.currentText()
  dlg.setWindowTitle(f"グラフ {n}: {title}")
  dlg.resize(760, 540)
  v = QtWidgets.QVBoxLayout(dlg)
  fig = Figure(figsize=(6, 4), dpi=100)
  canvas = FigureCanvas(fig)
  tb = NavigationToolbar(canvas, dlg)
  v.addWidget(tb)
  v.addWidget(canvas, 1)
  brow = QtWidgets.QHBoxLayout()
  b_upd = QtWidgets.QPushButton("現在の設定で更新")
  b_upd.setToolTip("メイン画面のいまの系列選択・書式でこのウィンドウを描き直します。")
  brow.addWidget(b_upd)
  brow.addStretch(1)
  v.addLayout(brow)
  def render():
   try:
    ctype = self.chart_combo.currentText()
    series, categories = self._build_series(ctype)
    fig.clf()
    if self._want_3d():
     from mpl_toolkits.mplot3d import Axes3D
     ax = fig.add_subplot(111, projection="3d")
    else:
     ax = fig.add_subplot(111)
    ax._twin_secondary = None
    plot_series( ax, series, ctype, categories=categories, title=self.title_edit.text(), xlabel=self.xlabel_edit.text() or self._effective_x_label(), ylabel=self.ylabel_edit.text() or self._effective_y_label(), xlim=self._range_pair(self.xmin, self.xmax, "X", []), ylim=self._range_pair(self.ymin, self.ymax, "Y", []), scope=None, markers=None, max_points=DECIMATE_TARGET, secondary_label="", zlabel=(self.z_combo.currentText() if self._want_3d() else ""), view_init=(self._view_angles() if self._want_3d() else None), threed=self._want_3d(), **self._plot_format_kwargs())
    dlg.setWindowTitle(f"グラフ {n}: " f"{self.title_edit.text() or self.chart_combo.currentText()}")
    try:
     fig.tight_layout()
    except Exception:
     get_logger().debug("render: 無視した例外", exc_info=True)
    canvas.draw()
   except Exception as e:
    QtWidgets.QMessageBox.critical(dlg, "描画エラー", str(e))
  b_upd.clicked.connect(render)
  render()
  if not hasattr(self, "_graph_windows"):
   self._graph_windows = []
  self._graph_windows.append(dlg)
  dlg.finished.connect(lambda *_: self._graph_windows.remove(dlg) if dlg in self._graph_windows else None)
  dlg.show()
  self._set_status(f"グラフウィンドウ {n} を開きました" "（メイン画面で選択・書式を変えて複数枚並べられます）。")
 def _draw_stacked(self, series, ctype, xlim, ylim, max_points):
  self._clear_dynamic_resample()
  for a in list(self.fig.axes):
   try:
    a.remove()
   except Exception:
    get_logger().debug("_draw_stacked: 無視した例外", exc_info=True)
  n = len(series)
  axes = self.fig.subplots(n, 1, sharex=True)
  if n == 1:
   axes = [axes]
  kw = self._plot_format_kwargs()
  kw["legend"] = False
  xlabel = self.xlabel_edit.text() or self._effective_x_label()
  for i, (ax, s) in enumerate(zip(axes, series)):
   s2 = dict(s)
   s2["axis"] = "primary"
   st = s.get("style") or {}
   plot_series( ax, [s2], ctype, title=(self.title_edit.text() if i == 0 else ""), xlabel=(xlabel if i == n - 1 else ""), ylabel=str(st.get("label") or s.get("label") or ""), xlim=xlim, ylim=ylim, scope=None, markers=None, max_points=max_points, secondary_label="", threed=False, **kw)
   ax._twin_secondary = None
  self.ax = axes[-1]
  self._tab_hook("_draw_ds_annotations")
  self._apply_figure_theme(redraw=False)
  try:
   self.fig.tight_layout()
  except Exception:
   get_logger().debug("_draw_stacked: 無視した例外", exc_info=True)
  self.canvas.draw()
  self._plotted_artists = [(ln.get_label(), ln) for a in axes for ln in a.get_lines() if "近似" not in str(ln.get_label())]
  self._style_artists = {}
  self._legend_pick_map = {}
  self._tab_hook("_regate")
  self._stacked = True
 def _draw_proto_overlay(self, ctype):
  info = getattr(self, "_proto_annotations", None)
  chk = getattr(self, "proto_overlay_check", None)
  if (not info or not info.get("rows") or chk is None or not chk.isChecked() or self._is_3d() or getattr(self, "_stacked", False) or ctype not in ("折れ線", "散布図") or (getattr(self, "swap_xy_check", None) and self.swap_xy_check.isChecked())):
   return
  import numpy as np
  from matplotlib import transforms as mtrans
  from matplotlib.lines import Line2D
  rows = info["rows"][:80]
  xs = axis_scale(np.array([r[0] for r in rows], dtype=float), self.xscale_edit.text())
  trans = mtrans.blended_transform_factory(self.ax.transData, self.ax.transAxes)
  fs = max((self.fs_annot.value() if hasattr(self, "fs_annot") else 9) - 1, 6)
  marker_kinds = {"START", "STOP", "BREAK", "SYNC", "RESET", "PRESENCE"}
  for i, ((_tm, kind, hexv, note), x) in enumerate(zip(rows, xs)):
   warn = "⚠" in str(note)
   color = ("#d02020" if warn else "#0a7a55" if str(kind) in marker_kinds else "#2b6cb0")
   label = str(hexv) if str(hexv) else str(kind)
   ytxt = 0.99 if i % 2 == 0 else 0.92
   self.ax.text(x, ytxt, label, transform=trans, ha="center", va="top", fontsize=fs, color=color, zorder=25, clip_on=True, bbox=dict(facecolor="white", alpha=0.78, edgecolor=color, lw=0.5, pad=1.2))
   self.ax.add_line(Line2D([x, x], [0.0, 0.86], transform=trans, color=color, lw=0.6, alpha=0.35, zorder=24))
  if len(info["rows"]) > 80:
   self.ax.text(0.99, 0.84, f"解読 {len(info['rows'])}件中 先頭80件を注記", transform=self.ax.transAxes, ha="right", va="top", fontsize=fs, color="#666", zorder=25)
 def _wire_legend_picking(self):
  self._legend_pick_map = {}
  leg = self.ax.get_legend()
  if leg is None:
   return
  label_map = {}
  for fl, col, _disp in self._selected_series_items():
   st = self.series_styles.get(self._style_key(fl, col)) or {}
   for k in {self._series_label(fl, col), st.get("label") or str(col)}:
    label_map[k] = (fl, col)
  handles = getattr(leg, "legend_handles", None) or getattr(leg, "legendHandles", [])
  for h, t in zip(handles, leg.get_texts()):
   key = label_map.get(t.get_text())
   if key is None:
    continue
   for art in (h, t):
    try:
     art.set_picker(6)
     self._legend_pick_map[art] = key
    except Exception:
     get_logger().debug("_wire_legend_picking: 無視した例外", exc_info=True)
  self._line_pick_map = {}
  for skey, ln in (self._style_artists or {}).items():
   try:
    ln.set_picker(5)
    self._line_pick_map[ln] = skey
   except Exception:
    get_logger().debug("_wire_legend_picking: 無視した例外", exc_info=True)
 def _on_legend_pick(self, event):
  key = getattr(self, "_legend_pick_map", {}).get(event.artist)
  if key is not None:
   yit = self._find_y_item(*key)
   if yit is not None:
    ck = QtCore.Qt.CheckState.Checked
    yit.setCheckState(QtCore.Qt.CheckState.Unchecked if yit.checkState() == ck else ck)
   return
  skey = getattr(self, "_line_pick_map", {}).get(event.artist)
  if skey is None:
   return
  if (self._tab_hook("_scope_active", default=False) or getattr(self.toolbar, "mode", "") or self._cursor_cid is not None or (getattr(self, "gate_btn", None) and self.gate_btn.isChecked())):
   return
  ind = getattr(event, "ind", None)
  if ind is None or not len(ind):
   return
  row = int(ind[0])
  fl = skey.split("\t", 1)[0]
  it = self._find_file_item(fl)
  if it is not None and self.file_list.currentItem() is not it:
   self.file_list.setCurrentRow(self.file_list.row(it))
  if row < self.table.rowCount():
   self.table.selectRow(row)
   cell = self.table.item(row, 0)
   if cell is not None:
    self.table.scrollToItem(cell)
   self._set_status(f"グラフの点 → データ編集表の行 {row} を選択（{fl}）")
  else:
   self._set_status(f"クリックした点は行 {row}" f"（プレビューは先頭{PREVIEW_ROWS}行のみ表示）")
 def _on_preview_selection_changed(self):
  if (getattr(self, "_preview_loading", False) or not getattr(self, "_has_drawn", False) or self._is_3d() or getattr(self, "_stacked", False)):
   return
  ctype = self.chart_combo.currentText()
  if (ctype not in ("折れ線", "散布図") or (getattr(self, "swap_xy_check", None) and self.swap_xy_check.isChecked())):
   return
  for a in getattr(self, "_link_artists", None) or []:
   try:
    a.remove()
   except Exception:
    get_logger().debug("_on_preview_selection_changed: 無視した例外", exc_info=True)
  self._link_artists = []
  lbl = getattr(self, "_preview_label", None)
  rows = sorted({i.row() for i in self.table.selectedIndexes()})
  if lbl and lbl in self.datasets and rows:
   import pandas as pd
   df = self.datasets[lbl]
   rows = [r for r in rows if r < len(df)][:500]
   xspec, yspec = self.xscale_edit.text(), self.yscale_edit.text()
   xraw = pd.to_numeric(pd.Series(self._x_values(df)), errors="coerce").to_numpy(dtype=float)
   for fl, col, _d in self._selected_series_items():
    if fl != lbl or col not in df.columns:
     continue
    st = self.series_styles.get(self._style_key(fl, col)) or {}
    if st.get("axis") == "secondary":
     continue
    y = pd.to_numeric(df[col], errors="coerce").to_numpy(dtype=float)
    xv = axis_scale(xraw[rows], xspec)
    yv = axis_scale(y[rows], yspec)
    art, = self.ax.plot(xv, yv, "o", ms=11, mfc="none", mec="#e6194b", mew=1.8, ls="none", zorder=26, label="_link_sel")
    self._link_artists.append(art)
  self.canvas.draw_idle()
 def _apply_tick_spacing(self, ctype, scope):
  if ctype == "円" or self._is_3d():
   return
  if scope.get("enabled") and ctype in ("折れ線", "散布図"):
   return
  from matplotlib.ticker import MultipleLocator
  dx = _parse_float(self.xtick_edit.text())
  dy = _parse_float(self.ytick_edit.text())
  def _too_many(lo, hi, step):
   try:
    return abs(hi - lo) / step > 1000
   except (ZeroDivisionError, TypeError):
    return True
  if (dx and dx > 0 and ctype in ("折れ線", "散布図") and self.ax.get_xscale() != "log"):
   x0, x1 = self.ax.get_xlim()
   if not _too_many(x0, x1, dx):
    try:
     self.ax.xaxis.set_major_locator(MultipleLocator(dx))
    except Exception:
     get_logger().debug("_apply_tick_spacing: 無視した例外", exc_info=True)
  if dy and dy > 0 and self.ax.get_yscale() != "log":
   y0, y1 = self.ax.get_ylim()
   if not _too_many(y0, y1, dy):
    try:
     self.ax.yaxis.set_major_locator(MultipleLocator(dy))
    except Exception:
     get_logger().debug("_apply_tick_spacing: 無視した例外", exc_info=True)
 def _apply_fill_between(self, ctype, series):
  if not getattr(self, "fill_check", None) or not self.fill_check.isChecked():
   return
  if ctype not in ("折れ線", "散布図") or not series:
   return
  if getattr(self, "swap_xy_check", None) and self.swap_xy_check.isChecked():
   self._set_status("塗りつぶし: X↔Y入れ替え中は無効です。")
   return
  import numpy as np
  import pandas as pd
  items = self._selected_series_items()
  if len(series) != len(items):
   self._set_status("塗りつぶし: X軸を複数選択中は無効です。")
   return
  dispmap = {it[2]: s for it, s in zip(items, series)}
  a = dispmap.get(self.fill_a.currentText())
  if a is None or a.get("x") is None:
   return
  xspec = self.xscale_edit.text()
  yspec = self.yscale_edit.text()
  def sxy(s):
   x = axis_scale(pd.to_numeric(pd.Series(s["x"]), errors="coerce").to_numpy(float), xspec)
   y = pd.to_numeric(pd.Series(s["y"]), errors="coerce").to_numpy(float)
   if s.get("axis") != "secondary":
    y = axis_scale(y, yspec)
   return x, y
  xa, ya = sxy(a)
  bname = self.fill_b.currentText()
  if bname == "0（X軸）":
   yb = np.zeros_like(ya)
  else:
   b = dispmap.get(bname)
   if b is None or b.get("x") is None:
    return
   if (b.get("axis") or "primary") != (a.get("axis") or "primary"):
    self._set_status("塗りつぶし: A と B は同じ軸の系列にしてください。")
    return
   xb, ybv = sxy(b)
   order = np.argsort(xb)
   yb = np.interp(xa, xb[order], ybv[order])
  color = self.fill_color or (a.get("style") or {}).get("color") or None
  target = self.ax
  if a.get("axis") == "secondary":
   target = getattr(self.ax, "_twin_secondary", None) or self.ax
  try:
   m = np.isfinite(xa) & np.isfinite(ya) & np.isfinite(yb)
   target.fill_between(xa, ya, yb, where=m, color=color, alpha=self.fill_alpha.value(), zorder=0, linewidth=0)
  except Exception:
   get_logger().debug("_apply_fill_between: 無視した例外", exc_info=True)
 def _draw_ds_annotations(self):
  if self._is_3d():
   return
  self._draw_annotation_box(getattr(self, "_ds_annotations", None), "tl")
  self._draw_annotation_box(getattr(self, "_meas_annotations", None), "tr")
 def _draw_annotation_box(self, anns, corner):
  if not anns:
   return
  fs = self.fs_annot.value() if hasattr(self, "fs_annot") else 9
  x, y, ha, va = {"tl": (0.02, 0.98, "left", "top"), "tr": (0.98, 0.98, "right", "top")}[corner]
  try:
   self.ax.text( x, y, "\n".join(anns), transform=self.ax.transAxes, ha=ha, va=va, fontsize=fs, zorder=20, bbox=dict(boxstyle="round", facecolor="white", alpha=0.8, edgecolor="#888"))
  except Exception:
   get_logger().debug("_draw_annotation_box: 無視した例外", exc_info=True)
 def _reset_figure_axes(self):
  for a in list(self.fig.axes):
   if a is not self.ax:
    try:
     a.remove()
    except Exception:
     get_logger().debug("_reset_figure_axes: 無視した例外", exc_info=True)
 def _is_3d(self):
  return getattr(getattr(self, "ax", None), "name", None) == "3d"
 def _want_3d(self):
  info = CHART_INFO.get(self.chart_combo.currentText(), {})
  d3 = info.get("dim3")
  if d3 == "always":
   return True
  if d3 == "optional":
   return bool(getattr(self, "threed_check", None) and self.threed_check.isChecked())
  return False
 def _ensure_axes_projection(self, want_3d):
  cur = getattr(self, "ax", None)
  if getattr(self, "_stacked", False):
   self._stacked = False
   cur = None
  if cur is not None and bool(want_3d) == (getattr(cur, "name", None) == "3d"):
   return
  self._clear_dynamic_resample()
  for a in list(self.fig.axes):
   try:
    a.remove()
   except Exception:
    get_logger().debug("_ensure_axes_projection: 無視した例外", exc_info=True)
  if want_3d:
   from mpl_toolkits.mplot3d import Axes3D
   self.ax = self.fig.add_subplot(111, projection="3d")
  else:
   self.ax = self.fig.add_subplot(111)
  self.ax._twin_secondary = None
  self._plotted_artists = []
  self._style_artists = {}
  self._cursor_pts = []; self._cursor_artists = []
  self._cursors = []; self._cursor_drag = None; self._cursor_text = None
  self._dyn = []; self._dyn_cid = None
 def _clear_dynamic_resample(self):
  if self._dyn_cid is not None:
   try:
    self.ax.callbacks.disconnect(self._dyn_cid)
   except Exception:
    get_logger().debug("_clear_dynamic_resample: 無視した例外", exc_info=True)
   self._dyn_cid = None
  self._dyn = []
 def _setup_dynamic_resample(self, series, ctype, max_points):
  if ctype != "折れ線":
   return
  import numpy as np
  import pandas as pd
  xspec = self.xscale_edit.text()
  yspec = self.yscale_edit.text()
  lines = self.ax.get_lines()
  for i, s in enumerate(series):
   if i >= len(lines) or s.get("x") is None:
    continue
   fx = pd.to_numeric(pd.Series(s["x"]), errors="coerce").to_numpy(dtype=float)
   if np.isfinite(fx).mean() < 0.8:
    continue
   fy = pd.to_numeric(pd.Series(s["y"]), errors="coerce").to_numpy(dtype=float)
   fx = axis_scale(fx, xspec)
   if s.get("axis") != "secondary":
    fy = axis_scale(fy, yspec)
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
  self._ensure_axes_projection(False)
  self._reset_figure_axes()
  self.ax.clear()
  self.ax.set_facecolor("white"); self.ax.tick_params(colors="black")
  self.ax.text(0.5, 0.5, "『データ』タブでファイルを追加し、\n列を選んで「グラフを描画」", ha="center", va="center", fontsize=12, color="#888", transform=self.ax.transAxes)
  self.ax.set_xticks([]); self.ax.set_yticks([])
  self.canvas.draw()
 def _set_status(self, text, level="info", detail=""):
  self.status.showMessage(str(text))
  self._log_message(text, level, detail)
class StyleTableMixin:
 def _on_x_changed(self, *_):
  self._request_redraw()
 def _on_xleft_toggled(self, on):
  self._refresh_columns()
  self._update_x_combo_enabled()
  self._update_x_multi_enabled()
 def _update_x_combo_enabled(self):
  info = CHART_INFO.get(self.chart_combo.currentText(), {})
  self.x_combo.setEnabled(info.get("use_x", True) and not self._use_leftmost_x())
 def _update_z_combo_enabled(self):
  if not hasattr(self, "z_combo"):
   return
  self.z_combo.setEnabled(self._want_3d())
 def _use_leftmost_x(self):
  return bool(getattr(self, "xleft_check", None) and self.xleft_check.isChecked())
 def _x_values(self, df, xname=None):
  if xname is None and self._use_leftmost_x():
   return df.iloc[:, 0].to_numpy()
  name = xname if xname is not None else self.x_combo.currentText()
  return df[name].to_numpy() if name in df.columns else df.iloc[:, 0].to_numpy()
 def _selected_x_columns(self):
  if (getattr(self, "multix_check", None) and self.multix_check.isChecked() and not self._use_leftmost_x()):
   cols = [self.x_list.item(i).data(UserRole) for i in range(self.x_list.count()) if self.x_list.item(i).checkState() == QtCore.Qt.CheckState.Checked]
   if cols:
    return cols
  return [None if self._use_leftmost_x() else self.x_combo.currentText()]
 def _update_x_multi_enabled(self):
  if not hasattr(self, "multix_check"):
   return
  ok = (self.chart_combo.currentText() in _SWAP_TYPES and not self._use_leftmost_x() and not self._want_3d())
  if not ok and self.multix_check.isChecked():
   self.multix_check.blockSignals(True)
   self.multix_check.setChecked(False)
   self.multix_check.blockSignals(False)
  self.multix_check.setEnabled(ok)
  self.x_list.setEnabled(ok and self.multix_check.isChecked())
 def _z_values(self, df):
  zname = self.z_combo.currentText() if hasattr(self, "z_combo") else ""
  return df[zname].to_numpy() if zname in df.columns else df.iloc[:, -1].to_numpy()
 def _effective_x_label(self):
  if self._use_leftmost_x():
   items = self._selected_series_items()
   if items:
    df = self.datasets.get(items[0][0])
    if df is not None and len(df.columns):
     return str(df.columns[0])
   return ""
  xcols = self._selected_x_columns()
  if len(xcols) > 1:
   return " / ".join(str(c) for c in xcols)
  return self.x_combo.currentText()
 @staticmethod
 def _auto_y_label(names, ctype):
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
  if hasattr(self, "show_ext_check") and not self.show_ext_check.isChecked():
   return os.path.splitext(fl)[0]
  return fl
 def _series_label(self, fl, col):
  st = self.series_styles.get(self._style_key(fl, col)) or {}
  if st.get("label"):
   return st["label"]
  multi = len(self.datasets) > 1
  show_fn = (not hasattr(self, "show_filename_check")) or self.show_filename_check.isChecked()
  if multi and show_fn:
   return f"{self._file_display_name(fl)} | {col}"
  return col
 def _effective_y_label(self):
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
  self._rebuild_series_bar()
  timer = getattr(self, "_ysel_timer", None)
  if timer is None:
   timer = self._ysel_timer = QtCore.QTimer(self)
   timer.setSingleShot(True)
   timer.timeout.connect(self._apply_y_selection_deferred)
  timer.start(30)
 def _apply_y_selection_deferred(self):
  self._rebuild_style_table()
  self._update_analysis_targets()
  self._request_redraw()
 def _set_all_checks(self, func):
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
 def select_by_name(self):
  text = self.y_filter.text().strip()
  if not text:
   self._set_status("名前を入力してください（例: 電圧）。")
   return
  tl = text.lower()
  def match(it):
   fl, col = it.data(UserRole)
   return tl in str(col).lower() or tl in it.text().lower()
  self._set_all_checks(match)
  n = sum(1 for i in range(self.y_list.count()) if self.y_list.item(i).checkState() == QtCore.Qt.CheckState.Checked)
  self._set_status(f"「{text}」を含む系列を {n} 件選択しました。" if n else f"「{text}」を含む系列はありません。")
 def _select_same_name(self, item):
  if item is None:
   return
  col = item.data(UserRole)[1]
  self._set_all_checks(lambda it: it.data(UserRole)[1] == col)
  self._set_status(f"列名「{col}」の系列をすべて選択しました。")
 def _on_y_double_clicked(self, item):
  self._set_all_checks(lambda it: it is item)
  self.draw_graph()
 def _maybe_draw(self):
  if self.datasets:
   self.draw_graph()
 def _series_menu(self, item):
  menu = QtWidgets.QMenu(self)
  if item is not None:
   menu.addAction("この系列だけ表示", lambda: self._solo_series(item))
   menu.addAction("この系列を非表示", lambda: self._hide_series(item))
   menu.addAction("同じ列名をすべて選択", lambda: (self._select_same_name(item), self._maybe_draw()))
   menu.addSeparator()
  menu.addAction("すべて表示", lambda: (self._check_all_y(True), self._maybe_draw()))
  menu.addAction("すべて非表示", lambda: (self._check_all_y(False), self._maybe_draw()))
  return menu
 def _solo_series(self, item):
  self._set_all_checks(lambda it: it is item)
  self._maybe_draw()
 def _hide_series(self, item):
  item.setCheckState(QtCore.Qt.CheckState.Unchecked)
  self._maybe_draw()
 def _on_style_label_edited(self, item):
  if self._suspend_redraw or item.column() != 0:
   return
  key = item.data(UserRole)
  if not key:
   return
  text = item.text().strip()
  st = self.series_styles.setdefault(key, dict(DEFAULT_STYLE))
  st["label"] = text or None
  self._request_redraw()
 def _on_y_selection_changed(self):
  self._rebuild_style_table()
  self._rebuild_series_bar()
  self._update_analysis_targets()
  self._request_redraw()
 def _update_analysis_targets(self):
  names = [d for _, _, d in self._selected_series_items()]
  combos = [self.analysis_target]
  for attr in ("phase_target2", "math_a", "math_b", "ds_target", "fill_a"):
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
  if hasattr(self, "fill_b"):
   cur = self.fill_b.currentText()
   self.fill_b.blockSignals(True)
   self.fill_b.clear()
   self.fill_b.addItem("0（X軸）")
   self.fill_b.addItems(names)
   idx = self.fill_b.findText(cur)
   if idx >= 0:
    self.fill_b.setCurrentIndex(idx)
   self.fill_b.blockSignals(False)
 @staticmethod
 def _style_key(fl, col):
  return f"{fl}\t{col}"
 def _rebuild_style_table(self):
  items = self._selected_series_items()
  new_keys = [self._style_key(fl, col) for fl, col, _ in items]
  old_keys = [ (self.style_table.item(r, 0).data(UserRole) if self.style_table.item(r, 0) else None) for r in range(self.style_table.rowCount())]
  if new_keys == old_keys:
   return
  i = 0
  m = min(len(new_keys), len(old_keys))
  while i < m and new_keys[i] == old_keys[i]:
   i += 1
  prev_suspend = self._suspend_redraw
  self._suspend_redraw = True
  vbar = self.style_table.verticalScrollBar().value()
  self.style_table.setUpdatesEnabled(False)
  self.style_table.setRowCount(len(items))
  for r in range(i, len(items)):
   fl, col, disp = items[r]
   self._build_style_row(r, fl, col, disp)
  self.style_table.setUpdatesEnabled(True)
  self.style_table.verticalScrollBar().setValue(vbar)
  self._suspend_redraw = prev_suspend
 def _build_style_row(self, r, fl, col, disp):
  key = self._style_key(fl, col)
  st = self.series_styles.setdefault(key, dict(DEFAULT_STYLE))
  name_item = QtWidgets.QTableWidgetItem(st.get("label") or disp)
  name_item.setData(UserRole, key)
  name_item.setFlags(name_item.flags() | QtCore.Qt.ItemFlag.ItemIsEditable)
  self.style_table.setItem(r, 0, name_item)
  btn = QtWidgets.QPushButton(st.get("color") or "自動")
  if st.get("color"):
   btn.setStyleSheet(f"background:{st['color']};")
  btn.clicked.connect(lambda _=False, k=key, b=btn: self._pick_color(k, b))
  self.style_table.setCellWidget(r, 1, btn)
  cb = QtWidgets.QComboBox(); cb.addItems(list(LINESTYLES.keys()))
  cur_ls = next((k2 for k2, vv in LINESTYLES.items() if vv == st["linestyle"]), "実線")
  cb.setCurrentText(cur_ls)
  cb.currentTextChanged.connect(lambda v, k=key: self._set_style(k, "linestyle", LINESTYLES[v]))
  self.style_table.setCellWidget(r, 2, cb)
  sp = QtWidgets.QDoubleSpinBox(); sp.setRange(0.2, 10); sp.setSingleStep(0.5); sp.setValue(st["linewidth"])
  sp.valueChanged.connect(lambda v, k=key: self._set_style(k, "linewidth", v))
  self.style_table.setCellWidget(r, 3, sp)
  mb = QtWidgets.QComboBox(); mb.addItems(list(MARKERS.keys()))
  cur_mk = next((k2 for k2, vv in MARKERS.items() if vv == st["marker"]), "なし")
  mb.setCurrentText(cur_mk)
  mb.currentTextChanged.connect(lambda v, k=key: self._set_style(k, "marker", MARKERS[v]))
  self.style_table.setCellWidget(r, 4, mb)
  msp = QtWidgets.QDoubleSpinBox(); msp.setRange(1, 50); msp.setSingleStep(1); msp.setDecimals(1)
  msp.setValue(st.get("markersize", 4.0))
  msp.setToolTip("マーカーの大きさ（マーカーを「なし」以外にすると反映）")
  msp.valueChanged.connect(lambda v, k=key: self._set_style(k, "markersize", v))
  self.style_table.setCellWidget(r, 5, msp)
  axb = QtWidgets.QComboBox(); axb.addItems(list(SERIES_AXES.keys()))
  axb.setCurrentText(next((k2 for k2, vv in SERIES_AXES.items() if vv == st.get("axis", "primary")), "主軸"))
  axb.currentTextChanged.connect( lambda v, k=key: self._set_style(k, "axis", SERIES_AXES[v]))
  self.style_table.setCellWidget(r, 6, axb)
  kb = QtWidgets.QComboBox(); kb.addItems(list(SERIES_KINDS.keys()))
  kb.setCurrentText(next((k2 for k2, vv in SERIES_KINDS.items() if vv == st.get("kind", "")), "自動"))
  kb.currentTextChanged.connect( lambda v, k=key: self._set_style(k, "kind", SERIES_KINDS[v]))
  self.style_table.setCellWidget(r, 7, kb)
  cur_e = st.get("errcol")
  eb = LazyColumnCombo( (lambda fl=fl: list(self.datasets[fl].columns) if fl in self.datasets else []), cur_e if cur_e is not None else None)
  eb.currentTextChanged.connect( lambda v, k=key: self._set_style(k, "errcol", None if v == "なし" else v))
  self.style_table.setCellWidget(r, 8, eb)
 def _pick_color(self, skey, btn):
  col = QtWidgets.QColorDialog.getColor(parent=self)
  if col.isValid():
   hexc = col.name()
   self._set_style(skey, "color", hexc)
   btn.setText(hexc); btn.setStyleSheet(f"background:{hexc};")
 _COLOR_BUTTONS = { "bg": ("bg_color", "bg_btn", "背景色: "), "trend": ("trend_color", "trend_color_btn", "色: "), "fill": ("fill_color", "fill_color_btn", "色: "), }
 def pick_color(self, kind):
  attr, btn_name, prefix = self._COLOR_BUTTONS[kind]
  col = QtWidgets.QColorDialog.getColor(parent=self)
  if not col.isValid():
   return
  setattr(self, attr, col.name())
  btn = getattr(self, btn_name)
  btn.setText(prefix + col.name())
  btn.setStyleSheet(f"background:{col.name()};")
  self._request_redraw()
 def reset_color(self, kind):
  attr, btn_name, prefix = self._COLOR_BUTTONS[kind]
  setattr(self, attr, "")
  btn = getattr(self, btn_name)
  btn.setText(prefix + "自動")
  btn.setStyleSheet("")
  self._request_redraw()
 def _wire_color_button(self, kind):
  _attr, btn_name, _prefix = self._COLOR_BUTTONS[kind]
  btn = getattr(self, btn_name)
  btn.clicked.connect(lambda *_a, k=kind: self.pick_color(k))
  btn.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
  btn.customContextMenuRequested.connect(lambda *_a, k=kind: self.reset_color(k))
  return btn
 def _reset_bg_color(self):
  self.reset_color("bg")
 def _reset_trend_color(self):
  self.reset_color("trend")
 def _reset_fill_color(self):
  self.reset_color("fill")
 _STYLE_VISUAL = frozenset({"color", "linewidth", "linestyle", "marker", "markersize"})
 def _set_style(self, skey, attr, value):
  self.series_styles.setdefault(skey, dict(DEFAULT_STYLE))[attr] = value
  if not self._try_style_fastpath(skey, attr, value):
   self._request_redraw()
 def _build_style_artist_map(self, series, ctype, decimated):
  m = {}
  if ctype != "折れ線" or decimated:
   return m
  items = self._selected_series_items()
  if len(items) != len(series):
   return m
  for sr in series:
   if (sr.get("kind") or "") not in ("", "line") or sr.get("yerr") is not None:
    return m
  from matplotlib.lines import Line2D
  def _data_lines(axx):
   return [ln for ln in axx.get_lines() if isinstance(ln, Line2D) and not str(ln.get_label()).startswith("_") and "近似" not in str(ln.get_label())]
  ax = self.ax
  ax2 = getattr(ax, "_twin_secondary", None)
  prim = _data_lines(ax)
  sec = _data_lines(ax2) if ax2 is not None else []
  prim_items = [it for it, sr in zip(items, series) if sr.get("axis") != "secondary"]
  sec_items = [it for it, sr in zip(items, series) if sr.get("axis") == "secondary"]
  if len(prim_items) != len(prim) or len(sec_items) != len(sec):
   return m
  for (fl, col, _disp), ln in zip(prim_items, prim):
   m[self._style_key(fl, col)] = ln
  for (fl, col, _disp), ln in zip(sec_items, sec):
   m[self._style_key(fl, col)] = ln
  return m
 def _try_style_fastpath(self, skey, attr, value):
  if attr not in self._STYLE_VISUAL:
   return False
  if self._suspend_redraw or not self._has_drawn:
   return False
  if not getattr(self, "live_check", None) or not self.live_check.isChecked():
   return False
  if self._redraw_timer.isActive():
   return False
  if self.chart_combo.currentText() != "折れ線":
   return False
  if attr == "color" and not value:
   return False
  ln = self._style_artists.get(skey)
  if ln is None or ln.axes is None:
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
  except Exception:
   return False
  if attr == "color":
   if self.legend_check.isChecked():
    self._rebuild_legend_inplace()
   self._rebuild_series_bar(self.chart_combo.currentText())
  self.canvas.draw_idle()
  return True
 def _rebuild_legend_inplace(self):
  ax = self.ax
  handles, labels = ax.get_legend_handles_labels()
  ax2 = getattr(ax, "_twin_secondary", None)
  if ax2 is not None:
   h2, l2 = ax2.get_legend_handles_labels()
   handles = handles + h2; labels = labels + l2
  if handles:
   f = self._fonts()
   ax.legend(handles, labels, loc=self.legend_loc.currentText(), fontsize=(f.get("legend") or f.get("tick", 9)))
class BatchMixin:
 def _save_current_figure(self, target, dpi, transparent, fmt=None):
  ratio = self._aspect_ratio()
  if not ratio or self._is_3d():
   self.fig.savefig(target, dpi=dpi, bbox_inches="tight", transparent=transparent, format=fmt)
   return
  orig = self.fig.get_size_inches()
  try:
   self.fig.set_size_inches(self._export_figsize())
   self.ax.set_box_aspect(None)
   ax2 = getattr(self.ax, "_twin_secondary", None)
   if ax2 is not None:
    ax2.set_box_aspect(None)
   try:
    self.fig.tight_layout()
   except Exception:
    get_logger().debug("_save_current_figure: 無視した例外", exc_info=True)
   self.fig.savefig(target, dpi=dpi, transparent=transparent, format=fmt)
  finally:
   self.fig.set_size_inches(orig)
   self._apply_aspect()
   try:
    self.fig.tight_layout()
   except Exception:
    get_logger().debug("_save_current_figure: 無視した例外", exc_info=True)
   self.canvas.draw_idle()
 def save_figure(self):
  path, _ = QtWidgets.QFileDialog.getSaveFileName( self, "グラフ画像を保存", os.path.join(self.last_dir, "graph.png"), "PNG (*.png);;JPEG (*.jpg);;PDF (*.pdf);;SVG (*.svg);;EPS (*.eps)")
  if not path:
   return
  try:
   dpi = self.dpi_spin.value()
   transparent = self.transparent_check.isChecked()
   self._save_current_figure(path, dpi, transparent)
   self.last_dir = os.path.dirname(path)
   self._set_status(f"保存しました: {path}（{dpi} DPI{'・背景透過' if transparent else ''}）")
  except Exception as e:
   QtWidgets.QMessageBox.critical(self, "保存エラー", str(e))
 def copy_figure(self):
  import io
  try:
   buf = io.BytesIO()
   self._save_current_figure(buf, self.dpi_spin.value(), self.transparent_check.isChecked(), fmt="png")
   buf.seek(0)
   img = QtGui.QImage.fromData(buf.getvalue(), "PNG")
   if img.isNull():
    raise RuntimeError("画像の生成に失敗しました。")
   QtWidgets.QApplication.clipboard().setImage(img)
   self._set_status("グラフをクリップボードにコピーしました。")
  except Exception as e:
   QtWidgets.QMessageBox.critical(self, "コピーエラー", str(e))
 @staticmethod
 def _safe_filename(name):
  import re
  return re.sub(r'[\\/:*?"<>|]+', "_", str(name)).strip() or "graph"
 def _build_series_for_file(self, label, x_names, y_names, chart_type, style_by_col, z_name="", threed=False):
  df = self.datasets[label]
  series, categories = [], None
  leftmost = self._use_leftmost_x()
  def xvals(xn):
   if xn is None or leftmost:
    return df.iloc[:, 0].to_numpy()
   return df[xn].to_numpy() if xn in df.columns else df.iloc[:, 0].to_numpy()
  xcols = list(x_names) if (x_names and not leftmost) else [None]
  primary = xvals(xcols[0])
  if threed:
   zv = (df[z_name].to_numpy() if z_name in df.columns else df.iloc[:, -1].to_numpy())
   for c in y_names:
    st = style_by_col.get(c) or {}
    series.append({"label": c, "x": primary, "y": df[c].to_numpy(), "z": zv, "style": st, "kind": st.get("kind", "")})
  elif chart_type in ("棒", "横棒", "積み上げ棒", "円", "ドーナツ"):
   categories = primary
   for c in y_names:
    series.append({"label": c, "y": df[c].to_numpy(), "style": style_by_col.get(c)})
  elif chart_type in ("折れ線", "散布図", "面", "積み上げ面", "ステップ", "ステム", "2Dヒストグラム", "hexbin"):
   multi = len(xcols) > 1
   for c in y_names:
    st = style_by_col.get(c) or {}
    errcol = st.get("errcol")
    yerr = df[errcol].to_numpy() if (errcol and errcol in df.columns) else None
    for xn in xcols:
     lab = c if not multi else f"{c} [X:{xn or str(df.columns[0])}]"
     series.append({"label": lab, "x": xvals(xn), "y": df[c].to_numpy(), "style": st, "axis": st.get("axis", "primary"), "kind": st.get("kind", ""), "yerr": yerr})
  else:
   for c in y_names:
    series.append({"label": c, "y": df[c].to_numpy(), "style": style_by_col.get(c)})
  return series, categories
 def _batch_options_dialog(self):
  dlg = QtWidgets.QDialog(self)
  dlg.setWindowTitle("一括画像保存の設定")
  form = QtWidgets.QFormLayout(dlg)
  info = QtWidgets.QLabel("各ファイルを現在のグラフ設定で1枚ずつ保存します。\n" "軸名・凡例・近似曲線・縦横比などは右の書式パネルの値を使います。")
  info.setStyleSheet("color:#666;"); form.addRow(info)
  title_edit = QtWidgets.QLineEdit(self.title_edit.text() or "{name}")
  title_edit.setToolTip("グラフタイトル。{name} はファイル名（拡張子なし）に置き換わります。\n" "空欄にするとタイトルなしで出力します。")
  title_edit.setPlaceholderText("（空欄=タイトルなし）")
  form.addRow("グラフタイトル", title_edit)
  fmt_combo = QtWidgets.QComboBox(); fmt_combo.addItems(["png", "jpg", "pdf", "svg"])
  form.addRow("出力形式", fmt_combo)
  dpi_spin = QtWidgets.QSpinBox(); dpi_spin.setRange(50, 1200)
  dpi_spin.setSingleStep(50); dpi_spin.setValue(self.dpi_spin.value())
  form.addRow("解像度 DPI", dpi_spin)
  trans = QtWidgets.QCheckBox(); trans.setChecked(self.transparent_check.isChecked())
  form.addRow("背景透過", trans)
  bb = QtWidgets.QDialogButtonBox( QtWidgets.QDialogButtonBox.StandardButton.Ok | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
  bb.button(QtWidgets.QDialogButtonBox.StandardButton.Ok).setText("フォルダを選んで保存...")
  bb.accepted.connect(dlg.accept); bb.rejected.connect(dlg.reject)
  form.addRow(bb)
  if dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted:
   return None
  return {"title": title_edit.text().strip(), "fmt": fmt_combo.currentText(), "dpi": dpi_spin.value(), "transparent": trans.isChecked()}
 def batch_export(self):
  if not self.datasets:
   self.notify("先にファイルを追加してください。", "warn")
   return
  ctype = self.chart_combo.currentText()
  y_names, style_by_col = [], {}
  for fl, col, disp in self._selected_series_items():
   if col not in y_names:
    y_names.append(col)
   style_by_col.setdefault(col, self.series_styles.get(self._style_key(fl, col)))
  prim_y = [c for c in y_names if (style_by_col.get(c) or {}).get("axis", "primary") != "secondary"]
  auto_ylabel = self.ylabel_edit.text() or self._auto_y_label(prim_y, ctype)
  if not y_names:
   self.notify("Y軸（値）の系列を1つ以上選んでください。\n" "その列名を各ファイルに適用し、ファイルごとに1枚ずつ出力します。", "warn")
   return
  x_name = self.x_combo.currentText()
  x_names = self._selected_x_columns()
  z_name = self.z_combo.currentText() if hasattr(self, "z_combo") else ""
  is3d = self._want_3d()
  view_init = self._view_angles() if is3d else None
  zlabel = z_name if is3d else ""
  opts = self._batch_options_dialog()
  if opts is None:
   return
  out_dir = QtWidgets.QFileDialog.getExistingDirectory( self, "一括出力フォルダを選択", self.last_dir)
  if not out_dir:
   return
  dpi = opts["dpi"]
  transparent = opts["transparent"]
  title_tpl = opts["title"]
  ext = opts["fmt"]
  ratio = self._aspect_ratio()
  fmt = self._plot_format_kwargs()
  if ratio:
   figsize = self._export_figsize()
   tight = False
  else:
   figsize = self.fig.get_size_inches()
   tight = True
  issues = []
  xlim = self._range_pair(self.xmin, self.xmax, "X", issues)
  ylim = self._range_pair(self.ymin, self.ymax, "Y", issues)
  max_points = (DECIMATE_TARGET if (self.decimate_check.isChecked() and ctype in ("折れ線", "散布図")) else 0)
  tasks, skipped, used = [], [], set()
  for label, df in self.datasets.items():
   cols = [c for c in y_names if c in df.columns]
   if not cols:
    skipped.append(f"{label}（対象列なし）")
    continue
   try:
    series, categories = self._build_series_for_file( label, x_names, cols, ctype, style_by_col, z_name=z_name, threed=is3d)
   except Exception as e:
    skipped.append(f"{label}（{e}）")
    continue
   stem = os.path.splitext(label)[0]
   sec_label = " / ".join(s["label"] for s in series if s.get("axis") == "secondary")
   if self.xlabel_edit.text():
    xlab = self.xlabel_edit.text()
   elif self._use_leftmost_x():
    xlab = str(df.columns[0])
   elif len(x_names) > 1 and x_names[0] is not None:
    xlab = " / ".join(str(c) for c in x_names)
   else:
    xlab = x_name
   base = self._safe_filename(stem)
   name, k = base, 2
   while name in used:
    name = f"{base}_{k}"; k += 1
   used.add(name)
   tasks.append({ "series": series, "categories": categories, "ctype": ctype, "title": title_tpl.replace("{name}", stem), "xlabel": xlab, "ylabel": auto_ylabel, "xlim": xlim, "ylim": ylim, "sec_label": sec_label, "max_points": max_points, "fmt": fmt, "ratio": None, "zlabel": zlabel, "view_init": view_init, "threed": is3d, "figsize": tuple(figsize), "tight": tight, "dpi": dpi, "transparent": transparent, "path": os.path.join(out_dir, f"{name}.{ext}"), "font_name": getattr(self, "font_name", None), })
  saved = []
  total = len(tasks)
  prog = QtWidgets.QProgressDialog("画像を出力中…", "キャンセル", 0, total, self)
  prog.setWindowTitle("一括画像出力")
  prog.setWindowModality(QtCore.Qt.WindowModality.WindowModal)
  prog.setMinimumDuration(0)
  prog.setValue(0)
  canceled = False
  try:
   use_pool = total >= BATCH_PARALLEL_THRESHOLD
   if use_pool:
    try:
     import concurrent.futures as _cf
     workers = min(8, (os.cpu_count() or 1))
     with _cf.ProcessPoolExecutor(max_workers=workers) as ex:
      futs = {ex.submit(render_one, t): t for t in tasks}
      done = 0
      for fut in _cf.as_completed(futs):
       if prog.wasCanceled():
        canceled = True
        for f in futs:
         f.cancel()
        break
       try:
        saved.append(fut.result())
       except Exception as e:
        skipped.append( f"{os.path.basename(futs[fut]['path'])}（{e}）")
       done += 1
       prog.setLabelText(f"出力中… {done}/{total}")
       prog.setValue(done)
       QtWidgets.QApplication.processEvents()
    except Exception as e:
     self._set_status(f"並列出力に失敗、逐次に切替: {e}")
     use_pool = False
     saved = []
   if not use_pool:
    for idx, t in enumerate(tasks, 1):
     if prog.wasCanceled():
      canceled = True
      break
     prog.setLabelText(f"出力中… {idx}/{total}: {os.path.basename(t['path'])}")
     QtWidgets.QApplication.processEvents()
     try:
      saved.append(render_one(t))
     except Exception as e:
      skipped.append(f"{os.path.basename(t['path'])}（{e}）")
     prog.setValue(idx)
  finally:
   prog.close()
  self.last_dir = out_dir
  msg = f"一括出力: {len(saved)} 件を保存しました。\n{out_dir}"
  if canceled:
   msg += "\n（途中でキャンセルしました）"
  if skipped:
   head = " / ".join(str(s) for s in skipped[:5])
   msg += f"\n\nスキップ {len(skipped)} 件: {head}" + (" ほか" if len(skipped) > 5 else "")
  self.notify(msg, "info")
  self._set_status(f"一括出力: {len(saved)} 件保存（{out_dir}）")
class PersistenceMixin:
 def show_help(self):
  self._show_text_window("使い方", self._HELP_TEXT)
 def _show_text_window(self, title, text):
  dlg = QtWidgets.QDialog(self)
  dlg.setWindowTitle(title)
  dlg.resize(760, 560)
  lay = QtWidgets.QVBoxLayout(dlg)
  view = QtWidgets.QPlainTextEdit(text)
  view.setReadOnly(True)
  view.setAccessibleName(title)
  lay.addWidget(view)
  btns = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Close)
  btns.rejected.connect(dlg.reject)
  btns.accepted.connect(dlg.accept)
  lay.addWidget(btns)
  self._text_window = dlg
  dlg.exec()
  return dlg
 _HELP_TEXT = ("【基本の流れ】\n" "1. 『データ』パネルで「ファイル追加」（ドラッグ&ドロップ可）\n" "2. ツリーでファイルを展開し、描きたい列（Y軸）にチェック（行クリックでON/OFF・\n" "   ダブルクリック=その列だけ表示・右クリックでメニュー）。X軸の列は下のコンボで選択\n" "3. 「グラフを描画」(F5)。『リアルタイム更新』ONなら設定変更が即反映\n" "4. 右端の『グラフ書式調整』パネルで種別・色・軸範囲・系列スタイルなどを編集\n" "   （項目は見出しクリックで開閉できます。開閉状態・ウィンドウ配置は次回起動時に復元）\n" "※ パネルの切り離し（別ウィンドウ化）は3通り:\n" "   ①タブをダブルクリック ②タブを外へドラッグ ③表示メニュー「別ウィンドウで表示」\n" "   切り離したウィンドウはWindowsのスナップ対応（画面端へドラッグ／Win+矢印／\n" "   最大化ボタンにマウスでレイアウト選択）。元に戻す: タイトルバーをダブルクリック、\n" "   メインウィンドウの左右端へドロップ、または表示メニューのチェックを外す。\n" "   ✕で閉じたパネルは表示メニューで再表示、「パネル配置をリセット」で初期配置へ\n" "5. 波形は『オシロ/解析』パネルで「解析実行」「FFT表示」「オシロスコープ表示」\n\n" "【グラフ上の操作】ホバー=近傍点の値を右下に表示／ホイール=ズーム" "（Shift+ホイール=X方向のみ）／ダブルクリック=全体表示／凡例クリック=系列ON/OFF\n" "【区間測定】『オシロ/解析』の「区間測定」ONでドラッグした区間だけを測定\n" "【結果の持ち出し】各結果表を右クリック→コピー/CSV保存。" "「ファイル→Excelレポート出力」でグラフ+表を1つのExcelブックに\n" "【その他】Ctrl+Shift+P=コマンドパレット（全操作を検索実行）／" "「ファイル→ファイルの変更を監視」=更新されたCSVを自動再読込／\n" "　書式パネル「系列ごとに段を分ける」=サブプロット表示／" "データ編集バーの「編集を戻す/やり直す」\n" "【出力】右端パネルの画像出力、またはメニュー「ファイル」から保存／コピー\n" "【グラフ種別と列】棒/円は1ファイル、折れ線/散布図は複数ファイル重ね描き可\n" "【設定が見つからないとき】Ctrl+F＝設定を検索（パネルを横断して該当項目へ移動）\n" "【見逃したメッセージ】ステータスバー右の「履歴」ボタンで過去の通知を確認")
 def show_about(self):
  QtWidgets.QMessageBox.about( self, "バージョン情報", "CSV / TSV / 波形 グラフ・解析ツール\n" "PySide6 + matplotlib 製\n" f"日本語フォント: {self.font_name or '未検出'}")
 def _ui_settings(self):
  return QtCore.QSettings("graph-tool", "GraphApp")
 def _restore_ui_state(self):
  s = self._ui_settings()
  geo = s.value("ui/geometry")
  if geo is not None:
   self.restoreGeometry(geo)
  ws = s.value("ui/window_state")
  if ws is not None:
   self.restoreState(ws)
  for key, sp in (("ui/center_splitter", getattr(self, "center_splitter", None)), ("ui/format_splitter", getattr(self, "format_splitter", None)), ("ui/data_splitter", getattr(self, "data_splitter", None))):
   st = s.value(key)
   if st is not None and sp is not None:
    sp.restoreState(st)
  if str(s.value("ui/watch_files")) in ("1", "true", "True"):
   self._watch_action.setChecked(True)
  self._apply_ui_style(str(s.value("ui/style") or "standard"))
  self._apply_ui_level(str(s.value(self.UI_LEVEL_KEY) or self.DEFAULT_UI_LEVEL))
  if hasattr(self, "_float_actions"):
   for d in [*self.left_docks, self.format_dock]:
    a = self._float_actions.get(d.objectName())
    if a is not None:
     self._sync_float_action(a, d.isFloating())
   self._wire_dock_tabbars()
 def _save_ui_state(self):
  s = self._ui_settings()
  s.setValue("ui/geometry", self.saveGeometry())
  s.setValue("ui/window_state", self.saveState())
  for key, sp in (("ui/center_splitter", getattr(self, "center_splitter", None)), ("ui/format_splitter", getattr(self, "format_splitter", None)), ("ui/data_splitter", getattr(self, "data_splitter", None))):
   if sp is not None:
    s.setValue(key, sp.saveState())
  for k, box in getattr(self, "_fmt_sections", {}).items():
   s.setValue("fmt_section/" + k, "1" if box.is_expanded() else "0")
  s.setValue(self.UI_LEVEL_KEY, self.ui_level())
 def export_excel_report(self):
  items = self._selected_series_items()
  if not items:
   self.notify("先にY系列を選択してください。", "warn")
   return
  src = items[0][0]
  path, _ = QtWidgets.QFileDialog.getSaveFileName( self, "Excelレポート出力", os.path.join(self.last_dir, "レポート.xlsx"), "Excel (*.xlsx)")
  if not path:
   return
  extra = {}
  for name, table in (("測定値", getattr(self, "meas_table", None)), ("ピーク", getattr(self, "peak_table", None)), ("FFT指標", getattr(self, "fft_metrics", None)), ("統計解析", getattr(self, "ds_table", None))):
   if table is not None and table.rowCount():
    extra[name] = self._table_rows(table, False)
  try:
   excel_chart = _install_package("excel_chart")
   out, eng = excel_chart.export_from_config( self.datasets[src], self._collect_config(), out_path=path, only_file=src, extra_sheets=extra or None)
  except Exception as e:
   QtWidgets.QMessageBox.critical(self, "Excelレポート出力", str(e))
   return
  self.last_dir = os.path.dirname(path)
  n = f"＋表{len(extra)}シート" if extra else ""
  self._set_status(f"Excelレポートを出力しました（{eng}エンジン{n}）: {out}")
 def _collect_config(self):
  return { "files": [self.meta[l]["path"] for l in self.datasets], "x_col": self.x_combo.currentText(), "z_col": self.z_combo.currentText() if hasattr(self, "z_combo") else "", "x_leftmost": self.xleft_check.isChecked(), "selected_y": [[fl, col] for fl, col, _ in self._selected_series_items()], "chart_type": self.chart_combo.currentText(), "threed": self.threed_check.isChecked() if hasattr(self, "threed_check") else False, "stack": self.stack_check.isChecked() if hasattr(self, "stack_check") else False, "swap_xy": self.swap_xy_check.isChecked() if hasattr(self, "swap_xy_check") else False, "multi_x": self.multix_check.isChecked() if hasattr(self, "multix_check") else False, "x_cols": ([self.x_list.item(i).data(UserRole) for i in range(self.x_list.count()) if self.x_list.item(i).checkState() == QtCore.Qt.CheckState.Checked] if hasattr(self, "x_list") else []), "view_elev": self.elev_spin.value() if hasattr(self, "elev_spin") else 30, "view_azim": self.azim_spin.value() if hasattr(self, "azim_spin") else -60, "title": self.title_edit.text(), "xlabel": self.xlabel_edit.text(), "ylabel": self.ylabel_edit.text(), "fonts": self._fonts(), "grid": self.grid_check.isChecked(), "legend": self.legend_check.isChecked(), "legend_loc": self.legend_loc.currentText(), "show_filename": self.show_filename_check.isChecked(), "show_ext": self.show_ext_check.isChecked(), "frame_width": self.frame_width.value(), "grid_width": self.grid_width.value(), "xmin": self.xmin.text(), "xmax": self.xmax.text(), "ymin": self.ymin.text(), "ymax": self.ymax.text(), "xtick": self.xtick_edit.text(), "ytick": self.ytick_edit.text(), "xunit": self.xunit_edit.text(), "yunit": self.yunit_edit.text(), "xscale": self.xscale_edit.text(), "yscale": self.yscale_edit.text(), "xlog": self.xlog.isChecked(), "ylog": self.ylog.isChecked(), "xinvert": self.xinvert_check.isChecked(), "yinvert": self.yinvert_check.isChecked(), "bins": self.bins_spin.value(), "pct": self.pct_check.isChecked(), "trend": self.trend_combo.currentText(), "trend_degree": self.trend_degree.value(), "trend_window": self.trend_window.value(), "trend_eq": self.trend_eq.isChecked(), "trend_color": getattr(self, "trend_color", ""), "fill_enabled": self.fill_check.isChecked(), "fill_a": self.fill_a.currentText(), "fill_b": self.fill_b.currentText(), "fill_color": getattr(self, "fill_color", ""), "fill_alpha": self.fill_alpha.value(), "data_labels": self.data_labels_check.isChecked(), "aspect": self.aspect_combo.currentText(), "aspect_w": self.aspect_w.value(), "aspect_h": self.aspect_h.value(), "bg_color": getattr(self, "bg_color", ""), "export_dpi": self.dpi_spin.value(), "transparent": self.transparent_check.isChecked(), "recent_files": self.recent_files, "styles": self.series_styles, "scope": self._scope_dict(), "npeaks": self.npeaks.value(), "tabs": self._collect_plugin_config(), }
 def _apply_config(self, cfg, load_files=True):
  prev_suspend = self._suspend_redraw
  self._suspend_redraw = True
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
  if cfg.get("z_col") and hasattr(self, "z_combo"):
   j = self.z_combo.findText(cfg["z_col"])
   if j >= 0:
    self.z_combo.setCurrentIndex(j)
  if hasattr(self, "elev_spin") and "view_elev" in cfg:
   self.elev_spin.setValue(int(cfg["view_elev"]))
   self.azim_spin.setValue(int(cfg.get("view_azim", -60)))
  self.xleft_check.setChecked(bool(cfg.get("x_leftmost", False)))
  self._refresh_columns()
  want = set()
  for p in cfg.get("selected_y", []):
   if isinstance(p, (list, tuple)) and len(p) == 2:
    want.add((p[0], p[1]))
  self.y_list.blockSignals(True)
  for i in range(self.y_list.count()):
   it = self.y_list.item(i)
   it.setCheckState(QtCore.Qt.CheckState.Checked if it.data(UserRole) in want else QtCore.Qt.CheckState.Unchecked)
  self.y_list.blockSignals(False)
  self.series_styles.update(cfg.get("styles", {}) or {})
  ct, mig3d = migrate_chart_type(cfg.get("chart_type", "折れ線"))
  self.chart_combo.setCurrentText(ct)
  if hasattr(self, "threed_check"):
   if "threed" in cfg:
    self.threed_check.setChecked(bool(cfg["threed"]))
   elif mig3d is not None:
    self.threed_check.setChecked(mig3d)
  if hasattr(self, "swap_xy_check"):
   self.swap_xy_check.setChecked(bool(cfg.get("swap_xy", False)))
  if hasattr(self, "stack_check"):
   self.stack_check.setChecked(bool(cfg.get("stack", False)))
  if hasattr(self, "x_list"):
   want = set(cfg.get("x_cols", []) or [])
   self.x_list.blockSignals(True)
   for i in range(self.x_list.count()):
    it = self.x_list.item(i)
    it.setCheckState(QtCore.Qt.CheckState.Checked if it.data(UserRole) in want else QtCore.Qt.CheckState.Unchecked)
   self.x_list.blockSignals(False)
   self.multix_check.setChecked(bool(cfg.get("multi_x", False)))
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
  self._update_analysis_targets()
  self.fill_check.setChecked(cfg.get("fill_enabled", False))
  self.fill_a.setCurrentText(cfg.get("fill_a", ""))
  self.fill_b.setCurrentText(cfg.get("fill_b", "0（X軸）"))
  self.fill_alpha.setValue(cfg.get("fill_alpha", 0.3))
  fc = cfg.get("fill_color", "")
  if fc:
   self.fill_color = fc
   self.fill_color_btn.setText("色: " + fc)
   self.fill_color_btn.setStyleSheet(f"background:{fc};")
  else:
   self._reset_fill_color()
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
  self._sync_explorer_checks()
  self._on_chart_type_change()
  self._apply_plugin_config(cfg.get("tabs", {}))
 def save_config_dialog(self):
  path, _ = QtWidgets.QFileDialog.getSaveFileName( self, "設定を保存", os.path.join(self.last_dir, "graph_config.json"), "JSON (*.json)")
  if not path:
   return
  try:
   save_config(self._collect_config(), path)
   self._set_status(f"設定を保存: {path}")
  except Exception as e:
   QtWidgets.QMessageBox.critical(self, "保存エラー", str(e))
 def load_config_dialog(self):
  path, _ = QtWidgets.QFileDialog.getOpenFileName( self, "設定を読み込み", self.last_dir, "JSON (*.json)")
  if not path:
   return
  cfg = load_config(path)
  if not cfg:
   self.notify("設定を読み込めませんでした。", "warn")
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
    n = len(self._selected_series_items())
    if n > HEAVY_SERIES:
     self._draw_placeholder()
     self.notify( f"前回の選択（{n} 系列）は多いため自動描画を省略しました。" "系列を減らすか「グラフを描画」で明示的に実行してください。", "warn")
     return True
    self.draw_graph()
   self._set_status("前回のセッションを復元しました。")
   return True
  except Exception:
   get_logger().exception("前回セッションの復元に失敗")
   return False
 _PRESET_KEYS = ("chart_type", "threed", "swap_xy", "stack", "fonts", "grid", "legend", "legend_loc", "show_filename", "show_ext", "frame_width", "grid_width", "xlog", "ylog", "xinvert", "yinvert", "bins", "pct", "data_labels", "trend", "trend_degree", "trend_window", "trend_eq", "trend_color", "bg_color", "aspect", "aspect_w", "aspect_h")
 def _presets_dir(self):
  d = os.path.join(APP_DIR, "presets")
  try:
   os.makedirs(d, exist_ok=True)
  except OSError:
   get_logger().debug("_presets_dir: 無視した例外", exc_info=True)
  return d
 def _list_presets(self):
  import glob
  return sorted(os.path.splitext(os.path.basename(p))[0] for p in glob.glob(os.path.join(self._presets_dir(), "*.json")))
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
  except OSError as e:
   self.notify(str(e), "warn")
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
   self.notify("プリセットを読み込めませんでした。", "warn")
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
   get_logger().debug("delete_preset: 無視した例外", exc_info=True)
  self._refresh_preset_combo()
 def _apply_format(self, d):
  prev = self._suspend_redraw
  self._suspend_redraw = True
  try:
   if "chart_type" in d:
    ct, mig3d = migrate_chart_type(d["chart_type"])
    self.chart_combo.setCurrentText(ct)
    if hasattr(self, "threed_check"):
     if "threed" in d:
      self.threed_check.setChecked(bool(d["threed"]))
     elif mig3d is not None:
      self.threed_check.setChecked(mig3d)
   f = d.get("fonts") or {}
   if f:
    self.fs_title.setValue(f.get("title", 12)); self.fs_label.setValue(f.get("label", 10))
    self.fs_tick.setValue(f.get("tick", 9)); self.fs_legend.setValue(f.get("legend", 9))
    self.fs_annot.setValue(f.get("annot", 9))
   for key, widget, kind in ( ("grid", self.grid_check, "chk"), ("legend", self.legend_check, "chk"), ("legend_loc", self.legend_loc, "txt"), ("show_filename", self.show_filename_check, "chk"), ("show_ext", self.show_ext_check, "chk"), ("frame_width", self.frame_width, "val"), ("grid_width", self.grid_width, "val"), ("xlog", self.xlog, "chk"), ("ylog", self.ylog, "chk"), ("xinvert", self.xinvert_check, "chk"), ("yinvert", self.yinvert_check, "chk"), ("bins", self.bins_spin, "val"), ("pct", self.pct_check, "chk"), ("data_labels", self.data_labels_check, "chk"), ("swap_xy", getattr(self, "swap_xy_check", None), "chk"), ("stack", getattr(self, "stack_check", None), "chk"), ("trend", self.trend_combo, "txt"), ("trend_degree", self.trend_degree, "val"), ("trend_window", self.trend_window, "val"), ("trend_eq", self.trend_eq, "chk")):
    if widget is None:
     continue
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
   else:
    self._reset_trend_color()
   bgc = d.get("bg_color", "")
   if bgc:
    self.bg_color = bgc; self.bg_btn.setText("背景色: " + bgc)
    self.bg_btn.setStyleSheet(f"background:{bgc};")
   else:
    self._reset_bg_color()
   if "aspect" in d:
    self.aspect_w.setValue(int(d.get("aspect_w", 16)))
    self.aspect_h.setValue(int(d.get("aspect_h", 9)))
    self.aspect_combo.setCurrentText(d["aspect"])
  finally:
   self._suspend_redraw = prev
  if self.datasets:
   self.draw_graph()
 def _snapshot(self):
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
  del self._hist[self._hist_i + 1:]
  self._hist.append(cfg)
  if len(self._hist) > 50:
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
BUILTIN_TABS = [ _DelegatingTab("data", "1. データ", 10, "基本", "_build_tab_data"), _DelegatingTab("scope", "2. オシロ/解析", 20, "標準", "_build_tab_scope"), _DelegatingTab("advanced", "3. 高度解析", 30, "全部", "_build_tab_advanced"), _DelegatingTab("datasci", "4. 統計解析", 40, "全部", "_build_tab_datasci"), ]
for _tab in BUILTIN_TABS:
 register_tab(_tab)
class GraphApp(HostMixin, UIBuildMixin, DataIOMixin, StyleTableMixin, PlotMixin, ScopeTabMixin, AdvancedMixin, DataSciMixin, BatchMixin, PersistenceMixin, QtWidgets.QMainWindow):
 def __init__(self):
  super().__init__()
  self.datasets = {}
  self.meta = {}
  self.series_styles = {}
  self.last_dir = os.path.expanduser("~")
  self._suspend_redraw = True
  self._has_drawn = False
  self.font_name = setup_japanese_font()
  get_logger().info("GraphApp 起動（フォント: %s）", self.font_name or "未検出")
  self.setWindowTitle("CSV / TSV / 波形 グラフ・解析ツール")
  self.resize(1280, 800)
  self.setAcceptDrops(True)
  self._redraw_timer = QtCore.QTimer(self)
  self._redraw_timer.setSingleShot(True)
  self._redraw_timer.timeout.connect(self._do_live_redraw)
  self._dyn = []
  self._dyn_cid = None
  self._resampling = False
  self._resample_timer = QtCore.QTimer(self)
  self._resample_timer.setSingleShot(True)
  self._resample_timer.timeout.connect(self._do_resample)
  self.recent_files = []
  self._cursor_cid = None
  self._cursor_pts = []
  self._cursor_artists = []
  self._cursors = []
  self._cursor_drag = None
  self._cursor_text = None
  self._build_menu()
  self._build_toolbar()
  self._build_central()
  self._build_statusbar()
  self._on_chart_type_change()
  self._restore_ui_state()
  restored = self._try_restore_session()
  if not restored:
   self._set_status("『データ』タブで「ファイル追加」、またはCSV/TSVファイルをドラッグ&ドロップして読み込んでください。")
  self._suspend_redraw = False
 def changeEvent(self, event):
  try:
   self._on_palette_changed(event.type())
  except Exception:
   get_logger().debug("テーマ変更の追従に失敗", exc_info=True)
  super().changeEvent(event)
 def closeEvent(self, event):
  try:
   self._stop_background_tasks()
  except Exception:
   get_logger().debug("バックグラウンド処理の停止に失敗", exc_info=True)
  try:
   save_last_session(self._collect_config())
  except Exception:
   get_logger().exception("終了時の設定保存に失敗")
  try:
   self._save_ui_state()
  except Exception:
   get_logger().exception("終了時のUI状態保存に失敗")
  get_logger().info("GraphApp 終了")
  super().closeEvent(event)
def main():
 setup_logging()
 app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
 def _notify(text):
  try:
   QtWidgets.QMessageBox.critical(None, "予期しないエラー", f"{text}\n\n詳細は app.log を確認してください:\n{LOG_FILE}")
  except Exception:
   get_logger().debug("_notify: 無視した例外", exc_info=True)
 install_excepthook(on_error=_notify)
 try:
  win = GraphApp()
  win.show()
  sys.exit(app.exec())
 except Exception:
  get_logger().exception("起動に失敗")
  raise
if __name__ == "__main__":
 main()
_PACKAGE_NAMES = {'excel_chart': ['excel_chart.mapping', 'excel_chart.spec', 'excel_chart.com_engine', 'excel_chart.openpyxl_engine', 'excel_chart.export', 'excel_chart']}
_PACKAGE_BLOB = "c-rlKZF3YylJN6+enoFzY-~3SjU)s1Dt0bT7TD%i7#_rWy&>x+S~ERTo0;jk?$JxHA0jj(n->F%jg7I5Zx<UI3ozgpc8vkUhx;ct8cBTeUwAUJs=BM+W=5F3*o!y?NZs|4m6es1m6?@Qt*UCxY&NP+vue*MJC*f|U#x%f)#mj-ciKO6+K)Qz&pRtOy33y{|8@MlvTvzmRkiVh2RbYForYC!_)Aq?f!t2(Zl`std;4Mc(I=aqu6CB&x%G>mb#H#yX@AyPx!75`{?mh#*htfIjfwp)@0&dGhlzcY(B6Tu!@u2k7@zj;dtvN%6Gw`a_0xk>oz|JPA0KsE#}x^|^}n{Dp&T>`0M#9;qVB+74*d7v|33{^o_%&^m#TDH*E_9i2&H|#vkZ0q1FCge58)r{h0<9$OPxF3X<zBAe9&os-C4QTS-F7V3FVuem3Mh|>+Z&*`<tuZby^>F+NYs+Kmw)Py3=XhR$h623|d?5zH_G2`cSdz^EHKGw|?Qy`h~9%h2@qY7O#{$c<|K&6Hx8e`UfYvH!pTiUIaWhAH9zaEVp0$-G0cs0R`9YE_Y9!SbO*%NXphl>eZVYci!Ll_VnWqJ_GO@4?jm@tE!qqvKIG_O}?ZQls9q;`~ZDM@vk<V2l6;oyR7PYp2M=VU64~Yy}2;MU>Uo4#$Klx<c)H0&mcJ8le1oS>K5c`_&2ZMZ;`|5#Bz@1*tmzNVli#UuHjuH0KAUS1ONx&J_o5K+bvbYbPv<1Xa7ELx?%diVLGDNbZxUfE7jPGIS9XOn>D8%Qlp%ev4k0b)gEkrDM;Rq$-joAMs?l`QVm{s7z>vr;%t*Myr$^}ISXmH9?O-jiee#`7Hg(^)N(cUM<1nHuGO4(>wM-IvsRO5D~=0v%twi(PYq2IJi&rb1LW|ugd%c@R<-Mv*YvAa6kx!U1T!d<kFaDC#isx=f@0O0wd&<!!}08<?bNlZQ{q7333w0_sH-yoOx2C5vj`N@sf1mDWDs0VO;zl=B1%#bk-}g}NWx$bJsVVSI*mx(`9`C6-91A=-Kte-_A2_!a4wp#dn8KB|MtGCGwKueTy3g@^;@l~a<5far9KxMrt4Y7IcrHPIaNn6H-M`<O@)#Ypim%Dng_J-nl7(tz@yy=$>13{Z=2qt-JH|Ze^T`j5LKKS9-S6tt5#j}bfr*Go{5%HRpWKXu4|<^Wt%dhRDdGz2z~VQSlwR~ls#eHrt60<_)~G6nzSk!gtMpEwT9z1m8OFvh*ZGVSu*cmfG_^wBxy8hU2GtaL>r3}DuNBq)a-gw^QMMIN2c@2@E$#{u!ND(UD1SHqkC8a>oITn6|*{T?Q`9%@xj3b+>6kKnOQe7xbEx>^er*+f}WUddjutW=-s?Bn^zDH6qgyxRsNr%%__h7jq;q1k2ClP$jb=1?(FQ$%+tq-v-U5CMqU;FRppn2;j0tjx`_giFR}b*S3b<)!ro&g_UsnRnqMTr8CHCDSD59MOw`jvCd#8<^IYi2e623Gw|h8}RfK6$I%?s9s_Y)&Su>^^MN!%PEYE7#Ry+$Az*i@V<6}qmy?F5OAE2wl`2Nb+#P9aO%Lu+4I=mm&svvK2-}u3o_p$`apBx{X*jL1*VhnW*l#_D$!54YrGr9i*s#Bo*tzWv^eQ*xcvbDQ6H*TB;O?KnlLuGspX8vTuDxsbiD3cq1eY4Yg1f@EytEhs3(gsT3A%D^?TYE@-z0qm6W!;shaP_mj+FALo)4q$pDI-<O!{?O~os|cmi?4rq`tkB*Y^&3H5C65#cRyR%xNwGa#fyXoJYVayA@{oI3#hB0=$==Gp?%QPZz*NF)Z7^W?X+)W-$B`L-Ce(VW%KH}?wJn|+Hxz0TJFwZC4u_T<BvP-GpI_-=(pQk`;{mK>g<<S9-lbL5L-V7n4BZCARzI>OB;W^+I?#UmFN-W@iIVu8|T9|5^qJuPo8ENhOQ{1%J{^7K&I3F4)I<&g&k|3LdChYy0Lnzd-4lta^upS^*?>Fe&$5?*2f_vv(W%(^@=^Kl`6CPsKQJWg{j$R)*c0P|I6m;O{l8;>*T?gVK5Pgs#R+8+DiAw&j5F3RDdC}@%}0)-Xx97CNO^0^gJt&!$DGBsn}Mv%nCOBhFzZ(WhQK|nO6>y*fp!Uhz%4@a*`h~PnZs^21*YkfsW5p7VUC#4pN2<G0oZJ$3j?!ivs(PSZ$Xv1W9JKF=tYhA)IxRVFpdB-CKXz`2ORdjg8B9#4EjnZL-n+;qjk75UB>0YX89BNAZ<-`69lOg&_2P)<Bra;N8VX2cNr_E^U5!9$!6{b&9|K8@_Iy`v!&rU-zncd970alb|hOq5r(71kXP`IE~NSIfD3X050P%jU7HxJo1M_)Zr<0{cW&U&mj6xZvD!6`m=hSKW$t)3lo0r?%SQ#d69YHO84$c_tJNS^YP=<<CXI`n^sN=sd8DJ&izZk3px6&Oj@pOc{o+r5>Pj5)+p*9^yVYyg|AF=3Akhm(x(C8V66!FfvTXQu|o|qh%H8yO4Tu&C@+oOl*PCqsGv%T$Rc3{;1tR;muxR6-f(Rw>$6%%?Rq%|$Z}okK`P1#VgzD?(V~Q}MVKdHf5MTW5=+Hw=%nrtbw_D-O@*Y!GBgu4SijBrYO`1|OHIf13soq{*5{_(l<3HttC}-bHJ0e7C3+T!iZW29n3l^_@lj>QajKAd#GSXK^df4yq5>)7lsW6#DOHwgc3mO>4OWB%OEq(;X92$-1iv4IrK&R<VD^Gp^?1GX<R!blV7bk-3Yj^`D2$R`N^YZ+R%gbpLt)T1k=YsR#-_lo=Y}{>&sp~DTr<phW=Q1x3vp)6YR)-jh6-qWk#(t51-VX)m}m19UPI0;M1;w<h?J7la-6hYfr)h#0pfYvwxf%tJL}1229+fvg&x3oc;i@*OO+v${f*|a*?<x*RQbvF0Lp>!!H|#Y{2o#R6$LG_BI&V0#(V>Y$kG@}WRL?aowXk;Oh_2876Yqm;hfYGl))|(s2>7g9#PdfnG2YZs6-;N02pBvzFtC&Kr#kd;o6x;F{vj(1wykxY@x|D*&3TiDXOPbW%4s<i?6@XkeXQ-g>9@MX`#-e_)TjGrE$;>zF;dtDnrLnCI|WWl7$76)Im}98ZW5paXSULUz4~!eB^VYz-I;<_5%AO@pYd`CaY{Tu`07Tixj6`^@|l7#*-Y0DYFAgvYxOM=r(X-VnS3SB`s9)ta1@3hb5(H!d(YYA~rt=!qid2YgBCj@mdp^LZ@kUlq`BSBaT|Wr|IO-c#XL;j!yTTmkrZ)2}ZnCj*Vt}Amf^5y<}-vHm_(^QX`x5jjE;Vidip{BLOqX4>6*Trp%an)2{R7Bxs(^HNXk$P7Q&rP7lM=aYTZVKvNd6!U3U{D^+w~1o;ED{Nxg+qP|h79(%3%1|WV+eHy|inDMysFo>a;|6lp@k0O5}MPy+lCU%%c%6hOM$DlKTMH>{z*+KQCB03>!4!T7ZP(dt3lkx~nWDSx;F_2NQ7s(<8GsKZz(}=^A&afbR=OwxJ8Rq(OZVZ)(N?MS_UL+%}E>lbksAGj)XNgc8l~Fyl2CA}!SOrYOHkg|^S_^gDSSy&6(FW?ig<^faCJhH9sZfs8-b9|cq{d<RNf^F>;U{7EX)sX#jbV*RfHi5O1S(m?j~0nSWSVdsC`-+%<fm5hdsmV)>sUo8C#y0j-myxMl2sV>@d7%3gTk1CGHi&Z5Bv!$=z$tA@4<pBbZuA(E7B5%`YI~I08E#cYAj|j+b|as&LI5DWi2eAM^;>qFSiwgTaFpk4L@2p*c{;YZrZXSs<I+UK?Wt*<^?ib(^_hVyB7G?-%|_)C4~U%<jEhOXJ(DAC#o`WPi;lEJ}4!=^FjJgcI%Pd0CI5gZT=z<wgy%ecXTmlxK*DG3NMhB!BaI*^0-mXRJ*hW5uF7=5GIjXR~90>2`T#+i5-*(B|JU86_U0g5$`>Ej?qIZyFxL_!C$oN&y4)^;8cNP1G=})bl+NCyLW#5+@((I%UIY!;0+eh2krA4@Bd}}<U2vAL9To2FF~pE3bok!a`Ug>cTZnne%fdR0u?pJ8lae#Or!!-yG{WPcRTGb$=!Rhv+@}^fN!7+`P?<`nq@A~P7A<X>9nr0$cB|aQ<a;DI{pLfPct7b^Obg5w-MFW4^X3f?)K)&k3a)hWH(lCbyn_gp86JkcR#=0X<dK^goa+{8|1^ipWD2DcjNY(-Amu@6rm<35h<u~`{DY9uOS<s&z;@85BT2S`0A?>o^;~VwTGwIemuMJ<1GR!oY_djj~ECVmTT0|JMf$0Fxt7ztF5*Be;ZYP4=RbX=qcNk19r)EJg3s+MBc9O5rpCspr$VE?5up)Sy@4!^U7D9_77`!&q7B7H~cLmCJz1=)D}i<h~a9T*?99)bmgD_y8GD*k?*#c59=SbS%^pX^KaHK0O2p8Z+*G7=-Qy(>Pq+B2c6b;-4pj{RKCoufB2`3&*0^{a(Eup=NjWqWQoViEh>im0<<S4y2f$AuCL$#Lc`V)HQfE?b3knU^jqB@-{V9<CpJfm{lPuO`KDbJsg9QmrZK1to&x_G+@EcT9@Rj-M$b0n9mo|AOdc%0Fg7uXUhE+faOQ$(!@5$1-bFU_qfHtW7@4An%DGCzP;zRZXGul|la?SiK|Mo3quJ%9VGhy@oo#h^#2n@UnnO#auKcqy6i(=RUUA9jSg1K=t*-1)hV#nE9zC*WTbgsVJ-dM`z>?aocrxN#Zo@J}yJ=db*32_Q0Cy?#%<WWcKqAI7gkl}vl42cd8^CXt@d`+Dpc3vN21JZW!(2v%9mArH01cUPDUH40xYjt9H4eY{Ja$*q6M#e~QtJMmyl3cBB`GRO>M84jsInKjK8e;3(jA`ri0uaYh>^%_Rv=dZF)Mk+nQs;wW^<050t>AF1yVoqz=trQVNF3+D~m)}*<7>e%~@8{lYIvfG&v&+wlhjq+p0H_p(!a9S<ICeXVZpNNuHunGbOQNFd-mh4$6$~qqjgxk+k>-*Au&;(CS{TD&g7!(-vk0O+dB|3yJ_?9nZig!<_N(uO_nepkUc{rE>6wW^b$<+W4$!*gL3EGml!3=4m_=No#w}qI0xBx_VHT1E*XsgdG9qS~X`O-Y_aXA#&tkfuyj|)bMm9NX7JuOI5E1bs{5=x+Q@EiC|y>CKk{oAykusvU>z^6%a_H*gc$N42mLx;zWH=V(TTdG-nz6>fXF-?X{82r8!MaEWN7!RCq=#Cm3T%3c&iGzS#I1EWJ0x;&G8e8)^AoZU?Imt*GDe-6*~|UBLa@<(3+4L8udaffozbX;^YLub<_c%b+E+E+d52o4}Vqg<``8UcT8`xk9VV_pk<TT)wmZ&RJUAZY!}yemQY)d~9Ou(4oC!N5+2n+G|IwTI03X0yyWpr`~@2(dTK*P4t)K92p;c+UrsY9Ez&xk5$3)@glndk>Om#@C;Vt_l|oMpdIy$G0@UO(Z7h*7iTD+NeyjS&NW_!8H0<>UND!!e%4)Q5d}BNt0J0G+9GJSLU4r;$Tfi_XXfoH7&`bGDVir(VFk{!MRUpWiYA)VWK}aKEUOl^X>dxz0*6Wt7&n?M0J)3I032(c7V`~SiJlW_#wxJX7NQi1mKt|}gLORyOb`m~3q(nu8hs||O++-4)>ECiBEk07(4FZr|0?-Lv4WncFjI9(N712*{!oop>?suX)5<nQBWODm1}O$=I_a14jKgMq*3#f%+^SYR3@;o8lRkJyK-3^4B5YkZ$ZSCV#AJ!xj7f9B8VjW$n93lAUZ4>zND@hx>x@?&&(g5w_#9&5v9&B=83~|Vywzc$@OxN3jPL*Nye%8gy(7SA84f%LAX^9q(|)ozorf5jKA?wu&YrZ8Pv<PNY`NtAM!t}Ew#YZ8SQR!j3rJZi%$)*7mZITIA?GZEM;k}F1S|zso%0lp-~ubWfQ1-HJ+wrJ7^+y{b!Y+0V1T#fq6?aL0Q!uPfrVjd9xX~d^Loe@bAe4A77bW7x(8qrXA%R}V-u8#n5ihs#`=()OHfPrzZa(LY4RE<zfm{|XyuFA-2rl<T0|VVpy(H{pKOu@9UftmBqRV#LC~|Y8BQ-<k3dP8Gn}vMjKO5ai80kw5OP_Z_dqNz$)&=Qq63s`Fh44aK=w-9hOw!ys(C3%4~L$4hcGAZ9g4#@7|#hm(I6l)-A6Il74;1U{#X%8BdWrqq{~EOwL%jKj45l0E6&@PTONK}J||Mc@hFC_HyI%ZE0QX;q^5dAhC`j5K#l}mxAUy`;lz>XkkN>*(oT|x#tR^u+9I~IU9p31Y%j3jSqZoZMJa|mZC>hd$fGdb1M?782I4q0TSGk_=9)4D!rVlB!z~T6>TqRGi#Wn?rCZ;0THkhB=T$vmhaPfMvWb}aIFREJ%W*u)6@$BL6E*le#Q`W+rUDw{QJI3$C>u?uNF=sP=mxY<1NI7P$+6s$rG}2k`I-T3)lE$|YL;2obmgB5%8>D#WKuA(Abf=Y+V-Hl5OBg-7)nco$y#stn$FO|q633OwMGW$CBTKNG#iGcqU{CU#Ziz(TDV&yf=PPoPwF5*D2=#4{1Di52BkS5Qn52h&RJ^4^sHjYl3Hx_FCpn-Y#VS6v&_N>x<pqF7_UxD$??e3@w!*eXVv0y%842*m@lIehAGEu#Do5Nwig6H$Dv?oU`9<0fR>AA&S-tWuJ&ZGH1e`Y@CdWAyhs4~v~YHz^h=JpCk?ycVuJz$dx;NLgh)g&;)C^2s%5&CnXERPQZfi?ADqpk+APYx9|?PqpGk|5u2Fi2(!Y;6$WXv(N48_u^kd?7uEA8a$vLxOkrhXQmLu8@P)o5c?!mGDG)c*U$DdhboSu_yRRCxZ1O~oD-cfipSU|-%3zo(+M!Mv5^-9b#jQU<7bw602U{o7>t*V7CZywocmzS__api>q3MiTvR#moIB{Y^$jpeYImMU``gC7rBLE476iF&EpEdfYqxKLkYg-3>B>vd8P@X-blKw~YL^5Kx@89K>*!(bqK>z96Sg8H1GUSuQH7gQn&p)Cc}iV`U`kOvy?!4$^J)*?%lEKjHsxCltUjpV!{%)ZpI@UzFlm&PI(dK}hNcerTo)u25poQnh}^^tuMjlP-PPQoA;jnmXRLYx8s5;l9bd7d!QNp@jS4wHN$&O;p#kuj+GqU+3~_&|vj9<TX1NC^iPqoM|Xh;odC$o`?fE5hQESR81gBsD3n<EOH*w4dS$WrdZ;L#bPzKwF#vPmRZW^LG|+3n?YVd;}UNMptKhkr3ibrib3o306-EPM7&G0ZN7tRtMTl&N+*RP!X*+%~>lBZvYP!amqkkHX0tQpgl6=bLo7cXGjP3XtxdvNT;1WBRrhU2<Zv+0Z-JXN&ZmLWh+jgAW;xZilQRmf?`y)k23j4g-An0bt%vFA3Yc|sZA^ukZ7R8EGbH-9tM~QJR){)pIyeDQigdyjTh`{HMxV?t8niv%O{jhk{lqlmyfzI`=s$D9V6JgjC3#D3J!6O><BZy;d)lkjy}jPC`D`@l^Bs9<HsF2I>;{#l|U64EhxbFM&(y9NcKP)RMk;awsEmn2dIG9!>t{a*#RK^g3eX$8c9kEUeW#|*28!(bismvtJ!t!*%92Sn6H-uY%%&&*Y!lG)c_n9Z4kL-mS7XlWb#Y2*7IP;^{O?%V5P{`pCeBP^w3L=tQ5@_{Z~C#Gv-=MDuklq)~2~xBgH>sW#cgQjI%M3pOn>4RM%67k+xBvH(hP7?XuOk07lRLdZ{{Jw(t=ZtpeW3v8zw}W7LTP>q}la01B_imQtRkKZ)Ft*Q#DydMQx~Ot}DNIf9|XVmFj{je?1znrM(bnhclbDktU|N7%M|SbnQ~-rLgQUG24LDT&}{e_>861xnQz5KAMiR2&e`GbNQD2~YN(pWcghA7RQgOz1AG1ggSG`Y?!L=gdZ<O8$eYrBOYxkpQwScnnjk&a8N3LArV_f!6`^b;o_twacVvL<SinqX%9xB9vS(tErTvqxJpB=%<j80QMv!E0In{zXutq9;cEYlF<*z=!azV<75o*dRk<}Ad$MSrCL>~2Dsi+)|dJWLSS&|srq#Mlxd0tEcF}}Q6_y{V&J#B1ofKhB=+QSMtbIz1sdT68eAGyKA>qaS`{jty%Hfr1EjQFo3Bk`8$o~?*3+Ya%%y&S;CBijbLq)uAi*SH+|Xyk9o$NRH^4Zvp|db@k;Rj@c-R7Rde)(;(>&;w$w;AzAkUitqVRf*Y_D}{f{I5bAA^t-GW>*e%2LIE7>D>ZMv}@Jzu-s$glA3$>K(>%hxc4a;d#&w3#Xz;-i!SMxPN+Zk}h{+w?xEaxi{{-uN?B5b50%JcntE+nprwHxszgzJ1h6c_s0W{p-~FX!XRw{kixhCW_WAe?cDk&Uu~SahF6n(zxw#naTbk@5ySBqbByA`Ah6&rj_&cZ8|NN&?_Cuk$=BBIU7$elHVY~qKX_m#3o}2H3!=m*{CSmbOId!rvWgL3;$FKOk3acV#4cZ@dqb{M)YvIGJdJMmJIS)v&%FcXS=?Foop(E}ciBCBX|c@g`n_ln<!Y}RNP<Xux}R`V2~L9HeTTv>$LA~O@i!UC@DQ_+AqA8gyn`fRC<BGo?w#(QI@?)!576nJ`2f0_>z@4E<B#4MRYcr6(5K|oW?&`42!4hPptbq=iS9cmF>3z1`*fel`;4mWR+IJbzwdssO83d!-hA}#+Jgrh9|JjWte^U((>nh5ir(IL;CIDC`wkZm9l`K`k!OdVG=y7Bs+17!?3mtxf^`Y~V9xShh;Y6q47-$MK+iZ_QS2W+5SJny1yRJd3=i-#!7N&^coNh3qXCUi7`zn^x8kR@G6J{Q-gz-QSc`=_1@T%XR)JbU$jNA}#o(Z?h&alnMOB4<z-Xl@trUxok~fxOtxrdH$RgW!A!noCk@ZRTa-%nc>ZNKRi*#;`gW@YK7>T7hVAGUnswa*36w#g~*D{+HE3HLiHKSprI2=4^G9EW7D9C~@p__sS4bMzOdB=kn|Gu#=|Ko$m(!;w_rqe(nJYk>z!2)<hdp|FNryrEwK|9PwVKc2xB8K4?S#W5f3vT+FwVGl$*qJ05jf(n4BA)?Pwksq0u@UvZH84ny@7Y>-P|r{x^e2J}E>9jgxKQlt%X{$|^Gy^@4=MCPQNhc@j%_)>5Nl4^WzEy^7Ne9HJZhMZe>alB7(JwU8hdcbE-rbiTjNZGKX1DH>5whb4qFw=wdy6SchHoCo^ap>1n0MREul6cT%<i?ki?25u+XBX-ct5K#i?<~4G^Z?Sg@+;0tJb_ED>-(Pb;8BkBDBx)8%D?;$0O$Mq)t1K#pj@M`$hL(n&Gt_$$xuT=0r?wG5_68j>IqqLb+gU_fzq2g+Hq4(%;sm81pRcPll6R}8kIaE=M~0q_R16jaLcK0&0gruQsvcyrF;D<&SR2m}hC*S`+mnH9Vt*C{gcrh9b<aQRBHEK&?y-z`f$$<1PRX|aPg26IcZD6?cdAY&tpGgD*ra1V&gq5@sqO~HLVq5}n>>bwU+9?C{otY1W7*sQZ)xmB9x!$U(UHx;C*5l?x3{*1XqQ#0Xjf8yD`)tOkNeR<rk7Eu7{j0sk%?agViV3NMfiDQ_ebtV>EzIx2ToOEVgvldxF(xL_u5wWzdA0!92*U-LRhPIHh3!I!KMZBf7hE{xt5{*GYT4IP@5Y>W+nkd8%q-~XcqWxew)CN(HpXQpgMSf25@>AjCK0Hk1ptu#J$sg^8CMvKy)Y7#Z&h;3_nil$k`yW!zdJbMP{3?ZEw&i7oBoSNFLmQf8d>L1M^88NJOjTyd1yp{v#_(Eb`l77v!&VVBNanHB!NvQp07JQhT9^ZRH96zU6z>|n$r7{u%xtz{6sS3U0zP|@X>0R^1+(#hHH4d|LEv*Ha|!6pirKsE#G~oKQ&Hi^1EGE)MN36PJqL(>r0ar8Neel;NtZH|^8Q)$UOCT_Xcs+25)5)i4Q}5_MOa4}hDoIq3+6eF9!|-K4%~;^2H?1mI*~YOFNNPcvKR@FxwId*d3H-Wi<BEQ6WNZ$0)C|WNUXZwvm;UoyvM~Ohn9-hb>+6SZ7RVLuF#&Fp)}XG6ZK`GiOI6@n6dnGtDXr&@;sn(y58s~J45p^YBbLA_|b+5Y0aoNPkqV88`px%ae4R^^^V@zC0y(-g=%%dtV(xM_LemZsYi^M<0{R8P<EXLc@RQ>OSn<Vnhp-B^2M-9_cYWS1`Go(mvuDod07(c0%a2CP|kE+)7Pek@PhMUV~D#it@13pAGcuyLsEp^7b!!-X7cQ+GW^B8x<E?i<kqOv)aZ`kX;_ii%kb#5uI%Jqi8<gtt6HTq;&{iMEv|mx4vJFLLBS!5qr>v`oC1<fkeI)Vg~kE*?2+BQulMqM^a72ClJh*;UjMs{WeMY=0Ec3X;@ScyGLbOqSVk(<n=v|ZILW@mNcB4VzDOy!fFQ#nj9P<%!N-j~v+;Wj%_JEVS3_tcfDN0TOVvx~q;;072lyx|%W7MnwKt(<%Akk)C?Q)_a{Fkb16Wg>sIt^#FZ^=MT(4*>R(UB!@=8%wtWcVG_5(+}`uOtw?!BvQKr_7#N!_-$-n@;e&e>XR5M9dzGz%Y1DO`5VMY}#r0l>0f@DNNR%WVq9mwh@Wh(_lhmx%<VFPe20Wef%B53bAyjOfR+<Ouc1&a1fANdO5)VzxobgloV|ZOqvvvl_!K{CrJx9?mwXF@wIng(2F~hjirpMLxMi@b8c@vO5wJtt;CUY3o^+Y(O4^pWR6rLn@9`p$AeE>9b(zXg6H1xtBE%gmsHBQm^JXgmb8LL>0RXdKr9tq9d%;9VCx5`8>ZC?N?S*_W(x<G<K#S@?E#E4e|B103f82N(X<DLiEYKXumjT7dTUEP;>^b>h)3e#A|~Gj^fsP@=w@SDk-zrYJjSlY}qq7`w6|Xh)a25rl(6bC?ok{Ngb9%QHH3^mOvhz?-a<rm@#{w%&jnhJnA*9DT4ywQc%=_Q7Ql+{qHtNTX3KEaGi%kmg4#z&Gm@A&RQ$^Hg#5DoxJ}SkCEej7eRJ`l((uP!a!uEnv!w}qalaaWqv|15n;!I1JhkfPezWkxX<ip?m={jezDB`bc}S3CBrI>0Lv&7^r&YzYos-dnMEZ6YZSuTDIj|Vwx)xm$nc<cl4Jv5>1Sf;r(x+2fTf>_rJsf+eUhesXQ9;d><s<zPzrOT!|=BNLwxL}KPsqi*PAAvbm+J^0LEhysceA$69J^p3iaKTBsUrtsANZ>LgQs4QH#ghhn2K}Bc@Z8cZ|?|eB;CQukWni`#>2xw0~3yuKnG-eslBT1NuUB82^cHa*XKX*4_2D{~UhCI*f<yp19Y2`x0H~D?#kE9syAJ-D%wx-?ILmc72X_RxZ<r^k`jjFb)f&P33P)v#-Mick+%;zOwTO{HKQT;$!yN=ip;@JG*D@bx)q?wBO!5alL!`Lign7-CG~C=)y=VtutaYcoZ)CR3L@T(%rxBQjF|3)Qh`-RIYpW!?hpZd;Hc}P!-t?k=@I8DBkoGzmS**g~Hp$oy+T=-08G#VE5b08()9A{^5J+F}UsX?AzS20Mszl)bo2qo#L2A_zH(C7Li&4Th*%1+W0-BU@2k=Y{9YU`pu$iHJqYTr!X=R+BOG<b6Q|!EFiN;UnnUSgCMJhlTr(Tg&*(4GCbS{`bZ^ZU7Odn>!AKLwV^y!U@IgJVzEi#v(i<l>D|b@oK|9o&^)T-5e%%iMObTS4?-$t#M_PU(3LBFW@g5Xtf{xLiUWg7d>bFHUZrpFu{&7#gQ}-rj8!&V3y`J2{ur{Tzd|1w)cIy*$8$S88^5HWmKwi)W&|H7l|F|E;;+7AINnOeS!A?(+2?sG;f=9PZ$V87FUdf-<Sl3{b{W7G;D26WoLW#D6z;ELLdhwEgf76tR?iG3ZrY&WW#X#Roa3-N^zq<vFkzzi?PAX;hmjBO)CMwz!P$x3Yd+6nm-+U*j90p8H~GP4Y%z>E6cgK!0?OI8HapV6<E*W+ruP6P5`u1Uv5*deb%Uan$=+=yvCOzGHoO+vwZc0=*sF068vm{3Yy9=4-|qWEaeQKIa&q5f@$kWeNAgPMwZLi7dD*NG!I6F19MR(4WkG7p*@wcFe@9M?Q$gj*2b+xBGI!ww*P8Q9{19jCYVAZ|ekPnHj)2eqW_}rO8)93GeC@7W;Q}o7X$#gnm~v>bz2MSCpEN@y0f%KG)?;#q&quw)kHPj6AJJkT{F(A86x?U8Q`36<(_nrq1c#j}2)`epsXi>s-DUjrZujIxb}Wc}jCbw+7i)LlW?!pKUa?FE3&Mq^L3@3{T4_YSMTp1d(0KLHwVd%;wkW09(z5_6W7%xRZ;rAk;Hi&bk>m=^e4LiDGDmJRX{u)*_Yh3R|Mou*9$`cIMNje2iL)3{4Z;}k^hpxBko>G{eO8`}d{F4Sb&Olt%g>*P(GTCnCuVLCLP-Z{(z!|g=$=43Xf}9?P@%UBV$=<~9+0@t0Q0U3j@u%8^cX%`9+Esi+RMor9wmsM9FpdE^q%veO83%t_<58*Uwk1geEpN_{6LsEZ-htgq~l1dopzfaH_B)&uu~NFDe~~k<4o7zc>jKP<s3J5dWf6k)k!^iuChaGaS_)#vvKVn>q-c?W_uosr4;*$JuYMQ)8pEMg9{v357a8E5UsZWH#%8&Cj3$i9&~Jj!A17krB3_3QRNK|^O&+Tc6EK^r=oUGUIXhcI9~~%p)v{J5K;Y@8uenbKz(w#4;Htd?9ZzTG^PCNjS#@GUn%{1)w3t5Sfi;e&FE2nVpSntc^5}@`OL<tAAqzp+NaqwKTNuOmOhEo?;}TRKYqdwWsdOg(nrs8p6Pd<lYJ>ZTwka||FwKo`jW<%$uB3Zzjqc|25wD!nQ7(z=G7J}y^|lz#WS4PNNnlAM))~b@x^&|Di^@A*4FNx#gl{h4I=t<5;_eoQrB1LOALWQeHoiryMJZ#(^Wdvd7X^vH`hP-LGt!XLm^brq}b)kV?r9!=iCf1PhbsMDyaCCHoq{XE)1jozc8XsXNuD-jV)Zs@YE8mV|p&lL2|m&20?I(xk94e8rioZo2t^8<l894U=VMy&rB)*I(hKr9E!!PH47$fausIkmh73~hmINVq35E9Ln1GIrk$7LA5qF2hkObWc}YRd6^me%6frPjD#tzuBU-}|3ESfzwpWu)V7X)?WcCKlK<#O03Qzrm5kbwVL&mT%q~`uVqr6DN"
def _package_entries(pkg_name):
 import base64 as _b64, zlib as _zlib
 srcs = _zlib.decompress(_b64.b85decode(_PACKAGE_BLOB)).decode("utf-8").split("\0")
 entries, at = {}, 0
 for pkg, names in _PACKAGE_NAMES.items():
  entries[pkg] = list(zip(names, srcs[at:at + len(names)]))
  at += len(names)
 return entries[pkg_name]
def _install_package(pkg_name):
 import types as _types
 if pkg_name in sys.modules:
  return sys.modules[pkg_name]
 sys.modules.setdefault("data_loader", sys.modules[__name__])
 base = os.path.join(os.path.dirname(os.path.abspath(__file__)), pkg_name)
 pkg = _types.ModuleType(pkg_name)
 pkg.__file__ = os.path.join(base, "__init__.py")
 pkg.__path__ = [base]
 pkg.__package__ = pkg_name
 made = {pkg_name: pkg}
 sys.modules[pkg_name] = pkg
 entries = _package_entries(pkg_name)
 for name, _src in entries:
  if name in made:
   continue
  mod = _types.ModuleType(name)
  mod.__file__ = os.path.join(base, name.split(".")[-1] + ".py")
  mod.__package__ = pkg_name
  made[name] = mod
  sys.modules[name] = mod
  setattr(pkg, name.split(".")[-1], mod)
 try:
  for name, src in entries:
   mod = made[name]
   exec(compile(src, mod.__file__, "exec"), mod.__dict__)
 except Exception:
  for name, _src in entries:
   sys.modules.pop(name, None)
  sys.modules.pop(pkg_name, None)
  raise
 return pkg
