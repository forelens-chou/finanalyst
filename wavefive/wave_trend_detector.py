# wave_trend_detector.py
"""
形态量化内核模块 (高适应性版本)：
1. 自适应识别下行浪形与压力线
2. 指数/板块跌幅门槛与个股动态适配
3. 容许突破后回踩确认的右侧形态
"""
from typing import Dict, Optional, Tuple
import numpy as np
import pandas as pd

from config import StrategyConfig, cfg


class WaveTrendDetector:
    def __init__(self, config: Optional[StrategyConfig] = None):
        self.cfg = config or cfg

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["ma5"] = df["close"].rolling(5).mean()
        df["ma10"] = df["close"].rolling(10).mean()
        df["ma20"] = df["close"].rolling(20).mean()
        df["ma30"] = df["close"].rolling(30).mean()
        df["ma60"] = df["close"].rolling(60).mean()

        ema_fast = df["close"].ewm(span=self.cfg.MACD_FAST, adjust=False).mean()
        ema_slow = df["close"].ewm(span=self.cfg.MACD_SLOW, adjust=False).mean()
        df["dif"] = ema_fast - ema_slow
        df["dea"] = df["dif"].ewm(span=self.cfg.MACD_SIGNAL, adjust=False).mean()
        df["macd_hist"] = (df["dif"] - df["dea"]) * 2
        return df

    def detect_pattern(self, df: pd.DataFrame, is_sector: bool = False) -> Tuple[bool, Optional[Dict]]:
        if len(df) < 70:
            return False, None

        # 截取过去 200 根 K 线
        df = df.tail(200).copy().reset_index(drop=True)
        df = self.calculate_indicators(df)
        total_len = len(df)

        highs = df["high"].values
        lows = df["low"].values
        closes = df["close"].values

        # 1. 寻找主周期的绝对顶峰 P0 (发生在至少 20 根 K 线前)
        p0_limit = total_len - 15
        if p0_limit <= 10:
            return False, None
        p0_idx = int(np.argmax(highs[:p0_limit]))

        # 2. 寻找 P0 之后波段的绝对最低点 T3
        sub_lows = lows[p0_idx + 5 :]
        if len(sub_lows) < 5:
            return False, None
        t3_idx = int(np.argmin(sub_lows) + (p0_idx + 5))

        # 最低点不能是今天，至少已筑底或反弹 1 天以上
        bars_since_bottom = total_len - 1 - t3_idx
        if bars_since_bottom < 1:
            return False, None

        # 3. 跌幅深度自适应：板块/指数只需跌幅 >= 18%，个股 >= 28%
        min_drop = 0.18 if is_sector else 0.28
        max_drop = (highs[p0_idx] - lows[t3_idx]) / highs[p0_idx]
        if max_drop < min_drop:
            return False, None

        # 4. 寻找下行主压力线的控制反弹点 (浪2/浪4高点)
        mid_highs = highs[p0_idx + 3 : t3_idx]
        if len(mid_highs) == 0:
            # 若最低点就在 P0 附近，跳过
            return False, None

        # 候选控制点
        candidate_anchors = []
        for offset, h in enumerate(mid_highs):
            idx = p0_idx + 3 + offset
            if idx > 0 and idx < total_len - 1:
                if highs[idx] >= highs[idx - 1] and highs[idx] >= highs[idx + 1]:
                    candidate_anchors.append(idx)

        if not candidate_anchors:
            candidate_anchors.append(int(p0_idx + 3 + np.argmax(mid_highs)))

        # 5. 趋势线拟合与突破判定
        best_line = None
        for anchor_idx in candidate_anchors:
            x1, y1 = float(p0_idx), float(highs[p0_idx])
            x2, y2 = float(anchor_idx), float(highs[anchor_idx])
            if x2 <= x1 or y2 >= y1:
                continue

            slope = (y2 - y1) / (x2 - x1)
            intercept = y1 - slope * x1

            # 核心：检查突破
            # 最近 15 天内，价格曾经上穿趋势线，且目前依然维持在趋势线附近或上方
            recent_idx = np.arange(total_len - 15, total_len)
            recent_trend = slope * recent_idx + intercept
            recent_closes = closes[-15:]

            breakouts = recent_closes >= recent_trend
            if np.any(breakouts):
                # 即使突破后回踩，最新收盘价不能跌破趋势线 3% 以上
                if closes[-1] >= (recent_trend[-1] * 0.97):
                    first_break_offset = int(np.where(breakouts)[0][0])
                    breakout_idx = total_len - 15 + first_break_offset
                    best_line = (slope, intercept, anchor_idx, breakout_idx)
                    break

        if not best_line:
            return False, None

        slope, intercept, anchor_idx, breakout_idx = best_line

        # 6. 构造图表坐标与技术指标
        p1_idx = anchor_idx
        t1_idx = int((p0_idx + p1_idx) // 2)
        p2_idx = int((anchor_idx + t3_idx) // 2) if t3_idx > anchor_idx else anchor_idx
        t2_idx = int((p1_idx + p2_idx) // 2)

        dif_vals = df["dif"].values
        macd_divergence = dif_vals[-1] > dif_vals[t3_idx]
        ma_rebound = closes[-1] >= df["ma10"].iloc[-1]

        score = int(max_drop * 100) + (15 if macd_divergence else 0) + (10 if ma_rebound else 0)

        match_info = {
            "p0": (p0_idx, str(df["date"].iloc[p0_idx].date()), highs[p0_idx]),
            "p1": (p1_idx, str(df["date"].iloc[p1_idx].date()), highs[p1_idx]),
            "p2": (p2_idx, str(df["date"].iloc[p2_idx].date()), highs[p2_idx]),
            "t1": (t1_idx, str(df["date"].iloc[t1_idx].date()), lows[t1_idx]),
            "t2": (t2_idx, str(df["date"].iloc[t2_idx].date()), lows[t2_idx]),
            "t3": (t3_idx, str(df["date"].iloc[t3_idx].date()), lows[t3_idx]),
            "breakout_idx": breakout_idx,
            "breakout_date": str(df["date"].iloc[breakout_idx].date()),
            "breakout_price": closes[breakout_idx],
            "max_drop_pct": round(max_drop * 100, 2),
            "trend_slope": slope,
            "trend_intercept": intercept,
            "macd_divergence": macd_divergence,
            "score": score,
            "df_processed": df
        }
        return True, match_info