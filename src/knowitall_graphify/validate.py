from .normalize import GenerationValidationError, GraphGeneration


def validate_generation(generation: GraphGeneration) -> None:
    """Recheck invariants needed before a normalized generation is publishable."""
    node_ids = {node.symbol_id for node in generation.nodes}
    if any(edge.source not in node_ids or edge.target not in node_ids for edge in generation.edges):
        raise GenerationValidationError("dangling edge endpoint")
    if generation.state == "complete" and generation.failed_files:
        raise GenerationValidationError("complete generation cannot contain failed files")
