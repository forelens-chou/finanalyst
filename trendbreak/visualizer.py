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
    candidates = ['WenQuanYi Micro Hei', 'Noto Sans CJK SC', 'SimHei', 'Microsoft YaHei']
    available = {f.name for f in fontManager.ttflist}
    for c in candidates:
        if c in available:
            plt.rcParams['font.sans-serif'] = [c, 'DejaVu Sans']
            plt.rcParams['axes.unicode_minus'] = False
            return True
    return False

HAS_CHINESE = _setup_chinese_font()

def plot_breakout_pattern(
    symbol: str, 
    name: str, 
    df: pd.DataFrame, 
    macro_trend: dict, 
    sub_trend: dict, 
    result: dict, 
    support_info: dict = None, 
    period: str = "day"
):
    save_dir = os.path.join(OUTPUT_BASE_DIR, period)
    os.makedirs(save_dir, exist_ok=True)

    plot_df = df.copy()
    plot_df['date'] = pd.to_datetime(plot_df['date'])
    plot_df.set_index('date', inplace=True)

    n = len(plot_df)
    
    # 1. 宏观白色压制线
    macro_series = np.full(n, np.nan)
    p0 = macro_trend['p0_idx']
    for i in range(p0, n):
        macro_series[i] = macro_trend['k'] * i + macro_trend['b']

    addplots = [
        mpf.make_addplot(macro_series, color='white', width=1.8, linestyle='solid'),
        mpf.make_addplot(plot_df['close'].rolling(5).mean(), color='yellow', width=0.8),
        mpf.make_addplot(plot_df['close'].rolling(10).mean(), color='purple', width=0.8),
        mpf.make_addplot(plot_df['close'].rolling(20).mean(), color='magenta', width=0.9),
        mpf.make_addplot(plot_df['close'].rolling(30).mean(), color='lime', width=0.9),
        mpf.make_addplot(plot_df['close'].rolling(60).mean(), color='cyan', width=1.1)
    ]

    # 2. 次级粉色压制线（若存在）
    if sub_trend:
        sub_series = np.full(n, np.nan)
        p_sub = sub_trend['p_sub_idx']
        for i in range(p_sub, n):
            sub_series[i] = sub_trend['k'] * i + sub_trend['b']
        addplots.append(mpf.make_addplot(sub_series, color='magenta', width=1.6, linestyle='solid'))

    # 3. 青色支撑虚线（双轨收敛）
    if result.get('is_dual_track') == "是" and support_info:
        sup_series = np.full(n, np.nan)
        sup_series[-25:] = support_info['support_price']
        addplots.append(mpf.make_addplot(sup_series, color='deepskyblue', width=1.2, linestyle='dashed'))

    custom_style = mpf.make_mpf_style(
        base_mpf_style='nightclouds',
        marketcolors=mpf.make_marketcolors(
            up='red', down='green', edge='inherit', wick='inherit', volume='inherit'
        )
    )

    cycle_txt = "日线" if period == "day" else "周线"
    tags = [f"阶段:{result['phase']}", f"评分:{result['score']}"]
    if result['is_dual_line'] == "是": tags.append("双线共振")
    if result['is_time_resonance'] == "是": tags.append(f"时间:{result['time_desc']}")

    tag_str = " | ".join(tags)
    if HAS_CHINESE:
        title = f"[{cycle_txt}] {symbol} {name} | {tag_str}"
    else:
        title = f"[{period.upper()}] {symbol} | Phase:{result['phase']} | Score:{result['score']}"

    save_path = os.path.join(save_dir, f"{symbol}_{name}.png")

    # 修复点：X轴是时间索引，vlines必须传入对应的日期对象
    plot_kwargs = {
        'type': 'candle',
        'volume': True,
        'addplot': addplots,
        'style': custom_style,
        'title': title,
        'figsize': (12, 6),
        'savefig': save_path
    }
    
    try:
        # 正确传入真实日期
        target_dates = [plot_df.index[p0], plot_df.index[-1]]
        plot_kwargs['vlines'] = dict(vlines=target_dates, colors='gold', linestyle='-.', linewidths=1.0)
    except Exception:
        pass

    mpf.plot(plot_df, **plot_kwargs)