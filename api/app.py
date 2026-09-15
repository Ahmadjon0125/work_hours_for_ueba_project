"""FastAPI app factory."""
import os

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pymongo.errors import PyMongoError

from api.routes import DASHBOARD_DIR, router
from utils.logger import get_logger

log = get_logger("api")


def create_app(lifespan=None):
    """FastAPI ilovasini yig'adi.

    `lifespan` — ishga tushish/to'xtash ilgagi (`main.py` beradi). Ilgari
    buning o'rniga `@app.on_event("startup"/"shutdown")` ishlatilardi, lekin
    u FastAPI'da eskirgan (deprecated) va kelajakda olib tashlanishi mumkin.
    """
    app = FastAPI(title="UEBA Working-Hours", docs_url="/api/docs",
                  redoc_url=None, lifespan=lifespan)
    app.include_router(router)
    app.mount("/static", StaticFiles(directory=os.path.join(DASHBOARD_DIR, "static")), name="static")

    @app.exception_handler(PyMongoError)
    def _mongo_down(request: Request, exc: PyMongoError):
        """Mongo yotganda xom 500 o'rniga tushunarli 503 qaytaramiz."""
        log.error("MongoDB xatosi (%s): %s", request.url.path, type(exc).__name__)
        return JSONResponse(status_code=503, content={"detail": "MongoDB bilan aloqa yo'q"})

    return app
