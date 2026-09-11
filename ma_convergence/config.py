"""
均线汇聚与向上突破量化选股 - 独立参数配置文件
"""

from dataclasses import dataclass
from typing import Tuple


@dataclass
class ScreenerConfig:
    # ==================== 1. 均线系统与周期设置 ====================
    MA_PERIODS: Tuple[int, ...] = (5, 10, 20, 30, 60, 120, 250)
    MIN_LISTING_DAYS: int = 35        # 次新股准入绝对底线（交易日）
    KLINE_BARS: int = 320             # 获取历史 K 线天数

    # ==================== 2. 汇聚粘合度与形态判定阈值 ====================
    BANDWIDTH_5LINES: float = 0.035   # 5线粘合极差率 <= 3.5%
    BANDWIDTH_4LINES: float = 0.040   # 4线粘合极差率 <= 4.0%
    VOL_RATIO_MIN: float = 1.4        # 当日成交量 / 5日均量 >= 1.5 倍

    # ==================== 3. 流动性分层过滤 ====================
    # --- 北交所 (BJ) ---
    BSE_MIN_AMOUNT: float = 8_000_000       # 成交额保底: 800 万元
    BSE_MIN_TURNOVER: float = 1.4           # 换手率门槛: 1.5%

    # --- 沪深主板 / 创业板 / 科创板 ---
    MAIN_MIN_AMOUNT: float = 20_000_000     # 成交额直接放行门槛: 3000 万元
    MAIN_ALT_AMOUNT: float = 10_000_000     # 换手率达标时备用门槛: 2000 万元
    MAIN_MIN_TURNOVER: float = 1.4          # 换手率辅助门槛: 1.5%

    # ==================== 4. 涨停基因与条件豁免设置 ====================
    LIMIT_UP_LOOKBACK_BARS: int = 50        #30
    LIMIT_UP_WAIVE_4MA_UPWARD: bool = True  # 30天内有涨停时，4条均线仅需汇聚（豁免必须全部向上）
    LIMIT_UP_WAIVE_VOLUME: bool = True      # 30天内有涨停时，豁免当日放量要求

    MAIN_LIMIT_UP_PCT: float = 9.8        # 沪深主板
    GROWTH_LIMIT_UP_PCT: float = 10.8     # 创业板/科创板 19.8
    BSE_LIMIT_UP_PCT: float = 12.8        # 北交所 29.8

    # ==================== 5. 自定义股票池文档设置 (新增) ====================
    # 当指定外部股票池文件时，是否跳过流动性初筛
    # True: 传入文档里的标的全部评测形态，不因今天成交额/换手率低而被提前误杀
    # False: 依然严格执行主板3000万/北交所800万的过滤条件
    CUSTOM_POOL_SKIP_LIQUIDITY: bool = True

    # ==================== 6. 网络通信与高并发控制 ====================
    MAX_WORKERS: int = 12
    REQUEST_TIMEOUT: float = 4.0
    MAX_RETRIES: int = 2
    BATCH_SIZE: int = 80