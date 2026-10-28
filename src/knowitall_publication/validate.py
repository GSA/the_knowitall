from collections.abc import Mapping

from knowitall_graphify import GraphGeneration, validate_generation
from knowitall_snapshot import SnapshotManifest

from .store import PublicationValidationError


def validate_for_publication(generation: GraphGeneration) -> None:
    validate_generation(generation)


def authoritative_deletions(previous: SnapshotManifest, current: SnapshotManifest, *, git_delta: Mapping[str, object] | None = None) -> set[str]:
    previous_paths = {entry.path for entry in previous.included}
    current_paths = {entry.path for entry in current.included}
    candidates = previous_paths - current_paths
    if current.inventory_complete:
        return candidates
    if git_delta is None:
        raise PublicationValidationError("incomplete inventory has no deletion authority")
    if git_delta.get("from") != previous.commit or git_delta.get("to") != current.commit:
        raise PublicationValidationError("Git delta does not bind both revisions")
    deleted = git_delta.get("deleted")
    if not isinstance(deleted, list) or any(not isinstance(path, str) for path in deleted):
        raise PublicationValidationError("Git delta deleted paths are invalid")
    asserted = set(deleted)
    if asserted != candidates:
        raise PublicationValidationError("Git delta does not account for deletion candidates")
    return asserted
