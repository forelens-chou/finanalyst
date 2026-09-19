"""
config.py - 选股系统全局参数
"""
from dataclasses import dataclass

@dataclass
class ScreenerConfig:
    # 线程与网络
    MAX_WORKERS: int = 16
    REQUEST_TIMEOUT: float = 6.0
    MAX_RETRIES: int = 2
    KLINE_BARS: int = 240          # 获取K线天数
    MIN_LISTING_DAYS: int = 120    # 剔除上市不足半年的次新股

    # 1. 基本面过滤
    MAX_PE_TTM: float = 26.0       # 最大市盈率 30
    MIN_PE_TTM: float = 0.01       # 剔除亏损标的 (PE > 0)
    MIN_AMOUNT: float = 3000000.0  # 最小成交额(元)，过滤极端停牌/死水股

    # 2. 地量参数与交易日判定
    VOLUME_LOW_WINDOW: int = 90    # 90天量能新低
    STRICT_LATEST_DAY_VOL: bool = False # True: 最低量必须是最新交易日; False: 允许最近几天内见地量(如地量后刚出大阳)
    VOLUME_TOLERANCE_DAYS: int = 3 # 当 STRICT=False 时，地量允许出现在最近 N 个交易日内

    # 3. 双底形态参数
    MIN_BOTTOM_GAP: int = 20       # 两底最小相隔K线数
    MAX_BOTTOM_GAP: int = 120      # 两底最大相隔K线数
    PEAK_BOUNCE_RATIO: float = 0.08# 两底之间反弹波峰幅度需 >= 8% (确认真实波谷)
    BOTTOM2_MAX_DROP: float = 0.03 # 底2允许击穿底1的最大跌幅 (不超过5%，即假破底)
    BOTTOM2_MAX_RISE: float = 0.08 # 底2允许高于底1的最大涨幅 (不超过8%，即微抬高底)

    # 4. CSV 导出设置
    EXPORT_CSV: bool = True
    CSV_FILENAME_PREFIX: str = "screener_results"