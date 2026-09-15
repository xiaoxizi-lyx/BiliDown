import shutil
from pathlib import Path
import logging
from typing import Dict, Any

log = logging.getLogger("bilidown.disk")

class DiskFullError(Exception):
    pass

async def get_disk_usage(path: str) -> Dict[str, int]:
    Path(path).mkdir(parents=True, exist_ok=True)
    usage = shutil.disk_usage(path)
    return {
        "total": usage.total,
        "used": usage.used,
        "free": usage.free
    }

async def ensure_disk_space(needed_bytes: int, video_dir: str, db, reserve_mb: int = 500) -> bool:
    """Ensure sufficient disk space before downloading."""
    Path(video_dir).mkdir(parents=True, exist_ok=True)
    reserve_bytes = reserve_mb * 1024 * 1024

    while True:
        usage = shutil.disk_usage(video_dir)
        if usage.free >= needed_bytes + reserve_bytes:
            return True
        
        # Find oldest done video
        oldest = await db.get_oldest_done_video()
        if not oldest:
            raise DiskFullError("Insufficient disk space and no old videos to clean.")
        
        path = Path(oldest["file_path"])
        if path.exists():
            path.unlink()
            
        await db.mark_video_cleaned(oldest["id"])
        log.info(f"Low disk space. Cleaned up old video: {oldest['bvid']} ({oldest['file_path']})")
