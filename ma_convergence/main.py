"""
A股多周期均线汇聚与向上突破选股系统 - 主执行程序
优化特性：
1. 数据采集与策略计算彻底解耦，依赖 fetcher.py
2. 30天内出现过涨停板的股票，4条均线仅需汇聚（豁免全部向上要求）；无涨停则保持4条均线向上汇聚
3. 依然支持涨停股票豁免当日放量限制
"""

import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd

from config import ScreenerConfig
from fetcher import DataFetcher

# ==================== 日志初始化 ====================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("MAScreener")


# ==================== 策略判定引擎 ====================
class StrategyEngine:
    def __init__(self, config: ScreenerConfig):
        self.cfg = config

    def _has_recent_limit_up(self, raw_code: str, df: pd.DataFrame) -> bool:
        """判断近 N 根 K 线内是否存在涨停板"""
        if raw_code.startswith(("68", "30")):
            threshold = self.cfg.GROWTH_LIMIT_UP_PCT  # 创业板/科创板 20%
        elif raw_code.startswith(("8", "4", "9")):
            threshold = self.cfg.BSE_LIMIT_UP_PCT     # 北交所 30%
        else:
            threshold = self.cfg.MAIN_LIMIT_UP_PCT    # 主板 10%

        pct_series = (df["close"] - df["close"].shift(1)) / df["close"].shift(1) * 100.0
        lookback_pcts = pct_series.iloc[-self.cfg.LIMIT_UP_LOOKBACK_BARS :]
        return bool((lookback_pcts >= threshold).any())

    def evaluate(self, raw_code: str, name: str, df: pd.DataFrame) -> Optional[dict]:
        total_bars = len(df)
        if total_bars < self.cfg.MIN_LISTING_DAYS:
            return None

        close = df["close"]
        volume = df["volume"]

        # 计算均线及其近期斜率
        ma_values = {}
        for period in self.cfg.MA_PERIODS:
            if total_bars >= period:
                series = close.rolling(window=period).mean()
                ma_values[f"MA{period}"] = {
                    "curr": series.iloc[-1],
                    "prev1": series.iloc[-2],
                    "prev3": series.iloc[-4] if total_bars >= period + 3 else series.iloc[-2],
                }

        if len(ma_values) < 4:
            return None

        sorted_ma = sorted(
            [(k, v["curr"]) for k, v in ma_values.items() if not np.isnan(v["curr"])],
            key=lambda x: x[1]
        )
        n = len(sorted_ma)

        latest_close = close.iloc[-1]
        latest_open = df["open"].iloc[-1]
        prev_close = close.iloc[-2]
        pct_chg = ((latest_close - prev_close) / prev_close) * 100.0

        # 成交量与量比
        ma_vol5 = volume.rolling(5).mean().iloc[-1]
        latest_vol = volume.iloc[-1]
        vol_ratio = latest_vol / ma_vol5 if ma_vol5 > 0 else 0.0

        # 检测 30 根 K 线内是否有涨停
        has_limit_up = self._has_recent_limit_up(raw_code, df)

        matched_rule = None
        converged_names = []
        cluster_bandwidth = 0.0
        cluster_max_val = 0.0

        # ---------------- 条件 A: 5条及以上均线汇聚 ----------------
        if n >= 5:
            for i in range(n - 5 + 1):
                window = sorted_ma[i : i + 5]
                min_v = window[0][1]
                max_v = window[-1][1]
                spread = (max_v - min_v) / min_v
                if spread <= self.cfg.BANDWIDTH_5LINES:
                    matched_rule = "5线粘合汇聚"
                    converged_names = [item[0] for item in window]
                    cluster_bandwidth = spread * 100
                    cluster_max_val = max_v
                    break

        # ---------------- 条件 B: 4条均线汇聚（分流判定） ----------------
        if not matched_rule and n >= 4:
            for i in range(n - 4 + 1):
                window = sorted_ma[i : i + 4]
                min_v = window[0][1]
                max_v = window[-1][1]
                spread = (max_v - min_v) / min_v
                if spread <= self.cfg.BANDWIDTH_4LINES:
                    # 核心需求：若近期有涨停且开启豁免，4线仅需汇聚；否则必须满足4线全部向上
                    if self.cfg.LIMIT_UP_WAIVE_4MA_UPWARD and has_limit_up:
                        matched_rule = "4线汇聚(涨停豁免向上)"
                        converged_names = [item[0] for item in window]
                        cluster_bandwidth = spread * 100
                        cluster_max_val = max_v
                        break
                    else:
                        all_upward = True
                        for name_k, _ in window:
                            ma_info = ma_values[name_k]
                            if not (ma_info["curr"] > ma_info["prev1"] and ma_info["curr"] > ma_info["prev3"]):
                                all_upward = False
                                break
                        if all_upward:
                            matched_rule = "4线向上汇聚"
                            converged_names = [item[0] for item in window]
                            cluster_bandwidth = spread * 100
                            cluster_max_val = max_v
                            break

        if not matched_rule:
            return None

        # ---------------- 条件 C: 必须站上汇聚均线簇最高线，且当日收阳或平盘 ----------------
        if not (latest_close >= cluster_max_val and latest_close >= latest_open and pct_chg >= 0):
            return None

        # ---------------- 条件 D: 成交量放量确认（含涨停放量豁免） ----------------
        is_vol_expanded = vol_ratio >= self.cfg.VOL_RATIO_MIN
        require_volume = True
        if self.cfg.LIMIT_UP_WAIVE_VOLUME and has_limit_up:
            require_volume = False

        if require_volume and not is_vol_expanded:
            return None

        # 标注状态标签
        if has_limit_up and not is_vol_expanded:
            status_tag = "涨停蓄势(免放量)"
        elif has_limit_up and is_vol_expanded:
            status_tag = "涨停+放量双共振"
        else:
            status_tag = "标准放量突破"

        return {
            "code": str(raw_code).zfill(6),
            "name": name,
            "close": round(latest_close, 2),
            "pct_chg": round(pct_chg, 2),
            "vol_ratio": round(vol_ratio, 2),
            "matched_rule": matched_rule,
            "status_tag": status_tag,
            "bandwidth(%)": round(cluster_bandwidth, 2),
            "converged_mas": ",".join(converged_names),
            "listing_days": total_bars,
        }


# ==================== 调度器与主流程 ====================
class StockScreenerApp:
    def __init__(self, config: ScreenerConfig):
        self.cfg = config
        self.fetcher = DataFetcher(config)
        self.engine = StrategyEngine(config)

    def run(self):
        start_time = time.time()
        raw_symbols = self.fetcher.get_market_symbols()
        pool = self.fetcher.prefilter_pool(raw_symbols)
        if not pool:
            logger.warning("候选池为空，退出。")
            return

        logger.info(f"启动 {self.cfg.MAX_WORKERS} 线程拉取 K 线并执行形态计算...")
        results = []
        fetch_success = 0
        fetch_fail = 0

        def worker_task(item: dict):
            df_kline = self.fetcher.get_kline(item["symbol"])
            if df_kline is None:
                return False, None
            return True, self.engine.evaluate(item["code"], item["name"], df_kline)

        with ThreadPoolExecutor(max_workers=self.cfg.MAX_WORKERS) as executor:
            future_to_stock = {executor.submit(worker_task, item): item for item in pool}
            completed = 0
            for future in as_completed(future_to_stock):
                completed += 1
                if completed % 300 == 0 or completed == len(pool):
                    logger.info(f"计算进度: {completed}/{len(pool)} ({(completed/len(pool)*100):.1f}%)")

                is_ok, res = future.result()
                if is_ok:
                    fetch_success += 1
                else:
                    fetch_fail += 1

                if res:
                    results.append(res)
                    logger.info(
                        f"🎯 [命中] {res['code']} {res['name']} | "
                        f"{res['matched_rule']} | 状态: {res['status_tag']} | "
                        f"涨幅: {res['pct_chg']}% | 量比: {res['vol_ratio']} | 均线: {res['converged_mas']}"
                    )

        elapsed = time.time() - start_time
        logger.info(
            f"扫描完成，总耗时: {elapsed:.2f} 秒 | "
            f"K线拉取成功: {fetch_success} 只, 丢弃: {fetch_fail} 只 | "
            f"最终选出: {len(results)} 只标的。"
        )

        if results:
            df_res = pd.DataFrame(results)
            df_res = df_res.sort_values(by=["matched_rule", "pct_chg"], ascending=[True, False])

            print("\n" + "=" * 98)
            print(f" 均线汇聚突破选股结果清单 (共 {len(df_res)} 只)")
            print("=" * 98)
            print(df_res.to_string(index=False))
            print("=" * 98 + "\n")

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            os.makedirs("results", exist_ok=True)

            csv_filename = os.path.join("results", f"ma_converged_{timestamp}.csv")
            df_res.to_csv(csv_filename, index=False, encoding="utf_8_sig")
            logger.info(f"标准分析报表已保存: {csv_filename}")

            txt_filename = os.path.join("results", f"import_to_em_{timestamp}.txt")
            with open(txt_filename, "w", encoding="utf-8") as f:
                for code in df_res["code"]:
                    f.write(f"{code}\n")
            logger.info(f"东方财富一键导入 TXT 码单已保存: {txt_filename}")
        else:
            logger.info("今日全市场未发现满足汇聚突破条件的股票。")


if __name__ == "__main__":
    app = StockScreenerApp(config=ScreenerConfig())
    app.run()