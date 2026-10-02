"""
Local filesystem drift state store.

Persists drift events as individual JSON files on disk.
Each event is stored as: <state_dir>/<fingerprint>.json

This is the MVP storage backend. The interface is designed so it can
be replaced with Redis or PostgreSQL without changing upstream code.
"""
from __future__ import annotations

import json
from pathlib import Path

from app.config.logging import get_logger
from app.config.settings import get_settings
from app.drift.models import DriftEvent
from app.storage.interface import DriftStoreInterface

logger = get_logger("storage.local")
settings = get_settings()


class LocalDriftStore(DriftStoreInterface):
    """
    Persists drift events as JSON files in a local directory.

    Directory structure:
        .driftguard/state/<fingerprint>.json

    Thread safety: not guaranteed. Single-process local use only.
    For multi-process or concurrent access, replace with Redis/PostgreSQL.
    """

    def __init__(self, state_dir: str | None = None) -> None:
        self._state_dir = Path(state_dir or settings.drift_state_dir)
        self._ensure_dir()

    def _ensure_dir(self) -> None:
        """Create the state directory if it does not exist."""
        self._state_dir.mkdir(parents=True, exist_ok=True)

    def _event_path(self, fingerprint: str) -> Path:
        """Return the path to the JSON file for a given fingerprint."""
        # Sanitize fingerprint — only hex characters allowed (SHA-256 output)
        if not all(c in "0123456789abcdef" for c in fingerprint):
            raise ValueError(f"Invalid fingerprint format: {fingerprint!r}")
        return self._state_dir / f"{fingerprint}.json"

    def get_event(self, fingerprint: str) -> DriftEvent | None:
        """Retrieve a drift event by fingerprint. Returns None if not found."""
        path = self._event_path(fingerprint)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return DriftEvent.model_validate(data)
        except (json.JSONDecodeError, Exception) as exc:  # noqa: BLE001
            logger.error(
                "Failed to read drift event file",
                path=str(path),
                error=str(exc),
            )
            return None

    def save_event(self, event: DriftEvent) -> None:
        """Persist or update a drift event."""
        path = self._event_path(event.fingerprint)
        try:
            path.write_text(
                event.model_dump_json(indent=2),
                encoding="utf-8",
            )
            logger.debug("Drift event saved", fingerprint=event.fingerprint, status=event.status.value)
        except OSError as exc:
            logger.error(
                "Failed to save drift event",
                fingerprint=event.fingerprint,
                error=str(exc),
            )
            raise

    def list_events(self) -> list[DriftEvent]:
        """Return all stored drift events, sorted by first_detected_at descending."""
        events: list[DriftEvent] = []
        for path in self._state_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                events.append(DriftEvent.model_validate(data))
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Skipping unreadable drift event file",
                    path=str(path),
                    error=str(exc),
                )
        events.sort(key=lambda e: e.first_detected_at, reverse=True)
        return events

    def delete_event(self, fingerprint: str) -> None:
        """Remove a drift event by fingerprint."""
        path = self._event_path(fingerprint)
        if path.exists():
            path.unlink()
            logger.debug("Drift event deleted", fingerprint=fingerprint)
