# -*- coding: utf-8 -*-
"""全モジュールを1つの graph_onefile.py に結合するビルダー。

内部importを除去し、モジュール修飾（plotter. など）を平坦化して単一名前空間にする。
使い方:  python tools/build_onefile.py   → プロジェクト直下に graph_onefile.py を生成
"""
import os, re

# このスクリプトは tools/ 配下にある前提。ROOT はその親（プロジェクト直下）。
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "graph_onefile.py")

# 連結順（facade analysis.py と graph_app_mixins/__init__.py は不要なので除外）
ORDER = [
    "applog.py",
    "config_io.py", "jp_font.py", "data_loader.py",
    "plotter_format.py", "plotter_draw.py", "plotter.py",
    "analysis_common.py", "analysis_spectrum.py", "analysis_measure.py",
    "advanced.py", "mathchan.py", "datasci.py", "batch_render.py",
    "graph_app_common.py",
    "graph_app_mixins/ui_build.py", "graph_app_mixins/data_io.py",
    "graph_app_mixins/style_table.py", "graph_app_mixins/plotting.py",
    "graph_app_mixins/scope_cursor.py", "graph_app_mixins/analysis_peaks.py",
    "graph_app_mixins/advanced_tools.py", "graph_app_mixins/datasci_tools.py",
    "graph_app_mixins/batch.py", "graph_app_mixins/persistence.py",
    "graph_app.py",
]
# 内部モジュール名（これらへの import と修飾参照を消す）
INTERNAL = {
    "applog", "config_io", "jp_font", "data_loader", "plotter_format", "plotter_draw", "plotter",
    "analysis_common", "analysis_spectrum", "analysis_measure", "analysis",
    "advanced", "mathchan", "datasci", "batch_render", "graph_app_common", "graph_app_mixins",
}
# 平坦化する修飾（長い名前を先に）
QUALIFIERS = sorted(
    {"plotter_format", "plotter_draw", "plotter", "analysis_common", "analysis_spectrum",
     "analysis_measure", "analysis", "mathchan", "config_io", "data_loader", "jp_font",
     "advanced", "datasci", "batch_render", "applog"}, key=len, reverse=True)


def is_internal_import(stripped):
    m = re.match(r"^import\s+([.\w]+)", stripped)
    if m:
        return m.group(1).split(".")[0] in INTERNAL
    m = re.match(r"^from\s+(\.?[.\w]*)\s+import", stripped)
    if m:
        mod = m.group(1)
        if mod.startswith("."):
            return True
        return mod.split(".")[0] in INTERNAL
    return False


def build():
    external = []        # 外部importを順序付きでdedup
    body = []
    for rel in ORDER:
        path = os.path.join(ROOT, rel.replace("/", os.sep))
        lines = open(path, encoding="utf-8").read().splitlines()
        i, paren_skip = 0, False
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()
            indented = line[:1] in (" ", "\t")
            if paren_skip:                                 # 複数行の内部importを丸ごと飛ばす
                if ")" in line:
                    paren_skip = False
                i += 1
                continue
            if stripped.startswith("# -*- coding"):
                i += 1
                continue
            if (not indented) and re.match(r"^(import|from)\s", stripped):
                if is_internal_import(stripped):
                    if line.count("(") > line.count(")"):
                        paren_skip = True
                    i += 1
                    continue                               # 内部import → 除去
                buf = [line]                               # 外部import（複数行括弧も結合）
                while (sum(b.count("(") for b in buf) - sum(b.count(")") for b in buf)) > 0 and i + 1 < len(lines):
                    i += 1
                    buf.append(lines[i])
                imp = "\n".join(buf)
                if imp not in external:
                    external.append(imp)
                i += 1
                continue
            if "matplotlib.use(" in line:                  # GUI(Qt)版では Agg 固定を消す
                i += 1
                continue
            body.append(line)
            i += 1
        body += ["", "# " + "=" * 70, "# ↑ " + rel, "# " + "=" * 70]

    text = "\n".join(body)
    for mod in QUALIFIERS:                                  # モジュール修飾を平坦化
        text = re.sub(r"\b" + re.escape(mod) + r"\.", "", text)
    # 一括出力の並列(プロセスプール)は単一ファイルでは spawn が再帰起動するため無効化
    text = re.sub(r"BATCH_PARALLEL_THRESHOLD\s*=\s*\d+", "BATCH_PARALLEL_THRESHOLD = 10**9", text)

    header = (
        "# -*- coding: utf-8 -*-\n"
        '"""CSV / TSV / 波形 グラフ・オシロ解析ツール（単一ファイル版）。\n\n'
        "全モジュールを結合した版。これ1ファイルだけで動作する（依存: requirements.txt）。\n"
        "tools/build_onefile.py で再生成できる。使い方:  python graph_onefile.py\n"
        '"""\n'
    )
    out = header + "\n".join(external) + "\n\n" + text + "\n"
    open(OUT, "w", encoding="utf-8").write(out)
    print(f"出力: {OUT}")
    print(f"結合: {len(ORDER)} モジュール / {out.count(chr(10)) + 1} 行 / {len(out) / 1024:.0f} KB / 外部import {len(external)} 種")


if __name__ == "__main__":
    build()
