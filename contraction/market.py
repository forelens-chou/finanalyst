"""
market.py - 股票代码处理与多通道全市场代码池管理
已适配境外云服务器 (CloudShell / 海外机房) 与国内环境
"""
import re
import os
import json
import requests
import pandas as pd
from typing import List, Tuple
import config as cfg

# 模拟真实浏览器请求头，避免被反爬阻断
COMMON_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://finance.sina.com.cn/"
}

def clean_code(val: str) -> str:
    """提取标准纯6位股票代码（剔除非数字字符，补齐前置零）"""
    digits = re.sub(r'\D', '', str(val).strip())
    return digits.zfill(6)

def to_tencent_symbol(code: str) -> str:
    """
    根据纯6位代码，内部自动补全腾讯接口所需的交易所前缀
    60/688 -> sh; 00/300/301 -> sz; 4/8/920 -> bj
    """
    code = clean_code(code)
    if code.startswith(('60', '688')):
        return f"sh{code}"
    elif code.startswith(('00', '300', '301')):
        return f"sz{code}"
    elif code.startswith(('4', '8', '920')):
        return f"bj{code}"
    return f"sz{code}"

def _fetch_all_from_netease() -> List[str]:
    """通道1: 网易财经接口 (对境外海外IP最友好，不拦截机房)"""
    codes = []
    # 沪深A股+北交所全量清单接口
    url = "https://quotes.money.163.com/hs/service/diyrank.php?host=http%3A%2F%2Fquotes.money.163.com%2Fhs%2Fservice%2Fdiyrank.php&page=0&query=STYPE%3AEQA&fields=SYMBOL&count=6000&type=query"
    resp = requests.get(url, headers=COMMON_HEADERS, timeout=10.0)
    if resp.status_code == 200 and resp.text.strip():
        data = resp.json().get("list", [])
        for item in data:
            c = clean_code(item.get("SYMBOL", ""))
            if len(c) == 6:
                codes.append(c)
    return codes

def _fetch_all_from_sina() -> List[str]:
    """通道2: 新浪财经全市场接口"""
    codes = []
    for page in range(1, 60):  # 约5000+只，每页100只
        url = f"https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData?page={page}&num=100&sort=symbol&asc=1&node=hs_a&symbol=&_s_r_a=init"
        try:
            resp = requests.get(url, headers=COMMON_HEADERS, timeout=5.0)
            if resp.status_code == 200 and resp.text.strip():
                text = resp.text.strip()
                if text == "null" or text == "[]":
                    break
                items = json.loads(text)
                if not items:
                    break
                for it in items:
                    c = clean_code(it.get("symbol", ""))
                    if len(c) == 6:
                        codes.append(c)
            else:
                break
        except Exception:
            break
    return codes

def _fetch_all_from_eastmoney() -> List[str]:
    """通道3: 东方财富接口（补充请求头）"""
    codes = []
    url = "https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=6000&po=1&np=1&ut=bd1d9d11&fltt=2&invt=2&fid=f3&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048&fields=f12"
    resp = requests.get(url, headers=COMMON_HEADERS, timeout=8.0)
    if resp.status_code == 200 and resp.text.strip():
        data = resp.json().get("data", {}).get("diff", [])
        for item in data:
            c = clean_code(item.get("f12", ""))
            if len(c) == 6:
                codes.append(c)
    return codes

def load_stock_targets() -> List[Tuple[str, str]]:
    """
    获取待检测的股票列表
    返回: [(pure_code, tencent_symbol), ...]
    """
    targets = []
    file_path = cfg.STOCK_POOL_FILE

    # ---------------- 模式 1: 从指定文件读取 ----------------
    if file_path and os.path.exists(file_path):
        print(f"[*] 正在从输入文件加载股票清单: {file_path}")
        try:
            df = pd.read_csv(file_path, header=None, dtype=str, sep=None, engine='python')
            raw_codes = df.iloc[:, 0].dropna().tolist()
            if raw_codes and not re.search(r'\d', raw_codes[0]):
                raw_codes = raw_codes[1:]  # 跳过文字表头

            for r in raw_codes:
                p_code = clean_code(r)
                if len(p_code) == 6:
                    targets.append((p_code, to_tencent_symbol(p_code)))

            targets = list(dict.fromkeys(targets))
            print(f"[+] 成功从文件加载 {len(targets)} 只标的")
            return targets
        except Exception as e:
            print(f"[!] 读取股票清单文件异常: {e}，正在切换至全市场扫描...")

    # ---------------- 模式 2: 全市场自动扫描（多通道容错） ----------------
    print("[*] 正在拉取 A 股全市场代码清单 (启用多通道容错)...")
    raw_codes = []

    # 尝试通道 1: 网易
    try:
        raw_codes = _fetch_all_from_netease()
        if raw_codes:
            print(f"[+] [通道1-网易] 成功获取 {len(raw_codes)} 只标的代码")
    except Exception as e:
        print(f"[-] [通道1-网易] 获取失败: {e}，尝试备用通道...")

    # 尝试通道 2: 新浪
    if not raw_codes:
        try:
            raw_codes = _fetch_all_from_sina()
            if raw_codes:
                print(f"[+] [通道2-新浪] 成功获取 {len(raw_codes)} 只标的代码")
        except Exception as e:
            print(f"[-] [通道2-新浪] 获取失败: {e}，尝试备用通道...")

    # 尝试通道 3: 东方财富
    if not raw_codes:
        try:
            raw_codes = _fetch_all_from_eastmoney()
            if raw_codes:
                print(f"[+] [通道3-东财] 成功获取 {len(raw_codes)} 只标的代码")
        except Exception as e:
            print(f"[-] [通道3-东财] 获取失败: {e}")

    # 组装返回列表
    for c in list(dict.fromkeys(raw_codes)):
        targets.append((c, to_tencent_symbol(c)))

    if not targets:
        print("[!] 错误: 所有全市场接口均被拦截，请检查机器外网连通性或提供 '股票清单.csv'。")
    else:
        print(f"[+] 全市场准备就绪，共计 {len(targets)} 只标的进入筛选管道")

    return targets