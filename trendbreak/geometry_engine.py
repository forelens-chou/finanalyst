# geometry_engine.py
import numpy as np
import pandas as pd
from scipy.signal import find_peaks

class TrendlineFitter:
    def __init__(self, df: pd.DataFrame, code: str = ""):
        self.df = df
        self.n = len(df)
        self.code = str(code).zfill(6)

        # =========================================================
        # 【核心矩阵：全市场阶梯式波动率容差体系】
        # =========================================================
        if self.code.startswith(('43', '83', '87', '88', '92')):
            # 北交所 (30% 涨跌幅)
            self.spike_limit = -0.12  # 上影线虚破容忍度 12%
            self.touch_limit = 0.065  # 中段触碰判定容差 6.5%
            self.channel_limit = 8.5
        elif self.code.startswith(('30', '688')):
            # 创业板、科创板 (20% 涨跌幅)
            self.spike_limit = -0.08  # 上影线虚破容忍度 8%
            self.touch_limit = 0.055  # 中段触碰判定容差 5.5%
            self.channel_limit = 8.0
        else:
            # 沪深主板 (10% 涨跌幅)
            self.spike_limit = -0.05  # 上影线虚破容忍度 5%
            self.touch_limit = 0.045  # 中段触碰判定容差 4.5%
            self.channel_limit = 7.5

    def fit_upper_resistance_line(self, min_peak_distance: int = 8, max_penetration_rate: float = 0.03):
        if self.n < 45:
            return None

        highs = self.df['high'].values
        closes = self.df['close'].values

        max_idx = int(np.argmax(highs[:int(self.n * 0.70)]))
        span = self.n - max_idx
        if span < 30:
            return None
        
        p0_x = max_idx
        p0_y = highs[max_idx]

        sub_highs = highs[max_idx:]
        peaks, _ = find_peaks(sub_highs, distance=min_peak_distance)
        peaks = peaks + max_idx
        peaks = [p for p in peaks if p > p0_x + 5]

        if len(peaks) == 0:
            return None

        best_candidate = None
        min_residual_area = float('inf')
        x_coords = np.arange(p0_x, self.n)

        for p_idx in peaks:
            k = (highs[p_idx] - p0_y) / (p_idx - p0_x)
            if k >= -0.0005:
                continue
            b = p0_y - k * p0_x

            line_vals = k * x_coords + b
            sub_closes = closes[p0_x:]
            sub_highs_segment = highs[p0_x:]

            # 穿透率检查
            penetrations = np.sum(sub_closes > line_vals * 1.008)
            penetration_rate = penetrations / len(sub_closes)
            if penetration_rate > max_penetration_rate:
                continue

            diff = line_vals - sub_highs_segment
            # 阶梯式上影线虚破检查
            if np.any(diff < self.spike_limit * line_vals):
                continue

            # 中段触碰防悬空（20% ~ 80%）
            mid_start = int(p0_x + span * 0.20)
            mid_end = int(p0_x + span * 0.80)
            if mid_end > mid_start:
                mid_highs = highs[mid_start:mid_end]
                mid_lines = line_vals[(mid_start - p0_x):(mid_end - p0_x)]
                min_mid_gap = np.min((mid_lines - mid_highs) / mid_lines)
                if min_mid_gap > self.touch_limit:
                    continue

            avg_gap = np.mean(diff / line_vals)
            if avg_gap > 0.16:
                continue

            area = np.sum(np.abs(diff))
            if area < min_residual_area:
                min_residual_area = area
                best_candidate = {
                    'k': k,
                    'b': b,
                    'p0_idx': p0_x,
                    'p1_idx': p_idx,
                    'p0_date': self.df['date'].iloc[p0_x],
                    'p0_price': p0_y,
                    'penetration_rate': penetration_rate
                }

        return best_candidate

    def fit_secondary_resistance_line(self, macro_trend_info: dict, min_peak_distance: int = 6):
        if macro_trend_info is None or self.n < 45:
            return None

        highs = self.df['high'].values
        closes = self.df['close'].values
        p0_idx = macro_trend_info['p0_idx']

        search_segment = highs[p0_idx + 8 : self.n - 15]
        if len(search_segment) < 12:
            return None

        sub_peaks, _ = find_peaks(search_segment, distance=min_peak_distance)
        if len(sub_peaks) == 0:
            return None

        sub_peaks = sub_peaks + p0_idx + 8
        p_sub_x = sub_peaks[np.argmax(highs[sub_peaks])]
        p_sub_y = highs[p_sub_x]

        after_sub_highs = highs[p_sub_x:]
        after_peaks, _ = find_peaks(after_sub_highs, distance=5)
        after_peaks = after_peaks + p_sub_x
        after_peaks = [p for p in after_peaks if p > p_sub_x + 4]

        if len(after_peaks) == 0:
            return None

        best_sub = None
        min_area = float('inf')
        x_coords = np.arange(p_sub_x, self.n)

        for p_idx in after_peaks:
            k = (highs[p_idx] - p_sub_y) / (p_idx - p_sub_x)
            if k >= -0.0008:
                continue
            b = p_sub_y - k * p_sub_x

            line_vals = k * x_coords + b
            sub_closes = closes[p_sub_x:]
            sub_highs = highs[p_sub_x:]

            penetrations = np.sum(sub_closes > line_vals * 1.01)
            if penetrations / len(sub_closes) > 0.04:
                continue

            area = np.sum(np.abs(line_vals - sub_highs))
            if area < min_area:
                min_area = area
                best_sub = {
                    'k': k,
                    'b': b,
                    'p_sub_idx': p_sub_x,
                    'p_sub_price': p_sub_y,
                    'p_sub_date': self.df['date'].iloc[p_sub_x]
                }

        return best_sub

    def check_dual_track_convergence(self, up_trend_info: dict) -> tuple:
        if up_trend_info is None or self.n < 40:
            return False, None

        lows = self.df['low'].values
        p0_x = up_trend_info['p0_idx']
        sub_lows = lows[p0_x:]
        
        if len(sub_lows) < 20:
            return False, None

        half_len = len(sub_lows) // 2
        early_min = np.min(sub_lows[:half_len])
        recent_min = np.min(sub_lows[half_len:])

        is_higher_low = recent_min >= early_min * 0.985
        curr_idx = self.n - 1
        curr_up_line = up_trend_info['k'] * curr_idx + up_trend_info['b']
        
        support_price = np.min(lows[-20:])
        channel_width_pct = (curr_up_line - support_price) / curr_up_line * 100

        is_converged = is_higher_low and (0 < channel_width_pct <= self.channel_limit)
        
        support_info = {
            'support_price': round(support_price, 2),
            'channel_width_pct': round(channel_width_pct, 2)
        }
        return is_converged, support_info