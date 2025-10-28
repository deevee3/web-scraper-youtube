"""FastAPI application exposing the scraper UI and API."""

from __future__ import annotations

import csv
import secrets
import uuid
from pathlib import Path
from typing import List, Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates

from config import Settings, load_settings

from .run_manager import RunManager, configure_manager
from .storage import RunStore, RunStatus

TEMPLATE_DIR = Path(__file__).parent / "templates"
UPLOAD_DIR_NAME = "ui_uploads"


security = HTTPBasic(auto_error=False)


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    settings = settings or load_settings()
    templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

    def store_factory(db_path: Path) -> RunStore:
        return RunStore(db_path)

    manager = configure_manager(settings, store_factory)

    app = FastAPI(title="Cafe24 Scraper UI", version="0.1.0")
    app.state.settings = settings
    app.state.manager = manager
    app.state.templates = templates

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        manager.shutdown()

    def get_settings() -> Settings:
        return settings

    def get_manager() -> RunManager:
        return manager

    def get_store() -> RunStore:
        return manager.store

    def _authenticate(
        credentials: Optional[HTTPBasicCredentials] = Depends(security),
        settings: Settings = Depends(get_settings),
    ) -> Optional[HTTPBasicCredentials]:
        username = settings.ui_basic_auth_username
        password = settings.ui_basic_auth_password
        if not username or not password:
            return None
        if credentials is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
        if not secrets.compare_digest(credentials.username, username) or not secrets.compare_digest(
            credentials.password, password
        ):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
        return credentials

    def require_auth(credentials: Optional[HTTPBasicCredentials] = Depends(_authenticate)) -> None:
        return None

    @app.get("/healthz", response_class=JSONResponse)
    async def healthcheck() -> dict:
        return {"status": "ok"}

    @app.get("/", response_class=HTMLResponse)
    async def index(
        request: Request,
        settings: Settings = Depends(get_settings),
        store: RunStore = Depends(get_store),
        auth=Depends(require_auth),
    ) -> HTMLResponse:
        runs = list(store.list_runs())
        default_input = settings.input_urls_path
        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "runs": runs,
                "default_input": default_input,
            },
        )

    @app.post("/runs", response_class=RedirectResponse)
    async def create_run(
        request: Request,
        use_default: str = Form("default"),
        upload: Optional[UploadFile] = File(None),
        manager: RunManager = Depends(get_manager),
        settings: Settings = Depends(get_settings),
        auth=Depends(require_auth),
    ) -> RedirectResponse:
        if use_default not in {"default", "upload"}:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid input selection")

        source = "default"
        input_path = settings.input_urls_path

        if use_default == "upload":
            if upload is None or upload.filename is None:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="CSV upload required")
            if not upload.filename.lower().endswith(".csv"):
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only CSV uploads supported")
            upload_dir = settings.output_root / UPLOAD_DIR_NAME
            upload_dir.mkdir(parents=True, exist_ok=True)
            dest_name = f"{uuid.uuid4().hex}_{upload.filename}"
            dest_path = upload_dir / dest_name
            contents = await upload.read()
            dest_path.write_bytes(contents)
            input_path = dest_path
            source = "upload"

        run_id = await manager.enqueue_run(input_path=input_path, source=source)
        return RedirectResponse(url=f"/?triggered={run_id}", status_code=status.HTTP_303_SEE_OTHER)

    @app.get("/runs", response_class=JSONResponse)
    async def list_runs(store: RunStore = Depends(get_store), auth=Depends(require_auth)) -> list[dict]:
        return [run.to_dict() for run in store.list_runs()]

    @app.get("/runs/{run_id}", response_class=JSONResponse)
    async def get_run(run_id: str, store: RunStore = Depends(get_store), auth=Depends(require_auth)) -> dict:
        record = store.get_run(run_id)
        if not record:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
        return record.to_dict()

    @app.get("/runs/{run_id}/download")
    async def download_run(run_id: str, store: RunStore = Depends(get_store), auth=Depends(require_auth)):
        record = store.get_run(run_id)
        if not record:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
        if record.status != RunStatus.SUCCEEDED or not record.archive_path:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Run archive unavailable")
        archive_path = Path(record.archive_path)
        if not archive_path.exists():
            raise HTTPException(status_code=status.HTTP_410_GONE, detail="Archive no longer exists")
        return FileResponse(archive_path, filename=archive_path.name)

    @app.get("/runs/{run_id}/preview", response_class=JSONResponse)
    async def preview_run(
        run_id: str,
        limit: int = 3,
        store: RunStore = Depends(get_store),
        auth=Depends(require_auth),
    ) -> dict:
        if limit <= 0:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Limit must be positive")

        record = store.get_run(run_id)
        if not record:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
        if record.status != RunStatus.SUCCEEDED or not record.csv_path:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Run results unavailable")

        csv_path = Path(record.csv_path)
        if not csv_path.exists():
            raise HTTPException(status_code=status.HTTP_410_GONE, detail="Run CSV no longer exists")

        previews = _load_preview_rows(csv_path, limit)
        return {"run_id": run_id, "records": previews, "total": len(previews)}

    @app.get("/runs/{run_id}/log")
    async def download_log(run_id: str, store: RunStore = Depends(get_store), auth=Depends(require_auth)):
        record = store.get_run(run_id)
        if not record:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
        if not record.log_path:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Log unavailable")
        log_path = Path(record.log_path)
        if not log_path.exists():
            raise HTTPException(status_code=status.HTTP_410_GONE, detail="Log file removed")
        return FileResponse(log_path, filename=log_path.name, media_type="text/plain")

    return app


app = create_app()


def _load_preview_rows(csv_path: Path, limit: int) -> List[dict]:
    previews: List[dict] = []
    seen_handles: set[str] = set()
    with csv_path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            handle = row.get("Handle") or ""
            if handle in seen_handles:
                continue
            previews.append(
                {
                    "handle": handle,
                    "title": row.get("Title") or "",
                    "body_html": row.get("Body (HTML)") or "",
                }
            )
            seen_handles.add(handle)
            if len(previews) >= limit:
                break
    return previews
