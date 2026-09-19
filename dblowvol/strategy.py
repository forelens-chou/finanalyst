"""
strategy.py - 双底与 90 天地量形态识别引擎
"""
import numpy as np
import pandas as pd
from typing import Optional, Dict

class PatternRecognizer:
    def __init__(self, cfg):
        self.cfg = cfg

    def evaluate(self, df: pd.DataFrame, pe_ttm: float) -> Optional[Dict]:
        if not (self.cfg.MIN_PE_TTM <= pe_ttm <= self.cfg.MAX_PE_TTM):
            return None

        if len(df) < self.cfg.VOLUME_LOW_WINDOW + 20:
            return None

        closes = df['close'].values
        lows = df['low'].values
        highs = df['high'].values
        vols = df['volume'].values
        dates = df['date'].dt.strftime('%Y-%m-%d').values
        n = len(df)

        # 1. 识别 90 天地量
        df['vol_min90'] = df['volume'].rolling(window=self.cfg.VOLUME_LOW_WINDOW).min()

        low_vol_idx = -1
        # 如果强制要求“必须是最新交易日”
        if self.cfg.STRICT_LATEST_DAY_VOL:
            if vols[-1] <= df['vol_min90'].iloc[-1]:
                low_vol_idx = n - 1
            else:
                return None
        else:
            # 允许在最近 N 天内找地量（兼容前一日地量、今日放量阳线启动）
            for i in range(1, self.cfg.VOLUME_TOLERANCE_DAYS + 1):
                idx = n - i
                if vols[idx] <= df['vol_min90'].iloc[idx]:
                    low_vol_idx = idx
                    break

        if low_vol_idx == -1:
            return None

        is_latest_day = (low_vol_idx == n - 1)

        # 2. 第二底识别 (底2发生在近期地量震荡区间)
        search_b2_range = lows[max(0, low_vol_idx - 5) : min(n, low_vol_idx + 3)]
        b2_low = np.min(search_b2_range)
        b2_idx = max(0, low_vol_idx - 5) + np.argmin(search_b2_range)

        # 3. 第一底识别 (底1向前回溯)
        start_b1 = max(0, b2_idx - self.cfg.MAX_BOTTOM_GAP)
        end_b1 = b2_idx - self.cfg.MIN_BOTTOM_GAP

        if end_b1 <= start_b1:
            return None

        b1_search_zone = lows[start_b1:end_b1]
        b1_low = np.min(b1_search_zone)
        b1_idx = start_b1 + np.argmin(b1_search_zone)

        # 4. 中间波峰反弹校验
        peak_zone = highs[b1_idx:b2_idx]
        if len(peak_zone) == 0:
            return None
        peak_high = np.max(peak_zone)
        bounce_ratio = (peak_high - b1_low) / b1_low
        if bounce_ratio < self.cfg.PEAK_BOUNCE_RATIO:
            return None

        # 5. 底2与底1价格偏离度校验
        diff_ratio = (b2_low - b1_low) / b1_low
        if diff_ratio < -self.cfg.BOTTOM2_MAX_DROP or diff_ratio > self.cfg.BOTTOM2_MAX_RISE:
            return None

        latest_change = (closes[-1] - closes[-2]) / closes[-2] * 100

        return {
            "pe_ttm": round(pe_ttm, 2),
            "latest_close": round(closes[-1], 2),
            "latest_pct": f"{latest_change:+.2f}%",
            "low_vol_date": dates[low_vol_idx],
            "is_latest_day_vol": "是" if is_latest_day else f"否(距今{n - 1 - low_vol_idx}天)",
            "b1_date": dates[b1_idx],
            "b1_low": round(b1_low, 2),
            "b2_date": dates[b2_idx],
            "b2_low": round(b2_low, 2),
            "gap_bars": int(b2_idx - b1_idx),
            "diff_pct": f"{diff_ratio * 100:+.2f}%"
        }