# Copilot 用ひな型：このアプリに新しいタブ（機能）を1つ追加する

> 使い方: 下の「プロンプト本体」を **GitHub Copilot Chat に貼り付け**、
> `【ここに作りたい機能を書く】` を書き換えて送る。**`graph_app_common.py` と `タブ追加ガイド.md` を
> Copilot に必ず添付（ファイルを開く）** するとさらに精度が上がる（検索任せだと `.pyc` しか見つからず
> 本文を読めないことがある）。※ ただし本プロンプトは単体で完結しており、添付できなくても動くコードは出る。

---

## プロンプト本体（ここから下をコピーして使う）

あなたはこのリポジトリ（PySide6 + matplotlib 製の CSV/TSV/波形データ グラフ・解析
デスクトップアプリ）に、**新しい解析タブを1つ追加**します。タブは差し込み式
（プラグイン）で、メインの `graph_app.py` は **import 1行以外は触らずに** 追加できます。

### まず参照するファイル
- `タブ追加ガイド.md` … 追加のしかたと使えるAPIの一覧
- `graph_app_common.py` … 基底クラス `TabPlugin`（`key/title/order/min_level` と `build(app)`）

### 作る成果物（これ以外は作らない・変更しない）
1. 新規ファイル `graph_tab_<英小文字の名前>.py` を **1つ**。
2. `graph_app.py` 冒頭の import 群に足す **1行**（例: `from graph_tab_<名前> import <クラス名>`）。

### 守る規約（重要）
- `graph_app_common.TabPlugin` を継承したクラスを1つ定義し、ファイル末尾で
  `register_tab(<クラス>())` を呼ぶ。
- クラス属性: `key`（一意・英小文字）／`title`（例 `"5. 移動平均"`）／
  `order`（内蔵タブは 10/20/30/40。**50以上**にする）／`min_level`（`"基本"`/`"標準"`/`"全部"`、迷ったら `"全部"`）。
- `build(self, app)` でウィジェットを作って返す。ウィジェット参照は `self.` に持つ
  （後で `collect_config` 等から読めるように）。
- 再描画の配線: 値が変わったら `app.draw_graph()` を呼ぶが、`QLineEdit` は
  **`editingFinished`**（確定・フォーカス外し）で呼ぶ。`textChanged` で**1文字ごとに再描画しない**
  （大きいデータで重くなる）。チェック/コンボ/スピンは `toggled`/`currentTextChanged`/`valueChanged` でよい。
- **下の「使ってよいAPI」以外の app のメソッドは呼ばない**（存在しないメソッドを発明しない）。
- `graph_app.py` の import 1行以外、**他のコアファイルは一切変更しない**。
- 設定を保存するなら **JSON化できる値だけ**（数値・文字列・真偽・リスト・辞書）。
- 文字コードは **UTF-8**、既存の書き方（日本語コメント可）に合わせる。

### 使ってよいAPI（`app` は GraphApp インスタンス）
- 選択中の解析対象 `(t, y, ラベル)` を取る（未選択なら自動で警告して None）:
  ```python
  got = app.analysis_xy_or_warn()
  if got is None:
      return
  t, y, label = got
  ```
- 特定系列（ファイル名, 列名）の `(t, y)` を取る: `t, y = app.series_xy(fl, col)`
- 選択中のY系列を列挙: `for fl, col, disp in app._selected_series_items(): ...`
- 計算結果を新しいデータとして追加: `app.register_dataset("移動平均: " + label, dataframe)`
  （`dataframe` は **横軸列＋値列を持つ** pandas.DataFrame。例 `pd.DataFrame({"time": t, "移動平均": y2})`。
  ファイル一覧・列一覧まで自動更新される。numpy/pandas が要るなら自分で `import numpy as np` / `import pandas as pd`）
- グラフを再描画: `app.draw_graph()`
- 画面内通知（モーダルにしない）: `app.notify("文", "info")` … 第2引数は `"info"/"ok"/"warn"/"error"`
- ステータスバーへ1行: `app._set_status("文")`

### 任意メソッド（定義すればコアを触らず効く）
- `def draw_overlay(self, app, ax):` … `app.draw_graph()` のたびに呼ばれ、メイングラフ
  `ax`（matplotlib の Axes）へ重ね描きできる。状態を変えたら `app.draw_graph()` を呼ぶ。
  - 描く線・帯・注記は **データ系列と紛れないよう色を明示**する（例 `color="tab:red"`、帯は `alpha=0.15`）。色サイクル任せにしない。
  - **通常の2Dグラフのときだけ呼ばれる**（3D・FFT等の特殊表示では呼ばれない）。軸種の手判定は不要
    （3D等でエラーが出ても本体が try/except で吸収する）。3D前提の描画は書かない。
- `def collect_config(self, app):` … このタブの設定を dict で返す（終了時に自動保存）。JSON化できる値だけ。
- `def apply_config(self, app, cfg):` … 保存 dict を**ウィジェットに書き戻すだけ**。復元中は
  `blockSignals(True/False)` で信号を止める。**ここで `app.draw_graph()` は呼ばない**
  （復元後に本体が描き直す。ここで描くと復元中に無駄な再描画＋Undo記録が走る）。

### 骨組み（この形に沿って書く）
```python
from graph_app_common import TabPlugin, register_tab, QtWidgets


class MyToolTab(TabPlugin):
    key = "mytool"          # 一意・英小文字。ドックは "dock_mytool"
    title = "5. 自作ツール"
    order = 50
    min_level = "全部"

    def build(self, app):
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        btn = QtWidgets.QPushButton("実行")
        btn.clicked.connect(lambda: self._run(app))
        lay.addWidget(btn)
        lay.addStretch(1)
        return w

    def _run(self, app):
        got = app.analysis_xy_or_warn()
        if got is None:
            return
        t, y, label = got
        # ここで計算する（numpy/pandas を使ってよい）
        app.notify(f"{label} を処理しました", "ok")


register_tab(MyToolTab())
```
追加する import 行（`graph_app.py` 冒頭へ）: `from graph_tab_mytool import MyToolTab`

### 任意メソッドを使う場合の型（描く・設定を保存するなら、この形を真似る）
```python
    def build(self, app):
        w = QtWidgets.QWidget(); lay = QtWidgets.QFormLayout(w)
        self.thr = QtWidgets.QLineEdit()
        self.thr.editingFinished.connect(lambda: app.draw_graph())  # ← 毎文字ではなく確定時
        lay.addRow("しきい値", self.thr)
        return w

    def draw_overlay(self, app, ax):        # 通常2Dグラフのときだけ呼ばれる
        try:
            y = float(self.thr.text())
        except ValueError:
            return
        ax.axhline(y, color="tab:red", linestyle="--")  # 色は明示（データと紛れない）

    def collect_config(self, app):
        return {"thr": self.thr.text()}

    def apply_config(self, app, cfg):
        self.thr.blockSignals(True)
        self.thr.setText(str(cfg.get("thr", "")))
        self.thr.blockSignals(False)        # ← ここで app.draw_graph() は呼ばない
```

### 作りたい機能
【ここに1〜3行で、作りたいタブの機能を書く。例:
　「選択中の系列に移動平均をかけるタブ。窓幅は QSpinBox で指定し、『実行』で
　　結果を新しいデータセットとして追加する。窓幅は設定として保存・復元する。」】

### 出力
1. `graph_tab_<名前>.py` の**全文**（そのまま保存できる完全なコード）。
2. `graph_app.py` に足す import の**1行**（正確に）。
3. 動かし方の1行メモ。

---

## 送ったあとにやること（人間側）
1. 出てきたファイルを `graph_tab_<名前>.py` として保存する。
2. `graph_app.py` 冒頭の import 群に、指定された1行を足す。
3. `起動.bat` で起動し、タブが増えて動くか確認する。
4. （あれば）`python tests/test_app.py` などのテストを流す。
