"""每日出刀情况图表生成"""

import asyncio
from datetime import date
from pathlib import Path
from typing import List

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib import font_manager
import numpy as np

from .models import UserDailySummary
from .config import MAX_KNIVES_PER_DAY, CHART_COLORS

OUTPUT_DIR = Path("data/charts")


def _setup_font():
    """尝试加载中文字体"""
    candidates = [
        "WenQuanYi Micro Hei", "Noto Sans CJK SC", "SimHei",
        "Microsoft YaHei", "PingFang SC", "Hiragino Sans GB",
    ]
    for name in candidates:
        try:
            font_manager.findfont(name, fallback_to_default=False)
            return name
        except Exception:
            pass
    return None


async def generate_daily_chart(
    summaries: List[UserDailySummary],
    round_num: int,
    group_id: str
) -> Path:
    """异步生成每日出刀图表，返回图片路径"""
    return await asyncio.get_event_loop().run_in_executor(
        None, _generate_chart_sync, summaries, round_num, group_id
    )


def _generate_chart_sync(
    summaries: List[UserDailySummary],
    round_num: int,
    group_id: str
) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    font_name = _setup_font()
    if font_name:
        plt.rcParams["font.family"] = font_name
    plt.rcParams["axes.unicode_minus"] = False

    bg = CHART_COLORS["background"]
    text_color = CHART_COLORS["text"]

    fig = plt.figure(figsize=(12, max(6, len(summaries) * 0.55 + 3)),
                     facecolor=bg)
    ax = fig.add_subplot(111, facecolor=bg)

    users = [s.user_name for s in summaries]
    normal_counts = [s.normal_count + s.tail_count for s in summaries]
    comp_counts = [s.compensate_count for s in summaries]
    damages = [s.total_damage for s in summaries]

    y = np.arange(len(users))
    bar_h = 0.5

    # 普通刀条
    bars_normal = ax.barh(
        y, normal_counts, bar_h,
        color=CHART_COLORS["done"], alpha=0.9, label="普通刀"
    )
    # 补偿刀条（叠加）
    bars_comp = ax.barh(
        y, comp_counts, bar_h, left=normal_counts,
        color=CHART_COLORS["compensate"], alpha=0.9, label="补偿刀"
    )

    # 刀数上限虚线
    ax.axvline(x=MAX_KNIVES_PER_DAY, color="#888", linestyle="--",
               linewidth=1, alpha=0.5, label=f"每日上限 {MAX_KNIVES_PER_DAY} 刀")

    # 文字标注
    for i, s in enumerate(summaries):
        total_knives = normal_counts[i] + comp_counts[i]
        comp_hint = " ★" if s.has_compensate_left else ""
        dmg_text = f"  {total_knives}刀 / {_fmt_hp(s.total_damage)}{comp_hint}"
        ax.text(
            total_knives + 0.05, i, dmg_text,
            va="center", ha="left", color=text_color,
            fontsize=9, alpha=0.95
        )

    # 轴设置
    ax.set_yticks(y)
    ax.set_yticklabels(users, color=text_color, fontsize=10)
    ax.set_xlabel("出刀数", color=text_color)
    ax.set_xlim(0, MAX_KNIVES_PER_DAY + 3)
    ax.tick_params(colors=text_color)
    for spine in ax.spines.values():
        spine.set_edgecolor("#444")

    # 图例
    legend = ax.legend(
        facecolor="#2a2a3e", edgecolor="#555",
        labelcolor=text_color, loc="lower right", fontsize=9
    )

    # 标题
    today = date.today().strftime("%Y-%m-%d")
    ax.set_title(
        f"工会战每日出刀汇总  |  第 {round_num} 周目  |  {today}",
        color=text_color, fontsize=13, pad=15, fontweight="bold"
    )

    # ★ 说明
    fig.text(0.01, 0.01, "★ = 有剩余补偿刀",
             color="#aaa", fontsize=8, va="bottom")

    plt.tight_layout()

    out_path = OUTPUT_DIR / f"{group_id}_{date.today().isoformat()}.png"
    fig.savefig(out_path, dpi=130, bbox_inches="tight",
                facecolor=bg, edgecolor="none")
    plt.close(fig)
    return out_path


def _fmt_hp(hp: int) -> str:
    if hp >= 1_000_000:
        return f"{hp/1_000_000:.2f}M"
    return f"{hp:,}"
