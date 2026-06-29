# [13/30] analysis.py の仕様

## 指示

- この仕様だけを読んで `analysis.py` を**完全な形**で実装し、出力してください。`pass` / `TODO` / 省略 / 要約 は一切禁止です。ファイル全体を、import 文・コメントまで含めて最後まで書き切ってください。
- 出力が途中で切れた場合は、続けて「続き」として最後まで出力してください。
- `analysis.py` は **ファサード（facade）** です。実装本体は別ファイル（`analysis_common.py` / `analysis_spectrum.py` / `analysis_measure.py`）にあり、このファイルはそれらを `import *` で取り込み、後方互換のためアンダースコア付きの内部関数も明示 import して再公開（re-export）するだけのモジュールです。**このファイル自身には関数・クラスの定義は一切ありません。**

### アプリ全体の前提（このファイルに関係する分）

- Python 3.10+。GUI は PySide6(Qt6) だが、**この `analysis.py` および取り込み先の解析モジュール群は GUI（Qt）から完全に独立**しており、単体で利用・テストできる（docstring にもその旨を記す）。
- scipy は**遅延 import ＋ numpy フォールバック**方式（scipy が無くてもモジュールは import でき、起動する）。本ファイルが取り込む `analysis_common` 側で `importlib.util.find_spec("scipy")` により `_HAVE_SCIPY` を判定している。
- `plotter.py` / `analysis.py` は **facade**：実体を `import *` ＋アンダースコア名の明示 import で再公開し、公開名（`analysis.X` でのアクセス）を保つ。

---

## 役割 / 責務

`analysis.py` は「オシロスコープ相当のデータ解析モジュール（ファサード）」である。

docstring の趣旨（モジュール先頭の三重引用符ドキュメント文字列に、以下の内容を日本語で記述すること）:

- このモジュールはオシロスコープ相当のデータ解析モジュールのファサードである。
- 実体（実装本体）は `analysis_common` / `analysis_spectrum` / `analysis_measure` の3ファイルに分割されている。
- 従来どおり `analysis.X` の形で全関数にアクセスできるよう、それらを再エクスポートする。
- GUI から独立しているので、単体でも利用・テストできる。

要するに、このファイルの役割は「分割した3つの解析サブモジュールを一括で取り込み、`analysis` という単一の名前空間から従来の公開名すべて（アンダースコア付きの内部関数も含む）にアクセスできるようにする後方互換レイヤ」である。

---

## ファイル先頭

- 1行目は文字コード宣言コメント `# -*- coding: utf-8 -*-`。
- 続いて上記「役割/責務」の docstring（三重引用符）。

---

## 依存（import するもの）

このファイルが行う import は次の3系統のみ。順序もこのとおりにすること。

1. `from analysis_common import *`
2. `from analysis_spectrum import *`
3. `from analysis_measure import *`

これら3行には、リンタ抑止コメント `# noqa: F401,F403` を各行末に付けること（未使用 import／ワイルドカード import の警告抑止）。

4. 後方互換のためのアンダースコア付き内部関数の明示 import（コメント「後方互換：アンダースコア付きの内部関数も analysis.X で参照可能にする」を付けてから）:

```
from analysis_common import (_simple_peaks, _zero_crossing_period, _edge_time,
                             _window, _mid_crossings, _trapz, _HAVE_SCIPY)
```

（括弧で囲んだ複数 import。2行目のインデントは1行目の開き括弧の次の `_simple_peaks` の位置に合わせる体裁。）

**重要な注意:**
- ワイルドカード import（`import *`）はアンダースコアで始まる名前（`_simple_peaks` 等）を取り込まないため、後方互換のために**アンダースコア付きの内部関数だけは明示的に列挙して import** する必要がある。これが第4の import 行の存在理由である。
- ファイルにはこれ以外のコード（関数定義・クラス定義・`__all__` 定義など）は書かない。実装本体はすべて取り込み先モジュールにある。

---

## 公開API（再エクスポートされる名前の一覧と意味）

`analysis.py` はファサードなので、ここで列挙する関数群は**取り込み先モジュールで定義されているもの**であり、`analysis.py` 経由で `analysis.関数名` としてアクセスできる。`analysis.py` を再現するうえで「どの名前が公開されるか」を正しく保つことが目的なので、各関数の正確なシグネチャを以下に示す（実装本体は各サブモジュール側にあるが、参照の便宜のため要点も記す）。

### `analysis_common` 由来（`import *` で公開、ただし `_` 始まりは明示 import）

公開関数（`_` なし、`import *` で取り込まれる）:

- `sampling_rate(t)` — 時間軸 `t[s]` から平均サンプリング周波数[Hz]を推定。`t.size < 2` なら `None`。`dt = np.median(np.diff(t))`、`dt > 0` のとき `1.0/dt`、それ以外 `None`。
- `smooth_signal(y, window)` — 移動窓で平滑化。Savitzky-Golay（`scipy.signal.savgol_filter`、多項式次数 `min(2, w-1)`）優先、失敗時は窓幅 `w` の移動平均（`np.convolve(..., mode="same")`）。窓幅 `w` が `3` 未満または `y.size` 超なら無加工で返す。偶数窓は `+1` して奇数化。
- `find_signal_peaks(y, t=None, n=5, prominence_frac=0.05, distance=None, mode="max", smooth=0)` — 主要ピーク上位 `n` 個を prominence 順で返す。戻り値は dict のリスト、各 dict のキーは `rank`, `index`, `time`, `value`, `prominence`。`mode="min"` で谷（信号を符号反転して検出）。`smooth>=3` で事前平滑化。`prominence_frac * span`（`span = nanmax - nanmin`）を prominence しきい値に使う。scipy があれば `scipy.signal.find_peaks` を遅延 import、無ければ `_simple_peaks`。`prominence` が NaN のときは `None` に変換して格納。
- `to_db(amp, ref=1.0, floor_db=-200.0)` — 振幅を dB（`20*log10(amp/ref)`）に変換。`amp<=0` の要素は `floor_db`。最後に `np.maximum(out, floor_db)`。
- `histogram_top_base(y, bins=256)` — ヒストグラム法で Top（中点以上で最頻のビン中心）・Base（中点未満で最頻のビン中心）を返すタプル `(top, base)`。`y` の有限値が4未満なら `(None, None)`。`vmax <= vmin` なら `(vmin, vmin)`。

公開定数:

- `WINDOWS = ["hann", "hamming", "blackman", "blackmanharris", "flattop", "kaiser", "gaussian", "rect"]`
- `_trapz` — `getattr(np, "trapezoid", None) or np.trapz`（NumPy の新旧 API 差を吸収する台形積分関数）。
- `_HAVE_SCIPY` — `importlib.util.find_spec("scipy") is not None`（bool）。

アンダースコア付き内部関数（明示 import で公開する対象）:

- `_simple_peaks(sig, distance=1)` — scipy 不在時の素朴な極大検出。`(sig[1:-1] > sig[:-2]) & (sig[1:-1] >= sig[2:])` を満たすインデックス（`+1` オフセット）を返す。
- `_zero_crossing_period(t, y)` — 平均除去後の信号の上昇ゼロ交差から周期[s]を推定。交差点を線形補間し、隣接交差時刻の差の中央値の2倍を周期とする。有限値3未満や交差不足なら `None`。
- `_edge_time(t, y, rising=True, lo=0.1, hi=0.9)` — 最初の立上り（`rising=True`）または立下りエッジの 10%-90% 遷移時間[s]。0%/100% 基準は `histogram_top_base` の Top/Base を使い、決められなければ 5%/95% パーセンタイルにフォールバック。10%・90% の交差は「同じエッジ上」で対応付ける。
- `_window(name, n)` — 窓関数の配列（長さ `n`）を返す。`name` を小文字化し、`hamming`/`blackman`/`blackmanharris`(別名 `blackman-harris`,`bharris`)/`flattop`/`kaiser`(β=14.0)/`gaussian`(std=n/6.0)/`none`,`rect`,`rectangular`(矩形=ones) を分岐。scipy 必要分は遅延 import し失敗時は numpy 窓へフォールバック。既定は `np.hanning(n)`。
- `_mid_crossings(t, y, level)` — `level` を上下に横切る位置（上昇・下降）のインデックス配列タプル `(up, down)` を返す。

### `analysis_spectrum` 由来（`import *` で公開）

- `fft_spectrum(t, y, window="hann", detrend=True)` — 片側振幅スペクトル `(freqs[Hz], amplitude)` を返す。`n<4` または fs 不明なら `(None, None)`。窓のコヒーレントゲイン `np.sum(w)/2.0` で正規化。
- `dominant_frequency(t, y)` — FFT で最大振幅の周波数[Hz]（DC 除く）。全 NaN・平坦信号は `None`。
- `find_spectral_peaks(t, y, n=5, prominence_frac=0.02)` — FFT スペクトルの主要ピーク上位 `n` 個。戻り値は dict リスト、キーは `rank`, `frequency`, `amplitude`。
- `spectrum_metrics(t, y, n_harm=6, window="hann", half_bins=3)` — `THD/SNR/SINAD/ENOB/SFDR` と基本波周波数を計算。戻り値 dict のキーは `f0`, `THD_pct`, `THD_dB`, `SNR_dB`, `SINAD_dB`, `ENOB_bits`, `SFDR_dB`。`n<16` または fs 不明なら `{}`。ENOB は `(SINAD - 1.76) / 6.02`。
- `spectrogram(t, y, nperseg=256, window="hann")` — STFT のスペクトログラム `(f, time, Sxx[dB])`。scipy 必須（無ければ `(None,None,None)`）。`nperseg<16` で `(None,None,None)`。`noverlap=nperseg//2`、`scaling="spectrum"`、`Sxx_db = 10*log10(Sxx + 1e-20)`、time は `t[0]` オフセットを加算。
- `channel_power(t, y, f_lo=None, f_hi=None, window="hann")` — 指定帯域 `[f_lo, f_hi]` の電力（振幅²の総和）。未指定なら全帯域（DC 除く）。
- `occupied_bandwidth(t, y, frac=0.99, window="hann")` — 全電力の `frac`（既定99%）が収まる占有帯域幅[Hz]。DC 除外。累積分布を `np.searchsorted` で両端探索。
- `harmonic_search(t, y, n_harm=5, window="hann")` — 基本波と高調波（基本波周波数の整数倍に最も近いビン）の周波数・振幅。戻り値は dict リスト、キーは `harmonic`, `frequency`, `amplitude`。

### `analysis_measure` 由来（`import *` で公開）

- `measurements(t, y)` — 主要測定値のリスト。各要素 dict のキーは `name`, `value`, `unit`（後述の固定行構成）。
- `slew_rate(t, y)` — 最大の立上り/立下りスルーレート[V/s]。戻り値 dict のキーは `rise`, `fall`（データ不足なら `{}`）。
- `cycle_stats(t, y)` — サイクル単位の平均/RMS と Cycle-Cycle ジッタ。戻り値キーは `cycle_mean`, `cycle_rms`, `cc_jitter`（`t.size<8` で `{}`）。
- `histogram_box_stats(y, bins=256)` — 最頻ビン点数 PEAKHits と平均±1/2/3σ内の割合[%]。戻り値キーは `peak_hits`, `sigma1`, `sigma2`, `sigma3`。
- `cycle_statistics(t, y)` — サイクルごとの周波数/周期/振幅/Vpp の統計。戻り値は dict、外側キーは `"周波数 [Hz]"`, `"周期 [s]"`, `"振幅 [V]"`, `"Vpp [V]"`、各値は `measurement_stats` の dict（`min/max/mean/std/count`）。
- `edge_intervals(t, y, level=None)` — エッジ間時間の平均[s]。戻り値キーは `rise_to_rise`, `fall_to_fall`, `rise_to_fall`, `fall_to_rise`（有限値4未満で `{}`）。`level=None` のときは Top/Base の中点を使用。
- `pulse_metrics(t, y, level=None)` — +/- パルス幅・デューティ・エッジ数・サイクル数。戻り値キーは `rising_edges`, `pos_width`, `neg_width`, `pos_duty`, `neg_duty`, `cycles`。
- `cycle_measurements(t, y)` — サイクルごとの配列。戻り値キーは `cycle_time`, `freq`, `amp`, `vpp`（各 numpy 配列）。
- `measurement_stats(values)` — 測定値配列の `min/max/mean/std/count` を返す dict。空なら値は `None`／`count=0`。
- `phase_delay(t, y1, y2)` — 2チャンネル間の遅延[s]と位相差[deg]を相互相関で。戻り値タプル `(delay, phase)`。位相は `-180..180` に正規化。
- `analyze(t, y, n_peaks=5, smooth=0)` — ピーク・測定・FFT をまとめた dict。キーは `peaks`, `troughs`, `measurements`, `spectral_peaks`。

> 注意: 上記サブモジュール側の関数群は、`analysis.py` の再現それ自体には実装不要（別ファイルの責務）。ただし `analysis.py` 経由で**これらの名前が確実に公開される**ことが再現の本質。`from <module> import *` を3つ正しい順序で書けば、`_` なし公開名はすべて取り込まれる。`_` 付き7名（`_simple_peaks, _zero_crossing_period, _edge_time, _window, _mid_crossings, _trapz, _HAVE_SCIPY`）は第4の明示 import 行で取り込む。

---

## 再現に必須の細部

- import の**順序**は `analysis_common` → `analysis_spectrum` → `analysis_measure`。スペクトル/測定モジュールは共通モジュールに依存するため、論理的にも共通を先頭に置く（ただし `import *` 同士の順序自体は名前衝突がなければ機能差を生まないので、この順序を保つこと）。
- `# noqa: F401,F403` コメントは3つの `import *` 行すべてに付ける。`F401`＝未使用 import 警告、`F403`＝`import *` の警告を抑止する。
- 第4の明示 import の対象は**ちょうど7つの名前**（`_simple_peaks`, `_zero_crossing_period`, `_edge_time`, `_window`, `_mid_crossings`, `_trapz`, `_HAVE_SCIPY`）で、すべて `analysis_common` 由来。`analysis_spectrum` / `analysis_measure` からはアンダースコア名を明示 import しない（これらの内部で使うアンダースコア名は共通モジュールのものを再利用しているため）。
- `_trapz` と `_HAVE_SCIPY` は厳密には「関数」ではなく値（callable／bool）だが、後方互換のために `analysis.X` で参照できるよう明示 import 対象に含める。
- このファイルには `__all__` を定義しない（`import *` の公開範囲は各サブモジュール側に委ねる）。
- 余計な実行コードを書かない。`if __name__ == "__main__":` ブロックも不要。

---

## このファイルに関係する落とし穴

- **facade 規約**: このファイルは「実体を `import *` ＋アンダースコア名の明示 import で再公開し、公開名を保つ」ことが唯一の役割。ここに解析ロジック本体を書いてはならない（`plotter.py` と同じ facade パターン）。
- **`import *` はアンダースコア名を取り込まない**: Python の `from m import *` は、`m` に `__all__` が無い場合、アンダースコアで始まる名前を除外する。したがって `_simple_peaks` 等の内部関数を `analysis._simple_peaks` の形で従来どおり参照可能にするには、第4の明示 import 行が**必須**。これを省くと後方互換が壊れる。
- **scipy フォールバック**: 取り込み先（特に `analysis_common`／`analysis_spectrum`）は scipy を遅延 import し、無い場合は numpy 実装にフォールバックする設計。`analysis.py` を import しただけで scipy が要求されることはない（`_HAVE_SCIPY` は `find_spec` での存在判定のみ）。
- **GUI 非依存**: この層では Qt（PySide6／matplotlib のバックエンド）を一切 import しない。Qt6 列挙のスコープ規約・monospace 回避・grid の `linewidth=None` 回避などの GUI 系の落とし穴は本ファイルには無関係（描画系ファイルの責務）。`analysis.py` に Qt 関連の import を混ぜないこと。
- **公開名の不変性**: 既存コードは `analysis.measurements(...)`、`analysis.fft_spectrum(...)`、`analysis._zero_crossing_period(...)` などの呼び出しに依存している。再エクスポートで公開名（綴り・大文字小文字）を一字一句変えないこと。
