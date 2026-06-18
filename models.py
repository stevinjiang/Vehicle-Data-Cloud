# ============================================================
# models.py — 车云大数据平台 数据模型定义
# 使用 dataclass 定义所有核心数据结构，类型安全，
# 方便 IDE 自动补全和类型检查。
# ============================================================

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict
from enum import Enum


# ── 枚举定义 ──

class FaultLevel(str, Enum):
    """
    故障等级枚举
    对应 CSV 中的「故障等级」列，不同等级权重不同，
    权重值在 config.yaml 的 risk_rules.fault_level_weight 中配置
    """
    CRITICAL = "严重"    # 严重故障 — 影响行车安全，需立即处理
    GENERAL = "一般"     # 一般故障 — 影响功能但不影响安全
    MINOR = "轻微"       # 轻微故障 — 不影响正常使用的提示类问题


class RiskLevel(str, Enum):
    """聚合后的风险等级枚举"""
    HIGH = "高危"        # 风险总分 ≥ 阈值，需重点关注
    MEDIUM = "中危"      # 有一定风险但可控
    LOW = "低危"         # 风险极低或正常


# ── 核心数据模型 ──

@dataclass
class FaultRecord:
    """
    单条故障记录 (对应 CSV 中的一行数据)

    属性说明:
      - vin: 车架号，车辆唯一标识，用于按车辆聚合
      - fault_code: 故障码，如 P1123, B2152，用于技术诊断
      - fault_level: 故障等级枚举
      - fault_desc: 故障描述文本，如 "制动液压力传感器异常"
      - fault_time: 故障发生时间，用于分析故障趋势
      - weight: 该故障权重（由 config 中 fault_level_weight 查表得到）
    """
    vin: str                              # 车架号 (必填)
    vehicle_model: str                    # 车型
    software_version: str                 # 软件版本号
    fault_code: str                       # 故障码
    fault_level: FaultLevel               # 故障等级（枚举）
    fault_desc: str                       # 故障描述
    fault_time: datetime                  # 故障时间
    mileage: Optional[float] = None       # 行驶里程（km），可能缺失
    region: Optional[str] = None          # 地区
    update_time: Optional[datetime] = None  # 数据更新时间
    weight: int = 0                       # 权重分（由 fault_level 计算）


@dataclass
class VehicleProfile:
    """
    车辆画像 — 将同一 VIN 的所有故障记录聚合后的视图

    属性说明:
      - vin: 车架号
      - model: 车型
      - software_version: 最新软件版本
      - total_faults: 总故障数
      - risk_score: 风险总分（所有故障权重之和）
      - risk_level: 风险等级（高危/中危/低危）
      - is_software_outdated: 软件是否过旧
      - is_known_bad_version: 是否使用已知问题版本
      - fault_categories: 故障分类汇总 {故障码: 次数}
      - latest_fault_time: 最近一次故障时间
    """
    vin: str
    model: str
    software_version: str
    total_faults: int = 0
    risk_score: int = 0
    risk_level: RiskLevel = RiskLevel.LOW
    is_software_outdated: bool = False
    is_known_bad_version: bool = False
    fault_categories: Dict[str, int] = field(default_factory=dict)
    latest_fault_time: Optional[datetime] = None
    records: List[FaultRecord] = field(default_factory=list)


@dataclass
class TopIssue:
    """
    TOP 问题 — 按故障码聚合后的排行榜条目

    属性说明:
      - fault_code: 故障码
      - fault_desc: 故障描述（取第一条作为代表）
      - count: 出现次数
      - affected_vehicles: 受影响车辆数量（去重）
      - avg_risk: 平均风险分
      - trend: 趋势方向 "↑上升" / "↓下降" / "→持平"
    """
    fault_code: str
    fault_desc: str
    count: int = 0
    affected_vehicles: int = 0
    avg_risk: float = 0.0
    trend: str = "→持平"


@dataclass
class TopVehicle:
    """
    TOP 高风险车辆 — 按风险评分排序的排行榜条目

    属性说明:
      - vin: 车架号
      - model: 车型
      - risk_score: 风险总分
      - reason: 高风险原因摘要（如"含3个严重故障，软件版本过旧"）
    """
    vin: str
    model: str
    risk_score: int
    reason: str = ""


@dataclass
class SummaryReport:
    """
    汇总报告 — 包含本次分析的全部结果

    属性说明:
      - total_records: 本次处理的总故障记录数
      - total_vehicles: 涉及车辆总数（VIN 去重）
      - high_risk_count: 高危车辆数
      - top_issues: TOP N 问题列表
      - top_vehicles: TOP N 高风险车辆列表
      - generated_at: 报告生成时间
    """
    total_records: int
    total_vehicles: int
    high_risk_count: int
    top_issues: List[TopIssue] = field(default_factory=list)
    top_vehicles: List[TopVehicle] = field(default_factory=list)
    generated_at: datetime = field(default_factory=datetime.now)


# ── 工具函数 ──

def calculate_weight(fault_level: FaultLevel, weight_map: dict) -> int:
    """
    根据故障等级和权重映射表计算权重分

    Args:
        fault_level: 故障等级枚举值
        weight_map: 配置文件中的权重映射，如 {"严重": 10, "一般": 5, "轻微": 2}

    Returns:
        对应的权重大分，未知等级默认 1 分
    """
    return weight_map.get(fault_level.value, 1)
