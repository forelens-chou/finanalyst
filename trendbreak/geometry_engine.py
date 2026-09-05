# geometry_engine.py
import numpy as np
import pandas as pd
from scipy.signal import find_peaks

class TrendlineFitter:
    def __init__(self, df: pd.DataFrame):
        self.df = df
        self.n = len(df)

    def fit_upper_resistance_line(self, min_peak_distance: int = 8, max_penetration_rate: float = 0.03):
        """
        高精度外包压制线拟合引擎（彻底杜绝 000546、000035 等断崖暴跌悬空线）
        """
        if self.n < 60:
            return None

        highs = self.df['high'].values
        closes = self.df['close'].values

        # 1. 最高点 P0 必须位于前半段（前 70%），留足下行震荡收敛周期
        max_idx = int(np.argmax(highs[:int(self.n * 0.70)]))
        span = self.n - max_idx
        # 下行周期跨度至少需要 35 根 K 线，避免把极短期的波动当成长线压制
        if span < 35:
            return None
        
        p0_x = max_idx
        p0_y = highs[max_idx]

        # 2. 寻找 P0 之后的所有次高点波峰
        sub_highs = highs[max_idx:]
        peaks, _ = find_peaks(sub_highs, distance=min_peak_distance)
        peaks = peaks + max_idx
        peaks = [p for p in peaks if p > p0_x + 5]

        if len(peaks) == 0:
            return None

        best_candidate = None
        min_residual_area = float('inf')
        x_coords = np.arange(p0_x, self.n)

        # 3. 遍历候选切线
        for p_idx in peaks:
            k = (highs[p_idx] - p0_y) / (p_idx - p0_x)
            if k >= -0.0005:  # 必须是清晰向下倾斜
                continue
            b = p0_y - k * p0_x

            line_vals = k * x_coords + b
            sub_closes = closes[p0_x:]
            sub_highs_segment = highs[p0_x:]

            # 约束 1：实体穿透率 <= 3%
            penetrations = np.sum(sub_closes > line_vals * 1.008)
            penetration_rate = penetrations / len(sub_closes)
            if penetration_rate > max_penetration_rate:
                continue

            # 约束 2：上影线大幅虚破容忍度 <= 5%
            diff = line_vals - sub_highs_segment
            if np.any(diff < -0.05 * line_vals):
                continue

            # =========================================================
            # 【核心防线 1：中段（20%~80%）反弹触碰检验，秒杀悬空线】
            # =========================================================
            # 避开起点刚下落的前 20% 和当前震荡的后 20%，截取真正的中途下行段
            mid_start = int(p0_x + span * 0.20)
            mid_end = int(p0_x + span * 0.80)

            if mid_end > mid_start:
                mid_highs = highs[mid_start:mid_end]
                mid_lines = line_vals[(mid_start - p0_x):(mid_end - p0_x)]
                
                # 计算中途所有 K 线最高价离切线的最小相对距离
                min_mid_gap = np.min((mid_lines - mid_highs) / mid_lines)
                
                # 必须在中段有至少一次反弹波峰接近或触碰切线（相对差距 <= 4.5%）
                # 000546 和 000035 在中段全部深陷 20%~40%，在这里会被 100% 拦截！
                if min_mid_gap > 0.045:
                    continue

            # =========================================================
            # 【核心防线 2：全区间平均悬空率限制】
            # =========================================================
            avg_gap = np.mean(diff / line_vals)
            # 若整段区间 K 线平均距离趋势线超过 15%，说明中间严重塌陷，淘汰
            if avg_gap > 0.15:
                continue

            # 凸外包最小面积优选
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