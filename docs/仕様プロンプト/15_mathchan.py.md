# [15/30] mathchan.py の仕様

## 指示

- この仕様だけを読んで `mathchan.py` を**完全な形**で実装し、出力してください。`pass` だけの関数、`TODO`、省略、要約、「ここに実装」などのプレースホルダは**一切禁止**です。すべての関数・分岐・フォールバックを動作する形で実装してください。
- 出力が途中で切れた場合は、こちらが「続き」と送るので、続きを最後まで出してください。
- このファイルは GUI を持たない**純計算モジュール**です。Qt は import しません（`batch_render` から spawn される子プロセスでも安全に使えるよう、Qt 非依存を保つこと）。
- アプリ全体の前提（関連分のみ）: Python 3.10+。scipy は**遅延 import ＋ numpy フォールバック**（scipy が無くても起動・計算できること）。数式評価は `ast` の安全評価で行い、Python の `eval` は使わない。

---

## ファイルの役割 / 責務

モジュール docstring（先頭の三重引用符文字列）は以下の趣旨をそのまま記述すること:

```
数学チャンネル（波形演算）。

2系列の四則演算（A±B / A×B / A÷B）と、単一系列の積分・微分・絶対値・
二乗・移動平均・ローパスフィルタを計算して新しい波形を作る。
X（時間軸）が異なる場合は B を A の時間軸へ補間して揃える。
```

責務:

- **2系列演算（binary）**: 系列 A と系列 B の四則演算。X 軸（時間軸）が異なる場合、B を A の時間軸へ補間して揃えてから演算する。
- **単一系列演算（unary）**: 積分・微分・絶対値・二乗・移動平均・各種フィルタ・包絡線・自己相関。
- **任意数式評価（eval_expr）**: A, B, VAR1, VAR2, t 等の変数と許可関数のみを使える安全な数式評価（AST のホワイトリスト評価で任意コード実行を防ぐ）。

---

## 依存（import するもの）

ファイル冒頭で以下を import する（**この順序・別名で**）:

```python
import ast as _ast
import importlib.util as _ilu

import numpy as np
```

- scipy は**モジュール先頭では import しない**。各関数内で遅延 import する。
- モジュール読み込み時に scipy の有無だけを調べる定数を定義する（下記 `_HAVE_SCIPY`）。

---

## モジュール定数・データ（正確な値）

import 群の直後に以下を定義する。

```python
_HAVE_SCIPY = _ilu.find_spec("scipy") is not None  # lfilter があれば IIR をベクトル化
```

```python
BINARY_OPS = ["A+B", "A-B", "A×B", "A÷B"]
```
（×は全角 U+00D7、÷は全角 U+00F7）

任意数式で使える関数・定数のホワイトリスト（コメント: `# 任意数式で使える関数・定数（ホワイトリスト。eval は使わず AST を自前評価する）`）:

```python
_EXPR_FUNCS = {
    "sin": np.sin, "cos": np.cos, "tan": np.tan, "asin": np.arcsin, "acos": np.arccos,
    "atan": np.arctan, "atan2": np.arctan2, "sinh": np.sinh, "cosh": np.cosh,
    "tanh": np.tanh, "exp": np.exp, "log": np.log, "log10": np.log10, "log2": np.log2,
    "sqrt": np.sqrt, "abs": np.abs, "sign": np.sign, "clip": np.clip,
    "min": np.minimum, "max": np.maximum, "where": np.where,
}
_EXPR_CONSTS = {"pi": np.pi, "e": np.e}
```

重要な対応関係（誤りやすい点）:
- `asin→np.arcsin`, `acos→np.arccos`, `atan→np.arctan`, `atan2→np.arctan2`
- `min→np.minimum`, `max→np.maximum`（要素ごとの最小/最大。Python 組み込みの min/max ではない）
- `abs→np.abs`（NumPy 版）

UNARY_OPS（`eval_expr` 関数の**後ろ**に定義される。値は正確に）:

```python
UNARY_OPS = ["積分 ∫A dt", "微分 dA/dt", "絶対値 |A|", "二乗 A²",
             "移動平均", "ローパス(RC)", "ローパス(Butterworth)",
             "ハイパス(Butterworth)", "包絡線(Hilbert)", "自己相関"]
```
特殊文字: `∫`(U+222B), `²`(U+00B2 上付き2), 括弧は半角 `()`。

> 注意: ソース上の定義順は `BINARY_OPS` → `_EXPR_FUNCS` / `_EXPR_CONSTS` → `eval_expr` → `UNARY_OPS` → 残りのヘルパ/関数、となっている。`UNARY_OPS` が `eval_expr` のあとに来る点を再現すること（機能上は順序に依存しないが、仕様としてこの並びを保つ）。

---

## 公開 API（完全なシグネチャと挙動）

### `eval_expr(expr, variables)`

安全な数式評価。docstring 趣旨:
```
安全な数式評価（A,B,VAR1,VAR2,t 等の変数と許可関数のみ）。

Python の eval は使わず AST をホワイトリストで評価するので任意コード実行は不可。
許可：四則・** ・% ・単項± ・括弧 ・許可関数 ・定数(pi,e) ・数値リテラル。
variables: dict（name -> ndarray/scalar）。
```

挙動:

1. `node = _ast.parse(expr, mode="eval").body` を行う。`SyntaxError` を捕捉したら `raise ValueError(f"式の構文エラー: {e}")` に変換する。
2. 内部の再帰関数 `ev(n)` で AST ノードを評価する。各ノード種別ごとの処理:
   - `_ast.BinOp`: 左右を `ev` で評価し、`n.op` の型で分岐:
     - `_ast.Add` → `l + r`
     - `_ast.Sub` → `l - r`
     - `_ast.Mult` → `l * r`
     - `_ast.Div` → `l / r`
     - `_ast.Pow` → `l ** r`
     - `_ast.Mod` → `l % r`
     - それ以外 → `raise ValueError("使用できない演算子です")`
   - `_ast.UnaryOp`: `v = ev(n.operand)` のあと `n.op` で分岐:
     - `_ast.UAdd` → `+v`
     - `_ast.USub` → `-v`
     - それ以外 → `raise ValueError("使用できない単項演算子です")`
   - `_ast.Call`: `name = getattr(n.func, "id", None)`。`name` が `_EXPR_FUNCS` に無ければ `raise ValueError(f"使用できない関数です: {name}")`。あれば `_EXPR_FUNCS[name](*[ev(a) for a in n.args])` を返す（位置引数のみ。キーワード引数は評価しない）。
   - `_ast.Name`: `n.id` が `variables` にあればその値、なければ `_EXPR_CONSTS` にあればその値、どちらにも無ければ `raise ValueError(f"未知の変数です: {n.id}（A, B, VAR1, VAR2, t が使えます）")`。
   - `_ast.Constant` かつ `n.value` が `(int, float)` → `n.value` を返す。
   - `_ast.Num` → `n.n` を返す（Python 3.7 互換のためのフォールバック。コメント `# Python 3.7 互換`）。
   - 上記いずれにも該当しない → `raise ValueError("この式は評価できません")`
3. 最後に `return ev(node)`。

戻り値: 式の評価結果（`variables` が ndarray を含めば ndarray、スカラーのみならスカラー）。

エッジケース/再現の要点:
- 属性アクセス `obj.attr` を呼び出した場合 `n.func` に `id` が無く `name=None` → `使用できない関数です: None` で弾く（任意コード実行防止）。
- 添字・比較・論理演算・代入などは「この式は評価できません」で弾かれる。

---

### `_sorted_xy(x, y)`

X 昇順に並べ替えて返すヘルパ。

```python
def _sorted_xy(x, y):
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    order = np.argsort(x)
    return x[order], y[order]
```
戻り値: `(x_sorted, y_sorted)`（ともに float ndarray）。

---

### `_resample(xa, xb, yb)`

B 系列を A の時間軸 `xa` へ補間する。docstring:
```
B系列を A の時間軸 xa へ補間。3次スプライン優先、無ければ線形(np.interp)。
```

アルゴリズム:
1. `xa = np.asarray(xa, dtype=float)`。
2. `xbs, ybs = _sorted_xy(xb, yb)`（B を X 昇順にソート）。
3. 重複 X を除去（CubicSpline の要件: X は狭義単調増加）:
   ```python
   uniq = np.concatenate(([True], np.diff(xbs) > 0))  # 重複xを除去（CubicSpline要件）
   xbs, ybs = xbs[uniq], ybs[uniq]
   ```
4. `xbs.size >= 4` なら 3次スプライン優先:
   ```python
   try:
       from scipy.interpolate import CubicSpline
       cs = CubicSpline(xbs, ybs, extrapolate=False)
       xc = np.clip(xa, xbs[0], xbs[-1])
       return cs(xc)
   except Exception:
       pass
   ```
   （`extrapolate=False` で外挿を禁止し、評価点 `xa` を `np.clip(xa, xbs[0], xbs[-1])` で B の範囲端へクランプしてから評価する。3次スプラインの外挿は範囲外で発散して `A±B` 等が誤った値になるため外挿させず、範囲外は端点値＝`np.interp` と同じ挙動にする。scipy 不在/失敗時は下へフォールバック）
5. フォールバック: `return np.interp(xa, xbs, ybs)`（線形補間。範囲外は端値でクリップ）。

要点: 点数が 4 未満なら無条件で線形補間。scipy が無いか CubicSpline が例外を出せば線形補間。

---

### `_rc_lowpass(y, alpha)`

1次 IIR ローパスフィルタ。docstring:
```
1次IIRローパス  r[i] = (1-α)·r[i-1] + α·y[i],  r[0] = y[0]。

再帰なので単純なnumpy要素演算では書けない。scipy があれば lfilter で
まとめて計算し（大波形で桁違いに速い）、無ければ従来の逐次ループにフォールバック。
どちらも数値的に同一の結果になる。
```

アルゴリズム:
1. `y.size == 0` なら `return y.copy()`（空配列はそのままコピーを返す）。
2. `_HAVE_SCIPY` が真なら scipy 経路:
   ```python
   try:
       from scipy.signal import lfilter   # 遅延import（起動を軽くする）
       zi = [(1.0 - alpha) * float(y[0])]  # y[-1]=y[0] 相当の初期状態
       r, _ = lfilter([alpha], [1.0, -(1.0 - alpha)], y, zi=zi)
       return np.asarray(r, dtype=float)
   except Exception:                       # noqa: BLE001  scipy不調→逐次へ
       pass
   ```
   伝達関数は分子 `[alpha]`、分母 `[1.0, -(1.0 - alpha)]`。初期状態 `zi` は `r[0] = y[0]` になるよう `(1-α)·y[0]` を与える。
3. フォールバック（逐次ループ。scipy 無しでも数値的に同一）:
   ```python
   r = np.empty_like(y)
   acc = y[0]
   for i in range(y.size):
       acc += alpha * (y[i] - acc)
       r[i] = acc
   return r
   ```
   注: `acc` の初期値が `y[0]` のため、`i=0` で `acc = y[0] + α·(y[0]-y[0]) = y[0]`、すなわち `r[0] = y[0]`。

戻り値: フィルタ済み ndarray（`y` と同じ長さ）。

---

### `binary(xa, ya, xb, yb, op)`

2系列の四則演算。docstring: `2系列の四則演算。B は A の時間軸に線形補間して揃える。`

アルゴリズム:
1. `xa = np.asarray(xa, dtype=float)`, `ya = np.asarray(ya, dtype=float)`。
2. `yb_i = _resample(xa, xb, yb)` で B を A の各点へ補間（3次優先・無ければ線形。コメント: `# A の各点での B の値（3次補間優先・無ければ線形）`）。
3. `with np.errstate(divide="ignore", invalid="ignore"):` の中で `op` により分岐:
   - `"A+B"` → `r = ya + yb_i`
   - `"A-B"` → `r = ya - yb_i`
   - `"A×B"` → `r = ya * yb_i`（×は全角）
   - `"A÷B"` → `r = np.where(yb_i != 0, ya / yb_i, np.nan)`（0除算は NaN。÷は全角）
   - それ以外 → `raise ValueError(f"未知の演算: {op}")`
4. `return xa, r`

戻り値: `(xa, r)` のタプル。`xa` は A の時間軸そのまま、`r` は演算結果 ndarray。

要点: 割り算では `yb_i == 0` の位置を NaN にする。`np.errstate` で 0除算/無効値の警告を抑制する。

---

### `unary(x, y, op, param=None)`

単一系列の演算。docstring: `単一系列の演算。param は移動平均の窓長やローパスのカットオフ[Hz]。`

冒頭で `x = np.asarray(x, dtype=float)`, `y = np.asarray(y, dtype=float)`。以下 `op` ごとに分岐し、いずれも `(x_out, y_out)` タプルを返す（自己相関のみ x の長さが変わる点に注意）。

| op 文字列 | 計算内容 |
|---|---|
| `"積分 ∫A dt"` | 累積台形積分。scipy 経路: `from scipy.integrate import cumulative_trapezoid` → `cumulative_trapezoid(y, x, initial=0.0)`。失敗時フォールバック: `dx = np.diff(x, prepend=x[0])` → `r = np.cumsum(y * dx)`。`return x, r`。 |
| `"微分 dA/dt"` | `return x, np.gradient(y, x)`（x 軸を考慮した数値微分）。 |
| `"絶対値 |A|"` | `return x, np.abs(y)`。 |
| `"二乗 A²"` | `return x, y * y`。 |
| `"移動平均"` | `win = int(param or 5)` → `win = max(1, win)` → `kernel = np.ones(win) / win` → `r = np.convolve(y, kernel, mode="same")` → `return x, r`。（窓長の既定は 5、最小 1） |
| `"ローパス(RC)"` | 1次 RC ローパス（下記詳細）。 |
| `"ローパス(Butterworth)"` / `"ハイパス(Butterworth)"` | 4次 Butterworth ＋ filtfilt（下記詳細）。 |
| `"包絡線(Hilbert)"` | 振幅包絡線（下記詳細）。 |
| `"自己相関"` | 自己相関（下記詳細）。 |
| 上記以外 | `raise ValueError(f"未知の演算: {op}")` |

#### `"ローパス(RC)"` の詳細
コメント: `# 1次 RC ローパス（カットオフ param[Hz]）を前進差分で適用`
```python
fc = float(param or 1000.0)
dt = np.median(np.diff(x)) if x.size > 1 else 1.0
if dt <= 0 or fc <= 0:
    return x, y.copy()
alpha = dt / (dt + 1.0 / (2 * np.pi * fc))
return x, _rc_lowpass(y, alpha)
```
- カットオフ既定 1000.0 Hz。サンプル間隔 `dt` はサンプル間隔の中央値（点が1個以下なら 1.0）。
- `dt <= 0` または `fc <= 0` なら入力をそのままコピーして返す（ガード）。
- α は RC ローパスの離散係数 `dt / (dt + 1/(2π fc))`。

#### `"ローパス(Butterworth)"` / `"ハイパス(Butterworth)"` の詳細
コメント: `# 4次 Butterworth ＋ filtfilt（零位相）。出来合い関数を使用。`
```python
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
```
- ガード（いずれかで原波形コピーを返す）: `fs` が偽（dt≤0）／`fc <= 0`／`fc >= fs/2`（ナイキスト以上）／`y.size < 13`（filtfilt の padlen 要件）。
- `btype` は op に `"ロー"` が含まれれば `"low"`、含まれなければ `"high"`。
- scipy 経路: `butter(4, fc, btype=btype, fs=fs)` の係数で `filtfilt`（零位相）。
- scipy 不在/失敗時フォールバック: RC ローパスで近似。`btype=="low"` なら RC ローパス結果、ハイパスなら `y - (RC ローパス結果)`。

#### `"包絡線(Hilbert)"` の詳細
コメント: `# 振幅包絡線 = |解析信号| = |hilbert(y)|。出来合い関数を使用。`
```python
try:
    from scipy.signal import hilbert
    return x, np.abs(hilbert(np.nan_to_num(y)))
except Exception:                       # noqa: BLE001 フォールバック（粗い）
    return x, np.abs(y - np.nanmean(y))
```
- scipy 経路: 解析信号の絶対値（`np.nan_to_num(y)` で NaN を 0 に置換してから hilbert）。
- フォールバック（粗い）: 平均を引いた絶対値 `|y - nanmean(y)|`。

#### `"自己相関"` の詳細
```python
a = np.nan_to_num(y - np.nanmean(y))
try:
    from scipy.signal import correlate
    r = correlate(a, a, mode="full", method="fft")
except Exception:                       # noqa: BLE001
    r = np.correlate(a, a, mode="full")
r = r[r.size // 2:]                      # 非負ラグのみ
if r.size and r[0] != 0:
    r = r / r[0]                         # ラグ0で正規化
x0 = float(x[0]) if x.size else 0.0
return x[:r.size] - x0, r
```
- 平均除去後に自己相関（scipy: FFT 法。無ければ `np.correlate`）。
- `mode="full"` の結果から後半（非負ラグ）のみ取り出す（`r[r.size // 2:]`）。
- ラグ0で正規化（`r[0]` が 0 でない場合のみ）。
- 戻り値の x は**ラグ軸（0始まり）** ＝ `x[:r.size] - x0`（`x0 = x[0]` があれば。`x.size==0` なら 0.0）。元 x の先頭から r.size 個を流用しつつ原点 `x[0]` を引くことで、開始時刻 `x[0]≠0` のデータでもラグ0が必ず 0 になる（`x[:r.size]` をそのまま使うと t0≠0 でラグ0がずれる）。**この op だけ x の長さが入力より短くなる**点に注意。

---

## 再現に必須の細部・落とし穴

- **Qt を一切 import しない**。matplotlib も import しない。numpy と標準ライブラリ（ast, importlib.util）と遅延 scipy のみ。spawn される子プロセスでも安全に使える純計算モジュールであること。
- **scipy は必ず関数内で遅延 import**。モジュール先頭では `_HAVE_SCIPY = _ilu.find_spec("scipy") is not None` で有無を確認するだけ。scipy が無くても全演算が numpy フォールバックで動作すること。
- **全角文字を正確に**: `×`(U+00D7)、`÷`(U+00F7)、`∫`(U+222B)、`²`(U+00B2)。`BINARY_OPS`・`UNARY_OPS` の文字列はこれらを含む。
- **0除算**: `binary` の `A÷B` は `np.where(yb_i != 0, ya/yb_i, np.nan)` で 0 を NaN に。`np.errstate(divide="ignore", invalid="ignore")` で警告抑制。
- **`np.diff` で `np.median` を取るときの x.size ガード**: `dt = np.median(np.diff(x)) if x.size > 1 else 1.0`（点1個以下なら dt=1.0）。
- **filtfilt のサンプル数ガード**: `y.size < 13` のとき Butterworth を適用せず原波形コピーを返す。
- **ナイキスト境界**: `fc >= fs/2` でフィルタを適用せず原波形コピー。
- **CubicSpline は X が狭義単調増加でないと失敗**するので、ソート＋重複除去（`np.diff(xbs) > 0` の先頭に `True` を `concatenate`）を必ず行う。点数 4 未満は線形補間。
- **`_rc_lowpass` は空配列で `y.copy()` を返す**（`y[0]` 参照で IndexError を防ぐガード）。
- **`param or 既定値`** のイディオム: `param=None` や `param=0` のとき既定値（移動平均は 5、RC/Butterworth は 1000.0）が使われる。
- **戻り値は常に `(x, y)` のタプル**（自己相関のみ x が短縮される）。呼び出し側はこの 2 要素タプルを期待する。
- **`eval_expr` のセキュリティ**: 関数呼び出しはホワイトリスト `_EXPR_FUNCS` のみ、変数はホイワイトリストの `variables`／`_EXPR_CONSTS` のみ。属性アクセスや非数値リテラル、未対応ノードはすべて `ValueError` で拒否する（任意コード実行を防ぐ）。
- **このファイルは GUI を持たない**ため、ウィジェット・レイアウト・シグナル接続・Qt6 列挙・Mixin 規約・facade・monospace/grid linewidth の各論点はこのファイルには直接該当しない（呼び出し元の GUI 側で扱われる）。本モジュールはあくまで純粋な計算 API を提供する。

---

## 実装順序（推奨）

1. docstring → import → `_HAVE_SCIPY`
2. `BINARY_OPS` → `_EXPR_FUNCS` / `_EXPR_CONSTS`
3. `eval_expr`
4. `UNARY_OPS`
5. `_sorted_xy` → `_resample` → `_rc_lowpass`
6. `binary` → `unary`

以上をすべて完全に実装し、省略なく出力してください。
