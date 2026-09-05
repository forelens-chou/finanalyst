# visualizer.py
import os
import warnings
import numpy as np
import pandas as pd
import mplfinance as mpf
import matplotlib.pyplot as plt
from matplotlib.font_manager import fontManager

warnings.filterwarnings("ignore")

OUTPUT_BASE_DIR = "./output_charts"

def _setup_chinese_font():
    """优先载入系统开源中文字体"""
    candidates = ['WenQuanYi Micro Hei', 'Noto Sans CJK SC', 'SimHei', 'Microsoft YaHei']
    available = {f.name for f in fontManager.ttflist}
    for c in candidates:
        if c in available:
            plt.rcParams['font.sans-serif'] = [c, 'DejaVu Sans']
            plt.rcParams['axes.unicode_minus'] = False
            return True
    return False

HAS_CHINESE = _setup_chinese_font()

def plot_breakout_pattern(symbol: str, name: str, df: pd.DataFrame, trend_info: dict, result: dict, period: str = "day"):
    # 自动按周期划分存储路径: ./output_charts/day/ 或 ./output_charts/week/
    save_dir = os.path.join(OUTPUT_BASE_DIR, period)
    os.makedirs(save_dir, exist_ok=True)

    plot_df = df.copy()
    plot_df['date'] = pd.to_datetime(plot_df['date'])
    plot_df.set_index('date', inplace=True)

    n = len(plot_df)
    line_series = np.full(n, np.nan)
    p0 = trend_info['p0_idx']
    for i in range(p0, n):
        line_series[i] = trend_info['k'] * i + trend_info['b']

    addplots = [
        mpf.make_addplot(line_series, color='white', width=1.8, linestyle='solid'),
        mpf.make_addplot(plot_df['close'].rolling(5).mean(), color='yellow', width=0.8),
        mpf.make_addplot(plot_df['close'].rolling(10).mean(), color='purple', width=0.8),
        mpf.make_addplot(plot_df['close'].rolling(20).mean(), color='magenta', width=0.9),
        mpf.make_addplot(plot_df['close'].rolling(30).mean(), color='lime', width=0.9),
        mpf.make_addplot(plot_df['close'].rolling(60).mean(), color='cyan', width=1.1)
    ]

    custom_style = mpf.make_mpf_style(
        base_mpf_style='nightclouds',
        marketcolors=mpf.make_marketcolors(
            up='red', down='green', edge='inherit', wick='inherit', volume='inherit'
        )
    )

    cycle_txt = "日线" if period == "day" else "周线"
    if HAS_CHINESE:
        title = f"[{cycle_txt}] {symbol} {name} | 压力线:{result['line_price']} | 偏差:{result['distance_pct']}% | 均线带宽:{result['ma_spread']}%"
    else:
        title = f"[{period.upper()}] {symbol} | Res:{result['line_price']} | Bias:{result['distance_pct']}% | MA Spread:{result['ma_spread']}%"

    save_path = os.path.join(save_dir, f"{symbol}_{name}.png")

    mpf.plot(
        plot_df,
        type='candle',
        volume=True,
        addplot=addplots,
        style=custom_style,
        title=title,
        figsize=(12, 6),
        savefig=save_path
    )