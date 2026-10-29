import json
from collections.abc import Mapping
from typing import TextIO

from .service import QueryService
from .status import empty_response


def serve_stdio(service: QueryService, input_stream: TextIO, output_stream: TextIO) -> None:
    """Exchange one v1 JSON response for each newline-delimited local request."""
    for line in input_stream:
        try:
            request = json.loads(line)
        except (json.JSONDecodeError, UnicodeError):
            request = {}
        response = service.execute(request) if isinstance(request, Mapping) else empty_response({}, "invalid_request")
        output_stream.write(json.dumps(response, sort_keys=True, separators=(",", ":")) + "\n")
        output_stream.flush()
