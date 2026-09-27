# visualizer.py
"""
可视化模块：绘制K线图、五浪节点与趋势线
解决 Linux 下无中文字体导致的 Glyph missing 告警，支持安全字符渲染
"""
import os
import warnings
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
import pandas as pd
import numpy as np
import logging

from config import IMAGE_DIR

# 1. 从根源上彻底静音字形缺失的 UserWarning
warnings.filterwarnings("ignore", message=".*Glyph.*missing from font.*")
logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)


def configure_fonts():
    """检测并配置中文字体，若无则使用标准英文字体"""
    candidates = [
        "WenQuanYi Micro Hei",
        "WenQuanYi Zen Hei",
        "Noto Sans CJK SC",
        "Source Han Sans CN",
        "SimHei",
        "Microsoft YaHei"
    ]
    sys_fonts = set(f.name for f in font_manager.fontManager.ttflist)
    found_font = None
    for cand in candidates:
        if cand in sys_fonts:
            found_font = cand
            break

    if found_font:
        plt.rcParams["font.sans-serif"] = [found_font, "DejaVu Sans", "sans-serif"]
        return True
    else:
        # 无中文字体，全部使用 DejaVu Sans 避免报错
        plt.rcParams["font.sans-serif"] = ["DejaVu Sans", "Arial"]
        return False

HAS_CHINESE_FONT = configure_fonts()


class ChartVisualizer:
    @staticmethod
    def render_and_save(symbol: str, name: str, category: str, pattern_meta: dict) -> str:
        """
        绘制专业日K线形态图并保存
        """
        df: pd.DataFrame = pattern_meta["df_processed"]
        p0 = pattern_meta["p0"]
        p1 = pattern_meta["p1"]
        p2 = pattern_meta["p2"]
        t1 = pattern_meta["t1"]
        t2 = pattern_meta["t2"]
        t3 = pattern_meta["t3"]
        slope = pattern_meta["trend_slope"]
        intercept = pattern_meta["trend_intercept"]
        max_drop = pattern_meta["max_drop_pct"]
        breakout_date = pattern_meta["breakout_date"]

        fig, (ax1, ax2) = plt.subplots(
            2, 1, figsize=(14, 8),
            gridspec_kw={"height_ratios": [3.2, 1.2]},
            sharex=True
        )
        plt.subplots_adjust(hspace=0.08, left=0.06, right=0.95, top=0.92, bottom=0.08)

        indices = np.arange(len(df))

        # 1. 绘制K线蜡烛
        up = df["close"] >= df["open"]
        down = df["close"] < df["open"]

        ax1.vlines(indices[up], df["low"][up], df["high"][up], color="#ef5350", linewidth=1.0)
        ax1.vlines(indices[down], df["low"][down], df["high"][down], color="#26a69a", linewidth=1.0)
        ax1.bar(indices[up], df["close"][up] - df["open"][up], bottom=df["open"][up], color="#ef5350", width=0.6)
        ax1.bar(indices[down], df["open"][down] - df["close"][down], bottom=df["close"][down], color="#26a69a", width=0.6)

        # 2. 均线系统
        ax1.plot(indices, df["ma5"], label="MA5", color="#fbc02d", linewidth=0.9, alpha=0.9)
        ax1.plot(indices, df["ma10"], label="MA10", color="#0288d1", linewidth=0.9, alpha=0.9)
        ax1.plot(indices, df["ma20"], label="MA20", color="#ab47bc", linewidth=1.1, alpha=0.9)
        ax1.plot(indices, df["ma60"], label="MA60", color="#388e3c", linewidth=1.2, alpha=0.9)

        # 3. 趋势线
        line_x = np.arange(p0[0], len(df))
        line_y = slope * line_x + intercept
        ax1.plot(line_x, line_y, color="#e91e63", linestyle="--", linewidth=1.8, label="Down Trendline")

        # 4. 标注 5 浪形态节点 (纯英文字符，100% 杜绝缺失警告)
        annotate_points = [
            (p0[0], p0[2], f"Top ({p0[2]:.2f})", "top"),
            (t1[0], t1[2], "Wave 1", "bottom"),
            (p1[0], p1[2], "Wave 2", "top"),
            (t2[0], t2[2], "Wave 3", "bottom"),
            (p2[0], p2[2], "Wave 4", "top"),
            (t3[0], t3[2], f"Wave 5 ({t3[2]:.2f})", "bottom")
        ]
        for idx, price, label, pos in annotate_points:
            offset_y = 12 if pos == "top" else -15
            color = "#d32f2f" if pos == "top" else "#1976d2"
            ax1.annotate(
                label,
                xy=(idx, price),
                xytext=(0, offset_y),
                textcoords="offset points",
                ha="center",
                fontsize=9,
                fontweight="bold",
                color=color,
                arrowprops=dict(arrowstyle="->", color=color, lw=1.2)
            )

        # 5. MACD 副图
        ax2.plot(indices, df["dif"], label="DIF", color="#ffb300", linewidth=1.0)
        ax2.plot(indices, df["dea"], label="DEA", color="#29b6f6", linewidth=1.0)
        hist = df["macd_hist"].values
        ax2.bar(indices[hist >= 0], hist[hist >= 0], color="#ef5350", width=0.5, alpha=0.8)
        ax2.bar(indices[hist < 0], hist[hist < 0], color="#26a69a", width=0.5, alpha=0.8)
        ax2.axhline(0, color="gray", linestyle=":", linewidth=0.8)

        # 标题处理：如果系统未安装中文字体，标题只显示代码和纯英文，防止出现豆腐块
        display_name = name if HAS_CHINESE_FONT else ""
        title_str = f"[{symbol}] {display_name} | 5-Wave Downward + Trendline Breakout | Drop: -{max_drop}% | Date: {breakout_date}"
        
        ax1.set_title(title_str, fontsize=12, fontweight="bold", pad=10)
        ax1.grid(True, linestyle="--", alpha=0.3)
        ax2.grid(True, linestyle="--", alpha=0.3)
        ax1.legend(loc="upper right", frameon=True, fontsize=8)
        ax2.legend(loc="upper left", frameon=True, fontsize=8)

        tick_step = max(len(df) // 8, 1)
        ax2.set_xticks(indices[::tick_step])
        ax2.set_xticklabels([d.strftime("%Y-%m-%d") for d in df["date"].iloc[::tick_step]], rotation=20, fontsize=8)

        # 保存图片，彻底过滤警告
        save_path = os.path.join(IMAGE_DIR, f"{category}_{symbol}_{breakout_date}.png")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            fig.savefig(save_path, dpi=130, bbox_inches="tight")
        plt.close(fig)
        return save_path