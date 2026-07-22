# -*- coding: utf-8 -*-
"""シンプル版の単一ファイル（graph_simple_onefile.py）を作るビルダー。

通常の単一ファイル版（tools/build_onefile.py）との違いは2つだけ:

1. **見た目テンプレートを削る**
   LabPlot風 / Veusz風 / KST2風 / Igor Pro風 の配置＋外観テンプレート、および
   「配置は変えずに外観だけ」サブメニューを取り除く。標準の見た目と、作業向けの
   4配置（標準／グラフ集中／解析中心／データ整備）は残す。
2. **既定の表示レベルが「基本」**
   起動時に出るのは読み込み→列選択→描画に必要なものだけ。隠れた設定は
   Ctrl+F（設定を検索）や Ctrl+Shift+P（コマンドパレット）から名前で呼び戻せる。

**解析・測定・出力などの機能は1つも削っていない。** 削るのは見た目の着せ替えだけ。

使い方:  python tools/build_simple_onefile.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_onefile                                    # noqa: E402

ROOT = build_onefile.ROOT
OUT = os.path.join(ROOT, "graph_simple_onefile.py")

UI = "graph_app_mixins/ui_build.py"

# 削除する塊。(対象ファイル, 開始マーカ, 終了マーカ, 説明)
# 開始マーカの位置から終了マーカの直前までを取り除く。
# **マーカは必ず1回だけ一致すること**を検証する（複数一致・不一致はビルド失敗）。
CUTS = [
    (UI,
     '        "labplot": {   # KDE Breeze調',
     "\n    }\n\n    _UI_STYLE_NAMES",
     "_UI_STYLES から ◯◯風の4テーマ"),
    (UI,
     '        lay_menu.addSeparator()\n        self._menu_action(lay_menu, "LabPlot風"',
     "\n        vm.addSeparator()\n        self._menu_action(vm, \"メッセージ履歴…\"",
     "見た目メニューの◯◯風4項目と「外観だけ」サブメニュー"),
    (UI,
     "        elif name == \"labplot\":",
     "\n    def _reset_panel_layout(self):",
     "_apply_layout_preset の ◯◯風4分岐"),
    (UI,
     "    def _set_ui_style(self, name):",
     "\n    def _apply_ui_style(self, name):",
     "_set_ui_style（外観だけ切替。呼び出し元がなくなるため）"),
]

# 単純な文字列置換。(対象ファイル, 前, 後, 説明, 期待件数)
SUBS = [
    (UI,
     '    _UI_STYLE_NAMES = {"standard": "標準", "labplot": "LabPlot風", "veusz": "Veusz風",\n'
     '                       "kst": "KST2風", "igor": "Igor Pro風"}\n',
     '    _UI_STYLE_NAMES = {"standard": "標準"}\n',
     "_UI_STYLE_NAMES を標準のみに", 1),
    (UI,
     '        # 「◯◯風」プリセットは配置だけでなく外観（ボタンの大きさ・密度・配色）も適用する\n'
     "        if name in self._UI_STYLES:\n"
     "            self._apply_ui_style(name)\n",
     "",
     "レイアウトプリセットからの外観適用（標準しか無いので不要）", 1),
    (UI,
     '        lay_menu = vm.addMenu("見た目（配置＋外観）")',
     '        lay_menu = vm.addMenu("画面の配置")',
     "メニュー名を実態に合わせる", 1),
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
    # 削ったテンプレートに言及したままのコメント・説明文を実態に合わせる
    # （残しておくと、無い機能の説明がファイルに残って読む人を惑わせる）
    (UI,
     "        # ツールバーは既定の上配置へ戻す（Veusz風だけが左縦に移す）\n",
     "        # ツールバーは既定の上配置へ戻す\n",
     "ツールバー復帰コメントの Veusz 参照", 1),
    (UI,
     "        if tb is not None:   # Veusz風で左縦に移したツールバーも上へ戻す\n",
     "        if tb is not None:   # ツールバーは常に上へ戻す\n",
     "配置リセットのコメントの Veusz 参照", 1),
    ("graph_app_mixins/plotting.py",
     '"""現在のグラフを独立ウィンドウとして複製する（Igor Pro風）。',
     '"""現在のグラフを独立ウィンドウとして複製する。',
     "別グラフウィンドウの説明の Igor 参照", 1),
    (UI,
     "        graph=Saleae風（グラフほぼ全画面）／analysis=オシロ作業／data=データ整備。\n",
     "        graph=グラフほぼ全画面／analysis=オシロ作業／data=データ整備。\n",
     "レイアウト説明の他ツール名", 1),
    (UI,
     '        self._menu_action(lay_menu, "グラフ集中（Saleae風）",',
     '        self._menu_action(lay_menu, "グラフ集中",',
     "レイアウト名から他ツール名を外す", 1),
    (UI,
     '        if name == "graph":          # Saleae風: 波形が主役、他は全部たたむ',
     '        if name == "graph":          # 波形が主役、他は全部たたむ',
     "レイアウト分岐コメントの他ツール名", 1),
]

HEADER = (
    "# -*- coding: utf-8 -*-\n"
    '"""CSV / TSV / 波形 グラフ・オシロ解析ツール（シンプル版・単一ファイル）。\n\n'
    "これ1ファイルだけで動作する（依存: requirements.txt）。使い方: python graph_simple_onefile.py\n\n"
    "通常の単一ファイル版（graph_onefile.py）との違い:\n"
    "  - 見た目テンプレート（LabPlot風/Veusz風/KST2風/Igor Pro風、外観だけの切替）が無い\n"
    "  - 起動時の表示レベルが「基本」＝読み込み→列選択→描画に必要なものだけを出す\n\n"
    "**解析・測定・出力などの機能は削っていない。** 画面に出ていない設定は\n"
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


def build():
    print("シンプル版・単一ファイルを構築します（見た目テンプレートを除去）")
    path = build_onefile.build(out_path=OUT, header=HEADER, transform=transform)
    return path


if __name__ == "__main__":
    build()
