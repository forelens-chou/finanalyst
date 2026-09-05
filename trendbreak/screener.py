# screener.py
import pandas as pd
import numpy as np

def evaluate_pattern(df: pd.DataFrame, trend_info: dict) -> dict:
    """
    校验均线粘合、临近突破、量能缩量等关键转折要素
    """
    if trend_info is None or len(df) < 60:
        return None

    # 计算均线
    df['ma5'] = df['close'].rolling(5).mean()
    df['ma10'] = df['close'].rolling(10).mean()
    df['ma20'] = df['close'].rolling(20).mean()
    df['ma30'] = df['close'].rolling(30).mean()
    df['ma60'] = df['close'].rolling(60).mean()
    df['vol_ma5'] = df['volume'].rolling(5).mean()
    df['vol_ma60'] = df['volume'].rolling(60).mean()

    curr_idx = len(df) - 1
    curr_close = df['close'].iloc[curr_idx]
    
    # 1. 计算当前最新日期的理论阻力线价格
    line_price_now = trend_info['k'] * curr_idx + trend_info['b']
    
    # 距压力线理论价格的偏差百分比
    distance_pct = (curr_close - line_price_now) / line_price_now * 100

    # 2. 计算五线粘合度 (MA5, 10, 20, 30, 60)
    ma_vals = [
        df['ma5'].iloc[curr_idx],
        df['ma10'].iloc[curr_idx],
        df['ma20'].iloc[curr_idx],
        df['ma30'].iloc[curr_idx],
        df['ma60'].iloc[curr_idx]
    ]
    
    if any(np.isnan(ma_vals)):
        return None

    ma_spread = (max(ma_vals) - min(ma_vals)) / df['ma20'].iloc[curr_idx] * 100

    # 3. 计算历史跌幅充分度
    p0_price = trend_info['p0_price']
    drop_pct = (p0_price - curr_close) / p0_price * 100

    # 4. 判断变盘临界条件
    # 条件A: 现价与压力线处于临界区 (-2.5% ~ +1.5%)
    cond_near_line = -2.5 <= distance_pct <= 1.5
    # 条件B: 均线高度粘合 (带宽 <= 3.5%)
    cond_ma_converge = ma_spread <= 3.5
    # 条件C: 累计回撤幅度充分 (>= 20%)
    cond_drop_deep = drop_pct >= 20.0
    # 条件D: 成交量未发生反常巨量混乱
    vol_ratio = df['vol_ma5'].iloc[curr_idx] / (df['vol_ma60'].iloc[curr_idx] + 1e-6)

    is_matched = cond_near_line and cond_ma_converge and cond_drop_deep

    return {
        'is_matched': is_matched,
        'curr_close': curr_close,
        'line_price': round(line_price_now, 2),
        'distance_pct': round(distance_pct, 2),
        'ma_spread': round(ma_spread, 2),
        'drop_pct': round(drop_pct, 2),
        'vol_ratio': round(vol_ratio, 2),
        'p0_date': trend_info['p0_date'],
        'p0_price': round(p0_price, 2)
    }