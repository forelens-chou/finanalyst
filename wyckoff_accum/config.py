# config.py
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "output"

DATA_DIR.mkdir(exist_ok=True, parents=True)
OUTPUT_DIR.mkdir(exist_ok=True, parents=True)

@dataclass
class StrategyConfig:
    mode: str = "subnew"

    # 1. 股票池基础属性
    MIN_LISTING_DAYS: int = 60
    MAX_LISTING_DAYS: int = 360
    MAX_DRAWDOWN_THRESHOLD: float = -0.45
    MIN_AMOUNT: float = 5000000.0   # 基础日成交额(元)
    DRAWDOWN_WINDOW: int = 250      # 回撤基准窗口(天)

    # 2. 平台筑底与试盘
    BASE_WINDOW: int = 60
    BASE_MAX_AMPLITUDE: float = 0.35
    MA_CONVERGENCE_THRESHOLD: float = 0.028
    TRIAL_TURNOVER_MIN: float = 7.5
    TRIAL_INTRA_GAIN_MIN: float = 0.035
    TRIAL_MIN_COUNT: int = 1
    TRIAL_MAX_COUNT: int = 8
    TRIAL_RECENCY_DAYS: int = 25

    # 3. 探底与地量小K线 (潜伏核心)
    BOTTOM_INTERVAL_MIN: int = 8
    BOTTOM_PRICE_TOLERANCE: float = 0.035
    BOTTOM_REBOUND_MIN: float = 0.07
    CANDLE_BODY_MAX: float = 0.018
    CANDLE_AMPLITUDE_MAX: float = 0.035
    VOLUME_SHRINK_RATIO: float = 0.45
    TURNOVER_SHRINK_MAX: float = 3.5
    HARD_STOP_LOSS_PCT: float = 0.015

    # 4. 盘中突破
    BREAKOUT_GAIN_MIN: float = 0.06
    BREAKOUT_VOLUME_RATIO: float = 2.5

    # 5. 系统网络 (腾讯接口硬性上限为 320 根)
    KLINE_BARS: int = 320
    MAX_WORKERS: int = 16
    REQUEST_TIMEOUT: float = 1.5
    MAX_RETRIES: int = 3 

# config.py 的 StrategyConfig 中新增以下字段：
    FLOAT_CAP_MIN: float = 4.0e8      # 流通市值下限: 10 亿元 (防微盘退市风险)
    FLOAT_CAP_MAX: float = 125.0e8      # 流通市值上限: 80 亿元 (彻底剔除大市值迟钝股)
    AVG_TURNOVER_MIN: float = 1.0      # 60日平均换手率底线 (1.0%, 排除死水冷门股)
    MA_SLOPE_MAX: float = 0.06         # MA30 在 20 日内的倾斜率绝对值 (<= 4%, 必须基本走平)   

def get_config(mode: str = "subnew") -> StrategyConfig:
    if mode == "all":
        return StrategyConfig(
            mode="all",
            MIN_LISTING_DAYS=60,            # 只要有 60 根 K 线就允许计算箱体
            MAX_LISTING_DAYS=99999,         # 老股不设上限！
            MAX_DRAWDOWN_THRESHOLD=-0.38,   # 适度放宽超跌幅度至 38%
            MIN_AMOUNT=10000000.0,          # 1000万日成交额
            DRAWDOWN_WINDOW=250,
            
            BASE_WINDOW=60,
            BASE_MAX_AMPLITUDE=0.38,        # 箱体振幅适度放宽到 38%
            MA_CONVERGENCE_THRESHOLD=0.035, # 均线粘合度 3.5%
            
            TRIAL_TURNOVER_MIN=2.5,         # 老股异动试盘换手 >= 2.5%
            TRIAL_INTRA_GAIN_MIN=0.035,
            
            FLOAT_CAP_MIN=4.0e8,           # 市值在 10 亿 ~ 120 亿之间
            FLOAT_CAP_MAX=120.0e8,
            AVG_TURNOVER_MIN=0.8,           # 老股 60 日日均换手 >= 0.8%
            MA_SLOPE_MAX=0.06,             # 均线基本走平
            
            TURNOVER_SHRINK_MAX=2.0,
            VOLUME_SHRINK_RATIO=0.55,
            CANDLE_BODY_MAX=0.020,
            CANDLE_AMPLITUDE_MAX=0.038
        )
    else:
        # 次新模式：上市天数放宽到 45 ~ 450 天（覆盖上市约 1 年半内的次新）
        return StrategyConfig(
            mode="subnew",
            MIN_LISTING_DAYS=45,            # 从 45 天开始考察
            MAX_LISTING_DAYS=450,           # 放宽至 450 天
            MAX_DRAWDOWN_THRESHOLD=-0.40,   # 超跌 40%
            MIN_AMOUNT=5000000.0,
            DRAWDOWN_WINDOW=400,
            BASE_WINDOW=60,
            BASE_MAX_AMPLITUDE=0.38,
            MA_CONVERGENCE_THRESHOLD=0.032,
            FLOAT_CAP_MIN=5.0e8,
            FLOAT_CAP_MAX=80.0e8,
            AVG_TURNOVER_MIN=1.5,
            MA_SLOPE_MAX=0.045,
            TRIAL_TURNOVER_MIN=7.0,
            TURNOVER_SHRINK_MAX=3.5
        )

cfg = get_config("subnew")