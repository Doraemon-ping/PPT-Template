# -*- coding: utf-8 -*-
"""Minimal schema-driven PPT generation engine used alongside the legacy path."""

import io
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional

from .binding_resolver import SchemaValueResolver
from .exceptions import PPTGenerationError, RendererError
from .renderers import ComplexImageRenderer, ImageRenderer, RenderContext, TextRenderer
from .schema import RendererType
from .schema_loader import SlideSchemaLoader
from .shape_resolver import ShapeResolver
from .slide_factory import SlideFactory
from .slide_planner import SlidePlanner
from .template_loader import TemplateLoader
from .validators import ReportValidator, TemplateValidator, ValidationResult


LOGGER = logging.getLogger(__name__)
GENERATOR_VERSION = "0.2-migration1"


@dataclass(frozen=True)
class PPTGenerationResult:
    buffer: io.BytesIO
    plans: tuple
    validation: ValidationResult
    template_version: str
    generator_version: str
    generation_time_seconds: float


class PPTEngine:
    """Generate only pages supported by the new named-shape template contract."""

    def __init__(
        self,
        template_path,
        schema_directory,
        *,
        template_version: str = "1",
        planner=None,
        renderers: Optional[Mapping[RendererType, object]] = None,
    ) -> None:
        self.template_path = Path(template_path)
        self.schema_directory = Path(schema_directory)
        self.template_version = str(template_version)
        self.planner = planner or SlidePlanner()
        self.renderers = dict(renderers or {
            RendererType.TEXT: TextRenderer(),
            RendererType.BADGE: TextRenderer(),
            RendererType.IMAGE: ImageRenderer(),
            RendererType.COMPLEX_IMAGE: ComplexImageRenderer(),
        })
        self.schema_loader = SlideSchemaLoader()
        self.shape_resolver = ShapeResolver()
        self.value_resolver = SchemaValueResolver()

    def generate(self, report) -> PPTGenerationResult:
        started = time.perf_counter()
        stage = "load"
        try:
            plans = tuple(self.planner.plan(report))
            schemas = self.schema_loader.load_directory(self.schema_directory)
            required_keys = [schemas.get_for_plan(plan).template for plan in plans]
            template = TemplateLoader(
                self.template_path,
                version=self.template_version,
                required_keys=required_keys,
            ).load()

            stage = "template_validation"
            TemplateValidator().validate_or_raise(template, schemas)

            stage = "slide_factory"
            created = SlideFactory().create(template, plans)

            stage = "render"
            for slide, plan in zip(created.slides, plans):
                schema = schemas.get_for_plan(plan)
                self._render_slide(slide, plan, schema)

            self._set_metadata(created.presentation, report)
            stage = "report_validation"
            validation = ReportValidator().validate_or_raise(
                created.presentation,
                plans=plans,
                schemas=schemas,
            )

            stage = "save"
            buffer = io.BytesIO()
            created.presentation.save(buffer)
            buffer.seek(0)
            elapsed = time.perf_counter() - started
            self._log_result(report, plans, validation, elapsed)
            return PPTGenerationResult(
                buffer=buffer,
                plans=plans,
                validation=validation,
                template_version=self.template_version,
                generator_version=GENERATOR_VERSION,
                generation_time_seconds=elapsed,
            )
        except Exception as exc:
            elapsed = time.perf_counter() - started
            LOGGER.exception(
                "new_ppt_generation_failed report_id=%s project_id=%s template_version=%s "
                "stage=%s generation_time=%.3f error=%s",
                report.metadata.report_id,
                report.project.project_id,
                self.template_version,
                stage,
                elapsed,
                exc,
            )
            if isinstance(exc, PPTGenerationError):
                raise
            raise PPTGenerationError(stage, str(exc)) from exc

    def _render_slide(self, slide, plan, schema):
        for field_name, binding in schema.fields.items():
            value = self.value_resolver.resolve_field(plan.data, field_name, binding)
            if not binding.required and self._is_empty(value):
                continue
            renderer = self.renderers.get(binding.renderer)
            if renderer is None:
                raise RendererError(
                    binding.renderer.value,
                    plan.template_key,
                    binding.shape,
                    "renderer is not registered",
                )
            shape = self.shape_resolver.get_shape(
                slide,
                binding.shape,
                slide_key=plan.template_key,
            )
            renderer.render(
                shape,
                value,
                RenderContext(
                    slide_key=plan.template_key,
                    field_name=field_name,
                    options=binding.options,
                ),
            )

    @staticmethod
    def _is_empty(value):
        if value is None:
            return True
        if isinstance(value, str):
            return not value.strip()
        if isinstance(value, (list, tuple, dict)):
            return not value
        return False

    def _set_metadata(self, presentation, report):
        properties = presentation.core_properties
        properties.subject = f"DFM report {report.metadata.report_id}".strip()
        properties.keywords = (
            f"template_version={self.template_version};"
            f"generator_version={GENERATOR_VERSION}"
        )
        properties.comments = (
            f"report_id={report.metadata.report_id};"
            f"project_id={report.project.project_id};"
            f"generated_at={report.metadata.generated_at.isoformat()}"
        )

    def _log_result(self, report, plans, validation, elapsed):
        LOGGER.info(
            "new_ppt_generation_complete report_id=%s project_id=%s template_version=%s "
            "generator_version=%s slide_count=%d issue_count=%d generation_time=%.3f "
            "validation_errors=%d validation_warnings=%d",
            report.metadata.report_id,
            report.project.project_id,
            self.template_version,
            GENERATOR_VERSION,
            len(plans),
            len(report.issues),
            elapsed,
            len(validation.errors),
            len(validation.warnings),
        )
