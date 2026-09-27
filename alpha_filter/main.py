# main.py
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import logging
import pandas as pd

from config import cfg, REPORTS_DIR
from fetch import DataFetcher
from evaluator import StrategyEvaluator

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("Runner")

def process_symbol(symbol: str, meta: dict, fetcher: DataFetcher, evaluator: StrategyEvaluator):
    """单只股票的数据处理与策略判定子任务"""
    df = fetcher.fetch_single_kline(symbol, meta["float_shares"])
    if df is None or len(df) < cfg.MIN_KLINE_BARS:
        return None, None

    sig_a = evaluator.evaluate_strategy_a(df.copy(), meta)
    sig_b = evaluator.evaluate_strategy_b(df.copy(), meta)
    return sig_a, sig_b

def main():
    start_time = datetime.now()
    fetcher = DataFetcher(cfg)
    evaluator = StrategyEvaluator(cfg)

    # 1. 取得全市场代码与基本行情快照
    raw_symbols = fetcher.get_market_symbols()
    if not raw_symbols:
        logger.error("未获取到全市场标的，退出。")
        return

    # 2. 盘前/盘中极速快照粗筛
    valid_pool = fetcher.prefilter_pool(raw_symbols)
    logger.info(f"开始对 {len(valid_pool)} 只有效标的执行深度特征与策略扫描...")

    signals_a = []
    signals_b = []

    # 3. 线程池并发处理
    completed_count = 0
    with ThreadPoolExecutor(max_workers=cfg.MAX_WORKERS) as executor:
        futures = {
            executor.submit(process_symbol, sym, meta, fetcher, evaluator): sym
            for sym, meta in valid_pool.items()
        }

        for future in as_completed(futures):
            completed_count += 1
            if completed_count % 300 == 0 or completed_count == len(valid_pool):
                logger.info(f"扫描进度: {completed_count}/{len(valid_pool)}")

            try:
                sig_a, sig_b = future.result()
                if sig_a:
                    signals_a.append(sig_a)
                if sig_b:
                    signals_b.append(sig_b)
            except Exception as e:
                logger.debug(f"任务异常: {e}")

    # 4. 生成 CSV 报告
    today_str = datetime.today().strftime("%Y%m%d")
    
    # 导出方案 A 报告
    if signals_a:
        df_a = pd.DataFrame(signals_a)
        csv_path_a = REPORTS_DIR / f"strategy_a_breakout_{today_str}.csv"
        df_a.to_csv(csv_path_a, index=False, encoding="utf_8_sig")
        logger.info(f"方案 A（筹码突破）筛选完成，捕获 {len(df_a)} 只标的，报告已保存至: {csv_path_a}")
    else:
        logger.info("方案 A（筹码突破）今日无触发标的。")

    # 导出方案 B 报告
    if signals_b:
        df_b = pd.DataFrame(signals_b)
        csv_path_b = REPORTS_DIR / f"strategy_b_divergence_{today_str}.csv"
        df_b.to_csv(csv_path_b, index=False, encoding="utf_8_sig")
        logger.info(f"方案 B（顶底背离）筛选完成，捕获 {len(df_b)} 只标的，报告已保存至: {csv_path_b}")
    else:
        logger.info("方案 B（顶底背离）今日无触发标的。")

    elapsed = (datetime.now() - start_time).total_seconds()
    logger.info(f"全流程运行完毕，总耗时: {elapsed:.1f} 秒。")

if __name__ == "__main__":
    main()