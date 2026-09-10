"""
行情数据采集与双源故障转移模块
负责：
1. 全市场代码清单获取（AkShare 静态库优先，新浪双节点兜底）
2. 腾讯批量快照极速初筛（换手率与成交额分层过滤）
3. 腾讯 HTTP (主) -> 新浪 JSONP (备) 双源 K 线平滑故障转移
"""

import json
import logging
import re
import time
from typing import List, Optional, Tuple

import akshare as ak
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import ScreenerConfig

logger = logging.getLogger("MAScreener")


def create_robust_session(pool_size: int = 50) -> requests.Session:
    """创建高并发长连接池 Session，彻底消除连接池打满警告"""
    session = requests.Session()
    adapter = HTTPAdapter(
        pool_connections=pool_size,
        pool_maxsize=pool_size,
        max_retries=Retry(total=2, backoff_factor=0.3, status_forcelist=[500, 502, 503, 504])
    )
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Connection": "keep-alive"
    })
    return session


class DataFetcher:
    def __init__(self, config: ScreenerConfig):
        self.cfg = config
        self.kline_session = create_robust_session(pool_size=config.MAX_WORKERS * 4)
        self.market_session = create_robust_session(pool_size=config.MAX_WORKERS * 2)

    @staticmethod
    def to_full_symbol(code: str) -> str:
        """转换标准带市场前缀的代码（支持北交所）"""
        code = str(code).strip()
        if code.startswith(("60", "68")):
            return f"sh{code}"
        elif code.startswith(("00", "30")):
            return f"sz{code}"
        elif code.startswith(("8", "4", "9")):
            return f"bj{code}"
        return f"sh{code}"

    # ---------------- 1. 全市场代码库获取 ----------------
    def _fetch_sina_node(self, node: str) -> List[Tuple[str, str, str]]:
        symbols = []
        page = 1
        consecutive_failures = 0

        while consecutive_failures < 3:
            url = (
                f"http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
                f"Market_Center.getHQNodeData?page={page}&num=100&sort=symbol&asc=1&node={node}"
            )
            try:
                resp = self.market_session.get(url, timeout=self.cfg.REQUEST_TIMEOUT)
                data = resp.json()
                if not data or not isinstance(data, list) or len(data) == 0:
                    break
                for item in data:
                    full_sym = item["symbol"]
                    pure_code = re.sub(r"^[a-zA-Z]+", "", full_sym).zfill(6)
                    symbols.append((full_sym, pure_code, item["name"]))
                page += 1
                consecutive_failures = 0
            except Exception:
                consecutive_failures += 1
                time.sleep(0.5)

        return symbols

    def get_market_symbols(self) -> List[Tuple[str, str, str]]:
        logger.info("正在获取全市场基础代码清单...")

        # 优先使用 AkShare 静态源（规避海外 IP 拦截）
        try:
            df = ak.stock_info_a_code_name()
            if df is not None and len(df) > 4000:
                symbols = []
                for _, row in df.iterrows():
                    pure_code = str(row["code"]).strip().zfill(6)
                    name = str(row["name"]).strip()
                    symbols.append((self.to_full_symbol(pure_code), pure_code, name))
                logger.info(f"成功获取股票列表 (AkShare 静态源): {len(symbols)} 只")
                return symbols
        except Exception:
            pass

        # 降级新浪双节点 (沪深 hs_a + 北交所 bse)
        logger.info("降级通过新浪双节点 (沪深+北交所) 分页获取全量代码...")
        symbols_hs = self._fetch_sina_node("hs_a")
        symbols_bse = self._fetch_sina_node("bse")
        symbols = symbols_hs + symbols_bse

        # 排重
        seen = set()
        dedup_symbols = []
        for s in symbols:
            if s[1] not in seen:
                seen.add(s[1])
                dedup_symbols.append(s)

        if len(dedup_symbols) < 1000:
            raise RuntimeError(f"股票列表拉取异常，仅获得 {len(dedup_symbols)} 只，请检查网络！")

        logger.info(f"代码库就绪，全市场有效股票数: {len(dedup_symbols)} 只")
        return dedup_symbols

    # ---------------- 2. 腾讯批量快照初筛 ----------------
    def prefilter_pool(self, raw_symbols: List[Tuple[str, str, str]]) -> List[dict]:
        logger.info("正在使用腾讯批量快照执行流动性预筛选...")
        filtered = []

        for i in range(0, len(raw_symbols), self.cfg.BATCH_SIZE):
            batch = raw_symbols[i : i + self.cfg.BATCH_SIZE]
            batch = [s for s in batch if not any(k in s[2] for k in ["ST", "*ST", "退"])]
            if not batch:
                continue

            query_param = ",".join([s[0] for s in batch])
            url = f"http://qt.gtimg.cn/q={query_param}"
            try:
                resp = self.market_session.get(url, timeout=self.cfg.REQUEST_TIMEOUT)
                for line in resp.text.strip().split(";"):
                    line = line.strip()
                    if not line or "=" not in line:
                        continue
                    m = re.search(r'v_(.*?)=\"(.*?)\"', line)
                    if not m:
                        continue
                    symbol = m.group(1)
                    fields = m.group(2).split("~")
                    if len(fields) < 39:
                        continue

                    pure_code = re.sub(r"^[a-zA-Z]+", "", symbol).zfill(6)
                    name = fields[1]
                    amount = float(fields[37] or 0) * 10000
                    turnover = float(fields[38] or 0)

                    # 分层流动性标准
                    if symbol.startswith("bj"):
                        if not (turnover >= self.cfg.BSE_MIN_TURNOVER and amount >= self.cfg.BSE_MIN_AMOUNT):
                            continue
                    else:
                        cond1 = amount >= self.cfg.MAIN_MIN_AMOUNT
                        cond2 = (turnover >= self.cfg.MAIN_MIN_TURNOVER) and (amount >= self.cfg.MAIN_ALT_AMOUNT)
                        if not (cond1 or cond2):
                            continue

                    filtered.append({
                        "symbol": symbol,
                        "code": pure_code,
                        "name": name,
                    })
            except Exception:
                pass

        logger.info(f"预筛选完成，符合流动性标准的计算标的: {len(filtered)} 只")
        return filtered

    # ---------------- 3. 双源 K 线采集与故障转移 ----------------
    def _fetch_from_tencent(self, symbol: str) -> Optional[pd.DataFrame]:
        url = f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={symbol},day,,,{self.cfg.KLINE_BARS},qfq"
        resp = self.kline_session.get(url, timeout=self.cfg.REQUEST_TIMEOUT)
        if resp.status_code != 200:
            raise ConnectionError(f"Tencent HTTP {resp.status_code}")

        data = resp.json()
        stock_data = data.get("data", {}).get(symbol, {})
        raw_bars = stock_data.get("qfqday", stock_data.get("day", []))
        if not raw_bars:
            raise ValueError("Empty kline")

        rows = []
        for b in raw_bars:
            rows.append({
                "date": b[0],
                "open": float(b[1]),
                "close": float(b[2]),
                "high": float(b[3]),
                "low": float(b[4]),
                "volume": float(b[5]),
            })
        df = pd.DataFrame(rows)
        df["date"] = pd.to_datetime(df["date"])
        return df.sort_values("date").reset_index(drop=True)

    def _fetch_from_sina(self, symbol: str) -> Optional[pd.DataFrame]:
        url = (
            f"http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
            f"CN_MarketData.getKLineData?symbol={symbol}&scale=240&ma=no&datalen={self.cfg.KLINE_BARS}"
        )
        resp = self.kline_session.get(url, timeout=self.cfg.REQUEST_TIMEOUT)
        if resp.status_code != 200:
            raise ConnectionError(f"Sina HTTP {resp.status_code}")

        text = resp.text.strip()
        if text.startswith("var"):
            text = text[text.find("=") + 1 :].rstrip(";")
        raw_bars = json.loads(text)
        if not raw_bars or not isinstance(raw_bars, list):
            raise ValueError("Empty kline")

        rows = []
        for b in raw_bars:
            rows.append({
                "date": b["day"],
                "open": float(b["open"]),
                "close": float(b["close"]),
                "high": float(b["high"]),
                "low": float(b["low"]),
                "volume": float(b["volume"]),
            })
        df = pd.DataFrame(rows)
        df["date"] = pd.to_datetime(df["date"])
        return df.sort_values("date").reset_index(drop=True)

    def get_kline(self, symbol: str) -> Optional[pd.DataFrame]:
        # 1. 尝试主源: 腾讯
        for _ in range(self.cfg.MAX_RETRIES):
            try:
                df = self._fetch_from_tencent(symbol)
                if df is not None and len(df) >= self.cfg.MIN_LISTING_DAYS:
                    return df
            except Exception:
                pass

        # 2. 降级备用源: 新浪
        for _ in range(self.cfg.MAX_RETRIES):
            try:
                df = self._fetch_from_sina(symbol)
                if df is not None and len(df) >= self.cfg.MIN_LISTING_DAYS:
                    return df
            except Exception:
                pass

        return None