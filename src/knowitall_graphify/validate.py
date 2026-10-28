from .normalize import GenerationValidationError, GraphGeneration


def validate_generation(generation: GraphGeneration) -> None:
    """Recheck invariants needed before a normalized generation is publishable."""
    node_ids = {node.symbol_id for node in generation.nodes}
    if any(edge.source not in node_ids or edge.target not in node_ids for edge in generation.edges):
        raise GenerationValidationError("dangling edge endpoint")
    failures = generation.failed_files + generation.inventory_failures + generation.exclusions
    if generation.coverage.inventory == "partial" and not generation.inventory_failures:
        raise GenerationValidationError("partial inventory requires machine-readable inventory failures")
    if generation.coverage.extraction == "partial" and not (generation.failed_files or generation.exclusions):
        raise GenerationValidationError("partial extraction requires machine-readable failures or exclusions")
    if generation.inventory_failures and (
        generation.coverage.inventory != "partial"
        or generation.coverage.relevant_scope != "partial"
        or generation.state != "partial"
    ):
        raise GenerationValidationError("inventory failures require partial inventory, state, and relevant scope")
    if (generation.failed_files or generation.exclusions) and (
        generation.coverage.extraction != "partial"
        or generation.coverage.relevant_scope != "partial"
        or generation.state != "partial"
    ):
        raise GenerationValidationError("extraction failures or exclusions require partial extraction, state, and relevant scope")
    if generation.state == "complete" and failures:
        raise GenerationValidationError("complete generation cannot contain failures")
    reasons = {reason for _, reason in failures}
    if not reasons.issubset(generation.coverage.limitations):
        raise GenerationValidationError("coverage limitations must include every failure reason")
