# -*- coding: utf-8 -*-
"""Aggregate slide validation across a generated presentation."""

from ....dfm.models import SlideType
from ..exceptions import ReportValidationError, SlideSchemaError
from .result import ValidationResult
from .slide_validator import SlideValidator


class ReportValidator:
    def __init__(self, **slide_validator_options) -> None:
        self.slide_validator_options = slide_validator_options

    def validate(self, presentation, *, plans=None, schemas=None) -> ValidationResult:
        result = ValidationResult()
        plan_list = list(plans or [])
        slides = list(presentation.slides)
        if plans is not None and len(plan_list) != len(slides):
            result.add_error(
                "SLIDE_COUNT_MISMATCH",
                f"generated slides={len(slides)} does not match plans={len(plan_list)}",
                details={"slide_count": len(slides), "plan_count": len(plan_list)},
            )

        validator = SlideValidator(
            presentation.slide_width,
            presentation.slide_height,
            **self.slide_validator_options,
        )
        for zero_index, slide in enumerate(slides):
            slide_index = zero_index + 1
            plan = plan_list[zero_index] if zero_index < len(plan_list) else None
            schema = None
            if plan is not None:
                raw_type = getattr(getattr(plan, "slide_type", None), "value", getattr(plan, "slide_type", None))
                try:
                    SlideType(raw_type)
                except (TypeError, ValueError):
                    result.add_error(
                        "SLIDE_TYPE_UNRECOGNIZED",
                        f"unrecognized slide type: {raw_type}",
                        slide_index=slide_index,
                        template_key=getattr(plan, "template_key", None),
                    )
                    plan = None
                if plan is not None and schemas is not None:
                    try:
                        schema = schemas.get_for_plan(plan)
                    except SlideSchemaError as exc:
                        result.add_error(
                            "SLIDE_SCHEMA_MISMATCH",
                            str(exc),
                            slide_index=slide_index,
                            template_key=getattr(plan, "template_key", None),
                            issue_id=getattr(plan, "issue_id", None),
                        )
            result.merge(
                validator.validate(
                    slide,
                    slide_index=slide_index,
                    plan=plan,
                    schema=schema,
                )
            )
        return result

    def validate_or_raise(self, presentation, *, plans=None, schemas=None) -> ValidationResult:
        result = self.validate(presentation, plans=plans, schemas=schemas)
        if result.errors:
            raise ReportValidationError(result)
        return result
