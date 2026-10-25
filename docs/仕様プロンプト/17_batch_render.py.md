# [17/30] batch_render.py の仕様

## 指示

- **この仕様だけを読んで `batch_render.py` を完全な形で実装し、出力すること。** 他ファイルの参照なしで動く完結したソースを書く。
- **`pass` だけの関数・`TODO`・「省略」・要約・ダミー実装は禁止。** すべての関数の本体を最後まで実装する。
- **出力が途中で切れたら、続けて「続き」を要求されたら最後まで出し切ること。** 関数を尻切れにしない。
- このファイルは「丸写しコード」を与えられずに、本仕様だけから完全再現できることを目的とする。

### アプリ全体の前提（このファイルに関係する分のみ）

- Python 3.10+。アプリ本体の GUI は PySide6(Qt6) だが、**`batch_render.py` は Qt をいっさい import しない**（`ProcessPoolExecutor` の `spawn` で別プロセス起動しても安全にするため）。
- matplotlib は **Agg バックエンド固定**（画面なしで描画・保存できる）。
- 日本語は `family="monospace"` を使わない（□化け回避）。日本語フォント設定は `jp_font` モジュール側で `axes.unicode_minus=False` も含めて行う。本ファイルからは `jp_font.setup_japanese_font(...)` を呼ぶだけ。
- 実際の描画ロジックは `plotter.plot_series(...)` に集約されている（facade）。本ファイルは「画面描画・逐次出力とまったく同じ `plot_series` 経路」を使うことで、出力画像が画面とピクセル一致するよう保証する。

---

## 1. ファイルの役割・責務

一括出力（バッチ書き出し）の **ワーカー**。`GraphApp` 本体から渡された picklable な「タスク dict」を受け取り、matplotlib の `Figure` に `plotter.plot_series` で描画し、ファイルへ保存する。

docstring の趣旨（モジュール先頭）:

> 一括出力のワーカー（Qt非依存・別プロセスでも実行可能）。
> `ProcessPoolExecutor` から呼ぶため、ここでは Qt や `graph_app` を import しない。
> matplotlib は Agg バックエンド固定。タスクは完全に picklable な dict 1個で渡す。

責務:
- 並列出力（`ProcessPoolExecutor` の各ワーカーが `render_one` を 1 タスクずつ実行）。
- 逐次出力（`render_sequential` が 1 つの Figure を使い回して全タスクを処理）。並列が使えない/不要なときのフォールバック。
- ワーカープロセスごとに 1 回だけ日本語フォントを設定する（`_ensure_font`）。

**設計上の重要点**: `render_one` は ProcessPoolExecutor から各タスクを渡されて呼ばれることを想定し、`task` は 1 個の dict だけ（複数引数にしない＝pickle と map が単純になる）。Qt / graph_app を import しないことが spawn 安全性の生命線。

---

## 2. 依存（import するもの）

モジュール先頭で（この順序・この内容で）:

```python
# -*- coding: utf-8 -*-
import matplotlib
matplotlib.use("Agg", force=True)
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg

import plotter
```

- `matplotlib.use("Agg", force=True)` は **`Figure` などを import する前**に呼ぶ（バックエンド固定）。`force=True` を付ける。
- `jp_font` は `_ensure_font` の中で **遅延 import**（関数内 import）する。トップレベルで import しない。
- `render_sequential` の中で `os` を **関数内 import** する（`os.path.basename` をエラーメッセージに使うため）。
- Qt / PySide6 / graph_app 系は**いっさい import しない**。

---

## 3. モジュール定数

```python
_FONT_DONE = False
```

- ワーカープロセスごとのグローバルフラグ。フォント設定を「プロセス内で 1 回だけ」行うためのガード。

---

## 4. 公開API（全関数の完全シグネチャと挙動）

### 4.1 `def _ensure_font(font_name):`

**役割**: ワーカープロセスごとに 1 回だけ日本語フォントを設定（□□□化を防ぐ）。

**挙動（擬似コード）**:

```
global _FONT_DONE
if not _FONT_DONE:
    try:
        import jp_font                         # 遅延 import
        jp_font.setup_japanese_font(font_name) # 引数 font_name をそのまま渡す
    except Exception:                          # noqa: BLE001  フォント未検出でも既定で続行
        pass
    _FONT_DONE = True                          # 成否にかかわらず True にする（再試行しない）
```

- 戻り値なし（`None`）。
- 例外は握りつぶす（フォントが見つからなくても matplotlib の既定フォントで処理続行する）。
- `_FONT_DONE = True` は **try/except の外**で、成功・失敗どちらでもセットする（プロセス内で 2 度目以降は何もしない）。
- `font_name` は呼び出し側から `None` で渡ってくることもある（`task.get("font_name")`）。その場合 `jp_font.setup_japanese_font(None)` を呼ぶ（jp_font 側で既定にフォールバックする想定）。

---

### 4.2 `def render_one(task):`

**役割**: 1 ファイル分を描画して保存し、保存パス（文字列）を返す。`task` は picklable な dict。画面描画・逐次出力と同一の `plot_series` 経路を使うため、出力はピクセル一致する。

**戻り値**: `task["path"]`（保存先パス文字列）。

**挙動（精密手順）**:

1. `_ensure_font(task.get("font_name"))` を呼ぶ（フォント設定。`font_name` キーが無ければ `None`）。
2. `fig = Figure(figsize=task["figsize"], dpi=task["dpi"])` で Figure 生成。
3. `FigureCanvasAgg(fig)` を生成（戻り値は使わないが、Figure に Agg キャンバスを結び付けるため**必ず呼ぶ**。これが無いと `savefig` 系が正しく動かないことがある）。
4. `ax = fig.add_subplot(111)`。
5. `plotter.plot_series` を**次の引数で**呼ぶ（位置引数 `ax, task["series"], task["ctype"]`、以降すべてキーワード）:
   ```python
   plotter.plot_series(
       ax, task["series"], task["ctype"], categories=task["categories"],
       title=task["title"], xlabel=task["xlabel"], ylabel=task["ylabel"],
       xlim=task["xlim"], ylim=task["ylim"],
       secondary_label=task["sec_label"], max_points=task["max_points"],
       **task["fmt"])
   ```
   - `task["ctype"]` がグラフ種別（`plot_series` の第3引数 `chart_type`）。
   - `task["sec_label"]` は `plot_series` の `secondary_label=` に渡す（dict キー名と引数名が異なる点に注意）。
   - `task["fmt"]` は**残りの全書式オプションをまとめた dict**で、`**` 展開で渡す（grid・legend・色・トレンドライン・xscale 等が入る。`plot_series` の他の任意キーワードはここ経由）。
6. アスペクト比の処理:
   ```python
   ratio = task.get("ratio")
   if ratio:
       ax.set_box_aspect(ratio)
       ax2 = getattr(ax, "_twin_secondary", None)
       if ax2 is not None:
           ax2.set_box_aspect(ratio)
   ```
   - `ratio` が真値（None や 0 でない）のときだけ `set_box_aspect` を適用。
   - 第2軸（twin）が存在する場合（`plot_series` が `ax._twin_secondary` 属性として第2軸を付与している）、その軸にも同じ box aspect を適用して左右軸の見た目をそろえる。属性が無ければ `getattr(..., None)` で `None` になりスキップ。
7. tight（余白トリミング）の処理:
   ```python
   tight = task.get("tight", True)   # 既定 True
   if not tight:                     # 図サイズ＝画像比率。ラベルが収まるよう整える
       try:
           fig.tight_layout()
       except Exception:
           pass
   ```
   - `tight` キーが無ければ既定 `True`。
   - `tight` が **False のとき**だけ `fig.tight_layout()` を呼ぶ（失敗しても握りつぶす）。これは「図サイズをそのまま画像の縦横比にしたい」モード用で、ラベルが切れないようレイアウト調整する。
8. 保存:
   ```python
   fig.savefig(task["path"], dpi=task["dpi"],
               bbox_inches=("tight" if tight else None),
               transparent=task["transparent"])
   ```
   - `bbox_inches` は `tight` が True なら文字列 `"tight"`、False なら `None`。
   - **`bbox_inches=None`（tight モード）を必ず許容すること**＝`tight=False` のときは図サイズ通りに出す。
   - `transparent=task["transparent"]`（背景透過の真偽）。
9. `return task["path"]`。

**重要な `task` dict のキー一覧（render_one が参照する）**:

| キー | 取得方法 | 用途/型 |
|---|---|---|
| `font_name` | `.get("font_name")` | 日本語フォント名（無ければ None 可） |
| `figsize` | `["figsize"]` 必須 | `(w, h)` インチ |
| `dpi` | `["dpi"]` 必須 | 解像度 |
| `series` | `["series"]` 必須 | 系列データ（plot_series の series） |
| `ctype` | `["ctype"]` 必須 | グラフ種別（plot_series の chart_type） |
| `categories` | `["categories"]` 必須 | カテゴリ軸ラベル等 |
| `title` | `["title"]` 必須 | タイトル文字列 |
| `xlabel` | `["xlabel"]` 必須 | X軸ラベル |
| `ylabel` | `["ylabel"]` 必須 | Y軸ラベル |
| `xlim` | `["xlim"]` 必須 | X範囲 |
| `ylim` | `["ylim"]` 必須 | Y範囲 |
| `sec_label` | `["sec_label"]` 必須 | 第2軸ラベル → `secondary_label=` へ |
| `max_points` | `["max_points"]` 必須 | 間引き上限 |
| `fmt` | `["fmt"]` 必須 | 残り書式オプション dict（`**` 展開） |
| `ratio` | `.get("ratio")` | box aspect 比（真値のときだけ適用） |
| `tight` | `.get("tight", True)` | 余白トリミング有無（既定 True） |
| `path` | `["path"]` 必須 | 保存先パス（戻り値にもなる） |
| `transparent` | `["transparent"]` 必須 | 透過保存の真偽 |

- 上表で「必須」のキーは `task[...]` で直接添字アクセス（無ければ `KeyError` で失敗 → 並列実行側で例外になる）。`.get(...)` のキー（`font_name` / `ratio` / `tight`）だけ欠落許容。

---

### 4.3 `def render_sequential(tasks):`

**役割**: 逐次出力。1 つの Figure を使い回して `tasks`（タスク dict のリスト）を全部処理する。並列が使えない／不要なときのフォールバック。

**戻り値**: タプル `(saved, skipped)`
- `saved`: 保存に成功したパス文字列のリスト。
- `skipped`: 失敗したファイルの説明メッセージ文字列のリスト。

**挙動（精密手順）**:

1. 関数の冒頭で `import os`（関数内 import）。
2. `saved, skipped = [], []` で空リスト初期化。
3. **`tasks` が空なら即 `return saved, skipped`**（空タプルではなく空リスト2つを返す。Figure を作らずに早期 return）。
4. **1 つだけ Figure を作る**（先頭タスクの figsize/dpi を使う）:
   ```python
   fig = Figure(figsize=tasks[0]["figsize"], dpi=tasks[0]["dpi"])
   FigureCanvasAgg(fig)
   ax = fig.add_subplot(111)
   ```
   - figsize/dpi はタスクごとに異なり得るが、ここでは先頭の値で 1 度だけ Figure を作り、以降は使い回す（逐次モードの仕様。figsize はタスク間で共通である前提）。
5. `for t in tasks:` で各タスクを処理。**各反復は try/except で囲む**（1 つ失敗しても残りを続ける）:
   ```python
   for t in tasks:
       try:
           ax.clear()                       # 前タスクの描画をクリアして使い回す
           plotter.plot_series(
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
   ```
   - **`ax.clear()` を毎回呼ぶ**こと（Figure を使い回すので前の描画を消す。これが無いと重なる）。
   - `plot_series` 呼び出し・ratio 処理・tight 処理・savefig は `render_one` と同一ロジック（dict キー名も同じ）。
   - 成功したら `saved.append(t["path"])`。
   - 失敗したら `skipped.append(f"{os.path.basename(t['path'])}（{e}）")` という形式の日本語メッセージを追加する。**全角括弧 `（` `）`** を使い、中にファイル名と例外文字列を入れる。
6. ループ後 `return saved, skipped`。

**エラーメッセージ書式（厳密に再現すること）**:
- `f"{os.path.basename(t['path'])}（{e}）"`
  - 例: `グラフ_01.png（division by zero）`
  - ファイル名はフルパスではなく `os.path.basename` で末尾のみ。
  - 区切りは半角括弧でなく**全角の `（` と `）`**。

---

## 5. 再現に必須の細部・エッジケース・ガード

- **import 順序**: `matplotlib.use("Agg", force=True)` を `from matplotlib.figure import Figure` より前に置く。
- **`FigureCanvasAgg(fig)` を必ず生成**（戻り値は捨てる）。`render_one` と `render_sequential` の両方で行う。
- **`_FONT_DONE` は成否に関わらず True にする**（再試行しない設計）。フォント例外は `pass`。
- **空タスク早期 return**: `render_sequential` で `tasks` が空のとき Figure を作らずに `([], [])` を返す。
- **逐次は Figure 1 個を使い回し、毎回 `ax.clear()`**。並列（`render_one`）はタスクごとに Figure を新規作成。
- **`bbox_inches`**: tight True → `"tight"`、tight False → `None`。`None` を渡すのは正常動作（図サイズ通り出力）。`bbox_inches=None` を「指定しない」に置き換えてはいけない（明示的に `None` を渡す）。
- **`ratio` のガード**: `if ratio:`（真値判定）で囲む。`None` / `0` / 空のときは `set_box_aspect` を呼ばない。
- **twin 軸**: `getattr(ax, "_twin_secondary", None)` で安全に取得（属性が無くても落ちない）。第2軸があれば box aspect を合わせる。
- **`tight_layout` の例外握りつぶし**: `try/except Exception: pass`。レイアウト調整に失敗しても保存は続行。
- **render_sequential の per-task try/except**: 1 件の失敗で全体を止めない。失敗は `skipped` に蓄積。
- **dict キー名の差異に注意**: `task["sec_label"]` → `plot_series(secondary_label=...)`、`task["ctype"]` → `plot_series` 第3引数 `chart_type`。
- **`fmt` は `**` 展開**: grid・legend・色・log・pct・トレンドライン等の残り書式は `task["fmt"]` に詰めて展開する。本ファイルは中身を解釈しない（透過的に plot_series へ渡すだけ）。

### 参考: `plotter.plot_series` のシグネチャ（呼び出し側として把握しておく）
本ファイルが渡すキーワードと整合するよう、`plot_series` は概ね次の形:
```python
def plot_series(ax, series, chart_type, *, categories=None, bins=10,
                title="", xlabel="", ylabel="", grid=True, legend=True,
                legend_loc="best", xlim=None, ylim=None, xlog=False, ylog=False,
                pct=False, fonts=None, scope=None, markers=None, max_points=0,
                trendline=None, data_labels=False, secondary_label="",
                xscale=1.0, yscale=1.0, xunit="", yunit="", bg_color=""):
```
- `categories / title / xlabel / ylabel / xlim / ylim / secondary_label / max_points` は本ファイルが明示キーワードで渡す。
- 上記以外（grid, legend, legend_loc, xlog, ylog, pct, fonts, markers, trendline, data_labels, xscale, yscale, xunit, yunit, bg_color, scope, bins 等）は **`task["fmt"]` 経由**で渡る想定。**本ファイル側でこれらの引数名を直接列挙する必要はない**（`**task["fmt"]` に任せる）。

---

## 6. このファイルに関係する落とし穴

- **Qt を import しない**: PySide6/Qt 由来のものを 1 つでも import すると `spawn` で別プロセス起動時に重く・不安定になる。`graph_app*` も import 禁止。描画は `plotter` と `matplotlib` だけで完結させる。
- **Agg バックエンド固定**: GUI バックエンドのままだと別プロセス/ヘッドレスで落ちる。`matplotlib.use("Agg", force=True)` を最優先で実行。
- **monospace 回避**: 日本語が □ 化けないよう、フォントは `jp_font.setup_japanese_font` 任せ。本ファイルで `family="monospace"` を指定しない（`plot_series` も同様の方針）。
- **grid の linewidth に None を渡さない**: grid 関連の書式は `task["fmt"]` 経由で `plot_series` に渡る。本ファイルでは grid を直接いじらないが、`fmt` に余計な `None` を混ぜない（呼び出し側 GraphApp が「指定があるときだけ linewidth を入れる」責任を持つ。`float(None)` で落ちるため）。本ファイルは `fmt` を透過的に渡すだけ。
- **`bbox_inches=None` を省略形に変えない**: tight=False のとき明示的に `None` を渡す（図サイズ＝画像比率を維持するため）。
- **facade 経路の一致**: 画面・逐次・並列のいずれも同じ `plotter.plot_series` を通すことで出力がピクセル一致する。独自描画コードを足さない。
- **picklable 制約**: `render_one(task)` の `task` は 1 個の dict。複数引数化や非 picklable オブジェクト（Qt ウィジェット、ロック等）を混ぜない。
