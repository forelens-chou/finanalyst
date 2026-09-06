# geometry_engine.py
import numpy as np
import pandas as pd
from scipy.signal import find_peaks

class TrendlineFitter:
    def __init__(self, df: pd.DataFrame):
        self.df = df
        self.n = len(df)

    def fit_upper_resistance_line(self, min_peak_distance: int = 8, max_penetration_rate: float = 0.03):
        """拟合上轨下倾压制线（严格防悬空）"""
        if self.n < 60:
            return None

        highs = self.df['high'].values
        closes = self.df['close'].values

        max_idx = int(np.argmax(highs[:int(self.n * 0.70)]))
        span = self.n - max_idx
        if span < 35:
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

            # 修复点：显式定义 penetration_rate
            penetrations = np.sum(sub_closes > line_vals * 1.008)
            penetration_rate = penetrations / len(sub_closes)
            if penetration_rate > max_penetration_rate:
                continue

            diff = line_vals - sub_highs_segment
            if np.any(diff < -0.05 * line_vals):
                continue

            # 中段触碰防悬空（20% ~ 80%）
            mid_start = int(p0_x + span * 0.20)
            mid_end = int(p0_x + span * 0.80)
            if mid_end > mid_start:
                mid_highs = highs[mid_start:mid_end]
                mid_lines = line_vals[(mid_start - p0_x):(mid_end - p0_x)]
                min_mid_gap = np.min((mid_lines - mid_highs) / mid_lines)
                if min_mid_gap > 0.045:
                    continue

            avg_gap = np.mean(diff / line_vals)
            if avg_gap > 0.15:
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

    def check_dual_track_convergence(self, up_trend_info: dict) -> tuple:
        """
        双轨收敛判定（检测下轨支撑是否抬高或收敛）
        返回: (is_dual_track: bool, support_info: dict)
        """
        if up_trend_info is None or self.n < 50:
            return False, None

        lows = self.df['low'].values
        p0_x = up_trend_info['p0_idx']
        sub_lows = lows[p0_x:]
        
        if len(sub_lows) < 30:
            return False, None

        half_len = len(sub_lows) // 2
        early_min = np.min(sub_lows[:half_len])
        recent_min = np.min(sub_lows[half_len:])

        is_higher_low = recent_min >= early_min * 0.985
        
        curr_idx = self.n - 1
        curr_up_line = up_trend_info['k'] * curr_idx + up_trend_info['b']
        
        support_price = np.min(lows[-20:])
        channel_width_pct = (curr_up_line - support_price) / curr_up_line * 100

        is_converged = is_higher_low and (0 < channel_width_pct <= 7.5)
        
        support_info = {
            'support_price': round(support_price, 2),
            'channel_width_pct': round(channel_width_pct, 2)
        }
        return is_converged, support_info