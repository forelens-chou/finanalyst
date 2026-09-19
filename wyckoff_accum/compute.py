# compute.py
from typing import Dict, Optional
import numpy as np
import pandas as pd
from config import cfg, StrategyConfig

def compute_indicators(df: pd.DataFrame, custom_cfg: Optional[StrategyConfig] = None) -> pd.DataFrame:
    """计算基础技术指标与K线属性"""
    c = custom_cfg or cfg
    df = df.copy()

    # 均线系统
    df["ma5"] = df["close"].rolling(5).mean()
    df["ma10"] = df["close"].rolling(10).mean()
    df["ma20"] = df["close"].rolling(20).mean()
    df["ma30"] = df["close"].rolling(30).mean()
    df["vma20"] = df["volume"].rolling(20).mean()

    # 均线粘合度 (MA5, 10, 20, 30 极差与收盘价比例)
    ma_max = df[["ma5", "ma10", "ma20", "ma30"]].max(axis=1)
    ma_min = df[["ma5", "ma10", "ma20", "ma30"]].min(axis=1)
    df["ma_spread"] = (ma_max - ma_min) / df["close"]

    # K线实体占比与全天振幅
    df["candle_body"] = (df["close"] - df["open"]).abs() / df["close"]
    df["candle_amp"] = (df["high"] - df["low"]) / df["close"]

    # 试盘脉冲标记 (放量冲高)
    df["is_trial"] = (
        (df["turnover_pct"] >= c.TRIAL_TURNOVER_MIN) &
        ((df["high"] - df["open"]) / df["open"] >= c.TRIAL_INTRA_GAIN_MIN)
    ).astype(int)

    # MACD 指标 (用于检测底背离)
    exp1 = df["close"].ewm(span=12, adjust=False).mean()
    exp2 = df["close"].ewm(span=26, adjust=False).mean()
    df["dif"] = exp1 - exp2
    df["dea"] = df["dif"].ewm(span=9, adjust=False).mean()
    df["macd"] = 2 * (df["dif"] - df["dea"])

    return df

def detect_bottom_structure(df: pd.DataFrame, custom_cfg: Optional[StrategyConfig] = None) -> Dict[str, object]:
    """严谨的双底/三底检测"""
    c = custom_cfg or cfg
    if len(df) < c.BASE_WINDOW:
        return {"valid": False}

    lows = df["low"].values
    highs = df["high"].values
    difs = df["dif"].values

    l2_idx = len(df) - 1 - int(np.argmin(lows[-3:]))
    l2_price = lows[l2_idx]

    search_end = len(df) - c.BOTTOM_INTERVAL_MIN
    search_start = max(0, len(df) - c.BASE_WINDOW)
    if search_end <= search_start:
        return {"valid": False}

    search_lows = lows[search_start:search_end]
    rel_l1_idx = int(np.argmin(search_lows))
    l1_idx = search_start + rel_l1_idx
    l1_price = lows[l1_idx]

    # 1. 两次探底价格容差
    diff_pct = abs(l2_price - l1_price) / l1_price
    if diff_pct > c.BOTTOM_PRICE_TOLERANCE:
        return {"valid": False}

    # 2. 颈线反弹幅度
    intermediate_high = np.max(highs[l1_idx:l2_idx]) if l2_idx > l1_idx else 0
    rebound_ratio = (intermediate_high - l1_price) / l1_price if l1_price > 0 else 0
    if rebound_ratio < c.BOTTOM_REBOUND_MIN:
        return {"valid": False}

    # 3. MACD 底背离
    is_divergence = difs[l2_idx] > difs[l1_idx]
    hard_stop = min(l1_price, l2_price) * (1.0 - c.HARD_STOP_LOSS_PCT)

    return {
        "valid": True,
        "l1_price": round(l1_price, 2),
        "l2_price": round(l2_price, 2),
        "l1_date": df.iloc[l1_idx]["date"].strftime("%Y-%m-%d"),
        "rebound_ratio": round(rebound_ratio * 100, 2),
        "is_divergence": is_divergence,
        "hard_stop_price": round(hard_stop, 2)
    }