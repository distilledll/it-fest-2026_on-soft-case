"""HTTP-вызовы TrustQA используют тот же пул и очередь, что и агент."""
import atexit
from contextlib import ExitStack
from threading import Lock

import httpx
from anyio.from_thread import start_blocking_portal
from openai import APIConnectionError, APITimeoutError, InternalServerError, RateLimitError

from app import llm


class ServiceUnavailable(RuntimeError):
    pass


async def post_json(base, endpoint, key, payload, timeout, auth_header="Authorization", *, profiles=None):
    if auth_header not in ("Authorization", "X-API-Key"):
        raise ValueError("Unsupported API authentication header")
    profile = (profiles or {}).get(endpoint)
    headers = {"User-Agent": "trustqa/0.1"}
    if key:
        headers[auth_header] = f"Bearer {key}" if auth_header == "Authorization" else key
    if profile:
        headers.update(profile.headers())
        if endpoint == "chat/completions":
            payload = {**profile.body(), **payload}
            if not profile.json_mode:
                payload.pop("response_format", None)

    async def send():
        try:
            response = await llm.http_client().post(base.rstrip("/") + "/" + endpoint, json=payload,
                                                    headers=headers, timeout=timeout)
        except httpx.TimeoutException as exc:
            raise APITimeoutError(request=exc.request) from None
        except httpx.RequestError as exc:
            raise APIConnectionError(request=exc.request) from None
        status = response.status_code
        if status == 429:
            hint = llm.RETRY_AFTER_RE.search(response.text[:2000])
            message = f"HTTP 429; retry after {hint[1]} s" if hint else "HTTP 429"
            raise RateLimitError(message, response=response, body=None)
        if 500 <= status < 600:
            raise InternalServerError(f"HTTP {status}", response=response, body=None)
        if not response.is_success:
            raise ServiceUnavailable(f"{endpoint}: HTTP {status}")
        try:
            body = response.json()
        except ValueError:
            raise ServiceUnavailable(f"{endpoint}: invalid JSON") from None
        if not isinstance(body, dict):
            raise ServiceUnavailable(f"{endpoint}: invalid response")
        return body

    try:
        return await llm.call(send, profile=profile)
    except llm.RETRYABLE as exc:
        raise ServiceUnavailable(f"{endpoint}: {type(exc).__name__}") from None


# Синхронный CLI запускает вопросы в нескольких потоках. Все используют один event loop.
# Гибрид передаёт собственный portal основного event loop приложения.
_cli_stack = ExitStack()
_cli_lock = Lock()
_cli_portal = None
atexit.register(_cli_stack.close)


def post(*args):
    global _cli_portal
    with _cli_lock:
        if _cli_portal is None:
            _cli_portal = _cli_stack.enter_context(start_blocking_portal())
            _cli_stack.callback(_cli_portal.call, llm.close_clients)
    return _cli_portal.call(post_json, *args)
