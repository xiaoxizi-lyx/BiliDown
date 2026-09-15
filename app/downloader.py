import yt_dlp
import asyncio
import os
import logging
from typing import Dict, Any, Optional
from app.disk import ensure_disk_space
from app.cookie_helper import get_netscape_cookie_path

log = logging.getLogger("bilidown.downloader")

def _extract_info(url: str, cookies_file: str) -> Dict[str, Any]:
    cookiefile = get_netscape_cookie_path(cookies_file)
    opts = {
        "cookiefile": cookiefile,
        "quiet": True,
        "no_warnings": True
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False)

async def extract_video_info(url: str, cookies_file: str) -> Dict[str, Any]:
    return await asyncio.to_thread(_extract_info, url, cookies_file)

def _download(url: str, config, progress_callback=None) -> Dict[str, Any]:
    quality = f"bestvideo[height<={config.preferred_quality}]+bestaudio/best"
    cookiefile = get_netscape_cookie_path(config.cookies_file)
    
    opts = {
        "format": quality,
        "merge_output_format": "mp4",
        "outtmpl": f"{config.download_dir}/%(title)s_%(id)s.%(ext)s",
        "cookiefile": cookiefile,
        "writethumbnail": True,
        "noplaylist": True,
        "postprocessor_args": {"merger": ["-movflags", "+faststart"]},
        "quiet": True,
        "no_warnings": True
    }

    if progress_callback:
        opts["progress_hooks"] = [progress_callback]

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        # yt-dlp prepare_filename gives the raw video filename, need to account for merge to mp4
        base_name = ydl.prepare_filename(info).rsplit(".", 1)[0]
        file_path = f"{base_name}.mp4"
        
        # fallback if mp4 is not the final extension (e.g., if it was already mp4 and didn't merge)
        if not os.path.exists(file_path):
            file_path = ydl.prepare_filename(info)

        return {
            "file_path": file_path,
            "file_size": os.path.getsize(file_path) if os.path.exists(file_path) else 0,
            "quality": f"{info.get('height', '?')}p",
        }

async def download_video(bvid: str, config, db, source: str = "auto", progress_callback=None) -> Dict[str, Any]:
    url = f"https://www.bilibili.com/video/{bvid}"
    
    try:
        log.info(f"Extracting info for {bvid}")
        info = await extract_video_info(url, config.cookies_file)
        estimated_size = (info.get("filesize_approx") or 500) * 1024 * 1024
        
        log.info(f"Ensuring disk space for {bvid}, estimated {estimated_size} bytes")
        await ensure_disk_space(estimated_size, config.download_dir, db, config.disk_reserve_mb)
        
        await db.update_video_status(bvid, "downloading")
        log.info(f"Starting download for {bvid}")
        
        result = await asyncio.to_thread(_download, url, config, progress_callback)
        
        await db.update_video_done(
            bvid=bvid,
            file_path=result["file_path"],
            file_size=result["file_size"],
            quality=result["quality"],
            source=source
        )
        log.info(f"Successfully downloaded {bvid} to {result['file_path']}")
        return result
        
    except Exception as e:
        log.error(f"Failed to download {bvid}: {str(e)}")
        await db.update_video_status(bvid, "failed", error_message=str(e))
        raise
