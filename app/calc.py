# -*- coding: utf-8 -*-
"""工艺计算引擎（Python 版）。

对应原 HTML 工具第 ④ 部分的全部 calc_* / r_* 函数：
结果统一返回 {"html": 界面结果HTML, "verdict": PPT 用纯文本结论}。
"""
import math

from .machines import (
    MACHINES, cur_machine, EJECT_SPEC, GATE_SPEED_TABLE, ASTM_LEVELS,
    CYL_STD, pick_std, pick_gate_speed_row, TON_N, N_TON, KN_TON,
)
from .utils import num, fmt, esc, sstr, T, N, V


# =========================================================================
# 通用显示件（HTML）
# =========================================================================
def pill(t, txt):
    return '<span class="pill p-' + t + '">' + esc(txt) + '</span>'


def verdict_html(t, text):
    return '<div class="verdict v-' + t + '">' + text + '</div>'


def KV(items):
    parts = []
    for it in items:
        val = '<span class="rv">' + it["v"] + '</span>' if it.get("red") else esc(it["v"])
        u = ' <span class="u">' + esc(it["u"]) + '</span>' if it.get("u") else ''
        parts.append('<div><div class="k">' + esc(it["k"]) + '</div><div class="v">' + val + u + '</div></div>')
    return '<div class="kv">' + ''.join(parts) + '</div>'


def ROT(head, rows):
    h = '<table class="ro"><thead><tr>' + ''.join('<th>' + esc(x) + '</th>' for x in head) + '</tr></thead><tbody>'
    for r in rows:
        tds = []
        for c in r:
            if isinstance(c, dict):
                cls = []
                if c.get("n"):
                    cls.append("n")
                if c.get("hi"):
                    cls.append("hi")
                cls_attr = (' class="' + ' '.join(cls) + '"') if cls else ''
                tds.append('<td' + cls_attr + '>' + esc(c.get("t", "")) + '</td>')
            else:
                tds.append('<td>' + esc(c) + '</td>')
        h += '<tr>' + ''.join(tds) + '</tr>'
    return h + '</tbody></table>'


def _result(html, verdict=""):
    return {"html": html, "verdict": verdict}


# =========================================================================
# 2.2 胀型力 / 锁模力
# 单位换算：1 MPa × 1 cm² = 100 N = 0.1 kN
# =========================================================================
def calc_force(f):
    P = N(f, 'castP')
    cav = max(1, N(f, 'cav'))
    aPart = N(f, 'aPart') * cav
    aRunner = N(f, 'aRunner') * cav
    aOver = N(f, 'aOver') * cav
    aProd = aPart + aRunner + aOver                                  # 产品+流道+渣包 总投影 cm²
    aSl = N(f, 'aSlider')                                             # 滑块投影 cm²
    slider_angle = N(f, 'sliderForceAngle')
    slider_factor = math.tan(math.radians(slider_angle)) if slider_angle else 1.0
    fPart = P * aPart / 10
    fRunner = P * aRunner / 10
    fOver = P * aOver / 10
    fProd = fPart + fRunner + fOver                                   # 产品+流道+渣包胀型力 kN
    fSl = P * aSl / 10 * slider_factor                                # 滑块胀型力 kN
    fTot = fProd + fSl                                                # 总胀型力 kN
    mach = cur_machine(f)
    lock = N(f, 'lockKN') or mach["lock"]                             # 设备锁模力 kN
    limit = N(f, 'useRatio') or 85
    ratio = fTot / lock * 100 if lock else 0
    needLock = fTot / (limit / 100) if limit else 0
    return {
        "P": P, "cav": cav, "aPart": aPart, "aRunner": aRunner, "aOver": aOver,
        "aProd": aProd, "aSl": aSl, "aTot": aProd + aSl,
        "fPart": fPart, "fRunner": fRunner, "fOver": fOver,
        "sliderAngle": slider_angle, "sliderFactor": slider_factor,
        "fProd": fProd, "fSl": fSl, "fTot": fTot, "fTotT": fTot * KN_TON,
        "lock": lock, "limit": limit, "ratio": ratio, "needLock": needLock,
        "mach": mach, "ok": ratio <= limit and ratio > 0,
    }


def r_force(f):
    c = calc_force(f)
    if not c["aTot"]:
        return _result('<h4>胀型力 / 锁模力校核</h4><div class="hint">请先在 2.1 / 2.2 中填写投影面积与铸造压力。</div>')
    st = 'ok' if c["ratio"] <= c["limit"] else ('warn' if c["ratio"] <= 95 else 'bad')
    html = ('<h4>胀型力 / 锁模力校核 <span class="st">'
            + pill(st, ('满足' if c["ok"] else '超出') + ' · 利用率 ' + fmt(c["ratio"], 1) + '%')
            + '</span></h4>'
            + KV([
                {"k": "产品胀型力", "v": fmt(c["fProd"], 1), "u": "kN", "red": True},
                {"k": "滑块胀型力", "v": fmt(c["fSl"], 1), "u": "kN", "red": True},
                {"k": "总胀型力", "v": fmt(c["fTot"], 1), "u": "kN", "red": True},
                {"k": "总胀型力", "v": fmt(c["fTotT"], 1), "u": "吨", "red": True},
                {"k": "总投影面积", "v": fmt(c["aTot"], 1), "u": "cm²"},
                {"k": "设备锁模力", "v": fmt(c["lock"], 0), "u": "kN"},
                {"k": "锁模力利用率", "v": fmt(c["ratio"], 1), "u": "%", "red": True},
                {"k": "满足上限所需最小锁模力", "v": fmt(c["needLock"], 0), "u": "kN", "red": True},
            ])
            + ROT(['项目', '产品+流道+渣包', '滑块', '合计'], [
                ['投影面积 cm²', fmt(c["aProd"], 1), fmt(c["aSl"], 1), {"t": fmt(c["aTot"], 1), "hi": True}],
                ['胀型力 kN', fmt(c["fProd"], 1), fmt(c["fSl"], 1), {"t": fmt(c["fTot"], 1), "hi": True}],
                ['胀型力 吨', fmt(c["fProd"] * KN_TON, 1), fmt(c["fSl"] * KN_TON, 1), {"t": fmt(c["fTotT"], 1), "hi": True}],
            ]))
    if c["ok"]:
        vcls, verdict = 'ok', ('🟢 设备锁模力满足要求（利用率 ' + fmt(c["ratio"], 1) + '% ≤ ' + fmt(c["limit"], 0)
                               + '%）。建议实际生产比压不超过 ' + fmt(c["P"], 0) + ' MPa。')
    elif st == 'warn':
        vcls, verdict = 'warn', ('🟡 锁模力利用率 ' + fmt(c["ratio"], 1) + '%，已超过 ' + fmt(c["limit"], 0)
                                 + '% 的建议上限，余量偏小：建议降低铸造比压至 '
                                 + fmt(c["P"] * c["limit"] / max(c["ratio"], 0.01), 0)
                                 + ' MPa，或评估更大吨位机型。')
    else:
        vcls, verdict = 'bad', ('🔴 锁模力不足：所需最小锁模力 ' + fmt(c["needLock"], 0) + ' kN，当前 '
                                + fmt(c["lock"], 0) + ' kN。建议改用更大吨位机型（当前参考机型 '
                                + c["mach"]["brand"] + ' ' + c["mach"]["model"] + '）。')
    html += verdict_html(vcls, verdict)
    return _result(html, verdict)


# =========================================================================
# 2.3 哥林柱受力分布与平衡度
# Rᵢ = F/4 × (1 ± 2ex/Bx ± 2ey/By)（刚性模板 + 四角对称支撑假定）
# =========================================================================
def calc_tiebar(f):
    fc = calc_force(f)
    F = fc["fTot"]
    tie = str(fc["mach"]["tie"])
    parts = tie.split('×')
    Bx = N(f, 'tieX') or (float(parts[0]) if parts else 0)
    By = N(f, 'tieY') or (float(parts[1]) if len(parts) > 1 else Bx)
    ex = N(f, 'exOff')
    ey = N(f, 'eyOff')
    q = F / 4
    bars = []
    for name, sx, sy in [('左上 (−x, +y)', -1, 1), ('右上 (+x, +y)', 1, 1),
                         ('左下 (−x, −y)', -1, -1), ('右下 (+x, −y)', 1, -1)]:
        r = q * (1 + sx * 2 * ex / Bx + sy * 2 * ey / By) if Bx and By else q
        bars.append({"n": name, "s": [sx, sy], "r": r, "t": r * KN_TON, "pct": r / F * 100 if F else 0})
    rs = [b["r"] for b in bars]
    fmax = max(rs)
    fmin = min(rs)
    avg = F / 4
    bal = (fmax - fmin) / avg * 100 if avg else 0
    dia = N(f, 'tieDia') or fc["mach"]["tieDia"]
    area = math.pi * dia * dia / 4
    stressMax = fmax * 1000 / area if area else 0
    return {
        "F": F, "Bx": Bx, "By": By, "ex": ex, "ey": ey, "bars": bars,
        "fmax": fmax, "fmin": fmin, "avg": avg, "bal": bal, "dia": dia,
        "area": area, "stressMax": stressMax,
        "pMax2": N(f, 'pMax2') or fc["P"], "limit": N(f, 'useRatio') or 85,
        "ok": bal <= 10, "warn": bal <= 20,
    }


def r_tiebar(f):
    c = calc_tiebar(f)
    st = 'ok' if c["bal"] <= 10 else ('warn' if c["bal"] <= 20 else 'bad')
    neg = any(b["r"] < 0 for b in c["bars"])
    html = ('<h4>哥林柱受力分布与平衡度 <span class="st">' + pill(st, '平衡度 ' + fmt(c["bal"], 1) + '%')
            + '</span></h4>'
            + KV([
                {"k": "最大铸造比压", "v": fmt(c["pMax2"], 0), "u": "MPa"},
                {"k": "总胀型力 F", "v": fmt(c["F"], 1), "u": "kN", "red": True},
                {"k": "单柱平均受力", "v": fmt(c["avg"], 1), "u": "kN"},
                {"k": "最大单柱受力", "v": fmt(c["fmax"], 1), "u": "kN", "red": True},
                {"k": "最小单柱受力", "v": fmt(c["fmin"], 1), "u": "kN", "red": True},
                {"k": "受力平衡度", "v": fmt(c["bal"], 1), "u": "%", "red": True},
                {"k": "哥林柱直径", "v": fmt(c["dia"], 0), "u": "mm"},
                {"k": "最大拉应力", "v": fmt(c["stressMax"], 1), "u": "MPa", "red": True},
            ])
            + ROT(['哥林柱位置', '坐标 (±Bx/2, ±By/2)', '受力 kN', '受力 吨', '占比 %'],
                  [[''.join([b["n"], ' (', ('+' if b["s"][0] > 0 else '−'), fmt(c["Bx"] / 2, 0), ', ',
                             ('+' if b["s"][1] > 0 else '−'), fmt(c["By"] / 2, 0), ')']),
                    {"t": fmt(b["r"], 1), "n": True, "hi": abs(b["r"] - c["fmax"]) < 0.01},
                    {"t": fmt(b["t"], 2), "n": True}, {"t": fmt(b["pct"], 1), "n": True}]
                   for b in c["bars"]]))
    if neg:
        vcls, verdict = 'bad', ('🔴 出现负反力（单柱卸载甚至出现张口趋势），必须调整：'
                                '① 将铸件/流道向模具中心偏移，减小形心偏移 ex/ey；'
                                '② 增加对称流道或工艺平衡块；③ 改用更大吨位机型。')
    elif st == 'ok':
        vcls, verdict = 'ok', ('🟢 四柱受力平衡度 ' + fmt(c["bal"], 1) + '% ≤ 10%，偏载小，模具与哥林柱受力均匀。')
    elif st == 'warn':
        vcls, verdict = 'warn', ('🟡 平衡度 ' + fmt(c["bal"], 1) + '%（10% ~ 20%），存在一定偏载。'
                                 '建议优化浇注位置：将形心偏移控制在 ±'
                                 + fmt(min(c["Bx"], c["By"]) * 0.04, 0) + ' mm 以内，并加强定模板刚度。')
    else:
        vcls, verdict = 'bad', ('🔴 平衡度 ' + fmt(c["bal"], 1) + '% > 20%，偏载严重，易造成飞料、'
                                '哥林柱早期疲劳与模具偏磨。必须重新布置型腔/流道，必要时采用偏心浇口或增加平衡块。')
    html += verdict_html(vcls, verdict)
    return _result(html, verdict)


# =========================================================================
# 3.1 包紧力  F = K·A·P·(η·cosα − sinα)/10000  (吨)
# =========================================================================
def holdF(A, alpha_deg, K, P, eta):
    a = alpha_deg * math.pi / 180
    k = eta * math.cos(a) - math.sin(a)
    if k < 0:
        k = 0
    return K * A * P * k / 10000


def calc_hold(f):
    K = N(f, 'kHold') or 1.1
    P = N(f, 'pHold') or 10
    eta = N(f, 'etaHold') or 0.25
    fd = holdF(N(f, 'aDyn'), N(f, 'alpDyn'), K, P, eta)
    ff = holdF(N(f, 'aFix'), N(f, 'alpFix'), K, P, eta)
    return {"K": K, "P": P, "eta": eta, "aDyn": N(f, 'aDyn'), "aFix": N(f, 'aFix'),
            "fd": fd, "ff": ff, "sum": fd + ff, "ratio": fd / ff if ff else 0}


def r_hold(f):
    c = calc_hold(f)
    if not c["aDyn"] and not c["aFix"]:
        return _result('<h4>包紧力计算</h4><div class="hint">请填写动/定模侧包紧面积。</div>')
    dyn_big = c["fd"] >= c["ff"]
    html = ('<h4>包紧力计算 <span class="st">'
            + pill('ok' if dyn_big else 'bad', '动模侧包紧力更大 · 分型合理' if dyn_big else '动模侧偏小 · 需调整')
            + '</span></h4>'
            + KV([
                {"k": "动模侧包紧面积", "v": fmt(c["aDyn"], 0), "u": "mm²"},
                {"k": "定模侧包紧面积", "v": fmt(c["aFix"], 0), "u": "mm²"},
                {"k": "动模侧包紧力", "v": fmt(c["fd"], 2), "u": "吨", "red": True},
                {"k": "定模侧包紧力", "v": fmt(c["ff"], 2), "u": "吨", "red": True},
                {"k": "包紧力合计", "v": fmt(c["sum"], 2), "u": "吨", "red": True},
                {"k": "动/定模包紧力比", "v": fmt(c["ratio"], 2), "red": True},
            ]))
    if dyn_big:
        vcls, verdict = 'ok', ('🟢 分型面结论：动模侧包紧力（' + fmt(c["fd"], 2) + ' 吨）≥ 定模侧（'
                               + fmt(c["ff"], 2) + ' 吨），开模后铸件将可靠地留在动模侧，由顶杆顶出，分型方案合理。')
    else:
        vcls, verdict = 'bad', ('🔴 分型面结论：定模侧包紧力（' + fmt(c["ff"], 2) + ' 吨）大于动模侧（'
                                + fmt(c["fd"], 2) + ' 吨），铸件有粘定模风险。修改方案：'
                                '① 减小定模侧拔模斜度或减小定模包紧面积；② 在动模侧增加粘模槽/拉钩/倒扣包紧结构；'
                                '③ 调整分型线，将更多包紧结构置于动模侧；④ 定模设置定模顶出或气动辅助脱模。')
    html += verdict_html(vcls, verdict)
    return _result(html, verdict)


# =========================================================================
# 3.2 顶杆顶出力与规格选型
# =========================================================================
def calc_eject(f):
    h = calc_hold(f)
    safe = N(f, 'ejSafe') or 1.2
    stress = N(f, 'ejStress') or 50
    d = N(f, 'ejDia') or 10
    A = math.pi * d * d / 4
    f1 = stress * A                       # 单根许用顶出力 N
    fNeed = h["fd"] * safe * TON_N        # 所需总顶出力 N
    nNeed = math.ceil(fNeed / f1) if f1 else 0
    zones = max(1, round(N(f, 'ejZone') or 1))
    per_zone = math.ceil(nNeed / zones) if zones else nNeed
    n_rec = per_zone * zones
    cap = N(f, 'ejSpace')
    spec = []
    for s in EJECT_SPEC:
        spec.append({"d": s["d"], "A": s["A"], "F": s["F"],
                     "ton": stress * s["A"] * N_TON,
                     "n": math.ceil(fNeed / (stress * s["A"])) if s["A"] else 0,
                     "boss": s["boss"], "mark": s["mark"]})
    return {"h": h, "safe": safe, "stress": stress, "d": d, "A": A, "f1": f1,
            "f1T": f1 * N_TON, "fNeed": fNeed, "fNeedT": h["fd"] * safe,
            "nNeed": nNeed, "zones": zones, "perZone": per_zone, "nRec": n_rec,
            "cap": cap, "ok": (not cap) or n_rec <= cap, "spec": spec}


def r_eject(f):
    c = calc_eject(f)
    if not c["h"]["fd"]:
        return _result('<h4>顶杆顶出力</h4><div class="hint">请先在 3.1 完成包紧力计算。</div>')
    st = 'ok' if c["ok"] else 'bad'
    html = ('<h4>顶杆顶出力与选型 <span class="st">'
            + pill(st, '布置可行' if c["ok"] else '超出可布置上限')
            + '</span></h4>'
            + KV([
                {"k": "动模侧包紧力", "v": fmt(c["h"]["fd"], 2), "u": "吨"},
                {"k": "顶出安全系数", "v": fmt(c["safe"], 2)},
                {"k": "所需总顶出力", "v": fmt(c["fNeedT"], 2), "u": "吨", "red": True},
                {"k": "选用顶杆直径", "v": 'φ' + sstr(c["d"]), "u": "mm"},
                {"k": "单根许用顶出力", "v": fmt(c["f1"], 0), "u": "N", "red": True},
                {"k": "单根许用顶出力", "v": fmt(c["f1T"], 3), "u": "吨", "red": True},
                {"k": "所需根数（向上取整）", "v": str(c["nNeed"]), "red": True},
                {"k": "顶出分区数量", "v": str(c["zones"]), "u": "区"},
                {"k": "每区根数", "v": str(c["perZone"]), "red": True},
                {"k": "推荐总数（对称布置）", "v": str(c["nRec"]), "red": True},
                {"k": "可布置上限", "v": sstr(c["cap"]) if c["cap"] else '—', "u": "根"},
            ])
            + '<h4 style="margin-top:12px">∅4 ~ ∅12 顶杆规格表（许用应力 ' + fmt(c["stress"], 0) + ' MPa）</h4>'
            + ROT(['顶杆直径', '截面积 mm²', '许用顶出力 N', '许用顶出力 吨', '所需根数', '是否加凸台', '凹入产品标识'],
                  [['φ' + str(s["d"]), {"t": fmt(s["A"], 2), "n": True}, {"t": fmt(s["F"], 0), "n": True},
                    {"t": fmt(s["ton"], 3), "n": True}, {"t": str(s["n"]), "n": True, "hi": s["d"] == c["d"]},
                    s["boss"], s["mark"]] for s in c["spec"]]))
    if c["ok"]:
        vcls, verdict = 'ok', ('🟢 顶出方案：选用 φ' + sstr(c["d"]) + ' 顶杆，共 ' + str(c["nRec"])
                               + ' 根（' + str(c["zones"]) + ' 个分区，每区 ' + str(c["perZone"]) + ' 根），'
                               + '总顶出力 ' + fmt(c["nRec"] * c["f1T"], 2) + ' 吨 ≥ 所需 '
                               + fmt(c["fNeedT"], 2) + ' 吨，满足要求。顶杆端面建议凹入产品表面 0~0.2 mm。')
    else:
        nd = 10 if c["d"] < 10 else 12
        adj_area = 100 if c["d"] < 10 else 144
        vcls, verdict = 'bad', ('🔴 布置空间不足：推荐 ' + str(c["nRec"]) + ' 根，可布置上限仅 '
                                + sstr(c["cap"]) + ' 根。修改方案：① 增大顶杆直径至 φ' + str(nd)
                                + '（单根许用 ' + fmt(c["stress"] * math.pi * adj_area / 4, 0)
                                + ' N）；② 采用扁顶杆/顶块/顶管替代圆顶杆；③ 减小动模侧包紧面积或增大动模侧拔模斜度；'
                                '④ 局部增加顶出板二次顶出结构。')
    html += verdict_html(vcls, verdict)
    return _result(html, verdict)


# =========================================================================
# 3.3 挤压销：V = L·h·w·a（a=6%），行程 d = V / 截面积
# =========================================================================
def calc_squeeze(f):
    L, h, w = N(f, 'sqL'), N(f, 'sqH'), N(f, 'sqW')
    a = N(f, 'sqA') / 100 or 0.06
    V = L * h * w * a
    d = N(f, 'sqD')
    As = math.pi * d * d / 4
    stroke = V / As if As else 0
    P = N(f, 'sqP') or 80
    Fsq = P * As / 1000
    mu = N(f, 'sqMu') or 0.15
    Lg = N(f, 'sqLg') or 0
    Ffr = mu * P * math.pi * d * Lg / 1000
    Foth = 0.3 * Fsq
    Fres = Ffr + Foth
    Ftot = Fsq + Fres
    sysP = N(f, 'sqSysP') or 16
    Dcyl = math.sqrt(4 * Ftot * 1000 / (math.pi * sysP)) if Ftot > 0 else 0
    Dstd = pick_std(CYL_STD, Dcyl)
    Freal = sysP * math.pi * Dstd * Dstd / 4 / 1000
    shrink = N(f, 'sqShrink')
    return {"L": L, "h": h, "w": w, "a": a, "V": V, "d": d, "As": As, "stroke": stroke,
            "P": P, "Fsq": Fsq, "Ffr": Ffr, "Foth": Foth, "Fres": Fres, "Ftot": Ftot,
            "sysP": sysP, "Dcyl": Dcyl, "Dstd": Dstd, "Freal": Freal, "shrink": shrink,
            "ratio": stroke / d if d else 0,
            "cover": V / shrink if shrink else 0,
            "ok": (stroke > 0 and stroke <= 50 and d and Dstd > 0 and Freal >= Ftot)}


def r_squeeze(f):
    c = calc_squeeze(f)
    if not c["V"]:
        return _result('<h4>挤压销计算</h4><div class="hint">请填写挤压区域尺寸 L / h / w 与挤压销直径。</div>')
    st = 'ok' if c["ok"] else 'warn'
    html = ('<h4>挤压销计算 <span class="st">' + pill(st, '方案可行' if c["ok"] else '需复核参数')
            + '</span></h4>'
            + KV([
                {"k": "挤压体积 V", "v": fmt(c["V"], 1), "u": "mm³", "red": True},
                {"k": "挤压销直径 d", "v": fmt(c["d"], 1), "u": "mm"},
                {"k": "挤压销截面积", "v": fmt(c["As"], 2), "u": "mm²"},
                {"k": "挤压行程", "v": fmt(c["stroke"], 2), "u": "mm", "red": True},
                {"k": "挤压比压 P局", "v": fmt(c["P"], 0), "u": "MPa"},
                {"k": "挤压力", "v": fmt(c["Fsq"], 2), "u": "kN", "red": True},
                {"k": "摩擦阻力", "v": fmt(c["Ffr"], 2), "u": "kN"},
                {"k": "附加背压阻力", "v": fmt(c["Foth"], 2), "u": "kN"},
                {"k": "挤压阻力合计", "v": fmt(c["Fres"], 2), "u": "kN", "red": True},
                {"k": "油缸需推力", "v": fmt(c["Ftot"], 2), "u": "kN", "red": True},
                {"k": "理论缸径", "v": fmt(c["Dcyl"], 1), "u": "mm", "red": True},
                {"k": "选用标准缸径", "v": '∅' + str(c["Dstd"]), "u": "mm", "red": True},
                {"k": "标准缸实际推力", "v": fmt(c["Freal"], 2), "u": "kN", "red": True},
                {"k": "行程/直径比", "v": fmt(c["ratio"], 2), "red": True},
            ]))
    verdict = ('挤压力校核：标准缸 ∅' + str(c["Dstd"]) + ' 实际推力 ' + fmt(c["Freal"], 1) + ' kN '
               + ('≥' if c["Freal"] >= c["Ftot"] else '＜') + ' 所需 ' + fmt(c["Ftot"], 1) + ' kN，'
               + ('满足要求。' if c["Freal"] >= c["Ftot"] else '推力不足，需加大缸径或提高系统压力。')
               + ' 行程 ' + fmt(c["stroke"], 2) + ' mm（行程/直径比 ' + fmt(c["ratio"], 2) + '，'
               + ('稳定性良好。' if c["ratio"] <= 3 else '长径比偏大，建议加大销径或减小挤压体积以防失稳。') + ')')
    if c["shrink"]:
        verdict += (' 体积补偿率 V/V缩孔 = ' + fmt(c["cover"], 2)
                    + ('，可覆盖缩孔。' if c["cover"] >= 1 else '，不足以覆盖缩孔，建议增大销径或增加挤压销数量。'))
    verdict += ' 结论：' + ('可行，建议按此方案布置挤压销。' if c["ok"] else '需复核参数后再定案。')
    html += verdict_html(st, verdict)
    return _result(html, verdict)


# =========================================================================
# 3.4 滑块油缸缸径：抽芯力 = K × 抽芯阻力（K=1.3）
# =========================================================================
def calc_slider(f):
    A = N(f, 'slA')
    alpha = N(f, 'slAlpha')
    K = N(f, 'slK') or 1.3
    Fres = holdF(A, alpha, N(f, 'kHold') or 1.1, N(f, 'pHold') or 10, N(f, 'etaHold') or 0.25)
    Fpull = K * Fres
    mu = N(f, 'slMu') or 0.15
    Ffric = mu * Fres
    Fneed = Fpull + Ffric
    sysP = N(f, 'slSysP') or 16
    Dcyl = math.sqrt(4 * Fneed * TON_N / (math.pi * sysP)) if Fneed > 0 else 0
    Dstd = pick_std(CYL_STD, Dcyl)
    Freal = sysP * math.pi * Dstd * Dstd / 4 * N_TON
    num = max(1, N(f, 'slNum') or 1)
    return {"A": A, "alpha": alpha, "K": K, "Fres": Fres, "Fpull": Fpull, "Ffric": Ffric,
            "Fneed": Fneed, "sysP": sysP, "Dcyl": Dcyl, "Dstd": Dstd, "Freal": Freal,
            "num": num, "stroke": N(f, 'slStroke'), "ok": Dstd > 0 and Freal >= Fneed}


def r_slider(f):
    c = calc_slider(f)
    if not c["A"]:
        return _result('<h4>滑块油缸缸径</h4><div class="hint">请填写滑块成型包紧面积。</div>')
    st = 'ok' if c["ok"] else 'bad'
    html = ('<h4>滑块油缸缸径计算 <span class="st">' + pill(st, '缸径满足' if c["ok"] else '缸径不足')
            + '</span></h4>'
            + KV([
                {"k": "滑块包紧面积", "v": fmt(c["A"], 0), "u": "mm²"},
                {"k": "抽芯斜度 α", "v": fmt(c["alpha"], 1), "u": "°"},
                {"k": "抽芯阻力", "v": fmt(c["Fres"], 2), "u": "吨", "red": True},
                {"k": "抽芯系数 K", "v": fmt(c["K"], 2)},
                {"k": "抽芯力 F抽", "v": fmt(c["Fpull"], 2), "u": "吨", "red": True},
                {"k": "导轨摩擦阻力", "v": fmt(c["Ffric"], 2), "u": "吨"},
                {"k": "油缸需推力", "v": fmt(c["Fneed"], 2), "u": "吨", "red": True},
                {"k": "理论缸径", "v": fmt(c["Dcyl"], 1), "u": "mm", "red": True},
                {"k": "选用标准缸径", "v": '∅' + str(c["Dstd"]), "u": "mm", "red": True},
                {"k": "标准缸实际推力", "v": fmt(c["Freal"], 2), "u": "吨", "red": True},
                {"k": "滑块数量", "v": sstr(c["num"]), "u": "个"},
                {"k": "抽芯行程", "v": fmt(c["stroke"], 0), "u": "mm"},
            ]))
    verdict = ('油缸推力校核：∅' + str(c["Dstd"]) + ' 标准缸在 ' + fmt(c["sysP"], 0)
               + ' MPa 系统压力下实际推力 ' + fmt(c["Freal"], 2) + ' 吨 '
               + ('≥' if c["Freal"] >= c["Fneed"] else '＜') + ' 所需 ' + fmt(c["Fneed"], 2) + ' 吨，'
               + ('满足抽芯要求。' if c["ok"] else '推力不足，建议加大一档缸径或提高系统压力。')
               + ' 共 ' + sstr(c["num"]) + ' 个滑块，抽芯行程 ' + fmt(c["stroke"], 0) + ' mm。'
               + ' 结论：' + ('可行。' if c["ok"] else '需增大缸径至 ∅'
                             + str(pick_std(CYL_STD, c["Dcyl"] + 1)) + ' 或优化滑块结构减小包紧面积。'))
    html += verdict_html(st, verdict)
    return _result(html, verdict)


# =========================================================================
# 3.5 抽真空：Qv = V·ln(P₀/P₁)/t，S = Qv×3.6×泄漏系数，A阀 = Qv×1000/v
# =========================================================================
def calc_vacuum(f):
    d_sleeve = N(f, 'vcSlvD')
    l_sleeve = N(f, 'vcSlvL')
    v_sleeve = math.pi * d_sleeve * d_sleeve / 4 * l_sleeve / 1e6
    V = N(f, 'vcCav') + N(f, 'vcRun') + v_sleeve
    P0 = 1013
    P1 = max(1, N(f, 'vcTarget') or 50)
    t = max(0.05, N(f, 'vcTime') or 1.5)
    ln = math.log(P0 / P1)
    Qv = V * ln / t
    leak = N(f, 'vcLeak') or 1.3
    S = Qv * 3.6 * leak
    v = N(f, 'vcVel') or 40
    Avalve = Qv * 1000 / v
    pump = N(f, 'vcPump')
    t_need = V * ln * 3.6 * leak / pump if pump else 0
    total_gas = V * ln
    return {"vSleeve": v_sleeve, "V": V, "P0": P0, "P1": P1, "t": t, "ln": ln, "Qv": Qv,
            "leak": leak, "S": S, "v": v, "Avalve": Avalve, "pump": pump,
            "tNeed": t_need, "totalGas": total_gas,
            "ok": ((not pump) or (pump >= S and t_need <= t)) and Avalve > 0}


def r_vacuum(f):
    c = calc_vacuum(f)
    if not c["V"]:
        return _result('<h4>抽真空计算</h4><div class="hint">请填写型腔容积、压室尺寸等参数。</div>')
    if c["pump"]:
        st = 'ok' if c["pump"] >= c["S"] else 'warn'
        st_txt = '真空能力满足' if c["pump"] >= c["S"] else '真空能力不足'
    else:
        st, st_txt = 'warn', '待填泵参数'
    html = ('<h4>抽真空计算 <span class="st">' + pill(st, st_txt) + '</span></h4>'
            + KV([
                {"k": "压室容积", "v": fmt(c["vSleeve"], 2), "u": "L"},
                {"k": "总抽气容积 V", "v": fmt(c["V"], 2), "u": "L", "red": True},
                {"k": "目标真空度 P₁", "v": fmt(c["P1"], 0), "u": "mbar"},
                {"k": "ln(P₀/P₁)", "v": fmt(c["ln"], 3)},
                {"k": "允许抽气时间", "v": fmt(c["t"], 2), "u": "s"},
                {"k": "平均抽气量 Qv", "v": fmt(c["Qv"], 2), "u": "L/s", "red": True},
                {"k": "所需泵抽速 S", "v": fmt(c["S"], 1), "u": "m³/h", "red": True},
                {"k": "真空阀排气截面积", "v": fmt(c["Avalve"], 1), "u": "mm²", "red": True},
                {"k": "总抽气量", "v": fmt(c["totalGas"], 2), "u": "L", "red": True},
                {"k": "真空泵抽速（实选）", "v": fmt(c["pump"], 1) if c["pump"] else '—', "u": "m³/h"},
                {"k": "实际所需抽气时间", "v": fmt(c["tNeed"], 2) if c["pump"] else '—', "u": "s", "red": True},
            ]))
    if c["pump"]:
        verdict = ('真空校核：实选泵 ' + fmt(c["pump"], 1) + ' m³/h ' + ('≥' if c["pump"] >= c["S"] else '＜')
                   + ' 所需 ' + fmt(c["S"], 1) + ' m³/h；抽至 ' + fmt(c["P1"], 0) + ' mbar 需 '
                   + fmt(c["tNeed"], 2) + ' s ' + ('≤' if c["tNeed"] <= c["t"] else '＞') + ' 允许 '
                   + fmt(c["t"], 2) + ' s。')
    else:
        verdict = '尚未填写真空泵抽速，无法完成抽气时间校核。'
    verdict += ' 真空阀有效排气截面积需 ≥ ' + fmt(c["Avalve"], 1) + ' mm²'
    if N(f, 'vvArea'):
        cur_total = N(f, 'vvArea') * (N(f, 'vvNum') or 1)
        verdict += ('，当前单阀 ' + fmt(N(f, 'vvArea'), 1) + ' mm² × ' + fmt(N(f, 'vvNum') or 1, 0)
                    + ' 个 = ' + fmt(cur_total, 1) + ' mm² '
                    + ('满足要求。' if cur_total >= c["Avalve"] else '不足，需增加阀数量或加大阀规格。'))
    else:
        verdict += '，请补充单阀截面积。'
    verdict += ' 结论：' + ('可行。' if c["ok"] else '需增大真空泵抽速或延长抽气时间/减小抽气容积。')
    html += verdict_html(st, verdict)
    return _result(html, verdict)


# =========================================================================
# 3.6 冷却：Q总 = C铝·M·ΔT + M·凝固潜热
# =========================================================================
def calc_cool(f):
    M = N(f, 'cwM') or (N(f, 'wCast') + N(f, 'wRunner') + N(f, 'wOverflow'))
    C = N(f, 'cwC') or 1.05
    L = N(f, 'cwL') or 389
    dT = N(f, 'cwDT') or 80
    Qs = C * M * dT
    Ql = M * L
    Q = Qs + Ql
    phi = N(f, 'cwPhi') or 0.6
    dTw = max(0.5, N(f, 'cwDTw') or 8)
    W = Q * phi / (4.187 * dTw)
    t_allow = N(f, 'cwTime')
    flow_need = W / t_allow * 60 if t_allow else 0
    flow_act = N(f, 'cwFlow')
    t_act = W / flow_act * 60 if flow_act else 0
    return {"M": M, "C": C, "L": L, "dT": dT, "Qs": Qs, "Ql": Ql, "Q": Q, "phi": phi,
            "dTw": dTw, "W": W, "tAllow": t_allow, "flowNeed": flow_need,
            "flowAct": flow_act, "tAct": t_act,
            "ok": (t_allow and flow_act) and (t_act <= t_allow),
            "ok2": (not flow_act or not t_allow) or (flow_need <= flow_act)}


def r_cool(f):
    c = calc_cool(f)
    if not c["M"]:
        return _result('<h4>冷却水计算</h4><div class="hint">请填写每次浇注金属量（由 2.1 自动带出）。</div>')
    if c["tAllow"] and c["flowAct"]:
        st = 'ok' if c["tAct"] <= c["tAllow"] else 'bad'
        st_txt = '节拍满足' if st == 'ok' else '冷却时间不足'
    else:
        st, st_txt = 'warn', '待填节拍/流量'
    html = ('<h4>冷却水量与冷却时间校核 <span class="st">' + pill(st, st_txt) + '</span></h4>'
            + KV([
                {"k": "每次浇注金属量 M", "v": fmt(c["M"], 3), "u": "kg"},
                {"k": "显热 Q₁ = C·M·ΔT", "v": fmt(c["Qs"], 0), "u": "kJ"},
                {"k": "潜热 Q₂ = M·L", "v": fmt(c["Ql"], 0), "u": "kJ"},
                {"k": "总热量 Q总", "v": fmt(c["Q"], 0), "u": "kJ", "red": True},
                {"k": "水冷分配系数 φ", "v": fmt(c["phi"], 2)},
                {"k": "冷却水温升 Δt", "v": fmt(c["dTw"], 1), "u": "K"},
                {"k": "需水量 W", "v": fmt(c["W"], 1), "u": "L", "red": True},
                {"k": "节拍允许冷却时间", "v": fmt(c["tAllow"], 0) if c["tAllow"] else '—', "u": "s"},
                {"k": "所需水流量", "v": fmt(c["flowNeed"], 1) if c["flowNeed"] else '—', "u": "L/min", "red": True},
                {"k": "实际设计水流量", "v": fmt(c["flowAct"], 1) if c["flowAct"] else '—', "u": "L/min"},
                {"k": "实际所需冷却时间", "v": fmt(c["tAct"], 1) if c["tAct"] else '—', "u": "s", "red": True},
            ]))
    verdict = ('热平衡：需带走总热量 ' + fmt(c["Q"], 0) + ' kJ（其中潜热占比 '
               + fmt(c["Ql"] / max(c["Q"], 1) * 100, 0) + '%），按 ' + fmt(c["phi"] * 100, 0)
               + '% 由冷却水带走、温升 ' + fmt(c["dTw"], 1) + ' K 计，需水量 ' + fmt(c["W"], 1) + ' L。')
    if c["tAllow"] and c["flowAct"]:
        verdict += (' 实际水流量 ' + fmt(c["flowAct"], 1) + ' L/min 下所需冷却时间 ' + fmt(c["tAct"], 1)
                    + ' s ' + ('≤' if c["tAct"] <= c["tAllow"] else '＞') + ' 节拍允许 '
                    + fmt(c["tAllow"], 0) + ' s，'
                    + ('节拍满足要求。' if c["tAct"] <= c["tAllow"]
                       else '冷却时间不足：建议加大水流量至 ' + fmt(c["flowNeed"], 1)
                       + ' L/min，或对厚大热节增加点冷/局部高压冷却。'))
    else:
        verdict += ' 请补充节拍允许冷却时间与实际设计水流量以完成校核。'
    html += verdict_html(st, verdict)
    return _result(html, verdict)


# =========================================================================
# 5.3 压射系统参数
# =========================================================================
def calc_inject(f):
    D = N(f, 'injD')
    Ag = N(f, 'injAg')
    vol = N(f, 'injVol')
    t = N(f, 'injT')
    Ap = math.pi * D * D / 4
    R = Ap / Ag if Ag else 0
    Q = vol * 1000 / t if vol and t else 0
    QL = Q / 1e6
    vg = Q / Ag / 1000 if Ag else 0
    vp = Q / Ap / 1000 if Ap else 0
    m = cur_machine(f)
    v0 = m.get("v0") or 6
    return {"D": D, "Ap": Ap, "Ag": Ag, "R": R, "vol": vol, "t": t, "Q": Q, "QL": QL,
            "vg": vg, "vp": vp, "v0": v0, "okVp": vp > 0 and vp <= v0 * 0.8, "mach": m}


def r_inject(f):
    c = calc_inject(f)
    if not c["Ap"] or not c["Ag"]:
        return _result('<h4>压射系统参数</h4><div class="hint">请填写冲头直径与内浇口面积。</div>')
    wall = N(f, 'wall')
    rec = pick_gate_speed_row(wall)
    rng = [float(x) for x in rec[1].split('~')]
    st = 'ok' if (rng[0] <= c["vg"] <= rng[1]) and c["okVp"] else 'warn'
    html = ('<h4>压射系统参数 <span class="st">' + pill(st, '参数匹配' if st == 'ok' else '需复核')
            + '</span></h4>'
            + KV([
                {"k": "冲头直径", "v": fmt(c["D"], 0), "u": "mm"},
                {"k": "冲头面积 A冲", "v": fmt(c["Ap"], 1), "u": "mm²"},
                {"k": "内浇口面积 A内", "v": fmt(c["Ag"], 1), "u": "mm²"},
                {"k": "速率比 R = A冲/A内", "v": fmt(c["R"], 2), "red": True},
                {"k": "型腔体积", "v": fmt(c["vol"], 1), "u": "cm³"},
                {"k": "填充时间", "v": fmt(c["t"], 3), "u": "s"},
                {"k": "体积流量 Q", "v": fmt(c["QL"], 2), "u": "L/s", "red": True},
                {"k": "内浇口速度 v_g", "v": fmt(c["vg"], 1), "u": "m/s", "red": True},
                {"k": "快压射速度 v_p", "v": fmt(c["vp"], 2), "u": "m/s", "red": True},
                {"k": "设备空压射速度", "v": fmt(c["v0"], 1), "u": "m/s"},
                {"k": "壁厚", "v": fmt(wall, 1), "u": "mm"},
                {"k": "推荐内浇口速度", "v": rec[1], "u": "m/s"},
            ]))
    verdict = ('速率比 R = A冲/A内 = ' + fmt(c["R"], 2) + '（内浇口速度为压射速度的 ' + fmt(c["R"], 1)
               + ' 倍，常规区间 8 ~ 25）。内浇口速度 ' + fmt(c["vg"], 1) + ' m/s，')
    if wall:
        verdict += ('壁厚 ' + fmt(wall, 1) + ' mm 对应推荐区间 ' + rec[1] + ' m/s，'
                    + ('处于推荐区间内。' if rng[0] <= c["vg"] <= rng[1]
                       else '偏离推荐区间，建议调整内浇口面积至 '
                       + fmt(c["Q"] / (max((rng[0] + rng[1]) / 2, 0.1) * 1000), 1) + ' mm²。'))
    verdict += (' 快压射速度 ' + fmt(c["vp"], 2) + ' m/s ' + ('≤' if c["okVp"] else '＞')
                + ' 设备空压射速度的 80%（' + fmt(c["v0"] * 0.8, 2) + ' m/s），'
                + ('压射能力可满足。' if c["okVp"] else '需提高压射能力或增大冲头直径/延长填充时间。'))
    html += verdict_html(st, verdict)
    return _result(html, verdict)


# =========================================================================
# 5.6 PQ² 工艺窗口
# 机器特性线：P = Pmax · (1 − (Q/Qmax)²)
# =========================================================================
def calc_pq2(f):
    c = calc_inject(f)
    m = cur_machine(f)
    injF = N(f, 'injForce') or m["injForce"]
    Pmax = injF * 1000 / c["Ap"] if c["Ap"] else 0
    Qmax = c["Ap"] * m["v0"] / 1000 if c["Ap"] else 0
    Q = c["QL"]
    Pneed = N(f, 'injIntP')
    Pline = Pmax * (1 - (Q / Qmax if Qmax else 0) ** 2)
    margin = (Pline - Pneed) / Pline * 100 if Pline else 0
    pts = [[fmt(Qmax * i / 5, 1), fmt(Pmax * (1 - (i / 5) ** 2), 1)] for i in range(6)]
    return {"c": c, "m": m, "injF": injF, "Pmax": Pmax, "Qmax": Qmax, "Q": Q,
            "Pneed": Pneed, "Pline": Pline, "margin": margin, "pts": pts,
            "ok": Q < Qmax and Pline >= Pneed,
            "good": Q < Qmax and Pline >= Pneed * 1.15}


def r_pq2(f):
    p = calc_pq2(f)
    if not p["Qmax"] or not p["Q"]:
        return _result('<h4>PQ² 工艺窗口</h4><div class="hint">请先在 5.3 填写冲头直径、内浇口面积、型腔体积与填充时间。</div>')
    if p["good"]:
        st, st_txt = 'ok', '窗口充足'
    elif p["ok"]:
        st, st_txt = 'ok', '余量偏小'
    else:
        st, st_txt = 'bad', '窗口不足'
    html = ('<h4>PQ² 工艺窗口与设备匹配 <span class="st">' + pill(st, st_txt) + '</span></h4>'
            + KV([
                {"k": "机型", "v": p["m"]["brand"] + ' ' + p["m"]["model"], "u": str(p["m"]["ton"]) + 'T'},
                {"k": "压射力", "v": fmt(p["injF"], 0), "u": "kN"},
                {"k": "理论最大比压 Pmax", "v": fmt(p["Pmax"], 1), "u": "MPa", "red": True},
                {"k": "最大流量 Qmax", "v": fmt(p["Qmax"], 1), "u": "L/s", "red": True},
                {"k": "工艺点流量 Q", "v": fmt(p["Q"], 2), "u": "L/s", "red": True},
                {"k": "需求比压 P", "v": fmt(p["Pneed"], 1), "u": "MPa", "red": True},
                {"k": "机器线可用比压", "v": fmt(p["Pline"], 1), "u": "MPa", "red": True},
                {"k": "压力余量", "v": fmt(p["margin"], 1), "u": "%", "red": True},
                {"k": "流量占用率", "v": fmt(p["Q"] / p["Qmax"] * 100, 1) if p["Qmax"] else '—', "u": "%", "red": True},
            ])
            + '<h4 style="margin-top:12px">机器特性线采样（P = Pmax·(1−(Q/Qmax)²)）</h4>'
            + ROT(['流量 Q (L/s)', '可用比压 P (MPa)'],
                  [[{"t": x[0], "n": True}, {"t": x[1], "n": True}] for x in p["pts"]]))
    verdict = ('PQ² 结论：工艺点 (Q=' + fmt(p["Q"], 2) + ' L/s, P=' + fmt(p["Pneed"], 1) + ' MPa) ')
    if p["good"]:
        verdict += '位于机器特性线下方且有 ' + fmt(p["margin"], 1) + '% 压力余量（≥ 15%），设备匹配良好。'
    elif p["ok"]:
        verdict += ('位于机器特性线下方，但压力余量仅 ' + fmt(p["margin"], 1)
                    + '%（< 15%），可行但余量偏小，建议预留工艺调整空间。')
    else:
        verdict += ('已超出可用窗口（机器线可用 ' + fmt(p["Pline"], 1) + ' MPa，需求 '
                    + fmt(p["Pneed"], 1) + ' MPa）。')
    verdict += ' 优化方向：' + ('可按当前参数试模，建议填充时间控制在 ' + fmt(p["c"]["t"], 3)
                              + '±0.01 s，慢压射 ' + fmt(N(f, 'injSlow'), 2) + ' m/s。' if p["ok"]
                              else '① 增大冲头直径以提高流量能力；② 降低需求比压（增大内浇口面积）；'
                                   '③ 换用更大压射力机型；④ 延长填充时间以减小瞬时流量。')
    html += verdict_html(st, verdict)
    return _result(html, verdict)


# =========================================================================
# 6 设备参数 / 机型对照 / 壁厚-浇口速度对照
# =========================================================================
def r_machine(f):
    m = cur_machine(f)
    html = ('<h4>当前机型参数自动填充 <span class="st">' + pill('info', m["brand"] + ' ' + m["model"])
            + '</span></h4>'
            + ROT(['参数', '数值', '单位'], [
                ['品牌 / 型号', m["brand"] + ' ' + m["model"], ''],
                ['锁模力', fmt(m["lock"], 0), 'kN'],
                ['锁模力', fmt(m["ton"], 0), 'T'],
                ['开模行程', fmt(m["open"], 0), 'mm'],
                ['容模量（最小 ~ 最大）', fmt(m["moldMin"], 0) + ' ~ ' + fmt(m["moldMax"], 0), 'mm'],
                ['哥林柱间距（内距）', m["tie"], 'mm'],
                ['哥林柱直径', fmt(m["tieDia"], 0), 'mm'],
                ['模板尺寸', m["plate"], 'mm'],
                ['压射力', fmt(m["injForce"], 0), 'kN'],
                ['压射行程', fmt(m["injStroke"], 0), 'mm'],
                ['冲头直径可选', ' / '.join(str(x) for x in m["punch"]), 'mm'],
                ['空压射速度', fmt(m["v0"], 1), 'm/s'],
                ['顶出力', fmt(m["ejForce"], 0), 'kN'],
                ['顶出行程', fmt(m["ejStroke"], 0), 'mm'],
            ])
            + '<div class="hint" style="margin-top:8px">以上参数已自动带入 2.2 锁模力、2.3 哥林柱、5.3 压射与 5.6 PQ² 计算。</div>')
    return _result(html)


def r_mach_list(f):
    rows = []
    for m in MACHINES:
        sel = (m["brand"] + ' ' + m["model"]) == V(f, 'machineId')
        rows.append([m["brand"], m["model"], {"t": fmt(m["ton"], 0), "n": True},
                     {"t": fmt(m["lock"], 0), "n": True}, {"t": fmt(m["open"], 0), "n": True},
                     fmt(m["moldMin"], 0) + '~' + fmt(m["moldMax"], 0), m["tie"],
                     {"t": fmt(m["tieDia"], 0), "n": True}, {"t": fmt(m["injForce"], 0), "n": True},
                     '/'.join(str(x) for x in m["punch"]), {"t": fmt(m["v0"], 1), "n": True},
                     {"t": fmt(m["ejForce"], 0), "n": True}, '● 已选' if sel else ''])
    html = '<h4>压铸机参数库对照表</h4>' + ROT(
        ['品牌', '型号', '吨位 T', '锁模力 kN', '开模行程 mm', '容模量 mm', '哥林柱间距 mm', '柱径 mm',
         '压射力 kN', '冲头直径 mm', '空压射 m/s', '顶出力 kN', '选中'], rows)
    return _result(html)


def r_gate_speed(f):
    html = ROT(['铸件壁厚 mm', '内浇口速度 m/s', '说明'],
               [[r[0], {"t": r[1], "hi": True}, r[2]] for r in GATE_SPEED_TABLE])
    return _result(html)


# =========================================================================
# 结果汇总
# =========================================================================
RESULTS = {
    "rForce": r_force, "rTieBar": r_tiebar, "rHold": r_hold, "rEject": r_eject,
    "rSqueeze": r_squeeze, "rSlider": r_slider, "rVacuum": r_vacuum, "rCool": r_cool,
    "rInject": r_inject, "rPQ2": r_pq2, "rMachine": r_machine, "rMachList": r_mach_list,
    "rGateSpeed": r_gate_speed,
}


# =========================================================================
# 派生值联动（对应原 JS recalcDerived）
# =========================================================================
def recalc_derived(f):
    out = {}
    wp = N(f, 'wCast') + N(f, 'wRunner') + N(f, 'wOverflow')
    out["wPour"] = f"{wp:.3f}" if wp else ''
    out["cwM"] = f"{wp:.3f}" if wp else ''
    at = (N(f, 'aPart') + N(f, 'aRunner') + N(f, 'aOver')) * max(1, N(f, 'cav')) + N(f, 'aSlider')
    out["aTotal2"] = f"{at:.1f}" if at else ''
    if not V(f, 'pMax2'):
        out["pMax2"] = V(f, 'castP')
    return out


# =========================================================================
# 机型选中自动填充（对应原 JS fillMachine）
# =========================================================================
def machine_fill(f):
    m = cur_machine(f)
    out = {}
    out["lockKN"] = m["lock"]
    tie = str(m["tie"]).split('×')
    out["tieX"] = tie[0]
    out["tieY"] = tie[1] if len(tie) > 1 else tie[0]
    out["tieDia"] = m["tieDia"]
    out["machTon"] = m["ton"]
    out["injForce"] = m["injForce"]
    out["machV0"] = m["v0"]
    if not N(f, 'injD') and m.get("punch"):
        out["injD"] = m["punch"][0]
    if not N(f, 'injVol') and N(f, 'wCast'):
        out["injVol"] = f"{N(f, 'wCast') * 1000 / 2.7:.1f}"
    if not N(f, 'vcSlvD') and m.get("punch"):
        out["vcSlvD"] = m["punch"][0]
    return out


def compute_all(f, apply_machine=False):
    """一次计算返回：派生值 + 机型填充（可选）+ 全部结果。"""
    derived = recalc_derived(f)
    mfill = machine_fill(f) if apply_machine else None
    results = {}
    for key, fn in RESULTS.items():
        try:
            results[key] = fn(f)
        except Exception as e:  # 单个结果失败不阻塞整体
            results[key] = {"html": '<div class="hint">计算暂不可用：' + esc(str(e)) + '</div>', "verdict": ""}
    return {"derived": derived, "machine_fill": mfill, "results": results}


def verdict_of(key, f):
    """取某结果的纯文本结论（PPT 用）。"""
    try:
        return RESULTS[key](f).get("verdict", "")
    except Exception:
        return ""
