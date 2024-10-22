from pydantic import BaseModel
from typing import Optional


from litestar import Controller, Request, Response

from litestar.handlers.http_handlers.decorators import (
    get,
    post,
    delete,
)


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

from util.redis_utils import upsert_task, push_to_queue

redis_client = redis.Redis(REDIS_HOST, port=REDIS_PORT)


# type DocTextInfo struct {
# 	Language       string `json:"language"`
# 	Text           string `json:"text"`
# 	IsOriginalText bool   `json:"is_original_text"`
# }
#
# type UpdateDocumentInfo struct {
# 	Url          string         `json:"url"`
# 	Doctype      string         `json:"doctype"`
# 	Lang         string         `json:"lang"`
# 	Name         string         `json:"name"`
# 	Source       string         `json:"source"`
# 	Hash         string         `json:"hash"`
# 	Mdata        map[string]any `json:"mdata"`
# 	Stage        string         `json:"stage"`
# 	Summary      string         `json:"summary"`
# 	ShortSummary string         `json:"short_summary"`
# 	Private      bool           `json:"private"`
# 	DocTexts     []DocTextInfo  `json:"doc_texts"`
# }


from common.task_schema import Task, create_task, GolangUpdateDocumentInfo


class DaemonState(BaseModel):
    enable_background_processing: Optional[bool] = None
    stop_at_background_docprocessing: Optional[str] = None
    clear_queue: Optional[bool] = None


class DocumentProcesserController(Controller):
    @get(path="/test")
    async def Test(self) -> str:
        return "Hello World!"

    @post(path="/process-existing-document")
    async def process_existing_document_handler(
        self, data: GolangUpdateDocumentInfo, priority: bool
    ) -> Task:
        task = create_task(data, priority, kwargs={})
        if task is None:
            raise Exception("Unable to create task")
        push_to_queue(task)
        return task
