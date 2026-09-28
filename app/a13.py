# -*- coding: utf-8 -*-
"""A13 state projections used by project persistence and the PPT workbench."""

from copy import deepcopy
from typing import Any, Mapping


QUOTE_META_FIELDS = {
    "customer": "quoteCustomer", "moldName": "quoteMoldName",
    "partNo": "quotePartNo", "date": "quoteDate", "alloy": "quoteAlloy",
    "blankW": "quoteBlankWeight", "finW": "quoteFinishedWeight",
    "moldType": "quoteMoldType", "mat": "quoteMoldMaterial",
    "ton": "quoteMachineTonnage", "cond": "quoteStructureCondition",
    "qty": "quoteMoldQuantity", "slider": "quoteHasSlider",
}


def project_state(data: Mapping[str, Any] | None) -> dict:
    """Keep full A13 state and expose rich data through stable ``f/t/i`` paths."""
    out = deepcopy(dict(data or {}))
    fields = out.setdefault("f", {})
    tables = out.setdefault("t", {})
    out.setdefault("i", {})

    quote = out.get("quote") if isinstance(out.get("quote"), Mapping) else {}
    meta = quote.get("meta") if isinstance(quote.get("meta"), Mapping) else {}
    for source, target in QUOTE_META_FIELDS.items():
        if source in meta:
            fields[target] = meta[source]

    sheet = quote.get("sheet") if isinstance(quote.get("sheet"), list) else []
    quote_rows, net_total = [], 0.0
    for item in sheet:
        if not isinstance(item, Mapping):
            continue
        unit, qty = _number(item.get("unit")), _number(item.get("qty"), 1.0)
        total = unit * qty
        net_total += total
        quote_rows.append({
            "key": item.get("key", ""), "cat": item.get("cat", ""),
            "desc": item.get("desc", ""), "unit": unit, "qty": qty, "total": total,
        })
    tables["quoteSheet"] = quote_rows
    fields.update({
        "quoteItemCount": len(quote_rows), "quoteNetTotal": round(net_total, 2),
        "quoteTax": round(net_total * 0.13, 2), "quoteGrossTotal": round(net_total * 1.13, 2),
    })

    mach = out.get("mach") if isinstance(out.get("mach"), Mapping) else {}
    machines = mach.get("list") if isinstance(mach.get("list"), list) else []
    tables["machineLibrary"] = [deepcopy(row) for row in machines if isinstance(row, Mapping)]

    vision_rows = []
    vision = out.get("v") if isinstance(out.get("v"), Mapping) else {}
    for module, bucket in vision.items():
        defects = bucket.get("defects") if isinstance(bucket, Mapping) else None
        if not isinstance(defects, list):
            continue
        for defect in defects:
            if not isinstance(defect, Mapping):
                continue
            vision_rows.append({
                "module": module.removesuffix("Def"), "image": defect.get("img", 0),
                "type": defect.get("type", ""), "severity": defect.get("severity", ""),
                "advice": defect.get("advice", ""), "source": defect.get("source", ""),
                "verdict": defect.get("verdict", ""), "confidence": defect.get("confidence", 0),
                "x": defect.get("x", 0), "y": defect.get("y", 0),
                "w": defect.get("w", 0), "h": defect.get("h", 0),
            })
    tables["visionDefects"] = vision_rows
    fields["visionDefectCount"] = len(vision_rows)
    fields["visionReviewedCount"] = sum(bool(row["verdict"]) for row in vision_rows)
    return out


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
