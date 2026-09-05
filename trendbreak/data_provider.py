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

def get_kline_from_tencent(symbol: str, period: str = "day", count: int = 200) -> pd.DataFrame:
    """
    腾讯财经通道（注意：必须使用 http，https 会被网关拦截为 501）
    """
    pure_code = ''.join(filter(str.isdigit, str(symbol))).zfill(6)
    tx_code = _format_symbol_for_tx(pure_code)
    
    # 使用标准 HTTP 协议
    url = f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={tx_code},{period},,,{count},qfq"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    try:
        resp = requests.get(url, headers=headers, timeout=5)
        if resp.status_code != 200:
            return pd.DataFrame()

        data_block = resp.json().get('data', {})
        if tx_code not in data_block:
            return pd.DataFrame()

        stock_data = data_block[tx_code]
        k_list = None
        for key in [f"qfq{period}", period]:
            if key in stock_data and isinstance(stock_data[key], list) and len(stock_data[key]) > 0:
                k_list = stock_data[key]
                break

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

def get_kline_from_sina(symbol: str, period: str = "day", count: int = 200) -> pd.DataFrame:
    """
    新浪财经备用通道（日线/周线通用）
    """
    pure_code = ''.join(filter(str.isdigit, str(symbol))).zfill(6)
    prefix = "sh" if pure_code.startswith(('6', '9', '688')) else "sz"
    scale = "240" if period == "day" else "1200"
    
    url = f"https://quotes.sina.cn/cn/api/jsonp_v2.php/var=/CN_MarketDataService.getKLineData?symbol={prefix}{pure_code}&scale={scale}&ma=no&datalen={count}"
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

def get_kline_data(symbol: str, period: str = "day", lookback: int = 180, force_update: bool = False) -> pd.DataFrame:
    """
    获取K线（带自动双通道故障转移与缓存）
    """
    pure_symbol = ''.join(filter(str.isdigit, str(symbol))).zfill(6)
    period_cache_dir = os.path.join(CACHE_BASE_DIR, period)
    os.makedirs(period_cache_dir, exist_ok=True)
    file_path = os.path.join(period_cache_dir, f"{pure_symbol}.parquet")

    # 1. 本地缓存命中
    if not force_update and os.path.exists(file_path):
        try:
            df = pd.read_parquet(file_path)
            if not df.empty and len(df) >= 50:
                return df.tail(lookback).copy().reset_index(drop=True)
        except Exception:
            pass

    # 2. 腾讯通道 (HTTP)
    df = get_kline_from_tencent(pure_symbol, period=period, count=lookback + 40)
    
    # 3. 备用新浪通道
    if df.empty:
        df = get_kline_from_sina(pure_symbol, period=period, count=lookback + 40)

    # 写入缓存
    if not df.empty:
        df.to_parquet(file_path, index=False)
        return df.tail(lookback).copy().reset_index(drop=True)

    return pd.DataFrame()

def get_all_a_shares() -> pd.DataFrame:
    if os.path.exists(STOCK_LIST_CACHE):
        df = pd.read_csv(STOCK_LIST_CACHE, dtype={'代码': str})
        df['代码'] = df['代码'].astype(str).str.zfill(6)
        return df
    print("未发现 all_stocks.csv，请先运行: python build_stock_list.py")
    return pd.DataFrame()