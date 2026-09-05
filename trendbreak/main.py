# main.py
import sys
import argparse
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from data_provider import get_kline_data, get_all_a_shares
from geometry_engine import TrendlineFitter
from screener import evaluate_pattern
from visualizer import plot_breakout_pattern

# 全局计数统计字典
STATS = {
    'total': 0,
    'fetch_success': 0,
    'trendline_fitted': 0,
    'drop_ok': 0,
    'ma_converged': 0,
    'distance_ok': 0,
    'matched': 0
}

def process_single_stock(code: str, name: str, period: str):
    # 强制保证 6 位标准代码
    pure_code = str(code).strip().zfill(6)
    
    try:
        df = get_kline_data(pure_code, period=period, lookback=180)
        if df.empty or len(df) < 50:
            return None
        
        STATS['fetch_success'] += 1

        # 1. 拟合压制线
        fitter = TrendlineFitter(df)
        trend_info = fitter.fit_upper_resistance_line()
        if trend_info is None:
            return None
        
        STATS['trendline_fitted'] += 1

        # 2. 评估临界变盘
        metrics = evaluate_pattern(df, trend_info)
        if metrics is None:
            return None

        # 统计分析
        if metrics['drop_pct'] >= 15.0:
            STATS['drop_ok'] += 1
        if metrics['ma_spread'] <= 5.5:
            STATS['ma_converged'] += 1
        if -4.0 <= metrics['distance_pct'] <= 2.5:
            STATS['distance_ok'] += 1

        if not metrics['is_matched']:
            return None

        STATS['matched'] += 1

        # 3. 绘图保存
        plot_breakout_pattern(pure_code, name, df, trend_info, metrics, period=period)
        
        return {
            'code': pure_code,
            'name': name,
            'curr_close': metrics['curr_close'],
            'line_price': metrics['line_price'],
            'distance_pct': metrics['distance_pct'],
            'ma_spread': metrics['ma_spread'],
            'drop_pct': metrics['drop_pct']
        }
    except Exception as e:
        return None

def main():
    parser = argparse.ArgumentParser(description="股票下行趋势临界变盘筛选系统")
    parser.add_argument("--period", type=str, default="day", choices=["day", "week"], help="周期：day 或 week")
    parser.add_argument("--workers", type=int, default=10, help="并发线程数")
    args = parser.parse_args()

    stock_df = get_all_a_shares()
    if stock_df.empty:
        print("all_stocks.csv 为空或不存在，请先运行 build_stock_list.py")
        return

    STATS['total'] = len(stock_df)
    print(f"\n=======================================================")
    print(f" 开始全市场漏斗扫描 | 周期: 【{args.period.upper()}】 | 标的总数: {STATS['total']}")
    print(f"=======================================================")

    results = []
    completed = 0

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        future_map = {
            executor.submit(process_single_stock, row['代码'], row['名称'], args.period): (row['代码'], row['名称'])
            for _, row in stock_df.iterrows()
        }

        for future in as_completed(future_map):
            completed += 1
            code, name = future_map[future]
            progress = (completed / STATS['total']) * 100
            sys.stdout.write(f"\r进度: [{completed}/{STATS['total']}] ({progress:.1f}%) | 正在分析: {code} | 已命中: {STATS['matched']}")
            sys.stdout.flush()

            res = future.result()
            if res:
                results.append(res)
                print(f"\n★ 命中: [{res['code']}] {res['name']} | 现价:{res['curr_close']} 阻力线:{res['line_price']} 偏差:{res['distance_pct']}% 均线带宽:{res['ma_spread']}%")

    print("\n\n" + "="*50)
    print("【全市场扫描漏斗数据报表】")
    print(f" 1. 扫描股票总数:         {STATS['total']}")
    print(f" 2. 成功获取 K 线数据:     {STATS['fetch_success']}  {'⚠️ 数据异常！' if STATS['fetch_success'] < 100 else '✅ 正常'}")
    print(f" 3. 成功拟合下行压制线:   {STATS['trendline_fitted']}")
    print(f" 4. 累计跌幅充分(>=15%):  {STATS['drop_ok']}")
    print(f" 5. 均线相对收敛(<=5.5%): {STATS['ma_converged']}")
    print(f" 6. 现价紧贴阻力线:       {STATS['distance_ok']}")
    print(f" 7. 最终全部满足并命中:   {STATS['matched']}")
    print("="*50)

    if results:
        res_df = pd.DataFrame(results).sort_values(by='distance_pct', ascending=False)
        print(f"\n成功输出 {len(res_df)} 只临界突破标的：")
        print(res_df.to_string(index=False))
        out_csv = f"breakout_{args.period}.csv"
        res_df.to_csv(out_csv, index=False, encoding='utf-8-sig')
        print(f"\nCSV 结果已输出至: {out_csv}")
        print(f"K线图已分别保存至: ./output_charts/{args.period}/")
    else:
        print("\n未发现满足所有条件的标的。请查看上方漏斗报表，看哪一项数值过低，即可针对性放宽该阈值。")

if __name__ == "__main__":
    main()