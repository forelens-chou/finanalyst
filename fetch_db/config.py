import os
from pathlib import Path

# 项目根目录
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# SQLite 数据库文件路径
DB_PATH = DATA_DIR / "stock_data.db"

class Config:
    # 爬虫与并发配置
    MAX_WORKERS: int = 16          # 同步 K 线时的线程数
    REQUEST_TIMEOUT: float = 3.0   # 请求超时时间（秒）
    MIN_AMOUNT: float = 10000000.0 # 预筛选成交额门槛（1000万元）
    DEFAULT_KLINE_LEN: int = 320   # 首次建仓拉取历史天数

cfg = Config()