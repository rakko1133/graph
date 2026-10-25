# [16/30] datasci.py の仕様

## 指示

- この仕様だけを読んで `datasci.py` を**完全な形**で実装し、ファイル全体を出力すること。
- `pass`・`TODO`・「以下省略」・要約・ダミー実装は**禁止**。すべての関数を実際に動作する形で実装する。
- 出力が途中で切れた場合は「続き」と指示されたら、続きから最後まで出力すること。
- 本ファイルは **GUI から独立した純粋な計算モジュール**である。Qt も matplotlib も import しない。`import numpy as np` のみ依存。`scipy` は各関数内で**遅延 import**し、無くても numpy フォールバックで動く（モジュール先頭で scipy を import してはいけない）。
- アプリ全体の前提（本ファイルに関係する分のみ）: Python 3.10+。`analysis.py` が facade として本ファイルの公開名を再公開する場合があるため、**公開関数名・引数名・戻り dict のキー名は厳密に保つ**こと。本ファイルには Qt6 列挙・Mixin・grid linewidth などの GUI 固有の落とし穴は出てこないが、「scipy 遅延 import ＋ numpy フォールバック」の規約だけは厳守する。

---

## ファイルの役割・責務

データサイエンス系の計算をGUIから完全に独立して提供するモジュール。線形回帰（線形性）・記述統計・相関・正規性検定など、データ解析でよく使う指標を計算する。

docstring の趣旨（モジュール先頭の docstring にそのまま書く内容）:

```
データサイエンス系の計算（GUI から独立）。

線形回帰（線形性）・記述統計・相関・正規性検定など、データ解析でよく使う指標を計算する。
scipy があればそれを使い、無くても numpy だけで主要な指標を返せるようフォールバックする。
入力は 1 次元配列（x, y）。NaN/inf は自動で除外する。
```

ファイル先頭行はエンコーディング宣言 `# -*- coding: utf-8 -*-`。その直後にモジュール docstring、その後 `import numpy as np`。

## 依存（import するもの）

- モジュールレベル: `import numpy as np` のみ。
- 各計算関数の内部で必要時のみ `from scipy import stats` を **try/except で遅延 import**。`Exception` を捕捉して numpy フォールバックに落とす（scipy 未インストールでもモジュールが import でき、関数が動くこと）。

## 公開API（全関数のシグネチャと挙動）

以下の順序で定義する（内部ヘルパ2つ → 公開5関数）。

---

### `def _clean_xy(x, y):`

内部ヘルパ。x, y を共通有効点に揃える。

- `x = np.asarray(x, dtype=float)` / `y = np.asarray(y, dtype=float)`。
- `n = min(x.size, y.size)` で短い方に切り詰め、`x, y = x[:n], y[:n]`。
- マスク `m = np.isfinite(x) & np.isfinite(y)` を作り、`return x[m], y[m]`。
- 戻り値: `(x_clean, y_clean)` の2要素タプル（どちらも 1次元 float ndarray）。

---

### `def _clean(y):`

内部ヘルパ。単一系列から非有限値を除去。

- `y = np.asarray(y, dtype=float)`。
- `return y[np.isfinite(y)]`。

---

### `def linear_regression(x, y):`

最小二乗の直線当てはめ。線形性（R²・相関 r）と直線性誤差を返す。

docstring（関数に付与する。戻り dict のキー説明を含める）:

```
最小二乗の直線当てはめ。線形性（R²・相関 r）と直線性誤差を返す。

戻り dict のキー:
  n, slope(傾き), intercept(切片), r(ピアソン相関), r2(決定係数),
  p_value(傾き=0 の検定。scipy 時のみ), std_err(傾きの標準誤差。scipy 時のみ),
  rmse(残差二乗平均平方根), linearity_error_pct(最大残差/Yの全幅×100[%FS])
```

アルゴリズム:

1. `x, y = _clean_xy(x, y)`。`n = int(x.size)`。
2. **ガード**: `if n < 2: return {}`（空 dict）。
3. `slope = intercept = rval = pval = stderr = None` で初期化。
4. **scipy 経路（try）**: `from scipy import stats` → `res = stats.linregress(x, y)` →
   `slope, intercept = float(res.slope), float(res.intercept)`；
   `rval, pval, stderr = float(res.rvalue), float(res.pvalue), float(res.stderr)`。
5. **フォールバック（except Exception）**: `slope, intercept = (float(v) for v in np.polyfit(x, y, 1))`（ジェネレータ内包をタプルアンパックに渡す）。この経路では `rval, pval, stderr` は None のまま。
6. `yhat = slope * x + intercept`；`resid = y - yhat`。
7. `ss_res = float(np.sum(resid ** 2))`；`ss_tot = float(np.sum((y - np.mean(y)) ** 2))`。
8. `r2 = (1.0 - ss_res / ss_tot) if ss_tot > 0 else None`。
9. `rval` が None のとき（フォールバック時）、`r2` から復元:
   `rval = (float(np.sign(slope) * np.sqrt(r2)) if (r2 is not None and r2 >= 0) else None)`。
   （符号は傾きの符号、大きさは √r2。r2 が None または負なら None。）
10. `rmse = float(np.sqrt(np.mean(resid ** 2)))`。
11. `yspan = float(np.max(y) - np.min(y))`。
12. `inl_pct = float(np.max(np.abs(resid)) / yspan * 100.0) if yspan > 0 else None`（最大絶対残差を Y 全幅で割り 100 倍、%FS）。
13. 戻り dict（**キー順そのまま**）:

```python
{
    "n": n, "slope": slope, "intercept": intercept,
    "r": rval, "r2": r2, "p_value": pval, "std_err": stderr,
    "rmse": rmse, "linearity_error_pct": inl_pct,
}
```

戻り値の形: dict。データ不足時のみ `{}`。scipy 無し時は `p_value` と `std_err` が None。

---

### `def describe(y):`

記述統計。docstring:

```
記述統計。count/mean/median/std/var/min/max/range/CV/歪度/尖度/四分位 など。
```

アルゴリズム:

1. `y = _clean(y)`。**ガード**: `if y.size == 0: return {}`。
2. `n = int(y.size)`；`mean = float(np.mean(y))`。
3. `std = float(np.std(y, ddof=1)) if n > 1 else 0.0`（**標本標準偏差 ddof=1**。n=1 のとき 0.0）。
4. `p25, p50, p75 = (float(np.percentile(y, q)) for q in (25, 50, 75))`。
5. 基本 dict `d` を構築（**キー順・式そのまま**）:

```python
d = {
    "count": n, "mean": mean, "median": float(np.median(y)),
    "std": std, "var": float(np.var(y, ddof=1)) if n > 1 else 0.0,
    "min": float(np.min(y)), "max": float(np.max(y)),
    "range": float(np.max(y) - np.min(y)),
    "cv": (float(std / mean) if mean != 0 else None),
    "p25": p25, "p50": p50, "p75": p75, "iqr": p75 - p25,
}
```

- `var` は **ddof=1**（n=1 のとき 0.0）。
- `cv`（変動係数）は `std/mean`。`mean == 0` のとき None。
- `iqr = p75 - p25`。

6. **歪度・尖度**（scipy 優先、フォールバックあり）。両経路とも `std > 0` でガードし、定数データ（分散0）は `skew=0.0, kurtosis=0.0` を返す:
   - try: `from scipy import stats` → `std > 0` なら
     `d["skew"] = float(stats.skew(y))`；
     `d["kurtosis"] = float(stats.kurtosis(y))`（**過剰尖度。正規分布=0**。コメント `# 過剰尖度（正規分布=0）` を付ける）。
     `std <= 0` のときは `d["skew"] = 0.0`；`d["kurtosis"] = 0.0`（scipy は定数データで nan を返すため除外。numpy フォールバックと一致させる）。
   - except Exception: `std > 0` なら標準化 `z = (y - mean) / std` を作り、
     `d["skew"] = float(np.mean(z ** 3))`（3次モーメント）；
     `d["kurtosis"] = float(np.mean(z ** 4) - 3.0)`（4次モーメント − 3、過剰尖度）。
     `std <= 0` のときは `d["skew"] = 0.0`；`d["kurtosis"] = 0.0`。
7. `return d`。

戻り値の形: dict。空入力時のみ `{}`。

---

### `def correlation(x, y, method="pearson"):`

2系列の相関係数と p 値。docstring:

```
2系列の相関係数と p 値（scipy 時）。method: 'pearson' | 'spearman'。
```

アルゴリズム:

1. `x, y = _clean_xy(x, y)`。**ガード**: `if x.size < 2: return None`（dict ではなく None）。
2. try: `from scipy import stats` →
   `method == "spearman"` なら `r, p = stats.spearmanr(x, y)`、それ以外（既定 pearson）は `r, p = stats.pearsonr(x, y)` →
   `return {"r": float(r), "p_value": float(p)}`。
3. except Exception: `return {"r": float(np.corrcoef(x, y)[0, 1]), "p_value": None}`（フォールバックは常に Pearson 相当、p は None）。

戻り値の形: `{"r": float, "p_value": float|None}` または None（データ不足時）。

---

### `def correlation_matrix(named_series, method="pearson"):`

複数系列の相関行列。docstring:

```
複数系列の相関行列。named_series: [(名前, y配列), ...]。

各系列を共通長に切り、全系列で有限な点だけを使って相関行列を計算する。
戻り値: (names, matrix[ndarray])。系列が2未満や有効点不足なら (names, None)。
```

引数 `named_series` は `[(名前, y配列), ...]` のリスト。

アルゴリズム:

1. `names = [str(nm) for nm, _ in named_series]`（名前を str 化）。
2. `arrs = [np.asarray(a, dtype=float) for _, a in named_series]`。
3. **ガード**: `if len(arrs) < 2: return names, None`。
4. `L = min(a.size for a in arrs)`（最短長）。**ガード**: `if L < 2: return names, None`。
5. `M = np.vstack([a[:L] for a in arrs])`（行=系列、列=サンプルの 2次元）。
6. `mask = np.all(np.isfinite(M), axis=0)`（全系列で有限な列のみ）；`M = M[:, mask]`。
7. **ガード**: `if M.shape[1] < 2: return names, None`。
8. try:
   - `method == "spearman"`: `from scipy import stats` → `mat, _ = stats.spearmanr(M, axis=1)` →
     `mat = np.atleast_2d(np.asarray(mat, dtype=float))`。
     **2系列のときの特例**: `if mat.shape != (len(arrs), len(arrs)):`（spearmanr は2系列だと scalar を返すため）
     `r = float(mat.ravel()[0])`（scipy が返した Spearman 値）を取り出し `mat = np.array([[1.0, r], [r, 1.0]])` で 2x2 を組み立てる（コメント `# 2系列時は scalar を 2x2 へ`）。`np.corrcoef` は Pearson を返すため使ってはいけない。
   - それ以外（pearson）: `mat = np.corrcoef(M)`。
9. except Exception: `mat = np.corrcoef(M)`。
10. `return names, np.asarray(mat, dtype=float)`。

戻り値の形: タプル `(names: list[str], matrix: np.ndarray | None)`。常に names は返す。行列が作れない場合は `(names, None)`。

---

### `def normality(y):`

Shapiro-Wilk 正規性検定。docstring:

```
Shapiro-Wilk 正規性検定（scipy 必須）。W 統計量・p 値・5%有意で正規かを返す。
scipy が無ければ空 dict。
```

アルゴリズム:

1. `y = _clean(y)`。**ガード**: `if y.size < 3: return {}`（Shapiro は最低3点必要）。
2. try: `from scipy import stats` → `w, p = stats.shapiro(y[:5000])`（**大標本対策で先頭 5000 点に上限**。コメント `# shapiro は大標本で重いため上限を設ける`）→
   `return {"W": float(w), "p_value": float(p), "normal_5pct": bool(p > 0.05)}`。
3. except Exception: `return {}`（scipy が無い／失敗時は空 dict。numpy フォールバックは無い）。

戻り値の形: `{"W": float, "p_value": float, "normal_5pct": bool}` または `{}`。
`normal_5pct` は `p > 0.05`（5%有意水準で正規と判定できれば True）。

## 再現に必須の細部・エッジケース

- **NaN/inf 除去**は全関数で `_clean` / `_clean_xy` 経由（呼び出し側で除去済みを仮定しない）。
- **戻り値の型の違いに注意**: `linear_regression`・`describe`・`normality` はデータ不足時 `{}`（空 dict）を返すが、`correlation` は `None` を返す。`correlation_matrix` は `(names, None)` を返す。
- **ddof**: `describe` の std/var は **ddof=1（標本）**。n=1 のときは 0.0。np.std の既定 ddof=0 とは異なるので注意。
- **歪度・尖度のフォールバック**は過剰尖度（excess kurtosis、正規分布で 0）になるよう `np.mean(z**4) - 3.0` とする。scipy の `stats.kurtosis` も既定で fisher（過剰尖度）なので整合する。
- **歪度・尖度の定数データ対策**: scipy 経路も `if std > 0` でガードする。分散0（定数データ）では scipy が nan を返すため、`std <= 0` のときは scipy・numpy 両経路とも `skew=0.0, kurtosis=0.0` を返して挙動を一致させる。
- **r のフォールバック復元**: scipy 無しの線形回帰では r を `sign(slope) * sqrt(r2)` で求める。r2 が負（数値誤差で起こり得る）または None のときは r=None。
- **spearman の2系列特例**: `stats.spearmanr` は入力が2系列だと相関係数を scalar で返すため、`correlation_matrix` では行列形状を検査し 2x2 を手組みする。このとき使う相関値は scipy が返した Spearman 値（`float(mat.ravel()[0])`）であり、`np.corrcoef`（Pearson）で組み直してはいけない。`correlation`（単一ペア）側は `r, p` のアンパックで受けるので問題なし。
- **shapiro の上限 5000**: 入力が 5000 を超えても先頭 5000 点のみ使用（重さ対策）。これは仕様として固定。
- **scipy 例外は広く捕捉**: import 失敗だけでなく計算時例外も `except Exception` で numpy 経路に逃がす（`correlation_matrix` の spearman try ブロックも except で `np.corrcoef` にフォールバック）。
- 数値の `float()` 明示変換が随所にあるのは、numpy scalar ではなく純粋 Python float を辞書に格納するため（JSON 化や表示の都合）。同じ意図で踏襲する。

## このファイルに関係する落とし穴

- **scipy は遅延 import**: モジュール先頭で `from scipy import stats` を書いてはいけない。scipy 未導入環境でも `import datasci` が成功し、各関数が numpy フォールバックで動くことが必須要件。
- **公開名・キー名の保持**: `analysis.py`（facade）が `from datasci import *` 等で再公開する可能性があるため、関数名・引数名（`x, y, method, named_series` 等）・戻り dict のキー名（`slope`, `intercept`, `r`, `r2`, `linearity_error_pct`, `cv`, `iqr`, `skew`, `kurtosis`, `W`, `normal_5pct` 等）を一字一句変えないこと。
- 本ファイルは GUI 非依存のため、Qt6 列挙・Mixin 規約・matplotlib・monospace 回避・grid linewidth=None 等の GUI 落とし穴は**該当しない**（が、計算結果が GUI 側のテーブル表示・グラフ注記に渡るため、戻り値の構造を崩さない）。
