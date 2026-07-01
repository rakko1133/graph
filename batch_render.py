# -*- coding: utf-8 -*-
"""一括出力のワーカー（Qt非依存・別プロセスでも実行可能）。

ProcessPoolExecutor から呼ぶため、ここでは Qt や graph_app を import しない。
matplotlib は Agg バックエンド固定。タスクは完全に picklable な dict 1個で渡す。
"""
import matplotlib
matplotlib.use("Agg", force=True)
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg

import plotter

_FONT_DONE = False


def _make_ax(fig, ctype):
    """種別に応じた投影の軸を作る（3D種別は projection='3d'）。"""
    if plotter.is_3d_type(ctype):
        from mpl_toolkits.mplot3d import Axes3D  # noqa: F401  '3d' 投影を登録
        return fig.add_subplot(111, projection="3d")
    return fig.add_subplot(111)


def _apply_ratio(ax, ratio, ctype):
    """縦横比を適用（3D軸はスカラー box_aspect 不可なのでスキップ）。"""
    if ratio and not plotter.is_3d_type(ctype):
        ax.set_box_aspect(ratio)
        ax2 = getattr(ax, "_twin_secondary", None)
        if ax2 is not None:
            ax2.set_box_aspect(ratio)


def _ensure_font(font_name):
    """ワーカープロセスごとに1回だけ日本語フォントを設定（□□□化を防ぐ）。"""
    global _FONT_DONE
    if not _FONT_DONE:
        try:
            import jp_font
            jp_font.setup_japanese_font(font_name)
        except Exception:        # noqa: BLE001  フォント未検出でも既定で続行
            pass
        _FONT_DONE = True


def render_one(task):
    """1ファイル分を描画して保存し、保存パスを返す。task は picklable な dict。

    画面描画・逐次出力と同一の plot_series 経路を使うため、出力はピクセル一致する。
    """
    _ensure_font(task.get("font_name"))
    fig = Figure(figsize=task["figsize"], dpi=task["dpi"])
    FigureCanvasAgg(fig)
    ax = _make_ax(fig, task["ctype"])
    plotter.plot_series(
        ax, task["series"], task["ctype"], categories=task["categories"],
        title=task["title"], xlabel=task["xlabel"], ylabel=task["ylabel"],
        xlim=task["xlim"], ylim=task["ylim"],
        secondary_label=task["sec_label"], max_points=task["max_points"],
        zlabel=task.get("zlabel", ""), view_init=task.get("view_init"),
        **task["fmt"])
    _apply_ratio(ax, task.get("ratio"), task["ctype"])
    tight = task.get("tight", True)
    if not tight:                       # 図サイズ＝画像比率。ラベルが収まるよう整える
        try:
            fig.tight_layout()
        except Exception:
            pass
    fig.savefig(task["path"], dpi=task["dpi"],
                bbox_inches=("tight" if tight else None),
                transparent=task["transparent"])
    return task["path"]


def render_sequential(tasks):
    """逐次出力（図を1つ再利用）。並列が使えない/不要なときのフォールバック。
    戻り値 (saved_paths, skipped_msgs)。"""
    import os
    saved, skipped = [], []
    if not tasks:
        return saved, skipped
    fig = Figure(figsize=tasks[0]["figsize"], dpi=tasks[0]["dpi"])
    FigureCanvasAgg(fig)
    ax = _make_ax(fig, tasks[0]["ctype"])   # 同一バッチは同一種別（投影を固定）
    for t in tasks:
        try:
            ax.clear()
            plotter.plot_series(
                ax, t["series"], t["ctype"], categories=t["categories"],
                title=t["title"], xlabel=t["xlabel"], ylabel=t["ylabel"],
                xlim=t["xlim"], ylim=t["ylim"],
                secondary_label=t["sec_label"], max_points=t["max_points"],
                zlabel=t.get("zlabel", ""), view_init=t.get("view_init"),
                **t["fmt"])
            _apply_ratio(ax, t.get("ratio"), t["ctype"])
            tight = t.get("tight", True)
            if not tight:
                try:
                    fig.tight_layout()
                except Exception:
                    pass
            fig.savefig(t["path"], dpi=t["dpi"],
                        bbox_inches=("tight" if tight else None),
                        transparent=t["transparent"])
            saved.append(t["path"])
        except Exception as e:  # noqa: BLE001
            skipped.append(f"{os.path.basename(t['path'])}（{e}）")
    return saved, skipped
