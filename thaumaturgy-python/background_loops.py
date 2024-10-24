from common.misc_schemas import QueryData

from common.file_schemas import DocumentStatus

import logging
from logic.filelogic import (
    add_file_raw,
    add_url_raw,
    process_file_raw,
    process_fileid_raw,
)
import asyncio
import redis
from util.redis_utils import (
    clear_file_queue,
    increment_doc_counter,
    task_pop_from_queue,
    task_push_to_queue,
    task_upsert,
)
import traceback

from constants import (
    REDIS_HOST,
    REDIS_PORT,
    REDIS_DOCPROC_CURRENTLY_PROCESSING_DOCS,
)

from pydantic import BaseModel
from common.task_schema import GolangUpdateDocumentInfo, ScraperInfo, Task, TaskType

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
        pull_obj = task_pop_from_queue(redis_client=redis_client)
        if pull_obj is None:
            await asyncio.sleep(2)
            return None

        increment_doc_counter(1, redis_client=redis_client)
        try:
            asyncio.create_task(execute_task(task=pull_obj))
        except Exception as e:
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
    logger = default_logger
    logger.info(f"Executing task of type {task.task_type.value}: {task.id}")
    match task.task_type:
        case TaskType.add_file_scraper:
            task.obj = ScraperInfo.model_validate(task.obj)
            await process_add_file_scraper(task)
        case TaskType.process_existing_file:
            task.obj = GolangUpdateDocumentInfo.model_validate(task.obj)
            await process_existing_file(task)

    logger.info(f"Finished executing task of type {task.task_type.value}: {task.id}")


async def process_add_file_scraper(task: Task) -> None:
    scraper_obj = task.obj
    assert isinstance(scraper_obj, ScraperInfo)
    logger = default_logger
    filetype = scraper_obj.file_type
    if filetype is None or filetype == "":
        filetype = "pdf"
    file_url = scraper_obj.file_url
    metadata = {
        "url": scraper_obj.file_url,
        "doctype": filetype,
        "lang": "",
        "title": scraper_obj.name,
        "source": scraper_obj.internal_source_name,
        "date": scraper_obj.published_date,
        "file_class": scraper_obj.file_class,
        "author_organisation": scraper_obj.author_organisation,
        "author": scraper_obj.author_organisation,
        "item_number": scraper_obj.item_number,
    }
    try:
        result_file = await add_url_raw(file_url, metadata)
    except Exception as e:
        tb = traceback.format_exc()
        return_task = task
        logger.error(e)
        logger.error(tb)
        logger.error("Encountered error while adding file: {e}")
        return_task.error = str(e)
        task.completed = True
        task_upsert(return_task)
    else:
        return_task = task
        task.obj = result_file
        task.completed = True
        task_upsert(return_task)


async def process_existing_file(task: Task) -> None:
    obj = task.obj
    assert isinstance(obj, GolangUpdateDocumentInfo)
    logger = default_logger
    try:
        result_file = await process_file_raw(
            obj, stop_at=DocumentStatus.completed, priority=task.priority
        )
    except Exception as e:
        tb = traceback.format_exc()
        return_task = task
        logger.error(e)
        logger.error(tb)
        logger.error("Encountered error while adding file: {e}")
        return_task.error = str(e)
        task.completed = True
        task_upsert(return_task)
    else:
        return_task = task
        task.obj = result_file
        task_upsert(return_task)
        process_task = Task(
            priority=task.priority,
            task_type=TaskType.process_existing_file,
            obj=result_file,
        )

        task_push_to_queue(process_task)
