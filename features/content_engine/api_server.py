import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from uuid import uuid4

from aiohttp import web

from database import DB_PATH

from . import resource_processor, storage

logger = logging.getLogger(__name__)

API_BASE = "/api/content-engine/v1"
ALLOWED_EXTENSIONS = {".pdf", ".txt", ".md", ".csv"}


def _json(data: Dict[str, Any], status: int = 200, request: Optional[web.Request] = None) -> web.Response:
    response = web.json_response(data, status=status)
    if request is not None:
        _apply_cors(request, response)
    return response


def _max_resource_bytes() -> int:
    try:
        max_mb = int(os.getenv("CONTENT_RESOURCE_MAX_MB", "300"))
    except ValueError:
        max_mb = 300
    return max(1, max_mb) * 1024 * 1024


def _resource_dir() -> Path:
    base = os.getenv("CONTENT_RESOURCE_DIR")
    if base:
        path = Path(base)
    else:
        db_dir = Path(DB_PATH).parent if DB_PATH else Path(".")
        path = db_dir / "content_resources"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_file_name(name: str) -> str:
    safe = (name or "").strip().replace("\\", "_").replace("/", "_")
    safe = "".join(ch if ch.isalnum() or ch in "._- ()" else "_" for ch in safe)
    return safe.strip("._ ") or f"resource_{uuid4().hex}"


def _iso_ts(value: Any) -> Optional[str]:
    try:
        if value is None:
            return None
        return datetime.fromtimestamp(int(value), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return None


def _api_key() -> str:
    return os.getenv("CONTENT_ENGINE_API_KEY", "").strip()


def _allowed_origins() -> set[str]:
    raw = os.getenv("CONTENT_ENGINE_ALLOWED_ORIGINS", "").strip()
    if not raw:
        return set()
    return {part.strip() for part in raw.split(",") if part.strip()}


def _apply_cors(request: web.Request, response: web.Response) -> None:
    origin = request.headers.get("Origin", "")
    allowed = _allowed_origins()
    if origin and origin in allowed:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"
        response.headers["Access-Control-Allow-Headers"] = "Authorization, X-Content-Engine-Key, Content-Type"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"


def _authorized(request: web.Request) -> tuple[bool, Optional[web.Response]]:
    expected = _api_key()
    if not expected:
        logger.warning("CONTENT_ENGINE_API_KEY is not configured; rejecting content API request")
        return False, _json(
            {"ok": False, "error": "api_key_not_configured"},
            status=503,
            request=request,
        )

    auth = request.headers.get("Authorization", "")
    bearer = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    header_key = request.headers.get("X-Content-Engine-Key", "").strip()
    if bearer == expected or header_key == expected:
        return True, None
    return False, _json({"ok": False, "error": "unauthorized"}, status=401, request=request)


@web.middleware
async def cors_options_middleware(request: web.Request, handler):
    if request.method == "OPTIONS":
        return _json({"ok": True}, request=request)
    try:
        response = await handler(request)
    except web.HTTPRequestEntityTooLarge:
        return _json(
            {"ok": False, "error": "file_too_large", "max_mb": _max_resource_bytes() // 1024 // 1024},
            status=413,
            request=request,
        )
    _apply_cors(request, response)
    return response


def _resource_payload(row: Dict[str, Any]) -> Dict[str, Any]:
    resource_id = int(row["id"])
    return {
        "id": resource_id,
        "title": row.get("title"),
        "file_name": row.get("file_name"),
        "category": row.get("category"),
        "source_type": row.get("source_type") or "",
        "status": row.get("status") or "uploaded",
        "idea_count": storage.count_resource_ideas(resource_id),
        "processing_error": row.get("processing_error"),
        "created_at": _iso_ts(row.get("created_at")),
        "processed_at": _iso_ts(row.get("processed_at")),
    }


async def health(request: web.Request) -> web.Response:
    return _json({"ok": True, "service": "content-engine", "version": 1}, request=request)


async def list_resources(request: web.Request) -> web.Response:
    ok, error = _authorized(request)
    if not ok:
        return error
    rows = storage.list_resources_with_idea_counts(200)
    response = web.json_response([_resource_payload(row) for row in rows])
    _apply_cors(request, response)
    return response


async def get_resource(request: web.Request) -> web.Response:
    ok, error = _authorized(request)
    if not ok:
        return error
    try:
        resource_id = int(request.match_info["resource_id"])
    except (KeyError, ValueError):
        return _json({"ok": False, "error": "invalid_resource_id"}, status=400, request=request)
    row = storage.get_resource(resource_id)
    if not row:
        return _json({"ok": False, "error": "not_found"}, status=404, request=request)
    payload = _resource_payload(row)
    payload["local_path_exists"] = bool(row.get("local_path") and Path(str(row["local_path"])).exists())
    return _json(payload, request=request)


async def retry_resource(request: web.Request) -> web.Response:
    ok, error = _authorized(request)
    if not ok:
        return error
    try:
        resource_id = int(request.match_info["resource_id"])
    except (KeyError, ValueError):
        return _json({"ok": False, "error": "invalid_resource_id"}, status=400, request=request)
    row = storage.get_resource(resource_id)
    if not row:
        return _json({"ok": False, "error": "not_found"}, status=404, request=request)

    status = str(row.get("status") or "uploaded").lower()
    if status == "ready":
        return _json({"ok": True, "resource_id": resource_id, "status": status, "message": "Resource is already ready."}, request=request)
    if status == "processing":
        return _json({"ok": True, "resource_id": resource_id, "status": status, "message": "Resource is already processing."}, request=request)
    if status == "failed":
        if not storage.reset_failed_resource(resource_id):
            return _json({"ok": False, "error": "retry_failed"}, status=500, request=request)
    if not row.get("local_path") or not Path(str(row["local_path"])).exists():
        return _json({"ok": False, "error": "local_file_missing"}, status=400, request=request)

    resource_processor.start_processing(resource_id)
    return _json(
        {
            "ok": True,
            "resource_id": resource_id,
            "status": "uploaded",
            "message": "Resource retry started in background.",
        },
        request=request,
    )


async def upload_resource(request: web.Request) -> web.Response:
    ok, error = _authorized(request)
    if not ok:
        return error

    max_bytes = _max_resource_bytes()
    try:
        reader = await request.multipart()
    except Exception:
        return _json({"ok": False, "error": "invalid_multipart"}, status=400, request=request)

    fields: Dict[str, str] = {}
    uploaded_path: Optional[Path] = None
    safe_name = ""
    mime_type = ""
    downloaded = 0

    try:
        async for part in reader:
            if part.name == "file":
                original_name = part.filename or f"resource_{uuid4().hex}"
                safe_name = _safe_file_name(original_name)
                ext = Path(safe_name).suffix.lower()
                if ext not in ALLOWED_EXTENSIONS:
                    return _json({"ok": False, "error": "unsupported_file_type"}, status=400, request=request)

                mime_type = (part.headers.get("Content-Type") or "").split(";", 1)[0].strip()
                uploaded_path = _resource_dir() / f"api_{uuid4().hex}_{safe_name}"
                tmp_path = uploaded_path.with_suffix(uploaded_path.suffix + ".tmp")
                with tmp_path.open("wb") as handle:
                    while True:
                        chunk = await part.read_chunk(size=1024 * 1024)
                        if not chunk:
                            break
                        downloaded += len(chunk)
                        if downloaded > max_bytes:
                            handle.close()
                            tmp_path.unlink(missing_ok=True)
                            return _json(
                                {"ok": False, "error": "file_too_large", "max_mb": max_bytes // 1024 // 1024},
                                status=413,
                                request=request,
                            )
                        handle.write(chunk)
                tmp_path.replace(uploaded_path)
            else:
                value = await part.text()
                fields[part.name] = value.strip()
    except web.HTTPException:
        raise
    except Exception:
        logger.exception("Content API upload failed while reading request")
        if uploaded_path:
            uploaded_path.unlink(missing_ok=True)
        return _json({"ok": False, "error": "upload_failed"}, status=500, request=request)

    if not uploaded_path:
        return _json({"ok": False, "error": "missing_file"}, status=400, request=request)

    title = fields.get("title") or safe_name
    category = fields.get("category") or ""
    source_type = fields.get("source_type") or "api_upload"
    resource_id = storage.add_resource(
        title=title,
        category=category,
        file_id="",
        file_unique_id=f"api_{uuid4().hex}",
        file_name=safe_name,
        mime_type=mime_type,
        local_path=str(uploaded_path),
        extracted_text="",
        source_type=source_type,
    )
    if not resource_id:
        uploaded_path.unlink(missing_ok=True)
        return _json({"ok": False, "error": "resource_create_failed"}, status=500, request=request)

    resource_processor.start_processing(int(resource_id))
    return _json(
        {
            "ok": True,
            "resource_id": int(resource_id),
            "status": "uploaded",
            "message": "Resource uploaded. Processing started in background.",
        },
        request=request,
    )


async def start_api_server() -> web.AppRunner:
    max_bytes = _max_resource_bytes()
    app = web.Application(
        middlewares=[cors_options_middleware],
        client_max_size=max_bytes + 20 * 1024 * 1024,
    )
    app.router.add_get(f"{API_BASE}/health", health)
    app.router.add_get(f"{API_BASE}/resources", list_resources)
    app.router.add_get(f"{API_BASE}/resources/{{resource_id:\\d+}}", get_resource)
    app.router.add_post(f"{API_BASE}/resources/upload", upload_resource)
    app.router.add_post(f"{API_BASE}/resources/{{resource_id:\\d+}}/retry", retry_resource)

    runner = web.AppRunner(app)
    await runner.setup()
    host = os.getenv("CONTENT_ENGINE_API_HOST", "0.0.0.0")
    port = int(os.getenv("PORT", os.getenv("CONTENT_ENGINE_API_PORT", "8080")))
    site = web.TCPSite(runner, host=host, port=port)
    await site.start()
    if not _api_key():
        logger.warning("Content Engine API started without CONTENT_ENGINE_API_KEY; protected endpoints return 503")
    logger.info("Content Engine API listening on %s:%s", host, port)
    return runner
