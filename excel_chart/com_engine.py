# -*- coding: utf-8 -*-
"""COM エンジン（pywin32）= VBA 完全互換でネイティブ Excel グラフを生成する。

実 Excel を COM で起動し、VBA と同じ Excel.Application オブジェクトモデルを叩く。
したがって VBA マクロでできる書式設定はすべて可能（線種・色・太さ・マーカー・
軸範囲/タイトル・対数軸・反転・第2軸・凡例位置・データラベル・エラーバー）。

要件: Windows + Microsoft Excel + pywin32。Linux/ヘッドレス不可。
このモジュールは Excel が無い環境では import 時には失敗せず、write() 呼び出しで
明確な RuntimeError を送出する（フォールバックは export 層が担当）。
"""
import importlib.util
import os

import pandas as pd

from . import mapping as M

# msoTrue/msoFalse, msoThemeColor 不使用。RGB は BGR 整数で直接渡す。
_MSO_FALSE = 0


def available():
    """この環境で COM エンジンが使えそうか（pywin32 が import できるか）。"""
    return importlib.util.find_spec("win32com") is not None


def _col_letter(idx1):
    """1始まりの列番号 -> 'A','B',...,'AA' のような列記号。"""
    s = ""
    n = idx1
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _set_line(fmt, color_bgr, width_pt, dash):
    """系列/グリッド線の Format.Line を設定。dash=None は線を非表示にする。"""
    if dash is None:
        fmt.Line.Visible = _MSO_FALSE
        return
    fmt.Line.Visible = -1  # msoTrue
    if color_bgr is not None:
        fmt.Line.ForeColor.RGB = color_bgr
    if width_pt:
        fmt.Line.Weight = float(width_pt)
    try:
        fmt.Line.DashStyle = dash
    except Exception:
        pass


def write(spec, df, out_path, *, visible=False, macro_enabled=False):
    """ChartSpec + DataFrame からネイティブ Excel グラフ入りブックを保存する。

    out_path: .xlsx（既定）。macro_enabled=True または拡張子 .xlsm なら .xlsm 保存。
    戻り値: 保存した絶対パス。
    """
    try:
        import win32com.client as win32
    except Exception as e:  # pragma: no cover - 環境依存
        raise RuntimeError(
            "COM エンジンには pywin32 が必要です（pip install pywin32）。") from e

    out_path = os.path.abspath(out_path)
    out_dir = os.path.dirname(out_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    if os.path.exists(out_path):
        os.remove(out_path)

    ext = os.path.splitext(out_path)[1].lower()
    as_xlsm = macro_enabled or ext == ".xlsm"
    file_format = 52 if as_xlsm else 51  # 52=xlsm, 51=xlsx

    try:
        excel = win32.gencache.EnsureDispatch("Excel.Application")
    except Exception as e:  # pragma: no cover - gen_py キャッシュ破損など
        raise RuntimeError(
            "Excel への COM 接続に失敗しました。Excel がインストールされ、"
            "起動できる環境か確認してください（gen_py キャッシュ破損時は "
            "%LOCALAPPDATA%\\Temp\\gen_py を削除）。") from e

    excel.Visible = bool(visible)
    excel.DisplayAlerts = False
    try:
        wb = excel.Workbooks.Add()
        ws = wb.Worksheets(1)
        ws.Name = "Data"

        nrow = _write_data(ws, spec, df)        # シートへ列を書き込み、行数を返す
        chart = _build_chart(ws, spec, df, nrow)
        _format_axes_and_legend(chart, spec)

        wb.SaveAs(out_path, FileFormat=file_format)
        wb.Close(SaveChanges=False)
        return out_path
    finally:
        try:
            excel.Quit()
        except Exception:
            pass
        del excel  # COM 参照を解放（EXCEL.EXE のリーク防止）


# --------------------------------------------------------------------------- 内部
def _write_data(ws, spec, df):
    """X 列・各系列の値列・誤差列をシートへ書き込み、データ行数を返す。

    レイアウト: A=X、B 以降=各系列 y、その後に誤差列。列位置は _build_chart と共有。
    """
    # 使用する列を順番に決める（X → y1,y2,... → err...）
    layout = _layout(spec)
    headers = [name for name, _col in layout]
    values = [_column_values(df, col, header=name) for name, col in layout]
    n = max((len(v) for v in values), default=0)

    # ヘッダ行
    for j, h in enumerate(headers, start=1):
        ws.Cells(1, j).Value = h
    # データ本体を 2 次元で一括書き込み（高速）
    if n:
        block = []
        for i in range(n):
            row = []
            for v in values:
                row.append(v[i] if i < len(v) else None)
            block.append(row)
        rng = ws.Range(ws.Cells(2, 1), ws.Cells(1 + n, len(headers)))
        rng.Value = block
    return n


def _layout(spec):
    """シート列レイアウト [(header, df列名), ...] を返す。X は df列名=None の特例。"""
    layout = []
    if _uses_x(spec):
        layout.append((spec.xlabel or spec.x_col or "X", spec.x_col))
    for s in spec.series:
        layout.append((s.name, s.y_col))
    for s in spec.series:
        if s.errcol:
            layout.append((f"{s.name}_err", s.errcol))
    return layout


def _col_index(spec, *, kind, key):
    """レイアウト上の 1 始まり列番号を引く。kind='x'|'y'|'err', key=系列 or None。"""
    pos = 1
    if _uses_x(spec):
        if kind == "x":
            return 1
        pos = 2
    # y 列
    for i, s in enumerate(spec.series):
        if kind == "y" and s is key:
            return pos + i
    pos += len(spec.series)
    # err 列
    err_series = [s for s in spec.series if s.errcol]
    for i, s in enumerate(err_series):
        if kind == "err" and s is key:
            return pos + i
    return None


def _uses_x(spec):
    return spec.chart_type not in ("ヒストグラム", "箱ひげ")


def _column_values(df, col, header=None):
    """df[col] を Excel に書ける Python リストへ。X=None の特例は連番。"""
    if col is None:
        return None
    if col not in df.columns:
        return []
    s = df[col]
    # 数値列は float、非数値はそのまま文字列で（カテゴリ軸ラベル等）
    num = pd.to_numeric(s, errors="coerce")
    if num.notna().mean() >= 0.8:
        out = [None if pd.isna(v) else float(v) for v in num.to_numpy()]
    else:
        out = [None if pd.isna(v) else str(v) for v in s.to_numpy()]
    return out


def _x_is_numeric(df, spec):
    if not spec.x_col or spec.x_col not in df.columns:
        return True   # X 未指定（連番）は数値扱い
    num = pd.to_numeric(df[spec.x_col], errors="coerce")
    return bool(num.notna().mean() >= 0.8)


def _base_chart_type(spec, df):
    """ChartSpec.chart_type -> XlChartType 整数。"""
    ct = spec.chart_type
    if ct == "散布図":
        return M.XL["xy_scatter"]
    if ct == "棒":
        return M.XL["column"]
    if ct == "横棒":
        return M.XL["bar"]
    if ct == "積み上げ棒":
        return M.XL["column_stacked"]
    if ct == "円":
        return M.XL["pie"]
    if ct in ("ヒストグラム",):
        return M.XL["column"]
    # 折れ線: 数値 X は XY 折れ線が忠実、カテゴリ X は通常の折れ線
    if _x_is_numeric(df, spec):
        return M.XL["xy_lines"]
    return M.XL["line_markers"]


def _series_chart_type(spec, s, df):
    """系列ごとの kind 上書き（複合グラフ）を XlChartType へ。None は基本種別のまま。"""
    if not s.kind:
        return None
    if s.kind == "bar":
        return M.XL["column"]
    if s.kind == "area":
        return 1  # xlArea
    if s.kind == "scatter":
        return M.XL["xy_scatter"]
    if s.kind == "line":
        return M.XL["xy_lines"] if _x_is_numeric(df, spec) else M.XL["line"]
    return None


def _build_chart(ws, spec, df, nrow):
    """グラフオブジェクトを作り、系列を 1 本ずつ追加・書式設定する。"""
    base = _base_chart_type(spec, df)
    shp = ws.Shapes.AddChart2(-1, base, 10, 10, spec.width, spec.height)
    chart = shp.Chart

    # AddChart2 が自動生成した系列を一掃し、こちらで明示的に作る（X/Y を完全制御）
    sc = chart.SeriesCollection()
    while sc.Count > 0:
        sc.Item(1).Delete()

    x_idx = _col_index(spec, kind="x", key=None) if _uses_x(spec) else None
    x_rng = None
    if x_idx is not None and nrow:
        x_rng = ws.Range(ws.Cells(2, x_idx), ws.Cells(1 + nrow, x_idx))

    if spec.chart_type == "円":
        _build_pie(ws, chart, spec, df, nrow, x_rng)
        return chart

    for s in spec.series:
        y_idx = _col_index(spec, kind="y", key=s)
        if y_idx is None or not nrow:
            continue
        ser = chart.SeriesCollection().NewSeries()
        ser.Name = s.name
        ser.Values = ws.Range(ws.Cells(2, y_idx), ws.Cells(1 + nrow, y_idx))
        if x_rng is not None:
            ser.XValues = x_rng

        # 系列ごとの種別（複合グラフ）
        st = _series_chart_type(spec, s, df)
        if st is not None:
            try:
                ser.ChartType = st
            except Exception:
                pass

        # 第2軸
        if s.axis == "secondary":
            try:
                ser.AxisGroup = M.XL_SECONDARY
            except Exception:
                pass

        _format_series(ser, s, spec, ws, nrow)

    return chart


def _build_pie(ws, chart, spec, df, nrow, x_rng):
    """円グラフ: 最初の系列のみ使用。ラベルは X 列。"""
    if not spec.series or not nrow:
        return
    s = spec.series[0]
    y_idx = _col_index(spec, kind="y", key=s)
    ser = chart.SeriesCollection().NewSeries()
    ser.Values = ws.Range(ws.Cells(2, y_idx), ws.Cells(1 + nrow, y_idx))
    if x_rng is not None:
        ser.XValues = x_rng
    if spec.data_labels or spec.pct:
        try:
            ser.HasDataLabels = True
            if spec.pct:
                ser.DataLabels().ShowPercentage = True
        except Exception:
            pass


def _format_series(ser, s, spec, ws, nrow):
    """1 系列の線・マーカー・データラベル・エラーバーを設定。"""
    color_bgr = M.hex_to_bgr(s.color)
    dash = M.excel_dash(s.linestyle)

    # 散布図（マーカーのみ）は線を消す。複合 area/bar はマーカー無し。
    is_scatter = (spec.chart_type == "散布図" and not s.kind) or s.kind == "scatter"
    is_barlike = s.kind in ("bar", "area") or spec.chart_type in (
        "棒", "横棒", "積み上げ棒", "ヒストグラム")

    if is_barlike:
        # 塗り色（棒・面）。線色は枠線として控えめに。
        if color_bgr is not None:
            try:
                ser.Format.Fill.Visible = -1
                ser.Format.Fill.ForeColor.RGB = color_bgr
            except Exception:
                pass
        return

    # 線
    line_dash = None if is_scatter else dash
    try:
        _set_line(ser.Format, color_bgr, s.linewidth, line_dash)
    except Exception:
        pass

    # マーカー
    mk = M.excel_marker(s.marker)
    if is_scatter and (s.marker in ("", None)):
        mk = M.excel_marker("o")   # 散布図でマーカー未指定なら丸
    try:
        ser.MarkerStyle = mk
        if mk != -4142:  # not none
            ser.MarkerSize = int(max(2, min(72, round(s.markersize))))
            if color_bgr is not None:
                ser.MarkerForegroundColor = color_bgr
                ser.MarkerBackgroundColor = color_bgr
    except Exception:
        pass

    # データラベル
    if spec.data_labels:
        try:
            ser.HasDataLabels = True
        except Exception:
            pass

    # エラーバー（Y・カスタム両側）
    if s.errcol and nrow:
        err_idx = _col_index(spec, kind="err", key=s)
        if err_idx is not None:
            try:
                # xlY=1, xlErrorBarIncludeBoth=1, xlErrorBarTypeCustom=-4114
                amount = ws.Range(ws.Cells(2, err_idx),
                                  ws.Cells(1 + nrow, err_idx))
                ser.ErrorBar(Direction=1, Include=1, Type=-4114,
                             Amount=amount, MinusValues=amount)
            except Exception:
                pass


def _format_axes_and_legend(chart, spec):
    """タイトル・軸（タイトル/範囲/対数/反転/グリッド）・第2軸・凡例を設定。"""
    # タイトル
    try:
        chart.HasTitle = bool(spec.title)
        if spec.title:
            chart.ChartTitle.Text = spec.title
    except Exception:
        pass

    if spec.chart_type == "円":
        _format_legend(chart, spec)
        return

    # X 軸（カテゴリ）
    try:
        catax = chart.Axes(M.XL_CATEGORY, M.XL_PRIMARY)
        if spec.xlabel:
            catax.HasTitle = True
            catax.AxisTitle.Text = spec.xlabel
        _apply_scale(catax, spec.xmin, spec.xmax, spec.xlog, spec.xinvert)
        catax.HasMajorGridlines = bool(spec.grid)
    except Exception:
        pass

    # Y 軸（主・値）
    try:
        valax = chart.Axes(M.XL_VALUE, M.XL_PRIMARY)
        if spec.ylabel:
            valax.HasTitle = True
            valax.AxisTitle.Text = spec.ylabel
        _apply_scale(valax, spec.ymin, spec.ymax, spec.ylog, spec.yinvert)
        valax.HasMajorGridlines = bool(spec.grid)
    except Exception:
        pass

    # 第2軸（値）
    if any(s.axis == "secondary" for s in spec.series):
        try:
            sec = chart.Axes(M.XL_VALUE, M.XL_SECONDARY)
            if spec.secondary_label:
                sec.HasTitle = True
                sec.AxisTitle.Text = spec.secondary_label
        except Exception:
            pass

    _format_legend(chart, spec)


def _apply_scale(axis, vmin, vmax, log, invert):
    """軸の最小/最大・対数・反転を設定（散布/折れ線の数値軸で有効）。"""
    try:
        if vmin is not None:
            axis.MinimumScale = float(vmin)
        if vmax is not None:
            axis.MaximumScale = float(vmax)
    except Exception:
        pass
    try:
        axis.ScaleType = M.XL_SCALE_LOG if log else M.XL_SCALE_LINEAR
    except Exception:
        pass
    try:
        axis.ReversePlotOrder = bool(invert)
    except Exception:
        pass


def _format_legend(chart, spec):
    try:
        chart.HasLegend = bool(spec.legend)
        if spec.legend:
            chart.Legend.Position = M.excel_legend_position(spec.legend_loc)
    except Exception:
        pass
