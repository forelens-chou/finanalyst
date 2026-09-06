# screener.py
import pandas as pd
import numpy as np

def evaluate_pattern(df: pd.DataFrame, trend_info: dict, is_dual_track: bool = False) -> dict:
    """
    变盘评估模型：包含首阳放量判定与多维综合评分
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
    curr_open = df['open'].iloc[curr_idx]
    
    # 压力线理论价
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

    # 均线粘合度
    ma_spread = (max(ma_vals) - min(ma_vals)) / df['ma20'].iloc[curr_idx] * 100
    # 跌幅
    p0_price = trend_info['p0_price']
    drop_pct = (p0_price - curr_close) / p0_price * 100

    # 门槛条件
    cond_near_line = -3.0 <= distance_pct <= 2.0
    cond_ma_converge = ma_spread <= 4.2
    cond_drop_deep = drop_pct >= 20.0
    is_matched = cond_near_line and cond_ma_converge and cond_drop_deep

    if not is_matched:
        return None

    # =========================================================
    # 【特性 1：右侧首阳放量异动检测】
    # =========================================================
    # 当日收阳（收盘 > 开盘），且收盘涨幅在 0.5% ~ 6.5% 之间
    prev_close = df['close'].iloc[-2] if len(df) >= 2 else curr_close
    pct_change = (curr_close - prev_close) / prev_close * 100
    is_yang = (curr_close > curr_open) and (0.3 <= pct_change <= 6.5)

    # 成交量放大检测：当日成交量较前5日均量放大 1.3 倍以上
    vol_curr = df['volume'].iloc[curr_idx]
    vol_ma5_prev = df['volume'].iloc[-6:-1].mean() if len(df) >= 6 else vol_curr
    vol_ratio = vol_curr / (vol_ma5_prev + 1e-6)
    
    is_volume_breakout = is_yang and (vol_ratio >= 1.25)

    # =========================================================
    # 【特性 2：多维综合评分系统（满分 100）】
    # =========================================================
    # 基础分 (最高 65 分)：均线越粘合、距离压力线越近得分越高
    score = 65.0 - (abs(distance_pct) * 4.0 + ma_spread * 3.5)
    score = max(40.0, score)

    # 双轨收敛加成：+20 分
    if is_dual_track:
        score += 20.0

    # 首阳放量加成：+15 分
    if is_volume_breakout:
        score += 15.0

    score = min(100.0, round(score, 1))

    return {
        'is_matched': True,
        'curr_close': round(curr_close, 2),
        'line_price': round(line_price_now, 2),
        'distance_pct': round(distance_pct, 2),
        'ma_spread': round(ma_spread, 2),
        'drop_pct': round(drop_pct, 2),
        'is_dual_track': "是" if is_dual_track else "否",
        'is_volume_breakout': "是" if is_volume_breakout else "否",
        'vol_ratio': round(vol_ratio, 2),
        'score': score,
        'p0_date': trend_info['p0_date'],
        'p0_price': round(p0_price, 2)
    }