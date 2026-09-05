# data_provider.py
import os
import requests
import pandas as pd

CACHE_DIR = "./stock_cache"
os.makedirs(CACHE_DIR, exist_ok=True)
STOCK_LIST_CACHE = "all_stocks.csv"

def _format_symbol_for_tencent(symbol: str) -> str:
    code = ''.join(filter(str.isdigit, str(symbol)))
    if code.startswith(('6', '9', '688')):
        return f"sh{code}"
    return f"sz{code}"

def get_kline_from_tencent(symbol: str, count: int = 250) -> pd.DataFrame:
    pure_code = ''.join(filter(str.isdigit, str(symbol)))
    tx_code = _format_symbol_for_tencent(pure_code)
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={tx_code},day,,,{count},qfq"
    
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        resp = requests.get(url, headers=headers, timeout=4)
        if resp.status_code != 200:
            return pd.DataFrame()

        data = resp.json()
        stock_data = data.get('data', {}).get(tx_code, {})
        k_list = stock_data.get('qfqday', []) or stock_data.get('day', [])
        if not k_list:
            return pd.DataFrame()

        records = [{
            'date': str(item[0]),
            'open': float(item[1]),
            'close': float(item[2]),
            'high': float(item[3]),
            'low': float(item[4]),
            'volume': float(item[5])
        } for item in k_list]

        return pd.DataFrame(records)
    except Exception:
        return pd.DataFrame()

def get_kline_data(symbol: str, lookback_days: int = 180, force_update: bool = False) -> pd.DataFrame:
    pure_symbol = ''.join(filter(str.isdigit, str(symbol)))
    file_path = os.path.join(CACHE_DIR, f"{pure_symbol}.parquet")

    # 1. 读本地缓存
    if not force_update and os.path.exists(file_path):
        try:
            df = pd.read_parquet(file_path)
            if not df.empty:
                return df.tail(lookback_days).copy().reset_index(drop=True)
        except Exception:
            pass

    # 2. 腾讯直连
    df = get_kline_from_tencent(pure_symbol, count=lookback_days + 40)
    if not df.empty:
        df.to_parquet(file_path, index=False)
        return df.tail(lookback_days).copy().reset_index(drop=True)

    return pd.DataFrame()

def get_all_a_shares() -> pd.DataFrame:
    """直接读取本地生成的 all_stocks.csv，100% 零网络阻塞"""
    if os.path.exists(STOCK_LIST_CACHE):
        return pd.read_csv(STOCK_LIST_CACHE, dtype={'代码': str})
    
    print("未发现 all_stocks.csv，请先运行: python build_stock_list.py 生成股票总表！")
    return pd.DataFrame()