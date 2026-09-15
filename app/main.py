import os
import ssl
import uvicorn
import logging
from datetime import datetime
from fastapi import FastAPI
from contextlib import asynccontextmanager

from app.config import load_config
from app.database import Database
from app.poller import Poller
from app.security import SecretPathMiddleware
from app.routes.api import router as api_router
from app.routes.stream import router as stream_router
from app.routes.pages import router as pages_router

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
log = logging.getLogger("bilidown")

config = load_config()
db = Database()
poller = Poller(config, db)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    log.info("Starting BiliDown backend...")
    
    # Initialize DB
    await db.init()
    
    # Sync config uploaders to DB
    for uploader in config.tracked_uploaders:
        mid = uploader.get("mid")
        name = uploader.get("name", f"Uploader {mid}")
        if mid:
            await db.add_uploader(
                mid=mid,
                name=name,
                face_url="",
                is_tracked=True,
                tracked_since=datetime.now()
            )
            
    # Store instances in app state
    app.state.config = config
    app.state.db = db
    app.state.poller = poller
    
    # Start poller background task
    poller.start()
    
    yield
    
    # Shutdown
    log.info("Shutting down BiliDown backend...")
    poller.stop()

app = FastAPI(lifespan=lifespan)

# Add middleware for secret path
app.add_middleware(SecretPathMiddleware, secret=config.secret_path)

# Include routers
app.include_router(api_router)
app.include_router(stream_router)
app.include_router(pages_router)

if __name__ == "__main__":
    host = "0.0.0.0"
    port = config.port
    
    ssl_cert = config.tls_cert
    ssl_key = config.tls_key
    
    run_kwargs = {
        "host": host,
        "port": port,
        "log_level": "info"
    }
    
    # Enable SSL if certs exist
    if os.path.exists(ssl_cert) and os.path.exists(ssl_key):
        log.info(f"Running with SSL on port {port}")
        run_kwargs["ssl_certfile"] = ssl_cert
        run_kwargs["ssl_keyfile"] = ssl_key
    else:
        log.warning(f"SSL certs not found at {ssl_cert} and {ssl_key}. Running in plain HTTP.")
        
    uvicorn.run("app.main:app", **run_kwargs)
