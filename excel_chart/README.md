# excel_chart — Python だけで「特定列＋特定書式」のネイティブ Excel グラフを作る

提出用に「Excel のグラフ」を求められたとき、Python だけで**VBA マクロと同等**の
ネイティブ Excel グラフ（編集可能なグラフオブジェクト）を生成するための独立ツール。
既存の GUI（PySide6 アプリ）には一切手を入れず、**データ読み込みと書式モデルだけを
流用**する。

## 2 つのエンジン（同じ書式指定 `ChartSpec` を解釈）

| エンジン | 中身 | 書式の再現度 | Excel 要否 | 対応 OS | マクロ同等 |
|---|---|---|---|---|---|
| **com**（既定・推奨） | pywin32 で実 Excel を COM 操作。VBA と同じ `Excel.Application` オブジェクトモデルを叩く | **上限なし（完全）** | 要 | Windows / mac | **○ 完全** |
| **openpyxl** | OOXML を直接生成。Excel 不要・CI/サーバOK | 高いが天井あり | 不要 | Win/mac/Linux | △ |

`engine="auto"`（既定）なら、Excel が使える環境では `com`、無ければ `openpyxl` を自動選択。
`.xlsm`（マクロ有効ブック）出力は `com` のみ。

> **なぜ com が「マクロ同等」か**: `com_engine` は系列・軸・凡例を作った後、
> Excel の生 COM オブジェクトへ直接プロパティを設定している。これは VBA マクロが
> 触るのと同一の API なので、線種・色（BGR）・太さ・マーカー・軸範囲/タイトル・
> 対数軸・反転・第2軸・凡例位置・データラベル・エラーバーまで再現できる。

## 使い方

### GUI（推奨・マウス操作だけで完結）

```bash
python -m excel_chart.gui
```
（リポジトリ直下の `Excelグラフ出力_起動.bat` をダブルクリックでも可）

操作の流れ:
1. **ファイルを開く**（CSV/TSV/Excel。ウィンドウへドラッグ&ドロップも可）
2. グラフ種別・X 軸・Y 軸（チェック）を選ぶ
3. 系列の書式（色・線種・幅・マーカー・主/第2軸）、タイトル/軸ラベル、軸範囲、
   凡例/グリッド/データラベルを整える（右側に matplotlib プレビューが即反映）
4. エンジン（自動/COM/openpyxl）を選び **「Excel に出力」** → 保存先を指定

右ペインのプレビューは matplotlib（見た目の意図確認用）。実際の出力は編集可能な
**ネイティブ Excel グラフ**。

### CLI

```bash
# 折れ線（X=時刻, Y=気温・電力, 電力は第2軸, 色指定）を VBA互換で出力
python -m excel_chart "サンプルデータ/Excel編集デモ.csv" \
    --x "時刻[h]" --y "気温[℃]" "電力[kW]" --type 折れ線 \
    --secondary "電力[kW]" --colors "#d62728" "#1f77b4" \
    --title 気温と電力 --xlabel 時刻 --ylabel 気温 --secondary-label 電力 \
    --out 出力.xlsx

# GUI で作った設定 JSON（書式プリセット/セッション）の見た目をそのまま流用
python -m excel_chart data.csv --config graph_config.json --out 出力.xlsx

# Excel 無し環境（CI 等）で生成
python -m excel_chart data.csv --x t --y v --engine openpyxl --out out.xlsx

# マクロ有効ブック（.xlsm）として出力（COM のみ）
python -m excel_chart data.csv --x t --y v --out out.xlsm
```

主なオプション: `--type`（折れ線/棒/横棒/積み上げ棒/散布図/円/ヒストグラム）、
`--secondary`（第2軸にする列）、`--colors`、`--xmin/--xmax/--ymin/--ymax`、
`--xlog/--ylog`、`--xinvert/--yinvert`、`--data-labels`、`--no-legend/--no-grid`、
`--legend-loc`、`--bins`、`--engine`、`--visible`。

### Python API

```python
from excel_chart import export_excel_chart, ChartSpec

# (1) 列と種別を直接指定
export_excel_chart("data.csv", x="時刻", y=["気温", "電力"],
                   chart_type="折れ線", out_path="out.xlsx")

# (2) 系列ごとに書式を細かく指定
spec = ChartSpec.from_columns(
    "時刻", ["気温", "電力"], chart_type="折れ線",
    styles={"気温": {"color": "#d62728", "marker": "o", "linestyle": "-"},
            "電力": {"color": "#1f77b4", "axis": "secondary", "linestyle": "--"}},
    title="気温と電力", xlabel="時刻", ylabel="気温", secondary_label="電力",
    ymin=0, ymax=30, legend_loc="lower right")
path, engine = export_excel_chart("data.csv", spec=spec, out_path="out.xlsx")

# (3) 既存 GUI の設定 JSON を書式に流用
import json
from excel_chart import export_from_config
cfg = json.load(open("graph_config.json", encoding="utf-8"))
export_from_config("data.csv", cfg, out_path="out.xlsx")
```

`data` は DataFrame でも、CSV/TSV/Excel のパスでも可（パスの場合は既存
`data_loader` で文字コード・区切りを自動判定して読み込む）。

## 既存システムからの流用ポイント

- **データ読み込み**: `data_loader.load_table`（CSV/TSV/Excel・文字コード/区切り自動判定）
- **書式モデル**: スタイル dict（`color/linestyle/linewidth/marker/markersize/axis/kind/errcol`）と
  日本語ラベル（`実線/破線…`, `丸/四角…`）は GUI と同一
- **書式の供給**: GUI の設定 JSON（`_collect_config` 形式）やプリセットを
  `ChartSpec.from_app_config` でそのまま読み込める

## 制限・注意

- `com`/`openpyxl` とも **箱ひげ図は未対応**（ネイティブ Excel グラフに無い）。箱ひげは
  既存 GUI（matplotlib）で画像出力を。
- `com` は Excel 必須・Windows/mac のみ（Linux/ヘッドレス不可）。終了時に
  `EXCEL.EXE` を確実に解放するよう実装済み。
- `openpyxl` はグラフを**描画しない**（画像化しない）。図は Excel/LibreOffice で
  開いた時に初めて描かれる。一部の高度な書式は OOXML に露出しておらず再現できない。
- 色は web 表記 `#RRGGBB` で指定。COM 側は内部で BGR 整数へ変換（VBA の罠を吸収）。

## 構成

```
excel_chart/
├─ __init__.py          公開 API（export_excel_chart / ChartSpec ...）
├─ __main__.py          python -m excel_chart のエントリ
├─ gui.py               GUI アプリ（python -m excel_chart.gui）。data_loader/jp_font/plotter を流用
├─ cli.py               コマンドライン
├─ export.py            データ読込→エンジン選択→出力（data_loader を流用）
├─ spec.py              ChartSpec（書式の中立表現）と組み立て
├─ mapping.py           matplotlib/日本語 → Excel 値 の対応表（色/線種/マーカー/凡例）
├─ com_engine.py        pywin32 COM = VBA 完全互換エンジン
└─ openpyxl_engine.py   OOXML 直接生成 = Excel 不要フォールバック
```
（リポジトリ直下に GUI 起動用 `Excelグラフ出力_起動.bat` あり）

テスト: `tests/test_excel_chart.py`（Excel 不要・openpyxl 経路を検証。CI で実行）。
