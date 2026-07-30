# -*- coding: utf-8 -*-
"""生成した差し込みタブ（graph_tab_<名前>.py）が「ちゃんと使えるコードか」を自動チェックする。

Copilot 等でタブを生成したら、採用（graph_app.py に import を足す）前にこれを回す:

    python tools/check_tab.py graph_tab_mytool         # モジュール名でも
    python tools/check_tab.py graph_tab_mytool.py      # ファイル名でも

graph_app.py を編集しなくても、対象を import → GraphApp を組み立て → サンプル波形で描画
→（あれば）draw_overlay / collect_config / apply_config まで通し、各項目の PASS/FAIL を出す。
すべて PASS なら「import 1行を足して採用してよい」目安。終了コードは 0=全PASS, 1=NGあり, 2=使い方誤り。
"""
import os
import sys
import json
import importlib

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# graph_app.py がある場所をリポジトリルートとみなす（tools/ に置いても、直下に置いても動く）
ROOT = os.path.dirname(os.path.abspath(__file__))
for _ in range(4):
    if os.path.isfile(os.path.join(ROOT, "graph_app.py")):
        break
    ROOT = os.path.dirname(ROOT)
sys.path.insert(0, ROOT)

import numpy as np                                        # noqa: E402
import pandas as pd                                       # noqa: E402
import config_io                                          # noqa: E402
config_io.load_last_session = lambda: None                # セッション復元を無効化
import graph_app                                          # noqa: E402
import graph_app_common as C                              # noqa: E402
from matplotlib.backends.qt_compat import QtCore, QtWidgets  # noqa: E402

# QMainWindow を作るには QApplication が要る。ダイアログは黙らせる。
_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
for _m in ("information", "critical", "warning"):
    setattr(QtWidgets.QMessageBox, _m, staticmethod(lambda *a, **k: None))
QtWidgets.QMessageBox.question = staticmethod(
    lambda *a, **k: QtWidgets.QMessageBox.StandardButton.Yes)
QtWidgets.QDialog.exec = lambda self: 0

_RESULTS = []


def check(name, ok, detail=""):
    _RESULTS.append(bool(ok))
    print(("OK   " if ok else "NG   ") + name + (("  … " + detail) if detail else ""))
    return ok


def _sample_app():
    """サンプル波形（時間/電圧/電流）を入れ、全Y系列を選択済みの GraphApp を返す。"""
    w = graph_app.GraphApp()
    t = np.linspace(0, 0.02, 500)
    df = pd.DataFrame({"時間": t, "電圧": np.sin(2 * np.pi * 500 * t),
                       "電流": np.cos(2 * np.pi * 500 * t)})
    w.datasets.clear(); w.file_list.clear(); w.y_list.clear()
    w.datasets["t.csv"] = df
    w.meta["t.csv"] = {"path": "t.csv", "enc": "utf-8", "delim": ","}
    w._add_file_item("t.csv"); w.file_list.setCurrentRow(0); w._refresh_columns()
    w.x_combo.setCurrentText("時間")
    for r in range(w.y_list.count()):
        it = w.y_list.item(r)
        on = it.data(graph_app.UserRole)[1] != "時間"
        it.setCheckState(QtCore.Qt.CheckState.Checked if on else QtCore.Qt.CheckState.Unchecked)
    w._on_y_selection_changed()
    return w


def main(argv):
    if len(argv) < 2:
        print("使い方: python tools/check_tab.py graph_tab_<名前>")
        return 2
    mod_name = os.path.basename(argv[1])
    if mod_name.endswith(".py"):
        mod_name = mod_name[:-3]

    QtCore.QSettings("graph-tool", "GraphApp").clear()
    print(f"--- {mod_name} を検査します ---")

    # 1) import できる（構文・依存・import 時エラーが無い）
    try:
        importlib.import_module(mod_name)
    except Exception as e:  # noqa: BLE001
        check(f"import {mod_name}", False, repr(e))
        print("\n=== 0/1 PASS ===  import で失敗。まず構文・import を直す。")
        return 1
    check(f"import {mod_name}", True)

    # 2) そのモジュールで TabPlugin が register_tab されている
    cands = [p for p in C.registered_tabs() if type(p).__module__ == mod_name]
    if not check("register_tab で TabPlugin が登録される", len(cands) >= 1,
                 f"見つかった数={len(cands)}"):
        print("\n=== NG ===  末尾で register_tab(<クラス>()) を呼んでいるか確認。")
        return 1
    plugin = cands[0]
    key = getattr(plugin, "key", "")

    # 3) 必須属性・命名規約
    check("必須属性 key/title/order/min_level がある",
          all(getattr(plugin, a, None) not in (None, "") for a in ("key", "title", "order", "min_level")),
          f"key={key!r} title={getattr(plugin, 'title', '')!r} "
          f"order={getattr(plugin, 'order', '?')} min_level={getattr(plugin, 'min_level', '')!r}")
    check("order は 50 以上（内蔵4タブ 10/20/30/40 と衝突しない）",
          isinstance(getattr(plugin, "order", None), int) and plugin.order >= 50,
          f"order={getattr(plugin, 'order', '?')}")
    check("min_level は 基本/標準/全部 のいずれか",
          getattr(plugin, "min_level", None) in ("基本", "標準", "全部"))

    # 4) GraphApp に組み込まれ、ドックが出る
    w = _sample_app()
    docks = [d.objectName() for d in w.left_docks]
    check(f"タブのドック dock_{key} が現れる", f"dock_{key}" in docks, f"docks={docks}")

    # 5) データありで描画しても落ちない
    try:
        w.draw_graph()
        check("draw_graph（タブ在り）が例外なく通る", True)
    except Exception as e:  # noqa: BLE001
        check("draw_graph（タブ在り）が例外なく通る", False, repr(e))

    # 6) draw_overlay があれば直接呼んで例外が出ないか
    if hasattr(plugin, "draw_overlay"):
        try:
            plugin.draw_overlay(w, w.ax)
            w.canvas.draw()
            check("draw_overlay(app, ax) が例外なく描ける", True)
        except Exception as e:  # noqa: BLE001
            check("draw_overlay(app, ax) が例外なく描ける", False, repr(e))

    # 7) collect_config / apply_config があれば JSON化・往復・本体保存への相乗り
    if hasattr(plugin, "collect_config"):
        cfg = None
        try:
            cfg = plugin.collect_config(w)
            json.dumps(cfg, ensure_ascii=False)
            check("collect_config が JSON 化できる dict を返す", isinstance(cfg, dict),
                  f"type={type(cfg).__name__}")
        except Exception as e:  # noqa: BLE001
            check("collect_config が JSON 化できる dict を返す", False, repr(e))
        if hasattr(plugin, "apply_config"):
            try:
                plugin.apply_config(w, cfg if isinstance(cfg, dict) else {})
                check("apply_config が同じ dict を受けて例外を出さない", True)
            except Exception as e:  # noqa: BLE001
                check("apply_config が同じ dict を受けて例外を出さない", False, repr(e))
        try:
            full = w._collect_config()
            check(f"本体の設定保存に tabs.{key} として載る（終了時に自動保存される）",
                  isinstance(full.get("tabs", {}).get(key), dict))
        except Exception as e:  # noqa: BLE001
            check("本体の設定保存に載る", False, repr(e))

    w.close()

    ok = sum(1 for r in _RESULTS if r)
    tot = len(_RESULTS)
    print("\n=== %d/%d PASS ===" % (ok, tot))
    if ok == tot:
        print(f"すべて PASS。graph_app.py に `import {mod_name}` を1行足して採用してOK。")
        return 0
    print("NG あり。上の NG を直してから採用する。")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
