import atexit
import asyncio
import os
import sys

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))

sys.path.insert(0, CURRENT_DIR)
os.chdir(CURRENT_DIR)

from dotenv import load_dotenv

load_dotenv(os.path.join(CURRENT_DIR, ".env"))

from a2wsgi import ASGIMiddleware
from server import app as fastapi_app

application = ASGIMiddleware(fastapi_app)


# a2wsgi handles WSGI HTTP requests but does not emit ASGI lifespan events.
# Start FastAPI explicitly so seed/cleanup startup handlers also run under
# Passenger, not only under Uvicorn during local development.
asyncio.run_coroutine_threadsafe(
    fastapi_app.router.startup(),
    application.loop,
).result(timeout=30)


@atexit.register
def shutdown_fastapi() -> None:
    if not application.loop.is_running():
        return

    try:
        asyncio.run_coroutine_threadsafe(
            fastapi_app.router.shutdown(),
            application.loop,
        ).result(timeout=10)
    except Exception:
        # Passenger can terminate a process while its event loop is already
        # stopping; there is nothing useful to recover at that point.
        pass
