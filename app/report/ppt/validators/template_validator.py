# -*- coding: utf-8 -*-
"""Validate a versioned template against every loaded slide schema."""

from ..exceptions import (
    TemplateShapeDuplicateError,
    TemplateShapeMissingError,
    TemplateSlideMissingError,
    TemplateValidationError,
)
from ..schema import RendererType
from ..shape_resolver import ShapeResolver
from .result import ValidationResult


class TemplateValidator:
    def __init__(self, shape_resolver=None) -> None:
        self.shape_resolver = shape_resolver or ShapeResolver()

    def validate(self, template, schemas) -> ValidationResult:
        result = ValidationResult()
        if str(template.version) != str(schemas.template_version):
            result.add_error(
                "TEMPLATE_VERSION_MISMATCH",
                f"template version={template.version} does not match schema version={schemas.template_version}",
                details={
                    "template_version": str(template.version),
                    "schema_template_version": str(schemas.template_version),
                },
            )

        used_template_keys = set()
        for schema in schemas.schemas.values():
            template_key = schema.template.strip().upper()
            used_template_keys.add(template_key)
            try:
                slide = template.get_slide(template_key)
            except TemplateSlideMissingError:
                result.add_error(
                    "TEMPLATE_SLIDE_MISSING",
                    f"required template slide is missing: {template_key}",
                    template_key=template_key,
                )
                continue

            for field_name, binding in schema.fields.items():
                try:
                    shape = self.shape_resolver.get_shape(
                        slide,
                        binding.shape,
                        slide_key=template_key,
                    )
                except TemplateShapeMissingError:
                    result.add_error(
                        "TEMPLATE_SHAPE_MISSING",
                        f"required named shape is missing: {binding.shape}",
                        template_key=template_key,
                        shape=binding.shape,
                        field=field_name,
                        renderer=binding.renderer.value,
                    )
                    continue
                except TemplateShapeDuplicateError:
                    result.add_error(
                        "TEMPLATE_SHAPE_DUPLICATE",
                        f"named shape appears more than once: {binding.shape}",
                        template_key=template_key,
                        shape=binding.shape,
                        field=field_name,
                        renderer=binding.renderer.value,
                    )
                    continue
                self._validate_shape_capability(
                    result,
                    shape,
                    template_key=template_key,
                    field_name=field_name,
                    renderer=binding.renderer,
                )

        for unused in sorted(set(template.template_keys).difference(used_template_keys)):
            result.add_warning(
                "UNUSED_TEMPLATE_SLIDE",
                f"template slide has no matching schema: {unused}",
                template_key=unused,
            )
        return result

    def validate_or_raise(self, template, schemas) -> ValidationResult:
        result = self.validate(template, schemas)
        if result.errors:
            raise TemplateValidationError(result)
        return result

    @staticmethod
    def _validate_shape_capability(
        result,
        shape,
        *,
        template_key,
        field_name,
        renderer,
    ) -> None:
        if renderer in {RendererType.TEXT, RendererType.BADGE}:
            supported = bool(getattr(shape, "has_text_frame", False))
            requirement = "a text frame"
        elif renderer == RendererType.TABLE:
            supported = bool(getattr(shape, "has_table", False))
            requirement = "a table"
        elif renderer in {RendererType.IMAGE, RendererType.COMPLEX_IMAGE}:
            supported = bool(getattr(shape, "width", 0) > 0 and getattr(shape, "height", 0) > 0)
            requirement = "positive width and height"
        else:  # RendererType currently prevents this, retained for future extensions.
            supported = False
            requirement = f"support for renderer={renderer}"
        if not supported:
            result.add_error(
                "TEMPLATE_SHAPE_INCOMPATIBLE",
                f"shape {shape.name} must provide {requirement} for renderer={renderer.value}",
                template_key=template_key,
                shape=shape.name,
                field=field_name,
                renderer=renderer.value,
            )
