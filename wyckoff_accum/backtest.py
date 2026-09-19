# backtest.py
from dataclasses import dataclass
import logging
import pandas as pd
from tqdm import tqdm

from config import cfg
from fetch import DataFetcher
from compute import compute_indicators, detect_bottom_structure

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("Backtest")

@dataclass
class TradeResult:
    code: str
    entry_date: str
    entry_price: float
    exit_date: str
    exit_price: float
    pnl_pct: float
    hold_days: int
    exit_reason: str # 'STOP_LOSS', 'TAKE_PROFIT', 'TIMEOUT'
    mae_pct: float   # Maximum Adverse Excursion (持有期间最大下探幅度)

def run_backtest_on_stock(symbol: str, meta: dict, fetcher: DataFetcher) -> list[TradeResult]:
    df = fetcher.fetch_single_kline(symbol, meta["float_shares"])
    if df is None or len(df) < cfg.MIN_LISTING_DAYS + 30:
        return []

    df = compute_indicators(df)
    results = []
    n_bars = len(df)

    # 滚动窗口模拟历史每日收盘判定
    for i in range(cfg.MIN_LISTING_DAYS, n_bars - 20):
        sub_df = df.iloc[: i + 1]
        last_row = sub_df.iloc[-1]

        # 必须满足次新与超跌
        all_time_high = sub_df["high"].max()
        if (last_row["close"] - all_time_high) / all_time_high > cfg.MAX_DRAWDOWN_THRESHOLD:
            continue

        # 满足均线粘合
        if last_row["ma_spread"] > cfg.MA_CONVERGENCE_THRESHOLD:
            continue

        # 满足双底结构
        bottom_info = detect_bottom_structure(sub_df)
        if not bottom_info["valid"]:
            continue

        # 满足地量与小K线
        is_ambush_day = (
            (last_row["volume"] <= cfg.VOLUME_SHRINK_RATIO * last_row["vma20"]) and
            (last_row["turnover_pct"] <= cfg.TURNOVER_SHRINK_MAX) and
            (last_row["candle_body"] <= cfg.CANDLE_BODY_MAX) and
            (last_row["candle_amp"] <= cfg.CANDLE_AMPLITUDE_MAX)
        )
        if not is_ambush_day:
            continue

        # --- 触发潜伏开仓 (在当日收盘价买入) ---
        entry_price = last_row["close"]
        entry_date = last_row["date"].strftime("%Y-%m-%d")
        hard_stop = bottom_info["hard_stop_price"]

        max_loss = 0.0
        exit_found = False

        # 跟踪后续 15 个交易日的走势
        for forward_day in range(1, 16):
            future_bar = df.iloc[i + forward_day]
            f_low = future_bar["low"]
            f_high = future_bar["high"]
            f_close = future_bar["close"]

            drawdown_since_entry = (f_low - entry_price) / entry_price
            if drawdown_since_entry < max_loss:
                max_loss = drawdown_since_entry

            # 1. 硬止损触发
            if f_low <= hard_stop:
                results.append(TradeResult(
                    code=meta["code"], entry_date=entry_date, entry_price=entry_price,
                    exit_date=future_bar["date"].strftime("%Y-%m-%d"), exit_price=hard_stop,
                    pnl_pct=(hard_stop - entry_price) / entry_price, hold_days=forward_day,
                    exit_reason="STOP_LOSS", mae_pct=max_loss
                ))
                exit_found = True
                break

            # 2. 止盈触发 (单日大涨 >= 8% 或放量首板，次日冲高离场保护利润)
            if (f_high - entry_price) / entry_price >= 0.12 or (future_bar["close"] / future_bar["open"] >= 1.08):
                exit_price = f_close
                results.append(TradeResult(
                    code=meta["code"], entry_date=entry_date, entry_price=entry_price,
                    exit_date=future_bar["date"].strftime("%Y-%m-%d"), exit_price=exit_price,
                    pnl_pct=(exit_price - entry_price) / entry_price, hold_days=forward_day,
                    exit_reason="TAKE_PROFIT", mae_pct=max_loss
                ))
                exit_found = True
                break

        # 3. 超过15天未启动，时间止损
        if not exit_found:
            timeout_bar = df.iloc[i + 15]
            results.append(TradeResult(
                code=meta["code"], entry_date=entry_date, entry_price=entry_price,
                exit_date=timeout_bar["date"].strftime("%Y-%m-%d"), exit_price=timeout_bar["close"],
                pnl_pct=(timeout_bar["close"] - entry_price) / entry_price, hold_days=15,
                exit_reason="TIMEOUT", mae_pct=max_loss
            ))

    return results

def run_backtest_pipeline():
    fetcher = DataFetcher()
    symbols = fetcher.get_market_symbols()
    valid_pool = fetcher.prefilter_pool(symbols)

    all_trades: list[TradeResult] = []
    logger.info("开始回测历史所有地量潜伏信号...")

    for sym, meta in tqdm(list(valid_pool.items())[:300], desc="回测样本采样"):
        trades = run_backtest_on_stock(sym, meta, fetcher)
        all_trades.extend(trades)

    if not all_trades:
        logger.warning("未检测到有效交易样本。")
        return

    df_trades = pd.DataFrame([t.__dict__ for t in all_trades])
    wins = df_trades[df_trades["pnl_pct"] > 0]
    losses = df_trades[df_trades["pnl_pct"] <= 0]

    win_rate = len(wins) / len(df_trades) * 100
    avg_win = wins["pnl_pct"].mean() * 100 if len(wins) > 0 else 0
    avg_loss = abs(losses["pnl_pct"].mean() * 100) if len(losses) > 0 else 0
    pnl_ratio = avg_win / avg_loss if avg_loss > 0 else 999.0

    print("\n" + "=" * 60)
    print("📊【地量小K线潜伏试仓策略 - 统计回测报告】")
    print("=" * 60)
    print(f"总交易样本数        : {len(df_trades)}")
    print(f"策略胜率            : {win_rate:.2f}%")
    print(f"平均盈利单收益      : +{avg_win:.2f}%")
    print(f"平均亏损单亏损      : -{avg_loss:.2f}%")
    print(f"盈亏比 (Profit Ratio): {pnl_ratio:.2f}:1")
    print(f"平均持仓天数        : {df_trades['hold_days'].mean():.1f} 天")
    print(f"平均最大不利下探(MAE): {df_trades['mae_pct'].mean() * 100:.2f}%")
    print("=" * 60 + "\n")

if __name__ == "__main__":
    run_backtest_pipeline()