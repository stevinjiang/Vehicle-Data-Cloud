# ============================================================
# main.py — 车云大数据平台 主入口
# 功能：编排整个数据拉取→处理→分析→报告生成流程
#
# 运行方式：
#   # 单次执行
#   python main.py --once
#
#   # 定时调度模式（按 config.yaml 中的 schedule.cron 定时执行）
#   python main.py --schedule
#
#   # 指定配置文件
#   python main.py --config my_config.yaml --once
#
# 完整数据流：
#   内网CSV → DataFetcher (下载)
#          → DataLoader (清洗+校验)
#          → Classifier (分类汇总)
#          → RiskAnalyzer (风险分析+预警)
#          → ReportGenerator (生成报告)
# ============================================================

import argparse
import sys
from pathlib import Path

import yaml
from loguru import logger

from data_fetcher import DataFetcher
from data_loader import DataLoader
from risk_analyzer import RiskAnalyzer
from report_generator import ReportGenerator
from scheduler import TaskScheduler


# ──────────────────────────────
#  配置加载
# ──────────────────────────────

def load_config(config_path: str = "config.yaml") -> dict:
    """
    从 YAML 文件加载配置

    Args:
        config_path: 配置文件路径

    Returns:
        解析后的配置字典

    Raises:
        FileNotFoundError: 配置文件不存在
        yaml.YAMLError: 配置文件语法错误
    """
    config_file = Path(config_path)
    if not config_file.exists():
        logger.error(f"配置文件不存在: {config_path}")
        raise FileNotFoundError(f"配置文件不存在: {config_path}")

    with open(config_file, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    logger.info(f"配置加载成功: {config_path}")
    return config


# ──────────────────────────────
#  日志初始化
# ──────────────────────────────

def setup_logging(config: dict):
    """
    初始化 loguru 日志系统

    同时输出到：
      1. 控制台（彩色）
      2. 日志文件（按天轮转，保留 30 天）

    Args:
        config: 配置字典
    """
    paths = config.get("paths", {})
    log_dir = Path(paths.get("log_dir", "./logs"))
    log_dir.mkdir(parents=True, exist_ok=True)

    # 移除默认 handler
    logger.remove()

    # 控制台输出（INFO 级别以上）
    logger.add(
        sys.stderr,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
        level="INFO",
        colorize=True,
    )

    # 文件输出（DEBUG 级别，完整日志）
    logger.add(
        log_dir / "vehicle_cloud_{time:YYYY-MM-DD}.log",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} | {message}",
        level="DEBUG",
        rotation="00:00",     # 每天午夜轮转
        retention="30 days",  # 保留 30 天
        encoding="utf-8",
    )

    logger.info(f"日志系统初始化完成，日志目录: {log_dir}")


# ──────────────────────────────
#  核心流水线
# ──────────────────────────────

def run_pipeline(config: dict):
    """
    执行完整的数据分析流水线（单次）

    步骤：
      1. 拉取数据 — DataFetcher 从内网下载 CSV
      2. 加载清洗 — DataLoader 解析 CSV → FaultRecord 列表
      3. 风险分析 — RiskAnalyzer 分析 → SummaryReport
      4. 生成报告 — ReportGenerator 输出 HTML/MD/JSON/Excel

    Args:
        config: 配置字典

    Returns:
        成功返回 True，失败返回 False
    """
    logger.info("=" * 60)
    logger.info("🚀 车辆故障数据分析流水线启动")
    logger.info("=" * 60)

    try:
        # ── 步骤 1：拉取数据 ──
        logger.info("📥 [1/4] 拉取数据...")
        fetcher = DataFetcher(config)
        csv_path = fetcher.fetch()
        if csv_path is None:
            logger.error("❌ 数据拉取失败，流水线终止")
            return False

        # ── 步骤 2：加载 + 清洗 ──
        logger.info("📋 [2/4] 加载并清洗数据...")
        loader = DataLoader(config)
        records = loader.load(csv_path)
        if not records:
            logger.error("❌ 无有效故障记录，流水线终止")
            return False
        logger.info(f"✅ 有效故障记录: {len(records)} 条")

        # ── 步骤 3：风险分析 ──
        logger.info("🔍 [3/4] 执行风险分析...")
        analyzer = RiskAnalyzer(config)
        report = analyzer.analyze(records)
        logger.info(f"✅ 分析完成: "
                     f"车辆={report.total_vehicles}, "
                     f"高危={report.high_risk_count}")

        # ── 步骤 4：生成报告 ──
        logger.info("📄 [4/4] 生成报告...")
        gen = ReportGenerator(config)
        # 获取车辆画像（报告生成需要）
        profiles = analyzer.classifier.build_vehicle_profiles(records)
        report_path = gen.generate(report, profiles, records)
        logger.info(f"✅ 报告已生成: {report_path}")

        logger.info("=" * 60)
        logger.info("🎉 流水线执行完毕")
        logger.info("=" * 60)
        return True

    except Exception as e:
        logger.exception(f"❌ 流水线执行异常: {e}")
        return False


# ──────────────────────────────
#  CLI 入口
# ──────────────────────────────

def main():
    """
    CLI 主入口 — 解析命令行参数并执行相应模式

    用法:
      python main.py --once              单次执行
      python main.py --schedule          定时调度模式
      python main.py                     默认单次执行
    """
    parser = argparse.ArgumentParser(
        description="车云大数据平台 — 车辆故障数据分析系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--config", "-c",
        default="config.yaml",
        help="配置文件路径 (默认: config.yaml)"
    )
    parser.add_argument(
        "--once", "-o",
        action="store_true",
        default=True,
        help="单次执行分析流水线 (默认)"
    )
    parser.add_argument(
        "--schedule", "-s",
        action="store_true",
        default=False,
        help="启动定时调度模式，按 config.yaml 中 schedule.cron 定时执行"
    )

    args = parser.parse_args()

    # ── 加载配置 + 初始化日志 ──
    try:
        config = load_config(args.config)
    except FileNotFoundError:
        logger.error("请确保 config.yaml 文件存在于当前目录")
        sys.exit(1)
    except yaml.YAMLError as e:
        logger.error(f"配置文件格式错误: {e}")
        sys.exit(1)

    setup_logging(config)

    # ── 单次执行模式 ──
    if args.once and not args.schedule:
        logger.info("运行模式: 单次执行")
        success = run_pipeline(config)
        sys.exit(0 if success else 1)

    # ── 定时调度模式 ──
    elif args.schedule:
        logger.info("运行模式: 定时调度")
        schedule_cfg = config.get("schedule", {})
        cron_expr = schedule_cfg.get("cron", "0 6 * * *")
        run_on_start = schedule_cfg.get("run_on_start", True)

        scheduler = TaskScheduler()
        # 将 run_pipeline 包装为无参数函数
        task = lambda: run_pipeline(config)
        scheduler.schedule_cron(
            cron_expr, task,
            run_on_start=run_on_start,
            description="车辆故障数据分析"
        )
        logger.info(f"⏰ 调度器启动: {cron_expr}，按 Ctrl+C 退出")
        scheduler.run()


if __name__ == "__main__":
    main()
