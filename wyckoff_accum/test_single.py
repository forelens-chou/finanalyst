# test_single.py
import sys
import pandas as pd
from fetch import DataFetcher
from compute import compute_indicators, detect_bottom_structure
from config import cfg

def test_code(code_str: str):
    symbol = DataFetcher.to_full_symbol(code_str)
    fetcher = DataFetcher()
    
    print(f"正在拉取 {symbol} 基础信息...")
    snap = fetcher.prefilter_pool([(symbol, code_str, "")])
    if symbol not in snap:
        print(f"❌ 未能从快照接口获取到 {symbol}")
        return

    meta = snap[symbol]
    print(f"股票名称: {meta['name']} | 当前价: {meta['latest_price']} | 流通股本: {int(meta['float_shares']):,} 股")

    df = fetcher.fetch_single_kline(symbol, meta["float_shares"])
    if df is None or df.empty:
        print("❌ K线数据获取失败，请检查网络或源地址")
        return

    df = compute_indicators(df)
    last = df.iloc[-1]
    ath = df["high"].max()
    drawdown = (last["close"] - ath) / ath

    print("\n" + "=" * 50)
    print(f"📊【{meta['name']} ({symbol})】形态指标诊断")
    print("=" * 50)
    print(f"上市总K线数     : {len(df)} 天 (筛选阈值: {cfg.MIN_LISTING_DAYS} ~ {cfg.MAX_LISTING_DAYS})")
    print(f"最高价回撤幅度   : {round(drawdown*100, 2)}% (筛选阈值: <= {cfg.MAX_DRAWDOWN_THRESHOLD*100}%)")
    print(f"当前均线粘合离散 : {round(last['ma_spread']*100, 3)}% (筛选阈值: <= {cfg.MA_CONVERGENCE_THRESHOLD*100}%)")
    print(f"近60日试盘次数   : {df.iloc[-60:]['is_trial'].sum()} 次 (筛选阈值: >= {cfg.TRIAL_MIN_COUNT})")
    print(f"最新一日振幅     : {round(last['candle_amp']*100, 2)}% (地量阈值: <= {cfg.CANDLE_AMPLITUDE_MAX*100}%)")
    print(f"最新一日换手率   : {round(last['turnover_pct'], 2)}% (地量阈值: <= {cfg.TURNOVER_SHRINK_MAX}%)")

    b_info = detect_bottom_structure(df)
    print("\n双底结构判定详情:")
    for k, v in b_info.items():
        print(f"  {k}: {v}")

    print("\n最近 5 个交易日走势预览:")
    cols = ["date", "close", "high", "low", "turnover_pct", "ma_spread", "is_trial"]
    display_df = df[cols].tail(5).copy()
    display_df["date"] = display_df["date"].dt.strftime("%Y-%m-%d")
    print(display_df.to_string(index=False))
    print("=" * 50 + "\n")

if __name__ == "__main__":
    code = sys.argv[1] if len(sys.argv) > 1 else "301551"
    test_code(code)