# main.py
import os
import sys
import argparse
from datetime import datetime
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed

from data_provider import get_kline_data, get_all_a_shares
from geometry_engine import TrendlineFitter
from time_cycle_engine import TimeCycleEngine
from wave_pattern_engine import WavePatternEngine
from screener import evaluate_pattern
from visualizer import plot_breakout_pattern

OUTPUT_CSV_DIR = "./output_csv"
EXCLUDE_FILE = "exclude_stocks.txt"

STATS = {
    'total': 0,
    'excluded': 0,
    'fetch_success': 0,
    'trendline_fitted': 0,
    'matched': 0,
    'bse_matched': 0,
    'subnew_matched': 0
}

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
    pure_code = str(code).strip().zfill(6)
    if pure_code in exclude_set:
        STATS['excluded'] += 1
        return None

    try:
        lookback = 120 if period == "week" else 200
        # 核心改动：由 data_provider 依据数据源真实全部历史长度判定是否为真实次新股
        df, is_real_subnew = get_kline_data(pure_code, period=period, lookback=lookback)
        if df.empty or len(df) < 40:
            return None
        
        STATS['fetch_success'] += 1
        type_str = "次新" if is_real_subnew else "常规"

        # 1. 拟合宏观主压制线 (内置分市场阶梯容差)
        fitter = TrendlineFitter(df, code=pure_code)
        macro_trend = fitter.fit_upper_resistance_line()
        if macro_trend is None:
            return None
        
        STATS['trendline_fitted'] += 1

        # 2. 拟合次级粉色主跌线
        sub_trend = fitter.fit_secondary_resistance_line(macro_trend)
        p_sub_idx = sub_trend['p_sub_idx'] if sub_trend else None

        # 3. 时间周期共振
        time_info = TimeCycleEngine.detect_time_resonance(len(df), macro_trend['p0_idx'], p_sub_idx)

        # 4. 波浪空间穷竭度 (传入真实次新判定)
        wave_info = WavePatternEngine.evaluate_wave_exhaustion(df, macro_trend['p0_idx'], is_subnew=is_real_subnew)

        # 5. 双轨收敛
        is_dual_track, support_info = fitter.check_dual_track_convergence(macro_trend)

        # 6. 计算理论距离与形态阶段
        curr_idx = len(df) - 1
        line_price_now = macro_trend['k'] * curr_idx + macro_trend['b']
        distance_pct = (df['close'].iloc[curr_idx] - line_price_now) / line_price_now * 100
        phase_str = WavePatternEngine.detect_pattern_phase(df, line_price_now, distance_pct)

        # 7. 全维度评分评估
        metrics = evaluate_pattern(
            df, 
            macro_trend=macro_trend, 
            sub_trend=sub_trend, 
            time_info=time_info, 
            wave_info=wave_info, 
            is_dual_track=is_dual_track,
            phase_str=phase_str,
            is_subnew=is_real_subnew
        )
        if metrics is None or not metrics.get('is_matched', False):
            return None

        STATS['matched'] += 1
        if pure_code.startswith(('43', '83', '87', '88', '92')):
            STATS['bse_matched'] += 1
        if is_real_subnew:
            STATS['subnew_matched'] += 1

        result_record = {
            '代码': pure_code,
            '名称': name,
            '类型': type_str,
            '形态阶段': metrics['phase'],
            '综合评分': metrics['score'],
            '时间共振': metrics['is_time_resonance'],
            '周期详情': metrics['time_desc'],
            '双线共振': metrics['is_dual_line'],
            '波浪穷竭': metrics['is_wave_exhausted'],
            '最大跌幅(%)': metrics['max_drawdown_pct'],
            '双轨收敛': metrics['is_dual_track'],
            '首阳放量': metrics['is_volume_breakout'],
            '量比': metrics['vol_ratio'],
            '现价': metrics['curr_close'],
            '宏观阻力价': metrics['line_price'],
            '次级阻力价': metrics['sub_line_price'],
            '偏差(%)': metrics['distance_pct'],
            '均线带宽(%)': metrics['ma_spread']
        }

        # 独立沙箱绘图
        try:
            display_name = f"{name}({type_str})" if is_real_subnew else name
            plot_breakout_pattern(
                pure_code, 
                display_name, 
                df, 
                macro_trend, 
                sub_trend, 
                metrics, 
                support_info=support_info, 
                period=period
            )
        except Exception:
            pass

        return result_record
    except Exception:
        return None

def main():
    parser = argparse.ArgumentParser(description="TrendBreak V3.0 多维时空量价共振识别系统")
    parser.add_argument("--period", type=str, default="day", choices=["day", "week"], help="分析周期: day 或 week")
    parser.add_argument("--workers", type=int, default=12, help="并发线程数")
    parser.add_argument("--save-exclude", action="store_true", help="自动将本次命中的标的追加写入排除文档")
    args = parser.parse_args()

    stock_df = get_all_a_shares()
    if stock_df.empty:
        print("all_stocks.csv 不存在，请先执行: python build_stock_list.py")
        return

    exclude_set = load_exclude_stocks()
    if exclude_set:
        print(f"-> 载入排除黑名单: {len(exclude_set)} 只标的。")
    else:
        print(f"-> 未设置排除项，执行全量扫描。")

    STATS['total'] = len(stock_df)
    print(f"\n==========================================================================")
    print(f" 开始全市场智能扫描 | 周期: 【{args.period.upper()}】 | 标的总数: {STATS['total']}")
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
            sys.stdout.write(f"\r进度: [{completed}/{STATS['total']}] ({progress:.1f}%) | 有效K线:{STATS['fetch_success']} 压制线:{STATS['trendline_fitted']} | 命中:{len(results)}")
            sys.stdout.flush()

            res = future.result()
            if res:
                results.append(res)
                tags = []
                if res['时间共振'] == "是": tags.append(f"时:{res['周期详情']}")
                if res['双线共振'] == "是": tags.append("双线")
                if res['波浪穷竭'] == "是": tags.append("跌透")
                if res['首阳放量'] == "是": tags.append("放量")
                tag_str = f"[{' | '.join(tags)}]" if tags else ""
                print(f"\n★ 命中: [{res['代码']}] {res['名称']} ({res['类型']}/{res['形态阶段']}) {tag_str} | 评分:{res['综合评分']} 现价:{res['现价']}")

    print("\n\n" + "="*60)
    print(f"【V3.0 {args.period.upper()} 周期扫描完成数据报表】")
    print(f" 扫描总股票数:     {STATS['total']}")
    print(f" 排除黑名单数:     {STATS['excluded']}")
    print(f" 成功拟合压制线数: {STATS['trendline_fitted']}")
    print(f" 最终精准命中数:   {len(results)} (其中真实次新: {STATS['subnew_matched']} 只，北交所: {STATS['bse_matched']} 只)")
    print("="*60)

    if results:
        res_df = pd.DataFrame(results).sort_values(by=['综合评分', '偏差(%)'], ascending=[False, False])
        print("\n" + res_df[['代码', '名称', '类型', '形态阶段', '综合评分', '时间共振', '双线共振', '波浪穷竭', '首阳放量', '现价', '偏差(%)']].head(30).to_string(index=False))

        out_csv_path = generate_csv_filename(args.period)
        res_df.to_csv(out_csv_path, index=False, encoding='utf-8-sig')
        print(f"\n★ 全维度排序报表已导出至: {out_csv_path}")
        print(f"★ 复合 K 线图保存在: ./output_charts/{args.period}/")

        if args.save_exclude:
            with open(EXCLUDE_FILE, 'a', encoding='utf-8') as f:
                for c in res_df['代码']:
                    f.write(f"{c}\n")
            print(f"★ 命中结果已追加至 {EXCLUDE_FILE}")
    else:
        print("\n未发现满足多维收敛标准的标的。")

if __name__ == "__main__":
    main()