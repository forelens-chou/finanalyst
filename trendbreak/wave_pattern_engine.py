# wave_pattern_engine.py
import numpy as np
import pandas as pd

class WavePatternEngine:
    @staticmethod
    def evaluate_wave_exhaustion(df: pd.DataFrame, p0_idx: int) -> dict:
        """
        评估大级别下跌是否穷竭（C浪急杀空间出清 + 底部扎实蓄势）
        """
        n = len(df)
        highs = df['high'].values
        lows = df['low'].values
        closes = df['close'].values

        p0_price = highs[p0_idx]
        sub_lows = lows[p0_idx:]
        
        # 寻找 P0 之后的绝对最低点（终极黄金坑，如安杰思的 39.56）
        min_offset = int(np.argmin(sub_lows))
        min_idx = p0_idx + min_offset
        min_price = lows[min_idx]

        # 1. 空间跌幅释放度（是否跌透）
        max_drawdown_pct = (p0_price - min_price) / p0_price * 100

        # 2. 见底以来的蓄势周期跨度（留足 1-2 浪筑底时间）
        base_span = (n - 1) - min_idx

        # 3. 底部右侧重心是否抬高（不创新低，右底高于绝对低点）
        recent_min = np.min(lows[-15:])
        is_higher_low = recent_min >= min_price * 1.015

        # 综合判定：跌幅充分（>=38.2%）且筑底蓄势至少20根K线且右底扎实
        is_exhausted = (max_drawdown_pct >= 38.2) and (base_span >= 20) and is_higher_low

        return {
            'is_wave_exhausted': is_exhausted,
            'max_drawdown_pct': round(max_drawdown_pct, 1),
            'base_span': base_span,
            'min_price': round(min_price, 2),
            'min_date': df['date'].iloc[min_idx]
        }

    @staticmethod
    def detect_pattern_phase(df: pd.DataFrame, line_price_now: float, distance_pct: float) -> str:
        """
        判定形态所处的实战阶段：
        1. 临界变盘：在压力线下方贴近（-3.0% ~ 0.0%）
        2. 突破初现：刚带量过线（+0.1% ~ +4.5% 且实体阳线）
        3. 回踩确认：过去曾有效突破，当前缩量回踩原压力支撑位
        """
        n = len(df)
        curr_close = df['close'].iloc[-1]
        curr_open = df['open'].iloc[-1]
        
        # 检验过去 6~20 根 K 线内是否出现过明显向上脉冲（曾站上阻力线上方 3% 以上）
        if n >= 20:
            past_closes = df['close'].iloc[-20:-3].values
            had_prior_breakout = np.any(past_closes > line_price_now * 1.03)
            # 当前回踩在阻力线附近（-2.5% ~ +2.5%）且缩量
            if had_prior_breakout and abs(distance_pct) <= 2.5:
                return "回踩确认"

        # 若最新一天放量穿透
        if (0.1 <= distance_pct <= 4.5) and (curr_close >= curr_open):
            return "突破初现"

        # 若在压力线下方蓄势贴近
        if -3.0 <= distance_pct <= 0.0:
            return "临界变盘"

        return "临界变盘"