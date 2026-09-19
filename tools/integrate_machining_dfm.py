"""Split the approved legacy machining DFM HTML into maintained frontend assets.

The source file remains untouched.  Re-run this script when a newer approved
single-file HTML is supplied; server persistence is provided by host.js and
app/machining_dfm.py.

⚠️ **这是"起点生成器"，不是线上页面的唯一来源。** 它写出的 ``index.html`` 停留在阶段 2a 之前：
模板里没有 ``issue_page.js`` / ``selection_page.js`` / ``history_page.js`` /
``trash_page.js`` / ``changes_page.js``，版本号也还是 ``?v=process-v1``（现在是 ``?v=trash-v1``）。
线上跑的是**手工维护**的 ``static/machining_dfm/index.html``。真要重跑这个脚本，
必须把上面这些脚本标签、版本号与 ``legacy_app.js`` 里的接线一起再补回去，
否则会把阶段 2a~4 的前端装配冲掉。重跑后请依次跑：
``tools/check_host_css.py``、``tools/check_served_page.py``、``tools/check_process_wiring.py``、
``node tools/smoke_machining_page.mjs``、``node tools/check_trash_page.mjs``。
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

try:  # run either as ``python tools/x.py`` or ``python -m tools.x``
    from split_machining_seed import split_seed
except ImportError:  # pragma: no cover - module-style invocation
    from tools.split_machining_seed import split_seed


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE = Path.home() / "Desktop" / "DFM机加模版.html"
STATIC = ROOT / "static" / "machining_dfm"
SEED_DIR = ROOT / "app" / "resources" / "machining_dfm_seed"


def between(source: str, opening: str, closing: str, start: int = 0) -> tuple[str, int, int]:
    left = source.index(opening, start) + len(opening)
    right = source.index(closing, left)
    return source[left:right], left, right


def rewrite_server_ui(text: str) -> str:
    old_help = "数据自动保存在本机浏览器。多人共享流程：点「导出共享文件」生成含全部数据的 HTML，放入资料库/微盘，他人下载打开即可看到数据；改完后再点「导出数据(.json)」同步最新备份，他人「导入数据(.json)」即可恢复。"
    new_help = "数据自动保存在 FastAPI 服务端。顶部可切换项目、立即保存、查看历史版本或恢复已删除项目；「导出数据(.json)」可生成离线备份。"
    text = text.replace(old_help, new_help)
    text = text.replace(
        '<button class="btn btn-s" onclick="exportHTML()" style="background:#805ad5;color:#fff">导出共享文件(含图片)</button>',
        "",
    )
    text = text.replace(
        "「导出DFM报告(PPT)」按DFM模版生成PPTX（封面/设备选型/工件信息/工序刀具表/检具/Open issue）；「导出共享文件」生成单文件HTML，含全部数据与图片，发给别人双击即可打开。",
        "「导出DFM报告(PPT)」按DFM模版生成PPTX（封面/设备选型/工件信息/工序刀具表/检具/Open issue）；项目完整数据由服务端保存，也可导出 JSON 离线备份。",
    )
    text = text.replace(
        "提示：「保存」会把全部数据写入本文件（首次会询问保存位置）；发给他人时请发送该文件。",
        "提示：「保存」会把全部数据写入服务端当前项目，并保留历史版本。",
    )
    return text


def main() -> None:
    source_file = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else DEFAULT_SOURCE
    source = source_file.read_text(encoding="utf-8-sig")
    css, _, style_end = between(source, "<style>", "</style>")
    body_start = source.index("<body>") + len("<body>")
    app_tag = source.index("<script>", body_start)
    body = rewrite_server_ui(source[body_start:app_tag])
    tabs_opening = '<div class="tabs" id="tabBar">'
    tabs_start = body.index(tabs_opening) + len(tabs_opening)
    tabs_end = body.index("</div>", tabs_start)
    body = body[:tabs_start] + body[tabs_end:]
    main_tag = body.index('<div class="main" id="mainPanels">')
    modal_tag = body.index('<div class="modal-overlay"', main_tag)
    body = body[:main_tag] + '<div class="main" id="mainPanels"></div>\n' + body[modal_tag:]

    marker = source.index("\n<!-- DATA_MARKER -->\n", app_tag) + 1
    app_end = source.rfind("</script>", app_tag, marker)
    legacy = source[app_tag + len("<script>"):app_end]

    def legacy_array(name: str) -> tuple[list[str], str]:
        opening = f"var {name}="
        start = legacy.index(opening) + len(opening)
        end = legacy.index(";", start)
        literal = legacy[start:end]
        value = ast.literal_eval(literal)
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise RuntimeError(f"无法提取原文件的 {name} 类别")
        return value, literal

    inspection_categories, inspection_literal = legacy_array("ICN")
    fixture_categories, fixture_literal = legacy_array("FCN")

    globals_start = legacy.index("var MDB=")
    g_start = legacy.index(",G=", globals_start) + 3
    g_end = legacy.index(";\nfunction dc", g_start)
    original_globals = legacy[g_start:g_end]
    neutral_globals = (
        '{cust:"",part:"",hpd:0,sft:0,dpm:0,avl:0,pI:null,pf:null,len:0,wid:0,hgt:0,wgt:0,'
        'showFlow:1,bInspType:"",bInspImg:null,fInspType:"",fInspImg:null,bInspPrice:0,'
        'fInspPrice:0,msInspPrice:0,custVer:"",dfmDate:"",prj:"hp",insp:[],fixQ:[],'
        'fixQC:[],inspQ:[],icnX:[],fcnX:[],lang:"zh"}'
    )
    replacement_count = legacy.count("G=" + original_globals)
    legacy = legacy.replace("G=" + original_globals, "G=" + neutral_globals)
    if replacement_count != 2:
        raise RuntimeError(f"原文件业务默认值应出现 2 次，实际 {replacement_count} 次")
    legacy = legacy.replace("var ICN=" + inspection_literal + ";", "var ICN=[];")
    legacy = legacy.replace("var FCN=" + fixture_literal + ";", "var FCN=[];")

    ppt_tag = source.index("<script>", marker)
    embedded_tag = source.rindex("<script>var _EMB=")
    ppt_end = source.rfind("</script>", ppt_tag, embedded_tag)
    pptx = source[ppt_tag + len("<script>"):ppt_end]

    embedded_end = source.index("</script>", embedded_tag)
    embedded_script = source[embedded_tag + len("<script>"):embedded_end].strip()
    prefix, suffix = "var _EMB=", ";embMerge();"
    if not embedded_script.startswith(prefix) or not embedded_script.endswith(suffix):
        raise RuntimeError("无法定位原文件的 _EMB 数据")
    seed_literal = embedded_script[len(prefix):-len(suffix)]
    try:
        seed = json.loads(seed_literal)
    except json.JSONDecodeError:
        # Some historical library rows use JavaScript object keys without
        # quotes.  Evaluate only the isolated object literal, never the HTML.
        node = subprocess.run(
            [
                "node",
                "-e",
                "const fs=require('fs'),vm=require('vm');"
                "const src=fs.readFileSync(0,'utf8');"
                "const value=vm.runInNewContext('('+src+')',Object.create(null),{timeout:1000});"
                "process.stdout.write(JSON.stringify(value));",
            ],
            input=seed_literal.encode("utf-8"),
            capture_output=True,
            check=True,
        )
        seed = json.loads(node.stdout.decode("utf-8"))
    # Older portable exports omitted empty collections.  The integrated API
    # stores an explicit, stable state shape so later migrations stay simple.
    for key in ("mdb", "tdb", "pr", "is", "fdb", "idb", "vh"):
        seed.setdefault(key, [])
    seed_globals = seed.setdefault("G", {})
    seed_globals["icnX"] = list(dict.fromkeys(inspection_categories + seed_globals.get("icnX", [])))
    seed_globals["fcnX"] = list(dict.fromkeys(fixture_categories + seed_globals.get("fcnX", [])))

    init_start = legacy.index("(function(){\n  try{var raw=localStorage.getItem('cncCalcV7')")
    init_end = legacy.index("\nfunction save()", init_start)
    legacy = legacy[:init_start] + "init();\n" + legacy[init_end + 1:]

    save_start = legacy.index("function save(){")
    save_end = legacy.index("\nvar _fh=null;", save_start)
    legacy = (
        legacy[:save_start]
        + "function save(){if(window.MachiningDFMHost)window.MachiningDFMHost.scheduleSave();}"
        + legacy[save_end:]
    )
    legacy = legacy.replace(
        "function resetData(){if(!confirm('Reset all data?'))return;localStorage.removeItem('cncCalcV7');init();curTab=0;render();}",
        "function resetData(){if(!confirm('Reset all data?'))return;init();curTab=0;render();}",
    )
    legacy = legacy.replace(
        "var raw=localStorage.getItem('cncCalcV7');if(!raw)return;",
        "var raw=null;if(!raw)return;",
    )
    legacy = legacy.replace(
        'var PWD="TP123456",PWD2="TP23456",dbUnl=false,adUnl=false;\n'
        'function checkPwd(){if(dbUnl)return true;var p=prompt(TR("请输入工艺设置密码"));if(p===PWD){dbUnl=true;return true;}if(p!==null)alert(TR("密码错误"));return false;}\n'
        'function checkAdm(){if(adUnl)return true;var p=prompt(TR("请输入管理员密码"));if(p===PWD2){adUnl=true;return true;}if(p!==null)alert(TR("密码错误"));return false;}',
        'var dbUnl=false,adUnl=false;\n'
        "function checkPwd(){return window.MachiningDFMHost?window.MachiningDFMHost.requireRole('process'):false;}\n"
        "function checkAdm(){return window.MachiningDFMHost?window.MachiningDFMHost.requireRole('admin'):false;}",
    )
    legacy = legacy.replace(
        "function lockAdmin(){dbUnl=false;adUnl=false;curTab=0;render();}",
        "function lockAdmin(){if(window.MachiningDFMHost)window.MachiningDFMHost.logout();"
        "else{dbUnl=false;adUnl=false;curTab=0;render();}}",
    )
    legacy = legacy.replace(
        'IS.push({tp:"尺寸",pr:"机加工序-OP10",ds:"",fx:"",cr:"",st:"进行中",bI:null,aI:null})',
        'IS.push({tp:"尺寸",pr:"",ds:"",fx:"",cr:"",st:"进行中",bI:null,aI:null})',
    )
    defaults_start = legacy.index("var D=")
    defaults_end = legacy.index(";\n\nvar MDB=", defaults_start) + 1
    legacy = (
        legacy[:defaults_start]
        + "var D={mdb:[],tdb:[],pr:[],is:[],fdb:[],idb:[],vh:[]};"
        + legacy[defaults_end:]
    )
    legacy = rewrite_server_ui(legacy)
    tail = "render();setTimeout(shrinkImgs,1200);"
    if tail not in legacy:
        raise RuntimeError("无法定位原文件的初始 render 调用")
    legacy = legacy.replace(tail, "", 1)

    STATIC.mkdir(parents=True, exist_ok=True)
    SEED_DIR.mkdir(parents=True, exist_ok=True)
    (STATIC / "app.css").write_text(css.strip() + "\n", encoding="utf-8")
    (STATIC / "legacy_app.js").write_text(legacy.strip() + "\n", encoding="utf-8")
    (STATIC / "pptxgen.bundle.js").write_text(pptx.strip() + "\n", encoding="utf-8")
    counts = split_seed(seed, SEED_DIR)

    index = f"""<!doctype html>
<html lang="zh-CN"><head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<title>机加 DFM · 项目工作台</title>
<link rel="stylesheet" href="/static/machining_dfm/app.css?v=process-v1">
<link rel="stylesheet" href="/static/machining_dfm/host.css?v=process-v1">
</head>
<body class="server-loading">
{body.strip()}
<script src="/static/machining_dfm/host.js?v=process-v1"></script>
<script src="/static/machining_dfm/machines.js?v=process-v1"></script>
<script src="/static/machining_dfm/tools.js?v=process-v1"></script>
<script src="/static/machining_dfm/library_pages.js?v=process-v1"></script>
<script src="/static/machining_dfm/fixtures.js?v=process-v1"></script>
<script src="/static/machining_dfm/gauges.js?v=process-v1"></script>
<script src="/static/machining_dfm/project_info.js?v=process-v1"></script>
<script src="/static/machining_dfm/process_page.js?v=process-v1"></script>
<script src="/static/machining_dfm/legacy_app.js?v=process-v1"></script>
<script src="/static/machining_dfm/pptxgen.bundle.js?v=process-v1"></script>
<script>MachiningDFMHost.start();</script>
</body></html>
"""
    (STATIC / "index.html").write_text(index, encoding="utf-8")
    print(f"integrated {source_file.name}: css={len(css)}, app={len(legacy)}, pptx={len(pptx)}, seed={counts}")


if __name__ == "__main__":
    main()
