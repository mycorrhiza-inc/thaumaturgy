# REDIS_DOCPROC_PRIORITYQUEUE_KEY = "docproc_queue_priority"
# REDIS_DOCPROC_QUEUE_KEY = "docproc_queue_background"
#
# REDIS_DOCPROC_INFORMATION = "docproc_information"
#
# REDIS_DOCPROC_BACKGROUND_DAEMON_TOGGLE = "docproc_background_daemon"
# REDIS_DOCPROC_BACKGROUND_PROCESSING_STOPS_AT = "docproc_background_stop_at"
# REDIS_DOCPROC_CURRENTLY_PROCESSING_DOCS = "docproc_currently_processing_docs"
from datetime import date
from pymilvus.client import re
from constants import (
    REDIS_DOCPROC_QUEUE_KEY,
    REDIS_DOCPROC_CURRENTLY_PROCESSING_DOCS,
    REDIS_HOST,
    REDIS_PORT,
    REDIS_DOCPROC_PRIORITYQUEUE_KEY,
)
from common.file_schemas import FileSchema, DocumentStatus, docstatus_index
from typing import List, Any, Union, Optional, Dict
import redis
import logging
from uuid import UUID
from common.task_schema import Task

from datetime import datetime


# TODO : Mabye asycnify all the redis calls

default_redis_client = redis.Redis(
    host=REDIS_HOST, port=REDIS_PORT, decode_responses=True
)
default_logger = logging.getLogger(__name__)


def pop_task_from_queue(redis_client: Optional[Any] = None) -> Optional[Task]:
    logger = default_logger
    if redis_client is None:
        redis_client = default_redis_client
    # TODO : Clean up code logic
    request_string = redis_client.lpop(REDIS_DOCPROC_PRIORITYQUEUE_KEY)
    if request_string is None:
        request_string = redis_client.lpop(REDIS_DOCPROC_QUEUE_KEY)
    if request_string is None:
        return None
    try:
        obj = Task.model_validate_json(request_string)
    except Exception as e:
        logger.error(e)
        logger.error(request_string)
        return None
    return obj


def push_to_queue(task: Task, redis_client: Optional[Any] = None) -> None:
    if redis_client is None:
        redis_client = default_redis_client
    assert isinstance(task, Task)
    priority = task.priority
    if priority:
        pushkey = REDIS_DOCPROC_QUEUE_KEY
    else:
        pushkey = REDIS_DOCPROC_PRIORITYQUEUE_KEY
    json_str = task.model_dump_json()
    redis_client.rpush(pushkey, json_str)
    upsert_task(task, redis_client)


def upsert_task(task, redis_client: Optional[Any] = None) -> None:
    task.updated_at = datetime.now()
    if redis_client is None:
        redis_client = default_redis_client
    assert isinstance(task, Task)
    json_str = task.model_dump_json()
    string_id = str(task.id)
    redis_client.set(string_id, json_str)


def get_task(task_id: UUID, redis_client: Optional[Any] = None) -> Optional[Task]:
    if redis_client is None:
        redis_client = default_redis_client
    uuid_str = str(task_id)
    task_str = redis_client.get(uuid_str)
    if task_str is None:
        return None
    try:
        task = Task.model_validate_json(task_str)
    except Exception as e:
        default_logger.error(e)
        return None
    return task


def increment_doc_counter(
    increment: int,
    redis_client: Optional[Any] = None,
) -> None:
    if redis_client is None:
        redis_client = default_redis_client
    counter = redis_client.get(REDIS_DOCPROC_CURRENTLY_PROCESSING_DOCS)
    default_logger.info(counter)
    redis_client.set(REDIS_DOCPROC_CURRENTLY_PROCESSING_DOCS, int(counter) + increment)


def clear_file_queue(
    redis_client: Optional[Any] = None,
) -> None:
    if redis_client is None:
        redis_client = default_redis_client
    redis_client.ltrim(REDIS_DOCPROC_PRIORITYQUEUE_KEY, 0, 0)
    redis_client.ltrim(REDIS_DOCPROC_QUEUE_KEY, 0, 0)


# def convert_model_to_results_and_push(
#     schemas: Union[FileSchema, List[FileSchema]],
#     redis_client: Optional[Any] = None,
# ) -> None:
#     def convert_model_to_results(schemas: List[FileSchema]) -> list:
#         return_list = []
#         for schema in schemas:
#             str_id = str(schema.id)
#             # Order doesnt matter since the list is shuffled anyway
#             return_list.append(str_id)
#         return return_list
#
#     if redis_client is None:
#         redis_client = default_redis_client
#     if isinstance(schemas, FileSchema):
#         schemas = [schemas]
#     id_list = convert_model_to_results(schemas)
#     redis_client.rpush(REDIS_DOCPROC_QUEUE_KEY, *id_list)


# async def bulk_process_file_background(
#     files: List[FileSchema],
#     stop_at: DocumentStatus,
#     max_documents: Optional[int] = None,
#     logger: Optional[Any] = None,
#     redis_client: Optional[Any] = None,
# ) -> bool:
#     if redis_client is None:
#         redis_client = default_redis_client
#     if logger is None:
#         logger = default_logger
#     if max_documents is None:
#         max_documents = 1000  # Default to prevent server from crashing by accidentially not including a value
#     if files is None or len(files) == 0:
#         logger.info("List of files to process was empty")
#         return max_documents == 0
#
#     def sanitize(x: Any) -> list:
#         if x is None:
#             return []
#         return list(x)
#
#     currently_processing_docs = sanitize(
#         redis_client.lrange(REDIS_DOCPROC_QUEUE_KEY, 0, -1)
#     ) + sanitize(redis_client.lrange(REDIS_DOCPROC_PRIORITYQUEUE_KEY, 0, -1))
#
#     def should_process(file: FileSchema) -> bool:
#         if not docstatus_index(DocumentStatus(file.stage)) < docstatus_index(stop_at):
#             return False
#         # Set up a toggle for this at some point in time
#         return file.id not in currently_processing_docs
#
#     # await files_repo.session.commit()
#     files_to_convert = list(filter(should_process, files))[:max_documents]
#
#     convert_model_to_results_and_push(schemas=files_to_convert)
#     return len(files_to_convert) == max_documents
