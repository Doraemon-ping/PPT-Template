# -*- coding: utf-8 -*-
"""按项目 id 校验「机加 DFM → PPT 工作台」的取数与绑定整条链路。

用途：DFM 表单保存后跳转工作台（``/template-editor?app_id=machining-dfm&project_id=<项目 id>``），
本脚本用同一套 HTTP 契约直接验证「工作台能否按项目 id 取到工序/设备/工艺/问题，并真的绑进 PPT」。

它做四件事：

1. 读工作台数据源清单，确认机加数据源已连接（否则打印 connections.json 的修法）；
2. 读项目清单并挑一个项目（可用 ``--project`` 指定）；
3. 拉项目快照，报告工序/设备/刀具/夹具/检具/问题/计算结果的表名与行数；
4. 用该快照做一次真实生成：封面字段 + 产品图片 + 工序整表 + 问题文字，
   并解包生成的 PPTX，确认数据真的写进了页面。

只读工作台与表单服务，不写任何业务数据；生成结果写到 ``--output``（默认临时目录）。

用法::

    python scripts/check_machining_binding.py
    python scripts/check_machining_binding.py --project <项目 id> --template dfm----20260305
    python scripts/check_machining_binding.py --workbench http://127.0.0.1:8003 --source machining-dfm
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import tempfile
import zipfile
from pathlib import Path

import httpx

#: 交互终端交给控制台自己编码（中文正常），被重定向/管道时统一 UTF-8，日志里不会变乱码。
if not sys.stdout.isatty() and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

#: 数据源里的业务数组路径 → 中文名。表键由提供方按路径生成（``<路径>_<哈希>``），
#: 因此这里按前缀匹配，项目之间可复用同一份绑定方案。
EXPECTED_TABLES = {
    "pr": "工序",
    "pr.tl": "工序 · 刀具明细（工艺）",
    "mdb": "设备库",
    "tdb": "刀具库",
    "is": "问题清单",
    "fdb": "夹具库",
    "idb": "检具库",
    "vh": "版本履历",
    "computed.processes": "工序计算结果（节拍/产能）",
}


def table_path(source_path: str) -> str:
    return str(source_path or "").replace("[*]", "")


def api(client: httpx.Client, method: str, url: str, **kwargs):
    response = client.request(method, url, **kwargs)
    if response.status_code >= 400:
        detail = response.text[:400]
        raise SystemExit(f"[失败] {method} {url} -> HTTP {response.status_code}\n{detail}")
    return response


def main() -> int:
    parser = argparse.ArgumentParser(description="校验机加 DFM 项目数据在工作台的绑定链路")
    parser.add_argument("--workbench", default="http://127.0.0.1:8003")
    parser.add_argument("--source", default="machining-dfm")
    parser.add_argument("--project", default="", help="项目 id；省略时取最近更新的项目")
    parser.add_argument("--template", default="", help="模板 id；省略时取该数据源第一个模板")
    parser.add_argument("--output", default="", help="生成的 pptx 存放路径")
    parser.add_argument("--save-scheme", default="",
                        help="把本次绑定保存成该名字的方案，再按方案复用生成一次（会写入工作台数据）")
    args = parser.parse_args()

    base = args.workbench.rstrip("/")
    source = args.source
    with httpx.Client(timeout=180) as client:
        # 1) 数据源
        listing = api(client, "GET", f"{base}/api/ppt/sources").json()
        match = next((item for item in listing.get("sources", []) if item["id"] == source), None)
        if match is None:
            print(f"[失败] 工作台没有数据源 {source}。errors={listing.get('errors')}")
            print("       请在工作台数据目录写 connections.json，例如：")
            print('       {"connections":[{"id":"machining","base_url":"http://127.0.0.1:8002"}]}')
            return 2
        print(f"[1/4] 数据源 {source} 已连接 -> {match.get('form_url', '')}")

        # 2) 项目
        projects = api(client, "GET", f"{base}/api/ppt/sources/{source}/projects").json()["projects"]
        if not projects:
            print("[失败] 该数据源没有可用项目，请先在机加 DFM 表单里保存一个项目")
            return 2
        project = next((item for item in projects if item["id"] == args.project), None) if args.project else projects[0]
        if project is None:
            print(f"[失败] 项目不存在或已删除：{args.project}")
            return 2
        print(f"[2/4] 项目 {project['name']}（id={project['id']}，版本 {project['revision']}）")

        # 3) 快照
        snapshot = api(
            client, "GET", f"{base}/api/ppt/sources/{source}/projects/{project['id']}/snapshot"
        ).json()
        catalog, data = snapshot["catalog"], snapshot["data"]
        by_path = {table_path(meta.get("source_path")): name for name, meta in catalog["tables"].items()}
        missing = []
        print("[3/4] 快照目录覆盖：")
        for path, label in EXPECTED_TABLES.items():
            name = by_path.get(path)
            rows = len(data["t"].get(name) or []) if name else 0
            flag = "OK " if name and rows else ("空 " if name else "缺 ")
            if not name:
                missing.append(path)
            print(f"      {flag}{label:<22} {name or '-'} rows={rows}")
        print(f"      标量字段 {len(catalog['fields'])} 个，图片 {len(catalog['images'])} 个")
        pr_rows = data["t"].get(by_path.get("pr") or "") or []
        for index, row in enumerate(pr_rows, 1):
            selected = "工序选定" if row.get("machine_selected") else "兜底机型"
            print(f"      工序 {index} {str(row.get('nm') or '')[:16]:<18} 设备 "
                  f"{row.get('machine_brand', '')} {row.get('machine_model', '')}（{selected}）")
        if missing:
            print(f"[警告] 快照缺少：{', '.join(missing)}")

        # 4) 真实生成
        templates = api(client, "GET", f"{base}/api/templates", params={"app_id": source}).json()["templates"]
        if not templates:
            print(f"[失败] 数据源 {source} 还没有可绑定模板，请先上传 .pptx")
            return 2
        template = args.template or templates[0]["template_id"]
        inspect = api(
            client, "POST", f"{base}/api/template/inspect",
            params={"app_id": source}, json={"template": template},
        ).json()
        slides = inspect["slides"]

        def find(slide_no, kind, name_contains=None):
            slide = next((s for s in slides if s["slide_index"] == slide_no), None)
            for shape in (slide or {}).get("shapes", []):
                if shape.get("kind") != kind:
                    continue
                if name_contains and name_contains not in (shape.get("text") or ""):
                    continue
                return shape
            return None

        # 封面字段（客户/零件号）、产品图片、工序整表、问题清单文字
        text_slide = 3 if len(slides) >= 3 else 1
        title = find(text_slide, "text") or find(1, "text")
        picture = find(text_slide, "picture") or find(1, "picture")
        table_shape = find(4, "table") or next(
            (s for sl in slides for s in sl["shapes"] if s.get("kind") == "table"), None
        )
        issue_title = next(
            (s for sl in slides for s in sl["shapes"]
             if s.get("kind") == "text" and "issue" in (s.get("text") or "").lower()),
            None,
        )

        # 工序表所在页上找一个非标题文本框，用来验证"这道工序用的是哪台设备"能绑进页面
        machine_shape = None
        table_slide = next((sl for sl in slides if table_shape in sl["shapes"]), None)
        for shape in (table_slide or {}).get("shapes", []):
            if shape.get("kind") == "text" and not (shape.get("shape_name") or "").startswith("标题"):
                machine_shape = shape
                break

        field_paths = {meta.get("source_path"): meta["path"] for meta in catalog["fields"]}
        cust = field_paths.get("G.cust") or (catalog["fields"][0]["path"] if catalog["fields"] else "")
        part = field_paths.get("G.part") or cust
        pr_table = by_path.get("pr")
        is_table = by_path.get("is")
        product_image = next((meta["path"] for meta in catalog["images"].values()
                              if str(meta.get("source_path", "")).startswith("G.pI")), "")

        bindings_info = []
        # 这套模板里「表格 8」「标题 1」这类名字在每页都重复，所以绑定必须落在对象**真实所在的那一页**，
        # 否则引擎会在同名对象上误绑（同页对象再多用 shape_id 精确定位）。
        pages = {}

        def page(slide_no):
            return pages.setdefault(slide_no, {"source": slide_no, "bindings": {}})

        def add(slide_no, shape, spec, label):
            spec = dict(spec)
            options = {"shape_id": shape["shape_id"]}
            options.update(spec.pop("options", {}))
            spec.update(shape=shape["shape_name"], options=options)
            page(slide_no)["bindings"][shape["shape_name"]] = spec
            bindings_info.append(label)

        table_slide_no = (table_slide or {}).get("slide_index", 4)
        issue_slide_no = next(
            (sl["slide_index"] for sl in slides if issue_title in sl["shapes"]), 1
        )
        if title and cust:
            add(text_slide, title, {"type": "text", "source": cust}, f"文本 {title['shape_name']} <- {cust}")
        if picture and product_image:
            add(text_slide, picture, {"type": "image", "source": product_image},
                f"图片 {picture['shape_name']} <- {product_image}")
        if table_shape and pr_table:
            add(table_slide_no, table_shape,
                {"type": "table_rows", "source": f"t.{pr_table}",
                 "options": {"start_row": 1, "columns_map": {"0": "nm", "1": "mc"}}},
                f"整表 {table_shape['shape_name']}（第 {table_slide_no} 页）<- t.{pr_table}（工序）")
        if machine_shape and pr_table and data["t"].get(pr_table):
            add(table_slide_no, machine_shape,
                {"type": "text", "source": f"t.{pr_table}[0].machine_model",
                 "options": {"empty": "keep"}},
                f"文本 {machine_shape['shape_name']} <- t.{pr_table}[0].machine_model（这道工序的设备）")
        if issue_title and is_table:
            add(issue_slide_no, issue_title,
                {"type": "text", "source": f"t.{is_table}[0].ds", "options": {"empty": "keep"}},
                f"文本 {issue_title['shape_name']} <- t.{is_table}[0].ds（问题）")

        for line in bindings_info:
            print(f"      绑定：{line}")
        if not pages:
            print("[失败] 模板里找不到可绑定的对象，或快照里没有对应字段")
            return 2

        deck_slides = list(pages.values())
        response = api(
            client, "POST", f"{base}/api/template/generate",
            params={"app_id": source},
            json={"template": template, "output_mode": "deck", "missing": "keep",
                  "slides": deck_slides, "data": data},
        )
        content = response.content
        headers = response.headers
        print(f"[4/4] 生成成功：{len(content)} 字节，模板 {template}")
        print("      引擎头部：" + ", ".join(
            f"{key}={headers.get(key)}" for key in
            ("X-DFM-Engine", "X-DFM-Slide-Count", "X-DFM-Text-Replaced",
             "X-DFM-Images-Bound", "X-DFM-Bindings-Applied", "X-DFM-Unbound-Targets")
        ))

        target = Path(args.output) if args.output else Path(tempfile.gettempdir()) / "machining-binding-check.pptx"
        target.write_bytes(content)

        # 解包确认数据真的落进页面
        with zipfile.ZipFile(io.BytesIO(content)) as package:
            xml = "".join(
                package.read(name).decode("utf-8", "ignore")
                for name in package.namelist()
                if name.startswith("ppt/slides/slide") and name.endswith(".xml")
            )
        # 内容校验：按"任一个候选值出现在页面里"判定，避免同一段文字被拆成多个 run
        checks = []
        if cust and data["f"].get(cust.split(".")[-1]) is not None:
            checks.append(("客户字段", [str(data["f"][cust.split(".")[-1]])]))
        if pr_rows:
            checks.append(("工序名", [str(pr_rows[0].get("nm") or "")]))
            checks.append(("工序设备", [str(pr_rows[0].get("machine_model") or ""),
                                    str(pr_rows[0].get("machine_brand") or "")]))
        content_ok = True
        for label, candidates in checks:
            hit = next((value for value in candidates if value and value in xml), "")
            content_ok = content_ok and bool(hit)
            print(f"      内容校验 {'命中' if hit else '未命中'}：{label} {hit or (candidates[0] if candidates else '')}")
        print(f"      输出文件：{target}")

        if args.save_scheme:
            # 绑定方案复用：保存后按方案 + 项目数据一键生成（表单页「按方案生成」走同一条路）。
            api(client, "POST", f"{base}/api/schemes", params={"app_id": source}, json={
                "name": args.save_scheme, "template": template, "description": "check_machining_binding",
                "output_mode": "deck", "missing": "keep", "slides": deck_slides,
            })
            again = api(client, "POST", f"{base}/api/schemes/{args.save_scheme}/generate",
                        params={"app_id": source}, json={"data": data})
            print(f"      方案 {args.save_scheme} 复用生成：{len(again.content)} 字节，"
                  f"绑定 {again.headers.get('X-DFM-Bindings-Applied')} 处")

        return 0 if content_ok else 1


if __name__ == "__main__":
    sys.exit(main())
