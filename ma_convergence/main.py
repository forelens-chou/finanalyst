"""
A股多周期均线汇聚与向上突破选股系统 - 主执行程序
命令行支持：
  1. 默认执行全市场扫描:   python main.py
  2. 指定文档筛选:        python main.py watchlist_sample.txt
  3. 参数显式指定:        python main.py -f /path/to/my_stocks.csv
"""

import argparse
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
        """检查近 N 根 K 线内是否存在涨停板"""
        if raw_code.startswith(("68", "30")):
            threshold = self.cfg.GROWTH_LIMIT_UP_PCT
        elif raw_code.startswith(("8", "4", "9")):
            threshold = self.cfg.BSE_LIMIT_UP_PCT
        else:
            threshold = self.cfg.MAIN_LIMIT_UP_PCT

        pct_series = (df["close"] - df["close"].shift(1)) / df["close"].shift(1) * 100.0
        lookback_pcts = pct_series.iloc[-self.cfg.LIMIT_UP_LOOKBACK_BARS :]
        return bool((lookback_pcts >= threshold).any())

    def evaluate(self, raw_code: str, name: str, df: pd.DataFrame) -> Optional[dict]:
        total_bars = len(df)
        if total_bars < self.cfg.MIN_LISTING_DAYS:
            return None

        close = df["close"]
        volume = df["volume"]

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

        ma_vol5 = volume.rolling(5).mean().iloc[-1]
        latest_vol = volume.iloc[-1]
        vol_ratio = latest_vol / ma_vol5 if ma_vol5 > 0 else 0.0

        has_limit_up = self._has_recent_limit_up(raw_code, df)

        matched_rule = None
        converged_names = []
        cluster_bandwidth = 0.0
        cluster_max_val = 0.0

        # 条件 A: 5条及以上汇聚
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

        # 条件 B: 4条均线汇聚（有涨停仅需汇聚，无涨停需向上汇聚）
        if not matched_rule and n >= 4:
            for i in range(n - 4 + 1):
                window = sorted_ma[i : i + 4]
                min_v = window[0][1]
                max_v = window[-1][1]
                spread = (max_v - min_v) / min_v
                if spread <= self.cfg.BANDWIDTH_4LINES:
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

        # 条件 C: 必须站上粘合最高均线，当日收阳或平盘
        if not (latest_close >= cluster_max_val and latest_close >= latest_open and pct_chg >= 0):
            return None

        # 条件 D: 成交量确认（含涨停放量豁免）
        is_vol_expanded = vol_ratio >= self.cfg.VOL_RATIO_MIN
        require_volume = True
        if self.cfg.LIMIT_UP_WAIVE_VOLUME and has_limit_up:
            require_volume = False

        if require_volume and not is_vol_expanded:
            return None

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
    def __init__(self, config: ScreenerConfig, custom_file: Optional[str] = None):
        self.cfg = config
        self.custom_file = custom_file
        self.fetcher = DataFetcher(config)
        self.engine = StrategyEngine(config)

    def run(self):
        start_time = time.time()

        # 判断执行模式：外部股票池还是全市场扫描
        is_custom_mode = self.custom_file is not None
        if is_custom_mode:
            logger.info(f"★ 运行模式: 指定文档筛选 [{self.custom_file}]")
            raw_symbols = self.fetcher.load_symbols_from_file(self.custom_file)
            skip_liq = self.cfg.CUSTOM_POOL_SKIP_LIQUIDITY
        else:
            logger.info("★ 运行模式: 全市场扫描")
            raw_symbols = self.fetcher.get_market_symbols()
            skip_liq = False

        pool = self.fetcher.prefilter_pool(raw_symbols, skip_liquidity=skip_liq)
        if not pool:
            logger.warning("有效候选池为空，程序退出。")
            return

        # 动态自适应调整线程数
        workers = min(self.cfg.MAX_WORKERS, max(1, len(pool)))
        logger.info(f"启动 {workers} 线程拉取 K 线并执行形态计算...")

        results = []
        fetch_success = 0
        fetch_fail = 0

        def worker_task(item: dict):
            df_kline = self.fetcher.get_kline(item["symbol"])
            if df_kline is None:
                return False, None
            return True, self.engine.evaluate(item["code"], item["name"], df_kline)

        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_stock = {executor.submit(worker_task, item): item for item in pool}
            completed = 0
            for future in as_completed(future_to_stock):
                completed += 1
                if completed % 200 == 0 or completed == len(pool):
                    logger.info(f"进度: {completed}/{len(pool)} ({(completed/len(pool)*100):.1f}%)")

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

            # 自定义文件模式下在输出文件名中打上标记，防止覆盖全市场报表
            file_tag = ""
            if is_custom_mode:
                base_name = os.path.splitext(os.path.basename(self.custom_file))[0]
                file_tag = f"_custom_{base_name}"

            csv_filename = os.path.join("results", f"ma_converged_{timestamp}{file_tag}.csv")
            df_res.to_csv(csv_filename, index=False, encoding="utf_8_sig")
            logger.info(f"标准分析报表已保存: {csv_filename}")

            txt_filename = os.path.join("results", f"import_to_em_{timestamp}{file_tag}.txt")
            with open(txt_filename, "w", encoding="utf-8") as f:
                for code in df_res["code"]:
                    f.write(f"{code}\n")
            logger.info(f"东方财富一键导入 TXT 码单已保存: {txt_filename}")
        else:
            logger.info("所选股票池中未发现满足汇聚突破条件的股票。")


# ==================== 命令行入口 ====================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="A股多周期均线汇聚量化选股系统")
    parser.add_argument(
        "file",
        nargs="?",
        default=None,
        help="可选：外部股票池文件路径（支持 .txt / .csv）。不填则默认全市场扫描。"
    )
    parser.add_argument(
        "-f", "--file-path",
        dest="opt_file",
        default=None,
        help="可选：显式指定外部股票池文件路径"
    )

    args = parser.parse_args()
    target_file = args.file or args.opt_file

    app = StockScreenerApp(config=ScreenerConfig(), custom_file=target_file)
    app.run()