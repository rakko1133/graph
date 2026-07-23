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


DEFAULT_HEADER = (
    "# -*- coding: utf-8 -*-\n"
    '"""CSV / TSV / 波形 グラフ・オシロ解析ツール（単一ファイル版）。\n\n'
    "全モジュールを結合した版。これ1ファイルだけで動作する（依存: requirements.txt）。\n"
    "tools/build_onefile.py で再生成できる。使い方:  python graph_onefile.py\n"
    '"""\n'
)


def compact_source(text):
    """コメント・docstring・空行を落として、動作はそのままに小さくする。

    配布して**動かす**ためのファイル向け。読むためのコードは元のモジュール側に
    あるので、結合済みファイルの説明文は落としてよい（実測で全体の約2割）。

    安全のための決まり:
    - コメントの除去は tokenize で行う（文字列リテラル中の # を壊さない）
    - docstring は ast が「本体の先頭にある文字列」と判定したものだけを消す。
      QSS やメッセージの複数行文字列は対象外。
    - 本体が docstring だけの関数は、消すと構文エラーになるので pass を残す
    - モジュール先頭の docstring は「これは何のファイルか」の説明なので残す
    """
    import ast
    import io as _io
    import tokenize

    tree = ast.parse(text)
    drop = set()          # 消す行番号（1始まり）
    need_pass = {}        # 行番号 -> インデント（pass を置く必要がある場所）
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue        # Module の docstring は残す
        if ast.get_docstring(node, clean=False) is None or not node.body:
            continue
        first = node.body[0]
        start, end = first.lineno, (first.end_lineno or first.lineno)
        for ln in range(start, end + 1):
            drop.add(ln)
        if len(node.body) == 1:     # 中身が docstring だけ → pass に置き換える
            line = text.splitlines()[start - 1]
            need_pass[start] = line[:len(line) - len(line.lstrip())]

    # 行コメント・行末コメントを tokenize で特定する
    comment_spans = {}    # 行番号 -> その行で切り捨てる開始桁
    for tok in tokenize.generate_tokens(_io.StringIO(text).readline):
        if tok.type == tokenize.COMMENT:
            row, col = tok.start
            comment_spans.setdefault(row, col)

    out = []
    for i, line in enumerate(text.splitlines(), start=1):
        if i in need_pass:
            out.append(need_pass[i] + "pass")
            continue
        if i in drop:
            continue
        if i in comment_spans:
            line = line[:comment_spans[i]].rstrip()
            if not line:
                continue          # 行まるごとコメントだった
        if not line.strip():
            continue              # 空行
        out.append(line.rstrip())
    result = "\n".join(out) + "\n"
    compile(result, "<compact>", "exec")   # 壊していないことをその場で確かめる
    return result


def build(out_path=None, header=None, transform=None, tail="", compact=False):
    """モジュールを結合して単一ファイルを書き出す。

    transform: (相対パス, ソース文字列) -> ソース文字列。結合前に各ファイルを
        書き換えるフック（シンプル版ビルドで見た目テンプレートを削るのに使う）。
    tail: 結合後の末尾に足すコード（エントリポイントの差し替え用）。
    """
    out_path = out_path or OUT
    header = DEFAULT_HEADER if header is None else header
    external = []        # 外部importを順序付きでdedup
    body = []
    for rel in ORDER:
        path = os.path.join(ROOT, rel.replace("/", os.sep))
        src = open(path, encoding="utf-8").read()
        if transform is not None:
            src = transform(rel, src)
        lines = src.splitlines()
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
            is_import = bool(re.match(r"^(import|from)\s", stripped))
            if is_import and is_internal_import(stripped):
                # 内部モジュールの import はインデントの有無に関わらず除去
                # （結合後は同一名前空間なので不要。関数内の import jp_font 等も剪定）
                if line.count("(") > line.count(")"):
                    paren_skip = True
                i += 1
                continue
            if is_import and (not indented):
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

    body = "\n".join(external) + "\n\n" + text + "\n" + tail
    if compact:
        before = len(body.encode("utf-8"))
        body = compact_source(body)
        after = len(body.encode("utf-8"))
        print(f"  圧縮: {before / 1024:.0f} KB → {after / 1024:.0f} KB "
              f"（-{100 * (before - after) / before:.0f}%。コメント・docstring・空行を除去）")
    out = header + body
    open(out_path, "w", encoding="utf-8").write(out)
    # サイズは**バイト**で出す（len(str) は文字数なので、日本語コメントが多いこの
    # ファイルでは実ファイルサイズと2〜3割ずれる）
    size_kb = len(out.encode("utf-8")) / 1024
    print(f"出力: {out_path}")
    print(f"結合: {len(ORDER)} モジュール / {out.count(chr(10)) + 1} 行 / "
          f"{size_kb:.0f} KB / 外部import {len(external)} 種")
    return out_path


if __name__ == "__main__":
    build()
