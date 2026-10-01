# sync.py
import datetime
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Tuple

import pandas as pd
from config import cfg
from db import db
from fetch import DataFetcher

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("SyncManager")

def sync_all_data():
    start_time = datetime.datetime.now()
    fetcher = DataFetcher()

    # 1. 抓取市场股票全清单并预筛选活跃股票池
    logger.info(">>> 步骤 1: 更新基础股票池...")
    raw_symbols = fetcher.get_market_symbols()
    if not raw_symbols:
        logger.error("未获取到股票清单，同步中断！")
        return

    active_pool = fetcher.prefilter_pool(raw_symbols)
    # 保存基础信息进数据库
    db.save_stock_basics(list(active_pool.values()))
    logger.info(f"股票池初筛完毕，待更新/同步活跃股票数: {len(active_pool)} 只")

    # 2. 查询本地数据库每只股票的最新日期，判断增量还是全量
    logger.info(">>> 步骤 2: 检查本地缓存进度 (增量判断)...")
    latest_date_map = db.get_latest_dates()
    today_str = datetime.date.today().strftime("%Y-%m-%d")

    tasks: List[Tuple[str, float, int]] = []
    for sym, item in active_pool.items():
        last_date = latest_date_map.get(sym)
        # 如果最后更新日期就是今天，跳过
        if last_date == today_str:
            continue
        
        # 如果本地已有最近数据（存在 last_date 且不是今天），只需拉 10 天增量
        # 否则拉取 320 天全量
        fetch_len = 10 if last_date else cfg.DEFAULT_KLINE_LEN
        tasks.append((sym, item["float_shares"], fetch_len))

    logger.info(f"今日需要从网络同步 K 线的标的数: {len(tasks)} 只")
    if not tasks:
        logger.info("所有标的数据已是最新，无须更新！")
        return

    # 3. 线程池并发抓取
    logger.info(f">>> 步骤 3: 启动 {cfg.MAX_WORKERS} 线程并发抓取 K 线...")
    collected_dfs: List[pd.DataFrame] = []
    
    def worker(task):
        sym, float_shares, req_len = task
        df = fetcher.fetch_single_kline(sym, float_shares=float_shares, datalen=req_len)
        return df

    success_count = 0
    with ThreadPoolExecutor(max_workers=cfg.MAX_WORKERS) as executor:
        futures = [executor.submit(worker, t) for t in tasks]
        for f in as_completed(futures):
            res_df = f.result()
            if res_df is not None and not res_df.empty:
                collected_dfs.append(res_df)
                success_count += 1
                
            # 每积累 200 只股票的数据，批量刷盘一次
            if len(collected_dfs) >= 200:
                db.save_klines_batch(collected_dfs)
                collected_dfs.clear()

    # 写入剩余未入库的数据
    if collected_dfs:
        db.save_klines_batch(collected_dfs)
        collected_dfs.clear()

    cost = (datetime.datetime.now() - start_time).total_seconds()
    logger.info(f">>> 同步完成! 成功入库: {success_count}/{len(tasks)} 只标的, 总耗时: {cost:.2f} 秒")

if __name__ == "__main__":
    sync_all_data()