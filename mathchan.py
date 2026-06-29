"""数学チャンネル（波形演算）。

2系列の四則演算（A±B / A×B / A÷B）と、単一系列の積分・微分・絶対値・
二乗・移動平均・ローパスフィルタを計算して新しい波形を作る。
X（時間軸）が異なる場合は B を A の時間軸へ補間して揃える。
"""

import ast as _ast
import importlib.util as _ilu

import numpy as np

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
