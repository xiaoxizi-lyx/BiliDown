import os
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter()

FRONTEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../frontend"))

@router.get("/")
@router.get("/index.html")
async def get_index():
    path = os.path.join(FRONTEND_DIR, "index.html")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Frontend index.html not found")
    return FileResponse(path)

@router.get("/explore")
@router.get("/explore.html")
async def get_explore():
    path = os.path.join(FRONTEND_DIR, "explore.html")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Frontend explore.html not found")
    return FileResponse(path)

@router.get("/style.css")
async def get_css():
    path = os.path.join(FRONTEND_DIR, "style.css")
    if os.path.exists(path):
        return FileResponse(path, media_type="text/css")
    raise HTTPException(status_code=404, detail="style.css not found")

@router.get("/app.js")
async def get_js():
    path = os.path.join(FRONTEND_DIR, "app.js")
    if os.path.exists(path):
        return FileResponse(path, media_type="application/javascript")
    raise HTTPException(status_code=404, detail="app.js not found")

@router.get("/static/{path:path}")
async def get_static(path: str):
    full_path = os.path.join(FRONTEND_DIR, path)
    if not os.path.abspath(full_path).startswith(FRONTEND_DIR):
        raise HTTPException(status_code=403, detail="Forbidden")
        
    if not os.path.exists(full_path) or not os.path.isfile(full_path):
        raise HTTPException(status_code=404, detail="Static file not found")
        
    return FileResponse(full_path)
