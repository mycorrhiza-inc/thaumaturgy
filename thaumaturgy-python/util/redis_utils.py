# REDIS_DOCPROC_PRIORITYQUEUE_KEY = "docproc_queue_priority"
# REDIS_DOCPROC_QUEUE_KEY = "docproc_queue_background"
#
# REDIS_DOCPROC_INFORMATION = "docproc_information"
#
# REDIS_DOCPROC_BACKGROUND_DAEMON_TOGGLE = "docproc_background_daemon"
# REDIS_DOCPROC_BACKGROUND_PROCESSING_STOPS_AT = "docproc_background_stop_at"
# REDIS_DOCPROC_CURRENTLY_PROCESSING_DOCS = "docproc_currently_processing_docs"
from constants import (
    REDIS_DOCPROC_QUEUE_KEY,
    REDIS_DOCPROC_CURRENTLY_PROCESSING_DOCS,
    REDIS_HOST,
    REDIS_PORT,
    REDIS_DOCPROC_PRIORITYQUEUE_KEY,
)
from models.files import FileSchema, FileRepository
from common.file_schemas import FileSchema, DocumentStatus, docstatus_index
from typing import List, Tuple, Any, Union, Optional, Dict
import redis
import logging
import sys

# TODO : Mabye asycnify all the redis calls

default_redis_client = redis.Redis(
    host=REDIS_HOST, port=REDIS_PORT, decode_responses=True
)
default_logger = logging.getLogger(__name__)


def pop_from_queue(redis_client: Optional[Any] = None) -> Optional[Any]:
    if redis_client is None:
        redis_client = default_redis_client
    # TODO : Clean up code logic
    request_string = redis_client.lpop(REDIS_DOCPROC_PRIORITYQUEUE_KEY)
    if request_string is None:
        request_string = redis_client.lpop(REDIS_DOCPROC_QUEUE_KEY)
    if isinstance(request_string, str) or request_string is None:
        return request_string
    default_logger.error(type(request_string))
    raise Exception(
        f"Request id is not string or none and is {type(request_string)} instead."
    )


def update_status_in_redis(request_id: int, status: Dict[str, str]) -> None:
    redis_client = default_redis_client
    redis_client.hmset(str(request_id), status)


def increment_doc_counter(
    increment: int,
    redis_client: Optional[Any] = None,
) -> None:
    if redis_client is None:
        redis_client = default_redis_client
    counter = redis_client.get(REDIS_DOCPROC_CURRENTLY_PROCESSING_DOCS)
    default_logger.info(counter)
    redis_client.set(REDIS_DOCPROC_CURRENTLY_PROCESSING_DOCS, int(counter) + increment)


def convert_model_to_results_and_push(
    schemas: Union[FileSchema, List[FileSchema]],
    redis_client: Optional[Any] = None,
) -> None:
    def convert_model_to_results(schemas: List[FileSchema]) -> list:
        return_list = []
        for schema in schemas:
            str_id = str(schema.id)
            # Order doesnt matter since the list is shuffled anyway
            return_list.append(str_id)
        return return_list

    if redis_client is None:
        redis_client = default_redis_client
    if isinstance(schemas, FileSchema):
        schemas = [schemas]
    id_list = convert_model_to_results(schemas)
    redis_client.rpush(REDIS_DOCPROC_QUEUE_KEY, *id_list)


def clear_file_queue(
    redis_client: Optional[Any] = None,
) -> None:
    if redis_client is None:
        redis_client = default_redis_client
    redis_client.ltrim(REDIS_DOCPROC_PRIORITYQUEUE_KEY, 0, 0)
    redis_client.ltrim(REDIS_DOCPROC_QUEUE_KEY, 0, 0)


async def bulk_process_file_background(
    files_repo: FileRepository,
    files: List[FileSchema],
    stop_at: DocumentStatus,
    max_documents: Optional[int] = None,
    logger: Optional[Any] = None,
    redis_client: Optional[Any] = None,
) -> bool:
    if redis_client is None:
        redis_client = default_redis_client
    if logger is None:
        logger = default_logger
    if max_documents is None:
        max_documents = 1000  # Default to prevent server from crashing by accidentially not including a value
    if files is None or len(files) == 0:
        logger.info("List of files to process was empty")
        return max_documents == 0

    def sanitize(x: Any) -> list:
        if x is None:
            return []
        return list(x)

    currently_processing_docs = sanitize(
        redis_client.lrange(REDIS_DOCPROC_QUEUE_KEY, 0, -1)
    ) + sanitize(redis_client.lrange(REDIS_DOCPROC_PRIORITYQUEUE_KEY, 0, -1))

    def should_process(file: FileSchema) -> bool:
        if not docstatus_index(file.stage) < docstatus_index(stop_at):
            return False
        # Set up a toggle for this at some point in time
        return file.id not in currently_processing_docs

    await files_repo.session.commit()
    files_to_convert = list(filter(should_process, files))[:max_documents]

    convert_model_to_results_and_push(schemas=files_to_convert)
    return len(files_to_convert) == max_documents
