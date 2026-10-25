# [9/30] plotter.py の仕様

## 指示

- この仕様だけを読んで `plotter.py` を**完全な形**で実装し、ファイル全体を出力してください。
- `pass` で逃げる・`TODO` を残す・処理の省略・要約・「以下同様」などは**禁止**です。すべての関数本体を最後まで具体的に書き切ってください。
- 出力が途中で切れた場合は、続けて「続き」と言われたら**最後まで**残りを出力してください。
- これは facade（窓口）ファイルです。実体は `plotter_format.py` と `plotter_draw.py` にあり、本ファイルはそれらを再公開しつつ高水準の組み立て関数（`plot_series` ほか）を定義します。**公開名（シンボル名）を変えてはいけません**。

### アプリ全体の前提（本ファイルに関係する分）

- Python 3.10+。本ファイルは GUI から独立した純ロジックで、PySide6/Qt には依存しない（単体・テスト利用可能、`batch_render` からの spawn でも安全）。
- `scipy` 等の重い依存はこのファイルでは直接 import しない。トレンドライン計算等は実体側（`plotter_draw.py`）に委譲され、そちらで遅延 import＋numpy フォールバックが行われる。
- グラフの `grid` 描画で `linewidth=None` を**絶対に渡さない**。matplotlib は内部で `float(None)` を呼んでクラッシュするため、指定があるときだけ `linewidth` を渡す（本ファイルで実装する重要ガード）。
- 日本語に `family="monospace"` を使わない（豆腐□化け回避）。本ファイルでは直接フォント family を指定しないが、フォントサイズは引数 `fonts` の辞書から取り出す。

---

## ファイルの役割 / 責務

モジュール docstring（先頭の三重引用符）にそのまま入れる趣旨:

> グラフ描画ロジック（系列ベース）。
>
> 複数ファイル由来の系列をまとめて描画でき、系列ごとに色・線種・線幅・マーカーを指定できる。軸範囲・対数軸・凡例位置などの編集にも対応。さらにオシロスコープ風の div グリッド表示（time/div・V/div・位置オフセット）をサポートする。
>
> GUI から独立しているので単体でも利用・テストできる。

責務:

1. **facade（再公開）**: `plotter_format.py`（数値整形・eng 表記）と `plotter_draw.py`（低レベル描画・トレンドライン・デシメーション）の公開シンボルを `import *` で取り込み、外部からは `plotter` 一つを import すれば済むようにする。
2. **アンダースコア名の明示再 import**: `plot_series` が直接呼ぶ低レベル描画関数（アンダースコア始まりで `*` には含まれない）を明示 import で取り込む。
3. **UI 用の定数テーブル群**（グラフ種別・線種・マーカー・凡例位置・トレンドライン・系列種別・系列軸）を定義し、GUI 側から参照させる。
4. **高水準の組み立て関数** `plot_series` / `build_series_from_df` / `plot` を提供する。

---

## 依存（import するもの）

ファイル先頭で以下を**この順**で記述する:

```python
import warnings  # noqa: F401
import numpy as np
import pandas as pd  # noqa: F401
from plotter_format import *   # noqa: F401,F403
from plotter_draw import *     # noqa: F401,F403
# plot_series が直接呼ぶ低レベル描画（アンダースコア）を取り込む
from plotter_draw import (_draw_xy, _draw_hist, _draw_box, _draw_bar, _draw_pie,
                          _remove_twin, _apply_scope, _data_labels)
```

要点:
- `warnings` と `pandas as pd` はこのファイル内で直接使わなくても import する（`# noqa: F401` 付き。後方互換・将来利用のため）。
- `from plotter_format import *` で `parse_eng` / `eng_125_sequence` 等の数値整形系を再公開する。
- `from plotter_draw import *` で `DEFAULT_STYLE` / `style_for` / `fit_trendline` / `decimate_minmax` 等を再公開する。
- アンダースコア名（`_draw_xy, _draw_hist, _draw_box, _draw_bar, _draw_pie, _remove_twin, _apply_scope, _data_labels`）は `*` には含まれないため、**明示 import** で取り込む。`_data_labels` は本ファイルでは直接呼ばないが、再公開のため列挙に含める（順序もこの通り）。

---

## モジュール定数（正確な値そのまま）

すべてモジュールトップレベルに、以下の順序・値で定義する。

### `CHART_TYPES`（グラフ種別の表示順リスト）

```python
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
```

### `CHART_INFO`（各種別のメタ情報辞書）

キーは日本語のグラフ種別名。各値は `use_x`（X軸列を使うか）/ `multi_y`（Y軸複数可か）/ `multi_file`（複数ファイル重ね描き可か）/ `hint`（GUI のヒント文）を持つ辞書。値を一字一句そのまま:

```python
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
```

### `LINESTYLES`（日本語ラベル → matplotlib 線種コード）

```python
LINESTYLES = {"実線": "-", "破線": "--", "一点鎖線": "-.", "点線": ":", "なし": "None"}
```

### `MARKERS`（日本語ラベル → matplotlib マーカーコード）

```python
MARKERS = {"なし": "", "丸": "o", "四角": "s", "三角": "^", "菱形": "D",
           "× ": "x", "＋": "+", "点": "."}
```

注意: `"× "` のキーは全角バツの後ろに**半角スペース**が付く（一字一句この通り）。`"＋"` は全角プラス。

### `LEGEND_LOCS`（凡例位置の選択肢リスト）

matplotlib の `loc` にそのまま渡す英字文字列。順序もこの通り:

```python
LEGEND_LOCS = ["best", "upper right", "upper left", "lower left",
               "lower right", "right", "center left", "center right",
               "lower center", "upper center", "center"]
```

### `TRENDLINES`（トレンドライン種別の日本語リスト）

```python
TRENDLINES = ["なし", "線形", "多項式", "指数", "対数", "移動平均"]
```

### `SERIES_KINDS`（系列の描画種別: 日本語ラベル → 内部コード）

```python
SERIES_KINDS = {"自動": "", "折れ線": "line", "棒": "bar", "面": "area",
                "散布図": "scatter"}
```

### `SERIES_AXES`（系列を割り当てる軸: 日本語ラベル → 内部コード）

```python
SERIES_AXES = {"主軸": "primary", "第2軸": "secondary"}
```

---

## 公開 API（完全シグネチャと挙動）

### `plot_series(...)`

完全シグネチャ（`*` 以降はすべてキーワード専用引数。デフォルト値もこの通り）:

```python
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
):
```

docstring（趣旨）: 「`ax` に系列群を描画する」。`series` の形式を説明する:
- 折れ線/散布図: `{label, x, y, style}`
- ヒストグラム/箱ひげ: `{label, y, style}`
- 棒/横棒/積み上げ棒: `{label, y, style}`（`categories` に X ラベル配列）
- 円: `{label, y, style}`（`categories` にラベル、`y[0]` を使用）

**戻り値**: 描画後の `ax`（matplotlib Axes）をそのまま返す。

**アルゴリズム（厳密に順序通り実装する）:**

1. **種別検証**: `info = CHART_INFO.get(chart_type)`。`info is None` なら `raise ValueError(f"未知のグラフ種別です: {chart_type}")`。
2. **系列空チェック**: `if not series:` なら `raise ValueError("Y軸（値）の系列を選択してください。")`。
3. `fonts = fonts or {}`（`None` を空 dict に正規化）。
4. **単位換算（スケール掛け）**: `if xscale != 1.0 or yscale != 1.0:` のときのみ実施。
   - 新リスト `scaled = []` を作り、各系列 `sr` を `sr = dict(sr)` で**浅いコピー**してから掛ける（元 dict を破壊しないため）。
   - X スケール: `xscale != 1.0 and sr.get("x") is not None` のとき `sr["x"] = np.asarray(sr["x"], dtype=float) * xscale`。
   - Y スケール: `yscale != 1.0 and sr.get("axis") != "secondary" and sr.get("y") is not None` のとき `sr["y"] = np.asarray(sr["y"], dtype=float) * yscale`。さらに `sr.get("yerr") is not None` なら `sr["yerr"] = np.asarray(sr["yerr"], dtype=float) * yscale`（誤差棒も同倍率でスケール）。
   - **重要分岐**: Y スケールは**主軸の系列のみ**に適用する（`axis == "secondary"` の第2軸系列は Y スケールを掛けない）。X スケールは全系列共通で適用。
   - 末尾で `scaled.append(sr)`、ループ後 `series = scaled` に差し替える。
5. **Axes 初期化**（毎回クリーンな状態にする）:
   - `ax.clear()`
   - `_remove_twin(ax)`（前回作った第2軸の掃除。コメント「前回の第2軸を掃除」）
   - `ax.set_aspect("auto")`（円グラフの `equal` を持ち越さないため）
   - `ax.set_facecolor(bg_color or "white")`（背景色。空文字なら白。オシロ表示は後で上書きされる）
   - `ax.tick_params(colors="black")`（オシロ表示の目盛り色を既定の黒へ戻す）
6. **第2軸の用意 + XY 系列描画**: `ax2 = None` で初期化。
   - `if chart_type in ("折れ線", "散布図"):`
     - `if any((sr.get("axis") == "secondary") for sr in series):` のとき `ax2 = ax.twinx()` を作り、`ax._twin_secondary = ax2`（属性として保持。`_remove_twin` がこれを掃除する）。さらに `if secondary_label:` なら `ax2.set_ylabel(secondary_label, fontsize=(fonts or {}).get("label", 10))`。
     - `_draw_xy(ax, series, line=(chart_type == "折れ線"), max_points=max_points, ax2=ax2, data_labels=data_labels, trendline=trendline, fonts=fonts)` を呼ぶ（`line=True` が折れ線、`False` が散布図）。
   - `elif chart_type == "ヒストグラム":` → `_draw_hist(ax, series, bins)`。
   - `elif chart_type == "箱ひげ":` → `_draw_box(ax, series)`。
   - `elif chart_type in ("棒", "横棒", "積み上げ棒"):`
     - `if categories is None:` なら `raise ValueError("X軸（カテゴリ）の列を選択してください。")`。
     - `_draw_bar(ax, series, categories, horizontal=(chart_type == "横棒"), stacked=(chart_type == "積み上げ棒"), data_labels=data_labels, fonts=fonts)`。
   - `elif chart_type == "円":`
     - `if categories is None:` なら `raise ValueError("X軸（ラベル）の列を選択してください。")`。
     - `_draw_pie(ax, series[0], categories, pct=pct)`（系列の先頭 `series[0]` のみ使用）。
7. **タイトル・軸ラベル**:
   - `if title:` → `ax.set_title(title, fontsize=fonts.get("title", 12))`。
   - `if chart_type != "円":`（円グラフには軸ラベルを付けない）
     - X ラベル: `xl = (f"{xlabel} [{xunit}]".strip() if xunit else xlabel)`。
     - Y ラベルのベース: `yl_base = ylabel or ("頻度" if chart_type == "ヒストグラム" else "")`（ヒストグラムで `ylabel` 未指定なら既定で `"頻度"`）。
     - Y ラベル: `yl = (f"{yl_base} [{yunit}]".strip() if yunit else yl_base)`。
     - `ax.set_xlabel(xl, fontsize=fonts.get("label", 10))`、`ax.set_ylabel(yl, fontsize=fonts.get("label", 10))`、`ax.tick_params(labelsize=fonts.get("tick", 9))`。
     - 単位の表記は `"<ラベル> [<単位>]"`（角括弧で囲む）。`.strip()` でラベルが空のとき先頭スペースを除く。
8. **対数軸・軸範囲**（`if chart_type != "円":` の中で）:
   - `if xlog: ax.set_xscale("log")`、`if ylog: ax.set_yscale("log")`。
   - `if xlim:` のとき、`xlim[0] is not None` なら `ax.set_xlim(left=xlim[0])`、`xlim[1] is not None` なら `ax.set_xlim(right=xlim[1])`。
   - `if ylim:` のとき、`ylim[0] is not None` なら `ax.set_ylim(bottom=ylim[0])`、`ylim[1] is not None` なら `ax.set_ylim(top=ylim[1])`。
   - **重要仕様**: min/max は**片側だけの指定でも反映**する（例: min=0 のみ指定 → 左端を 0 に詰め、matplotlib 自動の 5% 余白を消す）。`set_xlim(left=...)` / `set_xlim(right=...)` のように片端だけキーワード指定するのがポイント（両方そろわないと無視する旧仕様だと「0 を指定しても余白が残る」不具合になる）。
9. **オシロスコープ表示**（折れ線/散布図のみ）:
   - `if scope and scope.get("enabled") and chart_type in ("折れ線", "散布図"):`
     - `_apply_scope(ax, scope, bg_color=bg_color)` を呼ぶ。
     - 続けて `grid = True` に**強制**する（オシロ表示時はグリッドを必ず出す）。
10. **凡例**:
    - `if legend and chart_type != "円":`（円グラフに凡例は付けない）
      - `handles, labels = ax.get_legend_handles_labels()`。
      - `if ax2 is not None:`（第2軸の系列も凡例に統合）: `h2, l2 = ax2.get_legend_handles_labels()` を取り、`handles = handles + h2`、`labels = labels + l2`。
      - `if handles:` のとき `ax.legend(handles, labels, loc=legend_loc, fontsize=(fonts.get("legend") or fonts.get("tick", 9)))`。フォントサイズは `legend` キー優先、無ければ `tick`（既定 9）。
11. **グリッド（linewidth=None ガード）**:
    - `if grid and chart_type != "円":`
      - `gkw = {} if grid_width is None else {"linewidth": grid_width}`（**`grid_width` が `None` のときは `linewidth` を渡さない**＝既定の太さ。指定があるときだけ渡す）。
      - `ax.grid(True, linestyle="--", alpha=0.4, **gkw)`。線種は破線、透過 `alpha=0.4` 固定。
      - **落とし穴**: ここで `linewidth=None` を渡すと matplotlib が `float(None)` でクラッシュするため、上記の dict 分岐が必須。
12. **枠線（spine）の太さ**:
    - `if frame_width is not None:`
      - `ax` の全 spine について `for sp in ax.spines.values():` で `sp.set_linewidth(frame_width)` と `sp.set_visible(frame_width > 0)`（**0 以下なら枠を消す**）。
      - `if ax2 is not None:` なら `ax2.spines` にも同じ処理を適用。
      - `frame_width is None` のときは何もしない（matplotlib 既定のまま）。
13. **マーカー注記**（ピーク等）:
    - `if markers:` のとき、`for m in markers:`
      - `ax.plot(m["x"], m["y"], m.get("symbol", "v"), color=m.get("color", "red"), markersize=8)`（symbol 既定 `"v"`、color 既定 `"red"`、サイズ 8）。
      - `if m.get("text"):` なら `ax.annotate(m["text"], (m["x"], m["y"]), textcoords="offset points", xytext=(0, 8), ha="center", color=m.get("color", "red"), fontsize=fonts.get("tick", 9))`（点の 8pt 上にテキスト、中央寄せ）。
14. **`return ax`**。

`markers` 各要素の辞書キー: `"x"`, `"y"`（必須）/ `"symbol"`（既定 `"v"`）/ `"color"`（既定 `"red"`）/ `"text"`（任意）。

---

### `build_series_from_df(df, chart_type, x_col, y_cols)`

docstring（趣旨）: 「単一 DataFrame から系列リストと categories を作る（後方互換・簡易用途）」。

**戻り値**: タプル `(series, categories)`。`series` は dict のリスト、`categories` は numpy 配列または `None`。

**アルゴリズム:**
1. `info = CHART_INFO[chart_type]`（取得するが本関数内では使わない。種別不正なら `KeyError` で落ちる）。
2. `y_cols = list(y_cols or [])`（`None` を空リストに正規化してコピー）。
3. `categories = None`、`series = []` で初期化。
4. 種別による分岐:
   - `if chart_type in ("棒", "横棒", "積み上げ棒", "円"):`
     - `categories = df[x_col].to_numpy()`。
     - `for c in y_cols:` → `series.append({"label": c, "y": df[c].to_numpy()})`。
   - `elif chart_type in ("折れ線", "散布図"):`
     - `xv = df[x_col].to_numpy()`。
     - `for c in y_cols:` → `series.append({"label": c, "x": xv, "y": df[c].to_numpy()})`（全系列が同じ X 配列 `xv` を共有）。
   - `else:`（ヒストグラム / 箱ひげ）
     - `for c in y_cols:` → `series.append({"label": c, "y": df[c].to_numpy()})`。
5. `return series, categories`。

系列 dict のキー名は `"label"` / `"x"` / `"y"`（この通り。`label` には列名 `c` が入る）。

---

### `plot(ax, df, chart_type, x_col=None, y_cols=None, *, bins=10, title="", xlabel="", ylabel="", grid=True, legend=True, pct=False)`

完全シグネチャ（`*` 以降はキーワード専用）:

```python
def plot(ax, df, chart_type, x_col=None, y_cols=None, *, bins=10, title="",
         xlabel="", ylabel="", grid=True, legend=True, pct=False):
```

docstring（趣旨）: 「単一 DataFrame 版の簡易インターフェース（テスト・後方互換用）」。

**戻り値**: `plot_series(...)` の戻り値（＝ `ax`）。

**アルゴリズム:**
1. `info = CHART_INFO.get(chart_type)`。`info is None` なら `raise ValueError(f"未知のグラフ種別です: {chart_type}")`。
2. `if info["use_x"] and not x_col:` なら `raise ValueError("X軸の列を選択してください。")`（X 軸を使う種別で `x_col` 未指定はエラー）。
3. `if not y_cols:` なら `raise ValueError("Y軸（値）の列を選択してください。")`。
4. `series, categories = build_series_from_df(df, chart_type, x_col, y_cols)`。
5. `return plot_series(ax, series, chart_type, categories=categories, bins=bins, title=title, xlabel=xlabel or (x_col or ""), ylabel=ylabel, grid=grid, legend=legend, pct=pct)`。
   - **重要**: `xlabel` が空なら `x_col`（さらに `None` なら空文字）を X 軸ラベルとして使う（`xlabel or (x_col or "")`）。

---

## 再現に必須の細部・エッジケース・並び順

- **エラーメッセージ文字列は一字一句正確に**（末尾の句点「。」を含む）:
  - `f"未知のグラフ種別です: {chart_type}"`
  - `"Y軸（値）の系列を選択してください。"`（`plot_series`）/ `"Y軸（値）の列を選択してください。"`（`plot`）— **「系列」と「列」で文言が違う**ので混同しないこと。
  - `"X軸（カテゴリ）の列を選択してください。"`（棒系）
  - `"X軸（ラベル）の列を選択してください。"`（円）
  - `"X軸の列を選択してください。"`（`plot` の `use_x` チェック）
- **第2軸の保持属性名は `ax._twin_secondary`**（`_remove_twin` が掃除する前提のキー。名前を変えない）。
- 系列 dict の判定キー名: `"x"`, `"y"`, `"yerr"`, `"axis"`（値 `"secondary"`）, `"label"`, `"style"`。スケール処理は `sr.get(...)` でアクセスし、欠損は無視（`None`）として扱う。
- `xscale` / `yscale` のデフォルトは `1.0`（float）。`== 1.0` 比較で「変更なし」を判定するので、整数 1 でも float 比較が成立する。
- 第2軸系列に Y スケールを掛けない（`axis != "secondary"` 条件）のは、第2軸が独立スケールを持つため。
- 円グラフは: 軸ラベル・対数軸・軸範囲・凡例・グリッド・spine 調整を**いずれもスキップ**する（各ブロックの `if chart_type != "円":` ガード）。ただし `frame_width` の spine 処理とマーカー注記には `!= "円"` ガードが無いので、円でも実行され得る（仕様通りそのまま実装する）。
- オシロ表示の判定は `scope and scope.get("enabled")` の両方が真かつ折れ線/散布図のときのみ。判定後 `grid = True` を強制する副作用がある。
- グリッドは破線 `linestyle="--"`、`alpha=0.4` 固定。`linewidth` は `grid_width` 指定時のみ。
- `frame_width <= 0` で枠を非表示（`set_visible(frame_width > 0)`）。
- マーカー注記のテキストは点の 8pt 上（`xytext=(0, 8)`, `textcoords="offset points"`, `ha="center"`）。

---

## このファイルに関係する落とし穴（必読）

1. **grid の linewidth=None 回避**: `ax.grid(...)` に `linewidth=None` を渡してはいけない。`grid_width is None` のときは `linewidth` キーを dict から外す（`gkw = {} if grid_width is None else {"linewidth": grid_width}`）。これを怠ると `float(None)` で例外。
2. **facade 規約**: 実体は `plotter_format.py` / `plotter_draw.py`。本ファイルは `import *` で公開名を再公開し、`*` に含まれないアンダースコア関数（`_draw_xy` ほか）は**明示 import** する。公開シンボル名を変えない・減らさない。`_data_labels` は本ファイルで未使用でも再公開のため import 列挙に残す。
3. **Qt を import しない**: 本ファイルは GUI 非依存で、`batch_render`（別プロセス spawn）からも安全に使える純ロジック。matplotlib の Axes は引数 `ax` 経由でのみ触り、Qt/PySide6 を import しない。
4. **scipy を直接 import しない**: トレンドライン等は `plotter_draw` 側に委譲（そちらで遅延 import＋numpy フォールバック）。本ファイルでは `numpy` のみ使用（スケール掛けの `np.asarray`）。
5. **片側軸範囲の反映**: `set_xlim(left=...)` / `set_xlim(right=...)` のように片端だけ指定して、min/max の片方だけでも効くようにする。両端タプルで `set_xlim((a, b))` と渡す実装にすると片側指定が反映されない。
6. **系列 dict の破壊回避**: スケール掛けの前に `sr = dict(sr)` で浅いコピーしてから値を上書きする（呼び出し側の系列辞書を壊さない）。
7. **日本語ラベルに monospace 不使用**: 本ファイルは family を直接指定しないので問題は出ないが、`fonts` から取り出すサイズのみを使う方針を守る。
