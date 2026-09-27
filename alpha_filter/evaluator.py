# evaluator.py
from typing import Dict, Optional
import pandas as pd
from config import StrategyConfig
from features import FeatureCalculator

class StrategyEvaluator:
    def __init__(self, config: StrategyConfig):
        self.cfg = config

    def evaluate_strategy_a(self, df: pd.DataFrame, meta: dict) -> Optional[Dict]:
        """方案 A：筹码集中度 + 放量突破均线带"""
        if len(df) < self.cfg.MIN_KLINE_BARS:
            return None

        # 1. 计算均线与放量指标
        df = FeatureCalculator.calc_ma_ribbon(df, self.cfg.A_MA_PERIODS)
        df = FeatureCalculator.calc_volume_ma(df, period=20)

        last_row = df.iloc[-1]
        prev_window = df.iloc[-self.cfg.A_LOOKBACK_WINDOW : -1]

        # 判定一：涨幅与 K 线实体强度
        pct_change = (last_row["close"] - last_row["open"]) / (last_row["open"] + 1e-6) * 100
        bar_range = last_row["high"] - last_row["low"]
        body_range = abs(last_row["close"] - last_row["open"])
        body_ratio = body_range / (bar_range + 1e-6)

        if pct_change < self.cfg.A_MIN_PCT_CHANGE or body_ratio < self.cfg.A_MIN_BODY_RATIO:
            return None

        # 判定二：放量倍数
        if last_row["vol_ratio"] < self.cfg.A_VOLUME_SURGE_FACTOR:
            return None

        # 判定三：突破过去最高收盘价
        highest_prev_close = prev_window["close"].max()
        if last_row["close"] <= highest_prev_close:
            return None

        # 判定四：均线带顺向多头排列且 20 均线向上
        ma_aligned = (
            last_row["ema_5"] > last_row["ema_10"] > last_row["ema_20"] > last_row["ema_30"] > last_row["ema_60"]
            and last_row["ema_20_slope"] > 0
        )
        if not ma_aligned:
            return None

        # 判定五：前期筹码集中度 (VPVR)
        cr = FeatureCalculator.calc_vpvr_concentration(prev_window, bins=self.cfg.A_VPVR_BINS)
        if cr > self.cfg.A_MAX_CONCENTRATION_RATIO:
            return None

        return {
            "symbol": meta["symbol"],
            "name": meta["name"],
            "date": str(last_row["date"])[:10],
            "close": last_row["close"],
            "pct_change": round(pct_change, 2),
            "vol_ratio": round(last_row["vol_ratio"], 2),
            "concentration_ratio": round(cr, 4),
            "breakout_price": highest_prev_close,
            "strategy": "Strategy_A_Breakout"
        }

    def evaluate_strategy_b(self, df: pd.DataFrame, meta: dict) -> Optional[Dict]:
        """方案 B：量价与 RSI 顶/底背离检测"""
        if len(df) < self.cfg.MIN_KLINE_BARS:
            return None

        df = FeatureCalculator.calc_rsi(df, period=self.cfg.B_RSI_PERIOD)
        df = FeatureCalculator.calc_ma_ribbon(df, [10, self.cfg.B_CONFIRM_MA])
        peaks, troughs = FeatureCalculator.detect_pivots(
            df, left=self.cfg.B_PIVOT_LEFT, right=self.cfg.B_PIVOT_RIGHT
        )

        n = len(df)
        last_idx = n - 1
        last_row = df.iloc[-1]

        # ---------------- 顶背离判定 (逃顶/空头风险) ----------------
        if len(peaks) >= 2:
            p2 = peaks[-1]
            p1 = peaks[-2]

            # 校验双峰的有效跨度与确认延迟
            interval = p2["idx"] - p1["idx"]
            if (self.cfg.B_MIN_PEAK_INTERVAL <= interval <= self.cfg.B_MAX_PEAK_INTERVAL 
                and p2["confirm_idx"] <= last_idx):

                # 价格创新高、RSI显著下倾、P1处于超买区、成交量衰退
                price_new_high = p2["price"] > p1["price"] * 1.005
                rsi_divergence = (p2["rsi"] < p1["rsi"] - 3.0) and (p1["rsi"] >= self.cfg.B_TOP_RSI_OVERBOUGHT)
                vol_decay = p2["volume"] < p1["volume"]

                # 右侧破位确认：背离成立后跌破 EMA20
                broken_down = last_row["close"] < last_row[f"ema_{self.cfg.B_CONFIRM_MA}"]

                if price_new_high and rsi_divergence and vol_decay and broken_down:
                    return {
                        "symbol": meta["symbol"],
                        "name": meta["name"],
                        "date": str(last_row["date"])[:10],
                        "signal_type": "TOP_DIVERGENCE_EXIT",
                        "close": last_row["close"],
                        "p1_price": p1["price"],
                        "p2_price": p2["price"],
                        "p1_rsi": round(p1["rsi"], 2),
                        "p2_rsi": round(p2["rsi"], 2),
                        "confirm_ma": round(last_row[f"ema_{self.cfg.B_CONFIRM_MA}"], 2),
                        "strategy": "Strategy_B_Divergence"
                    }

        # ---------------- 底背离判定 (超跌/反弹观察) ----------------
        if len(troughs) >= 2:
            t2 = troughs[-1]
            t1 = troughs[-2]

            interval = t2["idx"] - t1["idx"]
            if (self.cfg.B_MIN_PEAK_INTERVAL <= interval <= self.cfg.B_MAX_PEAK_INTERVAL 
                and t2["confirm_idx"] <= last_idx):

                # 价格创新低、RSI抬高、T1处于超卖区
                price_new_low = t2["price"] < t1["price"] * 0.995
                rsi_bottom_div = (t2["rsi"] > t1["rsi"] + 2.0) and (t1["rsi"] <= self.cfg.B_BOTTOM_RSI_OVERSOLD)

                # 右侧企稳确认：收盘价收复 10 日均线
                broken_up = last_row["close"] > last_row["ema_10"]

                if price_new_low and rsi_bottom_div and broken_up:
                    return {
                        "symbol": meta["symbol"],
                        "name": meta["name"],
                        "date": str(last_row["date"])[:10],
                        "signal_type": "BOTTOM_DIVERGENCE_BUY",
                        "close": last_row["close"],
                        "t1_price": t1["price"],
                        "t2_price": t2["price"],
                        "t1_rsi": round(t1["rsi"], 2),
                        "t2_rsi": round(t2["rsi"], 2),
                        "strategy": "Strategy_B_Divergence"
                    }

        return None