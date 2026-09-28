from __future__ import annotations

from typing import Any

from ..models import FieldMapping

#: 显式前缀：高级模式（手工映射）用它直接指定字段类型。
_TABLE_PREFIX = "tables."
_IMAGE_PREFIX = "images."
_FIELD_PREFIX = "fields."

_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg")
_COLLECTION_MARKERS = ("[*]", "[?")


def _target_name(target: str) -> str:
    """``tables.processes`` / ``fields.customer`` / ``processes`` → 同一个业务名。"""
    for prefix in (_TABLE_PREFIX, _IMAGE_PREFIX, _FIELD_PREFIX):
        if target.startswith(prefix):
            return target[len(prefix):]
    return target


def _nested_get(value: Any, path: str) -> Any:
    current = value
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _column_labels(rows: list[Any], configured: dict[str, Any]) -> dict[str, str]:
    labels = {str(key): str(label) for key, label in configured.items()}
    for row in rows[:20]:
        if not isinstance(row, dict):
            continue
        for key in row:
            labels.setdefault(str(key), str(key))
    return labels


def _is_collection(mapping: FieldMapping, value: Any) -> bool:
    """这条映射指向"多行记录"：通配路径（``[*]``/``[?``）或响应本身就是数组。

    只看机制，不看业务名：向导（普通模式）把集合映射成 ``processes`` / ``issues``，
    高级模式映射成 ``tables.processes``，两种都要能当整表绑定。
    """
    return (
        any(marker in (mapping.source_path or "") for marker in _COLLECTION_MARKERS)
        or isinstance(value, list)
    )


def _is_image(mapping: FieldMapping, value: Any) -> bool:
    """这条映射指向"一张图片"：显式 ``images.`` 前缀、配了 ``url_base``
    （向导给图片字段打的标记）、值是 data URL，或值以常见图片扩展名结尾。"""
    if mapping.target_field.startswith(_IMAGE_PREFIX):
        return True
    if (mapping.transform_config or {}).get("url_base"):
        return True
    sample = value[0] if isinstance(value, list) and value else value
    if not isinstance(sample, str) or not sample:
        return False
    if sample.startswith("data:image/"):
        return True
    return sample.split("?", 1)[0].casefold().endswith(_IMAGE_EXTENSIONS)


def build_workspace_binding_context(
    dataset_data: dict[str, Any], mappings: list[FieldMapping]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Adapt a connector Dataset to the visual template editor's f/t/i contract.

    The adapter is configuration driven and only looks at mapping *mechanism*:

    * ``tables.<name>`` (advanced mode), or any mapping whose source is a collection —
      the wizard writes those as ``processes`` / ``issues`` — becomes a repeatable table;
    * ``images.<name>``, or any mapping that points at a picture (``url_base`` set,
      data URL, image extension), becomes an image slot;
    * everything else stays a regular field, under ``f.<target>``.

    No external-system branching lives here, and both target naming styles produce the
    same ``t.<name>`` / ``i.<name>`` paths, so saved bindings keep working either way.
    """

    tables_data = dict(dataset_data.get("tables") or {})
    images_data = dict(dataset_data.get("images") or {})
    catalog: dict[str, Any] = {
        "fields": [],
        "tables": {},
        "images": {},
        "derived": {},
        "results": {},
    }
    #: Dataset 顶层键被当成整表/图片之后，就不再作为标量字段重复暴露。
    consumed_keys: set[str] = set()

    seen_fields: set[str] = set()
    for mapping in mappings:
        target = mapping.target_field
        config = mapping.transform_config or {}
        label = str(config.get("display_name") or _target_name(target).split(".")[-1])
        module = str(config.get("module") or "项目数据")
        group = str(config.get("group") or "基本信息")
        value = _nested_get(dataset_data, target)
        explicit_table = target.startswith(_TABLE_PREFIX)
        name = _target_name(target)

        if explicit_table or _is_collection(mapping, value):
            rows = value if isinstance(value, list) else []
            if rows and not any(isinstance(row, dict) for row in rows):
                # 基础值数组（例如选型类别）包成单列，整表填入才有列可映射。
                rows = [{"value": row} for row in rows]
            tables_data[name] = rows
            if "." not in target:
                consumed_keys.add(target)
            catalog["tables"][name] = {
                "label": label,
                "module": module,
                "group": group,
                "source_path": mapping.source_path,
                "columns": _column_labels(rows, config.get("column_labels") or {}),
            }
            continue

        if _is_image(mapping, value):
            if value is None:
                images_data[name] = []
            elif isinstance(value, list):
                images_data[name] = value
            else:
                images_data[name] = [value]
            if "." not in target:
                consumed_keys.add(target)
            catalog["images"][name] = {
                "path": f"i.{name}[0]",
                "label": label,
                "module": module,
                "group": group,
                "source_path": mapping.source_path,
            }
            continue

        path = f"f.{target}"
        if path in seen_fields:
            continue
        seen_fields.add(path)
        catalog["fields"].append({
            "path": path,
            "label": label,
            "module": module,
            "group": group,
            "source_path": mapping.source_path,
        })

    fields_data = {
        key: value
        for key, value in dataset_data.items()
        if key not in {"tables", "images"} and key not in consumed_keys
    }

    # Keep user-created Dataset fields usable even if their mapping metadata was
    # removed later. They receive neutral labels and remain editable in advanced mode.
    def include_unmapped(value: Any, prefix: str) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if prefix == "" and key in {"tables", "images"} | consumed_keys:
                    continue
                include_unmapped(child, f"{prefix}.{key}" if prefix else str(key))
            return
        path = f"f.{prefix}"
        if path not in seen_fields:
            seen_fields.add(path)
            catalog["fields"].append({
                "path": path,
                "label": prefix.split(".")[-1],
                "module": "其他字段",
                "group": "未分类",
                "source_path": "",
            })

    include_unmapped(fields_data, "")
    return {
        "f": fields_data,
        "t": tables_data,
        "i": images_data,
        "_ppt_context_version": 1,
    }, catalog


def build_workspace_combined_binding_context(
    sources: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    """Merge every workspace system/endpoint without letting fields cross sources.

    A single-source workspace retains the original f/t/i paths. With multiple
    inputs, the catalog exposes stable ``_systems.source_<id>`` namespaces,
    while unprefixed compatibility aliases stay in the data so bindings saved
    before a second system was attached continue to render.
    """
    if not sources:
        raise ValueError("workspace sources are required")

    built: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = []
    summaries: list[dict[str, Any]] = []
    for source in sources:
        data, catalog = build_workspace_binding_context(
            source["dataset"].data, source["mappings"]
        )
        built.append((source, data, catalog))
        summaries.append({
            "key": source["source_key"],
            "name": source["display_name"],
            "connection_id": source["connection_id"],
            "endpoint_id": source["endpoint_id"],
            "dataset_id": source["dataset"].id,
            "source": source["dataset"].source,
            "created_at": source["dataset"].created_at,
            "field_count": len(catalog["fields"]),
            "table_count": len(catalog["tables"]),
            "image_count": len(catalog["images"]),
        })

    if len(built) == 1:
        _, data, catalog = built[0]
        catalog["sources"] = summaries
        return data, catalog, summaries

    combined: dict[str, Any] = {
        "f": {"_systems": {}},
        "t": {"_systems": {}},
        "i": {"_systems": {}},
        "_ppt_context_version": 1,
    }
    combined_catalog: dict[str, Any] = {
        "fields": [], "tables": {}, "images": {}, "derived": {}, "results": {},
        "sources": summaries,
    }
    for source, data, catalog in built:
        key, display_name = source["source_key"], source["display_name"]
        combined["f"]["_systems"][key] = data["f"]
        combined["t"]["_systems"][key] = data["t"]
        combined["i"]["_systems"][key] = data["i"]

        # Backward-compatible aliases. The first attached source wins a name
        # collision, matching the stable workspace attachment order.
        for name, value in data["f"].items():
            combined["f"].setdefault(name, value)
        for name, value in data["t"].items():
            combined["t"].setdefault(name, value)
        for name, value in data["i"].items():
            combined["i"].setdefault(name, value)

        for field in catalog["fields"]:
            original = str(field["path"])
            suffix = original[2:] if original.startswith("f.") else original
            combined_catalog["fields"].append({
                **field,
                "path": f"f._systems.{key}.{suffix}",
                "module": f"{display_name} · {field.get('module') or '项目数据'}",
            })
        for name, meta in catalog["tables"].items():
            combined_catalog["tables"][f"_systems.{key}.{name}"] = {
                **meta,
                "module": f"{display_name} · {meta.get('module') or '项目数据'}",
            }
        for name, meta in catalog["images"].items():
            namespaced = f"_systems.{key}.{name}"
            combined_catalog["images"][namespaced] = {
                **meta,
                "path": f"i.{namespaced}[0]",
                "module": f"{display_name} · {meta.get('module') or '项目数据'}",
            }
    return combined, combined_catalog, summaries
