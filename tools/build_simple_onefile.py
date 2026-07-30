# -*- coding: utf-8 -*-
"""シンプル版の単一ファイル（graph_simple_onefile.py）を作るビルダー。

通常の単一ファイル版（tools/build_onefile.py）との違いは **既定の表示レベルだけ**:

- 起動時の表示レベルが「基本」＝読み込み→列選択→描画に必要なものだけを出す。
  隠れた設定は Ctrl+F（設定を検索）や Ctrl+Shift+P（コマンドパレット）から
  名前で呼び戻せる（表示→表示レベルでまとめて出すこともできる）。
- レベルの保存先キーとウィンドウ見出しを通常版と分ける。

（かつては「見た目テンプレート（◯◯風スキン）」も削っていたが、本体から
テンプレート自体を廃止したため、通常版・シンプル版どちらにも存在しない。）

**機能は1つも削っていない。** 変えるのは起動時に見せる量だけ。

使い方:  python tools/build_simple_onefile.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_onefile                                    # noqa: E402

ROOT = build_onefile.ROOT
OUT = os.path.join(ROOT, "graph_simple_onefile.py")

UI = "graph_app.py"  # ui_build はメインに統合済み

# 通常版の本体（graph_app.py）から見た目テンプレートは廃止済みなので、
# シンプル版で切り取る塊はもう無い（違いは既定の表示レベルだけ）。
CUTS = []

# 単純な文字列置換。(対象ファイル, 前, 後, 説明, 期待件数)
SUBS = [
    (UI,
     '    DEFAULT_UI_LEVEL = "全部"',
     '    DEFAULT_UI_LEVEL = "基本"',
     "既定の表示レベルを基本へ", 1),
    (UI,
     '    UI_LEVEL_KEY = "ui/level"',
     '    UI_LEVEL_KEY = "ui/level_simple"',
     "表示レベルの保存先を通常版と分ける", 1),
    ("graph_app.py",
     'self.setWindowTitle("CSV / TSV / 波形 グラフ・解析ツール")',
     'self.setWindowTitle("CSV / TSV / 波形 グラフ・解析ツール — シンプル版")',
     "ウィンドウタイトル", 1),
]

HEADER = (
    "# -*- coding: utf-8 -*-\n"
    '"""CSV / TSV / 波形 グラフ・オシロ解析ツール（シンプル版・単一ファイル）。\n\n'
    "これ1ファイルだけで動作する（依存: requirements.txt）。使い方: python graph_simple_onefile.py\n\n"
    "通常の単一ファイル版（graph_onefile.py）との違いは、起動時の表示レベルが\n"
    "「基本」＝読み込み→列選択→描画に必要なものだけを出す点だけ。\n\n"
    "**機能は削っていない。** 画面に出ていない設定は\n"
    "Ctrl+F（設定を検索）で名前を入れると、表示レベルを自動で上げてそこまで移動する。\n"
    "表示→表示レベル→標準/全部 でまとめて出すこともできる（再起動不要）。\n\n"
    "tools/build_simple_onefile.py で再生成できる。\n"
    '"""\n'
)


def _cut(text, start, end, what):
    i = text.find(start)
    if i < 0 or text.find(start, i + 1) >= 0:
        raise SystemExit(f"[失敗] 開始マーカが1回一致しない: {what}")
    j = text.find(end, i)
    if j < 0:
        raise SystemExit(f"[失敗] 終了マーカが見つからない: {what}")
    return text[:i] + text[j + 1:]     # end 直前の改行は残す


def transform(rel, src):
    n = 0
    for target, start, end, what in CUTS:
        if target != rel:
            continue
        src = _cut(src, start, end, what)
        n += 1
    for target, old, new, what, times in SUBS:
        if target != rel:
            continue
        got = src.count(old)
        if got != times:
            raise SystemExit(f"[失敗] 置換対象が {got} 件（期待 {times}）: {what}")
        src = src.replace(old, new)
        n += 1
    if n:
        print(f"  {rel}: {n} 箇所を変更")
    return src


def build(compact=True):
    """シンプル版の単一ファイルを作る。

    compact=True（既定）ではコメント・docstring・空行も落とす。
    この版は「読むため」ではなく「配って動かすため」のファイルなので、
    説明は元のモジュール側にあれば十分（実測でファイルの約2割が説明文）。
    中身を読みながら追いたいときは compact=False でビルドする。
    """
    print("シンプル版・単一ファイルを構築します（既定の表示レベル=基本）")
    return build_onefile.build(out_path=OUT, header=HEADER, transform=transform,
                               compact=compact)


if __name__ == "__main__":
    build(compact="--keep-comments" not in sys.argv)
