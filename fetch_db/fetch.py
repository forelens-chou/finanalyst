# fetch.py
import json
import logging
import re
from typing import Dict, List, Optional, Tuple

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import cfg

logging.getLogger("urllib3").setLevel(logging.ERROR)
logger = logging.getLogger("DataFetcher")

def create_fast_session(pool_size: int = 32) -> requests.Session:
    session = requests.Session()
    adapter = HTTPAdapter(
        pool_connections=pool_size,
        pool_maxsize=pool_size,
        max_retries=Retry(total=1, backoff_factor=0.1)
    )
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Referer": "https://gu.qq.com/",
        "Connection": "keep-alive"
    })
    return session

class DataFetcher:
    def __init__(self):
        self.session = create_fast_session(pool_size=cfg.MAX_WORKERS * 2)

    @staticmethod
    def to_full_symbol(code: str) -> str:
        code = str(code).strip().lower()
        pure = re.sub(r'^[a-z]+', '', code).zfill(6)
        if pure.startswith(("60", "68")):
            return f"sh{pure}"
        elif pure.startswith(("00", "30")):
            return f"sz{pure}"
        elif pure.startswith(("8", "4", "9")):
            return f"bj{pure}"
        return f"sh{pure}"

    def get_market_symbols(self) -> List[Tuple[str, str, str]]:
        """获取全市场股票列表 (symbol, code, name)"""
        symbols = []
        try:
            for node in ["hs_a", "bse"]:
                page = 1
                while page <= 65:
                    url = f"https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData?page={page}&num=100&sort=symbol&asc=1&node={node}"
                    resp = self.session.get(url, timeout=3.0)
                    if resp.status_code != 200:
                        break
                    data = resp.json()
                    if not data or not isinstance(data, list):
                        break
                    for item in data:
                        full_sym = str(item["symbol"]).lower()
                        pure_code = re.sub(r'^[a-z]+', '', full_sym).zfill(6)
                        symbols.append((full_sym, pure_code, item.get("name", "")))
                    page += 1
            logger.info(f"成功获取全市场股票列表: {len(symbols)} 只")
        except Exception as e:
            logger.warning(f"全市场代码清单拉取异常: {e}")
        return symbols

    def prefilter_pool(self, raw_symbols: List[Tuple[str, str, str]]) -> Dict[str, dict]:
        """批量获取快照，滤除 ST/退市及低成交量股票"""
        valid_pool = {}
        batch_size = 80
        for i in range(0, len(raw_symbols), batch_size):
            batch = raw_symbols[i : i + batch_size]
            query_param = ",".join([s[0].lower() for s in batch])
            url = f"https://qt.gtimg.cn/q={query_param}"
            try:
                resp = self.session.get(url, timeout=2.5)
                for line in resp.text.strip().split(";"):
                    if not line or "=" not in line:
                        continue
                    m = re.search(r'v_(.*?)=\"(.*?)\"', line)
                    if not m:
                        continue
                    symbol = m.group(1).lower()
                    fields = m.group(2).split("~")
                    if len(fields) < 45:
                        continue

                    name = fields[1]
                    latest_price = float(fields[3] or 0)
                    amount = float(fields[37] or 0) * 10000
                    float_market_cap = float(fields[44] or 0) * 100000000.0

                    if any(k in name for k in ["退", "ST", "*ST"]):
                        continue
                    if latest_price <= 0 or amount < cfg.MIN_AMOUNT:
                        continue

                    float_shares = (float_market_cap / latest_price) if latest_price > 0 else 0
                    valid_pool[symbol] = {
                        "symbol": symbol,
                        "code": re.sub(r'^[a-z]+', '', symbol).zfill(6),
                        "name": name,
                        "latest_price": latest_price,
                        "turnover_today": float(fields[38] or 0),
                        "float_shares": float_shares,
                        "amount": amount
                    }
            except Exception:
                continue
        return valid_pool

    def fetch_single_kline(self, symbol: str, float_shares: float = 0.0, datalen: int = 320) -> Optional[pd.DataFrame]:
        """拉取单只股票 K 线（优先腾讯，备用新浪）"""
        symbol = symbol.lower()
        # 通道 1: 腾讯日线
        try:
            url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={symbol},day,,,{datalen}"
            resp = self.session.get(url, timeout=cfg.REQUEST_TIMEOUT)
            if resp.status_code == 200:
                data = resp.json().get("data", {}).get(symbol, {})
                raw_bars = data.get("day", [])
                if not raw_bars:
                    for k in ["qfqday", "hfqday"]:
                        if isinstance(data.get(k), list) and len(data.get(k)) > 0:
                            raw_bars = data.get(k)
                            break
                if isinstance(raw_bars, list) and len(raw_bars) > 0:
                    rows = []
                    for b in raw_bars:
                        if not isinstance(b, list) or len(b) < 6:
                            continue
                        vol = float(b[5]) * 100.0
                        turnover_pct = (vol / float_shares * 100) if float_shares > 0 else 0.0
                        rows.append({
                            "symbol": symbol,
                            "date": str(b[0]),
                            "open": float(b[1]),
                            "close": float(b[2]),
                            "high": float(b[3]),
                            "low": float(b[4]),
                            "volume": vol,
                            "turnover_pct": turnover_pct
                        })
                    if rows:
                        df = pd.DataFrame(rows)
                        return df.sort_values("date").reset_index(drop=True)
        except Exception:
            pass

        # 通道 2: 新浪备用
        try:
            url = f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={symbol}&scale=240&ma=no&datalen={datalen}"
            resp = self.session.get(url, timeout=cfg.REQUEST_TIMEOUT)
            if resp.status_code == 200:
                text = resp.text.strip()
                if text.startswith("var"):
                    text = text[text.find("=") + 1 :].rstrip(";")
                raw_bars = json.loads(text)
                if isinstance(raw_bars, list) and len(raw_bars) > 0:
                    rows = []
                    for b in raw_bars:
                        vol = float(b.get("volume", 0))
                        turnover_pct = (vol / float_shares * 100) if float_shares > 0 else 0.0
                        rows.append({
                            "symbol": symbol,
                            "date": str(b["day"]).split(" ")[0],
                            "open": float(b["open"]),
                            "close": float(b["close"]),
                            "high": float(b["high"]),
                            "low": float(b["low"]),
                            "volume": vol,
                            "turnover_pct": turnover_pct
                        })
                    if rows:
                        df = pd.DataFrame(rows)
                        return df.sort_values("date").reset_index(drop=True)
        except Exception:
            pass

        return None

    def fetch_realtime_snapshot(self, symbols: List[str]) -> Dict[str, dict]:
        """批量获取盘中最新切片数据"""
        result = {}
        if not symbols:
            return result
        for i in range(0, len(symbols), 80):
            batch = symbols[i : i + 80]
            query_param = ",".join([s.lower() for s in batch])
            url = f"https://qt.gtimg.cn/q={query_param}"
            try:
                resp = self.session.get(url, timeout=2.0)
                for line in resp.text.strip().split(";"):
                    m = re.search(r'v_(.*?)=\"(.*?)\"', line)
                    if not m:
                        continue
                    symbol = m.group(1).lower()
                    fields = m.group(2).split("~")
                    if len(fields) < 45:
                        continue
                    result[symbol] = {
                        "symbol": symbol,
                        "name": fields[1],
                        "price": float(fields[3] or 0),
                        "open": float(fields[5] or 0),
                        "high": float(fields[33] or 0),
                        "low": float(fields[34] or 0),
                        "volume_ratio": float(fields[49] or 1.0) if len(fields) > 49 and fields[49] else 1.0,
                        "turnover_pct": float(fields[38] or 0),
                        "gain_pct": float(fields[32] or 0)
                    }
            except Exception:
                continue
        return result