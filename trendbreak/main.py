# main.py
import os
import sys
import random
import argparse
from datetime import datetime
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from data_provider import get_kline_data, get_all_a_shares
from geometry_engine import TrendlineFitter
from screener import evaluate_pattern
from visualizer import plot_breakout_pattern

OUTPUT_CSV_DIR = "./output_csv"
EXCLUDE_FILE = "exclude_stocks.txt"

STATS = {
    'total': 0,
    'excluded': 0,
    'fetch_success': 0,
    'trendline_fitted': 0,
    'matched': 0
}

def load_exclude_stocks() -> set:
    """加载需要排除的股票黑名单"""
    if not os.path.exists(EXCLUDE_FILE):
        return set()
    
    exclude_set = set()
    try:
        with open(EXCLUDE_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                code = line.strip().split()[0] if line.strip() else ""
                code_pure = ''.join(filter(str.isdigit, code)).zfill(6)
                if code_pure and code_pure != '000000':
                    exclude_set.add(code_pure)
    except Exception as e:
        print(f"读取 {EXCLUDE_FILE} 失败: {e}")
    return exclude_set

def generate_csv_filename(period: str) -> str:
    """生成范例: breakout_day260905001.csv"""
    os.makedirs(OUTPUT_CSV_DIR, exist_ok=True)
    # 获取 YYMMDD 格式（如 2026年9月5日 -> 260905）
    yymmdd = datetime.now().strftime("%y%m%d")
    
    # 查找当天已有文件的最大序号，生成如 001, 002
    prefix = f"breakout_{period}{yymmdd}"
    existing_files = [f for f in os.listdir(OUTPUT_CSV_DIR) if f.startswith(prefix) and f.endswith(".csv")]
    
    seq = 1
    if existing_files:
        numbers = []
        for f in existing_files:
            part = f.replace(prefix, "").replace(".csv", "")
            if part.isdigit():
                numbers.append(int(part))
        if numbers:
            seq = max(numbers) + 1
            
    filename = f"{prefix}{seq:03d}.csv"
    return os.path.join(OUTPUT_CSV_DIR, filename)

def process_single_stock(code: str, name: str, period: str, exclude_set: set):
    pure_code = str(code).strip().zfill(6)
    
    # 排除项过滤
    if pure_code in exclude_set:
        STATS['excluded'] += 1
        return None

    try:
        # 获取K线（自适应处理次新股）
        df = get_kline_data(pure_code, period=period, lookback=180)
        # 次新股保护：若上市严重不足 60 根K线，难以形成收敛形态，予以跳过
        if df.empty or len(df) < 60:
            return None
        
        STATS['fetch_success'] += 1
        is_subnew = "次新" if len(df) < 110 else "常规"

        # 1. 拟合高精度下行压制线（防悬空线）
        fitter = TrendlineFitter(df)
        trend_info = fitter.fit_upper_resistance_line()
        if trend_info is None:
            return None
        
        STATS['trendline_fitted'] += 1

        # 2. 评估收敛指标
        metrics = evaluate_pattern(df, trend_info)
        if metrics is None or not metrics['is_matched']:
            return None

        STATS['matched'] += 1

        # 3. 绘图输出（按原有方式存储在 output_charts/day 或 week）
        display_name = f"{name}({is_subnew})" if is_subnew == "次新" else name
        plot_breakout_pattern(pure_code, display_name, df, trend_info, metrics, period=period)
        
        return {
            '代码': pure_code,
            '名称': name,
            '类型': is_subnew,
            '现价': metrics['curr_close'],
            '阻力线价': metrics['line_price'],
            '偏差(%)': metrics['distance_pct'],
            '均线带宽(%)': metrics['ma_spread'],
            '区间跌幅(%)': metrics['drop_pct']
        }
    except Exception:
        return None

def main():
    parser = argparse.ArgumentParser(description="股票下行趋势临界变盘筛选系统")
    parser.add_argument("--period", type=str, default="day", choices=["day", "week"], help="周期: day 或 week")
    parser.add_argument("--workers", type=int, default=12, help="并发线程数")
    parser.add_argument("--save-exclude", action="store_true", help="是否自动将本次命中的标的追加写入排除文档")
    args = parser.parse_args()

    stock_df = get_all_a_shares()
    if stock_df.empty:
        print("all_stocks.csv 不存在，请先执行: python build_stock_list.py")
        return

    # 加载排除黑名单
    exclude_set = load_exclude_stocks()
    if exclude_set:
        print(f"-> 检测到排除文档 {EXCLUDE_FILE}，已载入 {len(exclude_set)} 只排除标的。")
    else:
        print(f"-> 未设置排除项，执行全量正常扫描。")

    STATS['total'] = len(stock_df)
    print(f"\n=======================================================")
    print(f" 开始全市场并发扫描 | 周期: 【{args.period.upper()}】 | 标的总数: {STATS['total']}")
    print(f"=======================================================")

    results = []
    completed = 0

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        future_map = {
            executor.submit(process_single_stock, row['代码'], row['名称'], args.period, exclude_set): (row['代码'], row['名称'])
            for _, row in stock_df.iterrows()
        }

        for future in as_completed(future_map):
            completed += 1
            code, name = future_map[future]
            progress = (completed / STATS['total']) * 100
            sys.stdout.write(f"\r进度: [{completed}/{STATS['total']}] ({progress:.1f}%) | 正在分析: {code} | 命中数: {STATS['matched']}")
            sys.stdout.flush()

            res = future.result()
            if res:
                results.append(res)
                print(f"\n★ 精准命中: [{res['代码']}] {res['名称']} ({res['类型']}) | 现价:{res['现价']} 阻力线:{res['阻力线价']} 偏差:{res['偏差(%)']}% 均线带宽:{res['均线带宽(%)']}%")

    print("\n\n" + "="*55)
    print("【扫描漏斗与运行报表】")
    print(f" 1. 扫描总股票数:     {STATS['total']}")
    print(f" 2. 黑名单排除数:     {STATS['excluded']}")
    print(f" 3. 有效获取K线数:    {STATS['fetch_success']}")
    print(f" 4. 成功拟合趋势线数: {STATS['trendline_fitted']}")
    print(f" 5. 最终精准命中数:   {STATS['matched']}")
    print("="*55)

    if results:
        res_df = pd.DataFrame(results).sort_values(by='偏差(%)', ascending=False)
        print("\n" + res_df.to_string(index=False))

        # 1. 导出带日期和序列号的 CSV 到 output_csv 目录
        out_csv_path = generate_csv_filename(args.period)
        res_df.to_csv(out_csv_path, index=False, encoding='utf-8-sig')
        print(f"\n★ CSV 报表已成功保存至: {out_csv_path}")
        print(f"★ 高清 K 线图保持原样，分别存放在: ./output_charts/{args.period}/")

        # 2. 如果开启了 --save-exclude，则自动将本次结果追加写入排除文件
        if args.save_exclude:
            with open(EXCLUDE_FILE, 'a', encoding='utf-8') as f:
                for c in res_df['代码']:
                    f.write(f"{c}\n")
            print(f"★ 本次命中的 {len(res_df)} 只股票代码已自动追加到 {EXCLUDE_FILE}")
    else:
        print("\n未发现满足严格收敛标准的标的。")

if __name__ == "__main__":
    main()