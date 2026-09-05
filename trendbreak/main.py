# main.py
import sys
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from data_provider import get_kline_data, get_all_a_shares
from geometry_engine import TrendlineFitter
from screener import evaluate_pattern
from visualizer import plot_breakout_pattern

def process_single_stock(code: str, name: str):
    """单只股票处理任务（线程工作单元）"""
    try:
        df = get_kline_data(code, lookback_days=180)
        if df.empty or len(df) < 60:
            return None

        # 1. 几何拟合
        fitter = TrendlineFitter(df)
        trend_info = fitter.fit_upper_resistance_line()
        if trend_info is None:
            return None

        # 2. 临界变盘指标判定
        metrics = evaluate_pattern(df, trend_info)
        if metrics is None or not metrics['is_matched']:
            return None

        # 3. 命中目标，输出绘图
        plot_breakout_pattern(code, name, df, trend_info, metrics)
        
        return {
            'code': code,
            'name': name,
            'curr_close': metrics['curr_close'],
            'line_price': metrics['line_price'],
            'distance_pct': metrics['distance_pct'],
            'ma_spread': metrics['ma_spread'],
            'drop_pct': metrics['drop_pct']
        }
    except Exception:
        return None

def scan_entire_market(max_workers: int = 12):
    """
    全市场多线程并发扫描
    """
    stock_df = get_all_a_shares()
    total_count = len(stock_df)
    print(f"\n=======================================================")
    print(f" 开始全市场并发扫描 (共 {total_count} 只标的，并发线程数: {max_workers})")
    print(f"=======================================================")

    results = []
    completed = 0

    # 使用线程池并发抓取与分析
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {
            executor.submit(process_single_stock, row['代码'], row['名称']): (row['代码'], row['名称'])
            for _, row in stock_df.iterrows()
        }

        for future in as_completed(future_map):
            completed += 1
            code, name = future_map[future]
            
            # 控制台单行实时进度刷新
            progress = (completed / total_count) * 100
            sys.stdout.write(f"\r进度: [{completed}/{total_count}] ({progress:.1f}%) | 正在分析: {code} {name} | 命中数量: {len(results)}")
            sys.stdout.flush()

            try:
                res = future.result()
                if res:
                    results.append(res)
                    print(f"\n★ 命中形态: [{res['code']}] {res['name']} | 现价:{res['curr_close']} 压力线:{res['line_price']} 偏差:{res['distance_pct']}% 均线带宽:{res['ma_spread']}%")
            except Exception:
                pass

    print("\n\n" + "="*75)
    print("【全市场扫描完成，变盘临界标的汇总】")
    if results:
        res_df = pd.DataFrame(results)
        # 按离压力线的贴近程度排序
        res_df = res_df.sort_values(by='distance_pct', ascending=False)
        print(res_df.to_string(index=False))
        
        # 结果保存为 CSV
        output_csv = "breakout_candidates.csv"
        res_df.to_csv(output_csv, index=False, encoding='utf-8-sig')
        print(f"\n结果已成功导出至: {output_csv}")
        print(f"所有命中股票的高清 K 线图已生成在: ./output_charts/")
    else:
        print("未发现满足严格收敛条件的股票，可适当放宽 screener.py 中的均线粘合度阈值。")
    print("="*75)

if __name__ == "__main__":
    scan_entire_market(max_workers=12)