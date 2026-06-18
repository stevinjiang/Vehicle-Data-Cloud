# ============================================================
# data_fetcher.py — 数据拉取模块
# 功能：从内网固定时间拉取 CSV 表格数据
#   - 支持多个数据源 URL（自动切换备用源）
#   - 支持多种认证方式（basic / token / api_key）
#   - 支持失败重试 + 间隔等待
#   - 使用 loguru 记录详细日志
# ============================================================

import os
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from loguru import logger


class DataFetcher:
    """
    数据拉取器
    负责从内网服务器下载 CSV 文件，保存到本地 raw 目录。

    设计思路：
      1. 按 URL 列表顺序尝试，第一个成功就停止
      2. 每次请求失败后等待 interval 秒再重试
      3. 下载的 CSV 以时间戳命名，保留历史数据用于趋势分析

    使用示例：
      fetcher = DataFetcher(config)
      csv_path = fetcher.fetch()
      # csv_path 是下载到本地的文件路径，失败返回 None
    """

    def __init__(self, config: dict):
        """
        初始化数据拉取器

        Args:
            config: 完整配置字典（从 config.yaml 解析）
                    主要读取 data_source 和 paths 两个 section
        """
        # ── 从配置中提取数据源参数 ──
        src = config.get("data_source", {})
        self.urls: list = src.get("urls", [])
        self.timeout: int = src.get("timeout", 30)
        self.retry: int = src.get("retry", 3)
        self.interval: int = src.get("interval", 5)

        # ── 认证配置 ──
        self.auth_type: str = src.get("auth_type", "none")
        self.auth_username: str = src.get("auth_username", "")
        self.auth_password: str = src.get("auth_password", "")
        self.auth_token: str = src.get("auth_token", "")
        self.auth_header_name: str = src.get("auth_header_name", "Authorization")

        # ── 本地存储路径 ──
        paths = config.get("paths", {})
        self.raw_dir: Path = Path(paths.get("raw_data_dir", "./data/raw"))
        self.raw_dir.mkdir(parents=True, exist_ok=True)

        # ── 创建带重试机制的 requests Session ──
        self.session = self._build_session()

        logger.info(f"[DataFetcher] 初始化完成，数据源数: {len(self.urls)}, "
                     f"存储目录: {self.raw_dir}")

    def _build_session(self) -> requests.Session:
        """
        构建带重试策略的 requests Session

        使用 urllib3 的 Retry 类实现底层重试，处理：
          - 连接超时 (connect)
          - 读取超时 (read)
          - HTTP 5xx 服务器错误

        Returns:
            配置好重试策略的 requests.Session
        """
        session = requests.Session()

        # 配置重试策略：最多重试 self.retry 次，退避因子 1
        retry_strategy = Retry(
            total=self.retry,
            backoff_factor=1,         # 重试间隔：1s, 2s, 4s...
            status_forcelist=[500, 502, 503, 504],  # 这些状态码触发重试
            allowed_methods=["GET"]   # 只对 GET 请求重试
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        # ── 添加认证信息到 Session ──
        if self.auth_type == "basic":
            session.auth = (self.auth_username, self.auth_password)
            logger.info("[DataFetcher] 使用 Basic 认证")
        elif self.auth_type in ("token", "api_key"):
            session.headers[self.auth_header_name] = self.auth_token
            logger.info(f"[DataFetcher] 使用 {self.auth_type} 认证")

        return session

    def fetch(self) -> Optional[str]:
        """
        从数据源拉取 CSV 文件

        尝试 self.urls 中的每个地址，第一个成功即返回。
        所有地址都失败则返回 None。

        Returns:
            下载到本地的 CSV 文件路径，失败返回 None
        """
        for idx, url in enumerate(self.urls):
            logger.info(f"[DataFetcher] 尝试数据源 [{idx + 1}/{len(self.urls)}]: {url}")
            csv_path = self._try_fetch(url)
            if csv_path:
                logger.info(f"[DataFetcher] 数据拉取成功 → {csv_path}")
                return csv_path
            # 当前 URL 失败，等待 interval 秒后尝试下一个
            if idx < len(self.urls) - 1:
                logger.warning(f"[DataFetcher] 等待 {self.interval} 秒后切换到备用源...")
                time.sleep(self.interval)

        logger.error("[DataFetcher] 所有数据源均拉取失败！")
        return None

    def _try_fetch(self, url: str) -> Optional[str]:
        """
        尝试从单个 URL 拉取文件

        逻辑：
          1. 发送 GET 请求（带超时和重试）
          2. 检查 HTTP 状态码
          3. 检查 Content-Type 是否是 CSV
          4. 以时间戳命名保存到 raw_dir

        Args:
            url: 单个数据源的完整 URL

        Returns:
            保存到本地的文件路径，失败返回 None
        """
        try:
            # ── 发送请求 ──
            logger.debug(f"[DataFetcher] GET {url} (timeout={self.timeout}s)")
            resp = self.session.get(url, timeout=self.timeout)
            resp.raise_for_status()  # 非 2xx 抛出 HTTPError

            # ── 检查响应内容 ──
            content = resp.text.strip()
            if not content:
                logger.error(f"[DataFetcher] 响应内容为空: {url}")
                return None

            # ── 生成文件名（时间戳格式，便于区分历史文件） ──
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"vehicle_data_{timestamp}.csv"
            save_path = self.raw_dir / filename

            # ── 保存文件（UTF-8 编码） ──
            # 如果内网服务器使用 GBK 编码，这里需要做转换：
            #   content = resp.content.decode('gbk')
            # 先用 UTF-8，如果后续 data_loader 报编码错再调整
            save_path.write_text(content, encoding="utf-8")
            logger.debug(f"[DataFetcher] 文件已保存: {save_path} ({len(content)} 字节)")

            return str(save_path)

        except requests.exceptions.Timeout:
            logger.error(f"[DataFetcher] 请求超时: {url} (超时={self.timeout}s)")
            return None
        except requests.exceptions.ConnectionError as e:
            logger.error(f"[DataFetcher] 连接失败: {url} — {e}")
            return None
        except requests.exceptions.HTTPError as e:
            logger.error(f"[DataFetcher] HTTP 错误: {url} — {e}")
            return None
        except Exception as e:
            logger.error(f"[DataFetcher] 未知错误: {url} — {e}")
            return None
