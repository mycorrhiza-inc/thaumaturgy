from asyncio import run
import asyncio
import logging
import traceback

from litestar import Litestar, Router
from litestar.config.cors import CORSConfig
from litestar import MediaType, Request, Response
from litestar.status_codes import HTTP_500_INTERNAL_SERVER_ERROR

from litestar.di import Provide

from common.llm_utils import KeLLMUtils, ModelName
from util.logging import logging_config

from routing.docproc_controller import DocumentProcesserController


from background_loops import initialize_background_loops


from constants import (
    DEEPINFRA_API_KEY,
    FIREWORKS_API_KEY,
    GROQ_API_KEY,
    MARKER_MAX_POLLS,
    MARKER_SECONDS_PER_POLL,
    OCTOAI_API_KEY,
    OPENAI_API_KEY,
)

logger = logging.getLogger(__name__)


async def run_startup_env_checks():
    # Apparently this catches both none and "", stil spooky dynamic type stuff
    if not OPENAI_API_KEY:
        raise EnvironmentError(
            "OPENAI_API_KEY environment variable is not set. Please set it to use OpenAI services."
        )
    if not FIREWORKS_API_KEY:
        raise EnvironmentError(
            "FIREWORKS_API_KEY environment variable is not set. Please set it to use Fireworks AI services."
        )
    if not GROQ_API_KEY:
        raise EnvironmentError(
            "GROQ_API_KEY environment variable is not set. Please set it to use Groq services."
        )
    if not OCTOAI_API_KEY:
        raise EnvironmentError(
            "OCTOAI_API_KEY environment variable is not set. Please set it to use OctoAI services."
        )
    if not DEEPINFRA_API_KEY:
        raise EnvironmentError(
            "OCTOAI_API_KEY environment variable is not set. Please set it to use OctoAI services."
        )
    if not MARKER_MAX_POLLS or MARKER_MAX_POLLS < 0:
        raise EnvironmentError("MARKER_MAX_POLLS environment variable is not set.")
    if not MARKER_SECONDS_PER_POLL or MARKER_SECONDS_PER_POLL < 0:
        raise EnvironmentError(
            "MARKER_SECONDS_PER_POLL environment variable is not set."
        )
    test_medium_llm = KeLLMUtils(ModelName.llama_70b)
    medium_promise = test_medium_llm.simple_question("Did this test work?")
    test_small_llm = KeLLMUtils(ModelName.llama_8b)
    small_promise = test_small_llm.simple_question("Did this test work?")
    await asyncio.gather(medium_promise, small_promise)


async def on_startup() -> None:
    await run_startup_env_checks()
    initialize_background_loops()


def plain_text_exception_handler(request: Request, exc: Exception) -> Response:
    """Default handler for exceptions subclassed from HTTPException."""
    tb = traceback.format_exc()
    request.logger.error(f"exception: {exc}")
    request.logger.error(f"traceback:\n{tb}")
    status_code = getattr(exc, "status_code", HTTP_500_INTERNAL_SERVER_ERROR)
    details = getattr(exc, "detail", "")

    return Response(
        media_type=MediaType.TEXT,
        content=details,
        status_code=status_code,
    )


cors_config = CORSConfig(allow_origins=["*"])

api_router = Router(
    path="/v1/",
    route_handlers=[DocumentProcesserController],
)

app = Litestar(
    on_startup=[on_startup],
    route_handlers=[api_router],
    cors_config=cors_config,
    logging_config=logging_config,
    exception_handlers={Exception: plain_text_exception_handler},
)
