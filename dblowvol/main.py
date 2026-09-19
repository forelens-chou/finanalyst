"""
main.py - 选股系统入口（支持多模式传参并自动导出 CSV）
"""
import sys
import os
import datetime
import logging
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed

from config import ScreenerConfig
from fetch import DataFetcher
from strategy import PatternRecognizer

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ScreenerMain")

def parse_input_file() -> str:
    """智能解析参数：兼容 python main.py stocks.txt 或 python main.py --stocks.txt"""
    if len(sys.argv) > 1:
        arg = sys.argv[1].lstrip("-")
        if arg.endswith(".txt"):
            return arg
        if len(sys.argv) > 2:
            return sys.argv[2]
    return ""

def export_to_csv(results: list, cfg: ScreenerConfig):
    if not results:
        return
    now_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{cfg.CSV_FILENAME_PREFIX}_{now_str}.csv"
    
    # 转换为 DataFrame 并整理列名
    df = pd.DataFrame(results)
    column_mapping = {
        "code": "股票代码",
        "name": "股票名称",
        "latest_close": "最新价",
        "latest_pct": "最新涨幅",
        "pe_ttm": "市盈率(TTM)",
        "low_vol_date": "90天地量日期",
        "is_latest_day_vol": "地量是否最新日",
        "b1_date": "底1日期",
        "b1_low": "底1最低价",
        "b2_date": "底2日期",
        "b2_low": "底2最低价",
        "gap_bars": "两底间隔(K线数)",
        "diff_pct": "底2相对底1幅度"
    }
    
    cols = [k for k in column_mapping.keys() if k in df.columns]
    df = df[cols].rename(columns=column_mapping)
    
    # 使用 utf-8-sig 编码，防止 Excel 打开乱码
    df.to_csv(filename, index=False, encoding="utf-8-sig")
    print(f"\n📁 筛选结果已成功导出至 CSV 文件: {os.path.abspath(filename)}")

def main():
    cfg = ScreenerConfig()
    fetcher = DataFetcher(cfg)
    recognizer = PatternRecognizer(cfg)

    file_path = parse_input_file()
    if file_path:
        raw_symbols = fetcher.load_symbols_from_file(file_path)
    else:
        raw_symbols = fetcher.get_market_symbols()

    # 1. 批量快照初筛
    targets = fetcher.prefilter_pool(raw_symbols)

    # 2. 多线程扫描深度形态
    logger.info("开始拉取 K 线并识别双底与 90 天地量形态...")
    results = []

    def scan_worker(item):
        df = fetcher.get_kline(item["symbol"])
        if df is None:
            return None
        match_info = recognizer.evaluate(df, item["pe_ttm"])
        if match_info:
            return {**item, **match_info}
        return None

    with ThreadPoolExecutor(max_workers=cfg.MAX_WORKERS) as pool:
        futures = {pool.submit(scan_worker, item): item for item in targets}
        for f in as_completed(futures):
            res = f.result()
            if res:
                results.append(res)
                logger.info(
                    f"🎯 [命中] {res['code']} {res['name']} | "
                    f"PE: {res['pe_ttm']} | 地量日: {res['low_vol_date']} (最新日:{res['is_latest_day_vol']}) | "
                    f"两底相距: {res['gap_bars']} 天"
                )

    # 3. 终端打印表格
    print("\n" + "="*96)
    print(f"{'代码':<8}{'名称':<10}{'最新价':<8}{'PE(TTM)':<10}{'地量日期':<12}{'是否最新日':<12}{'底1日期':<12}{'底2日期':<12}{'相隔天数':<8}")
    print("-" * 96)
    for r in results:
        print(f"{r['code']:<8}{r['name']:<10}{r['latest_close']:<8}{r['pe_ttm']:<10}{r['low_vol_date']:<12}{r['is_latest_day_vol']:<12}{r['b1_date']:<12}{r['b2_date']:<12}{r['gap_bars']:<8}")
    print("="*96)
    print(f"扫描完毕，共命中 {len(results)} 只标的。")

    # 4. 自动生成并导出 CSV
    if cfg.EXPORT_CSV:
        export_to_csv(results, cfg)

if __name__ == "__main__":
    main()