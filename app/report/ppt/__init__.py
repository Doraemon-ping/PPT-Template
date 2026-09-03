# -*- coding: utf-8 -*-
"""PPT planning boundary.

Rendering remains in the legacy ``app.ppt`` module until later migration stages.
"""

from .binding_resolver import SchemaValueResolver
from .deck import DeckDefinition, DeckPlan, DeckPlanner, DeckSlide, SlideOp
from .engine import PPTEngine, PPTGenerationResult
from .exact_engine import ExactTemplateEngine, ExactTemplateGenerationResult
from .openxml import (  # noqa: F401
    FillStats,
    ImageBindingError,
    ImageBindingFiller,
    OoxmlPackage,
    PathResolver,
    PlaceholderScanner,
    TemplateScan,
    TextBindingFiller,
    clone_slide,
    rebuild_presentation,
)
from .renderers import (
    ComplexImagePayload,
    ComplexImageRenderer,
    ImageRenderMode,
    ImageRenderer,
    RenderContext,
    SnapshotBackend,
    TextRenderer,
)
from .retirement import LegacyRetirementAudit, audit_legacy_retirement
from .schema import RendererType, SchemaField, SlideSchema
from .schema_loader import SlideSchemaLoader, SlideSchemaRegistry
from .slide_planner import SlidePlanner, SlidePlannerConfig, plan_slides
from .slide_factory import CreatedSlides, SlideFactory
from .shape_resolver import ShapeResolver, get_shape
from .template_engine import GENERATOR_VERSION, TemplateEngine, TemplateEngineResult
from .template_loader import LoadedTemplate, TemplateLoader
from .validators import (
    ReportValidator,
    SlideValidator,
    TemplateValidator,
    ValidationMessage,
    ValidationResult,
)

__all__ = [
    "LoadedTemplate",
    "LegacyRetirementAudit",
    "CreatedSlides",
    "ComplexImagePayload",
    "ComplexImageRenderer",
    "DeckDefinition",
    "DeckPlan",
    "DeckPlanner",
    "DeckSlide",
    "ExactTemplateEngine",
    "ExactTemplateGenerationResult",
    "FillStats",
    "GENERATOR_VERSION",
    "ImageBindingError",
    "ImageBindingFiller",
    "ImageRenderMode",
    "ImageRenderer",
    "OoxmlPackage",
    "PPTEngine",
    "PPTGenerationResult",
    "PathResolver",
    "PlaceholderScanner",
    "RendererType",
    "RenderContext",
    "ReportValidator",
    "SchemaField",
    "SchemaValueResolver",
    "ShapeResolver",
    "SlideOp",
    "SlideSchema",
    "SlideSchemaLoader",
    "SlideSchemaRegistry",
    "SlideValidator",
    "SnapshotBackend",
    "SlidePlanner",
    "SlidePlannerConfig",
    "SlideFactory",
    "TemplateEngine",
    "TemplateEngineResult",
    "TemplateLoader",
    "TemplateScan",
    "TemplateValidator",
    "TextBindingFiller",
    "TextRenderer",
    "ValidationMessage",
    "ValidationResult",
    "clone_slide",
    "get_shape",
    "rebuild_presentation",
    "audit_legacy_retirement",
    "plan_slides",
]
