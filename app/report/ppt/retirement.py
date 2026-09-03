# -*- coding: utf-8 -*-
"""Objective safety gate for retiring the legacy PPT generator."""

from dataclasses import dataclass
from typing import Any, Mapping, Tuple


_MAPPED_FIELD_KEYS = frozenset({
    "projectId", "projNo", "projName", "partName", "partNo", "custName",
    "version", "dfmDate", "reportId", "projType", "material", "company",
    "maker", "checker", "approver",
    "wFinish", "wCast", "wRunner", "wOverflow", "wall", "wallMax",
    "dimL", "dimW", "dimH", "cav", "castP", "annual", "surfaceReq",
    "leakReq", "leakVal",
})
_MAPPED_TABLE_KEYS = frozenset({"issues"})
# The current adapter only accepts issue-local images from each issue row.
_MAPPED_TOP_LEVEL_IMAGE_KEYS = frozenset()


@dataclass(frozen=True)
class LegacyRetirementAudit:
    ready: bool
    blockers: Tuple[str, ...]
    unmapped_field_keys: Tuple[str, ...]
    unmapped_table_keys: Tuple[str, ...]
    unmapped_image_keys: Tuple[str, ...]
    legacy_slide_count: int
    new_slide_count: int
    output_equivalence_verified: bool
    api_cutover_verified: bool
    rollback_verified: bool

    def to_dict(self):
        return {
            "ready": self.ready,
            "blockers": list(self.blockers),
            "unmapped_field_keys": list(self.unmapped_field_keys),
            "unmapped_table_keys": list(self.unmapped_table_keys),
            "unmapped_image_keys": list(self.unmapped_image_keys),
            "legacy_slide_count": self.legacy_slide_count,
            "new_slide_count": self.new_slide_count,
            "output_equivalence_verified": self.output_equivalence_verified,
            "api_cutover_verified": self.api_cutover_verified,
            "rollback_verified": self.rollback_verified,
        }


def audit_legacy_retirement(
    f: Mapping[str, Any],
    t: Mapping[str, Any],
    i: Mapping[str, Any],
    *,
    legacy_slide_count: int,
    new_slide_count: int,
    output_equivalence_verified: bool = False,
    api_cutover_verified: bool = False,
    rollback_verified: bool = False,
) -> LegacyRetirementAudit:
    """Return readiness evidence; this function never deletes or switches anything."""

    unmapped_fields = _unmapped_nonempty_keys(f, _MAPPED_FIELD_KEYS)
    unmapped_tables = _unmapped_nonempty_keys(t, _MAPPED_TABLE_KEYS)
    unmapped_images = _unmapped_nonempty_keys(i, _MAPPED_TOP_LEVEL_IMAGE_KEYS)
    blockers = []
    if unmapped_fields:
        blockers.append("legacy fields are not represented in DFMReport")
    if unmapped_tables:
        blockers.append("legacy tables are not represented in DFMReport")
    if unmapped_images:
        blockers.append("top-level legacy images are not represented in DFMReport")
    if legacy_slide_count != new_slide_count:
        blockers.append("new and legacy slide counts differ")
    if not output_equivalence_verified:
        blockers.append("output equivalence has not been verified")
    if not api_cutover_verified:
        blockers.append("API cutover has not been verified")
    if not rollback_verified:
        blockers.append("rollback path has not been verified")
    return LegacyRetirementAudit(
        ready=not blockers,
        blockers=tuple(blockers),
        unmapped_field_keys=unmapped_fields,
        unmapped_table_keys=unmapped_tables,
        unmapped_image_keys=unmapped_images,
        legacy_slide_count=int(legacy_slide_count),
        new_slide_count=int(new_slide_count),
        output_equivalence_verified=bool(output_equivalence_verified),
        api_cutover_verified=bool(api_cutover_verified),
        rollback_verified=bool(rollback_verified),
    )


def _unmapped_nonempty_keys(values: Mapping[str, Any], mapped_keys) -> Tuple[str, ...]:
    return tuple(sorted(
        str(key) for key, value in (values or {}).items()
        if key not in mapped_keys and not _is_empty(value)
    ))


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, dict)):
        return not value
    return False
