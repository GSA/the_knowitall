from dataclasses import dataclass

from knowitall_contract import GenerationRef, SnapshotRef
from knowitall_publication import PublicationReceipt


class UpdateConflict(ValueError):
    pass


class UpdateValidationError(ValueError):
    pass


class UpdateInterrupted(RuntimeError):
    pass


@dataclass(frozen=True)
class UpdateStatus:
    request_id: str
    phase: str
    snapshot: SnapshotRef
    expected_current: GenerationRef | None
    generation: GenerationRef | None = None
    receipt: PublicationReceipt | None = None
    reasons: tuple[tuple[str, str], ...] = ()
