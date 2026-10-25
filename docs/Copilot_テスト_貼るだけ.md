# プロンプト動作テスト：これを丸ごとコピペして Copilot に送るだけ

> 下のコードブロックを**全部コピー**して GitHub Copilot Chat に貼るだけ。書き換え不要。
> 出た `graph_tab_movingavg.py` を保存し、`python check_tab.py graph_tab_movingavg` が
> 全 PASS なら、最新の生成プロンプトは「動くコードを吐く」＝合格。

```text
このリポジトリ（PySide6 + matplotlib 製の CSV/TSV/波形データ グラフ・解析デスクトップアプリ）に、
新しい解析タブを1つ追加してください。タブは差し込み式で、メインの graph_app.py は import 1行以外は
触らずに追加できます。

【成果物（これ以外は作らない・変更しない）】
1. 新規ファイル graph_tab_movingavg.py を1つ。
2. graph_app.py 冒頭の import 群に足す1行（import graph_tab_movingavg 相当）。

【守る規約】
- graph_app_common.TabPlugin を継承したクラスを1つ定義し、ファイル末尾で register_tab(<クラス>()) を呼ぶ。
- クラス属性: key（英小文字・一意）/ title / order（50以上）/ min_level（"基本"/"標準"/"全部"、迷ったら"全部"）。
- build(self, app) でウィジェットを作って返す。後で使う入力欄は self. に持つ。
- 再描画の配線: 値が変わったら app.draw_graph() を呼ぶ。ただし QLineEdit は editingFinished、
  チェック/コンボ/スピンは toggled/currentTextChanged/valueChanged。textChanged で1文字ごとに再描画しない。
- 下の「使ってよいAPI」以外の app のメソッドは呼ばない（存在しないメソッドを発明しない）。
- graph_app.py の import 1行以外、他のコアファイルは一切変更しない。設定は JSON化できる値だけ。UTF-8。

【使ってよいAPI（app は GraphApp インスタンス）】
- got = app.analysis_xy_or_warn()
  if got is None: return
  t, y, label = got                                   # 選択中の解析対象 (t, y, ラベル)
- t, y = app.series_xy(fl, col)                        # 特定系列の (t, y)
- for fl, col, disp in app._selected_series_items():  # 選択中Y系列の列挙
- app.register_dataset("名前: " + label, dataframe)   # dataframe は 横軸列＋値列 の pandas.DataFrame
- app.draw_graph()  /  app.notify("文","info"|"ok"|"warn"|"error")  /  app._set_status("文")

【任意メソッド（定義すればコア無改変で効く）】
- def draw_overlay(self, app, ax): 再描画のたびに呼ばれ、ax(matplotlib Axes)へ重ね描き。色を明示。
  3D軸を前提にしない。この中で app.draw_graph() を呼ばない。
- def collect_config(self, app): 設定を JSON化可能な dict で返す（自動保存）。
- def apply_config(self, app, cfg): dict をウィジェットに戻すだけ。blockSignals で囲む。
  ここで app.draw_graph() は呼ばない。

【骨組み】
from graph_app_common import TabPlugin, register_tab, QtWidgets
import numpy as np
import pandas as pd

class MovingAvgTab(TabPlugin):
    key = "movingavg"; title = "5. 移動平均"; order = 50; min_level = "全部"
    def build(self, app):
        w = QtWidgets.QWidget(); lay = QtWidgets.QFormLayout(w)
        # ここに窓幅 QSpinBox と「移動平均を実行」ボタンを作る
        return w
    # collect_config / apply_config も実装する
# 末尾: register_tab(MovingAvgTab())

【作りたい機能】
選択中の「解析対象」の系列に移動平均をかけ、新しいデータセットとして追加するタブ。
- key=movingavg, title="5. 移動平均"。
- 窓幅を QSpinBox（範囲 1〜999、既定 5）で指定する。行ラベルは「窓幅(点)」。
- 「移動平均を実行」ボタンを押すと:
    got = app.analysis_xy_or_warn()
    if got is None: return
    t, y, label = got
  として (t, y) を取り、numpy で窓幅ぶんの単純移動平均 y_ma を計算し（端は
  np.convolve(..., mode="same") 等でよい）、
    df = pd.DataFrame({"時間": t, "移動平均": y_ma})
    app.register_dataset(f"移動平均(窓{窓幅}): {label}", df)
  で新データとして追加する。最後に app.notify(f"{label} に移動平均(窓{窓幅})をかけました", "ok")。
- 窓幅は collect_config/apply_config で保存・復元する（QSpinBox なので valueChanged で配線してよい）。
- numpy / pandas は自分で import する。

【出力】
1. graph_tab_movingavg.py の全文（そのまま保存できる完全なコード）。
2. graph_app.py に足す import の1行。
3. 動かし方の1行メモ。
```

---

## 送ったあと（コピペで確認）
```bash
python check_tab.py graph_tab_movingavg
```
全 PASS＋「移動平均(窓5): 電圧」データセットが増えれば、最新プロンプトは合格。
