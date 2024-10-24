from pydantic import BaseModel
from typing import Optional



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


from typing import Optional



from common.niclib import rand_string, paginate_results



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


def task_push_to_queue(request: str, priority: bool):
    if priority:
        pushkey = REDIS_DOCPROC_QUEUE_KEY
    else:
        pushkey = REDIS_DOCPROC_PRIORITYQUEUE_KEY

    redis_client.rpush(pushkey, request)


class DaemonState(BaseModel):
    enable_background_processing: Optional[bool] = None
    stop_at_background_docprocessing: Optional[str] = None
    clear_queue: Optional[bool] = None


class EncounterController(Controller):
    @post(path="/dangerous/docproc/control_background_processing_daemon")
    async def control_background_processing_daemon(self, data: DaemonState) -> str:
        daemon_toggle = data.enable_background_processing
        stop_at = data.stop_at_background_docprocessing
        clear_queue = data.clear_queue
        if daemon_toggle is not None:
            redis_client.set(REDIS_DOCPROC_BACKGROUND_DAEMON_TOGGLE, int(daemon_toggle))
        if stop_at is not None:
            target = DocumentStatus(stop_at).value
            redis_client.set(REDIS_DOCPROC_BACKGROUND_PROCESSING_STOPS_AT, target)
        if clear_queue is not None:
            if clear_queue:
                clear_file_queue()
        return "Success!"
