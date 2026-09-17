"""Business projections belong to form providers, never the PPT engine."""
import re
from typing import Any, Dict, Mapping
from .calc import calc_force, compute_all
from .machines import cur_machine
def build_legacy_context(data: Mapping[str, Any], *, binding_sources=None) -> Dict[str, Any]:
    """Build scoped form data; only the built-in DFM application computes DFM values."""
    from app.form_platform import FORM_SCOPE
    if FORM_SCOPE.get() != 'dfm':
        context = {key: dict(data.get(key) or {}) for key in ('f', 't', 'i', 'derived', 'calc_results')}
        runtime = data.get('runtime')
        if isinstance(runtime, dict) and runtime.get('adapter') in {'dfm_quote_v1', 'json_export_v1'}:
            # Native HTML data is normalized using the source-specific catalog
            # paths.  PPT target placeholders are resolved only through the
            # explicit bindings saved by the template editor.
            from app.native_forms import normalize
            projected, _ = normalize(runtime, include_legacy_aliases=False)
            # Replace the persisted projection instead of merging it.  This
            # prevents an old project row containing ``f.custName`` aliases
            # from bypassing the template-driven binding contract.
            for key in ('f', 't', 'i'):
                context[key] = dict(projected[key])
            # A historical scheme may explicitly contain a legacy DFM source
            # such as ``f.custName``.  Resolve only those exact paths, and only
            # when the scheme asked for them.  This is a migration escape hatch
            # rather than a catalog-wide alias or an automatic mapping rule.
            requested = {str(path) for path in (binding_sources or []) if isinstance(path, str)}
            if requested and runtime.get('adapter') == 'dfm_quote_v1':
                legacy, _ = normalize(runtime, include_legacy_aliases=True)
                for path in requested:
                    match = re.match(r'^(f|t|i)\.([^\[]+)(?:\[(\d+)\])?$', path)
                    if not match:
                        continue
                    scope, name, index = match.groups()
                    if name not in legacy.get(scope, {}):
                        continue
                    value = legacy[scope][name]
                    if index is not None:
                        try:
                            value = value[int(index)]
                        except (IndexError, TypeError):
                            continue
                    context[scope][name] = value
        return context
    f = dict(data.get("f") or {})
    t = dict(data.get("t") or {})
    i = dict(data.get("i") or {})
    calculated = compute_all(f, apply_machine=False)
    verdicts = {key: value.get("verdict", "") for key, value in calculated["results"].items()}
    force = calc_force(f)
    machine = cur_machine(f)

    def display(value, digits=0):
        try:
            number = float(value)
        except (TypeError, ValueError):
            return "" if value is None else str(value)
        if digits == 0:
            return str(int(round(number)))
        return f"{number:.{digits}f}".rstrip("0").rstrip(".")

    safety = float(f.get("lockSafetyFactor") or 1.1)
    mold_structure = str(f.get("moldStructure") or f"{display(force['cav'])}出{display(force['cav'])}")
    product_info = "\n".join([
        f"零件号:{f.get('partNo', '')};",
        f"成品重量:{f.get('wFinish', '')}kg",
        f"毛坯重量:{f.get('wCast', '')}kg;",
        f"流道重量:{f.get('wRunner', '')}kg",
        f"渣包重量:{f.get('wOverflow', '')}kg",
        f"基本壁厚:{f.get('wall', '')}mm;",
        f"产品尺寸:{f.get('dimL', '')}X{f.get('dimW', '')}X{f.get('dimH', '')}mm;",
        f"高压压铸设备吨位：{display(machine.get('ton'))}T；模具结构{mold_structure}；",
        f"铸造压力:{f.get('castP', '')}MPa;高真空压铸",
        f"材料：{f.get('material', '')}",
    ])
    ppt_force = {
        "pressure": display(force["P"]),
        "area_part": display(force["aPart"]),
        "area_slider": display(force["aSl"]),
        "area_runner": display(force["aRunner"]),
        "area_overflow": display(force["aOver"]),
        "part": display(force["fPart"]),
        "slider": display(force["fSl"]),
        "runner": display(force["fRunner"]),
        "overflow": display(force["fOver"]),
        "total": display(force["fTot"]),
        "slider_angle": display(force["sliderAngle"]),
        "slider_term": (
            f" × tan {display(force['sliderAngle'])}°" if force["sliderAngle"] else ""
        ),
        "clamp_factor": display(safety, 2),
        "clamp_required": display(force["fTot"] * safety),
    }
    return {
        "f": f,
        "t": t,
        "i": i,
        "derived": calculated["derived"],
        "calc_results": verdicts,
        "ppt": {"product_info": product_info, "force": ppt_force},
    }


FORMULA_FIELDS = {'ppt.force.pressure': '铸造压力（公式显示）', 'ppt.force.area_part': '产品投影面积（公式显示）', 'ppt.force.area_slider': '滑块投影面积（公式显示）', 'ppt.force.area_runner': '流道投影面积（公式显示）', 'ppt.force.area_overflow': '渣包投影面积（公式显示）', 'ppt.force.part': '产品胀型力', 'ppt.force.slider': '滑块胀型力', 'ppt.force.runner': '流道胀型力', 'ppt.force.overflow': '渣包胀型力', 'ppt.force.total': '总胀型力', 'ppt.force.slider_angle': '滑块夹角（公式显示）', 'ppt.force.slider_term': '滑块角度修正项', 'ppt.force.clamp_factor': '锁模安全系数（公式显示）', 'ppt.force.clamp_required': '所需锁模力'}
