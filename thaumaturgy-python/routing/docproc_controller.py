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
    REDIS_DOCPROC_PRIORITYQUEUE_KEY,
    REDIS_DOCPROC_QUEUE_KEY,
    REDIS_DOCPROC_INFORMATION,
    REDIS_DOCPROC_BACKGROUND_DAEMON_TOGGLE,
    REDIS_DOCPROC_BACKGROUND_PROCESSING_STOPS_AT,
    REDIS_DOCPROC_CURRENTLY_PROCESSING_DOCS,
    REDIS_HOST,
    REDIS_PORT,
)

from background_loops import clear_file_queue

import redis
import uuid

from util.redis_utils import get_task, push_to_queue

redis_client = redis.Redis(REDIS_HOST, port=REDIS_PORT)


from common.task_schema import ScraperInfo, Task, create_task, GolangUpdateDocumentInfo


class DaemonState(BaseModel):
    enable_background_processing: Optional[bool] = None
    stop_at_background_docprocessing: Optional[str] = None
    clear_queue: Optional[bool] = None


class DocumentProcesserController(Controller):
    @get(path="/test")
    async def Test(self) -> str:
        return "Hello World!"

    @get(path="/status/{task_id:uuid}")
    async def get_status(
        self,
        task_id: uuid.UUID = Parameter(title="Task ID", description="Task to retieve"),
    ) -> Response:
        task = get_task(task_id)
        if task is None:
            return Response(status_code=404, content="Task not found")
        return Response(status_code=200, content=task)

    @post(path="/process-existing-document")
    async def process_existing_document_handler(
        self, data: GolangUpdateDocumentInfo, priority: bool
    ) -> Task:
        task = create_task(data, priority, kwargs={})
        if task is None:
            raise Exception("Unable to create task")
        push_to_queue(task)
        return task

    # https://thaum.kessler.xyz/v1/process-scraped-doc
    @post(path="/process-scraped-doc")
    async def process_scraped_document_handler(
        self, data: ScraperInfo, priority: bool
    ) -> Task:
        task = create_task(data, priority, kwargs={})
        if task is None:
            raise Exception("Unable to create task")
        push_to_queue(task)
        return task
