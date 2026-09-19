# screener.py
import argparse
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging
import pandas as pd
from tqdm import tqdm

from config import get_config, OUTPUT_DIR, StrategyConfig
from fetch import DataFetcher
from compute import compute_indicators, detect_bottom_structure

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("Screener")

funnel_stats = {
    "total": 0,
    "pass_prefilter": 0,
    "pass_listing_days": 0,
    "pass_drawdown": 0,
    "pass_box_amplitude": 0,
    "pass_ma_convergence": 0,
    "pass_trial_pulses": 0,
    "pass_bottom_structure": 0,
    "is_today_ambush": 0
}

def process_single_stock(symbol: str, meta: dict, fetcher: DataFetcher, cfg: StrategyConfig) -> dict | None:
    # ---------------- 1. 内存级快速初筛 (不发网络请求，秒级过滤) ----------------
    # 过滤成交额过低的死水股
    if meta["amount"] < cfg.MIN_AMOUNT:
        return None
    
    # 全市场老股模式下，排除当日换手率处于极端暴炒顶峰的标的
    if cfg.mode == "all" and meta["turnover_today"] > 25.0:
        return None

    funnel_stats["pass_prefilter"] += 1

    # ---------------- 2. 发起 K 线网络请求 ----------------
    df = fetcher.fetch_single_kline(symbol, meta["float_shares"])
    if df is None or len(df) < cfg.MIN_LISTING_DAYS:
        return None

    listing_days = len(df)

    # ---------------- 3. 上市周期过滤 (关键修复：模式解耦) ----------------
    if cfg.mode == "subnew":
        # 次新模式：严格要求上市天数在指定区间内
        if not (cfg.MIN_LISTING_DAYS <= listing_days <= cfg.MAX_LISTING_DAYS):
            return None
    else:
        # 全市场老股模式：只要 K 线数量达到计算要求即可，不设上限
        if listing_days < cfg.MIN_LISTING_DAYS:
            return None

    funnel_stats["pass_listing_days"] += 1
    latest_close = df.iloc[-1]["close"]

    # ---------------- 4. 流通市值精准约束 (排除万科/电力等权重大象) ----------------
    float_cap = meta["float_shares"] * latest_close
    cap_min = getattr(cfg, "FLOAT_CAP_MIN", 10.0e8)  # 默认 10 亿元
    cap_max = getattr(cfg, "FLOAT_CAP_MAX", 120.0e8) # 默认 120 亿元
    if not (cap_min <= float_cap <= cap_max):
        return None  # 排除万科A、上海电力、科大讯飞等数百亿权重股

    # ---------------- 5. 深度超跌计算 ----------------
    # 次新模式以全周期高点为基准，老股模式以近 250 个交易日高点为基准
    lookback = min(len(df), cfg.DRAWDOWN_WINDOW)
    high_water_mark = df.iloc[-lookback:]["high"].max()
    drawdown = (latest_close - high_water_mark) / high_water_mark
    if drawdown > cfg.MAX_DRAWDOWN_THRESHOLD:
        return None
    funnel_stats["pass_drawdown"] += 1

    # ---------------- 6. 平台箱体振幅过滤 ----------------
    recent_df = df.iloc[-cfg.BASE_WINDOW:]
    box_high = recent_df["high"].max()
    box_low = recent_df["low"].min()
    box_amp = (box_high - box_low) / box_low
    if box_amp > cfg.BASE_MAX_AMPLITUDE:
        return None
    funnel_stats["pass_box_amplitude"] += 1

    # 计算技术指标
    df = compute_indicators(df, cfg)
    last_row = df.iloc[-1]

    # ---------------- 7. 近 60 日平均换手率底线 (排除死水冷门股) ----------------
    avg_turnover_min = getattr(cfg, "AVG_TURNOVER_MIN", 0.8)
    avg_turnover_60 = df.iloc[-cfg.BASE_WINDOW:]["turnover_pct"].mean()
    if avg_turnover_60 < avg_turnover_min:
        return None  # 排除日均换手不足的沉寂股

    # ---------------- 修正 1: 均线真正走平判断 ----------------
    if len(df) >= 30:
        ma30_current = last_row["ma30"]
        ma30_prev20 = df.iloc[-20]["ma30"]
        ma_slope_max = getattr(cfg, "MA_SLOPE_MAX", 0.06)
        if ma30_prev20 > 0:
            ma30_slope = abs(ma30_current - ma30_prev20) / ma30_prev20
            # 允许筑底拐弯，仅排除单边陡峭下泄的极端阴跌（斜率 > 6% 且持续跌破 92%）
            if ma30_slope > ma_slope_max and ma30_current < ma30_prev20 * 0.92:
                return None

    # ---------------- 9. 均线极度粘合收敛 ----------------
    if last_row["ma_spread"] > cfg.MA_CONVERGENCE_THRESHOLD:
        return None
    funnel_stats["pass_ma_convergence"] += 1

    # ---------------- 修正 2: 试盘脉冲锐度检验 ----------------
    # 兼容主板（10%限制）与双创/北交所（20-30%限制）：振幅 >= 4.0% 且 冲高 >= 3.5%
    trials = df.iloc[-cfg.BASE_WINDOW:].apply(
        lambda r: (
            (r["turnover_pct"] >= cfg.TRIAL_TURNOVER_MIN or r["volume"] >= 2.0 * r["vma20"]) and
            ((r["high"] - r["open"]) / r["open"] >= cfg.TRIAL_INTRA_GAIN_MIN) and
            ((r["high"] - r["low"]) / r["close"] >= 0.040)  # 放宽至 4.0%，容纳主板放量针
        ), axis=1
    )
    trial_count = int(trials.sum())
    if not (cfg.TRIAL_MIN_COUNT <= trial_count <= cfg.TRIAL_MAX_COUNT):
        return None
    funnel_stats["pass_trial_pulses"] += 1

    # ---------------- 11. 双底/三底结构识别 ----------------
    bottom_info = detect_bottom_structure(df, cfg)
    if not bottom_info["valid"]:
        return None
    funnel_stats["pass_bottom_structure"] += 1

    # ---------------- 12. 今日地量小 K 线判定 (潜伏点) ----------------
    is_today_ambush = (
        (last_row["volume"] <= cfg.VOLUME_SHRINK_RATIO * last_row["vma20"]) and
        (last_row["turnover_pct"] <= cfg.TURNOVER_SHRINK_MAX) and
        (last_row["candle_body"] <= cfg.CANDLE_BODY_MAX) and
        (last_row["candle_amp"] <= cfg.CANDLE_AMPLITUDE_MAX)
    )

    if is_today_ambush:
        funnel_stats["is_today_ambush"] += 1

    # 返回精选结果数据字典
    return {
        "symbol": symbol,
        "code": meta["code"],
        "name": meta["name"],
        "close": latest_close,
        "float_cap_yi": round(float_cap / 1.0e8, 2),  # 流通市值(亿元)
        "avg_turnover_60": round(avg_turnover_60, 2),  # 60日平均换手率(%)
        "listing_days": listing_days,
        "drawdown_pct": round(drawdown * 100, 1),
        "box_amp_pct": round(box_amp * 100, 1),
        "ma_spread_pct": round(last_row["ma_spread"] * 100, 2),
        "trial_count": trial_count,
        "l1_price": bottom_info["l1_price"],
        "l2_price": bottom_info["l2_price"],
        "hard_stop_price": bottom_info["hard_stop_price"],
        "is_divergence": "✔ 是" if bottom_info["is_divergence"] else "✘ 否",
        "action_signal": "★ 尾盘潜伏试仓" if is_today_ambush else "👀 筑底观察中"
    }

def run_screener():
    parser = argparse.ArgumentParser(description="威科夫筑底形态筛选引擎")
    parser.add_argument("--mode", type=str, choices=["subnew", "all"], default="subnew",
                        help="筛选模式: subnew (次新股专项), all (全市场股票)")
    args = parser.parse_args()

    cfg = get_config(args.mode)
    fetcher = DataFetcher(cfg)

    mode_name = "【次新股模式】" if args.mode == "subnew" else "【全市场股票模式】"
    logger.info(f"启动 {mode_name} 筛选任务...")

    all_symbols = fetcher.get_market_symbols()
    valid_pool = fetcher.prefilter_pool(all_symbols)
    funnel_stats["total"] = len(valid_pool)

    logger.info(f"进入深度形态扫描 (并发线程: {cfg.MAX_WORKERS})...")
    candidates = []

    with ThreadPoolExecutor(max_workers=cfg.MAX_WORKERS) as executor:
        future_map = {
            executor.submit(process_single_stock, sym, meta, fetcher, cfg): sym
            for sym, meta in valid_pool.items()
        }
        for future in tqdm(as_completed(future_map), total=len(future_map), desc=f"形态扫描({args.mode})"):
            res = future.result()
            if res:
                candidates.append(res)

    print("\n" + "=" * 65)
    print(f"📈 {mode_name} 策略漏斗层级报告")
    print("=" * 65)
    print(f"1. 市场基础活跃标的总数   : {funnel_stats['total']} 只")
    print(f"2. 基础流动性初筛通过     : {funnel_stats['pass_prefilter']} 只")
    print(f"3. 符合上市周期要求       : {funnel_stats['pass_listing_days']} 只")
    print(f"4. 满足周期超跌要求       : {funnel_stats['pass_drawdown']} 只")
    print(f"5. 处于箱体横盘区间       : {funnel_stats['pass_box_amplitude']} 只")
    print(f"6. 均线极度粘合收敛       : {funnel_stats['pass_ma_convergence']} 只")
    print(f"7. 存在试盘异动痕迹       : {funnel_stats['pass_trial_pulses']} 只")
    print(f"8. 成功构筑双底结构       : {funnel_stats['pass_bottom_structure']} 只 (进入观察池)")
    print(f"9. 今日正好满足地量试仓点 : {funnel_stats['is_today_ambush']} 只 (触发潜伏)")
    print("=" * 65 + "\n")

    df_res = pd.DataFrame(candidates)
    today_str = datetime.now().strftime("%Y%m%d")
    out_file = OUTPUT_DIR / f"watchlist_{args.mode}_{today_str}.csv"

    if not df_res.empty:
        df_res = df_res.sort_values(by=["action_signal", "ma_spread_pct"], ascending=[False, True])
        df_res.to_csv(out_file, index=False, encoding="utf-8-sig")
        logger.info(f"🎉 筛选完成！发现 {len(df_res)} 只标的，已保存至: {out_file}")
        
        display_cols = ["code", "name", "close", "float_cap_yi", "avg_turnover_60", "hard_stop_price", "ma_spread_pct", "is_divergence", "action_signal"]
        print(df_res[display_cols].to_string(index=False))
    else:
        logger.info(f"{mode_name} 今日未发现完全符合形态的标的。")

if __name__ == "__main__":
    run_screener()