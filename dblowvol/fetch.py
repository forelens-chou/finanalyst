"""
行情数据采集与多源 HTTPS 冗余模块
针对海外云服务器（Cloud Shell）优化，修复腾讯快照PE字段与超时卡死
"""

import json
import logging
import os
import random
import re
import time
from typing import List, Optional, Tuple

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
            raise FileNotFoundError(f"未找到股票代码文件: {file_path}")

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
        logger.info(f"成功从文件提取到 {len(symbols)} 只合规代码")
        return symbols

    # ---------------- 2. 全市场代码获取（免国内接口卡死海外IP） ----------------
    def get_market_symbols(self) -> List[Tuple[str, str, str]]:
        logger.info("正在获取全市场基础代码清单...")
        symbols = []

        # 源1：新浪分批快照源（海外 Cloud Shell 最稳定）
        try:
            for node in ["hs_a", "bse"]:
                page = 1
                while page <= 65:
                    url = f"https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData?page={page}&num=100&sort=symbol&asc=1&node={node}"
                    resp = self.market_session.get(url, timeout=3.0)
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
            if len(symbols) > 1000:
                logger.info(f"成功获取全市场代码: {len(symbols)} 只 (新浪源)")
                return symbols
        except Exception as e:
            logger.debug(f"新浪节点获取失败: {e}")

        # 源2：降级走 AKShare（设置极短超时，防止海外无响应卡死）
        try:
            import akshare as ak
            df = ak.stock_info_a_code_name()
            if df is not None and len(df) > 4000:
                for _, row in df.iterrows():
                    pure_code = str(row["code"]).strip().zfill(6)
                    name = str(row["name"]).strip()
                    symbols.append((self.to_full_symbol(pure_code), pure_code, name))
                logger.info(f"成功获取全市场代码: {len(symbols)} 只 (AKShare源)")
                return symbols
        except Exception:
            pass

        logger.warning(f"全市场接口受限，仅拉取到 {len(symbols)} 只代码")
        return symbols

    # ---------------- 3. 快照初筛（修复PE下标 39 与 len<40） ----------------
    def prefilter_pool(self, raw_symbols: List[Tuple[str, str, str]]) -> List[dict]:
        filtered = []
        batch_size = 80

        if not raw_symbols:
            logger.error("待筛查股票列表为空，请检查网络或提供 stocks.txt 文件！")
            return []

        for i in range(0, len(raw_symbols), batch_size):
            batch = raw_symbols[i : i + batch_size]
            query_param = ",".join([s[0].lower() for s in batch])
            url = f"https://qt.gtimg.cn/q={query_param}"
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
                    
                    # 腾讯行情核心字段达到 40 个即包含市盈率
                    if len(fields) < 40:
                        continue

                    pure_code = re.sub(r'^[a-z]+', '', symbol).zfill(6)
                    name = fields[1]
                    latest_price = float(fields[3] or 0)
                    amount = float(fields[37] or 0) * 10000  # 成交额 (元)
                    
                    # 关键修复：腾讯接口下标 39 为市盈率 PE(TTM/动态)
                    pe_raw = fields[39].strip()

                    # 1. 过滤退市与风险警示
                    if any(k in name for k in ["退", "ST", "*ST"]):
                        continue

                    # 2. 过滤停牌（最新价为0或成交额为0）
                    if latest_price <= 0 or amount == 0:
                        continue

                    # 3. 基础流动性保护（防止零成交死水股）
                    if amount < getattr(self.cfg, "MIN_AMOUNT", 3000000.0):
                        continue

                    # 4. 市盈率过滤
                    try:
                        pe_val = float(pe_raw) if pe_raw else 0.0
                    except ValueError:
                        pe_val = 0.0

                    if not (self.cfg.MIN_PE_TTM <= pe_val <= self.cfg.MAX_PE_TTM):
                        continue

                    filtered.append({
                        "symbol": symbol,
                        "code": pure_code,
                        "name": name,
                        "latest_price": latest_price,
                        "pe_ttm": pe_val,
                        "amount": amount
                    })
            except Exception as e:
                logger.debug(f"快照批量异常: {e}")

        logger.info(f"快照初筛完成（已完成PE与基本过滤），进入深度形态分析标的: {len(filtered)} 只")
        return filtered

    # ---------------- 4. K 线数据获取 ----------------
    def _fetch_from_tencent_https(self, symbol: str) -> Optional[pd.DataFrame]:
        symbol = symbol.lower()
        url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={symbol},day,,,{self.cfg.KLINE_BARS},qfq"
        resp = self.kline_session.get(url, timeout=self.cfg.REQUEST_TIMEOUT)
        if resp.status_code != 200:
            raise ConnectionError(f"Tencent HTTPS Status {resp.status_code}")

        data = resp.json()
        stock_data = data.get("data", {}).get(symbol, {})
        raw_bars = stock_data.get("qfqday", stock_data.get("day", []))
        if not raw_bars:
            raise ValueError("Tencent empty bars")

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

    def _fetch_from_sina_https(self, symbol: str) -> Optional[pd.DataFrame]:
        symbol = symbol.lower()
        url = (
            f"https://quotes.sina.cn/cn/api/json_v2.php/"
            f"CN_MarketData.getKLineData?symbol={symbol}&scale=240&ma=no&datalen={self.cfg.KLINE_BARS}"
        )
        resp = self.kline_session.get(url, timeout=self.cfg.REQUEST_TIMEOUT)
        if resp.status_code != 200:
            raise ConnectionError(f"Sina HTTP Status {resp.status_code}")

        text = resp.text.strip()
        if text.startswith("var"):
            text = text[text.find("=") + 1 :].rstrip(";")
        raw_bars = json.loads(text)
        if not raw_bars or not isinstance(raw_bars, list):
            raise ValueError("Sina empty bars")

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
        time.sleep(random.uniform(0.01, 0.02))

        for _ in range(self.cfg.MAX_RETRIES):
            try:
                df = self._fetch_from_tencent_https(symbol)
                if df is not None and len(df) >= self.cfg.MIN_LISTING_DAYS:
                    return df
            except Exception:
                pass

        for _ in range(self.cfg.MAX_RETRIES):
            try:
                df = self._fetch_from_sina_https(symbol)
                if df is not None and len(df) >= self.cfg.MIN_LISTING_DAYS:
                    return df
            except Exception:
                pass

        return None