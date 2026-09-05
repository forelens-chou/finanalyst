# build_stock_list.py
import os
import requests
import pandas as pd
from concurrent.futures import ThreadPoolExecutor

OUTPUT_FILE = "all_stocks.csv"

# A 股常见的有效代码段前缀
PREFIXES = [
    # 沪市主板 & 科创板
    *[f"sh600{i:03d}" for i in range(1000)],
    *[f"sh601{i:03d}" for i in range(1000)],
    *[f"sh603{i:03d}" for i in range(1000)],
    *[f"sh605{i:03d}" for i in range(1000)],
    *[f"sh688{i:03d}" for i in range(800)],
    # 深市主板 & 创业板
    *[f"sz000{i:03d}" for i in range(1000)],
    *[f"sz001{i:03d}" for i in range(400)],
    *[f"sz002{i:03d}" for i in range(1000)],
    *[f"sz003{i:03d}" for i in range(100)],
    *[f"sz300{i:03d}" for i in range(1000)],
    *[f"sz301{i:03d}" for i in range(600)],
]

def check_batch(batch_codes):
    """通过腾讯极速批量接口查询代码是否存在"""
    query_str = ",".join([f"s_{c}" for c in batch_codes])
    url = f"http://qt.gtimg.cn/q={query_str}"
    headers = {"User-Agent": "Mozilla/5.0"}
    valid_stocks = []
    
    try:
        resp = requests.get(url, headers=headers, timeout=4)
        if resp.status_code == 200:
            lines = resp.text.split(";\n")
            for line in lines:
                if "~" in line:
                    parts = line.split("~")
                    if len(parts) > 2:
                        name = parts[1].strip()
                        code = parts[2].strip()
                        # 过滤无效代码和停牌退市标记
                        if name and code and not any(x in name for x in ["ST", "退", "PT"]):
                            valid_stocks.append({'代码': code, '名称': name})
    except Exception:
        pass
    return valid_stocks

def main():
    print(f"-> 正在利用腾讯全球直连通道，扫描并生成全 A 股清单...")
    batch_size = 80
    batches = [PREFIXES[i:i + batch_size] for i in range(0, len(PREFIXES), batch_size)]
    
    all_results = []
    completed = 0
    total = len(batches)

    # 10 线程极速并发探测
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(check_batch, b) for b in batches]
        for f in futures:
            res = f.result()
            all_results.extend(res)
            completed += 1
            if completed % 15 == 0 or completed == total:
                print(f"   进度: [{completed}/{total}] | 已找到有效标的: {len(all_results)} 只")

    df = pd.DataFrame(all_results).drop_duplicates(subset=['代码']).sort_values('代码').reset_index(drop=True)
    df.to_csv(OUTPUT_FILE, index=False, encoding='utf-8-sig')
    print(f"\n★ 成功！已生成本地全 A 股清单: {OUTPUT_FILE} (共 {len(df)} 只正常交易个股)")

if __name__ == "__main__":
    main()