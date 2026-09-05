# debug_stock.py
import sys
import pandas as pd
from data_provider import get_kline_data
from geometry_engine import TrendlineFitter
from screener import evaluate_pattern

code = "300059"  # 东方财富
print(f"========== 开始诊断 [{code}] ==========")

# 1. 检查数据拉取
df = get_kline_data(code, period="day", lookback=180, force_update=True)
print(f"1. 数据获取: 共获取到 {len(df)} 根K线 (预期 > 60)")
if df.empty or len(df) < 60:
    print("❌ 错误：K线数据拉取失败或数据不足！请检查网络或代码补零！")
    sys.exit(0)

# 2. 检查几何压制线拟合
fitter = TrendlineFitter(df)
trend_info = fitter.fit_upper_resistance_line()
if trend_info is None:
    print("❌ 拦截点：未能拟合出下行压制线 (可能因最高点位置或穿透率超标)")
    sys.exit(0)
else:
    print(f"2. 压制线拟合成功: 起点日期={trend_info['p0_date']}, 起点价格={trend_info['p0_price']}, 斜率k={trend_info['k']:.4f}")

# 3. 检查指标评估
curr_idx = len(df) - 1
curr_close = df['close'].iloc[curr_idx]
line_price = trend_info['k'] * curr_idx + trend_info['b']
distance_pct = (curr_close - line_price) / line_price * 100

df['ma5'] = df['close'].rolling(5).mean()
df['ma10'] = df['close'].rolling(10).mean()
df['ma20'] = df['close'].rolling(20).mean()
df['ma30'] = df['close'].rolling(30).mean()
df['ma60'] = df['close'].rolling(60).mean()
ma_vals = [df['ma5'].iloc[-1], df['ma10'].iloc[-1], df['ma20'].iloc[-1], df['ma30'].iloc[-1], df['ma60'].iloc[-1]]
ma_spread = (max(ma_vals) - min(ma_vals)) / df['ma20'].iloc[-1] * 100
drop_pct = (trend_info['p0_price'] - curr_close) / trend_info['p0_price'] * 100

print(f"3. 核心指标实测值:")
print(f"   - 现价: {curr_close} | 阻力线理论价: {line_price:.2f}")
print(f"   - 距阻力线偏差 distance_pct : {distance_pct:.2f}%  (当前阈值: -3.0% ~ +2.0%) -> {'✅ 通过' if -3.0 <= distance_pct <= 2.0 else '❌ 拦截'}")
print(f"   - 均线粘合度 ma_spread       : {ma_spread:.2f}%      (当前阈值: <= 4.0%)       -> {'✅ 通过' if ma_spread <= 4.0 else '❌ 拦截'}")
print(f"   - 历史回撤幅度 drop_pct      : {drop_pct:.2f}%     (当前阈值: >= 20.0%)      -> {'✅ 通过' if drop_pct >= 20.0 else '❌ 拦截'}")

res = evaluate_pattern(df, trend_info)
print(f"\n最终判定 is_matched: {res['is_matched'] if res else False}")
print("=========================================")