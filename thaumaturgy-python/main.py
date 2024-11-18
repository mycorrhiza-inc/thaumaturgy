from asyncio import run
import logging
import traceback

from litestar import Litestar, Router
from litestar.config.cors import CORSConfig
from litestar import MediaType, Request, Response
from litestar.status_codes import HTTP_500_INTERNAL_SERVER_ERROR

from litestar.di import Provide

from util.logging import logging_config

from routing.docproc_controller import DocumentProcesserController


from background_loops import initialize_background_loops


from constants import FIREWORKS_API_KEY, GROQ_API_KEY, OCTOAI_API_KEY, OPENAI_API_KEY

logger = logging.getLogger(__name__)


def run_startup_env_checks():
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


async def on_startup() -> None:
    run_startup_env_checks()
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
