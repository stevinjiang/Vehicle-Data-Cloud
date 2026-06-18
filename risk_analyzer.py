# ============================================================
# risk_analyzer.py — 风险分析模块
# 功能：
#   1. 高危风险识别 — 识别需要重点关注的车辆/问题
#   2. TOP N 排行 — 生成 TOP 问题 & TOP 高风险车辆
#   3. 趋势预警 — 检测故障增长趋势，提前预警
#   4. 漏洞软件版本检测 — 标记使用已知问题版本的车辆
#
# 设计思路：
#   - risk_analyzer 是 classifier 的上层封装
#   - 它调用 classifier 的分类方法，再加一层风险判定逻辑
#   - 输出结构化的分析结果供 report_generator 使用
# ============================================================

from datetime import datetime
from typing import List, Dict, Tuple, Optional

import pandas as pd
from loguru import logger

from models import (
    FaultRecord, FaultLevel, RiskLevel,
    VehicleProfile, TopIssue, TopVehicle, SummaryReport
)
from classifier import Classifier


class RiskAnalyzer:
    """
    风险分析器 — 核心分析引擎

    使用流程：
      analyzer = RiskAnalyzer(config)
      analyzer.analyze(records) → SummaryReport
    """

    def __init__(self, config: dict):
        """
        Args:
            config: 完整配置字典
        """
        self.config = config
        self.classifier = Classifier(config)

        # ── 风险阈值 ──
        risk = config.get("risk_rules", {})
        self.high_risk_threshold: int = risk.get("high_risk_threshold", 20)
        self.weight_map: dict = risk.get("fault_level_weight", {})

        # ── 版本风险 ──
        self.outdated_versions: set = set(risk.get("outdated_versions", []))
        self.known_bad_versions: set = set(risk.get("known_bad_versions", []))

        # ── TOP N ──
        top_n = config.get("top_n", {})
        self.top_issues_n: int = top_n.get("top_issues", 10)
        self.top_vehicles_n: int = top_n.get("top_vehicles", 10)

        logger.info("[RiskAnalyzer] 初始化完成")

    def analyze(self, records: List[FaultRecord]) -> SummaryReport:
        """
        主入口 — 对故障记录执行完整分析

        执行流程：
          1. 构建车辆画像
          2. 识别高危车辆
          3. 生成 TOP 问题排行
          4. 生成 TOP 高风险车辆排行
          5. 生成预警信息
          6. 汇总为 SummaryReport

        Args:
            records: FaultRecord 列表

        Returns:
            SummaryReport 汇总报告对象
        """
        if not records:
            logger.warning("[RiskAnalyzer] 无故障记录可分析")
            return SummaryReport(
                total_records=0,
                total_vehicles=0,
                high_risk_count=0,
            )

        logger.info(f"[RiskAnalyzer] 开始分析，故障记录数: {len(records)}")

        # 第1步：构建车辆画像
        profiles = self.classifier.build_vehicle_profiles(records)

        # 第2步：识别高危车辆
        high_risk_profiles = self._identify_high_risk(profiles)
        logger.info(
            f"[RiskAnalyzer] 高危识别完成: "
            f"总车辆={len(profiles)}, 高危={len(high_risk_profiles)}, "
            f"高危率={len(high_risk_profiles) / len(profiles) * 100:.1f}%"
        )

        # 第3步：生成预警
        warnings = self._generate_warnings(profiles, records)

        # 第4步：TOP 问题排行
        top_issues = self.classifier.get_top_issues(records, self.top_issues_n)

        # 第5步：TOP 高风险车辆排行
        top_vehicles = self.classifier.get_top_vehicles(records, self.top_vehicles_n)

        # 第6步：汇总报告
        report = SummaryReport(
            total_records=len(records),
            total_vehicles=len(profiles),
            high_risk_count=len(high_risk_profiles),
            top_issues=top_issues,
            top_vehicles=top_vehicles,
            generated_at=datetime.now(),
        )

        # 附加预警信息到报告（存储为额外属性）
        # SummaryReport 本身是 dataclass，我们用 __dict__ 附加额外字段
        report.__dict__["warnings"] = warnings
        report.__dict__["high_risk_profiles"] = high_risk_profiles
        report.__dict__["risk_level_distribution"] = self._risk_distribution(profiles)

        logger.info("[RiskAnalyzer] 分析完成")
        return report

    def multi_period_compare(self, current_records: List[FaultRecord],
                             previous_records: List[FaultRecord]) -> Dict:
        """
        多周期对比分析 — 比较本期 vs 上期数据

        用于回答"这周比上周好还是差"这类问题

        Args:
            current_records: 本期故障记录
            previous_records: 上期故障记录

        Returns:
            包含变化趋势的字典
        """
        current_report = self.analyze(current_records)
        previous_report = self.analyze(previous_records)

        # ── 关键指标对比 ──
        comparison = {
            "故障数变化": current_report.total_records - previous_report.total_records,
            "故障数变化率": self._change_rate(
                current_report.total_records, previous_report.total_records
            ),
            "车辆数变化": current_report.total_vehicles - previous_report.total_vehicles,
            "高危车辆变化": current_report.high_risk_count - previous_report.high_risk_count,
            "高危车辆变化率": self._change_rate(
                current_report.high_risk_count, previous_report.high_risk_count
            ),
        }

        # ── 新增的故障码 ──
        current_codes = {i.fault_code for i in current_report.top_issues}
        prev_codes = {i.fault_code for i in previous_report.top_issues}
        comparison["新增故障码"] = list(current_codes - prev_codes)
        comparison["消失故障码"] = list(prev_codes - current_codes)

        logger.info(f"[RiskAnalyzer] 多周期对比: {comparison}")
        return comparison

    # ============================================================
    #  私有方法
    # ============================================================

    def _identify_high_risk(self, profiles: List[VehicleProfile]) -> List[VehicleProfile]:
        """
        识别高危车辆

        判定标准（满足任一即标为高危）：
          1. 风险评分 >= high_risk_threshold
          2. 使用已知问题版本
          3. 含 3 个以上严重故障

        Args:
            profiles: 车辆画像列表

        Returns:
            高危车辆画像列表
        """
        high_risk = []

        for p in profiles:
            reasons = []

            # 标准1：风险评分超阈值
            if p.risk_score >= self.high_risk_threshold:
                reasons.append(f"风险评分{p.risk_score}≥{self.high_risk_threshold}")

            # 标准2：已知问题版本
            if p.is_known_bad_version:
                reasons.append(f"版本{p.software_version}为已知问题版本")

            # 标准3：多个严重故障
            critical_count = sum(
                1 for r in p.records if r.fault_level == FaultLevel.CRITICAL
            )
            if critical_count >= 3:
                reasons.append(f"含{critical_count}个严重故障")

            if reasons:
                high_risk.append(p)
                # 将原因记录到 profile 上（虽然 dataclass 没有该字段，但 __dict__ 方式临时附加）
                p.__dict__["high_risk_reasons"] = reasons

        return high_risk

    def _generate_warnings(self, profiles: List[VehicleProfile],
                           records: List[FaultRecord]) -> List[Dict]:
        """
        生成预警信息

        预警类型：
          1. 高危车辆数量预警 — 高危率超过 20%
          2. 严重故障集中爆发 — 单个故障码影响的车辆数 > 总车辆的 30%
          3. 软件版本过期预警 — 过期版本车辆占比 > 40%
          4. 单一地区故障集中 — 某地区高危率 > 50%

        Args:
            profiles: 车辆画像列表
            records: 故障记录列表

        Returns:
            预警列表，每条包含 {type, level, message}
        """
        warnings = []
        total_vehicles = len(profiles)
        if total_vehicles == 0:
            return warnings

        # ── 预警1：高危车辆比例 ──
        high_risk_count = sum(1 for p in profiles if p.risk_level == RiskLevel.HIGH)
        high_risk_rate = high_risk_count / total_vehicles
        if high_risk_rate > 0.2:
            warnings.append({
                "type": "高危车辆比例",
                "level": "🟡 警告" if high_risk_rate < 0.35 else "🔴 严重",
                "message": f"高危车辆占比 {high_risk_rate * 100:.1f}%（{high_risk_count}/{total_vehicles}），"
                          f"建议立即排查处理",
            })

        # ── 预警2：严重故障集中爆发 ──
        critical_records = [r for r in records if r.fault_level == FaultLevel.CRITICAL]
        if critical_records:
            from collections import Counter
            code_counts = Counter(r.fault_code for r in critical_records)
            top_code, top_count = code_counts.most_common(1)[0]
            affected_vins = {r.vin for r in critical_records if r.fault_code == top_code}
            concentration = len(affected_vins) / total_vehicles
            if concentration > 0.3:
                warnings.append({
                    "type": "故障集中爆发",
                    "level": "🔴 严重",
                    "message": f"严重故障'{top_code}'影响{len(affected_vins)}辆车"
                              f"（占总数的{concentration * 100:.1f}%），可能为系统性缺陷",
                })

        # ── 预警3：软件版本过期 ──
        outdated_count = sum(1 for p in profiles if p.is_software_outdated)
        if outdated_count / total_vehicles > 0.4:
            warnings.append({
                "type": "软件版本过期",
                "level": "🟡 警告",
                "message": f"{outdated_count}/{total_vehicles} 辆车使用过期版本"
                          f"（{outdated_count / total_vehicles * 100:.1f}%），建议推动 OTA 升级",
            })

        # ── 预警4：地区高危集中 ──
        region_risk = {}
        for p in profiles:
            for r in p.records:
                region = r.region or "未知"
                if region not in region_risk:
                    region_risk[region] = {"total": 0, "high_risk": 0}
                region_risk[region]["total"] += 1
            if p.risk_level == RiskLevel.HIGH:
                for r in p.records:
                    region = r.region or "未知"
                    region_risk[region]["high_risk"] += 1
                break  # 每辆车只算一次

        for region, stats in region_risk.items():
            if stats["total"] > 0 and stats["high_risk"] / stats["total"] > 0.5:
                warnings.append({
                    "type": "地区高危集中",
                    "level": "🔴 严重",
                    "message": f"地区'{region}'高危率为 "
                              f"{stats['high_risk'] / stats['total'] * 100:.1f}%，需重点关注",
                })

        if warnings:
            logger.info(f"[RiskAnalyzer] 生成 {len(warnings)} 条预警")
        return warnings

    @staticmethod
    def _risk_distribution(profiles: List[VehicleProfile]) -> Dict[str, int]:
        """风险等级分布统计"""
        dist = {"高危": 0, "中危": 0, "低危": 0}
        for p in profiles:
            if p.risk_level == RiskLevel.HIGH:
                dist["高危"] += 1
            elif p.risk_level == RiskLevel.MEDIUM:
                dist["中危"] += 1
            else:
                dist["低危"] += 1
        return dist

    @staticmethod
    def _change_rate(current: int, previous: int) -> str:
        """计算变化率（百分比字符串）"""
        if previous == 0:
            return "N/A（上期为0）"
        change = (current - previous) / previous * 100
        sign = "+" if change >= 0 else ""
        return f"{sign}{change:.1f}%"
