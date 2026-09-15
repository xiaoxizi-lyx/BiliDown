from fastapi import APIRouter, Request, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
import asyncio
import logging
from app.wbi import get_uploader_info, fetch_creator_videos
from app.downloader import download_video

log = logging.getLogger("bilidown.api")
router = APIRouter(prefix="/api")

class UploaderAddRequest(BaseModel):
    mid: int

class DownloadRequest(BaseModel):
    bvid: str
    mid: int
    title: str
    thumbnail_url: str
    duration: int
    upload_time: int
    description: Optional[str] = ""

@router.get("/videos")
async def get_videos(
    request: Request,
    page: int = 1,
    per_page: int = 20,
    source: Optional[str] = None,
    mid: Optional[int] = None,
    search: Optional[str] = None
):
    db = request.app.state.db
    result = await db.get_videos(page, per_page, source, mid, search)
    # Frontend expects: {videos: [...], total, page, pages}
    return {
        "videos": result["items"],
        "total": result["total"],
        "page": result["page"],
        "pages": result["total_pages"],
    }

@router.get("/videos/{bvid}")
async def get_video(request: Request, bvid: str):
    db = request.app.state.db
    video = await db.get_video(bvid)
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    return video

@router.delete("/videos/{bvid}")
async def delete_video(request: Request, bvid: str):
    db = request.app.state.db
    import os
    
    file_path = await db.delete_video(bvid)
    if file_path and os.path.exists(file_path):
        try:
            os.remove(file_path)
            # Try removing thumbnail too
            for ext in [".webp", ".jpg", ".jpeg", ".png"]:
                thumb = file_path.rsplit(".", 1)[0] + ext
                if os.path.exists(thumb):
                    os.remove(thumb)
        except Exception:
            pass
            
    return {"success": True}

@router.get("/uploaders")
async def get_uploaders(request: Request):
    db = request.app.state.db
    uploaders = await db.get_all_uploaders()
    # Enrich with video count per uploader
    enriched = []
    for up in uploaders:
        count_result = await db.get_videos(1, 1, mid_filter=up["mid"])
        up_copy = dict(up)
        up_copy["video_count"] = count_result["total"]
        enriched.append(up_copy)
    # Frontend expects: {uploaders: [...]}
    return {"uploaders": enriched}

@router.post("/uploaders")
async def add_uploader(request: Request, data: UploaderAddRequest):
    db = request.app.state.db
    config = request.app.state.config
    info = await get_uploader_info(data.mid, cookies_file=config.cookies_file)
    
    name = info.get("name") if info and info.get("name") and not info.get("name").startswith("Unknown") else f"UP主_{data.mid}"
    face_url = info.get("face_url", "") if info else ""
        
    await db.add_uploader(
        mid=data.mid,
        name=name,
        face_url=face_url,
        is_tracked=True,
        tracked_since=datetime.now()
    )
    return {"success": True, "name": name}

@router.delete("/uploaders/{mid}")
async def remove_uploader(request: Request, mid: int):
    db = request.app.state.db
    await db.remove_tracker(mid)
    return {"success": True}

@router.get("/explore/{mid}")
async def explore_uploader(request: Request, mid: int, pn: int = 1, ps: int = 20):
    db = request.app.state.db
    config = request.app.state.config
    # Fetch video list from Bilibili API
    data = await fetch_creator_videos(mid, pn, ps, cookies_file=config.cookies_file)
    vlist = data.get("list", {}).get("vlist", [])
    page_info = data.get("page", {"pn": pn, "ps": ps, "count": 0})
    
    # Get uploader info
    info = await get_uploader_info(mid, cookies_file=config.cookies_file)
    
    # Check which videos are already downloaded
    for v in vlist:
        v["downloaded"] = await db.video_exists(v.get("bvid", ""))
    
    # Frontend expects: {videos, page, uploader}
    return {
        "videos": vlist,
        "page": page_info,
        "uploader": info,
    }

@router.post("/explore/download")
async def manual_download(request: Request, data: DownloadRequest, background_tasks: BackgroundTasks):
    db = request.app.state.db
    config = request.app.state.config
    
    if await db.video_exists(data.bvid):
        raise HTTPException(status_code=400, detail="视频已在下载列表中")
        
    # Check if uploader exists, if not add them untracked
    uploaders_res = await db.get_all_uploaders()
    if not any(u["mid"] == data.mid for u in uploaders_res):
        info = await get_uploader_info(data.mid, cookies_file=config.cookies_file)
        await db.add_uploader(
            mid=data.mid,
            name=info["name"],
            face_url=info["face_url"],
            is_tracked=False,
            tracked_since=None
        )
        
    video_data = {
        "bvid": data.bvid,
        "aid": 0,
        "mid": data.mid,
        "title": data.title,
        "description": data.description or "",
        "length": data.duration,
        "pic": data.thumbnail_url,
        "created": data.upload_time
    }
    
    await db.insert_video(video_data, source="manual", status="pending")
    
    # Launch background download
    async def run_dl():
        try:
            await download_video(data.bvid, config, db, source="manual")
            log.info(f"Manual download completed: {data.bvid}")
        except Exception as e:
            log.error(f"Manual download failed for {data.bvid}: {e}")
            
    background_tasks.add_task(run_dl)
    return {"success": True}

@router.get("/status")
async def get_status(request: Request):
    db = request.app.state.db
    config = request.app.state.config
    poller = request.app.state.poller
    
    from app.disk import get_disk_usage
    disk_info = await get_disk_usage(config.download_dir)
    stats = await db.get_stats()
    
    # Add percent to disk info
    if disk_info["total"] > 0:
        disk_info["percent"] = round(disk_info["used"] / disk_info["total"] * 100, 1)
    else:
        disk_info["percent"] = 0
    
    # Frontend expects flat structure
    return {
        "poller_running": poller.is_running if hasattr(poller, "is_running") else False,
        "poll_interval": config.poll_interval_minutes * 60,
        "disk": disk_info,
        "queue_count": stats["queue_count"],
        "video_count": stats["total_videos"],
        "uploader_count": stats["tracked_uploaders"],
        "total_size": stats["total_size"],
    }
