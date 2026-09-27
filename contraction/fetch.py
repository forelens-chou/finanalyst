"""
fetch.py - 极速行情抓取与多通道 K 线解析
"""
import re
import json
import requests
from typing import List, Dict, Optional
import pandas as pd
import config as cfg

class DataFetcher:
    def __init__(self):
        self.session = requests.Session()
        # 伪装常用浏览器 UA，保障接口稳定访问
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })

    def fetch_snapshots(self, symbols: List[str]) -> Dict[str, Dict]:
        """
        分批获取股票实时快照
        返回格式: {symbol: {"name": str, "price": float, "float_shares": float}}
        """
        snapshots = {}
        batch_size = cfg.SNAPSHOT_BATCH_SIZE

        for i in range(0, len(symbols), batch_size):
            chunk = symbols[i : i + batch_size]
            q_str = ",".join(chunk)
            url = f"https://qt.gtimg.cn/q={q_str}"
            try:
                resp = self.session.get(url, timeout=cfg.REQUEST_TIMEOUT)
                if resp.status_code == 200:
                    text = resp.text
                    lines = text.strip().split(";")
                    for line in lines:
                        if not line or "~" not in line:
                            continue
                        parts = line.split("~")
                        if len(parts) > 45:
                            s_code = line.split("=")[0].replace("v_", "").strip()
                            name = parts[1]
                            price = float(parts[3]) if parts[3] else 0.0
                            today_turnover = float(parts[38]) if parts[38] else 0.0
                            vol_hand = float(parts[6]) if parts[6] else 0.0 # 成交量(手)
                            
                            # 核心技巧: 利用 当日成交股数 / (换手率/100) 推导高精度流通股本
                            float_shares = 0.0
                            if today_turnover > 0 and vol_hand > 0:
                                float_shares = (vol_hand * 100.0) / (today_turnover / 100.0)
                            else:
                                # 备用方案: 快照第44项为流通市值(亿元)
                                circ_val_yi = float(parts[44]) if parts[44] else 0.0
                                if circ_val_yi > 0 and price > 0:
                                    float_shares = (circ_val_yi * 1e8) / price

                            snapshots[s_code] = {
                                "name": name,
                                "price": price,
                                "float_shares": float_shares
                            }
            except Exception:
                continue

        return snapshots

    def fetch_kline(self, symbol: str, float_shares: float) -> Optional[pd.DataFrame]:
        """
        抓取单只股票的历史日K线，并按流通股本换算每根K线的换手率
        """
        symbol_lower = symbol.lower()

        # 通道 1: 腾讯纯净稳定日线
        try:
            url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={symbol_lower},day,,,{cfg.KLINE_COUNT}"
            resp = self.session.get(url, timeout=cfg.REQUEST_TIMEOUT)
            if resp.status_code == 200:
                data = resp.json().get("data", {}).get(symbol_lower, {})
                raw_bars = data.get("day", [])
                
                # 容错降级读取
                if not raw_bars:
                    for k in ["qfqday", "hfqday"]:
                        if isinstance(data.get(k), list) and len(data.get(k)) > 0:
                            raw_bars = data.get(k)
                            break

                if isinstance(raw_bars, list) and len(raw_bars) >= (cfg.LONG_WINDOW + cfg.CHECK_WINDOW):
                    rows = []
                    for b in raw_bars:
                        if not isinstance(b, list) or len(b) < 6:
                            continue
                        vol = float(b[5]) * 100.0  # 手转股数
                        # 计算单日换手率
                        turnover_pct = (vol / float_shares * 100.0) if float_shares > 0 else 0.0
                        rows.append({
                            "date": b[0],
                            "open": float(b[1]),
                            "close": float(b[2]),
                            "high": float(b[3]),
                            "low": float(b[4]),
                            "volume": vol,
                            "turnover_pct": turnover_pct
                        })

                    if len(rows) >= (cfg.LONG_WINDOW + cfg.CHECK_WINDOW):
                        df = pd.DataFrame(rows)
                        df["date"] = pd.to_datetime(df["date"])
                        return df.sort_values("date").reset_index(drop=True)
        except Exception:
            pass

        # 通道 2: 新浪 PC 接口兜底
        try:
            url = f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={symbol_lower}&scale=240&ma=no&datalen={cfg.KLINE_COUNT}"
            resp = self.session.get(url, timeout=cfg.REQUEST_TIMEOUT)
            if resp.status_code == 200:
                text = resp.text.strip()
                if text.startswith("var"):
                    text = text[text.find("=") + 1 :].rstrip(";")
                raw_bars = json.loads(text)
                if isinstance(raw_bars, list) and len(raw_bars) >= (cfg.LONG_WINDOW + cfg.CHECK_WINDOW):
                    rows = []
                    for b in raw_bars:
                        vol = float(b.get("volume", 0))
                        turnover_pct = (vol / float_shares * 100.0) if float_shares > 0 else 0.0
                        rows.append({
                            "date": b["day"],
                            "open": float(b["open"]),
                            "close": float(b["close"]),
                            "high": float(b["high"]),
                            "low": float(b["low"]),
                            "volume": vol,
                            "turnover_pct": turnover_pct
                        })
                    if len(rows) >= (cfg.LONG_WINDOW + cfg.CHECK_WINDOW):
                        df = pd.DataFrame(rows)
                        df["date"] = pd.to_datetime(df["date"])
                        return df.sort_values("date").reset_index(drop=True)
        except Exception:
            pass

        return None