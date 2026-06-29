# -*- coding: utf-8 -*-
"""低レベル描画（各グラフ種別の _draw_*・近似曲線・間引き・オシロ格子）。"""
import warnings

import numpy as np
import pandas as pd

from plotter_format import _eng   # オシロ格子の s/div・V/div 表示で使用


DEFAULT_STYLE = {
    "color": None,        # None なら matplotlib の既定カラーサイクル
    "linestyle": "-",
    "linewidth": 1.5,
    "marker": "",
    "markersize": 4.0,
    "alpha": 1.0,
}


def style_for(series):
    s = dict(DEFAULT_STYLE)
    s.update(series.get("style") or {})
    return s


def _coerce_x(values):
    """X 軸の値を数値 / 日時 / カテゴリへ変換し (values, kind) を返す。"""
    s = pd.Series(values)
    num = pd.to_numeric(s, errors="coerce")
    if num.notna().mean() >= 0.8:
        return num.to_numpy(dtype=float), "numeric"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            dt = pd.to_datetime(s, errors="coerce")
        except Exception:
            dt = pd.Series([pd.NaT] * len(s))
    if dt.notna().mean() >= 0.8:
        return dt.to_numpy(), "datetime"
    return s.astype(str).to_numpy(), "category"


def _num(values):
    return pd.to_numeric(pd.Series(values), errors="coerce").to_numpy(dtype=float)


def fit_trendline(x, y, kind, degree=2, window=5):
    """近似曲線を計算する。

    戻り値: (xfit, yfit, equation, r2) または None
      equation は数式文字列、r2 は決定係数（移動平均は None）。
    """
    x = np.asarray(_num(x), dtype=float)
    y = np.asarray(_num(y), dtype=float)
    m = np.isfinite(x) & np.isfinite(y)
    x, y = x[m], y[m]
    if len(x) < 2:
        return None
    order = np.argsort(x)
    x, y = x[order], y[order]
    eq = ""
    try:
        if kind == "線形":
            c = np.polyfit(x, y, 1)
            yf = np.polyval(c, x)
            eq = f"y={c[0]:.4g}x{c[1]:+.4g}"
        elif kind == "多項式":
            deg = int(max(1, min(degree, 6)))
            if len(x) <= deg:
                return None
            c = np.polyfit(x, y, deg)
            yf = np.polyval(c, x)
            terms = [f"{cc:+.3g}x^{deg - i}" for i, cc in enumerate(c[:-1])]
            eq = "y=" + "".join(terms) + f"{c[-1]:+.3g}"
        elif kind == "指数":              # y = a*exp(b x)
            pos = y > 0
            if pos.sum() < 2:
                return None
            # log線形回帰で初期値 → scipy.optimize.curve_fit で非線形最小二乗に精密化。
            # （log線形だけだと小さいyを過大評価して偏るため。scipy無し時は初期値を使う）
            c = np.polyfit(x[pos], np.log(y[pos]), 1)
            a, b = float(np.exp(c[1])), float(c[0])
            try:
                from scipy.optimize import curve_fit
                (a, b), _ = curve_fit(lambda xx, A, B: A * np.exp(B * xx), x, y,
                                      p0=(a, b), maxfev=10000)
                a, b = float(a), float(b)
            except Exception:
                pass
            yf = a * np.exp(b * x)
            eq = f"y={a:.4g}·e^({b:.4g}x)"
        elif kind == "対数":              # y = a*ln(x) + b（x>0）
            pos = x > 0
            if pos.sum() < 2:
                return None
            x, y = x[pos], y[pos]
            c = np.polyfit(np.log(x), y, 1)
            yf = c[0] * np.log(x) + c[1]
            eq = f"y={c[0]:.4g}·ln(x){c[1]:+.4g}"
        elif kind == "移動平均":
            w = int(max(2, min(window, len(y))))
            kern = np.ones(w) / w
            yf = np.convolve(y, kern, mode="same")
            return x, yf, f"移動平均(窓={w})", None
        else:
            return None
    except Exception:
        return None
    ss_res = float(np.sum((y - yf) ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    r2 = (1 - ss_res / ss_tot) if ss_tot > 0 else None
    return x, yf, eq, r2


def _data_labels(ax, xx, yy, color, fontsize, cap=40, fmt="{:.3g}"):
    """各データ点に値ラベルを付ける（点数が多い場合は間引き）。"""
    xx = np.asarray(xx, dtype=float)
    yy = np.asarray(yy, dtype=float)
    n = len(yy)
    step = max(1, int(np.ceil(n / cap)))
    for i in range(0, n, step):
        if not (np.isfinite(xx[i]) and np.isfinite(yy[i])):
            continue
        ax.annotate(fmt.format(yy[i]), (xx[i], yy[i]),
                    textcoords="offset points", xytext=(0, 5),
                    ha="center", fontsize=max(7, fontsize - 1), color=color or "#333")


def _remove_twin(ax):
    """前回作った第2軸(twinx)を図から取り除く。"""
    ax2 = getattr(ax, "_twin_secondary", None)
    if ax2 is not None:
        try:
            ax2.remove()
        except Exception:
            pass
    ax._twin_secondary = None


def _bar_width(xx):
    """数値Xに棒を描くときの適切な幅。"""
    xx = np.asarray(xx, dtype=float)
    xx = xx[np.isfinite(xx)]
    if len(xx) < 2:
        return 0.8
    d = np.diff(np.sort(xx))
    d = d[d > 0]
    return float(np.min(d) * 0.8) if len(d) else 0.8


def _draw_xy(ax, series, line=True, max_points=0, ax2=None, data_labels=False,
             trendline=None, fonts=None):
    # 各系列の X を評価し、カテゴリがあれば全系列で共有する位置マッピングを作る
    # （系列ごとに目盛りラベルを上書きして取り違える不具合を防ぐ）。
    fonts = fonts or {}
    fs = fonts.get("tick", 9)
    prepared = []
    cat_order, cat_pos = [], {}
    for sr in series:
        x_raw = sr.get("x")
        y = _num(sr["y"])
        if x_raw is None:
            prepared.append(("index", None, y, sr))
            continue
        x, kind = _coerce_x(x_raw)
        if kind == "category":
            for lab in x:
                if lab not in cat_pos:
                    cat_pos[lab] = len(cat_order)
                    cat_order.append(lab)
        prepared.append((kind, x, y, sr))

    # 棒の本数（複合グラフで棒が複数あるとき横に並べる）
    bar_series = [sr for *_unused, sr in prepared
                  if (sr.get("kind") or "") == "bar"]
    n_bars = max(1, len(bar_series))
    bar_idx = 0
    any_decimated = False

    for kind, x, y, sr in prepared:
        st = style_for(sr)
        target = ax2 if (ax2 is not None and sr.get("axis") == "secondary") else ax
        skind = sr.get("kind") or ("line" if line else "scatter")
        yerr = sr.get("yerr")
        yerr = _num(yerr) if yerr is not None else None
        if kind == "index":
            xx = np.arange(len(y))
        elif kind == "category":
            xx = np.array([cat_pos[lab] for lab in x], dtype=float)
        else:
            xx = np.asarray(x, dtype=float)
        # 大容量データの間引き（カテゴリ以外・誤差バー無し・線/散布のみ）
        decim = (max_points and kind != "category" and yerr is None
                 and skind in ("line", "scatter") and len(y) > max_points)
        if decim:
            if skind == "line":
                xx, yv = decimate_minmax(xx, y, max_points)
            else:
                step = max(1, len(y) // max_points)
                xx, yv = np.asarray(xx)[::step], np.asarray(y)[::step]
            any_decimated = True
        else:
            yv = y

        if skind == "bar":
            w = _bar_width(xx) / n_bars
            off = (bar_idx - (n_bars - 1) / 2) * w
            bar_idx += 1
            target.bar(np.asarray(xx, float) + off, yv, width=w, label=sr["label"],
                       color=st["color"], alpha=min(st["alpha"], 0.85),
                       yerr=yerr if yerr is not None else None, capsize=3)
        elif skind == "area":
            target.fill_between(xx, yv, color=st["color"], alpha=min(st["alpha"], 0.4))
            target.plot(xx, yv, label=sr["label"], color=st["color"],
                        linewidth=st["linewidth"], alpha=st["alpha"])
        elif skind == "scatter":
            target.scatter(xx, yv, label=sr["label"], color=st["color"],
                           s=st["markersize"] ** 2, marker=st["marker"] or "o",
                           alpha=st["alpha"])
            if yerr is not None:
                target.errorbar(xx, yv, yerr=yerr[:len(yv)], fmt="none",
                                 ecolor=st["color"], alpha=st["alpha"], capsize=3)
        else:   # line
            if yerr is not None:
                target.errorbar(xx, yv, yerr=yerr[:len(yv)], label=sr["label"],
                                color=st["color"], linestyle=st["linestyle"],
                                linewidth=st["linewidth"], marker=st["marker"],
                                markersize=st["markersize"], alpha=st["alpha"], capsize=3)
            else:
                target.plot(xx, yv, label=sr["label"], color=st["color"],
                            linestyle=st["linestyle"], linewidth=st["linewidth"],
                            marker=st["marker"], markersize=st["markersize"],
                            alpha=st["alpha"])

        if data_labels:
            _data_labels(target, xx, yv, st["color"], fs)

        # --- 近似曲線（線/散布/面のみ。数値X限定）---
        if (trendline and trendline.get("type") not in (None, "なし")
                and kind in ("numeric", "index") and skind != "bar"):
            fit = fit_trendline(xx, yv, trendline["type"],
                                degree=trendline.get("degree", 2),
                                window=trendline.get("window", 5))
            if fit is not None:
                xf, yf, eq, r2 = fit
                lab = f"{sr['label']} 近似: {eq}"
                if r2 is not None and trendline.get("show_eq"):
                    lab += f"  (R²={r2:.4f})"
                elif not trendline.get("show_eq"):
                    lab = None
                tcolor = trendline.get("color") or st["color"] or "#444"
                target.plot(xf, yf, color=tcolor, linestyle="--",
                            linewidth=1.3, alpha=0.9, label=lab)

    if any_decimated:  # 間引きしたことを示す（軸ラベルは GUI 側で付与）
        ax._decimated = True

    if cat_order:
        ax.set_xticks(range(len(cat_order)))
        ax.set_xticklabels(cat_order, rotation=45 if len(cat_order) > 6 else 0,
                           ha="right" if len(cat_order) > 6 else "center")


def _draw_hist(ax, series, bins):
    data, labels, colors = [], [], []
    for sr in series:
        y = _num(sr["y"])
        y = y[~np.isnan(y)]
        if len(y):
            data.append(y)
            labels.append(sr["label"])
            colors.append(style_for(sr)["color"])
    if not data:
        raise ValueError("ヒストグラムに使える数値データがありません。")
    colors = colors if all(c for c in colors) else None
    ax.hist(data, bins=int(bins), alpha=0.6, label=labels, color=colors)


def _draw_box(ax, series):
    data, labels = [], []
    for sr in series:
        y = _num(sr["y"])
        y = y[~np.isnan(y)]
        if len(y):
            data.append(y)
            labels.append(sr["label"])
    if not data:
        raise ValueError("箱ひげ図に使える数値データがありません。")
    try:
        ax.boxplot(data, tick_labels=labels)
    except TypeError:
        ax.boxplot(data, labels=labels)


def _draw_bar(ax, series, categories, horizontal=False, stacked=False,
              data_labels=False, fonts=None):
    fs = (fonts or {}).get("tick", 9)
    labels = np.asarray([str(c) for c in categories])
    pos = np.arange(len(labels))
    data = [(sr["label"], _num(sr["y"]), style_for(sr)) for sr in series]

    def _label_bars(bars, vals):
        if not data_labels:
            return
        for b, v in zip(bars, vals):
            if not np.isfinite(v):
                continue
            if horizontal:
                ax.annotate(f"{v:.3g}", (b.get_width(), b.get_y() + b.get_height() / 2),
                            textcoords="offset points", xytext=(3, 0),
                            va="center", ha="left", fontsize=max(7, fs - 1))
            else:
                ax.annotate(f"{v:.3g}", (b.get_x() + b.get_width() / 2, b.get_height()),
                            textcoords="offset points", xytext=(0, 3),
                            va="bottom", ha="center", fontsize=max(7, fs - 1))

    if stacked or len(data) == 1:
        bottom = np.zeros(len(labels))
        for name, vals, st in data:
            vals = np.nan_to_num(vals[:len(labels)])
            if horizontal:
                bars = ax.barh(pos, vals, left=bottom, label=name, color=st["color"], alpha=st["alpha"])
            else:
                bars = ax.bar(pos, vals, bottom=bottom, label=name, color=st["color"], alpha=st["alpha"])
            if not stacked:
                _label_bars(bars, vals)
            bottom = bottom + vals
    else:
        n = len(data)
        width = 0.8 / n
        for i, (name, vals, st) in enumerate(data):
            vals = np.nan_to_num(vals[:len(labels)])
            off = (i - (n - 1) / 2) * width
            if horizontal:
                bars = ax.barh(pos + off, vals, height=width, label=name, color=st["color"], alpha=st["alpha"])
            else:
                bars = ax.bar(pos + off, vals, width=width, label=name, color=st["color"], alpha=st["alpha"])
            _label_bars(bars, vals)

    if horizontal:
        ax.set_yticks(pos)
        ax.set_yticklabels(labels)
    else:
        ax.set_xticks(pos)
        ax.set_xticklabels(labels, rotation=45 if len(labels) > 6 else 0,
                           ha="right" if len(labels) > 6 else "center")


def _draw_pie(ax, sr, categories, pct=False):
    labels = np.asarray([str(c) for c in categories])
    values = np.nan_to_num(_num(sr["y"]))
    n = min(len(labels), len(values))
    labels, values = labels[:n], values[:n]
    mask = values > 0
    labels, values = labels[mask], values[mask]
    if len(values) == 0:
        raise ValueError("円グラフに使える正の数値データがありません。")
    ax.pie(values, labels=labels, autopct="%1.1f%%" if pct else None,
           startangle=90, counterclock=False)
    ax.axis("equal")


def _is_dark(color):
    """色（名前/HEX）が暗いか（相対輝度<0.45）。目盛り色などの自動切替に使う。"""
    try:
        from matplotlib.colors import to_rgb
        r, g, b = to_rgb(color)
        return (0.299 * r + 0.587 * g + 0.114 * b) < 0.45
    except Exception:
        return True


def _apply_scope(ax, scope, bg_color=""):
    """オシロスコープ風の div グリッドと表示範囲を設定する。

    背景色は bg_color（空なら従来の濃色 #0b0f0b）。背景の明暗に応じて
    目盛り・グリッド・情報文字の色を自動で見やすく切り替える。
    """
    xd = int(scope.get("x_divs", 10))
    yd = int(scope.get("y_divs", 8))
    tpd = float(scope.get("t_per_div", 1.0))
    vpd = float(scope.get("v_per_div", 1.0))
    xc = float(scope.get("x_pos", 0.0))
    yc = float(scope.get("y_pos", 0.0))

    x0, x1 = xc - xd / 2 * tpd, xc + xd / 2 * tpd
    y0, y1 = yc - yd / 2 * vpd, yc + yd / 2 * vpd
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.set_xticks(np.linspace(x0, x1, xd + 1))
    ax.set_yticks(np.linspace(y0, y1, yd + 1))
    bg = bg_color or "#0b0f0b"
    dark = _is_dark(bg)
    ax.grid(True, which="major", color=("#888" if dark else "#aaa"),
            linestyle="-", linewidth=0.6, alpha=0.5)
    ax.set_facecolor(bg)
    ax.tick_params(colors=("#888" if dark else "#555"), labelsize=8)
    # スコープ情報（背景の明暗で文字/箱の色を切替）
    info_fg = "#7CFC00" if dark else "#0a7a30"
    info_bg = "black" if dark else "white"
    ax.text(0.01, 0.99, f"{_eng(tpd)}s/div   {_eng(vpd)}V/div",
            transform=ax.transAxes, va="top", ha="left",
            color=info_fg, fontsize=9,
            bbox=dict(facecolor=info_bg, alpha=0.4, edgecolor="none"))


def decimate_minmax(x, y, max_points):
    """点数が多い波形を min/max エンベロープで間引く（見た目を保ったまま高速化）。

    各ビンの最小値・最大値の点を時間順に残すので、波形の包絡が保たれる。
    等幅ビンを reshape して per-bin の最小/最大インデックスを numpy でベクトル化
    （旧 Python ループ比 約30倍高速）。端数は最後のビンに併合する。
    """
    x = np.asarray(x)
    y = np.asarray(y, dtype=float)
    n = len(y)
    if n <= max_points or max_points < 4:
        return x, y
    n_bins = max(1, max_points // 2)
    bin_size = n // n_bins
    if bin_size < 1:
        return x, y
    main = bin_size * n_bins
    Y = y[:main].reshape(n_bins, bin_size)
    starts = np.arange(n_bins) * bin_size
    if np.isfinite(Y).all():   # NaN/inf 無し（一般ケース）は素の argmin/argmax で最速
        lo = starts + np.argmin(Y, axis=1)
        hi = starts + np.argmax(Y, axis=1)
    else:                      # NaN/inf は finite 優先で除外（全NaN行は先頭=0）
        lo = starts + np.argmin(np.where(np.isfinite(Y), Y, np.inf), axis=1)
        hi = starts + np.argmax(np.where(np.isfinite(Y), Y, -np.inf), axis=1)
    if main < n:   # 末尾の端数は最後のビンに併合して取り直す
        base = int(starts[-1])
        seg = y[base:n]
        fin = np.isfinite(seg)
        lo[-1] = base + int(np.argmin(np.where(fin, seg, np.inf)))
        hi[-1] = base + int(np.argmax(np.where(fin, seg, -np.inf)))
    first = np.minimum(lo, hi)     # 時間順（先のインデックス→後のインデックス）
    second = np.maximum(lo, hi)
    idx = np.empty(2 * n_bins, dtype=np.int64)
    idx[0::2] = first
    idx[1::2] = second
    return x[idx], y[idx]
