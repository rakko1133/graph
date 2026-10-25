# -*- coding: utf-8 -*-
"""保存した設定（``_collect_config`` 形式の dict）から、グラフを再現する
Python コードを生成する。

- ``generate_python(config)`` → 単体で動く ``.py`` スクリプト（文字列）
- ``generate_notebook(config)`` → Jupyter ``.ipynb``（dict。json.dump で保存可）
- ``export_code(config, path)`` → 拡張子（.py / .ipynb）で振り分けて書き出す

**方針（self-contained）**: 生成コードは ``pandas`` と ``matplotlib`` だけで動く。
本ツールのモジュール（plotter / data_loader 等）には依存しない。``series_styles`` には
すでに matplotlib 値（``"-"`` / ``"o"`` 等）が入っているため、線種・マーカーの変換は不要。

対応するグラフ種別（レポート系の主要種別）:
    折れ線 / 散布図 / 面 / ステップ / ステム / 棒 / 横棒 / 積み上げ棒 /
    ヒストグラム / 箱ひげ / バイオリン / 円 / ドーナツ / ヒートマップ /
    2Dヒストグラム / hexbin

再現対象外（生成コードにコメントで明記し、可能なら折れ線で代替）:
    3D 表示 / 曲面 / オシロスコープ表示 / FFT・スペクトル / 高度解析 / 数学チャンネル
"""
import datetime
import json
import os

__all__ = ["generate_python", "generate_notebook", "export_code"]


# グラフ種別の分類
_XY = ("折れ線", "散布図", "面", "ステップ", "ステム")
_XY_DEFAULT_KIND = {"折れ線": "line", "散布図": "scatter", "面": "area",
                    "ステップ": "step", "ステム": "stem"}
_BAR = ("棒", "横棒", "積み上げ棒")
_DIST = ("ヒストグラム", "箱ひげ", "バイオリン")
_PIE = ("円", "ドーナツ")
_PAIR = ("2Dヒストグラム", "hexbin")       # X・Y を1本ずつ使う
_HEAT = ("ヒートマップ",)
# 生成コードで再現しない種別（コメントで案内し、折れ線で代替表示）
_UNSUPPORTED = ("曲面",)


# ----------------------------------------------------------------------------- 小道具
def _lit(v):
    """Python リテラル表現（repr）。パス・ラベルの安全な埋め込みに使う。"""
    return repr(v)


def _num(text, default=None):
    """文字列を float へ。空・非数値は default。"""
    try:
        s = str(text).strip()
    except Exception:
        return default
    if s == "":
        return default
    try:
        return float(s)
    except ValueError:
        return default


def _scale_factor(spec):
    """倍率指定（数値のみ対応）。式・空・1 は None（＝変換なし）。"""
    if spec is None:
        return None
    if isinstance(spec, (int, float)):
        return None if float(spec) == 1.0 else float(spec)
    f = _num(spec, None)
    if f is None or f == 1.0:
        return None
    return f


def _file_meta(config):
    """label -> {path, enc, delim, sheet}。file_meta が無ければ files から推定。"""
    fm = config.get("file_meta")
    if isinstance(fm, dict) and fm:
        return {k: dict(v or {}) for k, v in fm.items()}
    out = {}
    for p in config.get("files", []) or []:
        if isinstance(p, str):
            out[os.path.basename(p)] = {"path": p, "enc": None, "delim": None, "sheet": None}
    return out


def _referenced_labels(config):
    """selected_y に現れるファイルラベルを出現順（重複除去）で返す。"""
    seen, out = set(), []
    for pair in config.get("selected_y", []) or []:
        if isinstance(pair, (list, tuple)) and len(pair) == 2:
            fl = pair[0]
            if fl not in seen:
                seen.add(fl)
                out.append(fl)
    return out


def _style_of(config, fl, col):
    styles = config.get("styles", {}) or {}
    return dict(styles.get(f"{fl}\t{col}") or {})


def _series_rows(config):
    """selected_y と styles から、描画系列の情報を組み立てる。

    返り値: [{file, ycol, xcol, label, color, linestyle, linewidth, marker,
              markersize, alpha, axis, kind}, ...]
    xcol が None のときは「各ファイルの最左列」を X にする。
    """
    sel = [(p[0], p[1]) for p in (config.get("selected_y", []) or [])
           if isinstance(p, (list, tuple)) and len(p) == 2]
    if config.get("x_leftmost"):
        xcols = [None]
    elif config.get("multi_x") and config.get("x_cols"):
        xcols = list(config["x_cols"])
    else:
        xcols = [config.get("x_col") or None]
    multi = len(xcols) > 1

    rows = []
    for fl, col in sel:
        st = _style_of(config, fl, col)
        base_label = st.get("label") or col
        for xc in xcols:
            label = base_label if not multi else f"{base_label} [X:{xc if xc else '最左列'}]"
            color = st.get("color") or ""
            # 複数Xのとき色指定があると各変種が同色になるので自動色に任せる
            if multi and color:
                color = ""
            rows.append({
                "file": fl, "ycol": col, "xcol": xc, "label": label,
                "color": color,
                "linestyle": st.get("linestyle", "-"),
                "linewidth": float(st.get("linewidth", 1.5) or 1.5),
                "marker": st.get("marker", "") or "",
                "markersize": float(st.get("markersize", 4.0) or 4.0),
                "alpha": float(st.get("alpha", 1.0) or 1.0),
                "axis": st.get("axis", "primary"),
                "kind": st.get("kind", "") or "",
            })
    return rows


def _axis_label(label, unit):
    label = label or ""
    unit = (unit or "").strip()
    if unit:
        return f"{label} [{unit}]" if label else f"[{unit}]"
    return label


def _figsize(config):
    aspect = str(config.get("aspect", ""))
    aw = config.get("aspect_w", 16) or 16
    ah = config.get("aspect_h", 9) or 9
    if "自動" in aspect or aw <= 0 or ah <= 0:
        return (8.0, 5.0)
    return (8.0, round(8.0 * ah / aw, 2))


# ----------------------------------------------------------------------------- 生成: 定型部
_HEADER = '''# -*- coding: utf-8 -*-
"""自動生成スクリプト — 保存したグラフ設定を再現します。

生成日時: {now}
生成元  : CSV/TSV/波形 グラフ・オシロ解析ツール（設定からのコード出力）

使い方:
    python "{fname}"              # ウィンドウに表示
    python "{fname}" out.png      # 画像として保存（拡張子で形式を指定）
"""
'''

_IMPORTS = '''import sys

import numpy as np
import pandas as pd
import matplotlib
import matplotlib.pyplot as plt

# 日本語フォント（環境にあれば使用。無くても描画は可能）
for _f in ("Meiryo", "Yu Gothic", "MS Gothic", "Hiragino Sans",
           "Noto Sans CJK JP", "IPAexGothic", "TakaoGothic"):
    try:
        matplotlib.rcParams["font.family"] = _f
        break
    except Exception:
        pass
matplotlib.rcParams["axes.unicode_minus"] = False
'''

_LOADER = '''def load_table(path, encoding=None, sep=None, sheet=None):
    """本ツールに近い簡易ローダ（CSV/TSV/Excel）。enc/sep が分かっていればそれを使う。"""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".xlsx", ".xlsm", ".xls"):
        return pd.read_excel(path, sheet_name=sheet if sheet is not None else 0)
    if encoding and sep is not None:
        return pd.read_csv(path, encoding=encoding, sep=sep)
    # enc/sep 不明時は推定（utf-8-sig → cp932 の順、区切りは自動）
    for enc in ([encoding] if encoding else []) + ["utf-8-sig", "utf-8", "cp932", "shift_jis"]:
        try:
            return pd.read_csv(path, encoding=enc, sep=sep,
                               engine="python" if sep is None else "c")
        except Exception:
            continue
    return pd.read_csv(path, sep=sep, engine="python")
'''

_HELPERS = '''def _num(series):
    return pd.to_numeric(pd.Series(series), errors="coerce").to_numpy(dtype=float)


def _trend(x, y, kind, degree, window):
    """近似曲線 (xf, yf) を返す。対応: 線形/多項式/指数/対数/移動平均。"""
    xv, yv = _num(x), _num(y)
    m = np.isfinite(xv) & np.isfinite(yv)
    xv, yv = xv[m], yv[m]
    if len(xv) < 2:
        return None, None
    order = np.argsort(xv)
    xs, ys = xv[order], yv[order]
    try:
        if kind == "線形":
            a, b = np.polyfit(xs, ys, 1)
            return xs, a * xs + b
        if kind == "多項式":
            c = np.polyfit(xs, ys, max(1, int(degree)))
            return xs, np.polyval(c, xs)
        if kind == "指数" and np.all(ys > 0):
            b, la = np.polyfit(xs, np.log(ys), 1)
            return xs, np.exp(la) * np.exp(b * xs)
        if kind == "対数" and np.all(xs > 0):
            a, b = np.polyfit(np.log(xs), ys, 1)
            return xs, a * np.log(xs) + b
        if kind == "移動平均":
            w = max(2, int(window))
            yf = pd.Series(ys).rolling(w, min_periods=1, center=True).mean().to_numpy()
            return xs, yf
    except Exception:
        return None, None
    return None, None


def _plot_one(ax, x, y, kind, label, color, linestyle, linewidth, marker, markersize, alpha):
    """1 系列を kind に応じて描く（複合グラフの per-series kind に対応）。"""
    c = color or None
    if kind == "scatter":
        ax.scatter(x, y, label=label, color=c, marker=marker or "o",
                   s=(markersize or 4.0) ** 2, alpha=alpha)
    elif kind == "area":
        line, = ax.plot(x, y, label=label, color=c, linestyle=linestyle,
                        linewidth=linewidth, marker=marker, markersize=markersize, alpha=alpha)
        ax.fill_between(_num(x), _num(y), alpha=min(alpha, 0.3), color=line.get_color())
    elif kind == "step":
        ax.step(x, y, where="post", label=label, color=c, linestyle=linestyle,
                linewidth=linewidth, alpha=alpha)
    elif kind == "stem":
        ax.stem(_num(x), _num(y), label=label)
    else:  # line
        ax.plot(x, y, label=label, color=c, linestyle=linestyle, linewidth=linewidth,
                marker=marker, markersize=markersize, alpha=alpha)
'''


# ----------------------------------------------------------------------------- 生成: データ部
def _data_source(config):
    fm = _file_meta(config)
    labels = _referenced_labels(config)
    if not labels:                       # 参照が無ければ全ファイルを読む
        labels = list(fm.keys())
    lines = ["# --- データ読み込み ---", "data = {}"]
    for lbl in labels:
        meta = fm.get(lbl, {})
        path = meta.get("path", "")
        if not path:
            lines.append(f"# {lbl}: パスが不明のため読み込みをスキップ")
            continue
        enc = meta.get("enc")
        sep = meta.get("delim")
        sheet = meta.get("sheet")
        lines.append(
            f"data[{_lit(lbl)}] = load_table({_lit(path)}, "
            f"encoding={_lit(enc)}, sep={_lit(sep)}, sheet={_lit(sheet)})")
    return "\n".join(lines)


# ----------------------------------------------------------------------------- 生成: 描画部
def _common_format_lines(config, has_secondary, is_pie):
    """軸・凡例・グリッド等の共通書式コード行を返す（ax / ax2 を操作）。"""
    f = config.get("fonts", {}) or {}
    title_fs = f.get("title", 12)
    label_fs = f.get("label", 10)
    tick_fs = f.get("tick", 9)
    legend_fs = f.get("legend", 9)
    out = []
    title = config.get("title", "")
    if title:
        out.append(f"ax.set_title({_lit(title)}, fontsize={title_fs})")
    if is_pie:
        if bool(config.get("legend", True)):
            out.append(f"ax.legend(loc={_lit(config.get('legend_loc', 'best'))}, fontsize={legend_fs})")
        return out

    out.append(f"ax.set_xlabel({_lit(_axis_label(config.get('xlabel', ''), config.get('xunit', '')))}, fontsize={label_fs})")
    out.append(f"ax.set_ylabel({_lit(_axis_label(config.get('ylabel', ''), config.get('yunit', '')))}, fontsize={label_fs})")
    out.append(f"ax.tick_params(labelsize={tick_fs})")

    xlo, xhi = _num(config.get("xmin")), _num(config.get("xmax"))
    if xlo is not None or xhi is not None:
        out.append(f"ax.set_xlim(left={xlo!r}, right={xhi!r})")
    ylo, yhi = _num(config.get("ymin")), _num(config.get("ymax"))
    if ylo is not None or yhi is not None:
        out.append(f"ax.set_ylim(bottom={ylo!r}, top={yhi!r})")

    if config.get("xlog"):
        out.append("ax.set_xscale('log')")
    if config.get("ylog"):
        out.append("ax.set_yscale('log')")
    if config.get("xinvert"):
        out.append("ax.invert_xaxis()")
    if config.get("yinvert"):
        out.append("ax.invert_yaxis()")

    gw = config.get("grid_width")
    if bool(config.get("grid", True)):
        gkw = "" if gw in (None, "") else f", linewidth={gw}"
        out.append(f"ax.grid(True{gkw})")
    else:
        out.append("ax.grid(False)")

    fw = config.get("frame_width")
    if fw not in (None, ""):
        out.append(f"for _sp in ax.spines.values():\n    _sp.set_linewidth({fw})")

    bg = config.get("bg_color")
    if bg:
        out.append(f"ax.set_facecolor({_lit(bg)})")

    if bool(config.get("legend", True)):
        loc = _lit(config.get("legend_loc", "best"))
        if has_secondary:
            sec_lbl = _lit(config.get("_secondary_label", "第2軸"))
            out.append(f"ax2.set_ylabel({sec_lbl}, fontsize={label_fs})")
            out.append("_h1, _l1 = ax.get_legend_handles_labels()")
            out.append("_h2, _l2 = ax2.get_legend_handles_labels()")
            out.append(f"if _h1 + _h2:\n    ax.legend(_h1 + _h2, _l1 + _l2, loc={loc}, fontsize={legend_fs})")
        else:
            out.append("_h, _l = ax.get_legend_handles_labels()")
            out.append(f"if _h:\n    ax.legend(loc={loc}, fontsize={legend_fs})")
    return out


def _indent(lines, n=4):
    pad = " " * n
    out = []
    for ln in lines:
        out.extend((pad + part) if part else "" for part in ln.split("\n"))
    return out


def _plot_body(config):
    """build_figure() の本体コード行（インデント前）を組み立てる。"""
    ct = config.get("chart_type", "折れ線")
    rows = _series_rows(config)
    W, H = _figsize(config)
    annot_fs = (config.get("fonts", {}) or {}).get("annot", 9)
    xscale = _scale_factor(config.get("xscale"))
    yscale = _scale_factor(config.get("yscale"))

    body = []
    note = []

    # 再現対象外の表示モードは案内を出し、折れ線で代替する
    threed = bool(config.get("threed"))
    scope_on = bool((config.get("scope") or {}).get("enabled"))
    draw_ct = ct
    if threed or ct in _UNSUPPORTED:
        note.append(f"# 注意: 『{'3D表示' if threed else ct}』は再現コードでは未対応です。2Dの折れ線で代替表示します。")
        draw_ct = "折れ線"
    elif scope_on and ct in ("折れ線", "散布図"):
        note.append("# 注意: オシロスコープ表示(time/div・V/div)は再現対象外です。通常の軸で表示します。")

    body.append(f"fig, ax = plt.subplots(figsize=({W}, {H}))")

    has_secondary = draw_ct in _XY and any(r["axis"] == "secondary" for r in rows)
    if has_secondary:
        body.append("ax2 = ax.twinx()")
        sec = [r["label"] for r in rows if r["axis"] == "secondary"]
        config = dict(config, _secondary_label=" / ".join(sec) or "第2軸")

    body.append(f"series = {_series_literal(rows)}")

    sx = f"{xscale}" if xscale is not None else "None"
    sy = f"{yscale}" if yscale is not None else "None"

    if draw_ct in _XY or draw_ct in _PAIR:
        default_kind = _XY_DEFAULT_KIND.get(draw_ct, "line")
        trend = config.get("trend", "なし")
        do_trend = (draw_ct in ("折れ線", "散布図")
                    and trend in ("線形", "多項式", "指数", "対数", "移動平均"))
        data_labels = bool(config.get("data_labels")) and draw_ct in ("折れ線", "散布図")
        if draw_ct in _PAIR:
            note.append(f"# 『{draw_ct}』は最初の系列の X・Y を使って描きます。")
        body.append("for s in series:")
        body.append("    df = data.get(s['file'])")
        body.append("    if df is None or s['ycol'] not in df.columns:")
        body.append("        continue")
        body.append("    x = df.iloc[:, 0] if s['xcol'] is None else df[s['xcol']]")
        body.append("    y = pd.to_numeric(df[s['ycol']], errors='coerce')")
        body.append(f"    _sx, _sy = {sx}, {sy}")
        body.append("    if _sx is not None:\n        x = _num(x) * _sx")
        body.append("    if _sy is not None and s['axis'] != 'secondary':\n        y = _num(y) * _sy")
        if draw_ct in _PAIR:
            if draw_ct == "2Dヒストグラム":
                body.append(f"    ax.hist2d(_num(x), _num(y), bins={config.get('bins', 30)})")
            else:
                body.append(f"    ax.hexbin(_num(x), _num(y), gridsize={config.get('bins', 30)})")
            body.append("    break")
        else:
            body.append(f"    kind = s['kind'] or {_lit(default_kind)}")
            body.append("    tgt = ax2 if (s['axis'] == 'secondary' and 'ax2' in dir()) else ax")
            body.append("    _plot_one(tgt, x, y, kind, s['label'], s['color'], s['linestyle'],"
                        " s['linewidth'], s['marker'], s['markersize'], s['alpha'])")
            if do_trend:
                body.append(f"    _xf, _yf = _trend(x, y, {_lit(trend)}, {config.get('trend_degree', 2)}, {config.get('trend_window', 5)})")
                tcolor = config.get("trend_color") or ""
                body.append(f"    if _xf is not None:\n        tgt.plot(_xf, _yf, linestyle='--', linewidth=1.2, color={_lit(tcolor) if tcolor else 'None'})")
            if data_labels:
                body.append("    _xx, _yy = _num(x), _num(y)")
                body.append("    if _xx.size <= 200:")
                body.append(f"        for _px, _py in zip(_xx, _yy):\n            ax.annotate(f'{{_py:g}}', (_px, _py), fontsize={annot_fs})")

    elif draw_ct in _BAR:
        note.append("# 棒グラフは最初に選んだファイルのカテゴリ列（X軸）を使います。")
        body.append("labels, groups = _bar_data(data, series, %s, %s)" % (_lit(config.get("x_col") or ""), str(bool(config.get("x_leftmost")))))
        body.append("xpos = np.arange(len(labels))")
        body.append("n = max(1, len(groups))")
        if draw_ct == "積み上げ棒":
            body.append("bottom = np.zeros(len(labels))")
            body.append("for lab, yv, color in groups:")
            body.append("    ax.bar(xpos, yv, bottom=bottom, label=lab, color=color or None)")
            body.append("    bottom = bottom + np.nan_to_num(yv)")
            body.append("ax.set_xticks(xpos)\nax.set_xticklabels(labels, rotation=30, ha='right')")
        elif draw_ct == "横棒":
            body.append("width = 0.8 / n")
            body.append("for i, (lab, yv, color) in enumerate(groups):")
            body.append("    ax.barh(xpos + i * width, yv, width, label=lab, color=color or None)")
            body.append("ax.set_yticks(xpos + width * (n - 1) / 2)\nax.set_yticklabels(labels)")
        else:  # 棒
            body.append("width = 0.8 / n")
            body.append("for i, (lab, yv, color) in enumerate(groups):")
            body.append("    ax.bar(xpos + i * width, yv, width, label=lab, color=color or None)")
            body.append("ax.set_xticks(xpos + width * (n - 1) / 2)\nax.set_xticklabels(labels, rotation=30, ha='right')")

    elif draw_ct in _DIST:
        body.append("arrays, labels = [], []")
        body.append("for s in series:")
        body.append("    df = data.get(s['file'])")
        body.append("    if df is None or s['ycol'] not in df.columns:\n        continue")
        body.append("    arrays.append(_num(df[s['ycol']]))\n    labels.append(s['label'])")
        if draw_ct == "ヒストグラム":
            dens = "True" if config.get("pct") else "False"
            body.append(f"ax.hist([a[np.isfinite(a)] for a in arrays], bins={config.get('bins', 30)}, label=labels, density={dens})")
        elif draw_ct == "バイオリン":
            body.append("ax.violinplot([a[np.isfinite(a)] for a in arrays], showmeans=True)")
            body.append("ax.set_xticks(np.arange(1, len(labels) + 1))\nax.set_xticklabels(labels, rotation=30, ha='right')")
        else:  # 箱ひげ（matplotlib の版差を避け、目盛りラベルは後から設定）
            body.append("ax.boxplot([a[np.isfinite(a)] for a in arrays])")
            body.append("ax.set_xticks(np.arange(1, len(labels) + 1))\nax.set_xticklabels(labels, rotation=30, ha='right')")

    elif draw_ct in _PIE:
        note.append("# 円/ドーナツは最初の系列の値とカテゴリ列（X軸）を使います。")
        body.append("labels, values = _pie_data(data, series, %s, %s)" % (_lit(config.get("x_col") or ""), str(bool(config.get("x_leftmost")))))
        if draw_ct == "ドーナツ":
            body.append("ax.pie(values, labels=labels, wedgeprops=dict(width=0.4))")
        else:
            body.append("ax.pie(values, labels=labels, autopct='%1.1f%%')")
        body.append("ax.set_aspect('equal')")

    elif draw_ct in _HEAT:
        body.append("rows_, labels = [], []")
        body.append("for s in series:")
        body.append("    df = data.get(s['file'])")
        body.append("    if df is None or s['ycol'] not in df.columns:\n        continue")
        body.append("    rows_.append(_num(df[s['ycol']]))\n    labels.append(s['label'])")
        body.append("if rows_:")
        body.append("    _w = min(len(r) for r in rows_)")
        body.append("    _mat = np.array([r[:_w] for r in rows_])")
        body.append("    _im = ax.imshow(_mat, aspect='auto', cmap='viridis')")
        body.append("    ax.set_yticks(np.arange(len(labels)))\n    ax.set_yticklabels(labels)")
        body.append("    fig.colorbar(_im, ax=ax)")

    else:
        note.append(f"# 『{ct}』は再現コードでは未対応です。折れ線で代替表示します。")
        body.append("for s in series:")
        body.append("    df = data.get(s['file'])")
        body.append("    if df is None or s['ycol'] not in df.columns:\n        continue")
        body.append("    x = df.iloc[:, 0] if s['xcol'] is None else df[s['xcol']]")
        body.append("    ax.plot(x, pd.to_numeric(df[s['ycol']], errors='coerce'), label=s['label'])")

    is_pie = draw_ct in _PIE
    body += _common_format_lines(config, has_secondary, is_pie)
    body.append("fig.tight_layout()")
    body.append("return fig")
    return note, body


def _series_literal(rows):
    """系列情報を Python のリスト literal 文字列にする。"""
    parts = []
    for r in rows:
        parts.append(
            "{" + ", ".join(
                f"{_lit(k)}: {_lit(r[k])}" for k in
                ("file", "ycol", "xcol", "label", "color", "linestyle",
                 "linewidth", "marker", "markersize", "alpha", "axis", "kind")
            ) + "}")
    return "[\n    " + ",\n    ".join(parts) + ",\n]" if parts else "[]"


_BAR_PIE_HELPERS = '''def _bar_data(data, series, xcol, leftmost):
    """棒グラフ用: 最初の系列のファイルからカテゴリと (label, y, color) 群を作る。"""
    if not series:
        return [], []
    src = series[0]["file"]
    df = data.get(src)
    if df is None:
        return [], []
    cats = (df.iloc[:, 0] if (leftmost or not xcol or xcol not in df.columns)
            else df[xcol]).astype(str).tolist()
    groups = []
    for s in series:
        if s["file"] != src or s["ycol"] not in df.columns:
            continue
        groups.append((s["label"], _num(df[s["ycol"]]), s["color"]))
    return cats, groups


def _pie_data(data, series, xcol, leftmost):
    """円グラフ用: 最初の系列の値と、カテゴリ列のラベルを返す。"""
    if not series:
        return [], []
    s = series[0]
    df = data.get(s["file"])
    if df is None or s["ycol"] not in df.columns:
        return [], []
    labels = (df.iloc[:, 0] if (leftmost or not xcol or xcol not in df.columns)
              else df[xcol]).astype(str).tolist()
    values = _num(df[s["ycol"]])
    return labels, values
'''


def _build_figure_source(config):
    note, body = _plot_body(config)
    lines = ["def build_figure():", '    """設定を再現した matplotlib Figure を返す。"""']
    lines += [("    " + n) for n in note]
    lines += _indent(body, 4)
    return "\n".join(lines)


def _needs_bar_pie(config):
    ct = config.get("chart_type", "折れ線")
    return ct in _BAR or ct in _PIE


# ----------------------------------------------------------------------------- 公開 API
def generate_python(config):
    """設定 dict から、単体で動く .py スクリプト（文字列）を生成する。"""
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    dpi = config.get("export_dpi", 150)
    transparent = bool(config.get("transparent", False))
    blocks = [
        _HEADER.format(now=now, fname="graph_reproduce.py"),
        "import os\n" + _IMPORTS,
        _LOADER,
        _HELPERS,
    ]
    if _needs_bar_pie(config):
        blocks.append(_BAR_PIE_HELPERS)
    blocks.append(_data_source(config))
    blocks.append(_build_figure_source(config))
    main = (
        'if __name__ == "__main__":\n'
        "    fig = build_figure()\n"
        "    if len(sys.argv) > 1:\n"
        f"        fig.savefig(sys.argv[1], dpi={dpi}, bbox_inches='tight', transparent={transparent})\n"
        '        print("保存しました:", sys.argv[1])\n'
        "    else:\n"
        "        plt.show()\n"
    )
    blocks.append(main)
    return "\n\n".join(b.rstrip() for b in blocks) + "\n"


def _code_cell(source):
    return {"cell_type": "code", "metadata": {}, "execution_count": None,
            "outputs": [], "source": source.rstrip("\n").splitlines(keepends=True)}


def _md_cell(source):
    return {"cell_type": "markdown", "metadata": {},
            "source": source.rstrip("\n").splitlines(keepends=True)}


def generate_notebook(config):
    """設定 dict から Jupyter Notebook（.ipynb 相当の dict）を生成する。"""
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    ct = config.get("chart_type", "折れ線")
    title = config.get("title") or "グラフ"
    cells = [
        _md_cell(f"# 設定を再現するノートブック\n\n"
                 f"- グラフ種別: **{ct}**\n- タイトル: {title}\n- 生成日時: {now}\n\n"
                 f"保存したグラフ設定を pandas + matplotlib で再現します。"),
        _code_cell("%matplotlib inline\nimport os\n" + _IMPORTS),
        _code_cell(_LOADER + "\n\n" + _HELPERS
                   + (("\n\n" + _BAR_PIE_HELPERS) if _needs_bar_pie(config) else "")),
        _code_cell(_data_source(config)),
        _code_cell(_build_figure_source(config) + "\n\n\nfig = build_figure()\nplt.show()"),
    ]
    return {
        "cells": cells,
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def export_code(config, path):
    """拡張子（.py / .ipynb）に応じてコードを書き出す。戻り値は書き出したパス。"""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".ipynb":
        nb = generate_notebook(config)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(nb, f, ensure_ascii=False, indent=1)
    else:
        src = generate_python(config)
        with open(path, "w", encoding="utf-8") as f:
            f.write(src)
    return path


def _main(argv=None):
    import argparse
    p = argparse.ArgumentParser(
        description="保存したグラフ設定(JSON)から Python コード(.py/.ipynb)を生成する")
    p.add_argument("config", help="設定 JSON（本ツールの『設定を保存』で出力したもの）")
    p.add_argument("out", help="出力先（.py または .ipynb）")
    args = p.parse_args(argv)
    with open(args.config, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    out = export_code(cfg, args.out)
    print("生成しました:", out)


if __name__ == "__main__":
    _main()
