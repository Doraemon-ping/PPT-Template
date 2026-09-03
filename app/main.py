# -*- coding: utf-8 -*-
"""HPDC DFM 报告自动生成工具 —— FastAPI 服务端。

路由：
  GET  /                              前端界面（static/index.html）
  GET  /template-editor               模板工作台（上传模板 → 绑定字段 → 生成）
  POST /api/calc                      工艺计算（派生值 + 机型填充 + 全部结果）
  POST /api/ppt                       生成 PPT（返回 .pptx 文件，旧版 47 页）
  POST /api/ppt/preview-v2            新模板引擎试运行（默认关闭）
  GET  /api/templates                 已注册模板清单（内置 + 用户上传）
  POST /api/templates/upload          导入 .pptx 模板文件
  DELETE /api/templates/{id}          删除用户上传模板
  POST /api/template/scan             OOXML 占位符扫描（{path} 清单）
  POST /api/template/inspect          形状清单（绑定选择用）
  POST /api/template/generate         Deck 编排生成（占位符 + 形状绑定替换）
  POST /api/template/live-preview     当前模板页绑定当前数据的真实 PNG 预览
  GET  /api/demo                      示例数据
  GET  /api/project/load              加载服务器保存的项目
  POST /api/project/save              保存项目到服务器
"""
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .calc import compute_all
from .demo import demo_state
from .ppt import build_pptx, safe_filename

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"
DATA_DIR = BASE_DIR / "data"
PROJECT_FILE = DATA_DIR / "project.json"
PPT_V2_TEMPLATE_PATH = BASE_DIR / "templates" / "DFM_Master_v1.pptx"
PPT_V2_SCHEMA_DIR = BASE_DIR / "app" / "report" / "ppt" / "schemas"
PPT_V2_TEMPLATE_VERSION = "1"

# 内置模板（registry 里 origin=builtin）；用户上传模板存于 data/templates/
BUILTIN_TEMPLATE_IDS = ("official", "exact", "pilot", "demo", "table-demo")

TEMPLATE_REGISTRY_SERVICE = None


def _registry() -> "TemplateRegistry":
    """Lazy singleton that also serves user-uploaded templates."""
    global TEMPLATE_REGISTRY_SERVICE
    if TEMPLATE_REGISTRY_SERVICE is None:
        from .report.ppt.template_registry import TemplateRegistry

        TEMPLATE_REGISTRY_SERVICE = TemplateRegistry(BASE_DIR)
    return TEMPLATE_REGISTRY_SERVICE


app = FastAPI(title="HPDC DFM 报告自动生成工具", version="1.0")


class CalcRequest(BaseModel):
    f: dict = {}
    t: dict = {}
    apply_machine: bool = False


class PptRequest(BaseModel):
    f: dict = {}
    t: dict = {}
    i: dict = {}


class SaveRequest(BaseModel):
    f: dict = {}
    t: dict = {}
    i: dict = {}


class TemplateScanRequest(BaseModel):
    template: str = "demo"


class TemplateSlideSpec(BaseModel):
    source: int
    template: Optional[str] = None
    repeat: Optional[str] = None
    condition: Optional[str] = None
    images: Dict[str, str] = {}
    bindings: Dict[str, Dict[str, Any]] = {}


class TemplateGenerateRequest(BaseModel):
    template: str = "demo"
    output_mode: str = "deck"
    missing: str = "keep"
    slides: List[TemplateSlideSpec]
    data: Dict[str, Any] = {}


class TemplateLivePreviewRequest(BaseModel):
    template: str
    slide: TemplateSlideSpec
    data: Dict[str, Any] = {}
    page: int = 1


class FormulaPreviewRequest(BaseModel):
    expression: str
    data: Dict[str, Any] = {}


@app.post('/api/template/formula-preview')
def api_formula_preview(req: FormulaPreviewRequest):
    """Render the same substituted formula used by the PPT generator, without COM."""
    import re
    from .report.ppt.template_engine import build_data_context
    from .report.ppt.openxml.text_binding import PathResolver
    from .report.ppt.openxml.visual_binding import render_data_template, render_formula_png
    expression = req.expression
    if not expression.strip() or len(expression) > 4000:
        raise HTTPException(status_code=422, detail='公式不能为空，且不能超过 4000 字符')
    without_fractions = re.sub(r'\[\[[^\[\]|]+\|[^\[\]|]+\]\]', '', expression)
    if '[[' in without_fractions or ']]' in without_fractions:
        raise HTTPException(status_code=422, detail='分式不完整或含有嵌套分式，请检查分子和分母')
    resolver = PathResolver((build_data_context(req.data),))
    missing = set()
    def check(match):
        path = match.group(1)
        value, found = resolver.resolve(path)
        if not found or value is None or value == '':
            missing.add(path)
            return '待填写'
        if isinstance(value, (dict, list)) or str(value).startswith('data:image/'):
            raise HTTPException(status_code=422, detail='公式参数必须是文字或数字，不能是图片或表格')
        return match.group(0)
    checked = re.sub(r'\{([A-Za-z_][A-Za-z0-9_.\[\]-]*)\}', check, expression)
    rendered = render_data_template(checked, resolver)
    png = render_formula_png(rendered, 9144000, 1371600, {'dpi': 120, 'font_size': 28})
    return Response(content=png, media_type='image/png', headers={
        'Cache-Control': 'no-store', 'X-DFM-Formula-Missing': str(len(missing)),
    })


class SchemeSaveRequest(BaseModel):
    name: str
    template: str
    description: str = ""
    output_mode: str = "deck"
    missing: str = "keep"
    slides: List[TemplateSlideSpec]


class SchemeGenerateRequest(BaseModel):
    data: Dict[str, Any] = {}


SCHEME_SERVICE = None


def _schemes() -> "SchemeService":
    """Lazy singleton for persisted binding schemes under ``data/schemes/``."""
    global SCHEME_SERVICE
    if SCHEME_SERVICE is None:
        from .report.ppt.scheme_service import SchemeService

        SCHEME_SERVICE = SchemeService(BASE_DIR)
    return SCHEME_SERVICE


def _template_map(base_template: str, slides) -> dict:
    """Resolve every template referenced by deck slides (multi-template decks)."""
    from .report.ppt.template_registry import TemplateRegistryError

    wanted = {base_template}
    for slide in slides:
        tid = (slide or {}).get("template")
        if tid:
            wanted.add(tid)
    mapping = {}
    for tid in wanted:
        try:
            mapping[tid] = _registry().resolve(tid).path
        except TemplateRegistryError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
    return mapping


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/api/calc")
def api_calc(req: CalcRequest):
    return compute_all(req.f, apply_machine=req.apply_machine)


@app.post("/api/ppt")
def api_ppt(req: PptRequest):
    try:
        buf = build_pptx(req.f, req.t, req.i)
        fname = safe_filename(req.f)
        cd = 'attachment; filename="DFM.pptx"; filename*=UTF-8\'\'' + quote(fname)
        return Response(
            content=buf.getvalue(),
            media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            headers={"Content-Disposition": cd},
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"PPT 生成失败：{e}") from e


def _ppt_v2_enabled():
    return os.getenv("DFM_PPT_V2_ENABLED", "").strip().casefold() in {"1", "true", "yes", "on"}


@app.post("/api/ppt/preview-v2")
def api_ppt_preview_v2(req: PptRequest):
    """Run the new named-shape engine without changing the legacy PPT route."""
    if not _ppt_v2_enabled():
        raise HTTPException(status_code=503, detail="PPT V2 预览功能未启用")
    try:
        # Lazy imports keep the legacy path independent from the incremental
        # engine until the feature flag is explicitly enabled.
        from .dfm import adapt_legacy_report
        from .report.ppt import PPTEngine

        report = adapt_legacy_report(req.f, req.t, req.i)
        template_path = Path(os.getenv("DFM_PPT_V2_TEMPLATE", str(PPT_V2_TEMPLATE_PATH)))
        schema_dir = Path(os.getenv("DFM_PPT_V2_SCHEMA_DIR", str(PPT_V2_SCHEMA_DIR)))
        result = PPTEngine(
            template_path,
            schema_dir,
            template_version=PPT_V2_TEMPLATE_VERSION,
        ).generate(report)
        filename = safe_filename(req.f).replace("DFM_", "DFM_PREVIEW_V2_", 1)
        content_disposition = (
            'attachment; filename="DFM_PREVIEW_V2.pptx"; filename*=UTF-8\'\''
            + quote(filename)
        )
        return Response(
            content=result.buffer.getvalue(),
            media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            headers={
                "Content-Disposition": content_disposition,
                "X-DFM-Engine": "preview-v2",
                "X-DFM-Template-Version": result.template_version,
                "X-DFM-Generator-Version": result.generator_version,
                "X-DFM-Slide-Count": str(len(result.plans)),
                "X-DFM-Validation-Warnings": str(len(result.validation.warnings)),
            },
        )
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"PPT V2 预览生成失败：{e}") from e


@app.get("/api/templates")
def api_templates():
    records = [record.to_dict() for record in _registry().list()]
    return {"templates": records}


@app.post("/api/templates/upload")
async def api_templates_upload(
    file: UploadFile,
    template_id: Optional[str] = None,
    version: str = "1",
):
    """Import a .pptx template file and register it for scan/bind/generate."""
    if file.content_type and file.content_type not in {
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/octet-stream",
    }:
        raise HTTPException(status_code=415, detail=f"不支持的文件类型：{file.content_type}")
    if not file.filename or not file.filename.lower().endswith((".pptx", ".ppt")):
        raise HTTPException(status_code=415, detail="仅支持 .pptx 模板文件")

    from .report.ppt.openxml import OoxmlPackage

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="上传文件为空")
    try:
        package = OoxmlPackage(data)
        if "ppt/presentation.xml" not in package.part_names() or not package.slide_parts():
            raise ValueError("not a valid pptx presentation")
        slide_count = len(package.slide_parts())
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"文件不是有效的 PPTX：{e}") from e

    derive_id = (Path(file.filename).stem or "template").strip().casefold()
    derive_id = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in derive_id)
    final_id = template_id or derive_id or "uploaded"

    from .report.ppt.template_registry import TemplateRegistryError

    try:
        record = _registry().register_upload(
            template_id=final_id,
            data=data,
            source_name=file.filename,
            version=version,
        )
    except TemplateRegistryError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e

    return {
        "ok": True,
        "template": record.to_dict(),
        "slide_count": slide_count,
        "hint": "使用 POST /api/template/scan 或 /api/template/inspect 查看占位符与形状，"
                "再用 /api/template/generate 生成。",
    }


@app.delete("/api/templates/{template_id}")
def api_templates_delete(template_id: str):
    """Delete a user-uploaded template (built-in templates are read-only)."""
    from .report.ppt.template_registry import TemplateRegistryError

    try:
        removed = _registry().delete(template_id)
    except TemplateRegistryError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return {"ok": removed, "template_id": template_id}


@app.get("/api/templates/{template_id}/slides/{slide_index}/preview.png")
def api_template_slide_preview(template_id: str, slide_index: int):
    """Exact visual preview rendered by desktop PowerPoint, cached as PNG."""
    from .report.ppt.slide_preview import SlidePreviewError, render_slide_preview
    from .report.ppt.template_registry import TemplateRegistryError

    try:
        record = _registry().resolve(template_id)
        target = render_slide_preview(record.path, slide_index, DATA_DIR / "template_previews")
    except TemplateRegistryError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except SlidePreviewError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    return FileResponse(target, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})


@app.post("/api/template/live-preview")
def api_template_live_preview(req: TemplateLivePreviewRequest):
    """Render the selected template slide after applying current bindings/data."""
    import tempfile

    from .report.ppt.deck import DeckDefinition, DeckSlide
    from .report.ppt.slide_preview import SlidePreviewError, render_slide_preview
    from .report.ppt.template_engine import TemplateEngine, build_data_context
    from .report.ppt.openxml.text_binding import PathResolver
    from .report.ppt.template_registry import TemplateRegistryError

    try:
        record = _registry().resolve(req.template)
        slide_payload = req.slide.model_dump()
        slide_payload["template"] = None
        # Editing always shows this page, even when its report condition is false.
        slide_payload["condition"] = None
        context = build_data_context(req.data)
        scopes = [context]
        if req.slide.repeat:
            items, found = PathResolver((context,)).resolve(req.slide.repeat)
            if found and isinstance(items, (list, tuple)) and items and isinstance(items[0], dict):
                scopes.insert(0, items[0])
        resolver = PathResolver(tuple(scopes))
        # In an editor, incomplete data is normal: keep only those objects unchanged.
        missing_bindings = [key for key, spec in slide_payload["bindings"].items()
                            if not resolver.resolve(spec.get("source", ""))[1]]
        missing_segments = 0
        for spec in slide_payload['bindings'].values():
            if spec.get('type') == 'text_replace':
                for segment in spec.get('options', {}).get('replacements', []):
                    value, found = resolver.resolve(segment.get('source', ''))
                    if not found or value is None or value == '':
                        missing_segments += 1
        for key in missing_bindings:
            del slide_payload["bindings"][key]
        slide = DeckSlide(**slide_payload)
        deck = DeckDefinition(
            template=req.template, output_mode="in_place", missing="keep", slides=[slide]
        )
        generated = TemplateEngine(record.path).generate(deck, req.data, preview_first_item=True, preview_page=req.page)
        with tempfile.TemporaryDirectory(prefix="dfm-live-preview-", dir=DATA_DIR) as temp_dir:
            temp_root = Path(temp_dir)
            pptx_path = temp_root / "preview.pptx"
            pptx_path.write_bytes(generated.buffer)
            png_path = render_slide_preview(
                pptx_path, req.slide.source, temp_root / "rendered"
            )
            content = png_path.read_bytes()
    except TemplateRegistryError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except SlidePreviewError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"实时预览生成失败：{e}") from e
    return Response(content=content, media_type="image/png", headers={
        "Cache-Control": "no-store", "X-DFM-Preview-Skipped": str(len(missing_bindings) + missing_segments),
        "X-DFM-Preview-Pages": str(generated.stats['preview_page_count']),
        "X-DFM-Preview-Page": str(generated.stats['preview_page']),
    })


@app.post("/api/template/scan")
def api_template_scan(req: TemplateScanRequest):
    """Return the ``{path}`` placeholder inventory of a registered template."""
    from .report.ppt.openxml import PlaceholderScanner
    from .report.ppt.template_registry import TemplateRegistryError

    try:
        record = _registry().resolve(req.template)
    except TemplateRegistryError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    try:
        scan = PlaceholderScanner().scan(record.path)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"模板扫描失败：{e}") from e
    return {
        "template": req.template,
        "origin": record.origin,
        "path": str(record.path),
        "engine": "openxml-scan-v1",
        **scan.to_dict(),
    }


@app.post("/api/template/inspect")
def api_template_inspect(req: TemplateScanRequest):
    """Shape inventory of a registered template (for binding selection)."""
    from .report.ppt.openxml.shape_inventory import ShapeInventoryScanner
    from .report.ppt.template_registry import TemplateRegistryError

    try:
        record = _registry().resolve(req.template)
    except TemplateRegistryError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    try:
        inventory = ShapeInventoryScanner().scan(record.path)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"模板检查失败：{e}") from e
    return {
        "template": req.template,
        "origin": record.origin,
        "path": str(record.path),
        "engine": "openxml-inspect-v1",
        **inventory.to_dict(),
    }


@app.post("/api/template/generate")
def api_template_generate(req: TemplateGenerateRequest):
    """Deck-driven template generation (placeholder fill + shape bindings)."""
    from .report.ppt.deck import DeckDefinition, DeckSlide
    from .report.ppt.template_engine import GENERATOR_VERSION, TemplateEngine

    if req.output_mode not in {"deck", "in_place"}:
        raise HTTPException(status_code=422, detail="output_mode 必须是 deck 或 in_place")
    if req.missing not in {"keep", "clear", "error"}:
        raise HTTPException(status_code=422, detail="missing 必须是 keep / clear / error")
    try:
        template_map = _template_map(req.template, [s.model_dump() for s in req.slides])
        path = _registry().resolve(req.template).path
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=404, detail=str(e)) from e
    try:
        deck = DeckDefinition(
            template=req.template,
            output_mode=req.output_mode,
            missing=req.missing,
            slides=[DeckSlide(**spec.model_dump()) for spec in req.slides],
        )
        result = TemplateEngine(path).generate(deck, req.data, template_map=template_map)
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"模板生成失败：{e}") from e

    data = req.data.get("f") or {}
    fname = safe_filename(data).replace("DFM_", "DFM_TEMPLATE_", 1)
    content_disposition = (
        'attachment; filename="DFM_TEMPLATE.pptx"; filename*=UTF-8\'\'' + quote(fname)
    )
    stats = result.stats
    return Response(
        content=result.buffer,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        headers={
            "Content-Disposition": content_disposition,
            "X-DFM-Engine": "openxml-template-v1",
            "X-DFM-Generator-Version": GENERATOR_VERSION,
            "X-DFM-Template": req.template,
            "X-DFM-Slide-Count": str(result.slide_count),
            "X-DFM-Text-Replaced": str(stats.get("text_replaced", 0)),
            "X-DFM-Images-Bound": str(stats.get("images_bound", 0)),
            "X-DFM-Images-Missing": str(len(stats.get("images_missing", []))),
            "X-DFM-Bindings-Applied": str(stats.get("bindings_applied", 0)),
            "X-DFM-Missing-Placeholders": str(len(stats.get("text_missing") or [])),
        },
    )


@app.get("/template-editor")
def template_editor_page():
    """Web workbench: upload template, bind fields, generate report."""
    return FileResponse(STATIC_DIR / "template_editor.html")


# =========================================================================
# 模板绑定方案（绑定一次 → 保存方案 → 填表后选方案直接生成 / 载入再编辑）
# =========================================================================
@app.get("/api/schemes")
def api_schemes_list():
    from .report.ppt.scheme_service import SchemeError

    try:
        return {"schemes": _schemes().list()}
    except SchemeError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/api/schemes")
def api_schemes_save(req: SchemeSaveRequest):
    """Create or update a binding scheme (template id + deck bindings)."""
    from .report.ppt.scheme_service import SchemeError

    # 校验模板与绑定结构（沿用 Deck 模型），并在保存时预检模板存在
    try:
        _registry().resolve(req.template)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=404, detail=str(e)) from e
    try:
        from .report.ppt.deck import DeckDefinition, DeckSlide

        DeckDefinition(
            template=req.template,
            output_mode=req.output_mode,
            missing=req.missing,
            slides=[DeckSlide(**spec.model_dump()) for spec in req.slides],
        )
        record = _schemes().save(
            name=req.name,
            template=req.template,
            description=req.description,
            output_mode=req.output_mode,
            missing=req.missing,
            slides=[spec.model_dump() for spec in req.slides],
        )
    except SchemeError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return {"ok": True, "scheme": record["name"]}


@app.get("/api/schemes/{name}")
def api_schemes_get(name: str):
    from .report.ppt.scheme_service import SchemeError

    try:
        return _schemes().get(name)
    except SchemeError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@app.delete("/api/schemes/{name}")
def api_schemes_delete(name: str):
    from .report.ppt.scheme_service import SchemeError

    try:
        _schemes().delete(name)
    except SchemeError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return {"ok": True, "name": name}


@app.post("/api/schemes/{name}/generate")
def api_schemes_generate(name: str, req: SchemeGenerateRequest):
    """One-click generate: saved scheme (template + bindings) + form data."""
    from .report.ppt.deck import DeckDefinition, DeckSlide
    from .report.ppt.scheme_service import SchemeError
    from .report.ppt.template_engine import GENERATOR_VERSION, TemplateEngine

    try:
        record = _schemes().get(name)
        deck_data = record.get("deck") or {}
        template_id = record["template"]
        template_map = _template_map(template_id, deck_data.get("slides", []))
        path = _registry().resolve(template_id).path
        deck = DeckDefinition(
            template=template_id,
            output_mode=deck_data.get("output_mode", "deck"),
            missing=deck_data.get("missing", "keep"),
            slides=[DeckSlide(**slide) for slide in deck_data.get("slides", [])],
        )
        result = TemplateEngine(path).generate(deck, req.data, template_map=template_map)
    except SchemeError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"按方案生成失败：{e}") from e

    data = req.data.get("f") or {}
    fname = safe_filename(data).replace("DFM_", "DFM_SCHEME_", 1)
    content_disposition = (
        'attachment; filename="DFM_SCHEME.pptx"; filename*=UTF-8\'\'' + quote(fname)
    )
    stats = result.stats
    return Response(
        content=result.buffer,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        headers={
            "Content-Disposition": content_disposition,
            "X-DFM-Engine": "openxml-scheme-v1",
            "X-DFM-Generator-Version": GENERATOR_VERSION,
            "X-DFM-Scheme": quote(name, safe=""),
            "X-DFM-Template": template_id,
            "X-DFM-Slide-Count": str(result.slide_count),
            "X-DFM-Text-Replaced": str(stats.get("text_replaced", 0)),
            "X-DFM-Images-Bound": str(stats.get("images_bound", 0)),
            "X-DFM-Images-Missing": str(len(stats.get("images_missing", []))),
            "X-DFM-Bindings-Applied": str(stats.get("bindings_applied", 0)),
        },
    )


@app.get("/api/demo")
def api_demo():
    return demo_state()


@app.get("/api/project/load")
def api_project_load():
    if PROJECT_FILE.exists():
        try:
            with open(PROJECT_FILE, "r", encoding="utf-8") as fp:
                return json.load(fp)
        except Exception:
            pass
    return {"f": {}, "t": {}, "i": {}}


@app.post("/api/project/save")
def api_project_save(req: SaveRequest):
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(PROJECT_FILE, "w", encoding="utf-8") as fp:
            json.dump({"f": req.f, "t": req.t, "i": req.i}, fp, ensure_ascii=False, indent=2)
        return {"ok": True, "path": str(PROJECT_FILE)}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"保存失败：{e}") from e


# 静态资源（图片等）
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def run():
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)


if __name__ == "__main__":
    run()
