"""
多周期共振、波动率挤压与筹码分布模型独立计算模块
负责对均线初筛命中的标的进行精排赋能（无需发起额外网络请求）
"""

import numpy as np
import pandas as pd


class AdvancedAnalytics:
    """多维共振与微观结构量化分析引擎"""

    # ---------------- 1. 周线多周期共振计算 ----------------
    @staticmethod
    def calc_weekly_resonance(df: pd.DataFrame) -> dict:
        """
        利用现有日K原地重采样为周K（W-FRI），计算周线 MA5, MA10, MA20 的共振状态
        """
        try:
            df_work = df.copy()
            df_work = df_work.set_index("date")

            # 聚合为周K线
            df_weekly = df_work.resample("W-FRI").agg({
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
            }).dropna()

            if len(df_weekly) < 20:
                return {"weekly_status": "周线样本不足", "weekly_score": 12.0}

            w_close = df_weekly["close"]
            w_ma5 = w_close.rolling(5).mean().iloc[-1]
            w_ma10 = w_close.rolling(10).mean().iloc[-1]
            w_ma20 = w_close.rolling(20).mean().iloc[-1]

            w_ma5_prev = w_close.rolling(5).mean().iloc[-2]
            w_ma10_prev = w_close.rolling(10).mean().iloc[-2]

            mas = [w_ma5, w_ma10, w_ma20]
            spread = (max(mas) - min(mas)) / min(mas)
            is_bull = (w_ma5 > w_ma10 > w_ma20) and (w_ma5 > w_ma5_prev) and (w_ma10 > w_ma10_prev)

            if spread <= 0.045:
                status = "周线极致收敛"
                score = 25.0
            elif is_bull:
                status = "周线多头排列"
                score = 23.0
            elif spread <= 0.08:
                status = "周线温和收敛"
                score = 18.0
            else:
                status = "周线中性震荡"
                score = 10.0

            return {"weekly_status": status, "weekly_score": score}
        except Exception:
            return {"weekly_status": "周线计算异常", "weekly_score": 10.0}

    # ---------------- 2. 波动率挤压指数 (TTM Squeeze) ----------------
    @staticmethod
    def calc_volatility_squeeze(df: pd.DataFrame) -> dict:
        """
        经典 TTM Squeeze 模型：
        比较 20日布林带 (BB, 2.0 std) 与 20日肯特纳通道 (KC, 1.5 ATR)
        当布林带收缩进肯特纳通道内部时，为极致波动率挤压（变盘爆发前兆）
        """
        try:
            close = df["close"]
            high = df["high"]
            low = df["low"]

            # 1. 布林带计算
            sma20 = close.rolling(20).mean()
            std20 = close.rolling(20).std()
            bb_upper = sma20 + 2.0 * std20
            bb_lower = sma20 - 2.0 * std20
            bandwidth = (bb_upper - bb_lower) / sma20

            # 2. 肯特纳通道 (ATR 20)
            prev_close = close.shift(1)
            tr = pd.concat([
                high - low,
                (high - prev_close).abs(),
                (low - prev_close).abs()
            ], axis=1).max(axis=1)
            atr20 = tr.rolling(20).mean()
            kc_upper = sma20 + 1.5 * atr20
            kc_lower = sma20 - 1.5 * atr20

            # 挤压判断
            is_squeeze = (bb_upper.iloc[-1] < kc_upper.iloc[-1]) and (bb_lower.iloc[-1] > kc_lower.iloc[-1])

            # 带宽历史分位数（近120日）
            history_window = min(len(df), 120)
            recent_bw = bandwidth.iloc[-history_window:]
            curr_bw = bandwidth.iloc[-1]
            bw_percentile = (recent_bw < curr_bw).mean() * 100.0

            if is_squeeze:
                status = "极度挤压(蓄势)"
                score = 25.0
            elif bw_percentile <= 15.0:
                status = "窄轨即将变盘"
                score = 22.0
            elif bw_percentile <= 30.0:
                status = "低波收口"
                score = 16.0
            else:
                status = "正常扩张"
                score = 10.0

            return {
                "squeeze_status": status,
                "bw_percentile": round(bw_percentile, 1),
                "squeeze_score": score,
            }
        except Exception:
            return {"squeeze_status": "计算异常", "bw_percentile": 50.0, "squeeze_score": 10.0}

    # ---------------- 3. 筹码分布集中度 (成本衰减 Volume Profile) ----------------
    @staticmethod
    def calc_chip_distribution(df: pd.DataFrame) -> dict:
        """
        基于日线价格区间的加权指数衰减筹码分布模型：
        计算 90% 筹码集中度（越小越密集）及最新价格处的获利盘比例
        """
        try:
            lookback = min(len(df), 120)
            sub_df = df.iloc[-lookback:].copy()

            low_min = sub_df["low"].min()
            high_max = sub_df["high"].max()

            if low_min >= high_max or np.isnan(low_min):
                return {"chip_90_ratio": 20.0, "profit_ratio": 50.0, "chip_score": 10.0}

            # 离散价格箱体（100 个分箱）
            bins = np.linspace(low_min, high_max, 101)
            chip_volume = np.zeros(100)

            # 历史衰减因子（模拟真实换手沉淀，半衰期约 30 天）
            decay_lambda = 0.975

            for i in range(lookback):
                row = sub_df.iloc[i]
                weight = decay_lambda ** (lookback - 1 - i)
                v = row["volume"] * weight
                bar_l, bar_h = row["low"], row["high"]

                if bar_h <= bar_l:
                    idx = min(np.searchsorted(bins, bar_l), 99)
                    chip_volume[idx] += v
                else:
                    # 将当日成交量均匀注入当日高低区间的箱体
                    idx_l = np.searchsorted(bins, bar_l)
                    idx_h = np.searchsorted(bins, bar_h)
                    idx_l = max(0, min(idx_l, 99))
                    idx_h = max(idx_l + 1, min(idx_h, 100))
                    num_bins = idx_h - idx_l
                    chip_volume[idx_l:idx_h] += v / num_bins

            total_vol = chip_volume.sum()
            if total_vol <= 0:
                return {"chip_90_ratio": 20.0, "profit_ratio": 50.0, "chip_score": 10.0}

            # 累积分布计算 90% 筹码区间 [P_5%, P_95%]
            cum_vol = np.cumsum(chip_volume) / total_vol
            p5_idx = np.searchsorted(cum_vol, 0.05)
            p95_idx = np.searchsorted(cum_vol, 0.95)

            p5 = bins[min(p5_idx, 99)]
            p95 = bins[min(p95_idx, 99)]

            # 90% 集中度 = (P95 - P5) / (P95 + P5)
            chip_90 = ((p95 - p5) / (p95 + p5)) * 100.0 if (p95 + p5) > 0 else 50.0

            # 获利盘比例 = 价格低于最新收盘价的筹码累积占比
            latest_close = df["close"].iloc[-1]
            close_idx = np.searchsorted(bins, latest_close)
            close_idx = min(max(close_idx, 0), 99)
            profit_ratio = cum_vol[close_idx] * 100.0

            # 打分系统 (满分 25 分: 集中度 15 分 + 获利盘 10 分)
            score = 0.0
            if chip_90 <= 9.0:
                score += 15.0
            elif chip_90 <= 13.0:
                score += 12.0
            elif chip_90 <= 18.0:
                score += 8.0
            else:
                score += 4.0

            if profit_ratio >= 80.0:
                score += 10.0
            elif profit_ratio >= 60.0:
                score += 7.0
            else:
                score += 3.0

            return {
                "chip_90_ratio": round(chip_90, 1),
                "profit_ratio": round(profit_ratio, 1),
                "chip_score": score,
            }
        except Exception:
            return {"chip_90_ratio": 20.0, "profit_ratio": 50.0, "chip_score": 10.0}

    # ---------------- 4. 综合赋能与打分整合 ----------------
    @classmethod
    def enrich(cls, base_result: dict, df: pd.DataFrame) -> dict:
        """
        整合三项指标并计算综合得分 (满分 100 分)
        基础粘合分(25) + 周线共振分(25) + 波动率挤压分(25) + 筹码集中分(25)
        """
        # 基础均线粘合度得分 (极差越小得分越高)
        bw = base_result["bandwidth(%)"]
        if bw <= 1.8:
            base_score = 25.0
        elif bw <= 2.8:
            base_score = 22.0
        elif bw <= 3.5:
            base_score = 18.0
        else:
            base_score = 14.0

        # 计算三大维度
        weekly_info = cls.calc_weekly_resonance(df)
        squeeze_info = cls.calc_volatility_squeeze(df)
        chip_info = cls.calc_chip_distribution(df)

        total_score = round(
            base_score
            + weekly_info["weekly_score"]
            + squeeze_info["squeeze_score"]
            + chip_info["chip_score"],
            1
        )

        # 在不改动原有字段的基础上，注入全新指标栏位
        enriched = dict(base_result)
        enriched["total_score"] = total_score
        enriched["weekly_resonance"] = weekly_info["weekly_status"]
        enriched["squeeze_status"] = squeeze_info["squeeze_status"]
        enriched["bw_percentile(%)"] = squeeze_info["bw_percentile"]
        enriched["chip_90(%)"] = chip_info["chip_90_ratio"]
        enriched["profit_ratio(%)"] = chip_info["profit_ratio"]

        return enriched