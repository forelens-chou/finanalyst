# config.py
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

# 路径配置
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
REPORTS_DIR = BASE_DIR / "reports"

DATA_DIR.mkdir(parents=True, exist_ok=True)
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

@dataclass
class StrategyConfig:
    # ---------------- 运行时与网络配置 ----------------
    MAX_WORKERS: int = 16
    REQUEST_TIMEOUT: float = 3.0

    # ---------------- 基础流动性与标的初筛 ----------------
    MIN_AMOUNT: float = 50_000_000.0        # 盘前快照最低成交额 (默认5000万)
    MIN_KLINE_BARS: int = 65                # 参与特征计算所需的最小K线根数

    # ---------------- 方案 A：筹码集中 + 放量突破 ----------------
    A_LOOKBACK_WINDOW: int = 60            # 筹码及平台分析回溯周期
    A_VPVR_BINS: int = 100                 # VPVR 价格区间切分档数
    A_MAX_CONCENTRATION_RATIO: float = 0.12 # 70%筹码覆盖区间占当前价格的最大比率 (<=12%代表高度集中)
    A_VOLUME_SURGE_FACTOR: float = 2.0     # 当日成交量对20日均量的放大倍数
    A_MIN_PCT_CHANGE: float = 3.5          # 突破当日最低涨幅限制(%)
    A_MIN_BODY_RATIO: float = 0.55         # 实体占比下限 (实体/总振幅)
    A_MA_PERIODS: List[int] = field(default_factory=lambda: [5, 10, 20, 30, 60])

    # ---------------- 方案 B：量价 + RSI 顶/底背离 ----------------
    B_RSI_PERIOD: int = 14                 # RSI 计算周期
    B_PIVOT_LEFT: int = 3                  # 极值点左侧确认周期
    B_PIVOT_RIGHT: int = 3                 # 极值点右侧确认周期 (延迟R根Bar确认，消除未来函数)
    B_MIN_PEAK_INTERVAL: int = 5           # 双峰/双谷之间的最小时间跨度
    B_MAX_PEAK_INTERVAL: int = 45          # 双峰/双谷之间的最大时间跨度
    B_TOP_RSI_OVERBOUGHT: float = 68.0     # 顶背离前高必须触及的超买分界
    B_BOTTOM_RSI_OVERSOLD: float = 32.0    # 底背离前低必须触及的超卖分界
    B_CONFIRM_MA: int = 20                 # 右侧破位/站上确认均线周期

cfg = StrategyConfig()