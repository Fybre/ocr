import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)

_queue: asyncio.Queue = asyncio.Queue()
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ocr-worker")


async def enqueue(job_id: str) -> None:
    await _queue.put(job_id)


async def worker_loop(process_fn) -> None:
    """
    Runs indefinitely, pulling job IDs from the queue and processing them
    in a thread pool so the event loop stays unblocked.
    process_fn(job_id: str) -> None  (synchronous, blocking)
    """
    logger.info("Job queue worker started")
    loop = asyncio.get_running_loop()
    while True:
        job_id = await _queue.get()
        try:
            await loop.run_in_executor(_executor, process_fn, job_id)
        except Exception:
            logger.exception("Worker failed processing job %s", job_id)
        finally:
            _queue.task_done()
