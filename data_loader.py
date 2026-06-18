# ============================================================
# data_loader.py — 数据加载与预处理模块
# 功能：
#   1. 加载 CSV 文件（自动检测编码）
#   2. 列名映射（将中文列名或非标准列名映射到标准字段）
#   3. 数据清洗：去空格、处理空值、格式转换
#   4. 数据验证：检查必填字段、日期格式、VIN 合法性
#   5. 转换为 FaultRecord 对象列表供下游分析
# ============================================================

import re
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict

import pandas as pd
from loguru import logger

from models import FaultRecord, FaultLevel, calculate_weight


class DataLoader:
    """
    数据加载器 — CSV → FaultRecord 列表

    设计思路：
      1. 加载 CSV → pandas DataFrame
      2. 列名映射（中文 → 英文标准名）
      3. 逐列清洗 + 类型转换
      4. 数据验证（跳过无效行，记录日志）
      5. 生成 FaultRecord 列表

    使用示例：
      loader = DataLoader(config)
      records = loader.load("/path/to/vehicle_data.csv")
      # records 是 List[FaultRecord]
    """

    def __init__(self, config: dict):
        """
        初始化数据加载器

        Args:
            config: 完整配置字典，主要读取 column_mapping 和 risk_rules
        """
        # ── 列名映射：实际CSV列名 → 标准字段名 ──
        mapping = config.get("column_mapping", {})
        # 反转：标准字段名 → 实际CSV列名
        self.col_map: Dict[str, str] = {std: actual for std, actual in mapping.items()}
        # 保存反向映射：实际CSV列名 → 标准字段名（用于查找）
        self.col_reverse: Dict[str, str] = {actual: std for std, actual in mapping.items()}

        # ── 故障等级权重表 ──
        risk_rules = config.get("risk_rules", {})
        self.weight_map: dict = risk_rules.get("fault_level_weight", {})
        self.high_risk_threshold: int = risk_rules.get("high_risk_threshold", 20)

        # ── 路径 ──
        paths = config.get("paths", {})
        self.processed_dir: Path = Path(paths.get("processed_data_dir", "./data/processed"))
        self.processed_dir.mkdir(parents=True, exist_ok=True)

        # ── 统计计数器 ──
        self.stats = {
            "total_rows": 0,        # 原始总行数
            "valid_rows": 0,        # 有效行数
            "skipped_empty_vin": 0, # 因 VIN 为空跳过的行数
            "skipped_invalid_vin": 0,  # 因 VIN 格式错误跳过
            "skipped_bad_date": 0,  # 因日期格式错误跳过
            "encoding": None,       # 检测到的编码
        }

        logger.info(f"[DataLoader] 初始化完成，列映射数: {len(self.col_map)}, "
                     f"权重表: {self.weight_map}")

    def load(self, csv_path: str) -> List[FaultRecord]:
        """
        加载并处理单个 CSV 文件，返回 FaultRecord 列表

        这是总入口，依次调用：
          _read_csv → _normalize_columns → _clean_data → _build_records

        Args:
            csv_path: CSV 文件路径

        Returns:
            FaultRecord 对象列表，如果加载失败返回空列表
        """
        logger.info(f"[DataLoader] 开始加载 CSV: {csv_path}")

        try:
            # 第1步：读取 CSV（自动检测编码）
            df = self._read_csv(csv_path)
            if df is None or df.empty:
                logger.error(f"[DataLoader] CSV 为空或无法读取: {csv_path}")
                return []

            self.stats["total_rows"] = len(df)

            # 第2步：列名规范化
            df = self._normalize_columns(df)

            # 第3步：数据清洗
            df = self._clean_data(df)

            # 第4步：构建 FaultRecord 列表
            records = self._build_records(df)

            self.stats["valid_rows"] = len(records)
            self._log_stats()

            # 第5步：保存处理后的干净数据（供调试）
            clean_path = self.processed_dir / f"clean_{Path(csv_path).name}"
            pd.DataFrame([r.__dict__ for r in records]).to_csv(clean_path, index=False)
            logger.info(f"[DataLoader] 干净数据已保存至: {clean_path}")

            return records

        except Exception as e:
            logger.error(f"[DataLoader] 加载失败: {csv_path} — {e}")
            return []

    # ──────────────────────────────
    #  私有方法
    # ──────────────────────────────

    def _read_csv(self, path: str) -> Optional[pd.DataFrame]:
        """
        读取 CSV，自动检测编码

        顺序尝试 UTF-8 → GBK → GB2312 → gb18030，
        因为内网系统导出的 CSV 可能是国标编码。

        Args:
            path: CSV 文件路径

        Returns:
            pandas DataFrame 或 None
        """
        # ── 编码检测顺序 ──
        encodings = ["utf-8", "utf-8-sig", "gbk", "gb2312", "gb18030", "latin-1"]

        for enc in encodings:
            try:
                df = pd.read_csv(path, encoding=enc, dtype=str, keep_default_na=False)
                # keep_default_na=False: 避免 "NA" 等被误解析为 NaN
                self.stats["encoding"] = enc
                logger.info(f"[DataLoader] 编码检测: {enc}, 行数: {len(df)}, 列数: {len(df.columns)}")
                logger.debug(f"[DataLoader] 原始列名: {list(df.columns)}")
                return df
            except (UnicodeDecodeError, UnicodeError):
                continue

        logger.error(f"[DataLoader] 无法识别编码: {path}")
        return None

    def _normalize_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        列名规范化

        策略：
          1. 去除列名前后的空白字符
          2. 如果列名在 col_reverse 映射表中（中文 → 标准名），替换为标准名
          3. 如果列名已经是标准名，保持不变
          4. 不认识的列保留（但标 warning）

        Args:
            df: 原始 DataFrame

        Returns:
            列名规范化后的 DataFrame
        """
        # 去首尾空白
        df.columns = df.columns.str.strip()

        rename_map = {}
        unrecognized = []

        for col in df.columns:
            if col in self.col_reverse:
                # 实际列名 → 标准字段名
                std_name = self.col_reverse[col]
                rename_map[col] = std_name
            elif col in self.col_map:
                # 列名已经是标准名，不动
                continue
            else:
                unrecognized.append(col)

        if rename_map:
            df = df.rename(columns=rename_map)
            logger.info(f"[DataLoader] 列名映射: {rename_map}")
        if unrecognized:
            logger.warning(f"[DataLoader] 未识别的列（不会参与分析）: {unrecognized}")

        return df

    def _clean_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        数据清洗

        处理以下问题：
          - 所有字符串字段去除首尾空白
          - VIN（车架号）统一大写
          - 空字符串替换为 None
          - 删除 VIN 为空的行

        Args:
            df: 归一化列名后的 DataFrame

        Returns:
            清洗后的 DataFrame
        """
        # ── 所有字符串字段去空白 ──
        for col in df.columns:
            df[col] = df[col].str.strip()

        # ── VIN 统一大写 ──
        if "vin" in df.columns:
            df["vin"] = df["vin"].str.upper()
            # 删除 VIN 为空的行
            empty_vin_mask = df["vin"].isna() | (df["vin"] == "") | (df["vin"] == "无")
            self.stats["skipped_empty_vin"] = empty_vin_mask.sum()
            df = df[~empty_vin_mask]
            logger.debug(f"[DataLoader] 清理空 VIN: {self.stats['skipped_empty_vin']} 行")

        return df

    def _build_records(self, df: pd.DataFrame) -> List[FaultRecord]:
        """
        将 DataFrame 每一行转换为 FaultRecord 对象

        逐行处理，捕获异常不影响其他行。
        同时完成：
          - 日期解析
          - 故障等级枚举转换
          - 权重计算

        Args:
            df: 清洗后的 DataFrame

        Returns:
            FaultRecord 对象列表（只含有效行）
        """
        records: List[FaultRecord] = []

        for idx, row in df.iterrows():
            try:
                # ── VIN 校验（17位字母数字组合） ──
                vin = str(row.get("vin", ""))
                if not self._is_valid_vin(vin):
                    self.stats["skipped_invalid_vin"] += 1
                    logger.warning(f"[DataLoader] 行 {idx}: VIN 格式异常 → '{vin}'，跳过")
                    continue

                # ── 故障等级解析 ──
                level_str = str(row.get("fault_level", "一般"))
                try:
                    fault_level = FaultLevel(level_str)
                except ValueError:
                    logger.warning(f"[DataLoader] 行 {idx}: 未知故障等级 → '{level_str}'，按'一般'处理")
                    fault_level = FaultLevel.GENERAL

                # ── 日期解析 ──
                fault_time, update_time = self._parse_dates(
                    str(row.get("fault_time", "")),
                    str(row.get("update_time", "")),
                    idx
                )
                if fault_time is None:
                    self.stats["skipped_bad_date"] += 1
                    continue

                # ── 权重计算 ──
                weight = calculate_weight(fault_level, self.weight_map)

                # ── 构建 FaultRecord ──
                record = FaultRecord(
                    vin=vin,
                    vehicle_model=str(row.get("vehicle_model", "未知")),
                    software_version=str(row.get("software_version", "未知")),
                    fault_code=str(row.get("fault_code", "未知")),
                    fault_level=fault_level,
                    fault_desc=str(row.get("fault_desc", "")),
                    fault_time=fault_time,
                    mileage=self._safe_float(row.get("mileage")),
                    region=str(row.get("region", "")),
                    update_time=update_time,
                    weight=weight,
                )
                records.append(record)

            except Exception as e:
                logger.error(f"[DataLoader] 行 {idx}: 解析异常 — {e}，跳过该行")
                continue

        return records

    # ── 辅助方法 ──

    @staticmethod
    def _is_valid_vin(vin: str) -> bool:
        """
        校验 VIN（车架号）格式

        国际标准 VIN：
          - 17 位字符
          - 不含 I、O、Q（容易混淆）
          - 字母数字混合

        Args:
            vin: 车架号字符串

        Returns:
            格式是否合法
        """
        vin = vin.strip().replace(" ", "")
        # 宽松校验：长度 ≥ 10 且不含非法字符
        if len(vin) < 10 or len(vin) > 17:
            return False
        # 检查是否包含不允许的字母
        illegal = set("IOQ")
        if illegal & set(vin):
            logger.debug(f"[DataLoader] VIN 含非法字符(I/O/Q): {vin}")
            return False
        return True

    @staticmethod
    def _safe_float(val) -> Optional[float]:
        """安全转换为 float，失败返回 None"""
        if val is None or str(val).strip() == "":
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _parse_dates(fault_str: str, update_str: str, row_idx: int) -> tuple:
        """
        解析日期字符串

        支持常见格式：2024-01-15, 2024/01/15, 2024-01-15 10:30:00 等

        Args:
            fault_str: 故障时间字符串
            update_str: 更新时间字符串
            row_idx: 行号（用于日志）

        Returns:
            (fault_time, update_time) 元组；fault_time 不可为 None
        """
        date_formats = [
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
            "%Y/%m/%d %H:%M:%S",
            "%Y/%m/%d",
            "%Y%m%d",
            "%d-%m-%Y",
        ]

        fault_time = None
        update_time = None

        for fmt in date_formats:
            try:
                fault_time = datetime.strptime(fault_str.strip(), fmt)
                break
            except (ValueError, AttributeError):
                continue

        if update_str and update_str.strip():
            for fmt in date_formats:
                try:
                    update_time = datetime.strptime(update_str.strip(), fmt)
                    break
                except (ValueError, AttributeError):
                    continue

        if fault_time is None:
            logger.warning(f"[DataLoader] 行 {row_idx}: 无法解析故障时间 → '{fault_str}'")

        return fault_time, update_time

    def _log_stats(self):
        """输出加载统计"""
        logger.info(
            f"[DataLoader] 加载统计: "
            f"原始={self.stats['total_rows']}, "
            f"有效={self.stats['valid_rows']}, "
            f"空VIN={self.stats['skipped_empty_vin']}, "
            f"非法VIN={self.stats['skipped_invalid_vin']}, "
            f"日期错误={self.stats['skipped_bad_date']}, "
            f"编码={self.stats['encoding']}"
        )
