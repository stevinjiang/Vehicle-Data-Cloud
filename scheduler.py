# ============================================================
# scheduler.py — 定时任务调度模块
# 功能：按 config.yaml 中的 schedule.cron 配置定时执行数据拉取+分析
#
# 设计思路：
#   1. 使用 schedule 库的轻量级定时器
#   2. 启动时可选立即执行一次（run_on_start）
#   3. 支持优雅退出（Ctrl+C 停止调度循环）
#   4. 每次执行记录日志 + 历史报告保留
# ============================================================

import time
import signal
import sys
from datetime import datetime
from typing import Callable, Optional

import schedule
from loguru import logger


class TaskScheduler:
    """
    定时任务调度器

    使用示例：
      scheduler = TaskScheduler()
      scheduler.schedule_cron("0 6 * * *", my_task_function, run_on_start=True)
      scheduler.run()   # 阻塞运行，直到 Ctrl+C
    """

    def __init__(self):
        """初始化调度器，注册 SIGINT 信号处理"""
        self._running = True
        self._jobs = []
        # 注册信号处理器，让 Ctrl+C 优雅退出
        signal.signal(signal.SIGINT, self._handle_sigint)
        signal.signal(signal.SIGTERM, self._handle_sigint)

    def _handle_sigint(self, signum, frame):
        """处理 Ctrl+C 信号"""
        logger.info("[Scheduler] 收到停止信号，正在关闭...")
        self._running = False
        sys.exit(0)

    def schedule_cron(self, cron_expr: str, task: Callable,
                      run_on_start: bool = False, description: str = ""):
        """
        注册一个 cron 定时任务

        schedule 库支持的标准 cron 字段:
          - every().day.at("06:00")       每天 6:00
          - every().monday.at("09:00")    每周一 9:00
          - every(4).hours                每 4 小时
          - every(30).minutes             每 30 分钟

        这里我们解析简化的 cron 表达式（仅支持常用格式）：
          - "分 时 * * *" — 每天定时
          - "分 时 * * 星期" — 每周定时

        Args:
            cron_expr: cron 字符串，格式 "分 时 * * *"
            task: 要执行的任务函数（无参数）
            run_on_start: 是否在注册后立即执行一次
            description: 任务描述（日志用）
        """
        self._parse_cron(cron_expr, task)

        logger.info(f"[Scheduler] 已注册定时任务: {description or task.__name__}, "
                     f"cron={cron_expr}")

        # 如果配置了 run_on_start，立即执行一次
        if run_on_start:
            logger.info(f"[Scheduler] 立即执行首次任务...")
            try:
                task()
            except Exception as e:
                logger.error(f"[Scheduler] 首次执行失败: {e}")

    def _parse_cron(self, cron_expr: str, task: Callable):
        """
        解析 cron 表达式并注册到 schedule 库

        支持的格式：
          - "0 6 * * *"    → 每天 6:00
          - "0 9 * * 1"    → 每周一 9:00
          - "0 9 * * 1-5"  → 工作日 9:00
          - "0 */4 * * *"  → 每 4 小时（不支持，用 "" 表示）

        对于不支持的格式，fallback 到 every(6).hours

        Args:
            cron_expr: cron 表达式字符串
            task: 任务函数
        """
        parts = cron_expr.strip().split()
        if len(parts) != 5:
            logger.error(f"[Scheduler] 无效的 cron 表达式: {cron_expr}")
            # 默认每天 6:00
            schedule.every().day.at("06:00").do(task)
            return

        minute, hour, day, month, weekday = parts

        # ── 每天定时 ──
        if day == "*" and month == "*" and weekday == "*":
            if "/" in hour:
                # "*/4" 格式 — schedule 不支持，用 every(n).hours 替代
                interval = int(hour.replace("*/", ""))
                schedule.every(interval).hours.do(task)
            else:
                time_str = f"{hour.zfill(2)}:{minute.zfill(2)}"
                schedule.every().day.at(time_str).do(task)

        # ── 每周定时 ──
        elif weekday != "*" and day == "*" and month == "*":
            time_str = f"{hour.zfill(2)}:{minute.zfill(2)}"
            if weekday == "1":
                schedule.every().monday.at(time_str).do(task)
            elif weekday == "2":
                schedule.every().tuesday.at(time_str).do(task)
            elif weekday == "3":
                schedule.every().wednesday.at(time_str).do(task)
            elif weekday == "4":
                schedule.every().thursday.at(time_str).do(task)
            elif weekday == "5":
                schedule.every().friday.at(time_str).do(task)
            elif weekday == "6":
                schedule.every().saturday.at(time_str).do(task)
            elif weekday == "0" or weekday == "7":
                schedule.every().sunday.at(time_str).do(task)
            else:
                logger.warning(f"[Scheduler] 不支持的星期格式: {weekday}，改为每天 {time_str}")
                schedule.every().day.at(time_str).do(task)

        # ── 每月定时 ──
        elif day != "*" and month == "*":
            logger.warning(f"[Scheduler] 每月定时暂不支持，改为每天定时")
            time_str = f"{hour.zfill(2)}:{minute.zfill(2)}"
            schedule.every().day.at(time_str).do(task)

        # ── Fallback ──
        else:
            logger.warning(f"[Scheduler] 无法解析 cron: {cron_expr}，使用默认每天 6:00")
            schedule.every().day.at("06:00").do(task)

    def run(self):
        """
        启动调度循环（阻塞运行）

        主循环每 1 秒检查一次是否有任务到期
        收到 Ctrl+C 退出
        """
        logger.info("[Scheduler] 调度器启动，等待任务触发...")
        while self._running:
            schedule.run_pending()
            time.sleep(1)

    def stop(self):
        """停止调度器"""
        self._running = False
        logger.info("[Scheduler] 调度器已停止")

    def run_once(self, task: Callable, description: str = ""):
        """
        立即执行一次任务（不需要调度）

        Args:
            task: 任务函数
            description: 描述
        """
        logger.info(f"[Scheduler] 手动执行: {description or task.__name__}")
        try:
            task()
            logger.info(f"[Scheduler] 任务完成")
        except Exception as e:
            logger.error(f"[Scheduler] 任务失败: {e}")
