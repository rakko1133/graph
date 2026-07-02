# -*- coding: utf-8 -*-
"""データサイエンス系の計算（GUI から独立）。

線形回帰（線形性）・記述統計・相関・正規性検定など、データ解析でよく使う指標を計算する。
scipy があればそれを使い、無くても numpy だけで主要な指標を返せるようフォールバックする。
入力は 1 次元配列（x, y）。NaN/inf は自動で除外する。
"""
import numpy as np


def _clean_xy(x, y):
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    n = min(x.size, y.size)
    x, y = x[:n], y[:n]
    m = np.isfinite(x) & np.isfinite(y)
    return x[m], y[m]


def _clean(y):
    y = np.asarray(y, dtype=float)
    return y[np.isfinite(y)]


def linear_regression(x, y):
    """最小二乗の直線当てはめ。線形性（R²・相関 r）と直線性誤差を返す。

    戻り dict のキー:
      n, slope(傾き), intercept(切片), r(ピアソン相関), r2(決定係数),
      p_value(傾き=0 の検定。scipy 時のみ), std_err(傾きの標準誤差。scipy 時のみ),
      rmse(残差二乗平均平方根), linearity_error_pct(最大残差/Yの全幅×100[%FS])
    """
    x, y = _clean_xy(x, y)
    n = int(x.size)
    if n < 2:
        return {}
    slope = intercept = rval = pval = stderr = None
    try:
        from scipy import stats
        res = stats.linregress(x, y)
        slope, intercept = float(res.slope), float(res.intercept)
        rval, pval, stderr = float(res.rvalue), float(res.pvalue), float(res.stderr)
    except Exception:
        slope, intercept = (float(v) for v in np.polyfit(x, y, 1))
    yhat = slope * x + intercept
    resid = y - yhat
    ss_res = float(np.sum(resid ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    r2 = (1.0 - ss_res / ss_tot) if ss_tot > 0 else None
    if rval is None:
        rval = (float(np.sign(slope) * np.sqrt(r2)) if (r2 is not None and r2 >= 0) else None)
    rmse = float(np.sqrt(np.mean(resid ** 2)))
    yspan = float(np.max(y) - np.min(y))
    inl_pct = float(np.max(np.abs(resid)) / yspan * 100.0) if yspan > 0 else None
    return {
        "n": n, "slope": slope, "intercept": intercept,
        "r": rval, "r2": r2, "p_value": pval, "std_err": stderr,
        "rmse": rmse, "linearity_error_pct": inl_pct,
    }


def describe(y):
    """記述統計。count/mean/median/std/var/min/max/range/CV/歪度/尖度/四分位 など。"""
    y = _clean(y)
    if y.size == 0:
        return {}
    n = int(y.size)
    mean = float(np.mean(y))
    std = float(np.std(y, ddof=1)) if n > 1 else 0.0
    p25, p50, p75 = (float(np.percentile(y, q)) for q in (25, 50, 75))
    d = {
        "count": n, "mean": mean, "median": float(np.median(y)),
        "std": std, "var": float(np.var(y, ddof=1)) if n > 1 else 0.0,
        "min": float(np.min(y)), "max": float(np.max(y)),
        "range": float(np.max(y) - np.min(y)),
        "cv": (float(std / mean) if mean != 0 else None),
        "p25": p25, "p50": p50, "p75": p75, "iqr": p75 - p25,
    }
    try:
        from scipy import stats
        if std > 0:                                # 定数データは scipy が nan を返すため除外
            d["skew"] = float(stats.skew(y))
            d["kurtosis"] = float(stats.kurtosis(y))   # 過剰尖度（正規分布=0）
        else:
            d["skew"] = 0.0
            d["kurtosis"] = 0.0
    except Exception:
        if std > 0:
            z = (y - mean) / std
            d["skew"] = float(np.mean(z ** 3))
            d["kurtosis"] = float(np.mean(z ** 4) - 3.0)
        else:
            d["skew"] = 0.0
            d["kurtosis"] = 0.0
    return d


def correlation(x, y, method="pearson"):
    """2系列の相関係数と p 値（scipy 時）。method: 'pearson' | 'spearman'。"""
    x, y = _clean_xy(x, y)
    if x.size < 2:
        return None
    try:
        from scipy import stats
        if method == "spearman":
            r, p = stats.spearmanr(x, y)
        else:
            r, p = stats.pearsonr(x, y)
        return {"r": float(r), "p_value": float(p)}
    except Exception:
        return {"r": float(np.corrcoef(x, y)[0, 1]), "p_value": None}


def correlation_matrix(named_series, method="pearson"):
    """複数系列の相関行列。named_series: [(名前, y配列), ...]。

    各系列を共通長に切り、全系列で有限な点だけを使って相関行列を計算する。
    戻り値: (names, matrix[ndarray])。系列が2未満や有効点不足なら (names, None)。
    """
    names = [str(nm) for nm, _ in named_series]
    arrs = [np.asarray(a, dtype=float) for _, a in named_series]
    if len(arrs) < 2:
        return names, None
    L = min(a.size for a in arrs)
    if L < 2:
        return names, None
    M = np.vstack([a[:L] for a in arrs])
    mask = np.all(np.isfinite(M), axis=0)
    M = M[:, mask]
    if M.shape[1] < 2:
        return names, None
    try:
        if method == "spearman":
            from scipy import stats
            mat, _ = stats.spearmanr(M, axis=1)
            mat = np.atleast_2d(np.asarray(mat, dtype=float))
            if mat.shape != (len(arrs), len(arrs)):   # 2系列時は scalar を 2x2 へ
                r = float(mat.ravel()[0])             # scipy が返した Spearman 値を使う
                mat = np.array([[1.0, r], [r, 1.0]])  # （np.corrcoef は Pearson なので不可）
        else:
            mat = np.corrcoef(M)
    except Exception:
        mat = np.corrcoef(M)
    return names, np.asarray(mat, dtype=float)


def pca(named_series, n_components=3, standardize=True):
    """複数系列（特徴量）に主成分分析（PCA）を行う。

    named_series : [(名前, y配列), ...]  各系列を1つの特徴量、行=サンプルとして扱う。
    n_components : 取り出す主成分の数（特徴量数・サンプル数で自動的に上限を丸める）。
    standardize  : True なら各特徴量を平均0・分散1に標準化してから分析（単位が違う
                   特徴量の混在に有効）。False は中心化のみ（sklearn 既定と同じ）。

    scikit-learn があればそれを使い、無ければ numpy の SVD で同等の結果を返す。
    戻り dict:
      n_components, n_samples, features(名前list), backend("scikit-learn"/"numpy"),
      scores([(name, array)], PC1.. の各列), explained_ratio(各PCの寄与率list)
    計算できないときは None。
    """
    names = [str(nm) for nm, _ in named_series]
    arrs = [np.asarray(a, dtype=float) for _, a in named_series]
    if len(arrs) < 2:
        return None
    length = min(a.size for a in arrs)
    if length < 3:
        return None
    x = np.column_stack([a[:length] for a in arrs])       # (サンプル, 特徴量)
    x = x[np.all(np.isfinite(x), axis=1)]                  # 欠測を含む行は除外
    n_samples, n_features = x.shape
    if n_samples < 2 or n_features < 2:
        return None
    k = int(max(1, min(int(n_components), n_features, n_samples)))

    xc = x - x.mean(axis=0)                                # 中心化
    if standardize:
        std = xc.std(axis=0, ddof=0)
        std[std == 0] = 1.0                                # 定数列は割らない
        xc = xc / std

    backend = "numpy"
    try:
        from sklearn.decomposition import PCA as _PCA      # あれば scikit-learn を使う
        model = _PCA(n_components=k)
        scores = model.fit_transform(xc)
        ratio = np.asarray(model.explained_variance_ratio_, dtype=float)
        backend = "scikit-learn"
    except Exception:
        # フォールバック: numpy の SVD（sklearn の PCA と数学的に同等）
        _u, s, _vt = np.linalg.svd(xc, full_matrices=False)
        scores = _u[:, :k] * s[:k]
        total = float(np.sum(s ** 2))
        ratio = (s[:k] ** 2 / total) if total else np.zeros(k)

    return {
        "n_components": k,
        "n_samples": int(n_samples),
        "features": names,
        "backend": backend,
        "scores": [(f"PC{i + 1}", scores[:, i]) for i in range(k)],
        "explained_ratio": [float(r) for r in np.asarray(ratio).ravel()[:k]],
    }


def normality(y):
    """Shapiro-Wilk 正規性検定（scipy 必須）。W 統計量・p 値・5%有意で正規かを返す。
    scipy が無ければ空 dict。"""
    y = _clean(y)
    if y.size < 3:
        return {}
    try:
        from scipy import stats
        w, p = stats.shapiro(y[:5000])   # shapiro は大標本で重いため上限を設ける
        return {"W": float(w), "p_value": float(p), "normal_5pct": bool(p > 0.05)}
    except Exception:
        return {}
