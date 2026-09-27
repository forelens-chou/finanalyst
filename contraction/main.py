"""
main.py - 扫描调度与 CSV 结果生成主程序
"""
import os
import csv
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd

import config as cfg
from market import load_stock_targets
from fetch import DataFetcher
from strategy import run_strategy

def main():
    start_time = time.time()
    print("=" * 65)
    print("  A股极致缩量突破策略扫描系统启动")
    print(f"  配置参数: 90日换手峰值 > {cfg.MIN_TURNOVER_90D}% | 30日换手峰值 > {cfg.MIN_TURNOVER_30D}%")
    print(f"  缩量要求: 30日最高 / 近3日最低 >= {cfg.MIN_SHRINK_RATIO}倍")
    print("=" * 65)

    # 1. 加载股票代码
    targets = load_stock_targets()
    if not targets:
        print("[!] 未找到任何有效的股票标的，程序退出。")
        return

    fetcher = DataFetcher()

    # 2. 批量拉取实时快照（用于获取实时流通股本和粗筛）
    print("[*] 正在批量拉取基础快照与流通股本...")
    all_symbols = [t[1] for t in targets]
    snapshots = fetcher.fetch_snapshots(all_symbols)
    print(f"[+] 快照拉取完毕，有效标的数: {len(snapshots)}")

    # 3. 多线程并发执行日 K 线抓取与策略筛选
    print(f"[*] 开始多线程并发扫描日K线形态 (并发线程数: {cfg.MAX_WORKERS})...")
    results = []
    processed = 0
    total = len(targets)

    def process_item(item):
        pure_code, symbol = item
        snap = snapshots.get(symbol)
        if not snap or snap["float_shares"] <= 0:
            return None
        
        # 拉取日线数据
        df_kline = fetcher.fetch_kline(symbol, snap["float_shares"])
        if df_kline is None:
            return None
            
        # 执行量化评估
        return run_strategy(df_kline, pure_code, snap["name"])

    with ThreadPoolExecutor(max_workers=cfg.MAX_WORKERS) as executor:
        future_map = {executor.submit(process_item, item): item for item in targets}
        for future in as_completed(future_map):
            res = future.result()
            if res:
                results.append(res)
                print(f"  >>> [命中标的] {res['代码']} {res['名称']} | 缩量: {res['缩量倍数']}倍 | 30日峰值: {res['30日最高换手(%)']}% | 近3日最低: {res['近3日最低换手(%)']}%")
            
            processed += 1
            if processed % 500 == 0 or processed == total:
                print(f"  进度: [{processed}/{total}] ({(processed/total)*100:.1f}%)")

    # 4. 生成 CSV 文档
    os.makedirs(cfg.OUTPUT_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = os.path.join(cfg.OUTPUT_DIR, f"shrink_candidates_{timestamp}.csv")

    if results:
        df_res = pd.DataFrame(results)
        # 按缩量倍数从高到低排序
        df_res = df_res.sort_values(by="缩量倍数", ascending=False)
        
        # 写入 CSV：强制代码列作为字符串输出，加上 utf_8_sig 确保 Excel 打开中文正常且不吞掉前导 0
        df_res.to_csv(out_file, index=False, encoding="utf_8_sig", quoting=csv.QUOTE_NONNUMERIC)
        print("=" * 65)
        print(f"[+] 扫描完成！共筛选出 {len(results)} 只符合条件的标的。")
        print(f"[+] 结果已保存至 CSV: {os.path.abspath(out_file)}")
    else:
        print("=" * 65)
        print("[-] 扫描完成，当前市场中未发现符合该极端缩量条件的股票。")

    print(f"[*] 耗时: {time.time() - start_time:.2f} 秒")
    print("=" * 65)

if __name__ == "__main__":
    main()