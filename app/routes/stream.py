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
                
    # Fallback to fetching remote thumbnail with Bilibili Referer
    if video.get("thumbnail_url"):
        return await proxy_image(video["thumbnail_url"])
        
    raise HTTPException(status_code=404, detail="Thumbnail not found")

@router.get("/proxy/image")
async def proxy_image(url: str):
    import httpx
    if not url:
        raise HTTPException(status_code=400, detail="Missing url parameter")
        
    # Upgrade to https if needed
    if url.startswith("//"):
        url = "https:" + url
    elif url.startswith("http://"):
        url = url.replace("http://", "https://", 1)
        
    # Allow only bilibili/hdslb domains for security
    allowed_domains = ["hdslb.com", "bilibili.com"]
    if not any(domain in url for domain in allowed_domains):
        raise HTTPException(status_code=403, detail="Domain not allowed")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Referer": "https://www.bilibili.com"
    }
    async with httpx.AsyncClient(headers=headers, timeout=10.0) as client:
        try:
            resp = await client.get(url)
            if resp.status_code != 200:
                raise HTTPException(status_code=resp.status_code, detail="Failed to fetch image")
            content_type = resp.headers.get("content-type", "image/jpeg")
            return Response(
                content=resp.content,
                media_type=content_type,
                headers={"Cache-Control": "public, max-age=86400"}
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
