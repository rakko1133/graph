# -*- coding: utf-8 -*-
"""オシロスコープ相当のデータ解析モジュール（ファサード）。

実体は analysis_common / analysis_spectrum / analysis_measure に分割。
従来どおり analysis.X で全関数にアクセスできるよう再エクスポートする。
GUI から独立しているので単体でも利用・テストできる。
"""
from analysis_common import *       # noqa: F401,F403
from analysis_spectrum import *     # noqa: F401,F403
from analysis_measure import *      # noqa: F401,F403
# 後方互換：アンダースコア付きの内部関数も analysis.X で参照可能にする
from analysis_common import (_simple_peaks, _zero_crossing_period, _edge_time,
                             _window, _mid_crossings, _trapz, _HAVE_SCIPY)
