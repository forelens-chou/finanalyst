# data_provider.py
import os
import json
import requests
import pandas as pd

CACHE_BASE_DIR = "./stock_cache"
STOCK_LIST_CACHE = "all_stocks.csv"

def _format_symbol_for_tx(symbol: str) -> str:
    code = ''.join(filter(str.isdigit, str(symbol))).zfill(6)
    if code.startswith(('43', '83', '87', '88', '92')):
        return f"bj{code}"
    elif code.startswith(('6', '9', '688')):
        return f"sh{code}"
    return f"sz{code}"

def _format_symbol_for_sina(symbol: str) -> str:
    code = ''.join(filter(str.isdigit, str(symbol))).zfill(6)
    if code.startswith(('43', '83', '87', '88', '92')):
        return f"bj{code}"
    elif code.startswith(('6', '9', '688')):
        return f"sh{code}"
    return f"sz{code}"

def get_kline_from_tencent(symbol: str, period: str = "day", count: int = 320) -> pd.DataFrame:
    pure_code = ''.join(filter(str.isdigit, str(symbol))).zfill(6)
    tx_code = _format_symbol_for_tx(pure_code)
    url = f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={tx_code},{period},,,{count},qfq"
    headers = {"User-Agent": "Mozilla/5.0"}

    try:
        resp = requests.get(url, headers=headers, timeout=5)
        if resp.status_code != 200:
            return pd.DataFrame()

        data_block = resp.json().get('data', {})
        if tx_code not in data_block:
            return pd.DataFrame()

        stock_data = data_block[tx_code]
        k_list = stock_data.get(f"qfq{period}", []) or stock_data.get(period, [])
        if not k_list:
            return pd.DataFrame()

        records = []
        for item in k_list:
            if len(item) >= 6:
                records.append({
                    'date': str(item[0]),
                    'open': float(item[1]),
                    'close': float(item[2]),
                    'high': float(item[3]),
                    'low': float(item[4]),
                    'volume': float(item[5])
                })

        return pd.DataFrame(records)
    except Exception:
        return pd.DataFrame()

def get_kline_from_sina(symbol: str, period: str = "day", count: int = 320) -> pd.DataFrame:
    pure_code = ''.join(filter(str.isdigit, str(symbol))).zfill(6)
    sina_code = _format_symbol_for_sina(pure_code)
    scale = "240" if period == "day" else "1200"
    url = f"https://quotes.sina.cn/cn/api/jsonp_v2.php/var=/CN_MarketDataService.getKLineData?symbol={sina_code}&scale={scale}&ma=no&datalen={count}"
    headers = {"User-Agent": "Mozilla/5.0"}
    
    try:
        resp = requests.get(url, headers=headers, timeout=5)
        if resp.status_code == 200 and "(" in resp.text:
            json_str = resp.text.split("(", 1)[1].rsplit(")", 1)[0]
            items = json.loads(json_str)
            if items:
                records = []
                for item in items:
                    records.append({
                        'date': str(item['day']),
                        'open': float(item['open']),
                        'close': float(item['close']),
                        'high': float(item['high']),
                        'low': float(item['low']),
                        'volume': float(item['volume'])
                    })
                return pd.DataFrame(records)
    except Exception:
        pass
    return pd.DataFrame()

def get_kline_data(symbol: str, period: str = "day", lookback: int = 200, force_update: bool = False) -> tuple[pd.DataFrame, bool]:
    """
    返回: (截断后的df, is_real_subnew: bool)
    """
    pure_symbol = ''.join(filter(str.isdigit, str(symbol))).zfill(6)
    period_cache_dir = os.path.join(CACHE_BASE_DIR, period)
    os.makedirs(period_cache_dir, exist_ok=True)
    file_path = os.path.join(period_cache_dir, f"{pure_symbol}.parquet")

    full_df = pd.DataFrame()

    if not force_update and os.path.exists(file_path):
        try:
            full_df = pd.read_parquet(file_path)
        except Exception:
            pass

    if full_df.empty or len(full_df) < 40:
        full_df = get_kline_from_tencent(pure_symbol, period=period, count=320)
        if full_df.empty:
            full_df = get_kline_from_sina(pure_symbol, period=period, count=320)
        if not full_df.empty:
            full_df.to_parquet(file_path, index=False)

    if full_df.empty:
        return pd.DataFrame(), False

    # 核心判断：在日线模式下，若服务器拉取到的全部历史数据原本就少于 220 根，证明上市绝对不足 1 年！
    # 在周线模式下，少于 48 周证明上市不足 1 年！
    threshold = 48 if period == "week" else 220
    is_real_subnew = len(full_df) < threshold

    # 截取分析窗口
    return full_df.tail(lookback).copy().reset_index(drop=True), is_real_subnew

def get_all_a_shares() -> pd.DataFrame:
    if os.path.exists(STOCK_LIST_CACHE):
        df = pd.read_csv(STOCK_LIST_CACHE, dtype={'代码': str})
        df['代码'] = df['代码'].astype(str).str.zfill(6)
        return df
    return pd.DataFrame()