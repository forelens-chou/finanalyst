# screener.py
import pandas as pd
import numpy as np

def evaluate_pattern(df: pd.DataFrame, trend_info: dict) -> dict:
    """
    恢复最初版本的评估条件，兼顾普昂医疗与东方财富这类真实收敛标的
    """
    if trend_info is None or len(df) < 50:
        return None

    # 计算均线
    df['ma5'] = df['close'].rolling(5).mean()
    df['ma10'] = df['close'].rolling(10).mean()
    df['ma20'] = df['close'].rolling(20).mean()
    df['ma30'] = df['close'].rolling(30).mean()
    df['ma60'] = df['close'].rolling(60).mean()

    curr_idx = len(df) - 1
    curr_close = df['close'].iloc[curr_idx]
    
    # 理论阻力线价格
    line_price_now = trend_info['k'] * curr_idx + trend_info['b']
    distance_pct = (curr_close - line_price_now) / line_price_now * 100

    ma_vals = [
        df['ma5'].iloc[curr_idx],
        df['ma10'].iloc[curr_idx],
        df['ma20'].iloc[curr_idx],
        df['ma30'].iloc[curr_idx],
        df['ma60'].iloc[curr_idx]
    ]
    
    if any(np.isnan(ma_vals)):
        return None

    # 均线粘合度 (极差 / MA20)
    ma_spread = (max(ma_vals) - min(ma_vals)) / df['ma20'].iloc[curr_idx] * 100

    # 历史跌幅充分度
    p0_price = trend_info['p0_price']
    drop_pct = (p0_price - curr_close) / p0_price * 100

    # 最初版判定条件（略微给0.5%弹性以防临界遗漏）：
    cond_near_line = -3.0 <= distance_pct <= 2.0
    cond_ma_converge = ma_spread <= 4.0
    cond_drop_deep = drop_pct >= 20.0

    is_matched = cond_near_line and cond_ma_converge and cond_drop_deep

    return {
        'is_matched': is_matched,
        'curr_close': round(curr_close, 2),
        'line_price': round(line_price_now, 2),
        'distance_pct': round(distance_pct, 2),
        'ma_spread': round(ma_spread, 2),
        'drop_pct': round(drop_pct, 2),
        'p0_date': trend_info['p0_date'],
        'p0_price': round(p0_price, 2)
    }