"""Base model and annotated scalar types shared by every contract."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Annotated, Any

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    WithJsonSchema,
)

from manuallabor import ids


class ContractModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        populate_by_name=True,
        use_enum_values=False,
        json_schema_serialization_defaults_required=True,
        ser_json_inf_nan="null",
    )


def round6(x: float) -> float:
    return round(x, 6) + 0.0


def round3(x: float) -> float:
    return round(x, 3) + 0.0


def check_bbox(v: list[float]) -> list[float]:
    x0, y0, x1, y1 = v
    if x0 > x1 or y0 > y1:
        raise ValueError(f"bbox must satisfy x0<=x1 and y0<=y1, got {v}")
    return v


Unit = Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False), AfterValidator(round6)]
Coord = Annotated[float, Field(allow_inf_nan=False), AfterValidator(round6)]
BBox = Annotated[
    list[Coord],
    Field(min_length=4, max_length=4),
    AfterValidator(check_bbox),
]


def _parse_utc(v: Any) -> Any:
    if isinstance(v, str):
        s = v[:-1] + "+00:00" if v.endswith("Z") else v
        try:
            v = datetime.fromisoformat(s)
        except ValueError:
            return v
    if isinstance(v, datetime):
        if v.tzinfo is None or v.utcoffset() is None:
            raise ValueError("datetime must be timezone-aware")
        v = v.astimezone(UTC)
        return v.replace(microsecond=(v.microsecond // 1000) * 1000)
    return v


def _fmt_utc(v: datetime) -> str:
    v = v.astimezone(UTC)
    base = v.strftime("%Y-%m-%dT%H:%M:%S")
    ms = v.microsecond // 1000
    return f"{base}.{ms:03d}Z" if ms else f"{base}Z"


UTCDateTime = Annotated[
    datetime,
    BeforeValidator(_parse_utc),
    PlainSerializer(_fmt_utc, return_type=str, when_used="json"),
    WithJsonSchema({"type": "string", "format": "date-time"}),
]


def _anon(pattern: str) -> str:
    """Same expression as ids.*_PATTERN with named groups made non-capturing (ECMA-safe)."""
    return re.sub(r"\?P<\w+>", "?:", pattern)


DocSlug = Annotated[str, Field(pattern=f"^{ids.SLUG_PATTERN}$", max_length=48)]
TopicSlug = Annotated[str, Field(pattern=f"^{ids.SLUG_PATTERN}$", max_length=48)]
BlockId = Annotated[str, Field(pattern=_anon(ids.BLOCK_ID_PATTERN))]
FigureId = Annotated[str, Field(pattern=_anon(ids.FIGURE_ID_PATTERN))]
ArticleId = Annotated[str, Field(pattern=_anon(ids.ARTICLE_ID_PATTERN))]
GroupId = Annotated[str, Field(pattern=_anon(ids.GROUP_ID_PATTERN))]
TargetId = Annotated[
    str,
    Field(pattern=f"(?:{_anon(ids.BLOCK_ID_PATTERN)})|(?:{_anon(ids.FIGURE_ID_PATTERN)})"),
]
Sha256Hex = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
PHash = Annotated[str, Field(pattern=r"^[0-9a-f]{16}$")]
FlagId = Annotated[str, Field(pattern=r"^flag-\d{6}$")]
ProposalId = Annotated[str, Field(pattern=r"^prop-\d{6}$")]


def check_target_id(v: str) -> str:
    if v.startswith("FIG-"):
        ids.parse_figure_id(v)
    else:
        ids.parse_block_id(v)
    return v
