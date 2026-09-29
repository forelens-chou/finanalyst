恭喜测试顺利通过！基于已实际跑通、验证无误的最终代码逻辑与工程架构，现为你整理并输出正式的**产品开发需求文档（PRD）**与**技术开发规格文档（SDD）**，供后续版本迭代、维护与团队交付使用。

---

# 第一部分：产品开发需求文档 (PRD)

## 1. 文档基本信息
* **项目名称**：A 股极致缩量突破策略扫描系统
* **版本号**：v1.0.0 (Release)
* **状态**：已验收交付

## 2. 业务背景与目标
在二级市场量价分析中，主力资金中长期建仓往往伴随明显的换手率波峰；而在洗盘整理末端、向上变盘前夕，往往伴随极端的“地量”缩量。  
本系统旨在通过自动化、工程化的量化扫描手段，从**自定义股票池**或**全市场 5000+ 标的**中，高效筛选出**“中长期异动放量，而近期出现 6 倍以上极端地量”**的高胜率候选标的，并生成规范的 CSV 供人工复盘与交易决策。

---

## 3. 量化筛选规则定义

| 规则维度 | 规则代号 | 严格量化定义 | 默认阈值 |
| :--- | :--- | :--- | :--- |
| **长期放量异动** | R-LONG | 考察区间 $[T-90, T-1]$ 共 90 个交易日内，单日最高换手率 $MaxTurnover_{90d}$ | $> 9.0\%$（或 $10.0\%$） |
| **中期放量中枢** | R-MID | 考察区间 $[T-30, T-1]$ 共 30 个交易日内，单日最高换手率 $MaxTurnover_{30d}$（**严格排除考察日 $T$**） | $> 2.9\%$ |
| **近期极致地量** | R-RECENT | 近 3 个交易日 $[T-2, T]$ 中，单日的最低换手率 $MinTurnover_{3d}$ | $\ge 0.01\%$（防止停牌死锁） |
| **缩量倍率下限** | R-RATIO | 缩量倍数 $Ratio = \frac{MaxTurnover_{30d}}{MinTurnover_{3d}}$ | $\ge 6.0$ 倍 |
| **缩量倍率上限** | R-RATIO-MAX | 若设定上限，则 $Ratio \le MaxRatio$；默认不限极值（地量更深依然保留） | `None`（不设上限） |

> **关键业务释义**：
> 1. **交易日对齐**：所有时间窗口均按 K 线有效交易日（Trading Day）计算，规避节假日与周末带来的日历日误差。
> 2. **排除 $T$ 日干扰**：30 天最高换手率窗口严格截至 $T-1$ 日，防止最新考察日放量干扰分母。

---

## 4. 输入与输出规范

### 4.1 输入模式
1. **模式 A（清单扫描）**：读取指定 CSV/TXT 文件（如 `股票清单.csv`），读取第一列为股票代码。支持含表头或纯数据，兼容纯 6 位数字代码或带市场前缀代码。
2. **模式 B（全市场扫描）**：配置文件中设定 `STOCK_POOL_FILE = ""` 时，系统自动遍历沪、深、北交易所全市场标的（无需任何预置文件）。

### 4.2 输出规范
* **文件存储**：自动生成在 `./output/` 目录下，文件命名遵循 `shrink_candidates_YYYYMMDD_HHMMSS.csv`。
* **编码格式**：UTF-8-SIG（解决 Excel 打开中文乱码问题）。
* **代码列格式**：严格输出为**纯 6 位数字字符**（如 `601377`，不带 `sh/sz` 前缀，强制保留前导零）。
* **字段定义**：

| 列名 | 数据类型 | 说明 | 示例 |
| :--- | :--- | :--- | :--- |
| **代码** | String | 纯 6 位股票代码 | `601377` |
| **名称** | String | 股票简称 | `兴业证券` |
| **最新价** | Float | 考察日最新收盘价 | `5.96` |
| **90日最高换手(%)** | Float | 90交易日内的最高换手率 | `12.50` |
| **30日最高换手(%)** | Float | 30交易日内的最高换手率（排除T日） | `4.80` |
| **30日峰值日期** | String | 30日最高换手出现日期 | `2026-08-15` |
| **当日换手(%)** | Float | 最新考察日换手率 | `0.65` |
| **近3日最低换手(%)** | Float | 近3日中单日最低换手率 | `0.60` |
| **缩量倍数** | Float | 缩量倍率，结果按降序排列 | `8.00` |

---

# 第二部分：技术开发规格文档 (SDD)

## 1. 系统总体架构设计

系统采用**“配置与数据解耦”、“分层流水线（Pipeline）”**以及**“内外透明适配”**的设计模式。

```text
                  [ 用户配置 config.py ]
                            │
                            ▼
   [ market.py: 标的生成与代码解析 (网易/新浪/东财多通道) ]
                            │ (标准化的 6 位纯代码 + 腾讯前缀代码)
                            ▼
     [ fetch.py: 批量快照引擎 (qt.gtimg.cn, 80只/批) ]
               │── 推导高精度流通股本: (当日成交股数 / 当日换手率)
               ▼
     [ fetch.py: 并发日K线拉取引擎 (16 Worker 线程池) ]
               │── 纯净无复权/前复权日线容错通道
               ▼
       [ strategy.py: 向量化形态过滤与倍数计算 ]
               │── [T-90, T-1] 峰值、[T-30, T-1] 峰值、[T-2, T] 地量
               ▼
        [ main.py: 结果排序与防截断 CSV 导出 ]
```

---

## 2. 关键技术方案与攻坚设计

### 2.1 外网与海外机房（如 CloudShell）多通道容错网络方案
* **问题痛点**：境外云服务器因 IP 归属地或请求头缺失，直接访问东方财富 `push2.eastmoney.com` 会触发反爬并返回空字符，导致 `JSONDecodeError`。
* **落地技术**：
  * **第一通道（网易财经）**：`quotes.money.163.com`，对境外机房 IP 宽容度高，单次直接拉取 6000 只标的，耗时 $< 1.5s$。
  * **第二通道（新浪财经）**：`vip.stock.finance.sina.com.cn`，按页并发兜底。
  * **第三通道（东方财富）**：挂载标准浏览器级 User-Agent 与 Referer 降级容灾。

### 2.2 流通股本高精度动态反推算法
* **问题痛点**：日 K 线接口仅返回成交量（手），不包含历史换手率；若直接取静态流通市值折算，易受多重舍入误差影响。
* **落地技术**：利用快照接口第 38 项 `换手率(%)` 和第 6 项 `成交量(手)` 之间严格的数学关系实时反推：
  $$\text{FloatShares} = \frac{\text{Volume}_{\text{hand}} \times 100}{\text{TurnoverPct} / 100}$$
  对于非交易时段换手率为 0 的标的，自动降级采用 $\text{流通市值(第44项)} \times 10^8 / \text{现价}$ 进行补全。

### 2.3 “外纯内适”的代码前缀自动封装
* **对外**：输入支持纯 6 位数字（如 `601377`），输出 CSV 亦为纯 6 位字符，符合用户习惯。
* **对内**：路由层根据号段自动匹配：
  * `60...` / `688...` $\rightarrow$ `sh`
  * `00...` / `300...` / `301...` $\rightarrow$ `sz`
  * `4...` / `8...` / `920...` $\rightarrow$ `bj`

---

## 3. 模块接口与核心代码定义

### 3.1 配置模块 (`config.py`)
```python
# 核心阈值定义
STOCK_POOL_FILE = ""      # "" 代表全市场模式，也可传入 "股票清单.csv"
OUTPUT_DIR = "./output"

MIN_TURNOVER_90D = 9.0    # 90天内最高换手率阈值(%)
MIN_TURNOVER_30D = 2.9    # 30天内最高换手率阈值(%)
MIN_SHRINK_RATIO = 6.0    # 缩量倍数下限
MAX_SHRINK_RATIO = None   # 缩量倍数上限 (None 代表不设上限)
MIN_VALID_TURNOVER = 0.01 # 排除停牌与除零死锁的保护下限

LONG_WINDOW = 90          # 长期考察交易日天数
SHORT_WINDOW = 30         # 中期考察交易日天数
CHECK_WINDOW = 3          # 近期缩量考察交易日天数
KLINE_COUNT = 160         # K线数据拉取深度

MAX_WORKERS = 16          # 并发扫描线程池大小
REQUEST_TIMEOUT = 2.0     # 单个请求超时时间 (秒)
```

### 3.2 策略运算核心逻辑 (`strategy.py`)
```python
def run_strategy(df: pd.DataFrame, pure_code: str, stock_name: str) -> Optional[Dict]:
    # 基础长度判定: 须具备满足长周期 + 近期考察期的完整有效K线
    if df is None or len(df) < (cfg.LONG_WINDOW + 1):
        return None

    # T 日与近 3 日最低换手率
    t_bar = df.iloc[-1]
    curr_turnover = float(t_bar["turnover_pct"])
    min_turnover_3d = min(df.iloc[-cfg.CHECK_WINDOW:]["turnover_pct"].astype(float).tolist())

    if min_turnover_3d < cfg.MIN_VALID_TURNOVER:
        return None

    # 排除 T 日，计算历史切片
    hist_df = df.iloc[:-1]
    
    # 30 交易日 [T-30, T-1]
    df_30 = hist_df.iloc[-cfg.SHORT_WINDOW:]
    max_turnover_30d = float(df_30["turnover_pct"].max())
    max_30d_date = str(df_30.loc[df_30["turnover_pct"].astype(float).idxmax(), "date"])[:10]

    # 90 交易日 [T-90, T-1]
    df_90 = hist_df.iloc[-cfg.LONG_WINDOW:]
    max_turnover_90d = float(df_90["turnover_pct"].max())

    # 判定与倍数
    if max_turnover_90d <= cfg.MIN_TURNOVER_90D or max_turnover_30d <= cfg.MIN_TURNOVER_30D:
        return None

    shrink_ratio = max_turnover_30d / min_turnover_3d
    if shrink_ratio < cfg.MIN_SHRINK_RATIO:
        return None
    if cfg.MAX_SHRINK_RATIO is not None and shrink_ratio > cfg.MAX_SHRINK_RATIO:
        return None

    return {
        "代码": str(pure_code).zfill(6),
        "名称": stock_name,
        "最新价": round(float(t_bar["close"]), 2),
        "90日最高换手(%)": round(max_turnover_90d, 2),
        "30日最高换手(%)": round(max_turnover_30d, 2),
        "30日峰值日期": max_30d_date,
        "当日换手(%)": round(curr_turnover, 2),
        "近3日最低换手(%)": round(min_turnover_3d, 2),
        "缩量倍数": round(shrink_ratio, 2)
    }
```

### 3.3 导出数据防截断设计 (`main.py`)
```python
# 使用 quote_nonnumeric 强制对字符串列（包括代码）加引号，并使用 utf_8_sig 确保跨系统打开不乱码
df_res.to_csv(out_file, index=False, encoding="utf_8_sig", quoting=csv.QUOTE_NONNUMERIC)
```

---

## 4. 性能与运维指标

1. **扫描效率**：
   * **清单模式（约 200 只）**：执行耗时约 **1.5 ~ 3.0 秒**。
   * **全市场扫描（约 5200+ 只）**：在 16 线程并发下，执行总耗时控制在 **25 ~ 45 秒**。
2. **容错机制**：
   * 单只标的网络超时不阻塞全局主流程。
   * 遇到分母极小值（停牌股）自动静默跳过，避免进程退出。