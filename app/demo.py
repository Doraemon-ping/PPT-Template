# -*- coding: utf-8 -*-
"""示例数据与默认 LOGO（对应原 HTML 的 loadDemo 与 DEFAULT_LOGO）。"""
import base64
import copy
import os

LOGO_PATH = os.path.join(os.path.dirname(__file__), "assets", "logo.png")

# 表格默认行（与网页表单初始化一致，保证任意 t.* 整表绑定都有数据可解析）
DEFAULT_TABLES = {
    "dfmHist": [
        {"ver": "A0", "date": "2026-08-18", "author": "工艺工程师", "content": "首次发布 DFM 报告", "remark": ""},
        {"ver": "A1", "date": "2026-09-01", "author": "工艺工程师", "content": "补充挤压销与点冷优化方案", "remark": "客户评审后更新"},
    ],
    "fileStat": [
        {"name": "2D 图纸", "code": "", "ver": "", "state": "待提供", "date": "", "remark": ""},
        {"name": "3D 数据", "code": "", "ver": "", "state": "待提供", "date": "", "remark": ""},
        {"name": "ESOW / 技术规范", "code": "", "ver": "", "state": "待提供", "date": "", "remark": ""},
        {"name": "材料标准", "code": "", "ver": "", "state": "待提供", "date": "", "remark": ""},
        {"name": "外观/表面标准", "code": "", "ver": "", "state": "待提供", "date": "", "remark": ""},
        {"name": "装配/接口定义", "code": "", "ver": "", "state": "待提供", "date": "", "remark": ""},
    ],
    "mech": [
        {"zone": "本体（一般区域）", "rm": "≥ 240 MPa", "rp": "≥ 140 MPa", "elong": "≥ 1.5 %", "hb": "", "remark": ""},
        {"zone": "高强区域 / 受力区", "rm": "", "rp": "", "elong": "≥ 2.0 %", "hb": "", "remark": ""},
        {"zone": "延伸率要求区域", "rm": "", "rp": "", "elong": "≥ 3.0 %", "hb": "", "remark": ""},
        {"zone": "气密 / 加工区域", "rm": "", "rp": "", "elong": "", "hb": "", "remark": ""},
    ],
    "matList": [
        {"no": "1", "part": "定模芯", "grade": "1.2343", "hard": "HRC 46~48", "supplier": "", "size": "", "weight": ""},
        {"no": "2", "part": "动模芯", "grade": "1.2343", "hard": "HRC 46~48", "supplier": "", "size": "", "weight": ""},
        {"no": "3", "part": "深腔镶块", "grade": "DIEVAR", "hard": "HRC 48~50", "supplier": "", "size": "", "weight": ""},
        {"no": "4", "part": "滑块座/成型块", "grade": "1.2343", "hard": "HRC 44~46", "supplier": "", "size": "", "weight": ""},
        {"no": "5", "part": "模架（A/B板）", "grade": "P20", "hard": "HRC 28~32", "supplier": "", "size": "", "weight": ""},
        {"no": "6", "part": "浇口套/分流锥", "grade": "DIEVAR", "hard": "HRC 46~48", "supplier": "", "size": "", "weight": ""},
    ],
    "asm": [
        {"item": "定模芯", "l": "", "w": "", "h": "", "wt": "", "remark": ""},
        {"item": "动模芯", "l": "", "w": "", "h": "", "wt": "", "remark": ""},
        {"item": "定模框", "l": "", "w": "", "h": "", "wt": "", "remark": ""},
        {"item": "动模框", "l": "", "w": "", "h": "", "wt": "", "remark": ""},
        {"item": "滑块 1", "l": "", "w": "", "h": "", "wt": "", "remark": ""},
        {"item": "滑块 2", "l": "", "w": "", "h": "", "wt": "", "remark": ""},
        {"item": "模具总装（合模）", "l": "", "w": "", "h": "", "wt": "", "remark": ""},
    ],
    "seal": [
        {"no": "1", "item": "定模冷却水路", "type": "O 型圈", "spec": "", "remark": ""},
        {"no": "2", "item": "动模冷却水路", "type": "O 型圈", "spec": "", "remark": ""},
        {"no": "3", "item": "真空阀接口", "type": "端面密封", "spec": "", "remark": ""},
        {"no": "4", "item": "滑块水路/油路", "type": "O 型圈+挡圈", "spec": "", "remark": ""},
        {"no": "5", "item": "镶块冷却水路", "type": "O 型圈", "spec": "", "remark": ""},
        {"no": "6", "item": "顶杆/推板导柱", "type": "组合密封", "spec": "", "remark": ""},
        {"no": "7", "item": "分流锥/浇口套", "type": "锥面密封", "spec": "", "remark": ""},
        {"no": "8", "item": "型芯冷却（点冷）", "type": "O 型圈+挡圈", "spec": "", "remark": ""},
    ],
    "spr1Table": [
        {"no": "SPR-01", "pos": "", "thick": "", "risk": "中", "act": ""},
    ],
    "tol": [
        {"no": "1", "item": "线性尺寸公差", "req": "", "cap": "GB/T 6414 CT6~CT7", "feas": "可行", "prop": ""},
        {"no": "2", "item": "形位公差（平面度）", "req": "", "cap": "", "feas": "有风险", "prop": ""},
        {"no": "3", "item": "位置度", "req": "", "cap": "", "feas": "可行", "prop": ""},
        {"no": "4", "item": "加工余量", "req": "", "cap": "", "feas": "可行", "prop": ""},
    ],
    "issues": [
        {"no": "1", "desc": "肋端最大壁厚 28.5 mm，存在热节与缩孔风险（ASTM E505 Level 4）",
         "prop": "建议掏料减薄至约 6 mm 并增加点冷", "fb": "", "st": "开放"},
        {"no": "2", "desc": "反拔模区域需滑块抽芯，模具成本上升",
         "prop": "评估产品局部减胶以避免滑块", "fb": "", "st": "待客户确认"},
    ],
}


def default_logo_data_uri():
    """读取内嵌 PNG 并返回 data URI（供 PPT 封面/水印与示例数据使用）。"""
    with open(LOGO_PATH, "rb") as fp:
        b64 = base64.b64encode(fp.read()).decode("ascii")
    return "data:image/png;base64," + b64


def demo_state():
    """构造示例项目状态，结构与前端 S = {f, t, i} 一致。

    表格数据补全为表单默认行（dfmHist / fileStat / issues 等），
    保证任意 t.* 整表绑定都有数据可用。
    """
    f = {
        "projName": "某新能源汽车后纵梁支架",
        "partNo": "TP-HPDC-2026-0087",
        "partName": "Rear Longitudinal Bracket",
        "custName": "XXXX 汽车",
        "version": "A1",
        "dfmDate": "2026-09-01",
        "maker": "工艺工程师",
        "checker": "压铸工艺部经理",
        "approver": "技术总监",
        "company": "TUOPU · 压铸工艺部",
        "machineId": "力劲 LK DCC3000",
        "wFinish": "3.85", "wCast": "4.20", "wRunner": "2.60", "wOverflow": "1.10",
        "wall": "3.0", "wallMax": "28.5", "moldStructure": "1出1",
        "dimL": "486", "dimW": "212", "dimH": "138",
        "cav": "1", "castP": "80", "material": "AlSi10MnMg", "annual": "120000",
        "aPart": "820", "aRunner": "210", "aOver": "130", "aSlider": "260",
        "sliderForceAngle": "10", "lockSafetyFactor": "1.1",
        "pMax2": "80", "exOff": "35", "eyOff": "-20",
        "aDyn": "128162", "aFix": "72827", "alpDyn": "1.5", "alpFix": "1.5",
        "ejZone": "4", "ejDia": "10", "ejSpace": "120",
        "sqL": "86", "sqH": "28.5", "sqW": "42", "sqD": "16", "sqShrink": "2600",
        "slA": "42380", "slAlpha": "1.5", "slStroke": "120", "slNum": "2",
        "vcCav": "1.85", "vcRun": "1.30", "vcSlvD": "120", "vcSlvL": "680",
        "vcTarget": "50", "vcTime": "1.5", "vcPump": "300",
        "injD": "90", "injAg": "560", "injVol": "2900", "injT": "0.120",
        "injSlow": "0.25", "injSwitch": "420", "injIntP": "65",
        "vvType": "机械阀", "vvArea": "150", "vvNum": "2",
        "cwTime": "28", "cwFlow": "160",
        "plLine": "沿产品最大轮廓设置分型线，主分型面位于产品法兰面；局部由滑块成型。",
        "plBase": "保证包紧力主要集中在动模侧；滑块成型区域置于便于抽芯方向；分型线避开外观面与密封面。",
        "insPlan": "动定模芯整体式 + 深腔区域镶拼；镶拼面避开高压区，镶块采用 DIEVAR 并做点冷。",
        "antiDraft": "反拔模区域采用滑块抽芯解决；局部倒扣通过斜销 + 滑块实现，斜度按 1.5° 设计。",
        "dcDesign": "深腔区域（肋端厚大处）采用镶块 + 点冷，镶块材料 DIEVAR，配合间隙 H7/g6。",
        "grText": "采用单侧扇形浇口 + 多分支流道，金属液自远端向近端充填；末端设置渣包与排气块配合真空阀。",
        "vvText": "采用机械真空阀 + 排气块组合，抽气时间 1.5 s，目标真空度 50 mbar。",
        "sqLayout": "厚大肋端布置 2 支 φ16 挤压销，由油缸驱动，增压后延时 0.6 s 触发。",
        "tText": "定模 200 ℃、动模 220 ℃，采用模温机 + 点冷独立控制，开机前预热至 180 ℃。",
        "isTemp": "压铸岛配置模温机 2 台（定/动模各 1），点冷机组 1 台，配备水温/流量在线监控。",
        "isSprayText": "六轴机器人喷涂，微量喷涂 + 定点吹干，喷涂量按节拍自动调节。",
        "isVac": "真空泵 300 m³/h，真空罐 200 L，真空阀机械式，配备真空度在线监测与报警。",
        "coIntro": "公司专注于铝合金高压压铸结构件研发与制造，具备 840T~7200T 压铸机、模流分析、模具设计与制造、精密加工全链条能力。",
        "trPos": "产品非外观面凸台（避开加工与装配区域）",
        "trContent": "零件号 + 日期 + 班次 + 模号 + 流水号",
        "f08Astm": "ASTM E505 Level 4",
        "f08Area": "肋端厚大区域（最大壁厚 28.5 mm）",
        "f08Cool": "增设点冷（φ10 点冷棒 2 支），并优化挤压销补偿",
        "f01Conc": "内浇口速度 40.2 m/s，处于壁厚 3.0 mm 推荐区间（35~45 m/s），充填平稳。",
        "f01Opt": "可维持现有内浇口面积，建议在试模阶段校核实际速度波动。",
        "f08Conc": "肋端厚大处存在缩孔，等级 ASTM E505 Level 4，超出关键区域要求（≤ Level 2）。",
        "f08Opt": "增设点冷并采用挤压销局部加压补偿；同步建议产品掏料减薄。",
    }
    t = copy.deepcopy(DEFAULT_TABLES)
    i = {"logoImg": [default_logo_data_uri()]}
    return {"f": f, "t": t, "i": i}
