"""
strategy.py - 量化筛选核心计算逻辑
"""
from typing import Optional, Dict
import pandas as pd
import config as cfg

def run_strategy(df: pd.DataFrame, pure_code: str, stock_name: str) -> Optional[Dict]:
    """
    输入排序后的日K线 DataFrame，执行筛选条件
    若符合条件返回字典结果，不符合返回 None
    """
    required_bars = cfg.LONG_WINDOW + 1
    if df is None or len(df) < required_bars:
        return None

    # 1. 提取考察日 T（最新收盘那根K线）
    t_bar = df.iloc[-1]
    curr_turnover = float(t_bar["turnover_pct"])

    # 2. 计算近3个交易日的单日最低换手率 (包含 T, T-1, T-2)
    recent_3d = df.iloc[-cfg.CHECK_WINDOW:]["turnover_pct"].astype(float).tolist()
    min_turnover_3d = min(recent_3d)

    # 边界保护: 排除停牌、一字跌停等极度死锁状态
    if min_turnover_3d < cfg.MIN_VALID_TURNOVER:
        return None

    # 3. 统计窗口排除当前考察日 T
    # 历史数据切片: 剔除最后1日
    hist_df = df.iloc[:-1]

    # [30交易日窗口]: 取历史最近 30 根 K 线
    df_30 = hist_df.iloc[-cfg.SHORT_WINDOW:]
    max_turnover_30d = float(df_30["turnover_pct"].max())
    max_30d_idx = df_30["turnover_pct"].astype(float).idxmax()
    max_30d_date = str(df_30.loc[max_30d_idx, "date"])[:10]

    # [90交易日窗口]: 取历史最近 90 根 K 线
    df_90 = hist_df.iloc[-cfg.LONG_WINDOW:]
    max_turnover_90d = float(df_90["turnover_pct"].max())

    # ==================== 条件匹配判断 ====================
    # 条件 1: 90天内最高换手率 > MIN_TURNOVER_90D (如 10.0%)
    if max_turnover_90d <= cfg.MIN_TURNOVER_90D:
        return None

    # 条件 2: 30天内最高换手率 > MIN_TURNOVER_30D (如 2.9%)
    if max_turnover_30d <= cfg.MIN_TURNOVER_30D:
        return None

    # 条件 3: 缩量倍数 = 30天最高换手率 / 近3天单日最低换手率
    shrink_ratio = max_turnover_30d / min_turnover_3d

    # 缩量倍数下限判断 (如 >= 6.0倍)
    if shrink_ratio < cfg.MIN_SHRINK_RATIO:
        return None

    # 缩量倍数上限判断 (可选，若配置了上限)
    if cfg.MAX_SHRINK_RATIO is not None and shrink_ratio > cfg.MAX_SHRINK_RATIO:
        return None

    # 命中返回结构体（保证 code 为纯 6 位字符）
    return {
        "代码": str(pure_code).zfill(6),
        "名称": stock_name,
        "最新价": round(float(t_bar["close"]), 2),
        "90日最高换手(%)": round(max_turnover_90d, 2),
        "30日最高换手(%)": round(max_turnover_30d, 2),
        "30日峰值日期": max_30d_date,
        "当日换手(%)": round(curr_turnover, 2),
        "近3日最低换手(%)": round(min_turnover_3d, 2),
        "缩量倍数": round(shrink_ratio, 2)
    }