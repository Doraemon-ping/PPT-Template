# -*- coding: utf-8 -*-
"""压铸机参数库（力劲 / 布勒，参考数据，可按实际设备维护）与常用常量。

对应原 HTML 工具中的 MACHINES / EJECT_SPEC / GATE_SPEED_TABLE / ASTM_LEVELS。
"""
import math

# ---------- 单位常量 ----------
TON_N = 9806.65      # 1 吨力(tf) = 9806.65 N
N_TON = 1 / 9806.65  # N -> 吨力
KN_TON = 1 / 9.80665  # kN -> 吨力
RHO_AL = 2.7e-6      # 铝合金密度 kg/mm³ (2.7 g/cm³)

# ---------- 压铸机参数库 ----------
MACHINES = [
    {"brand": "力劲 LK", "model": "DCC7200", "ton": 7200, "lock": 72000, "open": 1600, "moldMin": 900, "moldMax": 2000,
     "tie": "2100×2100", "tieDia": 280, "injForce": 1200, "injStroke": 1600, "punch": [160, 180, 200, 220], "v0": 6.0,
     "ejForce": 1200, "ejStroke": 400, "plate": "2400×2400"},
    {"brand": "力劲 LK", "model": "DCC4500", "ton": 4500, "lock": 45000, "open": 1300, "moldMin": 750, "moldMax": 1700,
     "tie": "1750×1750", "tieDia": 240, "injForce": 900, "injStroke": 1300, "punch": [130, 140, 150, 160, 180], "v0": 6.5,
     "ejForce": 900, "ejStroke": 350, "plate": "2050×2050"},
    {"brand": "力劲 LK", "model": "DCC3000", "ton": 3000, "lock": 30000, "open": 1150, "moldMin": 600, "moldMax": 1500,
     "tie": "1500×1500", "tieDia": 210, "injForce": 700, "injStroke": 1150, "punch": [110, 120, 130, 140, 160], "v0": 7.0,
     "ejForce": 700, "ejStroke": 300, "plate": "1780×1780"},
    {"brand": "力劲 LK", "model": "DCC2800", "ton": 2800, "lock": 28000, "open": 1100, "moldMin": 580, "moldMax": 1450,
     "tie": "1450×1450", "tieDia": 200, "injForce": 650, "injStroke": 1100, "punch": [100, 110, 120, 130, 150], "v0": 7.0,
     "ejForce": 650, "ejStroke": 300, "plate": "1720×1720"},
    {"brand": "力劲 LK", "model": "DCC2000", "ton": 2000, "lock": 20000, "open": 950, "moldMin": 500, "moldMax": 1250,
     "tie": "1250×1250", "tieDia": 180, "injForce": 500, "injStroke": 950, "punch": [90, 100, 110, 120, 140], "v0": 7.5,
     "ejForce": 500, "ejStroke": 250, "plate": "1500×1500"},
    {"brand": "力劲 LK", "model": "DCC840", "ton": 840, "lock": 8400, "open": 700, "moldMin": 350, "moldMax": 900,
     "tie": "900×900", "tieDia": 140, "injForce": 300, "injStroke": 700, "punch": [60, 70, 80, 90, 100], "v0": 6.0,
     "ejForce": 300, "ejStroke": 200, "plate": "1120×1120"},
    {"brand": "布勒 Bühler", "model": "Evolution 4400", "ton": 4400, "lock": 44000, "open": 1300, "moldMin": 700, "moldMax": 1750,
     "tie": "1700×1700", "tieDia": 235, "injForce": 880, "injStroke": 1300, "punch": [130, 140, 150, 160, 180], "v0": 6.5,
     "ejForce": 880, "ejStroke": 350, "plate": "2000×2000"},
    {"brand": "布勒 Bühler", "model": "Evolution 4000", "ton": 4000, "lock": 40000, "open": 1250, "moldMin": 700, "moldMax": 1700,
     "tie": "1650×1650", "tieDia": 225, "injForce": 820, "injStroke": 1250, "punch": [130, 140, 150, 160, 170], "v0": 6.5,
     "ejForce": 820, "ejStroke": 350, "plate": "1950×1950"},
    {"brand": "布勒 Bühler", "model": "Evolution 2800", "ton": 2800, "lock": 28000, "open": 1100, "moldMin": 580, "moldMax": 1450,
     "tie": "1450×1450", "tieDia": 200, "injForce": 650, "injStroke": 1100, "punch": [100, 110, 120, 130, 150], "v0": 7.0,
     "ejForce": 650, "ejStroke": 300, "plate": "1720×1720"},
    {"brand": "布勒 Bühler", "model": "Evolution 1400", "ton": 1400, "lock": 14000, "open": 850, "moldMin": 450, "moldMax": 1100,
     "tie": "1150×1150", "tieDia": 165, "injForce": 420, "injStroke": 850, "punch": [80, 90, 100, 110, 120], "v0": 7.0,
     "ejForce": 420, "ejStroke": 250, "plate": "1400×1400"},
    {"brand": "布勒 Bühler", "model": "Evolution 840", "ton": 840, "lock": 8400, "open": 700, "moldMin": 350, "moldMax": 900,
     "tie": "900×900", "tieDia": 140, "injForce": 300, "injStroke": 700, "punch": [60, 70, 80, 90, 100], "v0": 6.0,
     "ejForce": 300, "ejStroke": 200, "plate": "1120×1120"},
]

DEFAULT_MACHINE_ID = "力劲 LK DCC3000"


def machine_by_id(machine_id):
    """按 '品牌 型号' 查找机型，找不到返回 None。"""
    if not machine_id:
        return None
    for m in MACHINES:
        if m["brand"] + " " + m["model"] == machine_id:
            return m
    return None


def cur_machine(f):
    """当前选中机型；未选中时默认 DCC3000（MACHINES[2]）。"""
    m = machine_by_id(f.get("machineId", ""))
    return m or MACHINES[2]


# ---------- 顶杆规格参考（∅4 ~ ∅12，许用应力 50 MPa） ----------
def build_eject_spec(stress_mpa=50):
    spec = []
    for d in [4, 5, 6, 8, 10, 12]:
        A = math.pi * d * d / 4          # 截面积 mm²
        F = stress_mpa * A               # 许用顶出力 N
        spec.append({
            "d": d, "A": A, "F": F, "ton": F * N_TON,
            "boss": "建议加凸台" if d <= 6 else "视布置空间可选",
            "mark": "凹入 0~0.2 mm",
        })
    return spec


EJECT_SPEC = build_eject_spec()

# ---------- 壁厚 - 内浇口速度经验对照表 ----------
# [壁厚区间, 内浇口速度 m/s, 说明, 阈值(供程序选择, 取区间下界)]
GATE_SPEED_TABLE = [
    ["≤1.5", "45 ~ 60", "薄壁件，需高速充填避免冷隔"],
    ["1.5 ~ 2.5", "40 ~ 50", "常规薄壁结构件"],
    ["2.5 ~ 3.5", "35 ~ 45", "常规结构件主流区间"],
    ["3.5 ~ 5.0", "30 ~ 40", "中等壁厚，兼顾卷气"],
    ["5.0 ~ 8.0", "25 ~ 35", "厚壁件，降低速度减少冲刷"],
    ["> 8.0", "20 ~ 28", "厚大件/局部挤压补缩"],
]

# 程序按壁厚选择推荐行时使用的阈值（修复原 HTML 中 parseFloat('≤1.5'/' > 8.0') 得到 NaN→0 导致恒选末行的缺陷）
GATE_SPEED_THRESHOLDS = [0.0, 1.5, 2.5, 3.5, 5.0, 8.0]


def pick_gate_speed_row(wall):
    """按基本壁厚返回 GATE_SPEED_TABLE 中的推荐行。"""
    rec = GATE_SPEED_TABLE[0]
    for row, lo in zip(GATE_SPEED_TABLE, GATE_SPEED_THRESHOLDS):
        if wall >= lo:
            rec = row
    return rec


# ---------- ASTM E505 缩孔等级 ----------
ASTM_LEVELS = [
    "ASTM E505 Level 1", "ASTM E505 Level 2", "ASTM E505 Level 3", "ASTM E505 Level 4",
    "ASTM E505 Level 5", "ASTM E505 Level 6", "ASTM E505 Level 7", "ASTM E505 Level 8",
]

# 常用油缸缸径系列
CYL_STD = [32, 40, 50, 63, 80, 100, 125, 140, 160, 180, 200]


def pick_std(arr, val):
    """返回 >= val 的第一个标准值，否则返回末位。"""
    for a in arr:
        if a >= val:
            return a
    return arr[-1]
