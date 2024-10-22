from common.misc_schemas import QueryData

from common.file_schemas import DocumentStatus

import logging
from logic.filelogic import process_fileid_raw
import asyncio
from litestar.contrib.sqlalchemy.base import UUIDBase

from sqlalchemy.ext.asyncio import AsyncSession
import redis
from util.redis_utils import (
    clear_file_queue,
    convert_model_to_results_and_push,
    increment_doc_counter,
    pop_from_queue,
)
import traceback

from constants import (
    REDIS_DOCPROC_BACKGROUND_DAEMON_TOGGLE,
    REDIS_HOST,
    REDIS_PORT,
    REDIS_DOCPROC_CURRENTLY_PROCESSING_DOCS,
)

from pydantic import BaseModel
from common.task_schema import Task, TaskType

redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
default_logger = logging.getLogger(__name__)

# I dont think this does anything waiting to remove it.
# async def background_processing_loop() -> None:
#     await asyncio.sleep(
#         30
#     )  # Wait 30 seconds until application has finished loading to start processing background docs
#     default_logger.info(
#         "Starting the daemon that adds more background documents to process."
#     )
#
#     redis_client.set(REDIS_BACKGROUND_DAEMON_TOGGLE, 0)
#
#     async def activity():
#         if redis_client.get(REDIS_BACKGROUND_DAEMON_TOGGLE) == 0:
#             await asyncio.sleep(300)
#             return None
#         else:
#             await asyncio.sleep(300)
#
#     # Logic to force it to process each loop sequentially
#     result = None
#     while result is None:
#         try:
#             result = await activity()
#         except Exception as e:
#             tb = traceback.format_exc()
#             default_logger.error("Encountered error while processing a document")
#             default_logger.error(e)
#             default_logger.error(tb)
#             await asyncio.sleep(2)
#             result = None


async def main_processing_loop() -> None:
    await asyncio.sleep(
        10
    )  # Wait 10 seconds until application has finished loading to do anything
    max_concurrent_docs = 30
    redis_client.set(REDIS_DOCPROC_CURRENTLY_PROCESSING_DOCS, 0)
    # REMOVE FOR PERSIST QUEUES ACROSS RESTARTS:
    #
    clear_file_queue(redis_client=redis_client)
    default_logger.info("Starting the daemon processes docs in the queue.")

    async def activity():
        concurrent_docs = int(redis_client.get(REDIS_DOCPROC_CURRENTLY_PROCESSING_DOCS))
        if concurrent_docs >= max_concurrent_docs:
            await asyncio.sleep(2)
            return None
        pull_obj = pop_from_queue(redis_client=redis_client)
        if pull_obj is None:
            await asyncio.sleep(2)
            return None

        increment_doc_counter(1, redis_client=redis_client)
        try:
            asyncio.create_task(execute_task(task=pull_obj))
        except Exception as e:
            tb = traceback.format_exc()
            default_logger.error("Encountered error while processing a task.")
            default_logger.error(e)
            default_logger.error(tb)
            await asyncio.sleep(2)
            raise e
        finally:
            increment_doc_counter(-1, redis_client=redis_client)
        return None

    # Logic to force it to process each loop sequentially
    result = None
    while result is None:
        try:
            result = await activity()
        except Exception as e:
            result = None


def initialize_background_loops() -> None:
    asyncio.create_task(main_processing_loop())


async def execute_task(task: Task) -> None:
    if task.task_type == TaskType.add_file:
        raise Exception("Not implemented")

    elif task.task_type == TaskType.process_existing_file:
        await process_existing_file(**task.kwargs)


async def process_existing_file(doc_id_str: str, stop_at: str) -> None:
    logger = default_logger
    logger.info(f"Executing background docproc on {doc_id_str} to {stop_at}")
    stop_at = DocumentStatus(stop_at)
    # TODO:: Replace passthrough files repo with actual global repo
    # engine = create_async_engine(
    #     postgres_connection_string,
    # Maybe Remove for better perf?
    async with engine.begin() as conn:
        await conn.run_sync(UUIDBase.metadata.create_all)
    session = AsyncSession(engine)
    try:
        await process_fileid_raw(doc_id_str, logger, stop_at, priority=False)
    except Exception as e:
        increment_doc_counter(-1, redis_client=redis_client)
        raise e
    increment_doc_counter(-1, redis_client=redis_client)
