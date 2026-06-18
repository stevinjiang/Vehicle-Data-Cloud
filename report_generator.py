# ============================================================
# report_generator.py — 报告生成模块
# 功能：
#   1. HTML 报告 — 美观、包含图表和表格
#   2. Markdown 报告 — 适合消息推送
#   3. Excel 汇总表 — 结构化数据导出
#   4. JSON — 便于程序读取
#
# 报告内容：
#   - 概览：车辆总数、故障总数、高危车辆数
#   - TOP N 问题排行
#   - TOP N 高风险车辆排行
#   - 预警信息
#   - 故障等级分布
#   - 软件版本分布
# ============================================================

import json
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import pandas as pd
from loguru import logger

from models import SummaryReport, TopIssue, TopVehicle, VehicleProfile
from classifier import Classifier
from risk_analyzer import RiskAnalyzer


class ReportGenerator:
    """
    报告生成器 — 将分析结果输出为各种格式

    使用示例：
      gen = ReportGenerator(config)
      gen.generate(summary_report, profiles, records)
    """

    def __init__(self, config: dict):
        """
        Args:
            config: 完整配置字典
        """
        paths = config.get("paths", {})
        self.report_dir: Path = Path(paths.get("report_dir", "./reports"))
        self.report_dir.mkdir(parents=True, exist_ok=True)

        report_cfg = config.get("report", {})
        self.output_format: str = report_cfg.get("output_format", "html")
        self.generate_excel: bool = report_cfg.get("generate_excel", True)
        self.language: str = report_cfg.get("language", "zh")

        self.classifier = Classifier(config)
        self.risk_analyzer = RiskAnalyzer(config)

        logger.info(f"[ReportGenerator] 初始化完成，报告目录: {self.report_dir}")

    def generate(self, report: SummaryReport,
                 profiles: List[VehicleProfile],
                 records) -> str:
        """
        生成所有配置的报告格式

        Args:
            report: 汇总报告对象
            profiles: 车辆画像列表
            records: 原始故障记录列表

        Returns:
            生成的报告文件路径（主报告）
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = ""

        # ── 生成分类汇总 DataFrame ──
        fault_code_df = self.classifier.classify_by_fault_code(records) if records else pd.DataFrame()
        fault_level_df = self.classifier.classify_by_fault_level(records) if records else pd.DataFrame()
        sw_version_df = self.classifier.classify_by_software_version(records) if records else pd.DataFrame()
        region_df = self.classifier.classify_by_region(records) if records else pd.DataFrame()

        # ── HTML 报告 ──
        if self.output_format in ("html", "all"):
            report_path = self._generate_html(
                report, profiles, records,
                fault_code_df, fault_level_df, sw_version_df, region_df,
                timestamp
            )
            logger.info(f"[ReportGenerator] HTML 报告: {report_path}")

        # ── Markdown 报告 ──
        if self.output_format in ("markdown", "all"):
            md_path = self._generate_markdown(report, timestamp)
            logger.info(f"[ReportGenerator] Markdown 报告: {md_path}")

        # ── JSON 报告 ──
        if self.output_format in ("json", "all"):
            json_path = self._generate_json(report, timestamp)
            logger.info(f"[ReportGenerator] JSON 报告: {json_path}")

        # ── Excel 汇总表 ──
        if self.generate_excel:
            excel_path = self._generate_excel(
                report, profiles, fault_code_df, fault_level_df,
                sw_version_df, region_df, timestamp
            )
            logger.info(f"[ReportGenerator] Excel 报告: {excel_path}")

        return report_path

    # ============================================================
    #  HTML 报告
    # ============================================================

    def _generate_html(self, report: SummaryReport,
                       profiles: List[VehicleProfile],
                       records,
                       fault_code_df, fault_level_df, sw_version_df, region_df,
                       timestamp: str) -> str:
        """生成 HTML 格式的完整报告"""

        # ── 报告数据准备 ──
        warnings = report.__dict__.get("warnings", [])
        risk_dist = report.__dict__.get("risk_level_distribution", {})

        # ── TOP 问题表格行 ──
        top_issues_rows = ""
        for i, issue in enumerate(report.top_issues, 1):
            top_issues_rows += f"""
            <tr>
                <td class="rank">{i}</td>
                <td><code>{issue.fault_code}</code></td>
                <td>{issue.fault_desc[:30]}</td>
                <td class="num">{issue.count}</td>
                <td class="num">{issue.affected_vehicles}</td>
                <td class="num">{issue.avg_risk:.1f}</td>
                <td>{issue.trend}</td>
            </tr>"""

        # ── TOP 车辆表格行 ──
        top_vehicles_rows = ""
        for i, v in enumerate(report.top_vehicles, 1):
            risk_class = "high-risk" if v.risk_score >= self.risk_analyzer.high_risk_threshold else ""
            top_vehicles_rows += f"""
            <tr class="{risk_class}">
                <td class="rank">{i}</td>
                <td><code>{v.vin}</code></td>
                <td>{v.model}</td>
                <td class="num">{v.risk_score}</td>
                <td>{v.reason[:50]}</td>
            </tr>"""

        # ── 预警HTML ──
        warnings_html = ""
        if warnings:
            for w in warnings:
                warnings_html += f'<div class="warning-item {w["level"]}"><strong>[{w["level"]}] {w["type"]}</strong><br>{w["message"]}</div>'
        else:
            warnings_html = '<div class="warning-item ok">✅ 无预警，系统状态正常</div>'

        # ── 风险分布条 ──
        total = sum(risk_dist.values()) or 1
        high_pct = risk_dist.get("高危", 0) / total * 100
        med_pct = risk_dist.get("中危", 0) / total * 100
        low_pct = risk_dist.get("低危", 0) / total * 100

        html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>车云大数据平台 — 车辆故障分析报告</title>
<style>
    :root {{ color-scheme: light; }}
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
        background: #f5f7fa; color: #2c3e50; line-height: 1.6;
    }}
    .container {{ max-width: 1100px; margin: 0 auto; padding: 20px; }}
    .header {{
        background: linear-gradient(135deg, #1a73e8, #0d47a1);
        color: white; padding: 30px 40px; border-radius: 12px; margin-bottom: 24px;
    }}
    .header h1 {{ font-size: 28px; margin-bottom: 8px; }}
    .header .subtitle {{ opacity: 0.85; font-size: 14px; }}
    .cards {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-bottom: 24px; }}
    .card {{
        background: white; border-radius: 10px; padding: 20px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.08);
    }}
    .card .label {{ font-size: 13px; color: #7f8c8d; margin-bottom: 6px; }}
    .card .value {{ font-size: 32px; font-weight: 700; }}
    .card.high .value {{ color: #e74c3c; }}
    .risk-bar-container {{
        background: white; border-radius: 10px; padding: 20px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.08); margin-bottom: 24px;
    }}
    .risk-bar {{ display: flex; height: 28px; border-radius: 14px; overflow: hidden; margin-top: 10px; }}
    .risk-bar .high {{ background: #e74c3c; width: {high_pct:.1f}%; }}
    .risk-bar .medium {{ background: #f39c12; width: {med_pct:.1f}%; }}
    .risk-bar .low {{ background: #27ae60; width: {low_pct:.1f}%; }}
    .risk-legend {{ display: flex; gap: 20px; margin-top: 8px; font-size: 13px; }}
    .risk-legend span {{ display: flex; align-items: center; gap: 6px; }}
    .risk-legend .dot {{ width: 12px; height: 12px; border-radius: 50%; display: inline-block; }}
    .section {{
        background: white; border-radius: 10px; padding: 24px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.08); margin-bottom: 24px;
    }}
    .section h2 {{ font-size: 18px; margin-bottom: 16px; padding-bottom: 8px; border-bottom: 2px solid #1a73e8; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
    th {{ background: #f0f3f7; text-align: left; padding: 10px 12px; font-weight: 600; color: #555; }}
    td {{ padding: 10px 12px; border-bottom: 1px solid #eee; }}
    tr:hover {{ background: #fafbfc; }}
    .rank {{ font-weight: 700; color: #1a73e8; text-align: center; }}
    .num {{ text-align: right; font-variant-numeric: tabular-nums; }}
    tr.high-risk {{ background: #fff5f5; }}
    code {{ background: #eef; padding: 2px 6px; border-radius: 4px; font-size: 13px; }}
    .warnings {{ margin-bottom: 24px; }}
    .warning-item {{
        padding: 12px 16px; border-radius: 8px; margin-bottom: 8px; font-size: 14px;
    }}
    .warning-item.ok {{ background: #e8f5e9; color: #2e7d32; }}
    .warning-item.🟡 {{ background: #fff8e1; color: #f57f17; }}
    .warning-item.🔴 {{ background: #ffebee; color: #c62828; }}
    .footer {{ text-align: center; color: #999; font-size: 12px; padding: 20px; }}
</style>
</head>
<body>
<div class="container">

    <!-- 头部 -->
    <div class="header">
        <h1>🚗 车云大数据平台 — 车辆故障分析报告</h1>
        <div class="subtitle">生成时间: {report.generated_at.strftime('%Y-%m-%d %H:%M:%S')} | 数据周期: 最新</div>
    </div>

    <!-- 概览卡片 -->
    <div class="cards">
        <div class="card">
            <div class="label">📊 故障记录总数</div>
            <div class="value">{report.total_records}</div>
        </div>
        <div class="card">
            <div class="label">🚙 涉及车辆总数</div>
            <div class="value">{report.total_vehicles}</div>
        </div>
        <div class="card high">
            <div class="label">⚠️ 高危车辆数</div>
            <div class="value">{report.high_risk_count}</div>
        </div>
        <div class="card">
            <div class="label">📈 高危率</div>
            <div class="value">{report.high_risk_count / max(report.total_vehicles, 1) * 100:.1f}%</div>
        </div>
    </div>

    <!-- 风险分布条 -->
    <div class="risk-bar-container">
        <strong>风险等级分布</strong>
        <div class="risk-bar">
            <div class="high"></div>
            <div class="medium"></div>
            <div class="low"></div>
        </div>
        <div class="risk-legend">
            <span><span class="dot" style="background:#e74c3c"></span> 高危: {risk_dist.get("高危", 0)} 辆</span>
            <span><span class="dot" style="background:#f39c12"></span> 中危: {risk_dist.get("中危", 0)} 辆</span>
            <span><span class="dot" style="background:#27ae60"></span> 低危: {risk_dist.get("低危", 0)} 辆</span>
        </div>
    </div>

    <!-- 预警信息 -->
    <div class="warnings">
        <h2>🔔 预警信息</h2>
        {warnings_html}
    </div>

    <!-- TOP 问题排行 -->
    <div class="section">
        <h2>🔝 TOP {len(report.top_issues)} 问题排行</h2>
        <table>
            <thead>
                <tr><th>#</th><th>故障码</th><th>描述</th><th>出现次数</th><th>受影响车辆</th><th>平均风险</th><th>趋势</th></tr>
            </thead>
            <tbody>{top_issues_rows}</tbody>
        </table>
    </div>

    <!-- TOP 高风险车辆 -->
    <div class="section">
        <h2>🚨 TOP {len(report.top_vehicles)} 高风险车辆</h2>
        <table>
            <thead>
                <tr><th>#</th><th>车架号 (VIN)</th><th>车型</th><th>风险评分</th><th>原因摘要</th></tr>
            </thead>
            <tbody>{top_vehicles_rows}</tbody>
        </table>
    </div>

    <!-- 故障等级分布 -->
    <div class="section">
        <h2>📊 故障等级分布</h2>
        {fault_level_df.to_html(index=False, classes='table', border=0) if not fault_level_df.empty else '<p>暂无数据</p>'}
    </div>

    <!-- 软件版本分布 -->
    <div class="section">
        <h2>💿 软件版本分布</h2>
        {sw_version_df.to_html(index=False, classes='table', border=0) if not sw_version_df.empty else '<p>暂无数据</p>'}
    </div>

    <div class="footer">
        Vehicle-Data-Cloud 车云大数据平台 · 自动生成 · {datetime.now().strftime('%Y-%m-%d %H:%M')}
    </div>
</div>
</body>
</html>"""

        # ── 保存文件 ──
        filename = f"vehicle_report_{timestamp}.html"
        filepath = self.report_dir / filename
        filepath.write_text(html, encoding="utf-8")
        return str(filepath)

    # ============================================================
    #  Markdown 报告
    # ============================================================

    def _generate_markdown(self, report: SummaryReport, timestamp: str) -> str:
        """生成 Markdown 格式的简洁报告，适合消息推送"""
        warnings = report.__dict__.get("warnings", [])

        lines = [
            "# 🚗 车云大数据平台 — 车辆故障分析报告",
            "",
            f"**生成时间**: {report.generated_at.strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "## 📊 概览",
            "",
            f"| 指标 | 数值 |",
            f"|------|------|",
            f"| 故障记录总数 | {report.total_records} |",
            f"| 涉及车辆总数 | {report.total_vehicles} |",
            f"| 高危车辆数 | **{report.high_risk_count}** |",
            f"| 高危率 | {report.high_risk_count / max(report.total_vehicles, 1) * 100:.1f}% |",
            "",
        ]

        # ── 预警 ──
        if warnings:
            lines.append("## 🔔 预警信息")
            lines.append("")
            for w in warnings:
                lines.append(f"- {w['level']} **{w['type']}**: {w['message']}")
            lines.append("")

        # ── TOP 问题 ──
        if report.top_issues:
            lines.append(f"## 🔝 TOP 问题排行")
            lines.append("")
            lines.append("| # | 故障码 | 出现次数 | 影响车辆 | 趋势 |")
            lines.append("|---|--------|----------|----------|------|")
            for i, issue in enumerate(report.top_issues, 1):
                lines.append(f"| {i} | `{issue.fault_code}` | {issue.count} | {issue.affected_vehicles} | {issue.trend} |")
            lines.append("")

        # ── TOP 车辆 ──
        if report.top_vehicles:
            lines.append(f"## 🚨 TOP 高风险车辆")
            lines.append("")
            lines.append("| # | VIN | 车型 | 风险分 | 原因 |")
            lines.append("|---|-----|------|--------|------|")
            for i, v in enumerate(report.top_vehicles, 1):
                lines.append(f"| {i} | `{v.vin}` | {v.model} | {v.risk_score} | {v.reason[:40]} |")
            lines.append("")

        md_content = "\n".join(lines)
        filename = f"vehicle_report_{timestamp}.md"
        filepath = self.report_dir / filename
        filepath.write_text(md_content, encoding="utf-8")
        return str(filepath)

    # ============================================================
    #  JSON 报告
    # ============================================================

    def _generate_json(self, report: SummaryReport, timestamp: str) -> str:
        """生成 JSON 格式报告，便于程序读取"""
        data = {
            "generated_at": report.generated_at.isoformat(),
            "summary": {
                "total_records": report.total_records,
                "total_vehicles": report.total_vehicles,
                "high_risk_count": report.high_risk_count,
            },
            "warnings": report.__dict__.get("warnings", []),
            "risk_distribution": report.__dict__.get("risk_level_distribution", {}),
            "top_issues": [
                {
                    "fault_code": i.fault_code,
                    "fault_desc": i.fault_desc,
                    "count": i.count,
                    "affected_vehicles": i.affected_vehicles,
                    "avg_risk": i.avg_risk,
                    "trend": i.trend,
                }
                for i in report.top_issues
            ],
            "top_vehicles": [
                {
                    "vin": v.vin,
                    "model": v.model,
                    "risk_score": v.risk_score,
                    "reason": v.reason,
                }
                for v in report.top_vehicles
            ],
        }

        filename = f"vehicle_report_{timestamp}.json"
        filepath = self.report_dir / filename
        filepath.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return str(filepath)

    # ============================================================
    #  Excel 汇总表
    # ============================================================

    def _generate_excel(self, report: SummaryReport,
                        profiles: List[VehicleProfile],
                        fault_code_df, fault_level_df, sw_version_df, region_df,
                        timestamp: str) -> str:
        """
        生成 Excel 工作簿，包含多个 Sheet：
          - 概览
          - TOP 问题
          - TOP 高风险车辆
          - 故障等级分布
          - 软件版本分布
          - 地区分布
          - 完整车辆画像
        """
        filename = f"vehicle_data_{timestamp}.xlsx"
        filepath = self.report_dir / filename

        with pd.ExcelWriter(filepath, engine="openpyxl") as writer:
            # Sheet 1: 概览
            overview = pd.DataFrame([
                {"指标": "故障记录总数", "数值": report.total_records},
                {"指标": "涉及车辆总数", "数值": report.total_vehicles},
                {"指标": "高危车辆数", "数值": report.high_risk_count},
                {"指标": "高危率", "数值": f"{report.high_risk_count / max(report.total_vehicles, 1) * 100:.1f}%"},
                {"指标": "生成时间", "数值": report.generated_at.strftime("%Y-%m-%d %H:%M:%S")},
            ])
            overview.to_excel(writer, sheet_name="概览", index=False)

            # Sheet 2: TOP 问题
            if report.top_issues:
                issues_df = pd.DataFrame([
                    {"排名": i, "故障码": x.fault_code, "描述": x.fault_desc,
                     "出现次数": x.count, "受影响车辆": x.affected_vehicles,
                     "平均风险": x.avg_risk, "趋势": x.trend}
                    for i, x in enumerate(report.top_issues, 1)
                ])
                issues_df.to_excel(writer, sheet_name="TOP 问题", index=False)

            # Sheet 3: TOP 高风险车辆
            if report.top_vehicles:
                vehicles_df = pd.DataFrame([
                    {"排名": i, "VIN": v.vin, "车型": v.model,
                     "风险评分": v.risk_score, "原因": v.reason}
                    for i, v in enumerate(report.top_vehicles, 1)
                ])
                vehicles_df.to_excel(writer, sheet_name="TOP 高风险车辆", index=False)

            # Sheet 4-6: 分类汇总
            if not fault_level_df.empty:
                fault_level_df.to_excel(writer, sheet_name="故障等级分布", index=False)
            if not sw_version_df.empty:
                sw_version_df.to_excel(writer, sheet_name="软件版本分布", index=False)
            if not region_df.empty:
                region_df.to_excel(writer, sheet_name="地区分布", index=False)

            # Sheet 7: 完整车辆画像
            if profiles:
                profile_df = pd.DataFrame([
                    {"VIN": p.vin, "车型": p.model, "软件版本": p.software_version,
                     "故障总数": p.total_faults, "风险评分": p.risk_score,
                     "风险等级": p.risk_level.value, "软件过旧": p.is_software_outdated,
                     "已知问题版本": p.is_known_bad_version}
                    for p in profiles
                ])
                profile_df.to_excel(writer, sheet_name="车辆画像", index=False)

        return str(filepath)
