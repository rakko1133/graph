# -*- coding: utf-8 -*-
"""サンプルデータ生成スクリプト。

生成物（リポジトリ直下の サンプルデータ/ に出力。.gitignore 対象なので
CSV 本体はコミットせず、この再生成スクリプトだけを管理する）:

  1. 正弦波_余弦波.csv … 純粋な sin 波・cos 波（2D の折れ線／オシロ確認用）
  2. らせん_3D.csv     … 3次元らせん（3D 折れ線／散布図の回転確認用）
  3. 主成分分析_3D.csv … 合成クラスタデータを PCA(numpy SVD)で3次元へ。
                          クラスタごとに色分けできるよう NaN マスク列を用意。

再生成:  python tools/make_samples.py

依存は numpy のみ（sklearn 不要）。日本語ヘッダは utf-8-sig(BOM付き)で保存し、
本アプリ・Excel の双方で文字化けしないようにする。
"""
import os

import numpy as np

OUT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "サンプルデータ")


def _save(name, header, columns):
    """列（1次元配列のリスト）を CSV 保存する。長さは揃っている前提。"""
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, name)
    data = np.column_stack(columns)
    # BOM 付き UTF-8。NaN は "nan" として出力され、本アプリ側で欠測として扱われる。
    np.savetxt(path, data, delimiter=",", header=",".join(header),
               comments="", fmt="%.6g", encoding="utf-8-sig")
    print(f"生成: {os.path.relpath(path, os.path.dirname(OUT_DIR))}  {data.shape[0]}行 x {data.shape[1]}列")
    return path


def sine_cosine():
    """純粋な正弦波・余弦波（ノイズなし）。X=時間, Y=正弦波/余弦波。"""
    t = np.linspace(0.0, 1.0, 1000)          # 0〜1 秒
    freq = 2.0                                # 2 Hz → 2 周期
    sin = np.sin(2 * np.pi * freq * t)
    cos = np.cos(2 * np.pi * freq * t)
    _save("正弦波_余弦波.csv", ["時間[s]", "正弦波", "余弦波"], [t, sin, cos])


def helix():
    """3次元らせん。X=cos(t), Y=sin(t), Z=高さ(t)。3D 折れ線/散布図で回転確認。"""
    t = np.linspace(0.0, 6 * np.pi, 600)      # 3 周ぶん
    _save("らせん_3D.csv", ["媒介変数t", "X_cos", "Y_sin", "Z_高さ"],
          [t, np.cos(t), np.sin(t), t])


def pca_3d():
    """合成した4クラスタの高次元データを PCA で3次元へ落とし、3D散布図用に整形。

    列: PC1, PC2, PC3（全点。1色で雲全体を見る用）
        クラスタ1〜4（各クラスタの点だけ PC2、他は NaN。色分け表示用）

    使い方（本アプリ）: X軸=PC1, Z軸=PC3。
      - Y に PC2 をチェック → 雲全体を1色で 3D 散布図
      - Y に クラスタ1〜4 をチェック → クラスタごとに色分けした 3D 散布図
        （X=PC1・Z=PC3 は共有列。各クラスタ列は自分の点以外 NaN なので、
         系列ごとに自分のクラスタの点だけが残り、正しい位置に色分け表示される）
    """
    rng = np.random.default_rng(42)           # 再現性のため固定シード
    dim, n_clusters, per = 6, 4, 150
    centers = rng.normal(0.0, 6.0, size=(n_clusters, dim))   # よく離れた中心
    pts, labels = [], []
    for k in range(n_clusters):
        pts.append(centers[k] + rng.normal(0.0, 1.2, size=(per, dim)))
        labels.append(np.full(per, k))
    x = np.vstack(pts)
    labels = np.concatenate(labels)

    # PCA: 上位3主成分へ。scikit-learn があれば使い、無ければ numpy の SVD で計算。
    xc = x - x.mean(axis=0)
    try:
        from sklearn.decomposition import PCA
        model = PCA(n_components=3)
        scores = model.fit_transform(xc)
        var_ratio = model.explained_variance_ratio_
        backend = "scikit-learn"
    except Exception:
        _u, s, vt = np.linalg.svd(xc, full_matrices=False)
        scores = xc @ vt[:3].T                # (N, 3) = PC1, PC2, PC3
        var_ratio = (s[:3] ** 2) / np.sum(s ** 2)
        backend = "numpy"
    pc1, pc2, pc3 = scores[:, 0], scores[:, 1], scores[:, 2]

    header = ["PC1", "PC2", "PC3"]
    columns = [pc1, pc2, pc3]
    for k in range(n_clusters):               # クラスタ別 PC2（他クラスタは NaN）
        header.append(f"クラスタ{k + 1}")
        columns.append(np.where(labels == k, pc2, np.nan))

    _save("主成分分析_3D.csv", header, columns)
    print("  PC1〜3 の寄与率: " + ", ".join(f"{r * 100:.1f}%" for r in var_ratio))


def main():
    sine_cosine()
    helix()
    pca_3d()
    print("完了。本アプリの『データ』タブから サンプルデータ/ の各CSVを開いてください。")


if __name__ == "__main__":
    main()
