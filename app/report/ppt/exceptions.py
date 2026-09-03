# -*- coding: utf-8 -*-
"""Explicit template and named-shape errors for the PPT pipeline."""

from pathlib import Path


class PPTTemplateError(RuntimeError):
    """Base class for template contract failures."""


class TemplateNotFoundError(PPTTemplateError):
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        super().__init__(f"PPT template not found: {self.path}")


class TemplateLoadError(PPTTemplateError):
    def __init__(self, path: Path, reason: str) -> None:
        self.path = Path(path)
        self.reason = reason
        super().__init__(f"PPT template could not be loaded: {self.path}; reason={reason}")


class TemplateSlideMissingError(PPTTemplateError):
    def __init__(self, template_key: str, path: Path) -> None:
        self.template_key = template_key
        self.path = Path(path)
        super().__init__(f"Template slide missing: template={template_key}; path={self.path}")


class TemplateSlideDuplicateError(PPTTemplateError):
    def __init__(self, template_key: str, path: Path) -> None:
        self.template_key = template_key
        self.path = Path(path)
        super().__init__(f"Template slide duplicated: template={template_key}; path={self.path}")


class TemplateShapeMissingError(PPTTemplateError):
    def __init__(self, slide: str, shape: str) -> None:
        self.slide = slide
        self.shape = shape
        super().__init__(f"Template shape missing: slide={slide}; shape={shape}")


class TemplateShapeDuplicateError(PPTTemplateError):
    def __init__(self, slide: str, shape: str) -> None:
        self.slide = slide
        self.shape = shape
        super().__init__(f"Template shape duplicated: slide={slide}; shape={shape}")


class SlideSchemaError(RuntimeError):
    """Base class for slide-schema contract failures."""


class SlideSchemaNotFoundError(SlideSchemaError):
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        super().__init__(f"Slide schema not found: {self.path}")


class SlideSchemaLoadError(SlideSchemaError):
    def __init__(self, path: Path, reason: str) -> None:
        self.path = Path(path)
        self.reason = reason
        super().__init__(f"Slide schema could not be loaded: {self.path}; reason={reason}")


class SlideSchemaValidationError(SlideSchemaError):
    def __init__(self, source: str, reason: str) -> None:
        self.source = source
        self.reason = reason
        super().__init__(f"Slide schema invalid: source={source}; reason={reason}")


class SlideSchemaMissingError(SlideSchemaError):
    def __init__(self, slide_type: str) -> None:
        self.slide_type = slide_type
        super().__init__(f"Slide schema missing: slide_type={slide_type}")


class SlideSchemaDataMissingError(SlideSchemaError):
    def __init__(self, field: str, source: str) -> None:
        self.field = field
        self.source = source
        super().__init__(f"Slide schema data missing: field={field}; source={source}")


class RendererError(RuntimeError):
    """A renderer failed with enough context to identify the binding."""

    def __init__(self, renderer: str, slide: str, shape: str, reason: str) -> None:
        self.renderer = renderer
        self.slide = slide
        self.shape = shape
        self.reason = reason
        super().__init__(
            f"PPT renderer failed: renderer={renderer}; slide={slide}; "
            f"shape={shape}; reason={reason}"
        )


class TemplateValidationError(PPTTemplateError):
    def __init__(self, result) -> None:
        self.result = result
        first = result.errors[0].message if result.errors else "unknown validation error"
        super().__init__(
            f"PPT template validation failed: errors={len(result.errors)}; first={first}"
        )


class ReportValidationError(RuntimeError):
    def __init__(self, result) -> None:
        self.result = result
        first = result.errors[0].message if result.errors else "unknown validation error"
        super().__init__(
            f"Generated PPT validation failed: errors={len(result.errors)}; first={first}"
        )


class SlideFactoryError(RuntimeError):
    def __init__(self, template_key: str, reason: str) -> None:
        self.template_key = template_key
        self.reason = reason
        super().__init__(f"PPT slide factory failed: template={template_key}; reason={reason}")


class PPTGenerationError(RuntimeError):
    def __init__(self, stage: str, reason: str) -> None:
        self.stage = stage
        self.reason = reason
        super().__init__(f"PPT generation failed: stage={stage}; reason={reason}")
