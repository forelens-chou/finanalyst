"""
均线汇聚与向上突破量化选股 - 独立参数配置文件
"""

from dataclasses import dataclass
from typing import Tuple


@dataclass
class ScreenerConfig:
    # ==================== 1. 均线系统与周期设置 ====================
    # 评测的均线周期组合（按交易日计算）
    MA_PERIODS: Tuple[int, ...] = (5, 10, 20, 30, 60, 120, 250)

    # 次新股准入绝对底线（交易日天数）
    MIN_LISTING_DAYS: int = 35

    # 获取的历史K线总天数
    KLINE_BARS: int = 320


    # ==================== 2. 汇聚粘合度与形态判定阈值 ====================
    # 规则 A: 5条及以上均线汇聚的极差带宽阈值 (Max - Min) / Min
    BANDWIDTH_5LINES: float = 0.035  # 3.5%

    # 规则 B: 4条均线向上汇聚的极差带宽阈值
    BANDWIDTH_4LINES: float = 0.040  # 4.0%

    # 常规成交量突破倍数：当日成交量 / 5日均量
    # 达到 1.5 倍即确认为放量突破；若开启涨停豁免且近期有涨停，则此条件可免除
    VOL_RATIO_MIN: float = 1.5


    # ==================== 3. 流动性分层与防陷阱过滤 ====================
    # --- 北交所 (BJ) ---
    BSE_MIN_AMOUNT: float = 8_000_000      # 成交额保底: 800 万元
    BSE_MIN_TURNOVER: float = 1.5          # 换手率门槛: 1.5%

    # --- 沪深主板 / 创业板 / 科创板 ---
    MAIN_MIN_AMOUNT: float = 20_000_000    # 成交额主门槛: 3000 万元
    MAIN_ALT_AMOUNT: float = 10_000_000    # 换手率达标时的备用成交额底线: 2000 万元
    MAIN_MIN_TURNOVER: float = 1.1         # 换手率辅助门槛: 1.5%


    # ==================== 4. 涨停基因与放量豁免设置 (新增) ====================
    # 是否启用“近期出现过涨停，则无需当日放量也可入选”的豁免机制
    ENABLE_LIMIT_UP_BYPASS: bool = True

    # 追溯近多少根 K 线内出现过涨停板（默认 30 根交易日 K 线）
    LIMIT_UP_LOOKBACK_BARS: int = 30

    # 各板块涨停板判定涨幅门槛（考虑四舍五入，略微放宽 0.1~0.2%）
    MAIN_LIMIT_UP_PCT: float = 9.8       # 沪深主板（10% 涨停板，涨幅 >= 9.8% 判定为涨停）
    GROWTH_LIMIT_UP_PCT: float = 19.8    # 创业板/科创板（20% 涨停板，涨幅 >= 19.8% 判定为涨停）
    BSE_LIMIT_UP_PCT: float = 29.8       # 北交所（30% 涨停板，涨幅 >= 29.8% 判定为涨停）


    # ==================== 5. 网络通信与高并发控制 ====================
    MAX_WORKERS: int = 12
    REQUEST_TIMEOUT: float = 4.0
    MAX_RETRIES: int = 2
    BATCH_SIZE: int = 80