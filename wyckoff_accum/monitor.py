# monitor.py
from datetime import datetime
import glob
import logging
import os
import time
import pandas as pd

from config import cfg, OUTPUT_DIR
from fetch import DataFetcher

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("Monitor")

def load_latest_watchlist(mode: str) -> pd.DataFrame:
    pattern = f"watchlist_{mode}_*.csv"
    files = sorted(glob.glob(str(OUTPUT_DIR / pattern)))
    if not files:
        raise FileNotFoundError(f"未找到 {mode} 模式的观察池文件，请先运行 python screener.py --mode {mode}")
    latest_file = files[-1]
    logger.info(f"成功加载监控文件: {latest_file}")
    return pd.read_csv(latest_file)

def run_monitor(poll_interval: int = 5):
    watch_df = load_latest_watchlist()
    symbols = watch_df["symbol"].tolist()
    code_meta = watch_df.set_index("symbol").to_dict(orient="index")
    fetcher = DataFetcher()

    logger.info(f"🚀 盘中监控引擎已启动，监控标的: {len(symbols)} 只 | 刷新频率: {poll_interval}s")

    while True:
        now = datetime.now()
        now_time = now.strftime("%H:%M:%S")

        # 仅在交易时段执行
        is_trading = ("09:30:00" <= now_time <= "11:30:00") or ("13:00:00" <= now_time <= "15:00:00")
        if not is_trading:
            time.sleep(10)
            continue

        snapshots = fetcher.fetch_realtime_snapshot(symbols)
        is_tail_ambush_window = ("14:45:00" <= now_time <= "14:57:00")

        for sym, snap in snapshots.items():
            meta = code_meta.get(sym, {})
            price = snap["price"]
            high = snap["high"]
            low = snap["low"]
            gain = snap["gain_pct"]
            turnover = snap["turnover_pct"]
            vol_ratio = snap["volume_ratio"]
            hard_stop = meta.get("hard_stop_price", 0)

            # 1. 止损预警：现价跌破硬止损线
            if price < hard_stop and price > 0:
                print(f"🚨【止损预警】{meta['name']}({meta['code']}) 跌破止损线 {hard_stop}！当前价: {price} | 立即离场规避破位")

            # 2. 尾盘潜伏预警 (14:45 - 14:57)
            if is_tail_ambush_window:
                amp = (high - low) / price if price > 0 else 0
                if (turnover <= cfg.TURNOVER_SHRINK_MAX and amp <= cfg.CANDLE_AMPLITUDE_MAX and price >= hard_stop):
                    print(f"🎯【潜伏试仓预警】{meta['name']}({meta['code']}) 满足极度缩量探底！"
                          f"现价: {price} | 今日换手: {turnover}% | 振幅: {round(amp*100, 2)}% | 建议建立 20%-30% 侦察仓，止损位: {hard_stop}")

            # 3. 盘中主升突破预警 (放量突破平台)
            if gain >= cfg.BREAKOUT_GAIN_MIN * 100 and vol_ratio >= cfg.BREAKOUT_VOLUME_RATIO:
                print(f"⚡【放量突破预警】{meta['name']}({meta['code']}) 出现主力异动！"
                      f"现价: {price} | 涨幅: +{gain}% | 量比: {vol_ratio} | 建议顺势右侧跟进或加仓")

        time.sleep(poll_interval)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="盘中监控引擎")
    parser.add_argument("--mode", type=str, choices=["subnew", "all"], default="subnew",
                        help="监控模式: subnew 或 all")
    args = parser.parse_args()
    run_monitor(mode=args.mode)