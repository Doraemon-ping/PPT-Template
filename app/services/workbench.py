import json
import os
import re
import uuid
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from ..settings import BASE_DIR, APP_ROOT, DATA_DIR, STATIC_DIR
import threading
from collections import OrderedDict
from .workbench_core import hub, scope, storage_root, safe_filename, install_api
from ..report.ppt.template_registry import TemplateRegistry
from ..report.ppt.scheme_service import SchemeService
app = FastAPI(title='通用 PPT 模板工作台', version='2.0')
from .observability import install as install_logging
_LIVE_PREVIEW_CACHE = OrderedDict()
_LIVE_PREVIEW_CACHE_LOCK = threading.Lock()
_LIVE_PREVIEW_CACHE_MAX = 24
_LIVE_PREVIEW_CACHE_TTL = 90.0
import hashlib
def _registry():
    return TemplateRegistry(BASE_DIR, include_builtins=scope.get() == 'dfm', storage_root=storage_root(scope.get()) / 'templates')
def _schemes():
    return SchemeService(APP_ROOT, storage_root=storage_root(scope.get()) / 'schemes')
def _live_preview_cache_key(template_path: Path, slide_payload: dict, data: dict, page: int) -> str:
    """Return a stable key for one rendered preview request."""
    try:
        stat = Path(template_path).stat()
        template_fingerprint = {
            "path": str(Path(template_path).resolve()),
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
        }
    except OSError:
        template_fingerprint = {"path": str(template_path)}
    payload = {
        "template": template_fingerprint,
        "slide": slide_payload,
        "data": data,
        "page": page,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _live_preview_cache_get(key: str):
    now = time.monotonic()
    with _LIVE_PREVIEW_CACHE_LOCK:
        item = _LIVE_PREVIEW_CACHE.pop(key, None)
        if item is None:
            return None
        created, content, meta = item
        if now - created > _LIVE_PREVIEW_CACHE_TTL:
            return None
        _LIVE_PREVIEW_CACHE[key] = (created, content, meta)
        return content, meta


def _live_preview_cache_put(key: str, content: bytes, meta: dict):
    with _LIVE_PREVIEW_CACHE_LOCK:
        _LIVE_PREVIEW_CACHE.pop(key, None)
        _LIVE_PREVIEW_CACHE[key] = (time.monotonic(), content, dict(meta))
        while len(_LIVE_PREVIEW_CACHE) > _LIVE_PREVIEW_CACHE_MAX:
            _LIVE_PREVIEW_CACHE.popitem(last=False)


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
    from ..report.ppt.template_engine import build_data_context
    from ..report.ppt.openxml.text_binding import PathResolver
    from ..report.ppt.openxml.visual_binding import render_data_template, render_formula_png
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


def _template_map(base_template: str, slides) -> dict:
    """Resolve every template referenced by deck slides (multi-template decks)."""
    from ..report.ppt.template_registry import TemplateRegistryError

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


def _native_unresolved_placeholders(buffer: bytes, data: Dict[str, Any]) -> list[str]:
    """Return target placeholders still present after a native-form render.

    Native HTML applications expose their own source paths.  The imported PPT
    template defines the target slots, so a native report must not silently
    download a deck containing ``{f.someOtherName}`` just because no source
    field was selected for that slot.  We inspect the final OOXML package,
    after explicit shape bindings have run, which avoids false positives for a
    placeholder that an explicit binding replaced.
    """
    from ..report.ppt.openxml.placeholder_scanner import PlaceholderScanner
    try:
        scan = PlaceholderScanner().scan(buffer)
    except Exception:
        return []
    return list(scan.placeholder_paths)


def _deck_uses_legacy_native_names(slides) -> bool:
    """Detect an old scheme that explicitly names non-source native paths.

    Native source paths end in the collision-safe ten-hex digest generated by
    ``native_forms.key``.  Any scoped path without that suffix is a historical
    or manually-authored compatibility path.  This avoids maintaining a list
    of business names and keeps the rule valid for future adapters.
    """
    for slide in slides or []:
        bindings = slide.bindings if hasattr(slide, 'bindings') else (slide or {}).get('bindings', {})
        for spec in (bindings or {}).values():
            source = spec.source if hasattr(spec, 'source') else (spec or {}).get('source', '')
            options = spec.options if hasattr(spec, 'options') else (spec or {}).get('options', {})
            values = [source]
            if isinstance(options, dict):
                values += [r.get('source', '') for r in options.get('replacements', []) if isinstance(r, dict)]
                values += re.findall(r'\{([A-Za-z_][A-Za-z0-9_.\[\]-]*)\}', str(options.get('template', '')))
            for path in values:
                if not isinstance(path, str):
                    continue
                match = re.match(r'^(f|t|i)\.([^\[]+)(?:\[(\d+)\])?$', path)
                if match and not re.search(r'_[0-9a-f]{10}$', match.group(2), re.IGNORECASE):
                    return True
    return False


def _native_unbound_targets(result, data, *, allow_legacy=False) -> list[str]:
    """Report unresolved native-form template targets without blocking output.

    A partially bound imported template is still useful: with ``missing=keep``
    the untouched target remains exactly as it appeared in the source PPT.  The
    response header exposes the count for clients that want to show a warning.
    """
    if allow_legacy:
        return []
    return _native_unresolved_placeholders(result.buffer, data)


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

    from ..report.ppt.openxml import OoxmlPackage

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

    from ..report.ppt.template_registry import TemplateRegistryError

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
    from ..report.ppt.template_registry import TemplateRegistryError

    try:
        removed = _registry().delete(template_id)
    except TemplateRegistryError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return {"ok": removed, "template_id": template_id}


@app.get("/api/templates/{template_id}/slides/{slide_index}/preview.png")
def api_template_slide_preview(template_id: str, slide_index: int):
    """Exact visual preview rendered by desktop PowerPoint, cached as PNG."""
    from ..report.ppt.slide_preview import SlidePreviewError, render_slide_preview
    from ..report.ppt.template_registry import TemplateRegistryError

    try:
        record = _registry().resolve(template_id)
        target = render_slide_preview(record.path, slide_index, storage_root(scope.get()) / "previews")
    except TemplateRegistryError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except SlidePreviewError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    return FileResponse(target, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})


@app.post("/api/template/live-preview")
def api_template_live_preview(req: TemplateLivePreviewRequest):
    """Render the selected template slide after applying current bindings/data."""
    import tempfile

    from ..report.ppt.deck import DeckDefinition, DeckSlide
    from ..report.ppt.slide_preview import SlidePreviewError, render_slide_preview
    from ..report.ppt.template_engine import TemplateEngine, build_data_context
    from ..report.ppt.openxml.text_binding import PathResolver
    from ..report.ppt.template_registry import TemplateRegistryError

    try:
        record = _registry().resolve(req.template)
        slide_payload = req.slide.model_dump()
        slide_payload["template"] = None
        # Editing always shows this page, even when its report condition is false.
        slide_payload["condition"] = None
        preview_cache_key = _live_preview_cache_key(record.path, slide_payload, req.data, req.page)
        cached = _live_preview_cache_get(preview_cache_key)
        if cached is not None:
            content, meta = cached
            return Response(content=content, media_type="image/png", headers={
                "Cache-Control": "no-store", "X-DFM-Preview-Cache": "hit",
                "X-DFM-Preview-Skipped": str(meta["skipped"]),
                "X-DFM-Preview-Pages": str(meta["pages"]),
                "X-DFM-Preview-Page": str(meta["page"]),
            })
        binding_sources = []
        for spec in slide_payload.get('bindings', {}).values():
            if spec.get('source'):
                binding_sources.append(spec['source'])
            options = spec.get('options') or {}
            binding_sources.extend(
                item.get('source', '') for item in options.get('replacements', [])
                if isinstance(item, dict) and item.get('source')
            )
            binding_sources.extend(re.findall(r'\{([A-Za-z_][A-Za-z0-9_.\[\]-]*)\}', str(options.get('template', ''))))
        context = build_data_context(req.data, binding_sources=binding_sources)
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
        with tempfile.TemporaryDirectory(prefix="live-preview-", dir=storage_root(scope.get())) as temp_dir:
            temp_root = Path(temp_dir)
            pptx_path = temp_root / "preview.pptx"
            pptx_path.write_bytes(generated.buffer)
            png_path = render_slide_preview(
                pptx_path, req.slide.source, temp_root / "rendered"
            )
            content = png_path.read_bytes()
        preview_meta = {
            "skipped": len(missing_bindings) + missing_segments,
            "pages": generated.stats['preview_page_count'],
            "page": generated.stats['preview_page'],
        }
        _live_preview_cache_put(preview_cache_key, content, preview_meta)
    except TemplateRegistryError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except SlidePreviewError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"实时预览生成失败：{e}") from e
    return Response(content=content, media_type="image/png", headers={
        "Cache-Control": "no-store", "X-DFM-Preview-Cache": "miss",
        "X-DFM-Preview-Skipped": str(preview_meta["skipped"]),
        "X-DFM-Preview-Pages": str(preview_meta["pages"]),
        "X-DFM-Preview-Page": str(preview_meta["page"]),
    })


@app.post("/api/template/scan")
def api_template_scan(req: TemplateScanRequest):
    """Return the ``{path}`` placeholder inventory of a registered template."""
    from ..report.ppt.openxml import PlaceholderScanner
    from ..report.ppt.template_registry import TemplateRegistryError

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
    from ..report.ppt.openxml.shape_inventory import ShapeInventoryScanner
    from ..report.ppt.template_registry import TemplateRegistryError

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
    from ..report.ppt.deck import DeckDefinition, DeckSlide
    from ..report.ppt.template_engine import GENERATOR_VERSION, TemplateEngine

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
        unbound_targets = _native_unbound_targets(
            result, req.data,
            allow_legacy=_deck_uses_legacy_native_names(req.slides),
        )
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
            "X-DFM-Unbound-Targets": str(len(unbound_targets)),
        },
    )


@app.get("/template-editor")
def template_editor_page():
    """Web workbench: upload template, bind fields, generate report."""
    return FileResponse(STATIC_DIR / "template_editor.html")


@app.get("/api/schemes")
def api_schemes_list():
    from ..report.ppt.scheme_service import SchemeError

    try:
        return {"schemes": _schemes().list()}
    except SchemeError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/api/schemes")
def api_schemes_save(req: SchemeSaveRequest):
    """Create or update a binding scheme (template id + deck bindings)."""
    from ..report.ppt.scheme_service import SchemeError

    # 校验模板与绑定结构（沿用 Deck 模型），并在保存时预检模板存在
    try:
        _registry().resolve(req.template)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=404, detail=str(e)) from e
    try:
        from ..report.ppt.deck import DeckDefinition, DeckSlide

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
    from ..report.ppt.scheme_service import SchemeError

    try:
        return _schemes().get(name)
    except SchemeError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@app.get('/api/schemes/{name}/versions')
def api_scheme_versions(name: str):
    from ..report.ppt.scheme_service import SchemeError
    try:
        return {'versions': _schemes().versions(name)}
    except SchemeError as e:
        raise HTTPException(404, str(e)) from e


@app.delete("/api/schemes/{name}")
def api_schemes_delete(name: str):
    from ..report.ppt.scheme_service import SchemeError

    try:
        _schemes().delete(name)
    except SchemeError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return {"ok": True, "name": name}


@app.post("/api/schemes/{name}/generate")
def api_schemes_generate(name: str, req: SchemeGenerateRequest):
    """One-click generate: saved scheme (template + bindings) + form data."""
    from ..report.ppt.deck import DeckDefinition, DeckSlide
    from ..report.ppt.scheme_service import SchemeError
    from ..report.ppt.template_engine import GENERATOR_VERSION, TemplateEngine

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
        unbound_targets = _native_unbound_targets(
            result, req.data,
            allow_legacy=_deck_uses_legacy_native_names(deck.slides),
        )
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
            "X-DFM-Unbound-Targets": str(len(unbound_targets)),
        },
    )

PPT_V2_TEMPLATE_PATH = BASE_DIR / 'templates' / 'DFM_Master_v1.pptx'
PPT_V2_SCHEMA_DIR = BASE_DIR / 'app' / 'report' / 'ppt' / 'schemas'
PPT_V2_TEMPLATE_VERSION = '1'


class PptRequest(BaseModel):
    f: dict = {}
    t: dict = {}
    i: dict = {}


def _ppt_v2_enabled():
    return os.getenv("DFM_PPT_V2_ENABLED", "").strip().casefold() in {"1", "true", "yes", "on"}


@app.post("/api/ppt/preview-v2")
def api_ppt_preview_v2(req: PptRequest):
    """旧版命名形状引擎预览。

    三服务拆分后由压铸表单服务迁入工作台：压铸表单只保留传统 47 页 /api/ppt，
    命名形状引擎（PPTEngine）随渲染能力留在工作台。
    """
    if not _ppt_v2_enabled():
        raise HTTPException(status_code=503, detail="PPT V2 预览功能未启用")
    try:
        from ..dfm import adapt_legacy_report
        from ..report.ppt import PPTEngine

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


install_api(app)
LOG_FILE = install_logging(app, 'ppt_workbench')

# ============================================================================
#  数据源接入 API（v1）：表单服务 → 工作台
#  1) GET  /api/ppt/contract                        契约发现（数据源清单 + 生成入口）
#  2) GET  /api/ppt/sources/{id}/projects/{pid}/catalog   字段目录（绑定用，不含数据）
#  3) POST /api/ppt/generate                        按「数据源 + 项目」出报告（调用方不传数据）
#  工作台通过 /api/ppt-provider/v1 契约向表单服务拉取快照与目录；表单服务侧另有
#  /api/report/generate 同源转发入口，便于表单页面一键出报告。
# ============================================================================

class SourceGenerateRequest(BaseModel):
    source_id: str
    project_id: str
    scheme: Optional[str] = None
    template: Optional[str] = None
    slides: List[TemplateSlideSpec] = []
    output_mode: str = "deck"
    missing: str = "keep"


@app.get('/api/ppt/contract')
async def api_ppt_contract():
    """数据源契约发现：列出可用数据源与生成/目录/快照入口，供表单服务与第三方接入。"""
    listing = await hub.sources()
    return {
        'contract_version': '1.0',
        'generate': {
            'method': 'POST',
            'path': '/api/ppt/generate',
            'body': ['source_id', 'project_id', 'scheme 或 template+slides',
                     'output_mode(deck|in_place)', 'missing(keep|clear|error)'],
            'response': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
        },
        'catalog': {'method': 'GET', 'path': '/api/ppt/sources/{source_id}/projects/{project_id}/catalog'},
        'snapshot': {'method': 'GET', 'path': '/api/ppt/sources/{source_id}/projects/{project_id}/snapshot'},
        'sources': listing.get('sources', []),
        'errors': listing.get('errors', []),
    }


@app.get('/api/ppt/sources/{source_id}/projects/{project_id}/catalog')
async def api_ppt_project_catalog(source_id: str, project_id: str):
    """字段目录（绑定用）：只返回字段/明细表/图片槽位与结论标签，不含项目数据。"""
    token = scope.set(source_id)
    try:
        payload = await hub.snapshot(source_id, project_id)
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f'读取数据源失败：{e}') from e
    finally:
        scope.reset(token)
    return {
        'contract_version': payload.get('contract_version'),
        'source_id': source_id,
        'project_id': project_id,
        'name': payload.get('name'),
        'revision': payload.get('revision'),
        'catalog': payload.get('catalog') or {},
    }


@app.post('/api/ppt/generate')
async def api_ppt_generate_from_source(req: SourceGenerateRequest):
    """按「数据源 + 项目」生成 PPT：工作台自行按契约拉取快照，调用方无需传业务数据。"""
    from ..report.ppt.deck import DeckDefinition, DeckSlide
    from ..report.ppt.scheme_service import SchemeError
    from ..report.ppt.template_engine import GENERATOR_VERSION, TemplateEngine

    if req.output_mode not in {'deck', 'in_place'}:
        raise HTTPException(status_code=422, detail='output_mode 必须是 deck 或 in_place')
    if req.missing not in {'keep', 'clear', 'error'}:
        raise HTTPException(status_code=422, detail='missing 必须是 keep / clear / error')
    if not req.scheme and not req.template:
        raise HTTPException(status_code=422, detail='需要提供 scheme，或 template + slides')

    token = scope.set(req.source_id)
    try:
        payload = await hub.snapshot(req.source_id, req.project_id)
        data = payload.get('data') or {}
        if req.scheme:
            record = _schemes().get(req.scheme)
            deck_data = record.get('deck') or {}
            template_id = record['template']
            slides = deck_data.get('slides', [])
            deck = DeckDefinition(template=template_id,
                                  output_mode=deck_data.get('output_mode', 'deck'),
                                  missing=deck_data.get('missing', 'keep'),
                                  slides=[DeckSlide(**slide) for slide in slides])
        else:
            template_id = req.template
            slides = [spec.model_dump() for spec in req.slides]
            deck = DeckDefinition(template=template_id, output_mode=req.output_mode,
                                  missing=req.missing,
                                  slides=[DeckSlide(**spec) for spec in slides])
        template_map = _template_map(template_id, slides)
        template_path = _registry().resolve(template_id).path
        result = TemplateEngine(template_path).generate(deck, data, template_map=template_map)
    except SchemeError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f'按数据源生成失败：{e}') from e
    finally:
        scope.reset(token)

    stats = result.stats
    base_name = safe_filename(data.get('f') or {})
    content_disposition = (
        'attachment; filename="DFM_SOURCE.pptx"; filename*=UTF-8\'\''
        + quote(base_name.replace('DFM_', 'DFM_' + req.source_id + '_', 1))
    )
    return Response(
        content=result.buffer,
        media_type='application/vnd.openxmlformats-officedocument.presentationml.presentation',
        headers={
            'Content-Disposition': content_disposition,
            'X-DFM-Engine': 'openxml-source-v1',
            'X-DFM-Generator-Version': GENERATOR_VERSION,
            'X-DFM-Data-Source': req.source_id,
            'X-DFM-Project': req.project_id,
            'X-DFM-Project-Revision': str(payload.get('revision', '')),
            'X-DFM-Template': template_id,
            'X-DFM-Scheme': quote(req.scheme or '', safe=''),
            'X-DFM-Slide-Count': str(result.slide_count),
            'X-DFM-Text-Replaced': str(stats.get('text_replaced', 0)),
            'X-DFM-Images-Bound': str(stats.get('images_bound', 0)),
            'X-DFM-Bindings-Applied': str(stats.get('bindings_applied', 0)),
        },
    )


@app.get('/ppt')
def workbench_home():
    return FileResponse(STATIC_DIR / 'ppt_home.html')

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
