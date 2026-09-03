# -*- coding: utf-8 -*-
"""Reusable structured validation result shared by later validator stages."""

from dataclasses import asdict, dataclass, field as dc_field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class ValidationMessage:
    code: str
    message: str
    template_key: Optional[str] = None
    slide_index: Optional[int] = None
    shape: Optional[str] = None
    field: Optional[str] = None
    renderer: Optional[str] = None
    issue_id: Optional[str] = None
    details: Dict[str, Any] = dc_field(default_factory=dict)


@dataclass
class ValidationResult:
    errors: List[ValidationMessage] = dc_field(default_factory=list)
    warnings: List[ValidationMessage] = dc_field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not self.errors

    def add_error(self, code: str, message: str, **context: Any) -> None:
        self.errors.append(ValidationMessage(code=code, message=message, **context))

    def add_warning(self, code: str, message: str, **context: Any) -> None:
        self.warnings.append(ValidationMessage(code=code, message=message, **context))

    def merge(self, other: "ValidationResult") -> "ValidationResult":
        self.errors.extend(other.errors)
        self.warnings.extend(other.warnings)
        return self

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "errors": [asdict(item) for item in self.errors],
            "warnings": [asdict(item) for item in self.warnings],
        }
