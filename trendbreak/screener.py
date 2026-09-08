# screener.py
import pandas as pd
import numpy as np

def evaluate_pattern(
    df: pd.DataFrame, 
    macro_trend: dict, 
    sub_trend: dict = None, 
    time_info: dict = None, 
    wave_info: dict = None, 
    is_dual_track: bool = False, 
    phase_str: str = "临界变盘",
    is_subnew: bool = False
) -> dict:
    if macro_trend is None or len(df) < 40:
        return None

    # 计算均线
    df['ma5'] = df['close'].rolling(5).mean()
    df['ma10'] = df['close'].rolling(10).mean()
    df['ma20'] = df['close'].rolling(20).mean()
    df['ma30'] = df['close'].rolling(30).mean()
    if not is_subnew:
        df['ma60'] = df['close'].rolling(60).mean()

    curr_idx = len(df) - 1
    curr_close = df['close'].iloc[curr_idx]
    curr_open = df['open'].iloc[curr_idx]
    
    line_price_now = macro_trend['k'] * curr_idx + macro_trend['b']
    distance_pct = (curr_close - line_price_now) / line_price_now * 100

    # =========================================================
    # 【核心改进：次新股均线动态自适应】
    # 若是次新股，坚决剔除首发暴涨扭曲的 MA60，只考核 5/10/20/30 4线粘合
    # =========================================================
    if is_subnew:
        ma_vals = [
            df['ma5'].iloc[curr_idx],
            df['ma10'].iloc[curr_idx],
            df['ma20'].iloc[curr_idx],
            df['ma30'].iloc[curr_idx]
        ]
        ma_limit = 5.2  # 适度给次新股弹性
    else:
        ma_vals = [
            df['ma5'].iloc[curr_idx],
            df['ma10'].iloc[curr_idx],
            df['ma20'].iloc[curr_idx],
            df['ma30'].iloc[curr_idx],
            df['ma60'].iloc[curr_idx]
        ]
        ma_limit = 4.8

    if any(np.isnan(ma_vals)):
        return None

    ma_spread = (max(ma_vals) - min(ma_vals)) / df['ma20'].iloc[curr_idx] * 100
    p0_price = macro_trend['p0_price']
    drop_pct = (p0_price - curr_close) / p0_price * 100

    # 门槛判定
    cond_near_line = -3.5 <= distance_pct <= 3.5
    cond_ma_converge = ma_spread <= ma_limit
    # 次新股上市时间短，跌幅门槛由 18% 适度降为 14%
    cond_drop_deep = drop_pct >= (14.0 if is_subnew else 18.0)

    is_matched = cond_near_line and cond_ma_converge and cond_drop_deep
    if not is_matched:
        return None

    # 首阳放量判定
    prev_close = df['close'].iloc[-2] if len(df) >= 2 else curr_close
    pct_change = (curr_close - prev_close) / prev_close * 100
    is_yang = (curr_close > curr_open) and (0.3 <= pct_change <= 7.0)

    vol_curr = df['volume'].iloc[curr_idx]
    vol_ma5_prev = df['volume'].iloc[-6:-1].mean() if len(df) >= 6 else vol_curr
    vol_ratio = vol_curr / (vol_ma5_prev + 1e-6)
    is_volume_breakout = is_yang and (vol_ratio >= 1.25)

    # 双线共振
    is_dual_line = False
    sub_line_price = 0.0
    if sub_trend:
        sub_line_price = sub_trend['k'] * curr_idx + sub_trend['b']
        sub_dist_pct = (curr_close - sub_line_price) / sub_line_price * 100
        if -3.5 <= sub_dist_pct <= 3.5:
            is_dual_line = True

    is_time_hit = time_info.get('is_time_resonance', False) if time_info else False
    time_desc = time_info.get('resonance_desc', '无') if time_info else '无'
    is_wave_hit = wave_info.get('is_wave_exhausted', False) if wave_info else False
    max_dd = wave_info.get('max_drawdown_pct', 0.0) if wave_info else 0.0

    # 综合打分
    score = 40.0 - (abs(distance_pct) * 2.5 + ma_spread * 2.5)
    score = max(25.0, score)
    if is_dual_track: score += 15.0
    if is_volume_breakout: score += 15.0
    if is_time_hit: score += 10.0
    if is_dual_line: score += 10.0
    if is_wave_hit: score += 10.0

    score = min(100.0, round(score, 1))

    return {
        'is_matched': True,
        'phase': phase_str,
        'score': score,
        'curr_close': round(curr_close, 2),
        'line_price': round(line_price_now, 2),
        'sub_line_price': round(sub_line_price, 2) if is_dual_line else 0.0,
        'distance_pct': round(distance_pct, 2),
        'ma_spread': round(ma_spread, 2),
        'drop_pct': round(drop_pct, 2),
        'is_dual_track': "是" if is_dual_track else "否",
        'is_volume_breakout': "是" if is_volume_breakout else "否",
        'vol_ratio': round(vol_ratio, 2),
        'is_dual_line': "是" if is_dual_line else "否",
        'is_time_resonance': "是" if is_time_hit else "否",
        'time_desc': time_desc,
        'is_wave_exhausted': "是" if is_wave_hit else "否",
        'max_drawdown_pct': max_dd,
        'p0_date': macro_trend['p0_date'],
        'p0_price': round(p0_price, 2)
    }