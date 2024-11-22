from uuid import UUID
from common.misc_schemas import QueryData

from common.file_schemas import ConversationInformation, DocumentStatus

import logging
from logic.file_logic import (
    add_url_raw,
    process_file_raw,
    upsert_full_file_to_db,
    validate_and_rectify_file_extension,
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
from common.task_schema import (
    CompleteFileSchema,
    DatabaseInteraction,
    ScraperInfo,
    Task,
    TaskType,
    create_task,
)

redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
default_logger = logging.getLogger(__name__)


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
        try:
            concurrent_docs = int(
                redis_client.get(REDIS_DOCPROC_CURRENTLY_PROCESSING_DOCS)
            )
        except Exception as e:
            default_logger.error(
                f"Could not get number of currently processing docs from redis, stopping document processing out of an abundance of caution: {e}"
            )
            await asyncio.sleep(2)
            return None
        if concurrent_docs >= max_concurrent_docs:
            default_logger.info("At Capacity, Not adding any more documents.")
            await asyncio.sleep(2)
            return None
        try:
            pull_obj = task_pop_from_queue(redis_client=redis_client)
        except Exception as e:
            default_logger.error(f"Redis Error getting task from queue {e}")
            await asyncio.sleep(2)
            return None

        if pull_obj is None:
            await asyncio.sleep(2)
            return None
        try:
            asyncio.create_task(execute_task(task=pull_obj))
            # Give some time for the process to update the ratelimit in redis, if this is causing a throughput issue it should be okay to bring it down to .01 seconds or 10 miliseconds
            await asyncio.sleep(0.1)

        except Exception as e:
            default_logger.error(
                f"Encountered error while creating an async task object: {e}"
            )
            await asyncio.sleep(2)
        return None

    # Logic to force it to process each loop sequentially
    result = None
    while result is None:
        try:
            result = await activity()
        except Exception:
            result = None


def initialize_background_loops() -> None:
    asyncio.create_task(main_processing_loop())


async def execute_task(task: Task) -> None:
    increment_doc_counter(1, redis_client=redis_client)
    logger = default_logger
    # logger.info(f"Executing task of type {task.task_type.value}: {task.id}")
    try:
        match task.task_type:
            case TaskType.add_file_scraper:
                task.obj = ScraperInfo.model_validate(task.obj)
                await process_add_file_scraper(task)
            case TaskType.process_existing_file:
                task.obj = CompleteFileSchema.model_validate(task.obj)
                await process_existing_file(task)
    except Exception:
        logger.error(
            "Somehow an exception made it to the top task excecution level, this shouldnt happen, exception handling should be done inside each task function."
        )

    increment_doc_counter(-1, redis_client=redis_client)

    # logger.info(f"Finished executing task of type {task.task_type.value}: {task.id}")


def evolve_db_interact(
    interact: DatabaseInteraction, next_task_type: TaskType
) -> DatabaseInteraction:
    if next_task_type == TaskType.process_existing_file:
        match interact:
            case DatabaseInteraction.insert:
                return DatabaseInteraction.update
            case DatabaseInteraction.insert_later:
                return DatabaseInteraction.insert
            case DatabaseInteraction.insert_report_later:
                return DatabaseInteraction.insert_report
            case DatabaseInteraction.insert_report:
                return DatabaseInteraction.update_report
            case _:
                return interact
    else:
        return interact


async def process_add_file_scraper(task: Task) -> None:
    scraper_obj = task.obj
    assert isinstance(scraper_obj, ScraperInfo)
    logger = default_logger
    filetype = scraper_obj.file_type
    if filetype is None or filetype == "":
        filetype = "pdf"
    validated_filetype, file_extension_string = validate_and_rectify_file_extension(
        filetype
    )
    file_url = scraper_obj.file_url
    fixed_docket_id = scraper_obj.docket_id.strip().upper()

    metadata = {
        "docket_id": fixed_docket_id,
        "url": scraper_obj.file_url.strip(),
        "extension": file_extension_string,
        "lang": "en",
        "title": scraper_obj.name.strip(),
        "source": scraper_obj.internal_source_name.strip(),
        "date": scraper_obj.published_date.strip(),
        "file_class": scraper_obj.file_class.strip(),
        "author_organisation": scraper_obj.author_organisation.strip(),
        "author": scraper_obj.author_organisation.strip(),
        "author_email": scraper_obj.author_individual_email.strip(),
        "item_number": scraper_obj.item_number.strip(),
    }
    convo_info = ConversationInformation(
        state=scraper_obj.state, docket_id=scraper_obj.docket_id
    )
    file_object = CompleteFileSchema(
        name=scraper_obj.name,
        hash="",
        is_private=False,
        mdata=metadata,
        extension=file_extension_string,
        lang="en",
        conversation=convo_info,
    )
    try:
        error, result_file = await add_url_raw(file_url, file_object)
        if task.database_interact == DatabaseInteraction.insert:
            logger.info("Adding file to the database in file addition step.")
            # assert (
            #     False
            # ), "At this point with updates not working inserts shouldnt happen at the beginning of file processing."
            result_file = await upsert_full_file_to_db(
                result_file, interact=task.database_interact
            )
            assert isinstance(result_file.id, UUID)
            assert result_file.id != UUID(
                "00000000-0000-0000-0000-000000000000"
            ), "File has a null UUID"
    except Exception as e:
        tb = traceback.format_exc()
        return_task = task
        logger.error(e)
        logger.error(tb)
        logger.error("Encountered error while adding file: {e}")
        return_task.error = str(e)
        return_task.completed = True
        return_task.success = False
        task_upsert(return_task)
    else:
        # logger.info(
        #     f"File addition step execute successfully, adding a document processing event to the queue."
        # )
        return_task = task
        return_task.obj = result_file
        return_task.completed = True
        return_task.success = True
        db_interact = evolve_db_interact(
            return_task.database_interact, TaskType.process_existing_file
        )
        new_task = create_task(
            obj=result_file,
            database_interaction=db_interact,
            priority=task.priority,
            task_type=TaskType.process_existing_file,
        )
        if new_task is not None:
            return_task.followup_task_id = new_task.id
            return_task.followup_task_url = new_task.url
            task_push_to_queue(new_task)
        task_upsert(return_task)
        assert (
            new_task is not None
        ), "Encountered logic error relating to an empty task, create task on those inputs should never make an empty task."


async def process_existing_file(task: Task) -> None:
    obj = task.obj
    assert isinstance(obj, CompleteFileSchema)
    logger = default_logger
    try:
        error, result_file = await process_file_raw(
            obj, stop_at=DocumentStatus.completed, priority=task.priority
        )

        if (
            task.database_interact == DatabaseInteraction.insert
            or task.database_interact == DatabaseInteraction.update
        ):
            result_file = await upsert_full_file_to_db(
                result_file, interact=task.database_interact
            )
            assert isinstance(result_file.id, UUID)
            assert result_file.id != UUID(
                "00000000-0000-0000-0000-000000000000"
            ), "File has a null UUID"
    except Exception as e:
        tb = traceback.format_exc()
        return_task = task
        logger.error(e)
        logger.error(tb)
        logger.error(f"encountered error while adding file: {e}")
        return_task.error = f"encountered error while adding file: {e}, \n {tb}"
        task.completed = True
        return_task.success = False
        return_task.error = str(e)
        task_upsert(return_task)
    else:
        return_task = task
        return_task.obj = result_file
        task.completed = True
        return_task.success = True
        task_upsert(return_task)
