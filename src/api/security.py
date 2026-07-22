from __future__ import annotations

from fastapi import HTTPException, Request


LOCAL_HOSTS = {"localhost", "127.0.0.1", "[::1]"}
MAX_REQUEST_BYTES = 5 * 1024 * 1024


def enforce_state_change_boundary(request: Request) -> None:
    host = request.headers.get("host", "").split(":", 1)[0]
    if host and host not in LOCAL_HOSTS:
        raise HTTPException(status_code=400, detail="local host required")
    origin = request.headers.get("origin")
    if origin is not None and not any(origin.startswith(f"http://{host}") for host in LOCAL_HOSTS):
        raise HTTPException(status_code=403, detail="cross-origin requests are not allowed")
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(status_code=403, detail="cross-site requests are not allowed")
    content_type = request.headers.get("content-type", "")
    if request.method in {"POST", "PUT", "PATCH"} and "application/json" not in content_type:
        raise HTTPException(status_code=415, detail="application/json required")
    content_length = request.headers.get("content-length")
    if content_length is not None and int(content_length) > MAX_REQUEST_BYTES:
        raise HTTPException(status_code=413, detail="request body exceeds 5 MiB")
