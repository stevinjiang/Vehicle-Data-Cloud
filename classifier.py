# ============================================================
# classifier.py — 分类汇总模块
# 功能：对车辆故障数据按多个维度分类汇总
#   1. 按故障等级分类（严重/一般/轻微）
#   2. 按故障码分类（哪些故障最普遍）
#   3. 按软件版本分类（哪些版本车辆最多）
#   4. 按地区分类（地域分布分析）
#   5. 按故障趋势分类（按时间看增长/下降）
# ============================================================

from collections import Counter, defaultdict
from datetime import datetime
from typing import List, Dict, Tuple

import pandas as pd
from loguru import logger

from models import FaultRecord, FaultLevel, RiskLevel, VehicleProfile, TopIssue, TopVehicle


class Classifier:
    """
    分类汇总器

    设计思路：
      1. 接收 FaultRecord 列表
      2. 按 VIN 聚合 → VehicleProfile 列表
      3. 按故障码聚合 → TopIssue 排行
      4. 按风险评分排序 → TopVehicle 排行
      5. 输出各维度统计 DataFrame 供报告使用

    使用示例：
      classifier = Classifier(config)
      profiles = classifier.build_vehicle_profiles(records)
      top_issues = classifier.get_top_issues(records, n=10)
    """

    def __init__(self, config: dict):
        """
        Args:
            config: 完整配置字典
        """
        # ── 风险判定参数 ──
        risk = config.get("risk_rules", {})
        self.weight_map: dict = risk.get("fault_level_weight", {})
        self.high_risk_threshold: int = risk.get("high_risk_threshold", 20)

        # ── 软件版本风险评估 ──
        self.outdated_versions: set = set(risk.get("outdated_versions", []))
        self.known_bad_versions: set = set(risk.get("known_bad_versions", []))

        # ── TOP N ──
        top_n = config.get("top_n", {})
        self.top_issues_n: int = top_n.get("top_issues", 10)
        self.top_vehicles_n: int = top_n.get("top_vehicles", 10)

        logger.info(f"[Classifier] 初始化完成，高危阈值: {self.high_risk_threshold}")

    # ============================================================
    #  车辆画像聚合 (FaultRecord → VehicleProfile)
    # ============================================================

    def build_vehicle_profiles(self, records: List[FaultRecord]) -> List[VehicleProfile]:
        """
        将故障记录按 VIN 聚合，生成每个车辆的画像

        聚合内容包括：
          - 总故障数
          - 风险总分 → 风险等级判定
          - 软件版本评估（是否过旧 / 已知问题版本）
          - 故障分类计数
          - 最近故障时间

        Args:
            records: FaultRecord 列表

        Returns:
            VehicleProfile 列表，按风险评分降序排列
        """
        if not records:
            logger.warning("[Classifier] 故障记录为空，车辆画像为空")
            return []

        # ── 按 VIN 分组 ──
        grouped: Dict[str, List[FaultRecord]] = defaultdict(list)
        for r in records:
            grouped[r.vin].append(r)

        profiles: List[VehicleProfile] = []

        for vin, recs in grouped.items():
            # 取第一条记录的车型和软件版本（同一 VIN 应该一致，取出现最多的版本）
            model = self._most_common([r.vehicle_model for r in recs])
            sw_version = self._most_common([r.software_version for r in recs])

            # ── 风险评分：所有故障权重之和 ──
            total_score = sum(r.weight for r in recs)
            risk_level = self._evaluate_risk_level(total_score)

            # ── 软件版本评估 ──
            is_outdated = sw_version in self.outdated_versions
            is_bad = sw_version in self.known_bad_versions

            # ── 故障分类计数 ──
            fault_categories: Dict[str, int] = Counter(r.fault_code for r in recs)

            # ── 最近故障时间 ──
            latest = max(r.fault_time for r in recs if r.fault_time)

            profile = VehicleProfile(
                vin=vin,
                model=model,
                software_version=sw_version,
                total_faults=len(recs),
                risk_score=total_score,
                risk_level=risk_level,
                is_software_outdated=is_outdated,
                is_known_bad_version=is_bad,
                fault_categories=fault_categories,
                latest_fault_time=latest,
                records=recs,
            )
            profiles.append(profile)

        # ── 按风险评分降序排列，高风险排前面 ──
        profiles.sort(key=lambda p: p.risk_score, reverse=True)

        logger.info(
            f"[Classifier] 车辆画像构建完成: "
            f"总车辆={len(profiles)}, "
            f"高危={sum(1 for p in profiles if p.risk_level == RiskLevel.HIGH)}, "
            f"中危={sum(1 for p in profiles if p.risk_level == RiskLevel.MEDIUM)}, "
            f"低危={sum(1 for p in profiles if p.risk_level == RiskLevel.LOW)}"
        )
        return profiles

    # ============================================================
    #  故障码分类汇总 (→ TopIssue 排行)
    # ============================================================

    def classify_by_fault_code(self, records: List[FaultRecord]) -> pd.DataFrame:
        """
        按故障码分类汇总，生成统计 DataFrame

        包含字段：故障码、出现次数、受影响车辆数、平均权重、占比

        Args:
            records: FaultRecord 列表

        Returns:
            按出现次数降序排列的 DataFrame
        """
        if not records:
            return pd.DataFrame()

        # ── 聚合 ──
        code_counts = Counter(r.fault_code for r in records)
        code_vins = defaultdict(set)     # 每个故障码影响的 VIN 集合
        code_weights = defaultdict(list) # 每个故障码的权重列表

        for r in records:
            code_vins[r.fault_code].add(r.vin)
            code_weights[r.fault_code].append(r.weight)

        # ── 构建 DataFrame ──
        rows = []
        total_count = len(records)
        for code, count in code_counts.most_common():
            rows.append({
                "故障码": code,
                "出现次数": count,
                "占比": f"{count / total_count * 100:.1f}%",
                "受影响车辆数": len(code_vins[code]),
                "平均风险分": f"{sum(code_weights[code]) / len(code_weights[code]):.1f}",
                "故障描述": records[0].fault_desc if code == records[0].fault_code else "",
            })

        df = pd.DataFrame(rows)
        logger.info(f"[Classifier] 故障码分类: {len(df)} 种故障码")
        return df

    def classify_by_fault_level(self, records: List[FaultRecord]) -> pd.DataFrame:
        """
        按故障等级分类汇总（严重/一般/轻微）

        Returns:
            包含数量、占比、涉及车辆数的 DataFrame
        """
        if not records:
            return pd.DataFrame()

        level_counts = Counter(r.fault_level for r in records)
        level_vins = defaultdict(set)
        for r in records:
            level_vins[r.fault_level].add(r.vin)

        rows = []
        total = len(records)
        for level in [FaultLevel.CRITICAL, FaultLevel.GENERAL, FaultLevel.MINOR]:
            count = level_counts.get(level, 0)
            rows.append({
                "故障等级": level.value,
                "数量": count,
                "占比": f"{count / total * 100:.1f}%" if total > 0 else "0%",
                "涉及车辆数": len(level_vins[level]),
                "权重分": self.weight_map.get(level.value, 0),
            })

        df = pd.DataFrame(rows)
        logger.info(f"[Classifier] 故障等级分布: 严重={level_counts.get(FaultLevel.CRITICAL, 0)}, "
                     f"一般={level_counts.get(FaultLevel.GENERAL, 0)}, "
                     f"轻微={level_counts.get(FaultLevel.MINOR, 0)}")
        return df

    def classify_by_software_version(self, records: List[FaultRecord]) -> pd.DataFrame:
        """
        按软件版本分类汇总，便于了解各版本分布

        Returns:
            各版本的车辆数、故障数、平均风险分
        """
        if not records:
            return pd.DataFrame()

        # ── 先构建车辆画像来获取版本信息 ──
        profiles = self.build_vehicle_profiles(records)

        # ── 按版本聚合 ──
        version_data = defaultdict(lambda: {"vehicles": set(), "total_score": 0, "faults": 0})
        for p in profiles:
            key = p.software_version
            version_data[key]["vehicles"].add(p.vin)
            version_data[key]["total_score"] += p.risk_score
            version_data[key]["faults"] += p.total_faults

        rows = []
        for ver, data in version_data.items():
            vehicle_count = len(data["vehicles"])
            rows.append({
                "软件版本": ver,
                "车辆数": vehicle_count,
                "故障总数": data["faults"],
                "平均风险分": f"{data['total_score'] / vehicle_count:.1f}" if vehicle_count > 0 else "0",
                "是否过期": "⚠ 是" if ver in self.outdated_versions else "否",
                "已知问题版本": "🚨 是" if ver in self.known_bad_versions else "否",
            })

        df = pd.DataFrame(rows).sort_values("车辆数", ascending=False)
        logger.info(f"[Classifier] 软件版本分类: {len(df)} 个版本")
        return df

    def classify_by_region(self, records: List[FaultRecord]) -> pd.DataFrame:
        """
        按地区分类汇总（如果数据中有 region 字段）

        Returns:
            各地区的车辆数、故障数、高危数量
        """
        if not records:
            return pd.DataFrame()

        region_data = defaultdict(lambda: {"vehicles": set(), "faults": 0, "high_risk_vehicles": set()})
        profiles = self.build_vehicle_profiles(records)

        for p in profiles:
            for r in p.records:
                region = r.region or "未知"
                region_data[region]["vehicles"].add(r.vin)
                region_data[region]["faults"] += 1
            if p.risk_level == RiskLevel.HIGH:
                region = p.records[0].region or "未知"
                region_data[region]["high_risk_vehicles"].add(p.vin)

        rows = []
        for region, data in region_data.items():
            rows.append({
                "地区": region,
                "车辆数": len(data["vehicles"]),
                "故障总数": data["faults"],
                "高危车辆数": len(data["high_risk_vehicles"]),
            })

        df = pd.DataFrame(rows).sort_values("车辆数", ascending=False)
        logger.info(f"[Classifier] 地区分类: {len(df)} 个地区")
        return df

    # ============================================================
    #  TOP N 排行 (TopIssue + TopVehicle)
    # ============================================================

    def get_top_issues(self, records: List[FaultRecord], n: int = None) -> List[TopIssue]:
        """
        生成 TOP N 问题排行

        排名依据：故障出现次数（出现次数 = 权重×出现次数）
        附加信息：受影响车辆数、平均风险、趋势方向

        趋势算法（简化版）：
          比较最近 30 天 vs 前 30-60 天的出现次数
          增幅 > 10% → "↑上升" / 降幅 > 10% → "↓下降" / 否则 → "→持平"

        Args:
            records: FaultRecord 列表
            n: 取前 N 条，默认使用配置中的 top_n.top_issues

        Returns:
            TopIssue 列表，按出现次数降序
        """
        if n is None:
            n = self.top_issues_n

        if not records:
            return []

        # ── 故障码聚合 ──
        code_counts = Counter()
        code_descs = {}
        code_vins = defaultdict(set)
        code_weights = defaultdict(list)

        for r in records:
            code_counts[r.fault_code] += 1
            code_descs[r.fault_code] = r.fault_desc
            code_vins[r.fault_code].add(r.vin)
            code_weights[r.fault_code].append(r.weight)

        # ── 趋势分析（有足够数据时） ──
        now = datetime.now()
        trends = self._calculate_trends(records, now)

        # ── 构建 TopIssue 列表 ──
        issues = []
        for code, count in code_counts.most_common(n):
            avg_weight = (sum(code_weights[code]) / len(code_weights[code])
                          if code_weights[code] else 0)
            issues.append(TopIssue(
                fault_code=code,
                fault_desc=code_descs.get(code, ""),
                count=count,
                affected_vehicles=len(code_vins[code]),
                avg_risk=avg_weight,
                trend=trends.get(code, "→持平"),
            ))

        logger.info(f"[Classifier] TOP {n} 问题: {[(i.fault_code, i.count) for i in issues[:3]]}...")
        return issues

    def get_top_vehicles(self, records: List[FaultRecord], n: int = None) -> List[TopVehicle]:
        """
        生成 TOP N 高风险车辆排行

        排名依据：风险总分（所有故障权重之和）降序
        为什么不用简单的故障次数排名？
          — 因为 1 个严重故障（刹车失灵，权重10）比 5 个轻微故障（保养提醒，权重2）
            的风险高得多，所以用风险总分更科学

        Args:
            records: FaultRecord 列表
            n: 取前 N 条

        Returns:
            TopVehicle 列表，按风险评分降序
        """
        if n is None:
            n = self.top_vehicles_n

        # ── 先构建车辆画像 ──
        profiles = self.build_vehicle_profiles(records)

        # ── 取 TOP N ──
        top_vehicles = []
        for p in profiles[:n]:
            # 生成高风险原因摘要
            reasons = self._build_risk_reason(p)
            top_vehicles.append(TopVehicle(
                vin=p.vin,
                model=p.model,
                risk_score=p.risk_score,
                reason=reasons,
            ))

        logger.info(f"[Classifier] TOP {n} 高风险车辆: "
                     f"{[(v.vin, v.risk_score) for v in top_vehicles[:3]]}...")
        return top_vehicles

    # ============================================================
    #  私有辅助方法
    # ============================================================

    def _evaluate_risk_level(self, score: int) -> RiskLevel:
        """
        根据风险总分判定风险等级

        规则：
          - score >= high_risk_threshold → 高危
          - score >= high_risk_threshold / 2 → 中危
          - 其余 → 低危

        Args:
            score: 风险总分

        Returns:
            RiskLevel 枚举
        """
        if score >= self.high_risk_threshold:
            return RiskLevel.HIGH
        elif score >= self.high_risk_threshold // 2:
            return RiskLevel.MEDIUM
        else:
            return RiskLevel.LOW

    @staticmethod
    def _most_common(items: list) -> str:
        """取列表中出现最多的元素"""
        if not items:
            return "未知"
        return Counter(items).most_common(1)[0][0]

    def _calculate_trends(self, records: List[FaultRecord], now: datetime) -> Dict[str, str]:
        """
        计算各故障码的趋势方向

        简化版算法：
          将数据分为「最近30天」和「前30-60天」两段
          比较两段出现次数变化

        Args:
            records: 故障记录列表
            now: 当前时间

        Returns:
            {故障码: "↑上升"|"↓下降"|"→持平"} 字典
        """
        trends = {}

        # ── 时间窗口分割 ──
        # 最近30天
        recent_cutoff = now.timestamp() - 30 * 24 * 3600
        # 30-60天前
        older_start = now.timestamp() - 60 * 24 * 3600

        recent_counts: Dict[str, int] = Counter()
        older_counts: Dict[str, int] = Counter()

        for r in records:
            if r.fault_time is None:
                continue
            ts = r.fault_time.timestamp()
            if ts >= recent_cutoff:
                recent_counts[r.fault_code] += 1
            elif ts >= older_start:
                older_counts[r.fault_code] += 1

        # ── 计算变化趋势 ──
        all_codes = set(recent_counts.keys()) | set(older_counts.keys())
        for code in all_codes:
            recent = recent_counts.get(code, 0)
            older = older_counts.get(code, 0)
            if older == 0:
                trends[code] = "↑上升" if recent > 0 else "→持平"
            else:
                change = (recent - older) / older
                if change > 0.1:
                    trends[code] = "↑上升"
                elif change < -0.1:
                    trends[code] = "↓下降"
                else:
                    trends[code] = "→持平"

        return trends

    def _build_risk_reason(self, profile: VehicleProfile) -> str:
        """
        构建高风险原因摘要文字

        Args:
            profile: 车辆画像

        Returns:
            原因摘要，如 "含3个严重故障，软件版本v1.0.3为已知问题版本"
        """
        reasons = []

        # ── 统计严重故障数 ──
        critical_count = sum(
            1 for r in profile.records if r.fault_level == FaultLevel.CRITICAL
        )
        if critical_count > 0:
            reasons.append(f"含{critical_count}个严重故障")

        general_count = sum(
            1 for r in profile.records if r.fault_level == FaultLevel.GENERAL
        )
        if general_count > 0:
            reasons.append(f"含{general_count}个一般故障")

        # ── 软件版本问题 ──
        if profile.is_known_bad_version:
            reasons.append(f"软件版本{profile.software_version}为已知问题版本")
        elif profile.is_software_outdated:
            reasons.append(f"软件版本{profile.software_version}过旧")

        # ── 故障总数 ──
        if profile.total_faults >= 10:
            reasons.append(f"共计{profile.total_faults}个故障")

        return "，".join(reasons) if reasons else f"风险评分{profile.risk_score}偏高"
