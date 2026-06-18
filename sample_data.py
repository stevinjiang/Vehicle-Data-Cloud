# ============================================================
# sample_data.py — 样本数据生成器（仅用于开发测试）
# 功能：生成模拟的车辆故障 CSV 数据，供本地开发和测试使用
#
# 使用：python sample_data.py → 生成 data/raw/sample_vehicle_data.csv
# ============================================================

import csv
import random
import os
from datetime import datetime, timedelta
from pathlib import Path


def generate_sample_data(
    output_dir: str = "./data/raw",
    num_vehicles: int = 100,
    max_faults_per_vehicle: int = 5,
):
    """
    生成样本车辆故障 CSV 数据

    模拟真实场景：
      - 多个 VIN（车架号）
      - 不同车型（轿车/SUV/MPV/新能源）
      - 不同软件版本（含过旧版本和已知问题版本）
      - 多种故障码 + 故障等级
      - 合理的时间分布（最近 60 天内）

    Args:
        output_dir: 输出目录
        num_vehicles: 车辆数
        max_faults_per_vehicle: 每辆车最多故障数
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    # ── 车型池 ──
    models = [
        "V-SUV Pro", "V-Sedan Elite", "V-MPV Family",
        "V-EV Sport", "V-Hybrid Eco", "V-Crossover X",
    ]

    # ── 软件版本池（v1.0/v1.1/v1.2 为过旧版本，v1.0.3 为已知问题版本） ──
    software_versions = [
        "v1.0", "v1.1", "v1.2",       # 过旧版本（config 中配置的）
        "v1.0.3",                       # 已知问题版本 ⚠️
        "v2.0", "v2.1", "v2.1.4",     # 正常版本
        "v3.0", "v3.1.2",             # 最新版本
    ]

    # ── 故障码池（含权重信息） ──
    fault_pool = [
        # (故障码, 故障等级, 描述) — 等级权重: 严重=10, 一般=5, 轻微=2
        ("P1123", "严重", "制动液压力传感器异常可能导致制动失灵"),
        ("P2152", "严重", "高压电池过温风险需立即停车检查"),
        ("B1102", "严重", "安全气囊控制单元通讯丢失"),
        ("U0101", "严重", "变速箱控制模块通讯中断"),
        ("P0300", "一般", "发动机随机失火检测到多缸缺火"),
        ("P0420", "一般", "催化转换器效率低于阈值需要检修"),
        ("C1234", "一般", "ABS 轮速传感器信号异常"),
        ("U0155", "一般", "仪表盘控制模块通讯丢失"),
        ("B1304", "轻微", "空调系统制冷剂压力偏低"),
        ("P0500", "轻微", "车速传感器信号暂时不可用"),
        ("U0401", "轻微", "发动机控制模块收到无效数据"),
        ("C0041", "轻微", "胎压监测系统传感器电池电量低"),
    ]

    # ── 地区池 ──
    regions = ["华东", "华南", "华北", "华中", "西南", "西北", "东北"]

    rows = []
    now = datetime.now()

    for i in range(num_vehicles):
        # 生成17位 VIN（简化模拟，确保不重复）
        vin = f"LSV{random.randint(10000, 99999)}N{random.randint(410000, 419999)}"

        model = random.choice(models)
        # 模拟：15% 概率使用过旧版本，5% 使用已知问题版本
        sw_choice = random.random()
        if sw_choice < 0.05:
            sw = "v1.0.3"  # 已知问题版本
        elif sw_choice < 0.20:
            sw = random.choice(["v1.0", "v1.1", "v1.2"])  # 过旧版本
        else:
            sw = random.choice([v for v in software_versions
                                 if v not in ("v1.0", "v1.1", "v1.2", "v1.0.3")])

        region = random.choice(regions)
        mileage = random.randint(500, 150000)

        # 每辆车随机生成 1 ~ max_faults_per_vehicle 条故障
        num_faults = random.randint(1, max_faults_per_vehicle)
        for j in range(num_faults):
            fault_code, fault_level, fault_desc = random.choice(fault_pool)

            # 故障时间：最近 60 天内随机
            days_ago = random.randint(0, 60)
            fault_time = now - timedelta(days=days_ago,
                                         hours=random.randint(0, 23),
                                         minutes=random.randint(0, 59))

            rows.append({
                "车架号": vin,
                "车型": model,
                "软件版本": sw,
                "故障码": fault_code,
                "故障等级": fault_level,
                "故障描述": fault_desc,
                "故障时间": fault_time.strftime("%Y-%m-%d %H:%M:%S"),
                "里程": mileage,
                "地区": region,
                "数据更新时间": (fault_time + timedelta(minutes=random.randint(1, 60))).strftime("%Y-%m-%d %H:%M:%S"),
            })

    # ── 写入 CSV ──
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"sample_vehicle_data_{timestamp}.csv"
    filepath = Path(output_dir) / filename

    fieldnames = ["车架号", "车型", "软件版本", "故障码", "故障等级", "故障描述",
                  "故障时间", "里程", "地区", "数据更新时间"]

    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"✅ 样本数据已生成: {filepath}")
    print(f"   总车辆数: {num_vehicles}")
    print(f"   总故障记录数: {len(rows)}")
    print(f"   平均每车故障数: {len(rows) / num_vehicles:.1f}")

    # 统计
    severe = sum(1 for r in rows if r["故障等级"] == "严重")
    general = sum(1 for r in rows if r["故障等级"] == "一般")
    minor = sum(1 for r in rows if r["故障等级"] == "轻微")
    print(f"   严重: {severe}, 一般: {general}, 轻微: {minor}")

    old_ver = sum(1 for r in rows if r["软件版本"] in ("v1.0", "v1.1", "v1.2"))
    bad_ver = sum(1 for r in rows if r["软件版本"] == "v1.0.3")
    print(f"   过旧版本记录数: {old_ver}, 已知问题版本记录数: {bad_ver}")


if __name__ == "__main__":
    generate_sample_data()
