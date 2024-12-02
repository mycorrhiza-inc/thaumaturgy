import aiohttp
from typing_extensions import List
from pydantic import BaseModel, RootModel, TypeAdapter
from typing import Optional


from litestar import Controller, Request, Response

from litestar.handlers.http_handlers.decorators import (
    get,
    post,
)


from litestar.params import Parameter
from typing import Optional


from common.file_schemas import NEWDOCSTAGE
from constants import (
    KESSLER_API_URL,
    REDIS_DOCPROC_QUEUE_KEY,
    REDIS_HOST,
    REDIS_MAIN_PROCESS_LOOP_CONFIG,
    REDIS_PORT,
)


import redis
import uuid

from daemon_state import (
    DaemonState,
    updateExistingState,
    validateAllValuesDefined,
)
from util.redis_utils import task_get, task_push_to_queue


from common.task_schema import (
    BulkProcessInfo,
    BulkProcessSchema,
    DatabaseInteraction,
    ScraperInfo,
    Task,
    TaskType,
    create_task,
    CompleteFileSchema,
)
import logging

redis_client = redis.Redis(REDIS_HOST, port=REDIS_PORT)
default_logger = logging.getLogger(__name__)


class NyPUCScraperSchema(BaseModel):
    docket_id: Optional[str] = None
    serial: Optional[str]
    date_filed: Optional[str]
    nypuc_doctype: Optional[str]
    name: Optional[str]
    url: Optional[str]
    organization: Optional[str]
    itemNo: Optional[str]
    file_name: Optional[str]


def convert_ny_to_scraper_info(nypuc_scraper: NyPUCScraperSchema) -> ScraperInfo:
    return ScraperInfo(
        state="ny",
        file_url=nypuc_scraper.url or "",
        name=nypuc_scraper.name or "",
        published_date=nypuc_scraper.date_filed or "",
        internal_source_name=nypuc_scraper.organization or "",
        docket_id=nypuc_scraper.docket_id or "",
        author_organisation=nypuc_scraper.organization or "",
        file_class=nypuc_scraper.nypuc_doctype or "",
        file_type=(
            nypuc_scraper.file_name.split(".")[-1] if nypuc_scraper.file_name else ""
        ),
        lang="en",  # Assuming default language is "en"
        item_number=nypuc_scraper.itemNo or "",
    )


class DaemonStatus(BaseModel):
    config: DaemonState = DaemonState()
    background_task_queue_length: int = -1
    priority_task_queue_length: int = -1


def getDaemonStatus(redis_client: redis.Redis) -> DaemonStatus:
    existing_state_str = redis_client.get(REDIS_MAIN_PROCESS_LOOP_CONFIG)
    existing_state = DaemonState.model_validate_json(existing_state_str)
    priority_task_queue_length = int(redis_client.llen(REDIS_DOCPROC_PRIORITYQUEUE_KEY))
    background_task_queue_length = int(redis_client.llen(REDIS_DOCPROC_QUEUE_KEY))
    status = DaemonStatus(
        config=existing_state,
        background_task_queue_length=background_task_queue_length,
        priority_task_queue_length=priority_task_queue_length,
    )
    return status


class ListCompleteFileSchema(RootModel):
    root: List[CompleteFileSchema]


async def backgroundRequestDocuments(
    request_size: int,
    check_if_empty: bool = True,
    redis_client: redis.Redis = redis_client,
) -> str:
    if check_if_empty:
        background_not_empty = int(redis_client.llen(REDIS_DOCPROC_QUEUE_KEY)) != 0
        priority_not_empty = int(redis_client.llen(REDIS_DOCPROC_QUEUE_KEY)) != 0
        if background_not_empty or priority_not_empty:
            raise Exception("Queue not empty")
    async with aiohttp.ClientSession() as session:
        response = await session.post(
            f"{KESSLER_API_URL}/v2/admin/get-unverified-docs/{request_size}"
        )
        if response.status < 200 and response.status >= 300:
            raise Exception(
                "Failed to get response from server with code "
                + str(response.status)
                + "\n and body "
                + str(response)
            )
        files = ListCompleteFileSchema.model_validate(await response.json())
        files = files.root
        process_existing_docs(files=files, priority=False, redis_client=redis_client)

    return "complete"


def process_existing_docs(
    files: List[CompleteFileSchema],
    priority: bool = False,
    redis_client: redis.Redis = redis_client,
) -> List[Task]:
    logger = default_logger

    def create_push_file(file: CompleteFileSchema) -> Task:
        # Reset
        if file.stage.database_error_msg != "":
            logger.error(
                f"Encountered a database error for file {file.id} with error: {file.stage.database_error_msg}"
            )
            file.stage = NEWDOCSTAGE
        task = create_task(
            obj=file,
            priority=priority,
            database_interaction=DatabaseInteraction.update,
            kwargs={},
            task_type=TaskType.process_existing_file,
        )
        if task is None:
            raise Exception("Unable to create task")
        task_push_to_queue(task, redis_client=redis_client)
        return task

    return_tasks = map(create_push_file, files)
    return list(return_tasks)


class DocumentProcesserController(Controller):
    @get(path="/test")
    async def Test(self) -> str:
        return "Hello World!"

    @post(path="/dangerous/set-daemon-state")
    async def set_daemon_state(self, data: DaemonState) -> str:
        existing_state_str = redis_client.get(REDIS_MAIN_PROCESS_LOOP_CONFIG)
        existing_state = DaemonState.model_validate_json(existing_state_str)
        existing_state = updateExistingState(existing_state, data)
        assert validateAllValuesDefined(
            existing_state
        ), "All values for the daemon state must be defined, this is likely a programming error"
        existing_state_str = DaemonState.model_dump_json(existing_state)
        redis_client.set(REDIS_MAIN_PROCESS_LOOP_CONFIG, existing_state_str)
        return "Daemon State Updated"

    @get(path="/dangerous/get-daemon-status")
    async def get_daemon_state(self) -> DaemonState:
        existing_state_str = redis_client.get(REDIS_MAIN_PROCESS_LOOP_CONFIG)
        existing_state = DaemonState.model_validate_json(existing_state_str)
        return existing_state

    @get(path="/status/{task_id:uuid}")
    async def get_status(
        self,
        task_id: uuid.UUID = Parameter(title="Task ID", description="Task to retieve"),
    ) -> Response:
        task = task_get(task_id)
        if task is None:
            return Response(status_code=404, content="Task not found")
        return Response(status_code=200, content=task)

    @post(path="/get-docs-from-kessler")
    async def get_from_kessler(
        self, max_docs: int = 1000, priority: bool = False
    ) -> str:
        await backgroundRequestDocuments(max_docs, priority)
        return "Success!"

    @post(path="/process-existing-document")
    async def process_existing_document_handler(
        self, data: CompleteFileSchema, priority: bool
    ) -> Task:
        return process_existing_docs(files=[data], priority=priority)[0]

    @post(path="/process-existing-document/list")
    async def process_existing_documents_handler(
        self, data: List[CompleteFileSchema], priority: bool
    ) -> List[Task]:
        return process_existing_docs(files=data, priority=priority)

    # https://thaum.kessler.xyz/v1/process-scraped-doc
    @post(path="/process-scraped-doc")
    async def process_scraped_document_handler(
        self, data: ScraperInfo, priority: bool
    ) -> Task:
        task = create_task(
            data,
            priority=priority,
            database_interaction=DatabaseInteraction.insert,
            kwargs={},
            task_type=TaskType.add_file_scraper,
        )
        if task is None:
            raise Exception("Unable to create task")
        task_push_to_queue(task)
        return task

    @post(path="/process-scraped-docs-bulk")
    async def process_scraped_documents_bulk_handler(
        self, data: BulkProcessSchema, priority: bool
    ) -> List[Task]:
        scraperlist = data.scraper_info_list
        bulk_info = data.bulk_info
        tasklist = []
        for scraper in scraperlist:
            task = create_task(
                obj=scraper,
                priority=priority,
                database_interaction=DatabaseInteraction.insert,
                kwargs={},
                task_type=TaskType.add_file_scraper,
            )
            if task is None:
                raise Exception("Unable to create task")
            task_push_to_queue(task)
            tasklist.append(task)
        return tasklist

    @post(path="/process-scraped-doc/ny-puc/")
    async def process_nypuc_scraped_document_handler(
        self,
        data: NyPUCScraperSchema,
        priority: bool,
    ) -> Task:
        actual_data = convert_ny_to_scraper_info(data)
        task = create_task(
            actual_data,
            priority=priority,
            database_interaction=DatabaseInteraction.insert,
            kwargs={},
            task_type=TaskType.add_file_scraper,
        )
        if task is None:
            raise Exception("Unable to create task")
        task_push_to_queue(task)
        return task

    @post(path="/process-scraped-doc/ny-puc/list")
    async def process_nypuc_scraped_document_handler_list(
        self,
        data: List[NyPUCScraperSchema],
        priority: bool = False,
    ) -> List[Task]:
        tasklist: List[Task] = []
        for data_instance in data:
            actual_data = convert_ny_to_scraper_info(data_instance)
            task = create_task(
                actual_data,
                priority=priority,
                database_interaction=DatabaseInteraction.insert,
                kwargs={},
                task_type=TaskType.add_file_scraper,
            )
            if task is None:
                raise Exception("Unable to create task")
            task_push_to_queue(task)
            tasklist.append(task)
        return tasklist
