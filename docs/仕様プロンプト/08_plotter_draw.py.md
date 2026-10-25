# [8/30] plotter_draw.py の仕様

## 指示

- この仕様だけを読んで `plotter_draw.py` を**完全な形で**実装し、ファイル全体を出力してください。
- `pass` のみの関数・`TODO`・「省略」・「（以下同様）」・要約・ダミー実装は**一切禁止**です。すべての関数・分岐・エッジケース処理を実体として書き切ってください。
- 出力が途中で切れた場合は、ユーザーが「続き」と言ったら、**直前の続きから最後まで**出力してください（先頭から書き直さない）。

### アプリ全体の前提（このファイルに関係する分のみ）

- Python 3.10+ / GUI は PySide6 (Qt6) 上で matplotlib を描画。ただし**このファイル自体は Qt を一切 import しない**純粋な描画ロジックモジュール（`spawn` での `batch_render` から安全に使えるよう、Qt 非依存に保つ）。
- 日本語ラベルが含まれ得るため、`family="monospace"` は**絶対に使わない**（□豆腐化け防止）。フォント設定は呼び出し側（GUI / batch 側）の `jp_font` が `axes.unicode_minus=False` 込みで済ませている前提。
- `ax.grid(...)` の `linewidth` に `None` を渡さない（`float(None)` でクラッシュするため、本ファイルでは常に明示数値 `0.6` を渡す）。
- scipy は遅延 import ＋ numpy フォールバック。無くても動く（指数近似は初期値のまま使う）。

---

## 役割 / 責務

低レベル描画モジュール。各グラフ種別の描画関数（`_draw_xy` / `_draw_hist` / `_draw_box` / `_draw_bar` / `_draw_pie`）、近似曲線（トレンドライン）の計算、大容量データの min/max 間引き、オシロスコープ風 div グリッドの適用、スタイル解決などを提供する。

モジュール docstring（先頭行）は次の文字列とする:

```
"""低レベル描画（各グラフ種別の _draw_*・近似曲線・間引き・オシロ格子）。"""
```

ファイル冒頭は `# -*- coding: utf-8 -*-` のエンコーディング宣言で始める。

---

## 依存（import するもの）

- `import warnings`
- `import numpy as np`
- `import pandas as pd`
- `from plotter_format import _eng`  — オシロ格子の `s/div`・`V/div` 表示の工学接頭辞表記に使用。`_eng(x)` は数値を `1.5k` `500m` `2µ` のような工学接頭辞付き短縮表記の文字列に変換する関数。

scipy はモジュール冒頭では import せず、`fit_trendline` の指数近似の中で `from scipy.optimize import curve_fit` を**遅延 import**する（失敗時は `except Exception: pass` でフォールバック）。`matplotlib.colors.to_rgb` も `_is_dark` 内で遅延 import する。

---

## モジュール定数

### `DEFAULT_STYLE`（辞書、正確な値）

```python
DEFAULT_STYLE = {
    "color": None,        # None なら matplotlib の既定カラーサイクル
    "linestyle": "-",
    "linewidth": 1.5,
    "marker": "",
    "markersize": 4.0,
    "alpha": 1.0,
}
```

キー順・値・コメントを上記のとおり保つこと。`color` の `None` は「matplotlib の既定カラーサイクルに任せる」意味。

---

## 公開 API（完全シグネチャと挙動）

### `style_for(series)`

- `s = dict(DEFAULT_STYLE)` で既定の複製を作り、`s.update(series.get("style") or {})` で系列固有スタイルを上書きして返す。
- `series["style"]` が `None`/未定義でも `or {}` により安全。戻り値は 6 キーを持つ dict。

### `_coerce_x(values)`

X 軸の値を数値 / 日時 / カテゴリのいずれかへ変換し `(values, kind)` のタプルを返す。

- `s = pd.Series(values)`。
- まず `num = pd.to_numeric(s, errors="coerce")`。`num.notna().mean() >= 0.8`（8 割以上が数値化できる）なら `(num.to_numpy(dtype=float), "numeric")` を返す。
- 次に `warnings.catch_warnings()` + `warnings.simplefilter("ignore")` の中で `dt = pd.to_datetime(s, errors="coerce")` を試みる（例外時は `dt = pd.Series([pd.NaT] * len(s))`）。`dt.notna().mean() >= 0.8` なら `(dt.to_numpy(), "datetime")` を返す。
- どちらも満たさなければ `(s.astype(str).to_numpy(), "category")` を返す。
- `kind` 文字列は厳密に `"numeric"` / `"datetime"` / `"category"` の 3 種。

### `_num(values)`

- `return pd.to_numeric(pd.Series(values), errors="coerce").to_numpy(dtype=float)`。数値化できない要素は `NaN`。float の ndarray を返すワンライナー。

### `fit_trendline(x, y, kind, degree=2, window=5)`

近似曲線を計算する。**戻り値**: `(xfit, yfit, equation, r2)` のタプル、または計算不能時 `None`。`equation` は数式文字列、`r2` は決定係数（移動平均のみ `None`）。

docstring 趣旨:
```
"""近似曲線を計算する。

戻り値: (xfit, yfit, equation, r2) または None
  equation は数式文字列、r2 は決定係数（移動平均は None）。
"""
```

前処理（全 kind 共通）:
1. `x = np.asarray(_num(x), dtype=float)`、`y = np.asarray(_num(y), dtype=float)`。
2. `m = np.isfinite(x) & np.isfinite(y)` で有限値マスク、`x, y = x[m], y[m]`。
3. `len(x) < 2` なら `None`。
4. `order = np.argsort(x)` で X 昇順にソート、`x, y = x[order], y[order]`。`eq = ""` で初期化。
5. 以降の本体を `try: ... except Exception: return None` で囲む。

各 `kind`（**日本語文字列キー。厳密一致**）の分岐:

- `"線形"`: `c = np.polyfit(x, y, 1)`、`yf = np.polyval(c, x)`、数式 `eq = f"y={c[0]:.4g}x{c[1]:+.4g}"`。
- `"多項式"`: `deg = int(max(1, min(degree, 6)))`（1〜6 にクランプ）。`len(x) <= deg` なら `None`。`c = np.polyfit(x, y, deg)`、`yf = np.polyval(c, x)`。数式は各項を組み立てる:
  - `terms = [f"{cc:+.3g}x^{deg - i}" for i, cc in enumerate(c[:-1])]`
  - `eq = "y=" + "".join(terms) + f"{c[-1]:+.3g}"`（最後の係数は定数項）。
- `"指数"`（`y = a*exp(b x)`）: `pos = y > 0`、`pos.sum() < 2` なら `None`。
  - 初期値を log 線形回帰で得る: `c = np.polyfit(x[pos], np.log(y[pos]), 1)`、`a, b = float(np.exp(c[1])), float(c[0])`。
  - 精密化（任意）: `try: from scipy.optimize import curve_fit` → `(a, b), _ = curve_fit(lambda xx, A, B: A * np.exp(B * xx), x, y, p0=(a, b), maxfev=10000)` → `a, b = float(a), float(b)`。`except Exception: pass`（scipy 無し / 収束失敗なら初期値のまま）。
  - `yf = a * np.exp(b * x)`、数式 `eq = f"y={a:.4g}·e^({b:.4g}x)"`（中黒 `·` と上付き `e^` に注意）。
  - コメント: log 線形だけだと小さい y を過大評価して偏るため scipy で非線形最小二乗に精密化する旨。
- `"対数"`（`y = a*ln(x) + b`、x>0）: `pos = x > 0`、`pos.sum() < 2` なら `None`。`x, y = x[pos], y[pos]`。`c = np.polyfit(np.log(x), y, 1)`、`yf = c[0] * np.log(x) + c[1]`、数式 `eq = f"y={c[0]:.4g}·ln(x){c[1]:+.4g}"`。
- `"移動平均"`: `w = int(max(2, min(window, len(y))))`。`kern = np.ones(w) / w`、`yf = np.convolve(y, kern, mode="same")`。**ここで早期 return**: `return x, yf, f"移動平均(窓={w})", None`（r2 は `None`）。
- それ以外（未知の kind）: `return None`。

R² の計算（移動平均以外、try ブロックを抜けた後）:
- `ss_res = float(np.sum((y - yf) ** 2))`
- `ss_tot = float(np.sum((y - np.mean(y)) ** 2))`
- `r2 = (1 - ss_res / ss_tot) if ss_tot > 0 else None`
- `return x, yf, eq, r2`。

### `_data_labels(ax, xx, yy, color, fontsize, cap=40, fmt="{:.3g}")`

各データ点に値ラベルを注釈する（点数が多い場合は間引く）。

- `xx = np.asarray(xx, dtype=float)`、`yy = np.asarray(yy, dtype=float)`、`n = len(yy)`。
- `step = max(1, int(np.ceil(n / cap)))`（最大 `cap` 個程度に間引く）。
- `for i in range(0, n, step):` ループ。`np.isfinite(xx[i]) and np.isfinite(yy[i])` でない点は `continue`。
- 注釈: `ax.annotate(fmt.format(yy[i]), (xx[i], yy[i]), textcoords="offset points", xytext=(0, 5), ha="center", fontsize=max(7, fontsize - 1), color=color or "#333")`。
- 色が未指定（`None`/空）なら `"#333"` を使う。フォントサイズは最低 7。

### `_remove_twin(ax)`

前回作った第 2 軸（twinx）を図から取り除く。

- `ax2 = getattr(ax, "_twin_secondary", None)`。`None` でなければ `try: ax2.remove() except Exception: pass`。
- 最後に必ず `ax._twin_secondary = None` を代入してクリア。
- 第 2 軸の参照は `ax._twin_secondary` という属性名で管理する（命名厳守）。

### `_bar_width(xx)`

数値 X に棒を描くときの適切な幅を返す。

- `xx = np.asarray(xx, dtype=float)`、`xx = xx[np.isfinite(xx)]`。
- `len(xx) < 2` なら `return 0.8`。
- `d = np.diff(np.sort(xx))`、`d = d[d > 0]`（正の間隔のみ）。
- `return float(np.min(d) * 0.8) if len(d) else 0.8`（最小間隔の 0.8 倍。間隔ゼロなら 0.8）。

### `_draw_xy(ax, series, line=True, max_points=0, ax2=None, data_labels=False, trendline=None, fonts=None)`

折れ線 / 散布 / 棒 / 面の複合描画。`series` は系列 dict のリスト。

**系列 dict のキー**（参照されるもの）: `x`（X 値、無ければ `None`/未定義でインデックス扱い）、`y`（必須）、`label`（凡例名）、`style`（任意）、`kind`（`"bar"`/`"area"`/`"scatter"`/`"line"`、未指定なら後述で決定）、`axis`（`"secondary"` なら第 2 軸へ）、`yerr`（誤差バー、任意）。

`fonts` は dict（`fonts.get("tick", 9)` をフォントサイズに使う）。`fonts or {}` で None 安全化。

#### 前処理（カテゴリ位置の全系列共有）

`prepared = []`、`cat_order, cat_pos = [], {}` を用意。各系列 `sr` について:
- `x_raw = sr.get("x")`、`y = _num(sr["y"])`。
- `x_raw is None` なら `prepared.append(("index", None, y, sr))` して `continue`。
- そうでなければ `x, kind = _coerce_x(x_raw)`。`kind == "category"` の場合、各ラベル `lab` を `cat_pos`（未登録なら `cat_pos[lab] = len(cat_order)` し `cat_order.append(lab)`）に登録して**全系列で位置を共有**する（系列ごとに目盛りを上書きして取り違える不具合の防止）。
- `prepared.append((kind, x, y, sr))`。

#### 棒の本数算出

- `bar_series = [sr for *_unused, sr in prepared if (sr.get("kind") or "") == "bar"]`
- `n_bars = max(1, len(bar_series))`、`bar_idx = 0`、`any_decimated = False`。

#### 各系列の描画ループ `for kind, x, y, sr in prepared:`

1. `st = style_for(sr)`。
2. 描画先 `target`: `ax2 if (ax2 is not None and sr.get("axis") == "secondary") else ax`。
3. `skind = sr.get("kind") or ("line" if line else "scatter")`（kind 未指定なら `line` フラグで line/scatter を決定）。
4. `yerr = sr.get("yerr")`、`yerr = _num(yerr) if yerr is not None else None`。
5. X 位置 `xx` を決定:
   - `kind == "index"` → `xx = np.arange(len(y))`
   - `kind == "category"` → `xx = np.array([cat_pos[lab] for lab in x], dtype=float)`
   - それ以外（numeric/datetime）→ `xx = np.asarray(x, dtype=float)`
6. 間引き判定 `decim`: `max_points` が真かつ `kind != "category"` かつ `yerr is None` かつ `skind in ("line", "scatter")` かつ `len(y) > max_points`。
   - `decim` が真のとき: `line` は `xx, yv = decimate_minmax(xx, y, max_points)`、`scatter` は `step = max(1, len(y) // max_points)` で `xx, yv = np.asarray(xx)[::step], np.asarray(y)[::step]`。`any_decimated = True`。
   - 偽なら `yv = y`。
7. 種別別描画:
   - **bar**: `w = _bar_width(xx) / n_bars`、`off = (bar_idx - (n_bars - 1) / 2) * w`、`bar_idx += 1`。`target.bar(np.asarray(xx, float) + off, yv, width=w, label=sr["label"], color=st["color"], alpha=min(st["alpha"], 0.85), yerr=yerr if yerr is not None else None, capsize=3)`（棒のアルファは最大 0.85 でクランプ）。
   - **area**: `target.fill_between(xx, yv, color=st["color"], alpha=min(st["alpha"], 0.4))` の後、`target.plot(xx, yv, label=sr["label"], color=st["color"], linewidth=st["linewidth"], alpha=st["alpha"])`（塗りは最大 0.4、線は通常アルファ）。
   - **scatter**: `target.scatter(xx, yv, label=sr["label"], color=st["color"], s=st["markersize"] ** 2, marker=st["marker"] or "o", alpha=st["alpha"])`（マーカーサイズは `markersize` の 2 乗、マーカー未指定なら `"o"`）。`yerr` があれば `target.errorbar(xx, yv, yerr=yerr[:len(yv)], fmt="none", ecolor=st["color"], alpha=st["alpha"], capsize=3)`。
   - **line（その他すべて）**: `yerr` ありなら `target.errorbar(xx, yv, yerr=yerr[:len(yv)], label=sr["label"], color=..., linestyle=..., linewidth=..., marker=..., markersize=..., alpha=..., capsize=3)`。なしなら `target.plot(xx, yv, label=sr["label"], color=st["color"], linestyle=st["linestyle"], linewidth=st["linewidth"], marker=st["marker"], markersize=st["markersize"], alpha=st["alpha"])`。`yerr` はスライス `yerr[:len(yv)]` で長さを揃える。
8. `data_labels` が真なら `_data_labels(target, xx, yv, st["color"], fs)`（`fs = fonts.get("tick", 9)`）。
9. **近似曲線**: 条件 `trendline and trendline.get("type") not in (None, "なし") and kind in ("numeric", "index") and skind != "bar"`（数値 X / インデックス、棒以外のみ）。
   - `fit = fit_trendline(xx, yv, trendline["type"], degree=trendline.get("degree", 2), window=trendline.get("window", 5))`。
   - `fit is not None` なら `xf, yf, eq, r2 = fit`。ラベル `lab = f"{sr['label']} 近似: {eq}"`。
     - `r2 is not None and trendline.get("show_eq")` なら `lab += f"  (R²={r2:.4f})"`。
     - `elif not trendline.get("show_eq")` なら `lab = None`（凡例に出さない）。
   - `tcolor = trendline.get("color") or st["color"] or "#444"`。
   - `target.plot(xf, yf, color=tcolor, linestyle="--", linewidth=1.3, alpha=0.9, label=lab)`。

#### ループ後処理

- `if any_decimated: ax._decimated = True`（間引きが起きたことを `ax._decimated` 属性で示す。軸ラベル付与は GUI 側）。
- `if cat_order:` カテゴリがあれば共有目盛りを設定:
  - `ax.set_xticks(range(len(cat_order)))`
  - `ax.set_xticklabels(cat_order, rotation=45 if len(cat_order) > 6 else 0, ha="right" if len(cat_order) > 6 else "center")`（7 個以上で 45 度回転＋右寄せ）。

`trendline` の dict キー: `type`（日本語近似名）、`degree`（既定 2）、`window`（既定 5）、`show_eq`（数式を凡例に出すか）、`color`（線色、任意）。`type` が `None` または `"なし"`（日本語）なら描かない。

### `_draw_hist(ax, series, bins)`

ヒストグラム描画。

- `data, labels, colors = [], [], []`。各 `sr` について `y = _num(sr["y"])`、`y = y[~np.isnan(y)]`（NaN 除去）。`len(y)` が真なら `data`/`labels`/`colors` に `y`・`sr["label"]`・`style_for(sr)["color"]` を追加。
- `data` が空なら `raise ValueError("ヒストグラムに使える数値データがありません。")`。
- `colors = colors if all(c for c in colors) else None`（全色が指定されていれば使い、1 つでも `None` なら matplotlib 任せ）。
- `ax.hist(data, bins=int(bins), alpha=0.6, label=labels, color=colors)`。

### `_draw_box(ax, series)`

箱ひげ図描画。

- `data, labels = [], []`。各 `sr` について `y = _num(sr["y"])`、`y = y[~np.isnan(y)]`、`len(y)` が真なら追加。
- 空なら `raise ValueError("箱ひげ図に使える数値データがありません。")`。
- `try: ax.boxplot(data, tick_labels=labels) except TypeError: ax.boxplot(data, labels=labels)`（matplotlib バージョン互換: 新しい `tick_labels` を優先し、古い版では `labels` にフォールバック）。

### `_draw_bar(ax, series, categories, horizontal=False, stacked=False, data_labels=False, fonts=None)`

カテゴリ棒グラフ（グループ / 積み上げ / 横棒対応）。

- `fs = (fonts or {}).get("tick", 9)`。
- `labels = np.asarray([str(c) for c in categories])`、`pos = np.arange(len(labels))`。
- `data = [(sr["label"], _num(sr["y"]), style_for(sr)) for sr in series]`。

内部関数 `_label_bars(bars, vals)`（`data_labels` が偽なら即 `return`）:
- 各 `(b, v)` について `np.isfinite(v)` でなければ `continue`。
- 横棒（`horizontal`）: `ax.annotate(f"{v:.3g}", (b.get_width(), b.get_y() + b.get_height() / 2), textcoords="offset points", xytext=(3, 0), va="center", ha="left", fontsize=max(7, fs - 1))`。
- 縦棒: `ax.annotate(f"{v:.3g}", (b.get_x() + b.get_width() / 2, b.get_height()), textcoords="offset points", xytext=(0, 3), va="bottom", ha="center", fontsize=max(7, fs - 1))`。

分岐:
- **`stacked or len(data) == 1`**（積み上げ、または系列 1 本）: `bottom = np.zeros(len(labels))`。各 `(name, vals, st)`:
  - `vals = np.nan_to_num(vals[:len(labels)])`（ラベル数に切り詰め、NaN→0）。
  - 横棒 `bars = ax.barh(pos, vals, left=bottom, label=name, color=st["color"], alpha=st["alpha"])` / 縦棒 `bars = ax.bar(pos, vals, bottom=bottom, label=name, color=st["color"], alpha=st["alpha"])`。
  - `if not stacked: _label_bars(bars, vals)`（積み上げ時は値ラベルを出さない）。
  - `bottom = bottom + vals`。
- **else**（グループ化、複数系列）: `n = len(data)`、`width = 0.8 / n`。各 `i, (name, vals, st)`:
  - `vals = np.nan_to_num(vals[:len(labels)])`、`off = (i - (n - 1) / 2) * width`。
  - 横棒 `bars = ax.barh(pos + off, vals, height=width, ...)` / 縦棒 `bars = ax.bar(pos + off, vals, width=width, ...)`（`label=name, color=st["color"], alpha=st["alpha"]`）。
  - `_label_bars(bars, vals)`。

目盛り:
- 横棒: `ax.set_yticks(pos)`、`ax.set_yticklabels(labels)`。
- 縦棒: `ax.set_xticks(pos)`、`ax.set_xticklabels(labels, rotation=45 if len(labels) > 6 else 0, ha="right" if len(labels) > 6 else "center")`。

### `_draw_pie(ax, sr, categories, pct=False)`

円グラフ（単一系列 `sr`）。

- `labels = np.asarray([str(c) for c in categories])`、`values = np.nan_to_num(_num(sr["y"]))`。
- `n = min(len(labels), len(values))`、`labels, values = labels[:n], values[:n]`（短い方に合わせる）。
- `mask = values > 0`、`labels, values = labels[mask], values[mask]`（正の値のみ）。
- `len(values) == 0` なら `raise ValueError("円グラフに使える正の数値データがありません。")`。
- `ax.pie(values, labels=labels, autopct="%1.1f%%" if pct else None, startangle=90, counterclock=False)`（90 度開始、時計回り）。
- `ax.axis("equal")`（真円化）。

### `_is_dark(color)`

色（名前 / HEX）が暗いか（相対輝度 < 0.45）を判定。目盛り色などの自動切替に使う。

- `try: from matplotlib.colors import to_rgb` → `r, g, b = to_rgb(color)` → `return (0.299 * r + 0.587 * g + 0.114 * b) < 0.45`（ITU-R BT.601 相当の輝度係数）。
- `except Exception: return True`（解釈不能なら暗いとみなす）。

### `_apply_scope(ax, scope, bg_color="")`

オシロスコープ風の div グリッドと表示範囲を設定する。

docstring 趣旨:
```
"""オシロスコープ風の div グリッドと表示範囲を設定する。

背景色は bg_color（空なら従来の濃色 #0b0f0b）。背景の明暗に応じて
目盛り・グリッド・情報文字の色を自動で見やすく切り替える。
"""
```

`scope` dict から取得（**キー名・既定値厳守**）:
- `xd = int(scope.get("x_divs", 10))`
- `yd = int(scope.get("y_divs", 8))`
- `tpd = float(scope.get("t_per_div", 1.0))`
- `vpd = float(scope.get("v_per_div", 1.0))`
- `xc = float(scope.get("x_pos", 0.0))`
- `yc = float(scope.get("y_pos", 0.0))`

範囲・目盛り:
- `x0, x1 = xc - xd / 2 * tpd, xc + xd / 2 * tpd`
- `y0, y1 = yc - yd / 2 * vpd, yc + yd / 2 * vpd`
- `ax.set_xlim(x0, x1)`、`ax.set_ylim(y0, y1)`。
- `ax.set_xticks(np.linspace(x0, x1, xd + 1))`、`ax.set_yticks(np.linspace(y0, y1, yd + 1))`（div 数 + 1 本の格子線）。

外観（背景の明暗で自動切替）:
- `bg = bg_color or "#0b0f0b"`（空文字なら従来の濃色 `#0b0f0b`）。`dark = _is_dark(bg)`。
- `ax.grid(True, which="major", color=("#888" if dark else "#aaa"), linestyle="-", linewidth=0.6, alpha=0.5)` — **`linewidth` は必ず数値 `0.6`（`None` 禁止）**。
- `ax.set_facecolor(bg)`。
- `ax.tick_params(colors=("#888" if dark else "#555"), labelsize=8)`。
- 情報テキスト色: `info_fg = "#7CFC00" if dark else "#0a7a30"`、`info_bg = "black" if dark else "white"`。
- `ax.text(0.01, 0.99, f"{_eng(tpd)}s/div   {_eng(vpd)}V/div", transform=ax.transAxes, va="top", ha="left", color=info_fg, fontsize=9, bbox=dict(facecolor=info_bg, alpha=0.4, edgecolor="none"))`。
  - 表示文字列は `<tpd 工学表記>s/div   <vpd 工学表記>V/div`（s/div と V/div の間は**半角スペース 3 個**）。位置は軸座標 (0.01, 0.99) 左上。

### `decimate_minmax(x, y, max_points)`

点数が多い波形を min/max エンベロープで間引く（見た目の包絡を保ったまま高速化）。

docstring 趣旨:
```
"""点数が多い波形を min/max エンベロープで間引く（見た目を保ったまま高速化）。

各ビンの最小値・最大値の点を時間順に残すので、波形の包絡が保たれる。
等幅ビンを reshape して per-bin の最小/最大インデックスを numpy でベクトル化
（旧 Python ループ比 約30倍高速）。端数は最後のビンに併合する。
"""
```

アルゴリズム:
1. `x = np.asarray(x)`、`y = np.asarray(y, dtype=float)`、`n = len(y)`。
2. `if n <= max_points or max_points < 4: return x, y`（間引き不要 / 不能）。
3. `n_bins = max(1, max_points // 2)`、`bin_size = n // n_bins`。`if bin_size < 1: return x, y`。
4. `main = bin_size * n_bins`、`Y = y[:main].reshape(n_bins, bin_size)`、`starts = np.arange(n_bins) * bin_size`。
5. **各ビンの最小/最大インデックス**:
   - `if np.isfinite(Y).all():`（NaN/inf 無しの一般ケース、最速）: `lo = starts + np.argmin(Y, axis=1)`、`hi = starts + np.argmax(Y, axis=1)`。
   - `else:`（NaN/inf 混在）: `lo = starts + np.argmin(np.where(np.isfinite(Y), Y, np.inf), axis=1)`、`hi = starts + np.argmax(np.where(np.isfinite(Y), Y, -np.inf), axis=1)`（有限値優先で除外。全 NaN 行は先頭 index=0）。
6. **末尾端数の併合** `if main < n:`: `base = int(starts[-1])`、`seg = y[base:n]`、`fin = np.isfinite(seg)`、`lo[-1] = base + int(np.argmin(np.where(fin, seg, np.inf)))`、`hi[-1] = base + int(np.argmax(np.where(fin, seg, -np.inf)))`（端数を最後のビンに含めて取り直す）。
7. **時間順インターリーブ**: `first = np.minimum(lo, hi)`、`second = np.maximum(lo, hi)`（インデックスの小さい方→大きい方の順で時間順を保つ）。`idx = np.empty(2 * n_bins, dtype=np.int64)`、`idx[0::2] = first`、`idx[1::2] = second`。
8. `return x[idx], y[idx]`（各ビンから 2 点ずつ、計 `2 * n_bins` 点）。

---

## 再現に必須の細部・エッジケース

- `kind`（近似種別）はすべて**日本語文字列**（`"線形"` `"多項式"` `"指数"` `"対数"` `"移動平均"`）で厳密一致。`type` が `None`/`"なし"` のときは近似を描かない。
- 数式の整形子: 線形/指数/対数の係数は `:.4g`、多項式は `:.3g`、符号付きは `:+.4g`/`:+.3g`。指数表記は中黒 `·` と `e^(...)`、対数は `·ln(x)`。R² は `:.4f` で `(R²={r2:.4f})`（`²` は上付き全角の文字 U+00B2）。
- `ax` に付与する動的属性名は厳守: 第 2 軸保持は `ax._twin_secondary`、間引き発生フラグは `ax._decimated`。
- `_draw_xy` で**カテゴリ位置マッピングは全系列共有**（`cat_pos`/`cat_order`）。系列ごとに目盛りを再設定して取り違える不具合を防ぐためで、ループ後にまとめて 1 回だけ目盛り設定する。
- カテゴリ目盛りの回転閾値は「7 個以上（`> 6`）」で 45 度＋右寄せ、それ未満は 0 度＋中央寄せ。これは `_draw_xy`（カテゴリ）と `_draw_bar`（縦棒）で同一ルール。
- 棒の透明度は最大 0.85、面（塗り）の透明度は最大 0.4 にクランプ（`min(st["alpha"], ...)`）。
- `yerr` は描画前に `_num` で数値化し、描画時に `yerr[:len(yv)]` でデータ長に揃える。間引き対象判定では `yerr is None` のときのみ間引く。
- 散布の間引きは単純ステップ（`[::step]`）、線の間引きは `decimate_minmax`（min/max エンベロープ）と使い分ける。
- `_draw_hist` の色は「全系列に色がある」場合のみリストで渡し、1 つでも欠ければ `None`。
- `_draw_box` は `tick_labels`→`labels` の `TypeError` フォールバックで matplotlib 新旧両対応。
- `_draw_bar` の `np.nan_to_num(vals[:len(labels)])` でラベル数への切り詰めと NaN→0 を同時に行う。積み上げ時は値ラベルを抑制。
- `_draw_pie` は値を正のものだけに絞り、ラベルと値を短い方の長さに揃える。`startangle=90, counterclock=False`（12 時方向から時計回り）。
- 例外メッセージ（日本語、厳密一致）:
  - `"ヒストグラムに使える数値データがありません。"`
  - `"箱ひげ図に使える数値データがありません。"`
  - `"円グラフに使える正の数値データがありません。"`

## 関係する落とし穴

- **Qt を import しない**: このモジュールは `batch_render`（spawn 子プロセス）からも使われるため、PySide6 / Qt 関連を一切持ち込まない。matplotlib の `axes`/`figure` オブジェクトを引数で受け取って描くだけ。
- **`grid` の `linewidth=None` 禁止**: `_apply_scope` の `ax.grid(...)` では必ず数値 `0.6` を渡す（`None` を渡すと内部の `float(None)` でクラッシュ）。
- **`family="monospace"` 不使用**: 日本語ラベル（カテゴリ名・凡例・情報テキスト）が□豆腐化けするため、本ファイルでは一切 monospace を指定しない。フォント設定は呼び出し側に委ねる。
- **scipy 遅延 import ＋フォールバック**: 指数近似の `curve_fit` は `try/except Exception: pass`。scipy 不在でも log 線形回帰の初期値で動く。
- **facade 経由の公開**: 本ファイルの関数群はアンダースコア名（`_draw_*` 等）を含め `plotter.py`（facade）が `import *` ＋アンダースコア名の明示 import で再公開する想定。関数名・シグネチャ・公開名を変えないこと。`_eng` は `plotter_format` 経由で取得し、独自実装しない。
- **動的属性名の整合**: `ax._twin_secondary` / `ax._decimated` は GUI 側のコードが参照するため、名前を変更しない。
