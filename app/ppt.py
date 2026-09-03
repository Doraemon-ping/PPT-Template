# -*- coding: utf-8 -*-
"""PPT 导出（python-pptx，对应原 HTML 第 ⑤ 部分 buildPPT）。

页面顺序、版式严格对应原模板：封面 + 45 页内容 + 致谢/保密声明，共 46 页。
"""
import base64
import io
import re

from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_CONNECTOR
from pptx.enum.dml import MSO_LINE
from pptx.oxml.ns import qn

from .machines import MACHINES, cur_machine, GATE_SPEED_TABLE
from .utils import fmt, sstr, T, N, V
from . import calc
from .demo import default_logo_data_uri

PW = 10.0
PH = 5.625
FONT = "微软雅黑"
C_DARK = "16233A"
C_ORANGE = "FF6A00"
C_RED = "C0392B"
C_TH = "1B2A41"
C_BD = "B8C4D2"


# =========================================================================
# 底层绘图助手
# =========================================================================
def _color(hex_str):
    return RGBColor.from_string(hex_str.lstrip("#"))


def _add_text(slide, text, x, y, w, h, size=10, bold=False, color="333333",
              align="left", valign="top", font=FONT, rotation=None,
              fill=None, line=None, line_width=0.75, margin=None, dash=None):
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = box.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE if valign == "middle" else MSO_ANCHOR.TOP
    if margin:
        ml, mr, mt, mb = margin
        tf.margin_left = Pt(ml)
        tf.margin_right = Pt(mr)
        tf.margin_top = Pt(mt)
        tf.margin_bottom = Pt(mb)
    else:
        tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = Pt(0)
    if fill:
        box.fill.solid()
        box.fill.fore_color.rgb = _color(fill)
    else:
        box.fill.background()
    if line:
        box.line.color.rgb = _color(line)
        box.line.width = Pt(line_width)
        if dash:
            box.line.dash_style = MSO_LINE.DASH
    if rotation:
        box.rotation = rotation
    align_map = {"left": PP_ALIGN.LEFT, "center": PP_ALIGN.CENTER, "right": PP_ALIGN.RIGHT}
    lines = str(text).split("\n")
    for idx, line_text in enumerate(lines):
        p = tf.paragraphs[0] if idx == 0 else tf.add_paragraph()
        p.alignment = align_map.get(align, PP_ALIGN.LEFT)
        run = p.add_run()
        run.text = line_text
        run.font.size = Pt(size)
        run.font.bold = bold
        run.font.name = font
        run.font.color.rgb = _color(color)
    return box


def _add_rect(slide, x, y, w, h, fill="FFFFFF", line=None, line_width=0.75, dash=None):
    from pptx.enum.shapes import MSO_SHAPE
    shp = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    if fill:
        shp.fill.solid()
        shp.fill.fore_color.rgb = _color(fill)
    else:
        shp.fill.background()
    if line:
        shp.line.color.rgb = _color(line)
        shp.line.width = Pt(line_width)
        if dash:
            shp.line.dash_style = MSO_LINE.DASH
    else:
        shp.line.fill.background()
    shp.shadow.inherit = False
    return shp


def _add_line(slide, x1, y1, x2, y2, color="D9DEE6", width=0.5):
    conn = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT,
                                      Inches(x1), Inches(y1), Inches(x2), Inches(y2))
    conn.line.color.rgb = _color(color)
    conn.line.width = Pt(width)
    conn.shadow.inherit = False
    return conn


def _decode_image(data_url):
    if data_url and "," in data_url:
        b64 = data_url.split(",", 1)[1]
        return io.BytesIO(base64.b64decode(b64))
    return None


def _add_picture(slide, data_url, x, y, w, h):
    stream = _decode_image(data_url)
    if stream is None:
        return False
    try:
        slide.shapes.add_picture(stream, Inches(x), Inches(y), Inches(w), Inches(h))
        return True
    except Exception:
        return False


def _set_cell_border(cell, color=C_BD, width_pt=0.5):
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    tags = ["a:lnL", "a:lnR", "a:lnT", "a:lnB"]
    for tag in tags:
        for el in tcPr.findall(qn(tag)):
            tcPr.remove(el)
    w = str(int(width_pt * 12700))
    for i, tag in enumerate(tags):
        ln = tcPr.makeelement(qn(tag), {"w": w, "cap": "flat", "cmpd": "sng", "algn": "ctr"})
        solid_fill = ln.makeelement(qn("a:solidFill"), {})
        srgb = ln.makeelement(qn("a:srgbClr"), {"val": color})
        solid_fill.append(srgb)
        ln.append(solid_fill)
        tcPr.insert(i, ln)


def _fill_cell(cell, text, size=9, bold=False, color="333333", align="left",
               fill=None, margin=(2, 4, 2, 4)):
    if fill:
        cell.fill.solid()
        cell.fill.fore_color.rgb = _color(fill)
    else:
        cell.fill.solid()
        cell.fill.fore_color.rgb = _color("FFFFFF")
    cell.vertical_anchor = MSO_ANCHOR.MIDDLE
    cell.margin_left = Pt(margin[1])
    cell.margin_right = Pt(margin[1])
    cell.margin_top = Pt(margin[0])
    cell.margin_bottom = Pt(margin[0])
    tf = cell.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.alignment = {"left": PP_ALIGN.LEFT, "center": PP_ALIGN.CENTER, "right": PP_ALIGN.RIGHT}.get(align, PP_ALIGN.LEFT)
    run = p.add_run()
    run.text = "" if text is None else str(text)
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.name = FONT
    run.font.color.rgb = _color(color)
    _set_cell_border(cell)


# =========================================================================
# 模板元素
# =========================================================================
def _add_watermark(slide, logo_data=None):
    txt = "拓普"
    rows = [(0.7, -1.0), (2.2, 0.3), (3.7, -0.7), (5.0, 0.5)]
    cols = [-0.8, 2.4, 5.6, 8.8]
    i = 0
    for ry, x_off in rows:
        for cx in cols:
            x = cx + x_off
            if x < -1.5 or x > PW + 0.5:
                continue
            rotate = -18 if i % 2 == 0 else 18
            _add_text(slide, txt, x, ry, 3.2, 1.2, size=46, bold=True,
                      color="EAEEF3", align="center", valign="middle", rotation=rotate)
            i += 1
    if logo_data:
        _add_picture(slide, logo_data, 8.55, 0.12, 1.30, 0.36)


def _new_slide(prs, title, sub, plain=False):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    if plain:
        return slide
    logo = logo_of(_STATE)
    _add_watermark(slide, logo)
    if title:
        _add_text(slide, title, 0.35, 0.10, 7.8, 0.46, size=18, bold=True,
                  color="1F3A6F", valign="middle")
    if sub:
        _add_text(slide, sub, 0.35, 0.58, 9.3, 0.26, size=11, bold=True, color=C_DARK)
    _add_text(slide, str(_PAGE_NO[0]), 9.10, 5.35, 0.55, 0.22, size=9,
              color="8FA3BC", align="right", valign="middle")
    _PAGE_NO[0] += 1
    return slide


def addTbl(slide, head, rows, x=0.4, y=1.15, w=9.2, fs=9, rowH=0.3, colW=None):
    n_rows = max(len(rows) + 1, 2)
    n_cols = max(len(head), 1)
    shape = slide.shapes.add_table(n_rows, n_cols, Inches(x), Inches(y), Inches(w), Inches(0.5))
    table = shape.table
    if colW:
        total = sum(colW)
        for i, cw in enumerate(colW):
            table.columns[i].width = Inches(w * cw / total)
    # 表头
    for j, htext in enumerate(head):
        _fill_cell(table.cell(0, j), htext, size=fs, bold=True, color="FFFFFF",
                   align="center", fill=C_TH)
    # 数据行
    for i, row in enumerate(rows):
        for j in range(n_cols):
            c = row[j] if j < len(row) else ""
            is_obj = isinstance(c, dict)
            txt = c.get("t", "") if is_obj else c
            hi = bool(c.get("hi")) if is_obj else False
            right = bool(c.get("n")) if is_obj else False
            _fill_cell(table.cell(i + 1, j), txt, size=fs, bold=hi,
                       color=C_RED if hi else "333333",
                       align="right" if right else "left")
    table.rows[0].height = Inches(rowH)
    for i in range(1, n_rows):
        table.rows[i].height = Inches(rowH)
    return table


def addKV(slide, items, x, y, w):
    cw = [w * 0.20, w * 0.30, w * 0.20, w * 0.30]
    n_pairs = (len(items) + 1) // 2
    shape = slide.shapes.add_table(n_pairs, 4, Inches(x), Inches(y), Inches(w), Inches(0.3 * n_pairs))
    table = shape.table
    for i, cwv in enumerate(cw):
        table.columns[i].width = Inches(cwv)
    for ri in range(n_pairs):
        for j in range(2):
            it = items[ri * 2 + j] if ri * 2 + j < len(items) else None
            if it is None:
                _fill_cell(table.cell(ri, j * 2), "", size=8.5)
                _fill_cell(table.cell(ri, j * 2 + 1), "", size=9.5)
                continue
            _fill_cell(table.cell(ri, j * 2), it.get("k", ""), size=8.5, bold=True,
                       color="33475F", align="left", fill="EDF1F6")
            val = str(it.get("v", "")) + (" " + str(it.get("u", "")) if it.get("u") else "")
            _fill_cell(table.cell(ri, j * 2 + 1), val, size=9.5, bold=True,
                       color=C_RED if it.get("red") else "222222", align="left")
        table.rows[ri].height = Inches(0.3)
    return table


def addVerdict(slide, text, y, x=0.4, w=9.2):
    if not text:
        return
    _add_rect(slide, x, y, w, 0.8, fill="F2F5F9")
    _add_rect(slide, x, y, 0.05, 0.8, fill=C_ORANGE)
    _add_text(slide, text, x, y, w, 0.8, size=9.5, color="1F3A5F",
              valign="top", margin=(4, 6, 4, 6))


def addImgs(slide, key, x, y, w, h, max_n=2):
    arr = (_STATE.get("i", {}).get(key) or [])[:max_n]
    if not arr:
        _add_rect(slide, x, y, w, h, fill="F4F6F9", line=C_BD, line_width=0.75, dash=True)
        _add_text(slide, "图片占位", x, y, w, h, size=10, color="9AA7B6",
                  align="center", valign="middle")
        return False
    n = len(arr)
    gap = 0.12
    iw = (w - gap * (n - 1)) / n
    for i, src in enumerate(arr):
        if not _add_picture(slide, src, x + i * (iw + gap), y, iw, h):
            _add_rect(slide, x + i * (iw + gap), y, iw, h, fill="F4F6F9", line=C_BD, line_width=0.75, dash=True)
    return True


def addBlock(slide, title, text, x, y, w, h):
    _add_text(slide, title, x, y, w, 0.24, size=10, bold=True, color=C_DARK, valign="middle")
    _add_rect(slide, x, y + 0.24, w, h - 0.24, fill="F7F9FB", line="DDE3EA", line_width=0.5)
    _add_text(slide, text or "—", x + 0.06, y + 0.28, w - 0.12, h - 0.32,
              size=9, color="333333", valign="top", margin=(3, 4, 3, 4))


def rowsOf(t, key, cols):
    return [[r.get(c, "") or "" for c in cols] for r in (t.get(key) or [])]


_STATE = {"f": {}, "t": {}, "i": {}}
_PAGE_NO = [2]


def logo_of(state):
    arr = state.get("i", {}).get("logoImg") or []
    return arr[0] if arr else default_logo_data_uri()


# =========================================================================
# 主流程
# =========================================================================
def build_pptx(f, t, i):
    _STATE["f"] = f
    _STATE["t"] = t
    _STATE["i"] = i
    _PAGE_NO[0] = 2

    prs = Presentation()
    prs.slide_width = Inches(PW)
    prs.slide_height = Inches(PH)

    logo = logo_of(_STATE)
    sf = f

    # ---------- 1 封面 ----------
    s = _new_slide(prs, "", "", plain=True)
    s.background.fill.solid()
    s.background.fill.fore_color.rgb = _color("FFFFFF")
    _add_picture(s, logo, 3.6, 0.35, 2.8, 0.78)
    peakX, peakY = 5.0, 1.45
    baseY = PH + 0.3
    for i in range(13):
        x = -0.5 + i * (peakX + 0.5) / 12
        _add_line(s, x, baseY, peakX, peakY, "D9DEE6", 0.5)
    for i in range(13):
        x = peakX + i * (PW - peakX + 0.5) / 12
        _add_line(s, peakX, peakY, x, baseY, "D9DEE6", 0.5)
    peak2X, peak2Y = 2.6, 2.3
    for i in range(7):
        x = -0.5 + i * (peak2X + 0.5) / 6
        _add_line(s, x, baseY, peak2X, peak2Y, "E5E9EF", 0.4)
    for i in range(7):
        x = peak2X + i * (peakX - peak2X) / 6
        _add_line(s, peak2X, peak2Y, x, baseY, "E5E9EF", 0.4)
    peak3X, peak3Y = 7.4, 2.3
    for i in range(7):
        x = peakX + i * (peak3X - peakX) / 6
        _add_line(s, peakX, peakY, x, baseY, "E5E9EF", 0.4)
    for i in range(7):
        x = peak3X + i * (PW - peak3X + 0.5) / 6
        _add_line(s, peak3X, peak3Y, x, baseY, "E5E9EF", 0.4)
    _add_text(s, T(f, "partNo") or "XX", 1.0, 2.55, 8.0, 0.85, size=54, bold=True,
              color="1F3A6F", align="center", valign="middle")
    _add_text(s, "DFM", 1.0, 3.30, 8.0, 0.7, size=42, bold=True,
              color="1F3A6F", align="center", valign="middle")
    _add_text(s, T(f, "dfmDate"), 1.0, 4.10, 8.0, 0.5, size=24, bold=True,
              color="1F3A6F", align="center", valign="middle")
    _add_picture(s, logo, 7.2, 5.10, 2.2, 0.42)
    _add_text(s, "内部资料 · 注意保密", 0.6, 5.18, 3.0, 0.3, size=10,
              color="8FA3BC", valign="middle")

    # ---------- 1.1 项目信息总览 ----------
    s = _new_slide(prs, "1 项目信息", "1.1 项目信息总览")
    addTbl(s, ["项目", "内容"], [
        ["项目名称", T(f, "projName")], ["零件名称", T(f, "partName")], ["零件号", T(f, "partNo")],
        ["客户名称", T(f, "custName")], ["版本号", T(f, "version")], ["日期", T(f, "dfmDate")],
        ["项目类型", T(f, "projType")],
        ["编制 / 审核 / 批准", T(f, "maker") + " / " + T(f, "checker") + " / " + T(f, "approver")],
    ], x=0.6, y=1.15, w=8.8, fs=11, rowH=0.42, colW=[2.4, 6.4])

    # ---------- 1.2 DFM 履历 ----------
    s = _new_slide(prs, "1 项目信息", "1.2 DFM 履历表")
    addTbl(s, ["版本", "日期", "编制/修订", "主要修改内容", "备注"],
           rowsOf(t, "dfmHist", ["ver", "date", "author", "content", "remark"]),
           x=0.4, y=1.15, w=9.2, fs=10, rowH=0.34, colW=[1.1, 1.4, 1.5, 3.8, 1.4])

    # ---------- 1.3 文件状态 ----------
    s = _new_slide(prs, "1 项目信息", "1.3 文件状态（2D / 3D / ESOW …）")
    addTbl(s, ["文件名称", "文件编号", "版本", "状态", "接收日期", "备注"],
           rowsOf(t, "fileStat", ["name", "code", "ver", "state", "date", "remark"]),
           x=0.4, y=1.15, w=9.2, fs=10, rowH=0.32, colW=[2.0, 1.8, 0.9, 1.1, 1.3, 2.1])

    # ---------- 2.1 产品信息总表 ----------
    s = _new_slide(prs, "2 产品信息", "2.1 产品信息总表")
    wp = N(f, "wCast") + N(f, "wRunner") + N(f, "wOverflow")
    addTbl(s, ["项目", "数值", "项目", "数值"], [
        ["零件号", T(f, "partNo"), "零件名称", T(f, "partName")],
        ["成品重量 (kg)", T(f, "wFinish"), "毛坯重量 (kg)", T(f, "wCast")],
        ["流道重量 (kg)", T(f, "wRunner"), "渣包重量 (kg)", T(f, "wOverflow")],
        ["每次浇注重量 (kg)", {"t": f"{wp:.3f}" if wp else "—", "hi": True}, "基本壁厚 (mm)", T(f, "wall")],
        ["最大壁厚 (mm)", T(f, "wallMax"), "产品尺寸 L×W×H",
         T(f, "dimL") + " × " + T(f, "dimW") + " × " + T(f, "dimH")],
        ["设备吨位 (T)", str(cur_machine(f)["ton"]), "腔数", T(f, "cav")],
        ["铸造压力 (MPa)", T(f, "castP"), "材料牌号",
         T(f, "material") + (" / " + V(f, "matCustom") if V(f, "matCustom") else "")],
        ["年产量 (件/年)", T(f, "annual"), "表面要求", T(f, "surfaceReq")],
        ["气密要求", T(f, "leakReq") + " " + T(f, "leakVal"), "项目类型", T(f, "projType")],
    ], x=0.4, y=1.15, w=9.2, fs=10, rowH=0.36, colW=[2.2, 2.4, 2.2, 2.4])

    # ---------- 2.2 胀型力 / 锁模力 ----------
    c = calc.calc_force(f)
    s = _new_slide(prs, "2 产品信息", "2.2 投影面积 · 胀型力 · 锁模力校核")
    addKV(s, [
        {"k": "产品投影面积", "v": fmt(c["aProd"], 1), "u": "cm²"},
        {"k": "滑块投影面积", "v": fmt(c["aSl"], 1), "u": "cm²"},
        {"k": "产品胀型力", "v": fmt(c["fProd"], 1), "u": "kN", "red": True},
        {"k": "滑块胀型力", "v": fmt(c["fSl"], 1), "u": "kN", "red": True},
        {"k": "总胀型力", "v": fmt(c["fTot"], 1), "u": "kN", "red": True},
        {"k": "总胀型力", "v": fmt(c["fTotT"], 1), "u": "吨", "red": True},
        {"k": "设备锁模力", "v": fmt(c["lock"], 0), "u": "kN"},
        {"k": "锁模力利用率", "v": fmt(c["ratio"], 1), "u": "%", "red": True},
    ], 0.4, 1.15, 9.2)
    addTbl(s, ["项目", "产品+流道+渣包", "滑块", "合计"], [
        ["投影面积 (cm²)", fmt(c["aProd"], 1), fmt(c["aSl"], 1), {"t": fmt(c["aTot"], 1), "hi": True, "n": True}],
        ["胀型力 (kN)", fmt(c["fProd"], 1), fmt(c["fSl"], 1), {"t": fmt(c["fTot"], 1), "hi": True, "n": True}],
        ["胀型力 (吨)", fmt(c["fProd"] * 1 / 9.80665, 1), fmt(c["fSl"] * 1 / 9.80665, 1),
         {"t": fmt(c["fTotT"], 1), "hi": True, "n": True}],
    ], x=0.4, y=2.55, w=9.2, fs=10, rowH=0.3, colW=[3.0, 2.2, 2.0, 2.0])
    addVerdict(s, calc.verdict_of("rForce", f), 3.9)

    # ---------- 2.3 哥林柱 ----------
    c = calc.calc_tiebar(f)
    s = _new_slide(prs, "2 产品信息", "2.3 最大铸造压力评估 · 哥林柱受力分布与平衡度")
    addKV(s, [
        {"k": "最大铸造比压", "v": fmt(c["pMax2"], 0), "u": "MPa"},
        {"k": "总投影面积", "v": fmt(calc.calc_force(f)["aTot"], 1), "u": "cm²"},
        {"k": "总胀型力 F", "v": fmt(c["F"], 1), "u": "kN", "red": True},
        {"k": "单柱平均受力", "v": fmt(c["avg"], 1), "u": "kN"},
        {"k": "最大单柱受力", "v": fmt(c["fmax"], 1), "u": "kN", "red": True},
        {"k": "最小单柱受力", "v": fmt(c["fmin"], 1), "u": "kN", "red": True},
        {"k": "受力平衡度", "v": fmt(c["bal"], 1), "u": "%", "red": True},
        {"k": "最大拉应力", "v": fmt(c["stressMax"], 1), "u": "MPa", "red": True},
    ], 0.4, 1.15, 9.2)
    addTbl(s, ["哥林柱位置", "坐标 (±Bx/2, ±By/2)", "受力 kN", "受力 吨", "占比 %"],
           [[b["n"], "(" + ("+" if b["s"][0] > 0 else "−") + fmt(c["Bx"] / 2, 0) + ", "
             + ("+" if b["s"][1] > 0 else "−") + fmt(c["By"] / 2, 0) + ")",
             {"t": fmt(b["r"], 1), "n": True, "hi": True}, {"t": fmt(b["t"], 2), "n": True},
             {"t": fmt(b["pct"], 1), "n": True}] for b in c["bars"]],
           x=0.4, y=2.55, w=9.2, fs=10, rowH=0.3, colW=[2.6, 2.4, 1.6, 1.4, 1.2])
    addVerdict(s, calc.verdict_of("rTieBar", f), 4.15)

    # ---------- 2.4 机械性能 ----------
    s = _new_slide(prs, "2 产品信息", "2.4 机械性能要求")
    addTbl(s, ["区域/位置", "抗拉强度 Rm", "屈服强度 Rp0.2", "延伸率 A%", "硬度 HB", "备注"],
           rowsOf(t, "mech", ["zone", "rm", "rp", "elong", "hb", "remark"]),
           x=0.4, y=1.15, w=9.2, fs=10, rowH=0.34, colW=[2.4, 1.4, 1.6, 1.2, 1.1, 1.5])

    # ---------- 3.1 包紧力 ----------
    c = calc.calc_hold(f)
    s = _new_slide(prs, "3 工艺计算引擎", "3.1 包紧力计算　F = K·A·P·(η·cosα − sinα)/10000 (吨)")
    addKV(s, [
        {"k": "系数 K", "v": fmt(c["K"], 2)}, {"k": "压强 P", "v": fmt(c["P"], 1), "u": "MPa"},
        {"k": "摩擦系数 η", "v": fmt(c["eta"], 2)}, {"k": "动模侧面积", "v": fmt(c["aDyn"], 0), "u": "mm²"},
        {"k": "定模侧面积", "v": fmt(c["aFix"], 0), "u": "mm²"},
        {"k": "动/定模斜度", "v": fmt(N(f, "alpDyn"), 1) + "° / " + fmt(N(f, "alpFix"), 1) + "°"},
        {"k": "动模侧包紧力", "v": fmt(c["fd"], 2), "u": "吨", "red": True},
        {"k": "定模侧包紧力", "v": fmt(c["ff"], 2), "u": "吨", "red": True},
    ], 0.4, 1.15, 9.2)
    addTbl(s, ["项目", "动模侧", "定模侧", "合计 / 比值"], [
        ["包紧面积 (mm²)", {"t": fmt(c["aDyn"], 0), "n": True}, {"t": fmt(c["aFix"], 0), "n": True},
         {"t": fmt(c["aDyn"] + c["aFix"], 0), "n": True}],
        ["拔模斜度 (°)", {"t": fmt(N(f, "alpDyn"), 1), "n": True}, {"t": fmt(N(f, "alpFix"), 1), "n": True}, "—"],
        ["包紧力 (吨)", {"t": fmt(c["fd"], 2), "n": True, "hi": True}, {"t": fmt(c["ff"], 2), "n": True, "hi": True},
         {"t": fmt(c["sum"], 2), "n": True, "hi": True}],
        ["动/定模包紧力比", "—", "—", {"t": fmt(c["ratio"], 2), "n": True, "hi": True}],
    ], x=0.4, y=2.55, w=9.2, fs=10, rowH=0.3, colW=[3.0, 2.1, 2.1, 2.0])
    addVerdict(s, calc.verdict_of("rHold", f), 4.15)

    # ---------- 3.2 顶杆 ----------
    c = calc.calc_eject(f)
    s = _new_slide(prs, "3 工艺计算引擎", "3.2 顶杆顶出力 · ∅4~∅12 规格选型")
    addKV(s, [
        {"k": "动模侧包紧力", "v": fmt(c["h"]["fd"], 2), "u": "吨"},
        {"k": "安全系数", "v": fmt(c["safe"], 2)},
        {"k": "所需总顶出力", "v": fmt(c["fNeedT"], 2), "u": "吨", "red": True},
        {"k": "选用顶杆直径", "v": "φ" + sstr(c["d"]), "u": "mm"},
        {"k": "单根许用顶出力", "v": fmt(c["f1"], 0), "u": "N", "red": True},
        {"k": "单根许用顶出力", "v": fmt(c["f1T"], 3), "u": "吨", "red": True},
        {"k": "所需根数", "v": str(c["nNeed"]), "red": True},
        {"k": "推荐总数", "v": str(c["nRec"]) + " 根（" + str(c["zones"]) + " 区 × " + str(c["perZone"]) + "）", "red": True},
    ], 0.4, 1.15, 9.2)
    addTbl(s, ["顶杆直径", "截面积 mm²", "许用顶出力 N", "许用顶出力 吨", "所需根数", "是否加凸台", "凹入产品标识"],
           [["φ" + str(x["d"]), {"t": fmt(x["A"], 2), "n": True}, {"t": fmt(x["F"], 0), "n": True},
             {"t": fmt(x["ton"], 3), "n": True}, {"t": str(x["n"]), "n": True, "hi": x["d"] == c["d"]},
             x["boss"], x["mark"]] for x in c["spec"]],
           x=0.4, y=2.55, w=9.2, fs=9, rowH=0.26, colW=[1.1, 1.3, 1.6, 1.6, 1.1, 1.3, 1.2])
    addVerdict(s, calc.verdict_of("rEject", f), 4.35)

    # ---------- 3.3 挤压销 ----------
    c = calc.calc_squeeze(f)
    s = _new_slide(prs, "3 工艺计算引擎", "3.3 挤压销计算　V = L·h·w·a（a=6%）")
    addKV(s, [
        {"k": "挤压体积 V", "v": fmt(c["V"], 1), "u": "mm³", "red": True},
        {"k": "挤压销直径", "v": fmt(c["d"], 1), "u": "mm"},
        {"k": "挤压行程", "v": fmt(c["stroke"], 2), "u": "mm", "red": True},
        {"k": "挤压比压", "v": fmt(c["P"], 0), "u": "MPa"},
        {"k": "挤压力", "v": fmt(c["Fsq"], 2), "u": "kN", "red": True},
        {"k": "挤压阻力", "v": fmt(c["Fres"], 2), "u": "kN", "red": True},
        {"k": "理论缸径", "v": fmt(c["Dcyl"], 1), "u": "mm", "red": True},
        {"k": "选用缸径", "v": "∅" + str(c["Dstd"]) + "（推力 " + fmt(c["Freal"], 1) + " kN）", "red": True},
    ], 0.4, 1.15, 9.2)
    addTbl(s, ["挤压区域 L×h×w", "空隙率 a", "行程/直径比", "导向长度 mm", "待补偿缩孔体积 mm³", "体积补偿率"], [
        [fmt(c["L"], 1) + " × " + fmt(c["h"], 1) + " × " + fmt(c["w"], 1), fmt(c["a"] * 100, 1) + "%",
         {"t": fmt(c["ratio"], 2), "n": True}, {"t": fmt(N(f, "sqLg"), 0), "n": True},
         {"t": T(f, "sqShrink"), "n": True}, {"t": fmt(c["cover"], 2) if c["shrink"] else "—", "n": True, "hi": True}],
    ], x=0.4, y=2.55, w=9.2, fs=10, rowH=0.3, colW=[2.2, 1.1, 1.3, 1.3, 1.7, 1.6])
    addVerdict(s, calc.verdict_of("rSqueeze", f), 3.25)
    addImgs(s, "sqImg", 0.4, 4.25, 9.2, 0.95, 3)

    # ---------- 3.4 滑块缸径 ----------
    c = calc.calc_slider(f)
    s = _new_slide(prs, "3 工艺计算引擎", "3.4 滑块油缸缸径计算（K=1.3，系统压力 16 MPa）")
    addKV(s, [
        {"k": "滑块包紧面积", "v": fmt(c["A"], 0), "u": "mm²"},
        {"k": "抽芯斜度", "v": fmt(c["alpha"], 1), "u": "°"},
        {"k": "抽芯阻力", "v": fmt(c["Fres"], 2), "u": "吨", "red": True},
        {"k": "抽芯力 F抽", "v": fmt(c["Fpull"], 2), "u": "吨", "red": True},
        {"k": "导轨摩擦阻力", "v": fmt(c["Ffric"], 2), "u": "吨"},
        {"k": "油缸需推力", "v": fmt(c["Fneed"], 2), "u": "吨", "red": True},
        {"k": "理论缸径", "v": fmt(c["Dcyl"], 1), "u": "mm", "red": True},
        {"k": "选用缸径", "v": "∅" + str(c["Dstd"]) + "（" + fmt(c["Freal"], 2) + " 吨）", "red": True},
        {"k": "滑块数量", "v": sstr(c["num"]), "u": "个"},
        {"k": "抽芯行程", "v": fmt(c["stroke"], 0), "u": "mm"},
    ], 0.4, 1.15, 9.2)
    addVerdict(s, calc.verdict_of("rSlider", f), 3.1)

    # ---------- 3.5 抽真空 ----------
    c = calc.calc_vacuum(f)
    s = _new_slide(prs, "3 工艺计算引擎", "3.5 抽真空计算与校核")
    addKV(s, [
        {"k": "压室容积", "v": fmt(c["vSleeve"], 2), "u": "L"},
        {"k": "总抽气容积 V", "v": fmt(c["V"], 2), "u": "L", "red": True},
        {"k": "目标真空度", "v": fmt(c["P1"], 0), "u": "mbar"},
        {"k": "允许抽气时间", "v": fmt(c["t"], 2), "u": "s"},
        {"k": "平均抽气量 Qv", "v": fmt(c["Qv"], 2), "u": "L/s", "red": True},
        {"k": "所需泵抽速 S", "v": fmt(c["S"], 1), "u": "m³/h", "red": True},
        {"k": "阀口排气截面积", "v": fmt(c["Avalve"], 1), "u": "mm²", "red": True},
        {"k": "实际所需时间", "v": fmt(c["tNeed"], 2) if c["pump"] else "—", "u": "s", "red": True},
    ], 0.4, 1.15, 9.2)
    addTbl(s, ["真空阀类型", "型号/规格", "单阀截面积 mm²", "数量", "总截面积 mm²", "真空泵抽速 m³/h"], [
        [T(f, "vvType"), T(f, "vvModel"), {"t": fmt(N(f, "vvArea"), 1), "n": True},
         {"t": sstr(N(f, "vvNum") or 1), "n": True},
         {"t": fmt(N(f, "vvArea") * (N(f, "vvNum") or 1), 1), "n": True, "hi": True},
         {"t": T(f, "vcPump"), "n": True}],
    ], x=0.4, y=2.55, w=9.2, fs=10, rowH=0.3, colW=[1.6, 1.6, 1.6, 0.9, 1.6, 1.9])
    addVerdict(s, calc.verdict_of("rVacuum", f), 3.25)
    addImgs(s, "vvImg", 0.4, 4.25, 9.2, 0.95, 3)

    # ---------- 3.6 冷却水 ----------
    c = calc.calc_cool(f)
    s = _new_slide(prs, "3 工艺计算引擎", "3.6 冷却水量与冷却时间校核　Q总 = C铝·M·ΔT + M·凝固潜热")
    addKV(s, [
        {"k": "浇注金属量 M", "v": fmt(c["M"], 3), "u": "kg"},
        {"k": "显热 Q₁", "v": fmt(c["Qs"], 0), "u": "kJ"},
        {"k": "潜热 Q₂", "v": fmt(c["Ql"], 0), "u": "kJ"},
        {"k": "总热量 Q总", "v": fmt(c["Q"], 0), "u": "kJ", "red": True},
        {"k": "需水量 W", "v": fmt(c["W"], 1), "u": "L", "red": True},
        {"k": "所需水流量", "v": fmt(c["flowNeed"], 1) if c["flowNeed"] else "—", "u": "L/min", "red": True},
        {"k": "实际水流量", "v": fmt(c["flowAct"], 1) if c["flowAct"] else "—", "u": "L/min"},
        {"k": "实际冷却时间", "v": fmt(c["tAct"], 1) if c["tAct"] else "—", "u": "s", "red": True},
    ], 0.4, 1.15, 9.2)
    addVerdict(s, calc.verdict_of("rCool", f), 2.9)
    addImgs(s, "dcImg", 0.4, 3.95, 9.2, 1.25, 3)

    # ---------- 4.1 分型方案 ----------
    s = _new_slide(prs, "4 模具结构", "4.1 3D / 2D 分型方案与分型线")
    addImgs(s, "plImg3d", 0.4, 1.15, 4.5, 2.5, 2)
    addImgs(s, "plImg2d", 5.1, 1.15, 4.5, 2.5, 2)
    addBlock(s, "分型线描述", V(f, "plLine"), 0.4, 3.8, 4.5, 1.4)
    addBlock(s, "分型面选择依据", V(f, "plBase"), 5.1, 3.8, 4.5, 1.4)

    # ---------- 4.2 镶拼总档 ----------
    s = _new_slide(prs, "4 模具结构", "4.2 镶拼总档与反拔模斜度")
    addImgs(s, "insImg", 0.4, 1.15, 4.5, 2.6, 2)
    addBlock(s, "镶拼总档方案", V(f, "insPlan"), 5.1, 1.15, 4.5, 1.3)
    addBlock(s, "反拔模斜度处理", V(f, "antiDraft"), 5.1, 2.6, 4.5, 1.15)
    addBlock(s, "补充说明（材料/工艺）", V(f, "dcSurfNote"), 0.4, 3.9, 9.2, 1.3)

    # ---------- 4.3 材料备料表 ----------
    s = _new_slide(prs, "4 模具结构", "4.3 模具材料备料表")
    addTbl(s, ["序号", "部件", "牌号", "硬度", "供应商", "尺寸", "重量 kg"],
           rowsOf(t, "matList", ["no", "part", "grade", "hard", "supplier", "size", "weight"]),
           x=0.4, y=1.15, w=9.2, fs=10, rowH=0.32, colW=[0.7, 2.3, 1.2, 1.3, 1.4, 1.2, 1.1])

    # ---------- 4.4 总装尺寸 ----------
    s = _new_slide(prs, "4 模具结构", "4.4 模具总装尺寸")
    addTbl(s, ["项目", "长 L (mm)", "宽 W (mm)", "高 H (mm)", "重量 kg", "备注"],
           rowsOf(t, "asm", ["item", "l", "w", "h", "wt", "remark"]),
           x=0.4, y=1.15, w=9.2, fs=10, rowH=0.34, colW=[2.4, 1.3, 1.3, 1.3, 1.2, 1.7])
    m = cur_machine(f)
    addVerdict(s, "设备匹配：" + m["brand"] + " " + m["model"] + "，容模量 " + str(m["moldMin"]) + "~"
               + str(m["moldMax"]) + " mm，哥林柱间距 " + m["tie"] + " mm，模板 " + m["plate"]
               + " mm；模具闭合高度须落在容模量范围内，外形尺寸须小于哥林柱内距。", 4.1)

    # ---------- 4.5 镶块深腔 / 冷却 / 表面处理 ----------
    s = _new_slide(prs, "4 模具结构", "4.5 镶块深腔设计 · 冷却与表面处理")
    addBlock(s, "深腔镶块设计说明", V(f, "dcDesign"), 0.4, 1.15, 9.2, 1.5)
    addTbl(s, ["冷却方式", "表面处理", "补充说明"], [
        [T(f, "dcCool"), T(f, "dcSurf"), T(f, "dcSurfNote")],
    ], x=0.4, y=2.8, w=9.2, fs=10, rowH=0.32, colW=[3.0, 2.6, 3.6])
    addImgs(s, "dcImg", 0.4, 3.35, 9.2, 1.85, 3)

    # ---------- 5.1 流道理念 ----------
    s = _new_slide(prs, "5 浇排与工艺系统", "5.1 流道理念")
    addImgs(s, "grImg", 0.4, 1.15, 5.6, 3.2, 2)
    addBlock(s, "流道与排溢理念说明", V(f, "grText"), 6.2, 1.15, 3.4, 3.2)

    # ---------- 5.2 真空阀选型 ----------
    s = _new_slide(prs, "5 浇排与工艺系统", "5.2 真空阀选型（机械阀 / 排气块 / 主动阀）")
    addTbl(s, ["真空阀类型", "型号/规格", "单阀截面积 mm²", "数量", "总截面积 mm²", "所需截面积 mm²"], [
        [T(f, "vvType"), T(f, "vvModel"), {"t": fmt(N(f, "vvArea"), 1), "n": True},
         {"t": sstr(N(f, "vvNum") or 1), "n": True},
         {"t": fmt(N(f, "vvArea") * (N(f, "vvNum") or 1), 1), "n": True, "hi": True},
         {"t": fmt(calc.calc_vacuum(f)["Avalve"], 1), "n": True, "hi": True}],
    ], x=0.4, y=1.15, w=9.2, fs=10, rowH=0.32, colW=[1.7, 1.7, 1.6, 0.9, 1.7, 1.6])
    addImgs(s, "vvImg", 0.4, 1.75, 5.6, 2.4, 2)
    addBlock(s, "真空方案说明", V(f, "vvText"), 6.2, 1.75, 3.4, 2.4)
    addVerdict(s, calc.verdict_of("rVacuum", f), 4.3, 0.4, 5.6)

    # ---------- 5.3 压射参数 ----------
    c = calc.calc_inject(f)
    s = _new_slide(prs, "5 浇排与工艺系统", "5.3 冲头直径 / 内浇口面积 / 速率比 / 内浇口速度 / 填充时间 / 快压射速度")
    addKV(s, [
        {"k": "冲头直径", "v": fmt(c["D"], 0), "u": "mm"},
        {"k": "冲头面积", "v": fmt(c["Ap"], 1), "u": "mm²"},
        {"k": "内浇口面积", "v": fmt(c["Ag"], 1), "u": "mm²"},
        {"k": "速率比 R", "v": fmt(c["R"], 2), "red": True},
        {"k": "型腔体积", "v": fmt(c["vol"], 1), "u": "cm³"},
        {"k": "填充时间", "v": fmt(c["t"], 3), "u": "s", "red": True},
        {"k": "内浇口速度", "v": fmt(c["vg"], 1), "u": "m/s", "red": True},
        {"k": "快压射速度", "v": fmt(c["vp"], 2), "u": "m/s", "red": True},
        {"k": "慢压射速度", "v": fmt(N(f, "injSlow"), 2), "u": "m/s"},
        {"k": "切换位置", "v": T(f, "injSwitch"), "u": "mm"},
    ], 0.4, 1.15, 9.2)
    addVerdict(s, calc.verdict_of("rInject", f), 3.15)
    addTbl(s, ["铸件壁厚 mm", "内浇口速度 m/s", "说明"],
           [[r[0], {"t": r[1], "hi": True}, r[2]] for r in GATE_SPEED_TABLE],
           x=0.4, y=4.2, w=9.2, fs=8.5, rowH=0.19, colW=[1.8, 2.0, 5.4])

    # ---------- 5.4 密封方案 ----------
    s = _new_slide(prs, "5 浇排与工艺系统", "5.4 密封方案（8 项）")
    addTbl(s, ["序号", "密封位置", "密封形式", "规格", "说明"],
           rowsOf(t, "seal", ["no", "item", "type", "spec", "remark"]),
           x=0.4, y=1.15, w=9.2, fs=10, rowH=0.36, colW=[0.8, 2.4, 2.0, 1.6, 2.4])

    # ---------- 5.5 挤压销布置 ----------
    s = _new_slide(prs, "5 浇排与工艺系统", "5.5 挤压销布置与配合间隙")
    addImgs(s, "sqImg", 0.4, 1.15, 5.6, 2.6, 2)
    addTbl(s, ["配合间隙", "冷却方式"], [[T(f, "sqGap"), T(f, "sqCool")]],
           x=6.2, y=1.15, w=3.4, fs=10, rowH=0.36, colW=[1.7, 1.7])
    addBlock(s, "挤压销布置说明", V(f, "sqLayout"), 6.2, 1.75, 3.4, 2.0)
    addBlock(s, "挤压销计算结果", calc.verdict_of("rSqueeze", f), 0.4, 3.9, 9.2, 1.3)

    # ---------- 5.6 PQ² ----------
    p = calc.calc_pq2(f)
    s = _new_slide(prs, "5 浇排与工艺系统", "5.6 PQ² 工艺窗口与设备匹配")
    addKV(s, [
        {"k": "机型", "v": p["m"]["brand"] + " " + p["m"]["model"]},
        {"k": "压射力", "v": fmt(p["injF"], 0), "u": "kN"},
        {"k": "最大比压 Pmax", "v": fmt(p["Pmax"], 1), "u": "MPa", "red": True},
        {"k": "最大流量 Qmax", "v": fmt(p["Qmax"], 1), "u": "L/s", "red": True},
        {"k": "工艺点流量 Q", "v": fmt(p["Q"], 2), "u": "L/s", "red": True},
        {"k": "需求比压", "v": fmt(p["Pneed"], 1), "u": "MPa", "red": True},
        {"k": "机器线可用比压", "v": fmt(p["Pline"], 1), "u": "MPa", "red": True},
        {"k": "压力余量", "v": fmt(p["margin"], 1), "u": "%", "red": True},
    ], 0.4, 1.15, 5.4)
    addTbl(s, ["流量 Q (L/s)", "可用比压 P (MPa)"],
           [[{"t": x[0], "n": True}, {"t": x[1], "n": True, "hi": True}] for x in p["pts"]],
           x=6.0, y=1.15, w=3.6, fs=9.5, rowH=0.3, colW=[1.8, 1.8])
    addVerdict(s, calc.verdict_of("rPQ2", f), 3.1)

    # ---------- 6.1 当前机型参数 ----------
    m = cur_machine(f)
    s = _new_slide(prs, "6 压铸机参数库", "6.1 当前机型参数（选中后自动填充）")
    addTbl(s, ["参数", "数值", "单位"], [
        ["品牌 / 型号", m["brand"] + " " + m["model"], ""],
        ["锁模力", fmt(m["lock"], 0), "kN"],
        ["锁模力", fmt(m["ton"], 0), "T"],
        ["开模行程", fmt(m["open"], 0), "mm"],
        ["容模量（最小 ~ 最大）", fmt(m["moldMin"], 0) + " ~ " + fmt(m["moldMax"], 0), "mm"],
        ["哥林柱间距（内距）", m["tie"], "mm"],
        ["哥林柱直径", fmt(m["tieDia"], 0), "mm"],
        ["模板尺寸", m["plate"], "mm"],
        ["压射力", fmt(m["injForce"], 0), "kN"],
        ["压射行程", fmt(m["injStroke"], 0), "mm"],
        ["冲头直径可选", " / ".join(str(x) for x in m["punch"]), "mm"],
        ["空压射速度", fmt(m["v0"], 1), "m/s"],
        ["顶出力", fmt(m["ejForce"], 0), "kN"],
        ["顶出行程", fmt(m["ejStroke"], 0), "mm"],
    ], x=0.4, y=1.15, w=9.2, fs=10, rowH=0.27, colW=[3.6, 3.4, 2.2])

    # ---------- 6.2 机型对照表 ----------
    s = _new_slide(prs, "6 压铸机参数库", "6.2 机型对照表（力劲 / 布勒）")
    addTbl(s, ["品牌", "型号", "吨位 T", "锁模力 kN", "开模行程", "容模量 mm", "哥林柱间距", "柱径", "压射力 kN", "冲头直径", "空压射", "顶出力"],
           [[m["brand"], ("● " + m["model"]) if (m["brand"] + " " + m["model"]) == V(f, "machineId") else m["model"],
             {"t": fmt(m["ton"], 0), "n": True}, {"t": fmt(m["lock"], 0), "n": True},
             {"t": fmt(m["open"], 0), "n": True}, fmt(m["moldMin"], 0) + "~" + fmt(m["moldMax"], 0),
             m["tie"], {"t": fmt(m["tieDia"], 0), "n": True}, {"t": fmt(m["injForce"], 0), "n": True},
             "/".join(str(x) for x in m["punch"]), {"t": fmt(m["v0"], 1), "n": True},
             {"t": fmt(m["ejForce"], 0), "n": True}] for m in MACHINES],
           x=0.4, y=1.15, w=9.2, fs=7.5, rowH=0.26, colW=[0.95, 1.45, 0.55, 0.75, 0.65, 0.85, 0.75, 0.45, 0.75, 0.85, 0.55, 0.65])

    # ---------- 7.1 ~ 7.10 模流分析 10 项 ----------
    FLOW_ITEMS = [
        ("f01", "1 速度", "含壁厚 - 内浇口速度经验对照表", "speedTable"),
        ("f02", "2 卷气", "卷气位置与卷入量评估", None),
        ("f03", "3 气压", "型腔残余气压与排气能力", None),
        ("f04", "4 填充温度", "高/中/低温分区", None),
        ("f05", "5 料液追踪", "金属流前沿汇合位置", None),
        ("f06", "6 固相分数", "凝固顺序与固相分布", None),
        ("f07", "7 氧化物", "氧化夹杂聚集区域", None),
        ("f08", "8 缩孔", "ASTM 等级与点冷优化", "astm"),
        ("f09", "9 填充率", "填充完整性与短射风险", None),
        ("f10", "10 热平衡与变形", "模具热平衡与铸件变形", None),
    ]
    for idx, (k, tname, tip, extra) in enumerate(FLOW_ITEMS):
        name = re.sub(r"^\d+\s*", "", tname)
        s = _new_slide(prs, "7 模流分析", "7." + str(idx + 1) + " " + name + "　—　" + tip)
        addImgs(s, k + "Img", 0.4, 1.15, 5.6, 3.0, 2)
        addBlock(s, "结论", V(f, k + "Conc"), 6.2, 1.15, 3.4, 1.5)
        addBlock(s, "优化方案", V(f, k + "Opt"), 6.2, 2.75, 3.4, 1.4)
        if extra == "astm":
            addTbl(s, ["缩孔等级", "缩孔位置", "点冷优化方案"],
                   [[T(f, k + "Astm"), T(f, k + "Area"), T(f, k + "Cool")]],
                   x=0.4, y=4.3, w=9.2, fs=9.5, rowH=0.3, colW=[2.4, 3.0, 3.8])
        elif extra == "speedTable":
            addTbl(s, ["壁厚 mm", "内浇口速度 m/s", "说明"],
                   [[r[0], {"t": r[1], "hi": True}, r[2]] for r in GATE_SPEED_TABLE],
                   x=0.4, y=4.3, w=9.2, fs=8, rowH=0.18, colW=[1.4, 2.0, 5.8])
        else:
            addBlock(s, "补充说明", tip, 0.4, 4.3, 5.6, 0.9)

    # ---------- 8.1 / 8.2 SPR ----------
    s = _new_slide(prs, "8 质量策划", "8.1 SPR 点位分析（第 1 页）")
    addImgs(s, "spr1Img", 0.4, 1.15, 5.6, 2.6, 2)
    addBlock(s, "SPR 分析说明", V(f, "spr1Text"), 6.2, 1.15, 3.4, 2.6)
    addTbl(s, ["点位", "位置描述", "局部壁厚 mm", "风险评估", "措施"],
           rowsOf(t, "spr1Table", ["no", "pos", "thick", "risk", "act"]),
           x=0.4, y=3.9, w=9.2, fs=9, rowH=0.26, colW=[1.0, 2.8, 1.2, 1.0, 3.2])

    s = _new_slide(prs, "8 质量策划", "8.2 SPR 点位分析（第 2 页）")
    addImgs(s, "spr2Img", 0.4, 1.15, 5.6, 3.0, 2)
    addBlock(s, "SPR 分析说明", V(f, "spr2Text"), 6.2, 1.15, 3.4, 3.0)
    addBlock(s, "包紧力 / 顶出结论（影响 SPR 点位布置）", calc.verdict_of("rHold", f), 0.4, 4.3, 9.2, 0.9)

    # ---------- 8.3 追溯策划 ----------
    s = _new_slide(prs, "8 质量策划", "8.3 追溯策划（激光打码位置 / 二维码样式）")
    addTbl(s, ["激光打码位置", "二维码样式", "码尺寸", "编码规则"], [
        [T(f, "trPos"), T(f, "trQr"), T(f, "trSize"), T(f, "trContent")],
    ], x=0.4, y=1.15, w=9.2, fs=10, rowH=0.34, colW=[2.4, 2.0, 1.6, 3.2])
    addImgs(s, "trImg", 0.4, 1.75, 5.6, 2.4, 2)
    addBlock(s, "追溯策划说明", V(f, "trText"), 6.2, 1.75, 3.4, 2.4)
    addBlock(s, "补充说明", "追溯码应布置在非加工、非装配、非外观面，且便于扫码与激光打码设备可达。", 0.4, 4.3, 9.2, 0.9)

    # ---------- 8.4 图纸公差可行性 ----------
    s = _new_slide(prs, "8 质量策划", "8.4 图纸公差可行性评估与修改建议")
    addTbl(s, ["序号", "公差项", "图纸要求", "工艺能力", "可行性", "修改建议"],
           rowsOf(t, "tol", ["no", "item", "req", "cap", "feas", "prop"]),
           x=0.4, y=1.15, w=9.2, fs=10, rowH=0.36, colW=[0.7, 2.0, 1.5, 1.9, 1.0, 2.1])

    # ---------- 9.1 问题清单 ----------
    s = _new_slide(prs, "9 问题清单", "9.1 开口问题清单（问题描述 / 修改方案 / 客户回复）")
    addTbl(s, ["序号", "问题描述", "修改方案 / 建议", "客户回复", "状态"],
           rowsOf(t, "issues", ["no", "desc", "prop", "fb", "st"]),
           x=0.4, y=1.15, w=9.2, fs=10, rowH=0.42, colW=[0.8, 3.0, 3.0, 1.6, 0.8])

    # ---------- 10.1 模具温度 ----------
    s = _new_slide(prs, "10 技术应用与结尾", "10.1 模具温度与热管理")
    addTbl(s, ["项目", "温度 ℃", "说明"], [
        ["定模目标温度", T(f, "tFix"), ""],
        ["动模目标温度", T(f, "tDyn"), ""],
        ["型芯 / 镶块温度", T(f, "tCore"), ""],
        ["模具预热温度", T(f, "tPre"), ""],
        ["温控方式", "—", T(f, "tCtrl")],
    ], x=0.4, y=1.15, w=9.2, fs=10, rowH=0.32, colW=[2.6, 1.6, 5.0])
    addBlock(s, "模具温度控制策略", V(f, "tText"), 0.4, 3.1, 9.2, 2.1)

    # ---------- 10.2 压铸岛 ----------
    s = _new_slide(prs, "10 技术应用与结尾", "10.2 压铸岛：温控 / 喷涂 / 真空设计")
    addImgs(s, "isImg", 0.4, 1.15, 4.5, 2.3, 2)
    addBlock(s, "压铸岛温控设计", V(f, "isTemp"), 5.1, 1.15, 4.5, 1.15)
    addBlock(s, "喷涂方案（" + T(f, "isSpray") + "）", V(f, "isSprayText"), 5.1, 2.4, 4.5, 1.05)
    addBlock(s, "真空系统设计", V(f, "isVac"), 0.4, 3.6, 9.2, 1.6)

    # ---------- 10.3 公司介绍 ----------
    s = _new_slide(prs, "10 技术应用与结尾", "10.3 公司介绍")
    addBlock(s, "公司介绍", V(f, "coIntro"), 0.4, 1.15, 9.2, 3.9)

    # ---------- 致谢 ----------
    s = _new_slide(prs, "", "", plain=True)
    s.background.fill.solid()
    s.background.fill.fore_color.rgb = _color("0E1725")
    _add_rect(s, 0, 0, PW, 0.14, fill=C_ORANGE)
    _add_text(s, "致　谢", 0.8, 1.9, 8.4, 0.9, size=36, bold=True, color="FFFFFF",
              align="center")
    _add_text(s, V(f, "thanks") or "感谢客户团队在本次 DFM 交流中的支持与配合。",
              1.4, 3.0, 7.2, 1.0, size=15, color="C9D8EC", align="center", valign="middle")
    _add_text(s, T(f, "company"), 1.4, 4.4, 7.2, 0.4, size=12, color="8FA3BC", align="center")

    # ---------- 10.4 保密声明 ----------
    s = _new_slide(prs, "10 技术应用与结尾", "10.4 保密声明")
    addBlock(s, "保密声明", V(f, "secret"), 0.4, 1.15, 9.2, 2.0)
    addTbl(s, ["零件号", "版本号", "日期", "编制"], [
        [T(f, "partNo"), T(f, "version"), T(f, "dfmDate"), T(f, "maker")],
    ], x=0.4, y=3.5, w=9.2, fs=11, rowH=0.36, colW=[2.3, 2.3, 2.3, 2.3])

    # ---------- 输出 ----------
    buf = io.BytesIO()
    prs.save(buf)
    buf.seek(0)
    return buf


def safe_filename(f):
    no = re.sub(r'[\\/:*?"<>|]', "_", str(V(f, "partNo") or "PartNo"))
    ver = re.sub(r'[\\/:*?"<>|]', "_", str(V(f, "version") or "A0"))
    return "DFM_" + no + "_" + ver + ".pptx"
