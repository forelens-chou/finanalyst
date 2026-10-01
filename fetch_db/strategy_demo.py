# strategy_demo.py
import time
from db import db
from fetch import DataFetcher

def run_ma_breakout_strategy():
    print("开始执行均线突破筛选策略...")
    t0 = time.time()
    
    # 1. 直接从本地数据库读取近 60 天全市场数据（毫秒级读入内存）
    df_all = db.load_all_latest_kline(min_date="2025-01-01")
    print(f"本地读取全市场数据成功: {len(df_all)} 条记录，耗时: {time.time() - t0:.2f} 秒")
    
    selected_symbols = []
    # 2. 纯内存 Pandas 计算各股指标（以单只股票演示）
    for symbol, group in df_all.groupby("symbol"):
        if len(group) < 30:
            continue
        # 计算 20 日均线
        ma20 = group["close"].rolling(20).mean().iloc[-1]
        latest_close = group["close"].iloc[-1]
        
        # 简单策略：收盘价站上 20 日线且放量
        if latest_close > ma20:
            selected_symbols.append(symbol)

    print(f"策略初步筛选出: {len(selected_symbols)} 只标的")
    
    # 3. 盘中如果需要最新报价（秒级变动），最后才拉一次实时切片
    fetcher = DataFetcher()
    realtime_data = fetcher.fetch_realtime_snapshot(selected_symbols[:20]) # 取前20只看盘中
    for sym, snap in realtime_data.items():
        print(f"[{sym}] {snap['name']} 现价:{snap['price']} 涨幅:{snap['gain_pct']}% 量比:{snap['volume_ratio']}")

if __name__ == "__main__":
    run_ma_breakout_strategy()