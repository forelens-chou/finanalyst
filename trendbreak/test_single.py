# test_single.py
from data_provider import get_kline_data
from geometry_engine import TrendlineFitter
from screener import evaluate_pattern
from visualizer import plot_breakout_pattern

symbol = "300898"
name = "普昂医疗"

print(f"正在拉取 {name}({symbol}) 数据...")
df = get_kline_data(symbol, lookback_days=180)

if df.empty:
    print("获取数据失败，请检查网络！")
else:
    print(f"成功获取 {len(df)} 根K线，正在拟合几何压力线...")
    fitter = TrendlineFitter(df)
    trend_info = fitter.fit_upper_resistance_line()

    if trend_info is None:
        print("未拟合出有效的下行压制线。")
    else:
        print(f"成功拟合压力线！起点最高点: {trend_info['p0_date']} (价格: {trend_info['p0_price']})")
        metrics = evaluate_pattern(df, trend_info)
        print(f"现价: {metrics['curr_close']}")
        print(f"压力线理论价: {metrics['line_price']}")
        print(f"距压力线偏差: {metrics['distance_pct']}%")
        print(f"均线粘合度: {metrics['ma_spread']}%")
        print(f"是否命中临界转折: {metrics['is_matched']}")

        # 绘图输出
        plot_breakout_pattern(symbol, name, df, trend_info, metrics)