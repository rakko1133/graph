# 生成プロンプトの動作テスト（テストケース）

`Copilot_新タブ生成プロンプト.md`（最新版）が**ちゃんと動くタブを吐くか**を確かめるための、
決まったお題。これを `【作りたい機能】` に入れて Copilot に送り、出力を `check_tab.py` に通す。
全PASS＋下の受け入れ条件を満たせば「プロンプトは動く」と判定できる。

- **ねらい**: まだ実証していない経路 **`register_dataset`（計算→新データ追加）＋ `QSpinBox` 設定の保存/復元**
  を突く。（`draw_overlay`＋設定往復は既に threshold タブで実証済みなので、これで両archetypeを網羅。）

---

## 手順

1. `Copilot_新タブ生成プロンプト.md` の本体をコピーし、`【作りたい機能】` に**下のお題を丸ごと**貼って Copilot に送る。
2. 出た `graph_tab_movingavg.py` を保存する。
3. （任意）続けて `Copilot_タブ検証プロンプト.md` を送って自己点検させる。
4. `python check_tab.py graph_tab_movingavg` を回す。
5. 下の「受け入れ条件」を確認する。

---

## テストお題（`【作りたい機能】` にそのまま貼る）

```
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
```

---

## 受け入れ条件（すべて満たせば「プロンプトは動く」）

**A. 生成物の形**
- Copilot が `graph_tab_movingavg.py` の**全文**と、足す import 1行（`import graph_tab_movingavg` 相当）を出す。
- `graph_app.py` 以外のコアを変更しない。

**B. `check_tab.py` が全PASS**（`python check_tab.py graph_tab_movingavg`）
- import / register_tab / 属性(key,title,order≥50,min_level) / `dock_movingavg` 出現 / draw_graph 無例外 /
  collect_config が JSON化可能 / apply_config 無例外 / 本体設定に `tabs.movingavg` として載る。
- ※ このタブに `draw_overlay` は無いので、その項目は検査されない（在るものだけ検査＝正常）。

**C. 実際の動作（手動で1回）**
- `起動.bat` で起動 → データを読み、`電圧` を選ぶ。
- 「移動平均」タブで窓幅=5 → 「移動平均を実行」。
- **`移動平均(窓5): 電圧` というデータセットが1つ増える**（ファイル一覧に現れ、選ぶと描ける）。
- 一度アプリを終了→再起動して、窓幅が **5 のまま復元**されている。

---

## 落ちやすい所（プロンプトが弱いと出る失敗＝ここが直っているかの試金石）
- `register_dataset` に **DataFrame でなく生配列**を渡す（→ 受け入れ条件Cで失敗）。
  → プロンプトの「DataFrame は横軸列＋値列」ガイドが効いていれば回避される。
- `apply_config` の中で `app.draw_graph()` を呼ぶ（→ 復元中に無駄描画）。
  → プロンプトの「apply_config は描かない」ガイドで回避。
- `numpy`/`pandas` の import 忘れ（→ check_tab.py の import でNG）。
  → プロンプトの「自分で import」ガイドで回避。

これらが**出なければ**、最新プロンプトのガイドが効いている＝「動く」と言える。
```
