"""
Interview Coach - Persist Queue
Durable queue for database writes with retry and drop-oldest policy
"""
import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Any, Callable
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class QueueItemStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    DROPPED = "dropped"


@dataclass
class QueueItem:
    """An item in the persistence queue"""
    id: str
    data: dict
    created_at: datetime = field(default_factory=datetime.utcnow)
    attempts: int = 0
    max_attempts: int = 3
    status: QueueItemStatus = QueueItemStatus.PENDING
    last_error: Optional[str] = None
    last_attempt_at: Optional[datetime] = None


class PersistQueue:
    """
    Durable queue for database writes.
    
    Features:
    - Retry with exponential backoff (max 3 attempts)
    - Drop-oldest policy when queue is full (>100 items)
    - Logs dropped items for manual recovery
    
    Trade-off (V1): Under extreme pressure, oldest items are dropped.
    This is acceptable because:
    1. The live interview is not blocked
    2. Dropped items are logged for recovery
    3. In normal conditions, queue never fills
    """
    
    def __init__(
        self,
        max_size: int = 100,
        max_attempts: int = 3,
        backoff_base_ms: int = 100,
    ):
        self._queue: list[QueueItem] = []
        self._max_size = max_size
        self._max_attempts = max_attempts
        self._backoff_base_ms = backoff_base_ms
        self._counter = 0
        self._is_processing = False
        self._processor: Optional[Callable] = None
        self._process_task: Optional[asyncio.Task] = None
        
        # Statistics
        self._stats = {
            "enqueued": 0,
            "completed": 0,
            "failed": 0,
            "dropped": 0,
        }
    
    def enqueue(self, data: dict) -> QueueItem:
        """
        Add an item to the queue.
        
        If queue is full, drops the oldest item and logs it.
        """
        # Generate unique ID
        self._counter += 1
        item_id = f"item_{self._counter}_{int(time.time() * 1000)}"
        
        item = QueueItem(
            id=item_id,
            data=data,
            max_attempts=self._max_attempts,
        )
        
        # Check if queue is full
        if len(self._queue) >= self._max_size:
            # Drop oldest item
            dropped = self._queue.pop(0)
            dropped.status = QueueItemStatus.DROPPED
            self._stats["dropped"] += 1
            
            logger.warning(
                f"[PersistQueue] Dropped oldest item due to queue overflow: "
                f"id={dropped.id}, data={dropped.data}"
            )
        
        self._queue.append(item)
        self._stats["enqueued"] += 1
        
        return item
    
    def set_processor(self, processor: Callable[[dict], Any]):
        """Set the function that processes queue items"""
        self._processor = processor
    
    async def start_processing(self):
        """Start the background processor"""
        if self._is_processing:
            return
        
        self._is_processing = True
        self._process_task = asyncio.create_task(self._process_loop())
    
    async def stop_processing(self):
        """Stop the background processor"""
        self._is_processing = False
        if self._process_task:
            self._process_task.cancel()
            try:
                await self._process_task
            except asyncio.CancelledError:
                pass
            self._process_task = None
    
    async def _process_loop(self):
        """Background loop that processes queue items"""
        while self._is_processing:
            try:
                await self._process_next()
                await asyncio.sleep(0.1)  # Small delay between items
            except Exception as e:
                logger.error(f"[PersistQueue] Error in process loop: {e}")
                await asyncio.sleep(1)
    
    async def _process_next(self):
        """Process the next pending item in the queue"""
        if not self._processor:
            return
        
        # Find next pending item
        pending = None
        for item in self._queue:
            if item.status == QueueItemStatus.PENDING:
                pending = item
                break
        
        if not pending:
            return
        
        # Check backoff
        if pending.last_attempt_at:
            elapsed_ms = (datetime.utcnow() - pending.last_attempt_at).total_seconds() * 1000
            backoff_ms = self._backoff_base_ms * (2 ** pending.attempts)
            if elapsed_ms < backoff_ms:
                return  # Not ready yet
        
        # Process item
        pending.status = QueueItemStatus.PROCESSING
        pending.attempts += 1
        pending.last_attempt_at = datetime.utcnow()
        
        try:
            await self._processor(pending.data)
            pending.status = QueueItemStatus.COMPLETED
            self._queue.remove(pending)
            self._stats["completed"] += 1
            
        except Exception as e:
            pending.last_error = str(e)
            
            if pending.attempts >= pending.max_attempts:
                pending.status = QueueItemStatus.FAILED
                self._queue.remove(pending)
                self._stats["failed"] += 1
                
                logger.error(
                    f"[PersistQueue] Item failed after {pending.attempts} attempts: "
                    f"id={pending.id}, error={e}"
                )
            else:
                pending.status = QueueItemStatus.PENDING
    
    def get_stats(self) -> dict:
        """Get queue statistics"""
        return {
            **self._stats,
            "queue_size": len(self._queue),
            "pending": sum(1 for i in self._queue if i.status == QueueItemStatus.PENDING),
            "processing": sum(1 for i in self._queue if i.status == QueueItemStatus.PROCESSING),
        }
    
    def flush(self) -> list[QueueItem]:
        """
        Flush all pending items.
        Returns list of items that were in queue.
        """
        items = list(self._queue)
        self._queue.clear()
        return items


# Global queue instance
_queue: Optional[PersistQueue] = None


def get_persist_queue() -> PersistQueue:
    """Get or create the global persist queue"""
    global _queue
    if _queue is None:
        _queue = PersistQueue()
    return _queue
