import base64
import hashlib
import hmac
import json
from collections.abc import Mapping


class InvalidContinuation(ValueError):
    pass


def _binding(request: Mapping[str, object], generation_id: str, page_size: int) -> str:
    value = {key: request[key] for key in ("contract", "request_id", "project_id", "repository_id", "selector", "query")}
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256((canonical + "\0" + generation_id + "\0" + str(page_size)).encode()).hexdigest()


def issue_token(request: Mapping[str, object], generation_id: str, page_size: int, offset: int, secret: bytes) -> str:
    payload = json.dumps({"binding": _binding(request, generation_id, page_size), "offset": offset}, sort_keys=True, separators=(",", ":")).encode()
    signature = hmac.new(secret, payload, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(payload + signature).rstrip(b"=").decode()


def read_token(token: str, request: Mapping[str, object], generation_id: str, page_size: int, secret: bytes) -> int:
    try:
        data = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
        canonical = base64.urlsafe_b64encode(data).rstrip(b"=").decode()
        if not hmac.compare_digest(token, canonical):
            raise InvalidContinuation("noncanonical continuation encoding")
        payload, signature = data[:-32], data[-32:]
        if not hmac.compare_digest(signature, hmac.new(secret, payload, hashlib.sha256).digest()):
            raise InvalidContinuation("continuation signature mismatch")
        value = json.loads(payload)
        if value["binding"] != _binding(request, generation_id, page_size):
            raise InvalidContinuation("continuation binding mismatch")
        offset = value["offset"]
        if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
            raise InvalidContinuation("continuation offset is invalid")
        return offset
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        if isinstance(error, InvalidContinuation):
            raise
        raise InvalidContinuation("malformed continuation") from error
