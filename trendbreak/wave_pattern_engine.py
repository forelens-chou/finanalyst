# wave_pattern_engine.py
import numpy as np
import pandas as pd

class WavePatternEngine:
    @staticmethod
    def evaluate_wave_exhaustion(df: pd.DataFrame, p0_idx: int, is_subnew: bool = False) -> dict:
        n = len(df)
        highs = df['high'].values
        lows = df['low'].values

        p0_price = highs[p0_idx]
        sub_lows = lows[p0_idx:]
        
        min_offset = int(np.argmin(sub_lows))
        min_idx = p0_idx + min_offset
        min_price = lows[min_idx]

        max_drawdown_pct = (p0_price - min_price) / p0_price * 100
        base_span = (n - 1) - min_idx

        recent_min = np.min(lows[-10:])
        is_higher_low = recent_min >= min_price * 1.01

        # 门槛自适应：常规股跌幅>=38.2%、筑底>=20天；次新股跌幅>=25%、筑底>=10天
        min_dd_limit = 25.0 if is_subnew else 38.2
        min_base_span = 10 if is_subnew else 20

        is_exhausted = (max_drawdown_pct >= min_dd_limit) and (base_span >= min_base_span) and is_higher_low

        return {
            'is_wave_exhausted': is_exhausted,
            'max_drawdown_pct': round(max_drawdown_pct, 1),
            'base_span': base_span,
            'min_price': round(min_price, 2),
            'min_date': df['date'].iloc[min_idx]
        }

    @staticmethod
    def detect_pattern_phase(df: pd.DataFrame, line_price_now: float, distance_pct: float) -> str:
        n = len(df)
        curr_close = df['close'].iloc[-1]
        curr_open = df['open'].iloc[-1]
        
        if n >= 20:
            past_closes = df['close'].iloc[-20:-3].values
            had_prior_breakout = np.any(past_closes > line_price_now * 1.03)
            if had_prior_breakout and abs(distance_pct) <= 2.5:
                return "回踩确认"

        if (0.1 <= distance_pct <= 4.5) and (curr_close >= curr_open):
            return "突破初现"

        if -3.5 <= distance_pct <= 0.0:
            return "临界变盘"

        return "临界变盘"