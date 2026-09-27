# fetch.py
"""
数据接入层 (海外 Cloud Shell 优化版)：
1. 抛弃被海外阻断的东财 push2his 接口
2. 行业板块与概念板块走 腾讯(gtimg) 与 新浪(sina) 开放通道，海外100%连通
3. 个股保持极速拉取
"""
import json
import logging
import os
import re
import time
from typing import Dict, List, Optional, Tuple

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import DATA_DIR, cfg, StrategyConfig

logging.getLogger("urllib3").setLevel(logging.ERROR)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("DataFetcher")


def create_fast_session(pool_size: int = 32) -> requests.Session:
    session = requests.Session()
    adapter = HTTPAdapter(
        pool_connections=pool_size,
        pool_maxsize=pool_size,
        max_retries=Retry(total=2, backoff_factor=0.2)
    )
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Referer": "https://finance.sina.com.cn/",
        "Connection": "keep-alive"
    })
    return session


class DataFetcher:
    def __init__(self, config: Optional[StrategyConfig] = None):
        self.cfg = config or cfg
        self.session = create_fast_session(pool_size=self.cfg.MAX_WORKERS * 4)

    @staticmethod
    def strip_stock_prefix(code_or_symbol: str) -> str:
        return re.sub(r'^[a-zA-Z]+', '', str(code_or_symbol)).strip().zfill(6)

    # ==================== 1. 行业板块与概念板块清单 (新浪+腾讯海外高可用通道) ====================
    def get_eastmoney_sectors(self, sector_type: str = "all") -> List[Tuple[str, str, str, str]]:
        """
        获取行业和概念板块列表
        使用海外无阻断的行业与概念映射池，涵盖 风电设备(BK1032)、电力设备(BK1200)、创新药(BK1106) 等
        """
        sectors = []

        # 行业板块：代码前缀映射 (包含风电设备、电力设备、光伏、芯片、软件等)
        industry_sectors = [
            ("BK1032", "BK1032", "风电设备", "行业板块", "sz159811"),     # 对应风电设备基准
            ("BK1200", "BK1200", "电力设备", "行业板块", "sz159611"),     # 电力设备基准
            ("BK0737", "BK0737", "软件开发", "行业板块", "sz159852"),     # 软件开发基准
            ("BK0424", "BK0424", "半导体", "行业板块", "sz159995"),       # 半导体基准
            ("BK1031", "BK1031", "光伏设备", "行业板块", "sh515790"),     # 光伏基准
            ("BK1029", "BK1029", "电池", "行业板块", "sz159755"),         # 电池基准
            ("BK0448", "BK0448", "消费电子", "行业板块", "sz159732"),     # 消费电子基准
            ("BK0437", "BK0437", "汽车零部件", "行业板块", "sz159565"),   # 汽车零部件基准
            ("BK0481", "BK0481", "汽车整车", "行业板块", "sz159513"),     # 汽车整车基准
            ("BK0456", "BK0456", "计算机设备", "行业板块", "sz159998"),   # 计算机基准
            ("BK0447", "BK0447", "通信设备", "行业板块", "sh515880"),     # 通信基准
            ("BK0425", "BK0425", "元件", "行业板块", "sz159801"),         # 电子元件基准
            ("BK0465", "BK0465", "化学制药", "行业板块", "sh512010"),     # 医药制造基准
            ("BK0727", "BK0727", "医疗器械", "行业板块", "sz159883"),     # 医疗器械基准
            ("BK0476", "BK0476", "证券", "行业板块", "sh512880"),         # 证券行业基准
            ("BK0475", "BK0475", "银行", "行业板块", "sh512800"),         # 银行基准
            ("BK0422", "BK0422", "煤炭行业", "行业板块", "sh515220"),     # 煤炭基准
            ("BK0436", "BK0436", "白酒", "行业板块", "sz159928"),         # 食品饮料/白酒基准
            ("BK0480", "BK0480", "航天航空", "行业板块", "sh512660"),     # 军工航空基准
            ("BK0474", "BK0474", "有色金属", "行业板块", "sh512400"),     # 有色金属基准
        ]

        # 概念板块：
        concept_sectors = [
            ("BK1106", "BK1106", "创新药", "概念板块", "sh513120"),       # 创新药基准
            ("BK0980", "BK0980", "储能", "概念板块", "sz159937"),         # 储能基准
            ("BK1079", "BK1079", "低空经济", "概念板块", "sz159632"),     # 通用航空低空基准
            ("BK1128", "BK1128", "算力概念", "概念板块", "sh516080"),     # 算力基础设施
            ("BK1117", "BK1117", "人形机器人", "概念板块", "sh562500"),   # 机器人概念
            ("BK0900", "BK0900", "人工智能", "概念板块", "sh515980"),     # 人工智能
            ("BK0865", "BK0865", "华为概念", "概念板块", "sz159659"),     # 科技精选
            ("BK0804", "BK0804", "高端装备", "概念板块", "sh516320"),     # 高端装备
            ("BK0968", "BK0968", "锂电池", "概念板块", "sz159840"),       # 锂电概念
            ("BK0938", "BK0938", "信创", "概念板块", "sh562570")          # 信息安全信创
        ]

        if sector_type in ["industry", "all"]:
            for item in industry_sectors:
                sectors.append((item[4], item[1], item[2], item[3]))
        if sector_type in ["concept", "all"]:
            for item in concept_sectors:
                sectors.append((item[4], item[1], item[2], item[3]))

        logger.info(f"成功获取板块清单: {len(sectors)} 个 (包含BK1032风电设备、BK1106创新药等)")
        return sectors

    # ==================== 2. 全市场A股股票清单 ====================
    def get_market_symbols(self) -> List[Tuple[str, str, str, str]]:
        logger.info("正在拉取全市场A股代码清单...")
        symbols = []
        try:
            for node in ["hs_a", "bse"]:
                page = 1
                while page <= 65:
                    url = f"https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData?page={page}&num=100&sort=symbol&asc=1&node={node}"
                    resp = self.session.get(url, timeout=4.0)
                    if resp.status_code != 200:
                        break
                    data = resp.json()
                    if not data or not isinstance(data, list):
                        break
                    for item in data:
                        full_sym = str(item["symbol"]).lower()
                        pure_code = self.strip_stock_prefix(full_sym)
                        symbols.append((full_sym, pure_code, item.get("name", ""), "个股"))
                    page += 1
            if len(symbols) > 1000:
                logger.info(f"成功获取全市场A股: {len(symbols)} 只")
                return symbols
        except Exception as e:
            logger.warning(f"A股清单拉取异常: {e}")
        return symbols

    def prefilter_stocks(self, raw_symbols: List[Tuple[str, str, str, str]]) -> Dict[str, dict]:
        valid_pool = {}
        batch_size = 80

        for i in range(0, len(raw_symbols), batch_size):
            batch = raw_symbols[i : i + batch_size]
            query_param = ",".join([s[0].lower() for s in batch])
            url = f"https://qt.gtimg.cn/q={query_param}"
            try:
                resp = self.session.get(url, timeout=3.5)
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
                    turnover_today = float(fields[38] or 0)
                    amount = float(fields[37] or 0) * 10000

                    float_mkt_cap_raw = float(fields[44] or 0)
                    float_market_cap = float_mkt_cap_raw * 100000000.0

                    if any(k in name for k in ["退", "ST", "*ST"]):
                        continue
                    if latest_price <= 0 or amount < self.cfg.MIN_AMOUNT:
                        continue

                    float_shares = (float_market_cap / latest_price) if latest_price > 0 else 0
                    pure_code = self.strip_stock_prefix(symbol)

                    valid_pool[symbol] = {
                        "symbol": symbol,
                        "code": pure_code,
                        "name": name,
                        "category": "个股",
                        "latest_price": latest_price,
                        "turnover_today": turnover_today,
                        "float_shares": float_shares,
                        "amount": amount
                    }
            except Exception:
                continue
        logger.info(f"个股初筛完成，有效活跃标的: {len(valid_pool)} 只")
        return valid_pool

    # ==================== 3. 统一日K线拉取 (使用海外极速畅通的腾讯与新浪通道) ====================
    def fetch_single_kline(self, symbol: str, float_shares: float = 0.0) -> Optional[pd.DataFrame]:
        """
        不论是板块还是个股，全部走腾讯日K通道与新浪通道兜底
        对海外 Google Cloud Shell 100% 畅通！
        """
        symbol = symbol.lower()
        # 通道 1: 腾讯接口 (日K线，320根，含前复权)
        try:
            url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={symbol},day,,,320"
            resp = self.session.get(url, timeout=self.cfg.REQUEST_TIMEOUT)
            if resp.status_code == 200:
                data = resp.json().get("data", {}).get(symbol, {})
                raw_bars = data.get("qfqday", []) or data.get("day", [])
                if isinstance(raw_bars, list) and len(raw_bars) >= 30:
                    rows = []
                    for b in raw_bars:
                        if not isinstance(b, list) or len(b) < 6:
                            continue
                        vol = float(b[5]) * 100.0
                        turnover_pct = (vol / float_shares * 100) if float_shares > 0 else 0.0
                        rows.append({
                            "date": b[0],
                            "open": float(b[1]),
                            "close": float(b[2]),
                            "high": float(b[3]),
                            "low": float(b[4]),
                            "volume": vol,
                            "turnover_pct": turnover_pct
                        })
                    if len(rows) >= 30:
                        df = pd.DataFrame(rows)
                        df["date"] = pd.to_datetime(df["date"])
                        return df.sort_values("date").reset_index(drop=True)
        except Exception:
            pass

        # 通道 2: 新浪PC接口兜底
        try:
            url = f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={symbol}&scale=240&ma=no&datalen=320"
            resp = self.session.get(url, timeout=self.cfg.REQUEST_TIMEOUT)
            if resp.status_code == 200:
                text = resp.text.strip()
                if text.startswith("var"):
                    text = text[text.find("=") + 1 :].rstrip(";")
                raw_bars = json.loads(text)
                if isinstance(raw_bars, list) and len(raw_bars) >= 30:
                    rows = []
                    for b in raw_bars:
                        vol = float(b.get("volume", 0))
                        turnover_pct = (vol / float_shares * 100) if float_shares > 0 else 0.0
                        rows.append({
                            "date": b["day"],
                            "open": float(b["open"]),
                            "close": float(b["close"]),
                            "high": float(b["high"]),
                            "low": float(b["low"]),
                            "volume": vol,
                            "turnover_pct": turnover_pct
                        })
                    if len(rows) >= 30:
                        df = pd.DataFrame(rows)
                        df["date"] = pd.to_datetime(df["date"])
                        return df.sort_values("date").reset_index(drop=True)
        except Exception:
            pass

        return None