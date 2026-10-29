from dataclasses import dataclass
from enum import StrEnum


class QueryStatus(StrEnum):
    OK = "ok"
    PARTIAL = "partial"
    NOT_FOUND = "not_found"
    AMBIGUOUS = "ambiguous"
    STALE = "stale"
    UNAVAILABLE = "unavailable"
    INVALID_REQUEST = "invalid_request"


def _nonempty(name: str, value: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a nonempty opaque string")


@dataclass(frozen=True)
class SnapshotRef:
    project_id: str
    repository_id: str
    snapshot_id: str
    commit: str
    content_manifest_digest: str

    def __post_init__(self) -> None:
        for name in (
            "project_id",
            "repository_id",
            "snapshot_id",
            "commit",
            "content_manifest_digest",
        ):
            _nonempty(name, getattr(self, name))


@dataclass(frozen=True)
class GenerationRef:
    snapshot: SnapshotRef
    generation_id: str
    artifact_digest: str

    def __post_init__(self) -> None:
        _nonempty("generation_id", self.generation_id)
        _nonempty("artifact_digest", self.artifact_digest)


@dataclass(frozen=True)
class SourceRange:
    start_line: int
    start_column: int
    end_line: int
    end_column: int

    def __post_init__(self) -> None:
        points = (self.start_line, self.start_column, self.end_line, self.end_column)
        if any(not isinstance(point, int) or isinstance(point, bool) or point < 1 for point in points):
            raise ValueError("source positions must be one-based positive integers")
        if (self.end_line, self.end_column) <= (self.start_line, self.start_column):
            raise ValueError("source range must be nonempty and half-open")


@dataclass(frozen=True)
class Coverage:
    inventory: str
    extraction: str
    relevant_scope: str
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("inventory", "extraction", "relevant_scope"):
            if getattr(self, name) not in {"complete", "partial", "unknown"}:
                raise ValueError(f"{name} has an invalid coverage value")


@dataclass(frozen=True)
class MissingEvidence:
    kind: str
    scope: str
    reason: str

    def __post_init__(self) -> None:
        for name in ("kind", "scope", "reason"):
            _nonempty(name, getattr(self, name))
