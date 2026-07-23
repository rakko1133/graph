# -*- coding: utf-8 -*-
"""内蔵の解析タブを差し込み式で登録するモジュール。

左側の4タブ（データ / オシロ・解析 / 高度解析 / 統計解析）を TabPlugin として
登録する。各タブの中身を組み立てるロジックは従来どおり GraphApp の各 Mixin に
あり、ここは「どのメソッドがどのタブか・どの表示レベルで出すか・並び順」を
宣言するだけ（挙動は一切変えない）。

新しい機能タブの足し方は タブ追加ガイド.md を参照。要点だけ:
TabPlugin を継承したクラスを書いて register_tab() で登録すれば、メイン側
（GraphApp）を触らずにタブが増える。build(app) の app は GraphApp なので
既存の描画・解析メソッドをそのまま呼べる。
"""
from graph_app_common import register_tab, _DelegatingTab

# 内蔵4タブ。order で並び順、min_level で「どの表示レベルから現れるか」を決める。
# （data=基本, scope=標準, advanced/datasci=全部 という現行の挙動をそのまま宣言）
BUILTIN_TABS = [
    _DelegatingTab("data", "1. データ", 10, "基本", "_build_tab_data"),
    _DelegatingTab("scope", "2. オシロ/解析", 20, "標準", "_build_tab_scope"),
    _DelegatingTab("advanced", "3. 高度解析", 30, "全部", "_build_tab_advanced"),
    _DelegatingTab("datasci", "4. 統計解析", 40, "全部", "_build_tab_datasci"),
]

for _tab in BUILTIN_TABS:
    register_tab(_tab)
