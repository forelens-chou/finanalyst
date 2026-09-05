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
        拟合下降趋势上轨外包阻力线
        返回: (k, b, peak_idx, target_peak_idx, details)
        """
        if self.n < 60:
            return None

        highs = self.df['high'].values
        closes = self.df['close'].values

        # 1. 寻找全周期最高点作为基准锚点 P0
        # 锚点必须在前半段（留出足够的下跌及收敛观察周期）
        max_idx = int(np.argmax(highs[:int(self.n * 0.7)]))
        if max_idx >= self.n - 30: # 留足至少30根K线筑底
            return None
        
        p0_x = max_idx
        p0_y = highs[max_idx]

        # 2. 寻找 P0 之后的所有次高点局部波峰
        sub_highs = highs[max_idx:]
        peaks, _ = find_peaks(sub_highs, distance=min_peak_distance)
        peaks = peaks + max_idx  # 还原全局索引
        peaks = [p for p in peaks if p > p0_x + 5]

        if len(peaks) == 0:
            return None

        best_candidate = None
        min_residual_area = float('inf')

        x_coords = np.arange(p0_x, self.n)

        # 3. 遍历候选切线，执行外包约束筛选
        for p_idx in peaks:
            # 切线斜率 k = (y2 - y1) / (x2 - x1)
            k = (highs[p_idx] - p0_y) / (p_idx - p0_x)
            if k >= 0:  # 必须下倾
                continue
            b = p0_y - k * p0_x

            # 计算此线在全区间的理论值
            line_vals = k * x_coords + b
            sub_closes = closes[p0_x:]
            sub_highs_segment = highs[p0_x:]

            # 穿透率检查：收盘价不得大幅越过阻力线
            penetrations = np.sum(sub_closes > line_vals * 1.005)
            penetration_rate = penetrations / len(sub_closes)

            if penetration_rate <= max_penetration_rate:
                # 累积切线与K线最高价之间的面积（越紧绷贴合，面积越小）
                diff = line_vals - sub_highs_segment
                if np.all(diff >= -0.05 * line_vals):  # 影线虚破容忍度5%
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