from fetch import DataFetcher
from config import cfg
import numpy as np

fetcher = DataFetcher(cfg)
# 测试风电设备对应的标的 sz159811
symbol = "sz159811"
print(f"正在拉取 {symbol} K线数据...")
df = fetcher.fetch_single_kline(symbol)

if df is None or len(df) == 0:
    print("❌ 获取K线失败！")
    exit()

print(f"✅ 成功获取 {len(df)} 根K线，日期范围: {df['date'].iloc[0].date()} ~ {df['date'].iloc[-1].date()}")
print(f"最新收盘价: {df['close'].iloc[-1]}")

sub_df = df.tail(200).reset_index(drop=True)
highs = sub_df['high'].values
lows = sub_df['low'].values
closes = sub_df['close'].values
total_len = len(sub_df)

p0_idx = int(np.argmax(highs[:total_len - 25]))
t3_idx = int(np.argmin(lows[p0_idx + 10:]) + (p0_idx + 10))

print("\n=== 关键数据点分析 ===")
print(f"P0 顶峰: 价格 {highs[p0_idx]}, 日期 {sub_df['date'].iloc[p0_idx].date()}, 距今 {total_len - 1 - p0_idx} 天")
print(f"T3 底谷: 价格 {lows[t3_idx]}, 日期 {sub_df['date'].iloc[t3_idx].date()}, 距今 {total_len - 1 - t3_idx} 天")

drop_pct = (highs[p0_idx] - lows[t3_idx]) / highs[p0_idx] * 100
print(f"区间最大跌幅: -{drop_pct:.2f}%")

# 寻找反弹高点拟合趋势线
mid_highs = highs[p0_idx + 5 : t3_idx]
if len(mid_highs) > 0:
    p_ctrl_idx = int(p0_idx + 5 + np.argmax(mid_highs))
    slope = (highs[p_ctrl_idx] - highs[p0_idx]) / (p_ctrl_idx - p0_idx)
    intercept = highs[p0_idx] - slope * p0_idx
    curr_trend_val = slope * (total_len - 1) + intercept
    print(f"反弹控制点: 价格 {highs[p_ctrl_idx]}, 日期 {sub_df['date'].iloc[p_ctrl_idx].date()}")
    print(f"当前趋势线对应价格: {curr_trend_val:.3f}, 当前实际收盘价: {closes[-1]:.3f}")
    print(f"是否站上趋势线: {'✅ 是' if closes[-1] >= curr_trend_val else '❌ 否'}")

