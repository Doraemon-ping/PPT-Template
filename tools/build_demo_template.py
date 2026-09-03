# -*- coding: utf-8 -*-
"""Build the placeholder demo template used by the template engine demo deck.

The template is a small 3-page deck with ``{path}`` placeholders, following the
pptx-template convention:
  - page 1: cover fields
  - page 2: part specifications + a picture placeholder bound to ``i.logoImg[0]``
  - page 3: an issue card repeated over ``t.issues`` (item-scope placeholders)

This utility is template authoring time only; runtime generation never resaves
the package through python-pptx.
"""
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.util import Inches, Pt

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "templates" / "DFM_Template_Placeholder_Demo.pptx"
LOGO = ROOT / "app" / "assets" / "logo.png"

FONT = "微软雅黑"


def _rgb(value):
    return RGBColor.from_string(value.lstrip("#"))


def add_text(slide, name, text, x, y, w, h, size=16, bold=False, color="1F3A6F"):
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    box.name = name
    tf = box.text_frame
    tf.word_wrap = True
    paragraph = tf.paragraphs[0]
    run = paragraph.add_run()
    run.text = text
    run.font.name = FONT
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = _rgb(color)
    return box


def main():
    prs = Presentation()
    prs.slide_width = Inches(10)
    prs.slide_height = Inches(5.625)
    blank = prs.slide_layouts[6]

    # ---------------- 1 封面 ----------------
    cover = prs.slides.add_slide(blank)
    add_text(cover, "COVER_PART_NUMBER", "{f.partNo}", 1.0, 1.4, 8.0, 0.9, size=44, bold=True)
    add_text(cover, "COVER_PROJECT_NAME", "{f.projName}", 1.0, 2.5, 8.0, 0.5, size=20, bold=True)
    add_text(cover, "COVER_CUSTOMER", "客户：{f.custName}", 1.0, 3.1, 8.0, 0.4, size=14)
    add_text(cover, "COVER_DATE", "日期：{f.dfmDate}", 1.0, 3.6, 8.0, 0.4, size=14)
    add_text(cover, "COVER_VERSION", "版本：{f.version}", 1.0, 4.1, 8.0, 0.4, size=14)

    # ---------------- 2 产品信息 ----------------
    info = prs.slides.add_slide(blank)
    pic = info.shapes.add_picture(str(LOGO), Inches(0.4), Inches(0.5), Inches(3.2), Inches(1.2))
    pic.name = "PART_IMAGE"
    rows = [
        ("毛坯重量 (kg)", "{f.wCast}", 2.0),
        ("成品重量 (kg)", "{f.wFinish}", 2.6),
        ("基本壁厚 (mm)", "{f.wall}", 3.2),
        ("最大壁厚 (mm)", "{f.wallMax}", 3.8),
        ("铸造压力 (MPa)", "{f.castP}", 4.4),
        ("材料牌号", "{f.material}", 5.0),
    ]
    for label, placeholder, y in rows:
        add_text(info, "PART_LABEL_" + label, label, 4.4, y, 2.4, 0.4, size=14, color="6B7684")
        add_text(info, "PART_VALUE_" + label, placeholder, 6.9, y, 2.4, 0.4, size=14, bold=True)
    # ---------------- 3 问题卡片（repeat over t.issues） ----------------
    issue = prs.slides.add_slide(blank)
    add_text(issue, "ISSUE_NO", "问题 {no}", 0.5, 0.6, 2.0, 0.5, size=18, bold=True)
    add_text(issue, "ISSUE_STATUS", "状态：{st}", 7.6, 0.6, 2.0, 0.5, size=14)
    add_text(issue, "ISSUE_DESCRIPTION", "{desc}", 0.5, 1.4, 9.0, 1.4, size=16)
    add_text(issue, "ISSUE_RECOMMENDATION", "建议：{prop}", 0.5, 3.0, 9.0, 1.2, size=14, color="0F7A37")
    add_text(issue, "ISSUE_CUSTOMER_FEEDBACK", "客户回复：{fb}", 0.5, 4.3, 9.0, 0.6, size=14)

    prs.save(OUT)
    print(f"saved: {OUT}")


if __name__ == "__main__":
    main()
