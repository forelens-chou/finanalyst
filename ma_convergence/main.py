"""
A股多周期均线汇聚与向上突破选股系统 - 主执行程序 (支持近期涨停放量豁免机制)
"""

import json
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import List, Optional, Tuple

import akshare as ak
import numpy as np
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import ScreenerConfig

# ==================== 日志初始化 ====================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("MAScreener")


def create_robust_session(pool_size: int = 50) -> requests.Session:
    """创建大容量长连接池 Session"""
    session = requests.Session()
    adapter = HTTPAdapter(
        pool_connections=pool_size,
        pool_maxsize=pool_size,
        max_retries=Retry(total=2, backoff_factor=0.3, status_forcelist=[500, 502, 503, 504])
    )
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "*/*",
        "Connection": "keep-alive"
    })
    return session


# ==================== 1. 双源 K 线采集引擎 ====================
class DualSourceKlineFetcher:
    def __init__(self, config: ScreenerConfig):
        self.cfg = config
        self.session = create_robust_session(pool_size=config.MAX_WORKERS * 4)

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
        url = (
            f"http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
            f"CN_MarketData.getKLineData?symbol={symbol}&scale=240&ma=no&datalen={self.cfg.KLINE_BARS}"
        )
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
        for _ in range(self.cfg.MAX_RETRIES):
            try:
                df = self._fetch_from_tencent(symbol)
                if df is not None and len(df) >= self.cfg.MIN_LISTING_DAYS:
                    return df
            except Exception:
                pass

        for _ in range(self.cfg.MAX_RETRIES):
            try:
                df = self._fetch_from_sina(symbol)
                if df is not None and len(df) >= self.cfg.MIN_LISTING_DAYS:
                    return df
            except Exception:
                pass

        return None


# ==================== 2. 核心量化策略引擎 ====================
class StrategyEngine:
    def __init__(self, config: ScreenerConfig):
        self.cfg = config

    def _has_recent_limit_up(self, raw_code: str, df: pd.DataFrame) -> bool:
        """检查近 N 根 K 线内是否存在涨停板"""
        if not self.cfg.ENABLE_LIMIT_UP_BYPASS:
            return False

        # 根据股票代码前缀确定所属板块的涨停阈值
        if raw_code.startswith(("68", "30")):
            threshold = self.cfg.GROWTH_LIMIT_UP_PCT  # 双创板 20%
        elif raw_code.startswith(("8", "4", "9")):
            threshold = self.cfg.BSE_LIMIT_UP_PCT     # 北交所 30%
        else:
            threshold = self.cfg.MAIN_LIMIT_UP_PCT    # 主板 10%

        # 计算日收益率序列并截取近 30 根 K 线
        pct_series = (df["close"] - df["close"].shift(1)) / df["close"].shift(1) * 100.0
        lookback_pcts = pct_series.iloc[-self.cfg.LIMIT_UP_LOOKBACK_BARS :]
        return bool((lookback_pcts >= threshold).any())

    def evaluate(self, raw_code: str, name: str, df: pd.DataFrame) -> Optional[dict]:
        total_bars = len(df)
        if total_bars < self.cfg.MIN_LISTING_DAYS:
            return None

        close = df["close"]
        volume = df["volume"]

        # 计算均线
        ma_values = {}
        for period in self.cfg.MA_PERIODS:
            if total_bars >= period:
                series = close.rolling(window=period).mean()
                ma_values[f"MA{period}"] = {
                    "curr": series.iloc[-1],
                    "prev1": series.iloc[-2],
                    "prev3": series.iloc[-4] if total_bars >= period + 3 else series.iloc[-2],
                }

        if len(ma_values) < 4:
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

        # 成交量与放量指标
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
                    matched_rule = "5线粘合汇聚"
                    converged_names = [item[0] for item in window]
                    cluster_bandwidth = spread * 100
                    cluster_max_val = max_v
                    break

        # 条件 B: 4条均线向上汇聚
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
                        matched_rule = "4线向上汇聚"
                        converged_names = [item[0] for item in window]
                        cluster_bandwidth = spread * 100
                        cluster_max_val = max_v
                        break

        if not matched_rule:
            return None

        # 条件 C: 必须站上粘合簇最高线，且当日收红或平盘
        if not (latest_close >= cluster_max_val and latest_close >= latest_open and pct_chg >= 0):
            return None

        # 条件 D: 成交量与涨停基因判定
        has_limit_up = self._has_recent_limit_up(raw_code, df)
        is_vol_expanded = vol_ratio >= self.cfg.VOL_RATIO_MIN

        # 核心逻辑：若近30根K线有涨停，则豁免放量要求；否则必须满足当日放量
        if not (is_vol_expanded or has_limit_up):
            return None

        # 标注命中标签，方便在报表中一目了然
        if has_limit_up and not is_vol_expanded:
            limit_up_tag = "涨停洗盘(豁免放量)"
        elif has_limit_up and is_vol_expanded:
            limit_up_tag = "涨停+放量双共振"
        else:
            limit_up_tag = "标准放量突破"

        return {
            "code": str(raw_code).zfill(6),
            "name": name,
            "close": round(latest_close, 2),
            "pct_chg": round(pct_chg, 2),
            "vol_ratio": round(vol_ratio, 2),
            "matched_rule": matched_rule,
            "limit_up_tag": limit_up_tag,
            "bandwidth(%)": round(cluster_bandwidth, 2),
            "converged_mas": ",".join(converged_names),
            "listing_days": total_bars,
        }


# ==================== 3. 调度与防假死扫描流程 ====================
class StockScreenerApp:
    def __init__(self, config: ScreenerConfig):
        self.cfg = config
        self.fetcher = DualSourceKlineFetcher(config)
        self.engine = StrategyEngine(config)
        self.session = create_robust_session(pool_size=config.MAX_WORKERS * 2)

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

    def _fetch_sina_node_with_retry(self, node: str) -> List[Tuple[str, str, str]]:
        node_symbols = []
        page = 1
        consecutive_failures = 0

        while consecutive_failures < 3:
            url = (
                f"http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
                f"Market_Center.getHQNodeData?page={page}&num=100&sort=symbol&asc=1&node={node}"
            )
            try:
                resp = self.session.get(url, timeout=self.cfg.REQUEST_TIMEOUT)
                data = resp.json()
                if not data or not isinstance(data, list) or len(data) == 0:
                    break
                for item in data:
                    full_sym = item["symbol"]
                    pure_code = re.sub(r"^[a-zA-Z]+", "", full_sym).zfill(6)
                    node_symbols.append((full_sym, pure_code, item["name"]))
                page += 1
                consecutive_failures = 0
            except Exception:
                consecutive_failures += 1
                time.sleep(0.5)

        return node_symbols

    def get_market_symbols(self) -> List[Tuple[str, str, str]]:
        logger.info("正在获取全市场基础代码清单...")

        # 优先使用 AkShare 静态源
        try:
            df = ak.stock_info_a_code_name()
            if df is not None and len(df) > 4000:
                symbols = []
                for _, row in df.iterrows():
                    pure_code = str(row["code"]).strip().zfill(6)
                    name = str(row["name"]).strip()
                    symbols.append((self._to_full_symbol(pure_code), pure_code, name))
                logger.info(f"成功获取股票列表 (AkShare 静态源): {len(symbols)} 只")
                return symbols
        except Exception:
            pass

        # 降级新浪双节点
        logger.info("降级通过新浪双节点 (沪深+北交所) 分页获取全量代码...")
        symbols_hs = self._fetch_sina_node_with_retry("hs_a")
        symbols_bse = self._fetch_sina_node_with_retry("bse")
        symbols = symbols_hs + symbols_bse

        seen = set()
        dedup_symbols = []
        for s in symbols:
            if s[1] not in seen:
                seen.add(s[1])
                dedup_symbols.append(s)

        if len(dedup_symbols) < 1000:
            raise RuntimeError(f"全市场股票列表拉取异常，仅获得 {len(dedup_symbols)} 只，请检查网络！")

        logger.info(f"代码库就绪，全市场有效股票数: {len(dedup_symbols)} 只")
        return dedup_symbols

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
                resp = self.session.get(url, timeout=self.cfg.REQUEST_TIMEOUT)
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

                    # 分层流动性校验
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

    def run(self):
        start_time = time.time()
        raw_symbols = self.get_market_symbols()
        pool = self.prefilter_pool(raw_symbols)
        if not pool:
            logger.warning("候选池为空，退出。")
            return

        logger.info(f"启动 {self.cfg.MAX_WORKERS} 线程拉取 K 线并执行形态计算...")
        results = []
        fetch_success = 0
        fetch_fail = 0

        def worker_task(item: dict):
            df_kline = self.fetcher.get_kline(item["symbol"])
            if df_kline is None:
                return False, None
            return True, self.engine.evaluate(item["code"], item["name"], df_kline)

        with ThreadPoolExecutor(max_workers=self.cfg.MAX_WORKERS) as executor:
            future_to_stock = {executor.submit(worker_task, item): item for item in pool}
            completed = 0
            for future in as_completed(future_to_stock):
                completed += 1
                if completed % 300 == 0 or completed == len(pool):
                    logger.info(f"计算进度: {completed}/{len(pool)} ({(completed/len(pool)*100):.1f}%)")

                is_ok, res = future.result()
                if is_ok:
                    fetch_success += 1
                else:
                    fetch_fail += 1

                if res:
                    results.append(res)
                    logger.info(
                        f"🎯 [命中] {res['code']} {res['name']} | "
                        f"{res['matched_rule']} | 状态: {res['limit_up_tag']} | "
                        f"涨幅: {res['pct_chg']}% | 量比: {res['vol_ratio']} | 均线: {res['converged_mas']}"
                    )

        elapsed = time.time() - start_time
        logger.info(
            f"扫描完成，总耗时: {elapsed:.2f} 秒 | "
            f"K线拉取成功: {fetch_success} 只, 超时/失败丢弃: {fetch_fail} 只 | "
            f"最终选出: {len(results)} 只标的。"
        )

        if results:
            df_res = pd.DataFrame(results)
            df_res = df_res.sort_values(by=["matched_rule", "pct_chg"], ascending=[True, False])

            print("\n" + "=" * 95)
            print(f" 均线汇聚突破选股结果清单 (共 {len(df_res)} 只)")
            print("=" * 95)
            print(df_res.to_string(index=False))
            print("=" * 95 + "\n")

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            os.makedirs("results", exist_ok=True)

            csv_filename = os.path.join("results", f"ma_converged_{timestamp}.csv")
            df_res.to_csv(csv_filename, index=False, encoding="utf_8_sig")
            logger.info(f"标准分析报表已保存: {csv_filename}")

            txt_filename = os.path.join("results", f"import_to_em_{timestamp}.txt")
            with open(txt_filename, "w", encoding="utf-8") as f:
                for code in df_res["code"]:
                    f.write(f"{code}\n")
            logger.info(f"东方财富一键导入 TXT 码单已保存: {txt_filename}")
        else:
            logger.info("今日全市场未发现满足汇聚突破条件的股票。")


if __name__ == "__main__":
    app = StockScreenerApp(config=ScreenerConfig())
    app.run()