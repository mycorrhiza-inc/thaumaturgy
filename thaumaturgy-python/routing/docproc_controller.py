from typing_extensions import List
from pydantic import BaseModel
from typing import Optional


from litestar import Controller, Request, Response

from litestar.handlers.http_handlers.decorators import (
    get,
    post,
    delete,
)


from litestar.params import Parameter
from typing import Optional


from constants import (
    REDIS_HOST,
    REDIS_PORT,
)

from background_loops import clear_file_queue

import redis
import uuid

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

redis_client = redis.Redis(REDIS_HOST, port=REDIS_PORT)


class DaemonState(BaseModel):
    enable_background_processing: Optional[bool] = None
    stop_at_background_docprocessing: Optional[str] = None
    clear_queue: Optional[bool] = None


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


class DocumentProcesserController(Controller):
    @get(path="/test")
    async def Test(self) -> str:
        return "Hello World!"

    @get(path="/status/{task_id:uuid}")
    async def get_status(
        self,
        task_id: uuid.UUID = Parameter(title="Task ID", description="Task to retieve"),
    ) -> Response:
        task = task_get(task_id)
        if task is None:
            return Response(status_code=404, content="Task not found")
        return Response(status_code=200, content=task)

    @post(path="/process-existing-document")
    async def process_existing_document_handler(
        self, data: CompleteFileSchema, priority: bool
    ) -> Task:
        task = create_task(
            data,
            priority=priority,
            database_interaction=DatabaseInteraction.update,
            kwargs={},
            task_type=TaskType.process_existing_file,
        )
        if task is None:
            raise Exception("Unable to create task")
        task_push_to_queue(task)
        return task

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
        priority: bool,
        docket_id: str = Parameter(title="Docket ID", description="Docket ID"),
    ) -> List[Task]:
        tasklist: List[Task] = []
        for data_instance in data:
            actual_data = convert_ny_to_scraper_info(data_instance)
            actual_data.docket_id = docket_id
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
