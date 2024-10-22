from pydantic import BaseModel
from typing import Optional


from uuid import UUID

from litestar import Controller, Request, Response

from litestar.handlers.http_handlers.decorators import (
    get,
    post,
    delete,
)


from litestar.params import Parameter
from litestar.di import Provide
from litestar.repository.filters import LimitOffset
from litestar.datastructures import UploadFile
from litestar.enums import RequestEncodingType
from litestar.params import Body


from common.file_schemas import (
    FileSchema,
    DocumentStatus,
    FileTextSchema,
    docstatus_index,
)


from typing import List, Optional, Dict, Annotated, Tuple, Any


import json

from common.niclib import rand_string, paginate_results

from enum import Enum


from constants import (
    OS_TMPDIR,
)

from common.misc_schemas import QueryData

# REDIS_DOCPROC_PRIORITYQUEUE_KEY = "docproc_queue_priority"
# REDIS_DOCPROC_QUEUE_KEY = "docproc_queue_background"
#
# REDIS_DOCPROC_INFORMATION = "docproc_information"
#
# REDIS_DOCPROC_BACKGROUND_DAEMON_TOGGLE = "docproc_background_daemon"
# REDIS_DOCPROC_BACKGROUND_PROCESSING_STOPS_AT = "docproc_background_stop_at"
# REDIS_DOCPROC_CURRENTLY_PROCESSING_DOCS = "docproc_currently_processing_docs"
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

redis_client = redis.Redis(REDIS_HOST, port=REDIS_PORT)


def push_to_queue(request: str, priority: bool):
    if priority:
        pushkey = REDIS_DOCPROC_QUEUE_KEY
    else:
        pushkey = REDIS_DOCPROC_PRIORITYQUEUE_KEY

    redis_client.rpush(pushkey, request)


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
    ) -> str:
        task
        return "Success"
