from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
import pytest_asyncio

from api.run_manager import RunManager
from api.storage import RunStatus
from config import Settings
from scraper.pipeline import PipelineResult, PipelineSettings


class DummyResult:
    def __init__(self, csv_path: Path) -> None:
        self.csv_path = csv_path
        self.summary_path = csv_path.with_name("run_summary.json")
        self.images_zip = csv_path.with_name("images.zip")
        self.screenshots_zip = None


@pytest_asyncio.fixture
async def run_manager(tmp_path: Path) -> RunManager:
    settings = Settings(input_urls_path=tmp_path / "urls.csv")
    settings.output_root = tmp_path / "output"
    settings.logs_root = tmp_path / "logs"
    settings.templates_root = tmp_path / "templates"
    settings.output_root.mkdir()
    settings.logs_root.mkdir()
    settings.templates_root.mkdir()

    def store_factory(path: Path):
        store = MagicMock()
        store.initialize = MagicMock()
        store.create_run = MagicMock()
        store.mark_running = MagicMock()
        store.mark_succeeded = MagicMock()
        store.mark_failed = MagicMock()
        store.list_runs = MagicMock(return_value=[])
        store.get_run = MagicMock(return_value=None)
        return store

    manager = RunManager(settings=settings, store=store_factory(settings.ui_database_path))

    async def fake_run_background(*args, **kwargs):
        return None

    manager._run_background = fake_run_background  # type: ignore
    yield manager
    manager.shutdown()


@pytest.mark.asyncio
async def test_enqueue_run_missing_file(tmp_path: Path, run_manager: RunManager) -> None:
    missing_path = tmp_path / "missing.csv"
    with pytest.raises(FileNotFoundError):
        await run_manager.enqueue_run(input_path=missing_path, source="upload")


@pytest.mark.asyncio
async def test_enqueue_run_calls_store(tmp_path: Path, run_manager: RunManager) -> None:
    input_file = tmp_path / "urls.csv"
    input_file.write_text("url\nhttps://example.com")
    await run_manager.enqueue_run(input_path=input_file, source="upload")
    run_manager.store.create_run.assert_called_once()
