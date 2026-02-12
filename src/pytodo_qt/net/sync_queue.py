"""sync_queue.py

Client-side operation queue for managing sync operations sequentially.
"""

from __future__ import annotations

import asyncio
import contextlib
import random
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from PyQt6.QtCore import QObject, pyqtSignal

from ..core.logger import Logger

if TYPE_CHECKING:
    from .client import AsyncClient


logger = Logger(__name__)


class SyncOperationType(Enum):
    """Types of sync operations."""

    PUSH = "push"
    PULL = "pull"


class SyncStatus(Enum):
    """Status of a sync operation."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    FAILED = "failed"
    BUSY_RETRY = "busy_retry"
    CONNECTION_RETRY = "connection_retry"
    CANCELLED = "cancelled"


@dataclass
class SyncResult:
    """Result of a sync operation."""

    success: bool
    data: bytes = b""
    error: str = ""
    status: SyncStatus = SyncStatus.SUCCESS
    retry_after: int = 0  # Seconds to wait before retry (if busy)
    current_peer: str = ""  # Peer that server is busy with


@dataclass
class SyncOperation:
    """A queued sync operation."""

    id: UUID = field(default_factory=uuid4)
    operation_type: SyncOperationType = SyncOperationType.PULL
    host: str = ""
    port: int = 5364
    data: bytes = b""  # For push operations
    device_id: UUID | None = None  # Associated device (optional)
    list_ids: list[UUID] = field(default_factory=list)  # Specific lists (optional)
    max_retries: int = 3
    retry_count: int = 0
    status: SyncStatus = SyncStatus.PENDING
    result: SyncResult | None = None

    def can_retry(self) -> bool:
        """Check if operation can be retried."""
        return self.retry_count < self.max_retries


class SyncQueue(QObject):
    """Manages outgoing sync operations sequentially.

    Ensures only one sync operation runs at a time on the client side.
    Handles server busy responses with automatic retry.
    """

    # Signals
    operation_started = pyqtSignal(str)  # operation_id
    operation_completed = pyqtSignal(str, bool)  # operation_id, success
    operation_progress = pyqtSignal(str, str)  # operation_id, message
    queue_empty = pyqtSignal()

    def __init__(self, client: AsyncClient, parent: QObject | None = None):
        super().__init__(parent)
        self._client = client
        self._queue: asyncio.Queue[SyncOperation] = asyncio.Queue()
        self._current: SyncOperation | None = None
        self._results: dict[str, SyncResult] = {}
        self._running = False
        self._process_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Start processing the queue."""
        if self._running:
            return
        self._running = True
        self._process_task = asyncio.create_task(self._process_loop())
        logger.log.info("SyncQueue started")

    async def stop(self) -> None:
        """Stop processing the queue."""
        self._running = False
        if self._process_task:
            self._process_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._process_task
            self._process_task = None
        logger.log.info("SyncQueue stopped")

    async def enqueue(self, operation: SyncOperation) -> str:
        """Add operation to queue, return operation ID."""
        await self._queue.put(operation)
        logger.log.debug(
            "Enqueued %s operation to %s:%d (id=%s)",
            operation.operation_type.value,
            operation.host,
            operation.port,
            operation.id,
        )
        return str(operation.id)

    def enqueue_sync(self, operation: SyncOperation) -> str:
        """Synchronously add operation to queue (for non-async callers)."""
        # Use asyncio.create_task if there's a running loop
        try:
            loop = asyncio.get_running_loop()
            asyncio.ensure_future(self._queue.put(operation), loop=loop)
        except RuntimeError:
            # No running loop, need to handle differently
            # This shouldn't happen in normal Qt usage with qasync
            logger.log.warning("No running event loop for enqueue_sync")
        return str(operation.id)

    def get_result(self, operation_id: str) -> SyncResult | None:
        """Get the result of a completed operation."""
        return self._results.get(operation_id)

    def get_current_operation(self) -> SyncOperation | None:
        """Get the currently running operation."""
        return self._current

    def get_queue_size(self) -> int:
        """Get number of pending operations."""
        return self._queue.qsize()

    def is_busy(self) -> bool:
        """Check if a sync is in progress."""
        return self._current is not None

    async def _process_loop(self) -> None:
        """Main processing loop."""
        while self._running:
            try:
                # Wait for next operation
                operation = await self._queue.get()
                self._current = operation
                operation.status = SyncStatus.IN_PROGRESS

                self.operation_started.emit(str(operation.id))
                self.operation_progress.emit(
                    str(operation.id),
                    f"{operation.operation_type.value.title()}ing {operation.host}:{operation.port}...",
                )

                result: SyncResult | None = None
                try:
                    result = await self._execute_with_retry(operation)
                    self._results[str(operation.id)] = result
                    operation.result = result
                    operation.status = result.status

                    self.operation_completed.emit(str(operation.id), result.success)
                except Exception as e:
                    logger.log.exception("Error executing operation %s: %s", operation.id, e)
                    result = SyncResult(success=False, error=str(e), status=SyncStatus.FAILED)
                    self._results[str(operation.id)] = result
                    operation.result = result
                    operation.status = SyncStatus.FAILED
                    self.operation_completed.emit(str(operation.id), False)
                finally:
                    # Resolve future if caller is awaiting execute()
                    future = getattr(operation, "_future", None)
                    if future is not None and not future.done():
                        future.set_result(result)
                    self._current = None
                    self._queue.task_done()

                # Check if queue is empty
                if self._queue.empty():
                    self.queue_empty.emit()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.log.exception("Error in SyncQueue process loop: %s", e)

    async def _execute_with_retry(self, operation: SyncOperation) -> SyncResult:
        """Execute operation with retry on busy or connection error."""
        while True:
            result = await self._execute_operation(operation)

            # Check if server was busy and we can retry
            if result.status == SyncStatus.BUSY_RETRY and operation.can_retry():
                operation.retry_count += 1
                base_wait = result.retry_after or 5
                # Add jitter: 0.5x-1.5x of base wait time
                jitter = 0.5 + random.random()  # noqa: S311
                wait_time = base_wait * jitter

                logger.log.info(
                    "Server busy (with %s), retrying in %.1fs (attempt %d/%d)",
                    result.current_peer,
                    wait_time,
                    operation.retry_count,
                    operation.max_retries,
                )

                self.operation_progress.emit(
                    str(operation.id),
                    f"Server busy, retrying in {wait_time:.0f}s...",
                )

                await asyncio.sleep(wait_time)
                continue

            # Check if connection failed and we can retry
            if result.status == SyncStatus.CONNECTION_RETRY and operation.can_retry():
                operation.retry_count += 1
                # Exponential backoff: 2^retry_count seconds, with 0.5x-1.5x jitter
                base_wait = 2**operation.retry_count
                jitter = 0.5 + random.random()  # noqa: S311
                wait_time = base_wait * jitter

                logger.log.info(
                    "Connection failed to %s:%d, retrying in %.1fs (attempt %d/%d)",
                    operation.host,
                    operation.port,
                    wait_time,
                    operation.retry_count,
                    operation.max_retries,
                )

                self.operation_progress.emit(
                    str(operation.id),
                    f"Connection failed, retrying in {wait_time:.0f}s...",
                )

                await asyncio.sleep(wait_time)
                continue

            return result

    async def execute(self, operation: SyncOperation) -> SyncResult:
        """Enqueue operation and await its result."""
        future: asyncio.Future[SyncResult] = asyncio.get_running_loop().create_future()
        operation._future = future  # type: ignore[attr-defined]
        await self._queue.put(operation)
        return await future

    async def _execute_operation(self, operation: SyncOperation) -> SyncResult:
        """Execute a single sync operation."""
        try:
            if operation.operation_type == SyncOperationType.PULL:
                success, data = await self._client.sync_pull(operation.host, operation.port)
                if success:
                    return SyncResult(success=True, data=data, status=SyncStatus.SUCCESS)
                busy = self._client.get_last_busy_response()
                if busy:
                    self._client._last_busy_response = None
                    return SyncResult(
                        success=False,
                        error="Server busy",
                        status=SyncStatus.BUSY_RETRY,
                        retry_after=busy.retry_after,
                        current_peer=busy.current_peer,
                    )
                if self._client.had_connection_error():
                    return SyncResult(
                        success=False,
                        error="Connection failed",
                        status=SyncStatus.CONNECTION_RETRY,
                    )
                return SyncResult(success=False, error="Pull failed", status=SyncStatus.FAILED)

            elif operation.operation_type == SyncOperationType.PUSH:
                success = await self._client.sync_push(
                    operation.host, operation.port, operation.data
                )
                if success:
                    return SyncResult(success=True, status=SyncStatus.SUCCESS)
                busy = self._client.get_last_busy_response()
                if busy:
                    self._client._last_busy_response = None
                    return SyncResult(
                        success=False,
                        error="Server busy",
                        status=SyncStatus.BUSY_RETRY,
                        retry_after=busy.retry_after,
                        current_peer=busy.current_peer,
                    )
                if self._client.had_connection_error():
                    return SyncResult(
                        success=False,
                        error="Connection failed",
                        status=SyncStatus.CONNECTION_RETRY,
                    )
                return SyncResult(success=False, error="Push failed", status=SyncStatus.FAILED)

            else:
                return SyncResult(
                    success=False,
                    error=f"Unknown operation type: {operation.operation_type}",
                    status=SyncStatus.FAILED,
                )

        except Exception as e:
            logger.log.exception("Operation execution error: %s", e)
            return SyncResult(success=False, error=str(e), status=SyncStatus.FAILED)


def create_push_operation(
    host: str,
    port: int,
    data: bytes,
    device_id: UUID | None = None,
    list_ids: list[UUID] | None = None,
) -> SyncOperation:
    """Create a push sync operation."""
    return SyncOperation(
        operation_type=SyncOperationType.PUSH,
        host=host,
        port=port,
        data=data,
        device_id=device_id,
        list_ids=list_ids or [],
    )


def create_pull_operation(
    host: str,
    port: int,
    device_id: UUID | None = None,
    list_ids: list[UUID] | None = None,
) -> SyncOperation:
    """Create a pull sync operation."""
    return SyncOperation(
        operation_type=SyncOperationType.PULL,
        host=host,
        port=port,
        device_id=device_id,
        list_ids=list_ids or [],
    )
