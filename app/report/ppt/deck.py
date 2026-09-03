# -*- coding: utf-8 -*-
"""Declarative deck orchestration (编排).

A deck describes which template slides make up the report, in what order,
which slide repeats over an array (for example ``t.issues``) and which
optional slides are skipped by a condition. Two binding styles are supported:

1. Placeholder convention (pptx-template style): template text contains
   ``{path.to.data}`` and the path itself is the binding.
2. Explicit shape-name bindings: ``bindings`` maps a PowerPoint shape name to a
   data path (``text`` / ``table_cell`` / ``image``), which also works on
   templates that contain no placeholders.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Tuple

from pydantic import BaseModel, Field

from .openxml.text_binding import PathResolver


class ShapeBindingSpec(BaseModel):
    type: str = Field(
        "text",
        description="text | text_replace | text_template | image | image_region | formula | table_cell | table_rows",
    )
    source: str = Field(..., min_length=1, description="dotted data path")
    required: bool = Field(True, description="missing shape raises when true")
    shape: Optional[str] = Field(None, description="target shape name; defaults to the binding key")
    options: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "shape_id selects duplicate names; table cell: {row,column}; "
            "text_template/formula: {template}; image_region: {fit: cover|contain|stretch}"
        ),
    )


class DeckSlide(BaseModel):
    source: int = Field(..., ge=1, description="1-based template slide index")
    template: Optional[str] = Field(None, description="template id; defaults to the deck template")
    repeat: Optional[str] = Field(None, description="dotted path to an array in the data")
    condition: Optional[str] = Field(None, description="dotted path; slide is skipped when falsy")
    images: Dict[str, str] = Field(
        default_factory=dict,
        description="shape name -> data path of image bindings on this slide",
    )
    bindings: Dict[str, ShapeBindingSpec] = Field(
        default_factory=dict,
        description="explicit shape-name bindings (text / table_cell / image)",
    )


class DeckDefinition(BaseModel):
    template: str = Field(..., min_length=1, description="registered template name")
    output_mode: str = Field("deck", description="deck (rebuilt slide list) or in_place (fill only)")
    missing: str = Field("keep", description="placeholder missing policy: keep | clear | error")
    slides: List[DeckSlide] = Field(..., min_length=1)


@dataclass(frozen=True)
class SlideOp:
    """One expansion of a deck slide: a source slide plus repeat items."""

    source_index: int
    items: Tuple[Optional[Dict[str, Any]], ...]
    images: Dict[str, str]
    bindings: Dict[str, ShapeBindingSpec]
    template: Optional[str] = None

    # Runtime-only table slices, not saved in scheme manifests.
    table_data: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_repeat(self) -> bool:
        return len(self.items) > 1


@dataclass(frozen=True)
class DeckPlan:
    ops: tuple = ()
    warnings: tuple = ()
    source_indices: tuple = ()

    def to_dict(self) -> dict:
        return {
            "ops": [
                {
                    "source_index": op.source_index,
                    "repeat_items": len(op.items),
                    "images": op.images,
                    "bindings": {name: spec.model_dump() for name, spec in op.bindings.items()},
                }
                for op in self.ops
            ],
            "warnings": list(self.warnings),
        }


class DeckPlanner:
    """Expand a deck against resolved data without touching any PPT object."""

    def expand(self, deck: DeckDefinition, data: Mapping) -> DeckPlan:
        resolver = PathResolver((data,))
        ops: List[SlideOp] = []
        warnings = []
        source_indices = []
        for slide in deck.slides:
            if slide.condition:
                value, found = resolver.resolve(slide.condition)
                if not found or not _truthy(value):
                    continue
            items: Tuple[Optional[Dict[str, Any]], ...]
            if slide.repeat:
                value, found = resolver.resolve(slide.repeat)
                if not found:
                    warnings.append(f"repeat path missing: {slide.repeat}")
                    items = (None,)
                elif not isinstance(value, (list, tuple)):
                    warnings.append(f"repeat path is not an array: {slide.repeat}")
                    items = (None,)
                else:
                    items = tuple(
                        item for item in value
                        if isinstance(item, dict) or item is None
                    ) or (None,)
            else:
                items = (None,)
            ops.append(SlideOp(
                source_index=slide.source,
                items=items,
                images=dict(slide.images),
                bindings=dict(slide.bindings),
                template=slide.template,
            ))
            source_indices.append(slide.source)
        return DeckPlan(ops=tuple(ops), warnings=tuple(warnings), source_indices=tuple(source_indices))


def _truthy(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, dict)):
        return bool(value)
    return bool(value)
