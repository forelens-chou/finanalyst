"""
行情数据采集与双源故障转移模块 (带容错与自愈强化版)
"""

import json
import logging
import os
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
        "Accept-Encoding": "gzip, deflate",
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
        """格式化为小写标准前缀代码（sh/sz/bj）"""
        code = str(code).strip().lower()
        pure = re.sub(r'^[a-z]+', '', code).zfill(6)
        if pure.startswith(("60", "68")):
            return f"sh{pure}"
        elif pure.startswith(("00", "30")):
            return f"sz{pure}"
        elif pure.startswith(("8", "4", "9")):
            return f"bj{pure}"
        return f"sh{pure}"

    # ---------------- 1. 外部文档解析 ----------------
    def load_symbols_from_file(self, file_path: str) -> List[Tuple[str, str, str]]:
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"未找到文件: {file_path}")

        logger.info(f"正在读取外部股票池文件: {file_path}")
        content = ""
        for encoding in ["utf-8-sig", "utf-8", "gbk"]:
            try:
                with open(file_path, "r", encoding=encoding) as f:
                    content = f.read()
                break
            except Exception:
                continue

        tokens = re.split(r'[\r\n,;\t\s]+', content)
        extracted_codes = set()

        for token in tokens:
            token = token.strip().lower()
            if not token or token.startswith("#"):
                continue
            pure = re.sub(r'^(sh|sz|bj)', '', token)
            if pure.isdigit() and 1 <= len(pure) <= 6:
                clean_code = pure.zfill(6)
                if clean_code.startswith(("00", "30", "60", "68", "8", "4", "9")):
                    extracted_codes.add(clean_code)

        symbols = [(self.to_full_symbol(c), c, "") for c in sorted(extracted_codes)]
        logger.info(f"成功提取到 {len(symbols)} 只合规代码")
        return symbols

    # ---------------- 2. 全市场代码获取 ----------------
    def get_market_symbols(self) -> List[Tuple[str, str, str]]:
        logger.info("正在获取全市场基础代码清单...")
        try:
            df = ak.stock_info_a_code_name()
            if df is not None and len(df) > 4000:
                symbols = []
                for _, row in df.iterrows():
                    pure_code = str(row["code"]).strip().zfill(6)
                    name = str(row["name"]).strip()
                    symbols.append((self.to_full_symbol(pure_code), pure_code, name))
                return symbols
        except Exception:
            pass

        # 新浪节点兜底
        symbols = []
        for node in ["hs_a", "bse"]:
            page = 1
            while page <= 60:
                url = f"http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData?page={page}&num=100&sort=symbol&asc=1&node={node}"
                try:
                    resp = self.market_session.get(url, timeout=self.cfg.REQUEST_TIMEOUT)
                    data = resp.json()
                    if not data or not isinstance(data, list):
                        break
                    for item in data:
                        full_sym = str(item["symbol"]).lower()
                        pure_code = re.sub(r'^[a-z]+', '', full_sym).zfill(6)
                        symbols.append((full_sym, pure_code, item["name"]))
                    page += 1
                except Exception:
                    break
        return symbols

    # ---------------- 3. 快照初筛与名称补全 ----------------
    def prefilter_pool(self, raw_symbols: List[Tuple[str, str, str]], skip_liquidity: bool = False) -> List[dict]:
        filtered = []
        for i in range(0, len(raw_symbols), self.cfg.BATCH_SIZE):
            batch = raw_symbols[i : i + self.cfg.BATCH_SIZE]
            query_param = ",".join([s[0].lower() for s in batch])
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
                    symbol = m.group(1).lower()
                    fields = m.group(2).split("~")
                    if len(fields) < 39:
                        continue

                    pure_code = re.sub(r'^[a-z]+', '', symbol).zfill(6)
                    name = fields[1]
                    amount = float(fields[37] or 0) * 10000
                    turnover = float(fields[38] or 0)

                    if "退" in name:
                        continue

                    if not skip_liquidity:
                        if any(k in name for k in ["ST", "*ST"]):
                            continue
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
            except Exception as e:
                logger.debug(f"快照批量请求异常: {e}")

        logger.info(f"快照解析完成，进入深度形态扫描的标的数: {len(filtered)} 只")
        return filtered

    # ---------------- 4. 双源 K 线采集强化实现 ----------------
    def _fetch_from_tencent(self, symbol: str) -> Optional[pd.DataFrame]:
        symbol = symbol.lower()
        url = f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={symbol},day,,,{self.cfg.KLINE_BARS},qfq"
        resp = self.kline_session.get(url, timeout=self.cfg.REQUEST_TIMEOUT)
        if resp.status_code != 200:
            raise ConnectionError(f"Tencent HTTP {resp.status_code}")

        data = resp.json()
        stock_data = data.get("data", {}).get(symbol, {})
        # 兼容 qfqday 或普通 day
        raw_bars = stock_data.get("qfqday", stock_data.get("day", []))
        if not raw_bars:
            raise ValueError(f"Tencent empty bars for {symbol}")

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
        symbol = symbol.lower()
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
            raise ValueError(f"Sina empty bars for {symbol}")

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
        symbol = symbol.lower()
        # 1. 尝试主源: 腾讯
        for _ in range(self.cfg.MAX_RETRIES):
            try:
                df = self._fetch_from_tencent(symbol)
                if df is not None and len(df) >= self.cfg.MIN_LISTING_DAYS:
                    return df
            except Exception as e:
                # 记录最后一次错误便于追踪
                last_err = e

        # 2. 降级备用源: 新浪
        for _ in range(self.cfg.MAX_RETRIES):
            try:
                df = self._fetch_from_sina(symbol)
                if df is not None and len(df) >= self.cfg.MIN_LISTING_DAYS:
                    return df
            except Exception as e:
                last_err = e

        # 仅对单只样本输出排查日志，避免刷屏
        logger.debug(f"[{symbol}] K线获取最终失败: {last_err}")
        return None