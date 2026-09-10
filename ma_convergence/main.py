import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import akshare as ak
import numpy as np
import pandas as pd
import requests

# ==================== 日志与全局配置 ====================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("MAScreener")


@dataclass
class ScreenerConfig:
    MA_PERIODS: Tuple[int, ...] = (5, 10, 20, 30, 60, 120, 250)
    MIN_LISTING_DAYS: int = 35

    BANDWIDTH_5LINES: float = 0.035
    BANDWIDTH_4LINES: float = 0.040
    VOL_RATIO_MIN: float = 1.5

    BSE_MIN_AMOUNT: float = 8_000_000      # 800万
    BSE_MIN_TURNOVER: float = 1.5          # 1.5%
    MAIN_MIN_AMOUNT: float = 20_000_000    # 3000万
    MAIN_ALT_AMOUNT: float = 15_000_000    # 2000万
    MAIN_MIN_TURNOVER: float = 1.5

    MAX_WORKERS: int = 12
    REQUEST_TIMEOUT: float = 4.0
    MAX_RETRIES: int = 2
    KLINE_BARS: int = 320


# ==================== 双源 K 线采集引擎 ====================
class DualSourceKlineFetcher:
    def __init__(self, config: ScreenerConfig):
        self.cfg = config
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })

    def _fetch_from_tencent(self, symbol: str) -> Optional[pd.DataFrame]:
        url = f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={symbol},day,,,{self.cfg.KLINE_BARS},qfq"
        resp = self.session.get(url, timeout=self.cfg.REQUEST_TIMEOUT)
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
        url = f"http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={symbol}&scale=240&ma=no&datalen={self.cfg.KLINE_BARS}"
        resp = self.session.get(url, timeout=self.cfg.REQUEST_TIMEOUT)
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
        for attempt in range(self.cfg.MAX_RETRIES):
            try:
                df = self._fetch_from_tencent(symbol)
                if df is not None and len(df) >= self.cfg.MIN_LISTING_DAYS:
                    return df
            except Exception:
                pass

        try:
            df = self._fetch_from_sina(symbol)
            if df is not None and len(df) >= self.cfg.MIN_LISTING_DAYS:
                return df
        except Exception:
            pass

        return None


# ==================== 策略判定引擎 ====================
class StrategyEngine:
    def __init__(self, config: ScreenerConfig):
        self.cfg = config

    def evaluate(self, symbol: str, name: str, df: pd.DataFrame) -> Optional[dict]:
        total_bars = len(df)
        if total_bars < self.cfg.MIN_LISTING_DAYS:
            return None

        close = df["close"]
        volume = df["volume"]

        ma_values = {}
        for period in self.cfg.MA_PERIODS:
            if total_bars >= period:
                series = close.rolling(window=period).mean()
                ma_values[f"MA{period}"] = {
                    "curr": series.iloc[-1],
                    "prev1": series.iloc[-2],
                    "prev3": series.iloc[-4] if total_bars >= period + 3 else series.iloc[-2],
                }

        valid_count = len(ma_values)
        if valid_count < 4:
            return None

        sorted_ma = sorted(
            [(k, v["curr"]) for k, v in ma_values.items() if not np.isnan(v["curr"])],
            key=lambda x: x[1]
        )
        n = len(sorted_ma)

        latest_close = close.iloc[-1]
        latest_open = df["open"].iloc[-1]
        prev_close = close.iloc[-2]
        pct_chg = ((latest_close - prev_close) / prev_close) * 100.0

        ma_vol5 = volume.rolling(5).mean().iloc[-1]
        latest_vol = volume.iloc[-1]
        vol_ratio = latest_vol / ma_vol5 if ma_vol5 > 0 else 0.0

        matched_rule = None
        converged_names = []
        cluster_bandwidth = 0.0
        cluster_max_val = 0.0

        # 条件 A: 5条及以上汇聚
        if n >= 5:
            for i in range(n - 5 + 1):
                window = sorted_ma[i : i + 5]
                min_v = window[0][1]
                max_v = window[-1][1]
                spread = (max_v - min_v) / min_v
                if spread <= self.cfg.BANDWIDTH_5LINES:
                    matched_rule = "Rule_A_5Lines_Cluster"
                    converged_names = [item[0] for item in window]
                    cluster_bandwidth = spread * 100
                    cluster_max_val = max_v
                    break

        # 条件 B: 4条向上汇聚
        if not matched_rule and n >= 4:
            for i in range(n - 4 + 1):
                window = sorted_ma[i : i + 4]
                min_v = window[0][1]
                max_v = window[-1][1]
                spread = (max_v - min_v) / min_v
                if spread <= self.cfg.BANDWIDTH_4LINES:
                    all_upward = True
                    for name_k, _ in window:
                        ma_info = ma_values[name_k]
                        if not (ma_info["curr"] > ma_info["prev1"] and ma_info["curr"] > ma_info["prev3"]):
                            all_upward = False
                            break
                    if all_upward:
                        matched_rule = "Rule_B_4Lines_Upward"
                        converged_names = [item[0] for item in window]
                        cluster_bandwidth = spread * 100
                        cluster_max_val = max_v
                        break

        if not matched_rule:
            return None

        # 破局与放量过滤
        if not (latest_close >= cluster_max_val and latest_close >= latest_open and pct_chg >= 0):
            return None
        if vol_ratio < self.cfg.VOL_RATIO_MIN:
            return None

        return {
            "symbol": symbol,
            "name": name,
            "close": round(latest_close, 2),
            "pct_chg": round(pct_chg, 2),
            "vol_ratio": round(vol_ratio, 2),
            "matched_rule": matched_rule,
            "bandwidth": round(cluster_bandwidth, 2),
            "converged_mas": ",".join(converged_names),
            "listing_days": total_bars,
        }


# ==================== 调度器与高兼容股票池构建 ====================
class StockScreenerApp:
    def __init__(self, config: ScreenerConfig):
        self.cfg = config
        self.fetcher = DualSourceKlineFetcher(config)
        self.engine = StrategyEngine(config)
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })

    @staticmethod
    def _to_full_symbol(code: str) -> str:
        code = str(code).strip()
        if code.startswith(("60", "68")):
            return f"sh{code}"
        elif code.startswith(("00", "30")):
            return f"sz{code}"
        elif code.startswith(("8", "4", "9")):
            return f"bj{code}"
        return f"sh{code}"

    def _get_symbols_from_sina(self) -> List[Tuple[str, str]]:
        """从新浪财经分页拉取全市场A股/北交所代码 (兼容海外IP)"""
        logger.info("正在通过新浪财经接口获取全市场代码列表 (支持海外环境)...")
        symbols = []
        page = 1
        num_per_page = 100
        while True:
            url = (
                f"http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
                f"Market_Center.getHQNodeData?page={page}&num={num_per_page}&sort=symbol&asc=1&node=hs_a"
            )
            try:
                resp = self.session.get(url, timeout=self.cfg.REQUEST_TIMEOUT)
                data = resp.json()
                if not data or not isinstance(data, list):
                    break
                for item in data:
                    symbols.append((item["symbol"], item["name"]))
                page += 1
            except Exception as e:
                logger.warning(f"新浪节点拉取完成或分页结束: {e}")
                break
        return symbols

    def _get_symbols_from_akshare_safe(self) -> List[Tuple[str, str]]:
        """使用 AkShare 轻量元数据表获取代码列表 (不走东方财富实时流)"""
        try:
            df = ak.stock_info_a_code_name()
            res = []
            for _, row in df.iterrows():
                code = str(row["code"]).strip()
                name = str(row["name"]).strip()
                res.append((self._to_full_symbol(code), name))
            return res
        except Exception:
            return []

    def get_market_symbols(self) -> List[Tuple[str, str]]:
        """多源故障转移获取股票代码"""
        # 1. 尝试 AkShare 基础代码表
        logger.info("尝试拉取基础股票代码列表...")
        symbols = self._get_symbols_from_akshare_safe()
        if symbols:
            logger.info(f"成功获取股票列表 (AkShare 源)，共 {len(symbols)} 只")
            return symbols

        # 2. 降级尝试新浪全市场节点
        symbols = self._get_symbols_from_sina()
        if symbols:
            logger.info(f"成功获取股票列表 (新浪源)，共 {len(symbols)} 只")
            return symbols

        raise RuntimeError("无法获取A股股票列表，请检查网络连接！")

    def _enrich_and_prefilter_with_tencent_snapshot(self, raw_symbols: List[Tuple[str, str]]) -> List[dict]:
        """
        利用腾讯批量快照接口 (qt.gtimg.cn) 快速获取成交额与换手率，
        在拉取详细 K 线前完成高并发筛选（每次打包 80 只）。
        """
        logger.info("正在使用腾讯批量快照执行流动性预筛选...")
        filtered_list = []
        batch_size = 80

        for i in range(0, len(raw_symbols), batch_size):
            batch = raw_symbols[i : i + batch_size]
            # 剔除 ST、退市标的
            batch = [s for s in batch if not any(k in s[1] for k in ["ST", "*ST", "退"])]
            if not batch:
                continue

            query_param = ",".join([s[0] for s in batch])
            url = f"http://qt.gtimg.cn/q={query_param}"
            try:
                resp = self.session.get(url, timeout=self.cfg.REQUEST_TIMEOUT)
                text = resp.text
                lines = text.strip().split(";")
                for line in lines:
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

                    name = fields[1]
                    amount = float(fields[37] or 0) * 10000  # 腾讯成交额单位为万元，转为元
                    turnover = float(fields[38] or 0)        # 腾讯换手率百分比

                    is_bse = symbol.startswith("bj")
                    # 规则预筛选
                    if is_bse:
                        if not (turnover >= self.cfg.BSE_MIN_TURNOVER and amount >= self.cfg.BSE_MIN_AMOUNT):
                            continue
                    else:
                        cond1 = amount >= self.cfg.MAIN_MIN_AMOUNT
                        cond2 = (turnover >= self.cfg.MAIN_MIN_TURNOVER) and (amount >= self.cfg.MAIN_ALT_AMOUNT)
                        if not (cond1 or cond2):
                            continue

                    filtered_list.append({
                        "symbol": symbol,
                        "name": name,
                        "amount": amount,
                        "turnover": turnover,
                    })
            except Exception:
                pass

        logger.info(f"流动性预筛选完成，进入深度形态扫描的标的数: {len(filtered_list)} 只")
        return filtered_list

    def run(self):
        start_time = time.time()
        try:
            raw_symbols = self.get_market_symbols()
        except Exception as e:
            logger.error(f"构建股票池失败: {e}")
            return

        pool = self._enrich_and_prefilter_with_tencent_snapshot(raw_symbols)
        if not pool:
            logger.warning("预筛选后候选池为空，退出任务。")
            return

        logger.info(f"启动多线程 (Workers={self.cfg.MAX_WORKERS}) 扫描K线形态...")
        results = []

        def worker_task(item: dict):
            df_kline = self.fetcher.get_kline(item["symbol"])
            if df_kline is None:
                return None
            return self.engine.evaluate(item["symbol"], item["name"], df_kline)

        with ThreadPoolExecutor(max_workers=self.cfg.MAX_WORKERS) as executor:
            future_to_stock = {executor.submit(worker_task, item): item for item in pool}
            completed_count = 0
            for future in as_completed(future_to_stock):
                completed_count += 1
                if completed_count % 200 == 0:
                    logger.info(f"扫描进度: {completed_count}/{len(pool)} ({(completed_count/len(pool)*100):.1f}%)")
                res = future.result()
                if res:
                    results.append(res)
                    logger.info(
                        f"🎯 [命中] {res['symbol']} {res['name']} | "
                        f"规则: {res['matched_rule']} | 涨幅: {res['pct_chg']}% | "
                        f"量比: {res['vol_ratio']} | 粘合线: {res['converged_mas']}"
                    )

        elapsed = time.time() - start_time
        logger.info(f"全流程耗时: {elapsed:.2f} 秒，共选出 {len(results)} 只标的。")

        if results:
            df_res = pd.DataFrame(results)
            df_res = df_res.sort_values(by=["matched_rule", "pct_chg"], ascending=[True, False])
            
            print("\n" + "=" * 80)
            print(f" 均线汇聚突破选股结果表 (共 {len(df_res)} 只)")
            print("=" * 80)
            print(df_res.to_string(index=False))
            print("=" * 80 + "\n")

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            csv_filename = f"ma_converged_stocks_{timestamp}.csv"
            df_res.to_csv(csv_filename, index=False, encoding="utf_8_sig")
            logger.info(f"结果已保存至文件: {csv_filename}")
        else:
            logger.info("今日全市场未发现满足极端汇聚突破条件的股票。")


if __name__ == "__main__":
    app_config = ScreenerConfig()
    screener = StockScreenerApp(config=app_config)
    screener.run()