# features.py
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple

class FeatureCalculator:
    @staticmethod
    def calc_ma_ribbon(df: pd.DataFrame, periods: List[int]) -> pd.DataFrame:
        """计算 EMA 均线带及斜率"""
        for p in periods:
            df[f"ema_{p}"] = df["close"].ewm(span=p, adjust=False).mean()
        
        # 计算基准均线 (如 EMA20) 的 3日斜率
        if "ema_20" in df.columns:
            df["ema_20_slope"] = (df["ema_20"] - df["ema_20"].shift(3)) / (df["ema_20"].shift(3) + 1e-6)
        return df

    @staticmethod
    def calc_rsi(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
        """计算标准 RSI 指标"""
        delta = df["close"].diff()
        gain = (delta.where(delta > 0, 0.0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0.0)).rolling(window=period).mean()
        
        rs = gain / (loss + 1e-6)
        df["rsi"] = 100 - (100 / (1 + rs))
        return df

    @staticmethod
    def calc_volume_ma(df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
        """计算成交量均线与放量倍数"""
        df[f"vol_ma_{period}"] = df["volume"].rolling(window=period).mean()
        df["vol_ratio"] = df["volume"] / (df[f"vol_ma_{period}"] + 1e-6)
        return df

    @staticmethod
    def calc_vpvr_concentration(df_window: pd.DataFrame, bins: int = 100) -> float:
        """
        计算回溯窗口内 70% 筹码密集度比率 (Concentration Ratio)
        数值越小代表筹码越集中在狭窄的价格带内。
        """
        if len(df_window) < 10:
            return 1.0

        p_min = df_window["low"].min()
        p_max = df_window["high"].max()
        
        if p_max <= p_min:
            return 0.0

        bin_edges = np.linspace(p_min, p_max, bins + 1)
        bin_vols = np.zeros(bins)

        # 将每日成交量按价格区间摊入直方图
        for _, row in df_window.iterrows():
            bar_l, bar_h, vol = row["low"], row["high"], row["volume"]
            if bar_h <= bar_l or vol <= 0:
                continue
            idx_start = np.searchsorted(bin_edges, bar_l, side="left") - 1
            idx_end = np.searchsorted(bin_edges, bar_h, side="right") - 1
            idx_start = max(0, idx_start)
            idx_end = min(bins - 1, idx_end)
            
            span = max(1, idx_end - idx_start + 1)
            bin_vols[idx_start : idx_end + 1] += (vol / span)

        total_vol = bin_vols.sum()
        if total_vol <= 0:
            return 1.0

        # 双指针滑动窗口，寻找容纳 70% 成交量的最小价格范围
        target_vol = total_vol * 0.70
        min_width = float("inf")
        curr_vol = 0.0
        r = 0

        for l in range(bins):
            while r < bins and curr_vol < target_vol:
                curr_vol += bin_vols[r]
                r += 1
            if curr_vol >= target_vol:
                width = bin_edges[r] - bin_edges[l]
                if width < min_width:
                    min_width = width
            curr_vol -= bin_vols[l]

        latest_close = df_window["close"].iloc[-1]
        return min_width / (latest_close + 1e-6)

    @staticmethod
    def detect_pivots(df: pd.DataFrame, left: int = 3, right: int = 3) -> Tuple[List[dict], List[dict]]:
        """
        极值点检测算子（严格右侧确认，无未来函数）
        返回确认好的历史波峰列表与波谷列表
        """
        peaks = []
        troughs = []
        highs = df["high"].values
        lows = df["low"].values
        closes = df["close"].values
        rsis = df["rsi"].values
        vols = df["volume"].values
        dates = df["date"].values

        n = len(df)
        # 必须给右侧留足 right 根确认 Bar
        for i in range(left, n - right):
            # 波峰判定
            if highs[i] == max(highs[i - left : i + right + 1]):
                peaks.append({
                    "idx": i,
                    "date": dates[i],
                    "confirm_idx": i + right,
                    "price": highs[i],
                    "close": closes[i],
                    "rsi": rsis[i],
                    "volume": vols[i]
                })
            # 波谷判定
            if lows[i] == min(lows[i - left : i + right + 1]):
                troughs.append({
                    "idx": i,
                    "date": dates[i],
                    "confirm_idx": i + right,
                    "price": lows[i],
                    "close": closes[i],
                    "rsi": rsis[i],
                    "volume": vols[i]
                })
        return peaks, troughs