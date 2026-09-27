# config.py
"""
系统配置模块：定义路径、筛选阈值、波浪结构和技术指标参数
"""
import os
from dataclasses import dataclass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
IMAGE_DIR = os.path.join(OUTPUT_DIR, "charts")
DATA_DIR = os.path.join(BASE_DIR, "data")

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(IMAGE_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)


@dataclass
class StrategyConfig:
    # 线程并发与网络控制
    MAX_WORKERS: int = 16
    REQUEST_TIMEOUT: float = 3.5
    MIN_AMOUNT: float = 20_000_000.0  # 过滤成交额过小的僵尸股 (2000万)

    # 1. 周期与跌幅约束（对应年初高点到近期7-8月低点）
    MIN_TOTAL_BARS: int = 120         # 至少有半年的K线历史
    LOOKBACK_BARS: int = 200          # 考察窗口，约8-10个月
    MIN_DROP_PCT: float = 0.32        # 从波段顶部到第5浪波谷的最小跌幅（32%~40%以上）
    
    # 2. 波谷与突破时间约束
    MAX_BOTTOM_RECENCY: int = 45      # 第5浪最低点必须出现在最近45根K线内（允许底部筑底）
    MIN_BOTTOM_RECENCY: int = 3       # 最低点不能是今天刚创的（给右侧走出反弹突破留出时间）
    BREAKOUT_WINDOW: int = 5          # 突破趋势线判定在最近N个交易日内发生
    BREAKOUT_CONFIRM_RATIO: float = 1.005 # 突破需站上趋势线上方0.5%以上

    # 3. 极值滤波与形态参数
    EXTREMA_ORDER: int = 8            # 局部高低点提取窗口（约1.5-2周的局部极值）
    
    # 4. 指标参数
    MACD_FAST: int = 12
    MACD_SLOW: int = 26
    MACD_SIGNAL: int = 9

cfg = StrategyConfig()