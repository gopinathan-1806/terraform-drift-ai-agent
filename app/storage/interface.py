"""
Storage interface — Phase 8 implementation.

Defines the abstract interface for drift state persistence.
Allows the backend to be swapped (local → Redis/PostgreSQL) without
changing upstream code.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from app.drift.models import DriftEvent


class DriftStoreInterface(ABC):
    """Abstract interface for drift event persistence."""

    @abstractmethod
    def get_event(self, fingerprint: str) -> DriftEvent | None:
        """Retrieve a drift event by fingerprint. Returns None if not found."""

    @abstractmethod
    def save_event(self, event: DriftEvent) -> None:
        """Persist or update a drift event."""

    @abstractmethod
    def list_events(self) -> list[DriftEvent]:
        """Return all stored drift events."""

    @abstractmethod
    def delete_event(self, fingerprint: str) -> None:
        """Remove a drift event by fingerprint."""
