# visualizer.py
import os
import numpy as np
import pandas as pd
import mplfinance as mpf
import matplotlib.pyplot as plt

# 兼容中文字体设置
plt.rcParams['font.sans-serif'] = ['SimHei', 'DejaVu Sans', 'Arial']
plt.rcParams['axes.unicode_minus'] = False

OUTPUT_DIR = "./output_charts"
os.makedirs(OUTPUT_DIR, exist_ok=True)

def plot_breakout_pattern(symbol: str, name: str, df: pd.DataFrame, trend_info: dict, result: dict):
    """
    复现与实盘软件一致的高级形态图
    """
    plot_df = df.copy()
    plot_df['date'] = pd.to_datetime(plot_df['date'])
    plot_df.set_index('date', inplace=True)

    n = len(plot_df)
    line_series = np.full(n, np.nan)
    
    # 构建趋势线绘图序列
    p0 = trend_info['p0_idx']
    for i in range(p0, n):
        line_series[i] = trend_info['k'] * i + trend_info['b']

    # 构造绘图附加对象
    addplots = [
        # 白色压制线（加粗醒目）
        mpf.make_addplot(line_series, color='white', width=1.5, linestyle='solid'),
        # 彩色均线群
        mpf.make_addplot(plot_df['close'].rolling(5).mean(), color='yellow', width=0.8),
        mpf.make_addplot(plot_df['close'].rolling(10).mean(), color='purple', width=0.8),
        mpf.make_addplot(plot_df['close'].rolling(20).mean(), color='magenta', width=0.9),
        mpf.make_addplot(plot_df['close'].rolling(30).mean(), color='lime', width=0.9),
        mpf.make_addplot(plot_df['close'].rolling(60).mean(), color='cyan', width=1.1)
    ]

    # 自定义深色看盘配色风格
    custom_style = mpf.make_mpf_style(
        base_mpf_style='nightclouds',
        rc={
            'font.family': 'SimHei',
            'axes.unicode_minus': False
        },
        marketcolors=mpf.make_marketcolors(
            up='red', down='green', edge='inherit', wick='inherit', volume='inherit'
        )
    )

    title = f"{symbol} {name} | 阻力价: {result['line_price']} | 偏差: {result['distance_pct']}% | 均线带宽: {result['ma_spread']}%"
    save_path = os.path.join(OUTPUT_DIR, f"{symbol}_{name}.png")

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
    print(f"-> 命中形态图已输出至: {save_path}")