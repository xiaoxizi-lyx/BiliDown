import os
from fastapi import APIRouter, Request, HTTPException, Response
from fastapi.responses import FileResponse, StreamingResponse, RedirectResponse

router = APIRouter(prefix="/api")

def send_bytes_range_requests(
    file_obj, start: int, end: int, chunk_size: int = 1024 * 1024
):
    """Generator to read a file chunk by chunk for range requests."""
    with file_obj as f:
        f.seek(start)
        while (pos := f.tell()) <= end:
            read_size = min(chunk_size, end + 1 - pos)
            chunk = f.read(read_size)
            if not chunk:
                break
            yield chunk

@router.get("/stream/{bvid}")
async def stream_video(request: Request, bvid: str):
    db = request.app.state.db
    video = await db.get_video(bvid)
    
    if not video or video.get("status") != "done" or not video.get("file_path"):
        raise HTTPException(status_code=404, detail="Video not found or not ready")
        
    file_path = video["file_path"]
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found on disk")
        
    file_size = os.path.getsize(file_path)
    range_header = request.headers.get("range")
    
    if range_header:
        # Handle Range request: bytes=start-end
        byte1, byte2 = 0, None
        match = range_header.replace("bytes=", "").split("-")
        byte1 = int(match[0])
        if match[1]:
            byte2 = int(match[1])
            
        start = byte1
        end = byte2 if byte2 is not None else file_size - 1
        
        # Adjust end to file size limit
        end = min(end, file_size - 1)
        length = end - start + 1
        
        headers = {
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(length),
            "Content-Type": "video/mp4",
        }
        
        return StreamingResponse(
            send_bytes_range_requests(open(file_path, "rb"), start, end),
            status_code=206,
            headers=headers
        )
    else:
        # No range provided
        headers = {
            "Accept-Ranges": "bytes",
            "Content-Length": str(file_size),
            "Content-Type": "video/mp4",
        }
        return FileResponse(file_path, headers=headers)

@router.get("/download/{bvid}")
async def download_file(request: Request, bvid: str):
    db = request.app.state.db
    video = await db.get_video(bvid)
    
    if not video or video.get("status") != "done" or not video.get("file_path"):
        raise HTTPException(status_code=404, detail="Video not found or not ready")
        
    file_path = video["file_path"]
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found on disk")
        
    filename = os.path.basename(file_path)
    return FileResponse(
        file_path, 
        media_type="application/octet-stream",
        filename=filename
    )

@router.get("/thumbnail/{bvid}")
async def get_thumbnail(request: Request, bvid: str):
    db = request.app.state.db
    video = await db.get_video(bvid)
    
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
        
    if video.get("file_path"):
        # Try local thumbnail (yt-dlp often saves .webp or .jpg next to .mp4)
        base_path = video["file_path"].rsplit(".", 1)[0]
        for ext in [".webp", ".jpg", ".jpeg", ".png"]:
            thumb_path = f"{base_path}{ext}"
            if os.path.exists(thumb_path):
                return FileResponse(thumb_path)
                
    # Fallback to redirecting to bilibili URL
    if video.get("thumbnail_url"):
        return RedirectResponse(url=video["thumbnail_url"])
        
    raise HTTPException(status_code=404, detail="Thumbnail not found")
