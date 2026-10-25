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
    # タブ（1タブ=1ファイル）
    "graph_tab_data.py",
    "graph_tab_scope.py",
    "graph_tab_advanced.py",
    "graph_tab_datasci.py",
    "graph_tab_threshold.py",
    # メイン（GUIフレームワーク＋タブ登録＋GraphApp を統合した1ファイル）
    "graph_app.py",
]
# 内部モジュール名（これらへの import と修飾参照を消す）
INTERNAL = {
    "applog", "config_io", "jp_font", "data_loader", "plotter_format", "plotter_draw", "plotter",
    "analysis_common", "analysis_spectrum", "analysis_measure", "analysis",
    "advanced", "mathchan", "datasci", "batch_render", "graph_app_common",
    "graph_tab_data", "graph_tab_scope", "graph_tab_advanced", "graph_tab_datasci",
    "graph_tab_threshold",
}
# 平坦化する修飾（長い名前を先に）
QUALIFIERS = sorted(
    {"plotter_format", "plotter_draw", "plotter", "analysis_common", "analysis_spectrum",
     "analysis_measure", "analysis", "mathchan", "config_io", "data_loader", "jp_font",
     "advanced", "datasci", "batch_render", "applog"}, key=len, reverse=True)

# ---- 同梱するパッケージ（平坦化せず「本物のモジュール」として持つ）----
# excel_chart は com_engine と openpyxl_engine が write/available/_layout/_uses_x/
# _build_chart/_column_values/_x_is_numeric を同名で持つので、ORDER に足して
# 平坦化すると後勝ちで潰れる。export.load_table も data_loader.load_table を潰す。
# そのため中身はソースのまま埋め込み、実行時に sys.modules へ登録して exec する。
PACKAGES = {
    "excel_chart": ["mapping", "spec", "com_engine", "openpyxl_engine", "export",
                    "__init__"],
}

# ---- 同梱する単一モジュール（平坦化せず「本物のモジュール」として持つ）----
# code_export は _num / _lit 等のヘルパ名が他モジュール（plotter_draw._num 等）と
# 衝突し得るので、平坦化すると後勝ちで潰れる。excel_chart と同じく独立した名前空間へ
# exec する。code_export は stdlib のみ依存・内部モジュール非依存なので単独で動く。
EMBED_MODULES = ["code_export"]

# ---- 結合前に落とす塊（1ファイル版では呼び出し元が無く、死にコードになるもの）----
# (相対パス, 開始マーカ, 終了マーカ または None=ファイル末尾まで, 説明)
# 開始マーカは**必ず1回だけ**一致すること。落とす範囲にトップレベル定義が
# 2つ以上入っていたら失敗させる（マーカのずれで巻き添えを出さないため）。
# モジュール側のファイルは触らないので、テスト・ドキュメントには影響しない。
# 現状カットするものは無い（render_sequential は元コードから削除済み）。
# 1ファイル版でだけ死ぬコードが再び出たらここに (相対パス, 開始, 終了, 説明) を足す。
CUTS = []


def _cut(text, start, end, what):
    """開始マーカから終了マーカ直前までを取り除く（end=None ならファイル末尾まで）。"""
    i = text.find(start)
    if i < 0:
        raise SystemExit(f"[失敗] 開始マーカが見つからない: {what}")
    if text.find(start, i + 1) >= 0:
        raise SystemExit(f"[失敗] 開始マーカが複数一致: {what}")
    j = len(text) if end is None else text.find(end, i)
    if j < 0:
        raise SystemExit(f"[失敗] 終了マーカが見つからない: {what}")
    removed = text[i:j]
    # 落とす範囲に居るトップレベル定義（桁0の非空行）はちょうど1つのはず
    tops = [l for l in removed.splitlines() if l.strip() and l[:1] not in (" ", "\t")]
    if len(tops) != 1:
        raise SystemExit(f"[失敗] 落とす範囲のトップレベルが {len(tops)} 個（期待 1）: {what}")
    return text[:i] + ("" if end is None else text[j + 1:])


def apply_cuts(rel, src):
    """CUTS のうち rel が対象のものを適用する。"""
    for target, start, end, what in CUTS:
        if target == rel:
            src = _cut(src, start, end, what)
    return src


def check_cuts_unused(text):
    """落とした名前が結合後のコードに残っていないことを確かめる。

    落とした関数を**後から**誰かが呼び始めても、ビルドは黙って通ってしまい、
    実行時 NameError で機能が落ちる（例: 一括出力）。ここで落として気づかせる。
    仕様プロンプト／コピペ用プロンプトから貼り直すと実際にそうなるので、
    この確認は必須。
    """
    for _target, start, _end, what in CUTS:
        m = re.match(r"\s*(?:def|class)\s+(\w+)", start)
        if not m:
            continue
        name = m.group(1)
        if re.search(r"\b" + re.escape(name) + r"\b", text):
            raise SystemExit(
                f"[失敗] 落としたはずの {name} が結合後に残っている"
                f"（呼び出し元が増えた）: {what}")


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
    - docstring と実コードが同じ行にあるとき（`def f(): \"\"\"説明\"\"\"` や
      `\"\"\"説明\"\"\"; x = 1`）は、行ごと消すと実コードまで道連れになる。
      compile() は通ってしまい**黙って**機能が落ちるので、その docstring は消さない
    """
    import ast
    import io as _io
    import tokenize

    tree = ast.parse(text)
    src_lines = text.splitlines()
    drop = set()          # 消す行番号（1始まり）
    need_pass = {}        # 行番号 -> インデント（pass を置く必要がある場所）
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue        # Module の docstring は残す
        if ast.get_docstring(node, clean=False) is None or not node.body:
            continue
        first = node.body[0]
        start, end = first.lineno, (first.end_lineno or first.lineno)
        # 桁位置で「その行に docstring 以外の中身が居るか」を確かめる。
        # 居るなら行単位では消せない（消すとその中身まで一緒に消える）。
        # ast の col_offset は**UTF-8のバイト位置**なので、必ず encode してから
        # 切る。文字位置のまま切ると、日本語 docstring では切り過ぎて
        # 「後ろに何も無い」と誤判定し、同居する実コードを消してしまう。
        before = (src_lines[start - 1].encode("utf-8")[:first.col_offset]
                  .decode("utf-8", "replace").strip())
        after = (src_lines[end - 1].encode("utf-8")[(first.end_col_offset or 0):]
                 .decode("utf-8", "replace").strip())
        if before or (after and not after.startswith("#")):
            continue        # 実コードと同居 → この docstring は触らない
        for ln in range(start, end + 1):
            drop.add(ln)
        if len(node.body) == 1:     # 中身が docstring だけ → pass に置き換える
            line = src_lines[start - 1]
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


PACKAGE_TAIL = '''

_PACKAGE_NAMES = {names}
_PACKAGE_BLOB = "{blob}"


def _package_entries(pkg_name):
    """埋め込んだパッケージのソースをほどいて (モジュール名, ソース) の並びにする。

    ソースをそのまま書くと 1,300 行・48 KB のデータがファイルに居座るので、
    zlib で縮めて base85 の1行にしてある（実測 48 KB → 18 KB）。
    中身は元のファイルと**1バイトも違わない**（ビルド時に復元して照合済み）。
    """
    import base64 as _b64, zlib as _zlib
    srcs = _zlib.decompress(_b64.b85decode(_PACKAGE_BLOB)).decode("utf-8").split("\\0")
    entries, at = {}, 0
    for pkg, names in _PACKAGE_NAMES.items():
        entries[pkg] = list(zip(names, srcs[at:at + len(names)]))
        at += len(names)
    return entries[pkg_name]


def _install_package(pkg_name):
    """同梱したパッケージを、本物のモジュールとして sys.modules に載せる。

    平坦化（同一名前空間への展開）だと同名関数が後勝ちで潰れるので、
    types.ModuleType で個別の名前空間を作り、依存順に exec する。
    先に sys.modules へ登録しておくことで `from . import x` / `from .x import Y`
    のような相対 import がそのまま解決する。
    """
    import types as _types
    if pkg_name in sys.modules:
        return sys.modules[pkg_name]
    # パッケージ側の `import data_loader` は、この1ファイルの load_table
    # （全形式対応）へ橋渡しする。読み込み経路を2重に持たないため。
    sys.modules.setdefault("data_loader", sys.modules[__name__])
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), pkg_name)
    pkg = _types.ModuleType(pkg_name)
    pkg.__file__ = os.path.join(base, "__init__.py")   # __file__ を触る実装がある
    pkg.__path__ = [base]
    pkg.__package__ = pkg_name
    made = {pkg_name: pkg}
    sys.modules[pkg_name] = pkg
    entries = _package_entries(pkg_name)
    for name, _src in entries:
        if name in made:
            continue
        mod = _types.ModuleType(name)
        mod.__file__ = os.path.join(base, name.split(".")[-1] + ".py")
        mod.__package__ = pkg_name
        made[name] = mod
        sys.modules[name] = mod
        setattr(pkg, name.split(".")[-1], mod)
    try:
        for name, src in entries:
            mod = made[name]
            exec(compile(src, mod.__file__, "exec"), mod.__dict__)
    except Exception:
        for name, _src in entries:      # 半端な状態を残さない
            sys.modules.pop(name, None)
        sys.modules.pop(pkg_name, None)
        raise
    return pkg
'''


def package_sources(compact=False):
    """PACKAGES のソースを、実行時に exec できる形の Python コードにする。

    ソースは zlib+base85 の1行に畳んで埋め込む。生のまま raw 文字列で置くと
    1,300 行・48 KB を占めるが、畳むと 2 行・18 KB で済む（実測）。
    畳んだ側は**その場で復元して元と1バイトずつ照合**するので、取り違えは起きない。
    base85 の文字集合には引用符もバックスラッシュも無いので、普通の文字列に入れられる。
    """
    if not PACKAGES:
        return ""
    import base64
    import zlib

    names, srcs = {}, []
    for pkg, mods in PACKAGES.items():
        got = []
        for m in mods:
            path = os.path.join(ROOT, pkg, m + ".py")
            src = open(path, encoding="utf-8").read()
            if compact:
                src = compact_source(src)
            if not src.endswith("\n"):
                src += "\n"
            if "\0" in src:                     # 区切りに使う文字が中に居たら困る
                raise SystemExit(f"[失敗] NUL を含むソース: {pkg}/{m}.py")
            compile(src, path, "exec")          # 埋め込む前に構文を確かめる
            got.append(pkg if m == "__init__" else f"{pkg}.{m}")
            srcs.append(src)
        names[pkg] = got
    blob = base64.b85encode(zlib.compress("\0".join(srcs).encode("utf-8"), 9)).decode("ascii")
    if '"' in blob or "\\" in blob:
        raise SystemExit("[失敗] base85 に引用符/バックスラッシュが混じった")
    back = zlib.decompress(base64.b85decode(blob)).decode("utf-8").split("\0")
    if back != srcs:                            # 復元できることをその場で確かめる
        raise SystemExit("[失敗] 埋め込んだソースを復元できない")
    raw = sum(len(s.encode("utf-8")) for s in srcs)
    print(f"  同梱パッケージを圧縮: {raw / 1024:.0f} KB → {len(blob) / 1024:.0f} KB "
          f"（{sum(len(v) for v in names.values())} モジュール、復元して照合済み）")
    return PACKAGE_TAIL.replace("{names}", repr(names)).replace("{blob}", blob)


MODULE_TAIL = '''

_EMBED_MODULE_NAMES = {names}
_EMBED_MODULE_BLOB = "{blob}"


def _embed_module_entries():
    """埋め込んだ単一モジュールのソースを (名前 -> ソース) に復元する。"""
    import base64 as _b64, zlib as _zlib
    srcs = _zlib.decompress(_b64.b85decode(_EMBED_MODULE_BLOB)).decode("utf-8").split("\\0")
    return dict(zip(_EMBED_MODULE_NAMES, srcs))


def _install_module(mod_name):
    """同梱した単一モジュール（code_export 等）を本物のモジュールとして sys.modules に載せる。

    平坦化（同一名前空間への展開）だと同名ヘルパ（_num 等）が後勝ちで潰れるので、
    excel_chart と同様に types.ModuleType で独立した名前空間を作り、そこで exec する。"""
    import types as _types
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    src = _embed_module_entries()[mod_name]
    mod = _types.ModuleType(mod_name)
    mod.__file__ = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                mod_name + ".py")
    sys.modules[mod_name] = mod
    try:
        exec(compile(src, mod.__file__, "exec"), mod.__dict__)
    except Exception:
        sys.modules.pop(mod_name, None)
        raise
    return mod
'''


def module_sources(compact=False):
    """EMBED_MODULES のソースを、実行時に exec できる形の Python コードにする。

    単一モジュール（パッケージでない）を、平坦化せず本物のモジュールとして持つ。
    package_sources と同じく zlib+base85 の1行に畳んで埋め込み、その場で復元照合する。
    """
    if not EMBED_MODULES:
        return ""
    import base64
    import zlib

    names, srcs = [], []
    for m in EMBED_MODULES:
        path = os.path.join(ROOT, m + ".py")
        src = open(path, encoding="utf-8").read()
        if compact:
            src = compact_source(src)
        if not src.endswith("\n"):
            src += "\n"
        if "\0" in src:                     # 区切りに使う文字が中に居たら困る
            raise SystemExit(f"[失敗] NUL を含むソース: {m}.py")
        compile(src, path, "exec")          # 埋め込む前に構文を確かめる
        names.append(m)
        srcs.append(src)
    blob = base64.b85encode(zlib.compress("\0".join(srcs).encode("utf-8"), 9)).decode("ascii")
    if '"' in blob or "\\" in blob:
        raise SystemExit("[失敗] base85 に引用符/バックスラッシュが混じった")
    back = zlib.decompress(base64.b85decode(blob)).decode("utf-8").split("\0")
    if back != srcs:                        # 復元できることをその場で確かめる
        raise SystemExit("[失敗] 埋め込んだモジュールを復元できない")
    raw = sum(len(s.encode("utf-8")) for s in srcs)
    print(f"  同梱モジュールを圧縮: {raw / 1024:.0f} KB → {len(blob) / 1024:.0f} KB "
          f"（{len(names)} モジュール、復元して照合済み）")
    return MODULE_TAIL.replace("{names}", repr(names)).replace("{blob}", blob)


def _same_ast(before, after, what):
    """変換の前後で構文木が完全に一致することを確かめる（文字列の中身も含む）。

    行の畳み込みやインデント幅の変更は「見た目だけ」の変換なので、構文木が
    1ビットも変わらないなら意味は変わりようがない。逆に、複数行文字列の中身を
    うっかり削ったような取り違えはここで必ず落ちる。
    """
    import ast
    a = ast.dump(ast.parse(before), include_attributes=False)
    b = ast.dump(ast.parse(after), include_attributes=False)
    if a != b:
        raise SystemExit(f"[失敗] {what} で構文木が変わった")


def join_wrapped_lines(text):
    """括弧で折り返してある1つの文を、1行に畳む。

    結合ファイルは「読むため」ではなく「配って動かすため」のものなので、
    80桁の折り返しを保つ意味が無い。折り返し行の**行頭の空白**がそのまま
    容量になっているので、畳むと行数もバイト数も減る。

    触らないもの（畳むと中身が変わる／壊れるもの）:
    - 複数行の文字列リテラルを含む文（改行が値の一部）
    - 行末バックスラッシュで継いだ文（括弧の外なので空白に置き換えられない）
    - 途中にコメントを挟んでいる文（畳むと後ろが全部コメントになる）
    """
    import io as _io
    import tokenize

    lines = text.splitlines()
    spans, start, depth, prev_row, skip = [], None, 0, 0, False
    for tok in tokenize.generate_tokens(_io.StringIO(text).readline):
        ty = tok.type
        if ty in (tokenize.INDENT, tokenize.DEDENT, tokenize.ENDMARKER):
            continue
        if start is None:
            if ty in (tokenize.NEWLINE, tokenize.NL, tokenize.COMMENT):
                continue
            start, depth, prev_row, skip = tok.start[0], 0, tok.start[0], False
        pre_depth = depth        # このトークンを処理する前の括弧の深さ
        if ty == tokenize.COMMENT:
            skip = True
        elif tok.end[0] > tok.start[0] and ty != tokenize.NEWLINE:
            # 1つのトークンが複数行にまたがる＝複数行の文字列（f 文字列を含む）。
            # 3.12 の f 文字列は STRING ではなく FSTRING_MIDDLE で改行を持つので、
            # 種類ではなく「またいでいるか」で判定する。
            skip = True
        elif ty == tokenize.OP:
            if tok.string in "([{":
                depth += 1
            elif tok.string in ")]}":
                depth -= 1
        # 行またぎが「括弧の外」か判定するのは、このトークンを処理する**前**の深さで
        # 行う。閉じ括弧が単独行にあると depth はこの行で 0 に落ちるため、処理後の
        # depth で見ると「括弧の外の行継続＝行末 \」と誤判定して畳むのをやめてしまう。
        if tok.start[0] > prev_row and pre_depth == 0 and ty != tokenize.NEWLINE:
            skip = True                          # 括弧の外での行またぎ＝行末 \
        prev_row = max(prev_row, tok.end[0])
        if ty == tokenize.NEWLINE:
            if tok.end[0] > start and not skip:
                spans.append((start, tok.end[0]))
            start = None

    drop, joined = set(), {}
    for a, b in spans:
        parts = [lines[a - 1].rstrip()]
        for r in range(a + 1, b + 1):
            piece = lines[r - 1].strip()
            if piece:
                parts.append(piece)
            drop.add(r)
        joined[a] = " ".join(parts)
    out = "\n".join(joined.get(i, l) for i, l in enumerate(lines, 1) if i not in drop)
    out += "\n"
    _same_ast(text, out, "行の畳み込み")
    print(f"  折り返しを畳む: {len(spans)} 文 / {len(drop)} 行削除")
    return out


def shrink_indent(text, width=1):
    """ネスト1段あたりの字下げを width 文字にする（既定は1文字）。

    実測でこのファイルの約2割（100 KB）が行頭の空白。Python は段の深さしか
    見ないので、1段=4文字を1文字にしても意味は変わらない。

    書き換えるのは**文の先頭行だけ**。複数行文字列の中身や、括弧内の折り返し行は
    触らない（前者は値そのもの、後者はどう字下げしても解釈が変わらない）。
    """
    import io as _io
    import tokenize

    level, at_start, want = 0, True, {}
    for tok in tokenize.generate_tokens(_io.StringIO(text).readline):
        ty = tok.type
        if ty == tokenize.INDENT:
            level += 1
            continue
        if ty == tokenize.DEDENT:
            level -= 1
            continue
        if ty in (tokenize.NEWLINE, tokenize.NL):
            at_start = True
            continue
        if ty == tokenize.ENDMARKER:
            continue
        if at_start:
            want[tok.start[0]] = level
            at_start = False

    lines = text.splitlines()
    out, saved = [], 0
    for i, line in enumerate(lines, 1):
        if i in want:
            body = line.lstrip(" \t")
            saved += len(line) - len(body) - width * want[i]
            line = " " * (width * want[i]) + body
        out.append(line)
    result = "\n".join(out) + "\n"
    _same_ast(text, result, "字下げの詰め")
    print(f"  字下げを1段={width}文字に: {saved / 1024:.0f} KB 削減")
    return result


def dedup_top_level_assigns(text):
    """複数モジュールから来た「同じ名前・同じ内容」のトップレベル代入を1本化する。

    結合すると analysis_common.py と mathchan.py が両方持つ
    `_HAVE_SCIPY = _ilu.find_spec("scipy") is not None` が2回実行される。
    後の代入が必ず勝つので、先行分は消してよい。

    消してよい条件（どれか欠けたら消さない）:
    - 文が **ast.unparse で完全に一致**する（右辺が違えば別物なので触らない）。
      生ソースで比べると、片方だけ行末コメントが付いている重複を取り逃す。
    - 消す代入と最後の代入の**間にあるトップレベル実行文**がその名前を読まない
      （読むなら「先の値」に意味がある）
    """
    import ast

    tree = ast.parse(text)
    lines = text.splitlines()
    spots = {}                              # 名前 -> [(開始行, 終了行, 文)]
    for st in tree.body:
        if not (isinstance(st, ast.Assign) and len(st.targets) == 1
                and isinstance(st.targets[0], ast.Name)):
            continue
        spots.setdefault(st.targets[0].id, []).append(
            (st.lineno, st.end_lineno, ast.unparse(st)))

    drop, removed = set(), []
    for name, hits in spots.items():
        if len(hits) < 2 or len({h[2] for h in hits}) != 1:
            continue                        # 1回だけ / 内容が違う → 触らない
        last = hits[-1][0]
        # def/class の中身は呼ばれるまで動かないので、間の判定からは外す
        reads = any(
            any(isinstance(n, ast.Name) and n.id == name for n in ast.walk(st))
            for st in tree.body
            if not isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef,
                                   ast.ClassDef))
            and hits[0][0] < st.lineno < last)
        if reads:
            continue
        for start, end, _src in hits[:-1]:
            drop.update(range(start, end + 1))
            removed.append(f"{name}(行{start})")

    if not drop:
        return text
    out = "\n".join(l for i, l in enumerate(lines, 1) if i not in drop)
    compile(out, "<dedup>", "exec")          # 壊していないことをその場で確かめる
    print(f"  重複代入を1本化: {len(drop)} 行削除（{', '.join(removed)}）")
    return out


def build(out_path=None, header=None, transform=None, tail="", compact=True,
          join=True, indent_width=1):
    """モジュールを結合して単一ファイルを書き出す。

    transform: (相対パス, ソース文字列) -> ソース文字列。結合前に各ファイルを
        書き換えるフック（シンプル版ビルドで見た目テンプレートを削るのに使う）。
    tail: 結合後の末尾に足すコード（エントリポイントの差し替え用）。
    compact: コメント・docstring・空行を落として小さくする。既定 True。
        **既定を True にしているのは、テスト（test_onefile）が build() を
        引数なしで呼んで graph_onefile.py を上書きするため**。ここが False
        だと、CLI で圧縮ビルドした成果物をテストが非圧縮で書き戻してしまう。
    """
    out_path = out_path or OUT
    header = DEFAULT_HEADER if header is None else header
    external = []        # 外部importを順序付きでdedup
    body = []
    for rel in ORDER:
        path = os.path.join(ROOT, rel.replace("/", os.sep))
        src = open(path, encoding="utf-8").read()
        src = apply_cuts(rel, src)
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
    # 同梱パッケージは import せず、末尾に埋め込んだソースからその場で組み立てる
    for pkg in PACKAGES:
        text, n = re.subn(r"(?m)^([ \t]*)import " + re.escape(pkg) + r"[ \t]*$",
                          r"\1" + pkg + " = _install_package(\"" + pkg + "\")", text)
        if n != 1:
            raise SystemExit(f"[失敗] `import {pkg}` が {n} 件（期待 1）")
    # 同梱する単一モジュールの import も、埋め込みソースからの install 呼び出しに置き換える
    for mod in EMBED_MODULES:
        text, n = re.subn(r"(?m)^([ \t]*)import " + re.escape(mod) + r"[ \t]*$",
                          r"\1" + mod + " = _install_module(\"" + mod + "\")", text)
        if n != 1:
            raise SystemExit(f"[失敗] `import {mod}` が {n} 件（期待 1）")
    check_cuts_unused(text)
    text = dedup_top_level_assigns(text)    # 同名・同内容のトップレベル代入を1本化

    # 同梱パッケージのソースは**文字列リテラル**として埋め込むので、後段の
    # compact_source では縮まらない（コードではなくデータ扱いになる）。
    # 圧縮ビルドのときは、埋め込む前にこちらも個別に縮めておく。
    pack_compact = compact or os.environ.get("ONEFILE_PACK_COMPACT") == "1"
    body = ("\n".join(external) + "\n\n" + text + "\n"
            + package_sources(pack_compact) + module_sources(pack_compact) + tail)
    if compact:
        before = len(body.encode("utf-8"))
        body = compact_source(body)
        after = len(body.encode("utf-8"))
        print(f"  圧縮: {before / 1024:.0f} KB → {after / 1024:.0f} KB "
              f"（-{100 * (before - after) / before:.0f}%。コメント・docstring・空行を除去）")
    # 以下は「見た目だけ」の変換。構文木が変わらないことを毎回その場で確かめる。
    if join:
        body = join_wrapped_lines(body)
    if indent_width:
        body = shrink_indent(body, indent_width)
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
    import sys
    # 中身を読みたいときは --keep-comments で非圧縮ビルドにできる。
    build(compact="--keep-comments" not in sys.argv)
