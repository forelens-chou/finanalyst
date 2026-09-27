# main.py
"""
系统主入口：
1. 修复板块 symbol (行情抓取代码) 与 code (展示代码如BK1032) 的映射
2. 动态区分板块与个股的跌幅自适应阈值
3. 板块 CSV 第一列为 BKxxxx，个股 CSV 第一列为纯数字代码
"""
import argparse
import concurrent.futures
import logging
import os
import time
from typing import Dict, List

import pandas as pd

from config import OUTPUT_DIR, cfg
from fetch import DataFetcher
from wave_trend_detector import WaveTrendDetector
from visualizer import ChartVisualizer

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("MainScanner")


def process_single_task(fetcher: DataFetcher, detector: WaveTrendDetector, visualizer: ChartVisualizer, item: dict) -> dict:
    symbol = item["symbol"]       # 用于拉取 K 线的行情代码 (如 sz159811 或 600519)
    pure_code = item["code"]      # 用于展示与导出的代码 (如 BK1032 或 600519)
    name = item["name"]
    category = item.get("category", "标的")
    float_shares = item.get("float_shares", 0.0)

    # 1. 抓取日K线
    df = fetcher.fetch_single_kline(symbol, float_shares=float_shares)
    if df is None or len(df) < 50:
        return None

    # 2. 5浪与趋势线突破检测 (板块与个股自适应阈值)
    is_sector = category in ["行业板块", "概念板块"]
    matched, meta = detector.detect_pattern(df, is_sector=is_sector)
    if not matched:
        return None

    logger.info(f"===> 🎯 命中目标 [{category}]: {pure_code} {name} | 跌幅: -{meta['max_drop_pct']}% | 突破日: {meta['breakout_date']}")

    # 3. 绘制并保存走势图
    img_path = visualizer.render_and_save(pure_code, name, category, meta)

    if is_sector:
        return {
            "板块代码": pure_code,       # 第一列：BKxxxx
            "板块名称": name,
            "板块类别": category,
            "综合打分": meta["score"],
            "最大跌幅%": meta["max_drop_pct"],
            "突破日期": meta["breakout_date"],
            "突破价格": meta["breakout_price"],
            "波段顶峰日期": meta["p0"][1],
            "波段底谷日期": meta["t3"][1],
            "最低点价格": meta["t3"][2],
            "MACD底背离": "是" if meta["macd_divergence"] else "否",
            "图表路径": img_path
        }
    else:
        return {
            "股票代码": pure_code,       # 第一列：纯6位数字
            "股票名称": name,
            "类别": category,
            "综合打分": meta["score"],
            "最大跌幅%": meta["max_drop_pct"],
            "突破日期": meta["breakout_date"],
            "突破价格": meta["breakout_price"],
            "波段顶峰日期": meta["p0"][1],
            "波段底谷日期": meta["t3"][1],
            "最低点价格": meta["t3"][2],
            "MACD底背离": "是" if meta["macd_divergence"] else "否",
            "图表路径": img_path
        }


def main():
    parser = argparse.ArgumentParser(description="下跌5浪与趋势线突破扫描器")
    parser.add_argument(
        "--mode",
        type=str,
        choices=["sector", "stock", "all"],
        default="sector",
        help="筛选模式: 'sector' (行业与概念板块), 'stock' (全市场个股), 'all' (两者全部)"
    )
    args = parser.parse_args()

    start_time = time.time()
    logger.info(f"=== 启动扫描器 | 当前模式: {args.mode.upper()} ===")

    fetcher = DataFetcher(cfg)
    detector = WaveTrendDetector(cfg)
    visualizer = ChartVisualizer()

    target_items: List[dict] = []

    # 1. 行业与概念板块模式
    if args.mode in ["sector", "all"]:
        sector_raw = fetcher.get_eastmoney_sectors(sector_type="all")
        for sym, code, name, cat in sector_raw:
            target_items.append({
                "symbol": sym,           # 关键修复：拉取K线用畅通的行情代码 (sym)
                "code": code,            # 展示和导出的板块代码 (BK1032等)
                "name": name,
                "category": cat,
                "float_shares": 0.0
            })

    # 2. 个股模式
    if args.mode in ["stock", "all"]:
        stock_raw = fetcher.get_market_symbols()
        valid_stocks = fetcher.prefilter_stocks(stock_raw)
        target_items.extend(list(valid_stocks.values()))

    if not target_items:
        logger.error("未获取到待扫描的标的清单，请检查网络！")
        return

    logger.info(f"进入深度形态扫描标的数量: {len(target_items)} 个，配置并发线程: {cfg.MAX_WORKERS}")

    results: List[Dict] = []
    completed = 0
    total = len(target_items)

    with concurrent.futures.ThreadPoolExecutor(max_workers=cfg.MAX_WORKERS) as executor:
        futures = {
            executor.submit(process_single_task, fetcher, detector, visualizer, item): item["code"]
            for item in target_items
        }

        for future in concurrent.futures.as_completed(futures):
            completed += 1
            if completed % 50 == 0 or completed == total:
                logger.info(f"扫描进度: {completed}/{total} ({completed / total * 100:.1f}%)")
            try:
                res = future.result()
                if res:
                    results.append(res)
            except Exception as e:
                code_id = futures[future]
                logger.debug(f"{code_id} 处理异常: {e}")

    # 3. 导出结果
    if results:
        df_out = pd.DataFrame(results)
        df_out = df_out.sort_values(by="综合打分", ascending=False).reset_index(drop=True)

        date_str = time.strftime("%Y%m%d_%H%M%S")
        csv_name = f"scan_{args.mode}_{date_str}.csv"
        csv_path = os.path.join(OUTPUT_DIR, csv_name)
        df_out.to_csv(csv_path, index=False, encoding="utf-8-sig")

        logger.info(f"✅ 扫描完成！共命中 {len(df_out)} 个符合标的。")
        logger.info(f"📊 结果清单已保存至: {csv_path}")
        logger.info(f"🖼️ 图表已输出至目录: {os.path.abspath(os.path.join(OUTPUT_DIR, 'charts'))}")
    else:
        logger.warning(f"⚠️ 在 {args.mode} 模式下未匹配到符合标的。")

    logger.info(f"全流程总耗时: {time.time() - start_time:.2f} 秒")


if __name__ == "__main__":
    main()