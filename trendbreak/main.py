# main.py
import os
import sys
import argparse
import traceback
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
    'cond_near': 0,
    'cond_ma': 0,
    'matched': 0,
    'error_count': 0
}

FIRST_ERROR_SHOWN = False

def load_exclude_stocks() -> set:
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
    except Exception:
        pass
    return exclude_set

def generate_csv_filename(period: str) -> str:
    os.makedirs(OUTPUT_CSV_DIR, exist_ok=True)
    yymmdd = datetime.now().strftime("%y%m%d")
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
    global FIRST_ERROR_SHOWN
    pure_code = str(code).strip().zfill(6)
    if pure_code in exclude_set:
        STATS['excluded'] += 1
        return None

    try:
        # 1. 获取K线
        df = get_kline_data(pure_code, period=period, lookback=180)
        if df.empty or len(df) < 50:
            return None
        
        STATS['fetch_success'] += 1
        is_subnew = "次新" if len(df) < 110 else "常规"

        # 2. 拟合上轨压制线
        fitter = TrendlineFitter(df)
        trend_info = fitter.fit_upper_resistance_line()
        if trend_info is None:
            return None
        
        STATS['trendline_fitted'] += 1

        # 3. 判定双轨收敛与支撑位
        is_dual_track, support_info = fitter.check_dual_track_convergence(trend_info)

        # 4. 评估指标与计算综合评分
        metrics = evaluate_pattern(df, trend_info, is_dual_track=is_dual_track)
        if metrics is None or not metrics.get('is_matched', False):
            return None

        STATS['matched'] += 1

        # 5. 绘图（若这里传参错误会直接暴露）
        display_name = f"{name}({is_subnew})" if is_subnew == "次新" else name
        try:
            plot_breakout_pattern(pure_code, display_name, df, trend_info, metrics, support_info=support_info, period=period)
        except TypeError:
            # 兼容旧版本 visualizer.py（若未带 support_info 参数）
            plot_breakout_pattern(pure_code, display_name, df, trend_info, metrics, period=period)
        
        return {
            '代码': pure_code,
            '名称': name,
            '类型': is_subnew,
            '综合评分': metrics['score'],
            '双轨收敛': metrics['is_dual_track'],
            '首阳放量': metrics['is_volume_breakout'],
            '量比': metrics['vol_ratio'],
            '现价': metrics['curr_close'],
            '阻力价': metrics['line_price'],
            '偏差(%)': metrics['distance_pct'],
            '均线带宽(%)': metrics['ma_spread'],
            '区间跌幅(%)': metrics['drop_pct']
        }
    except Exception as e:
        STATS['error_count'] += 1
        if not FIRST_ERROR_SHOWN:
            print(f"\n❌ 捕获到首个未预期内部错误 [{pure_code}]:")
            traceback.print_exc()
            FIRST_ERROR_SHOWN = True
        return None

def main():
    parser = argparse.ArgumentParser(description="股票下行趋势临界变盘筛选系统")
    parser.add_argument("--period", type=str, default="day", choices=["day", "week"], help="周期: day 或 week")
    parser.add_argument("--workers", type=int, default=12, help="并发线程数")
    parser.add_argument("--save-exclude", action="store_true", help="自动将本次命中的标的追加写入排除文档")
    args = parser.parse_args()

    stock_df = get_all_a_shares()
    if stock_df.empty:
        print("all_stocks.csv 不存在，请先执行: python build_stock_list.py")
        return

    exclude_set = load_exclude_stocks()
    if exclude_set:
        print(f"-> 检测到排除文档 {EXCLUDE_FILE}，已载入 {len(exclude_set)} 只排除标的。")
    else:
        print(f"-> 未设置排除项，执行全量正常扫描。")

    STATS['total'] = len(stock_df)
    print(f"\n==========================================================================")
    print(f" 开始全市场并发扫描 | 周期: 【{args.period.upper()}】 | 标的总数: {STATS['total']}")
    print(f"==========================================================================")

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
            
            # 强化进度条展示：显示K线获取成功数、趋势线拟合数、命中数
            sys.stdout.write(f"\r进度: [{completed}/{STATS['total']}] ({progress:.1f}%) | K线有效:{STATS['fetch_success']} 压制线:{STATS['trendline_fitted']} | 命中:{STATS['matched']}")
            sys.stdout.flush()

            res = future.result()
            if res:
                results.append(res)
                tags = []
                if res['双轨收敛'] == "是": tags.append("双轨")
                if res['首阳放量'] == "是": tags.append("放量")
                tag_str = f"[{'+'.join(tags)}]" if tags else ""
                print(f"\n★ 命中: [{res['代码']}] {res['名称']} {tag_str} | 评分:{res['综合评分']} 阻力线:{res['阻力价']} 偏差:{res['偏差(%)']}%")

    print("\n\n" + "="*60)
    print("【扫描完成数据漏斗】")
    print(f" 1. 扫描总股票数:     {STATS['total']}")
    print(f" 2. 排除黑名单数:     {STATS['excluded']}")
    print(f" 3. 成功获取K线数:    {STATS['fetch_success']} {'⚠️ 严重：K线未拉取到！' if STATS['fetch_success'] < 100 else '✅ 正常'}")
    print(f" 4. 拟合出压制线数:   {STATS['trendline_fitted']}")
    print(f" 5. 最终精准命中数:   {STATS['matched']}")
    if STATS['error_count'] > 0:
        print(f" ⚠️ 运行中出现异常报错次数: {STATS['error_count']}")
    print("="*60)

    if results:
        res_df = pd.DataFrame(results).sort_values(by=['综合评分', '偏差(%)'], ascending=[False, False])
        print("\n" + res_df.to_string(index=False))

        out_csv_path = generate_csv_filename(args.period)
        res_df.to_csv(out_csv_path, index=False, encoding='utf-8-sig')
        print(f"\n★ CSV 排序报表已成功导出至: {out_csv_path}")
        print(f"★ 高清 K 线图存放在: ./output_charts/{args.period}/")

        if args.save_exclude:
            with open(EXCLUDE_FILE, 'a', encoding='utf-8') as f:
                for c in res_df['代码']:
                    f.write(f"{c}\n")
            print(f"★ 本次命中的股票已追加至 {EXCLUDE_FILE}")
    else:
        print("\n未发现满足严格收敛标准的标的。请查看上方漏斗数据确定瓶颈。")

if __name__ == "__main__":
    main()