# Vehicle-Data-Cloud 🚗☁️

车云大数据平台 — 车辆故障数据自动拉取、分类分析、风险预警与报告生成系统。

## 项目结构

```
Vehicle-Data-Cloud/
├── main.py              # ⭐ 主入口 — 编排整个流水线
├── models.py            # 数据模型定义 (FaultRecord, VehicleProfile, TopIssue 等)
├── data_fetcher.py      # 数据拉取 — 从内网下载 CSV，支持重试和多源切换
├── data_loader.py       # 数据加载 — CSV 解析、编码检测、清洗校验
├── classifier.py        # 分类汇总 — 按故障码/等级/版本/地区多维度分类
├── risk_analyzer.py     # 风险分析 — 高危识别、预警、TOP N 排行
├── report_generator.py  # 报告生成 — HTML/Markdown/JSON/Excel 多格式输出
├── scheduler.py         # 定时调度 — cron 表达式定时执行
├── config.yaml          # 配置文件 — 所有参数集中管理
├── sample_data.py       # 样本数据生成器（开发测试用）
├── requirements.txt     # Python 依赖
├── data/
│   ├── raw/             # 原始 CSV 下载存放
│   └── processed/       # 处理后的干净数据
├── reports/             # 生成的报告输出
└── logs/                # 日志文件
```

## 数据流

```
内网CSV  →  DataFetcher  →  DataLoader  →  Classifier  →  RiskAnalyzer  →  ReportGenerator
 下载        清洗+校验       分类汇总       风险分析           生成报告
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt --break-system-packages
```

### 2. 生成测试数据

```bash
python sample_data.py
```

### 3. 修改配置（指向你的内网地址）

编辑 `config.yaml`，修改 `data_source.urls` 为你的内网 CSV 地址：

```yaml
data_source:
  urls:
    - "http://your-internal-server/data/vehicle_data.csv"
```

### 4. 单次执行

```bash
python main.py --once
```

### 5. 定时执行

```bash
python main.py --schedule
```

默认每天早上 6:00 执行（可在 `config.yaml` 的 `schedule.cron` 中修改）。

## 核心功能

| 功能 | 说明 |
|------|------|
| 自动拉取 | 定时从内网拉取 CSV，支持多源 + 认证 + 重试 |
| 数据清洗 | 自动检测编码、列名映射、VIN 校验、日期解析 |
| 分类汇总 | 按故障等级/故障码/软件版本/地区多维度统计 |
| 风险分析 | 风险评分 → 高危/中危/低危分级，多条件预警 |
| TOP 排行 | TOP N 高频问题 + TOP N 高风险车辆 |
| 报告生成 | HTML（带样式）/ Markdown（推送）/ JSON / Excel |

## 配置说明

所有参数在 `config.yaml` 中集中管理：

- `data_source` — 数据源 URL、认证方式
- `paths` — 数据/报告/日志目录
- `column_mapping` — CSV 列名映射（中文→标准名）
- `risk_rules` — 风险判定规则（权重、阈值、版本风险）
- `top_n` — 排行榜配置
- `schedule` — 定时任务配置
- `report` — 报告输出配置

## 开发分支

当前在功能分支上开发（不合并 main），开发完成后用 PR 合并。
