import pandas as pd
import numpy as np
from fetch import DataFetcher
from config import cfg

fetcher = DataFetcher(cfg)
print("正在拉取 BK1032 风电设备 日K线...")
df = fetcher.fetch_single_kline("BK1032")

if df is None or len(df) == 0:
    print("❌ 错误：未获取到 BK1032 的K线数据！请检查接口连接！")
    exit()

print(f"✅ 成功获取 K线数据，总共 {len(df)} 根 K 线。")
print(f"数据起始日期: {df['date'].iloc[0].date()} ~ 最新日期: {df['date'].iloc[-1].date()}")
print(f"最新价: {df['close'].iloc[-1]}")

# 截取近 180 根 K 线
sub_df = df.tail(180).reset_index(drop=True)
highs = sub_df["high"].values
lows = sub_df["low"].values
closes = sub_df["close"].values

max_idx = int(np.argmax(highs))
min_idx = int(np.argmin(lows))

print(f"\n--- 统计分析 ---")
print(f"最高价: {highs[max_idx]} (日期: {sub_df['date'].iloc[max_idx].date()}, 距今: {len(sub_df) - 1 - max_idx} 根K线)")
print(f"最低价: {lows[min_idx]} (日期: {sub_df['date'].iloc[min_idx].date()}, 距今: {len(sub_df) - 1 - min_idx} 根K线)")
drop = (highs[max_idx] - lows[min_idx]) / highs[max_idx]
print(f"最大跌幅: {drop * 100:.2f}%")

