import os
import aiosqlite
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional

log = logging.getLogger('bilidown')

class Database:
    def __init__(self, db_path: str = "./data/bilidown.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)

    async def init(self):
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute('''
                CREATE TABLE IF NOT EXISTS uploaders (
                    mid           INTEGER PRIMARY KEY,
                    name          TEXT NOT NULL,
                    face_url      TEXT,
                    is_tracked    BOOLEAN DEFAULT 0,
                    tracked_since DATETIME,
                    last_check    DATETIME,
                    created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            await db.execute('''
                CREATE TABLE IF NOT EXISTS videos (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    bvid          TEXT UNIQUE NOT NULL,
                    aid           INTEGER,
                    mid           INTEGER NOT NULL,
                    title         TEXT NOT NULL,
                    description   TEXT,
                    duration      INTEGER,
                    thumbnail_url TEXT,
                    upload_time   DATETIME NOT NULL,
                    
                    source        TEXT NOT NULL,
                    status        TEXT DEFAULT 'pending',
                    file_path     TEXT,
                    file_size     INTEGER,
                    quality       TEXT,
                    downloaded_at DATETIME,
                    error_message TEXT,
                    
                    created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (mid) REFERENCES uploaders(mid)
                )
            ''')
            await db.commit()

    async def _fetch_all(self, query: str, params: tuple = ()) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, params) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    async def _fetch_one(self, query: str, params: tuple = ()) -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, params) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def _execute(self, query: str, params: tuple = ()) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(query, params)
            await db.commit()

    async def get_tracked_uploaders(self) -> List[Dict[str, Any]]:
        return await self._fetch_all("SELECT * FROM uploaders WHERE is_tracked = 1")

    async def get_all_uploaders(self) -> List[Dict[str, Any]]:
        return await self._fetch_all("SELECT * FROM uploaders ORDER BY created_at DESC")

    async def add_uploader(self, mid: int, name: str, face_url: str, is_tracked: bool, tracked_since: datetime):
        await self._execute(
            """
            INSERT INTO uploaders (mid, name, face_url, is_tracked, tracked_since)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(mid) DO UPDATE SET
                name = excluded.name,
                face_url = excluded.face_url,
                is_tracked = excluded.is_tracked,
                tracked_since = COALESCE(uploaders.tracked_since, excluded.tracked_since)
            """,
            (mid, name, face_url, 1 if is_tracked else 0, tracked_since)
        )

    async def remove_tracker(self, mid: int):
        await self._execute("UPDATE uploaders SET is_tracked = 0 WHERE mid = ?", (mid,))

    async def update_last_check(self, mid: int):
        await self._execute("UPDATE uploaders SET last_check = ? WHERE mid = ?", (datetime.now(), mid))

    async def get_uploader(self, mid: int) -> Optional[Dict[str, Any]]:
        return await self._fetch_one("SELECT * FROM uploaders WHERE mid = ?", (mid,))

    async def video_exists(self, bvid: str) -> bool:
        row = await self._fetch_one("SELECT 1 FROM videos WHERE bvid = ?", (bvid,))
        return row is not None

    async def insert_video(self, video_data: dict, source: str, status: str = 'pending'):
        upload_time = datetime.fromtimestamp(video_data["created"])
        await self._execute(
            """
            INSERT OR IGNORE INTO videos (
                bvid, aid, mid, title, description, duration, 
                thumbnail_url, upload_time, source, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                video_data["bvid"], video_data.get("aid"), video_data["mid"],
                video_data["title"], video_data.get("description", ""), video_data.get("length", 0),
                video_data.get("pic", ""), upload_time, source, status
            )
        )

    async def update_video_status(self, bvid: str, status: str, error_message: str = None):
        await self._execute(
            "UPDATE videos SET status = ?, error_message = ? WHERE bvid = ?",
            (status, error_message, bvid)
        )

    async def update_video_done(self, bvid: str, file_path: str, file_size: int, quality: str, source: str):
        await self._execute(
            """
            UPDATE videos SET 
                status = 'done', 
                file_path = ?, 
                file_size = ?, 
                quality = ?, 
                downloaded_at = ?,
                source = ?
            WHERE bvid = ?
            """,
            (file_path, file_size, quality, datetime.now(), source, bvid)
        )

    async def get_videos(self, page: int = 1, per_page: int = 20, source_filter: str = None, mid_filter: int = None, search: str = None) -> Dict[str, Any]:
        offset = (page - 1) * per_page
        query = "SELECT videos.*, uploaders.name as uploader_name FROM videos LEFT JOIN uploaders ON videos.mid = uploaders.mid WHERE 1=1"
        count_query = "SELECT COUNT(*) as total FROM videos LEFT JOIN uploaders ON videos.mid = uploaders.mid WHERE 1=1"
        params = []
        
        if source_filter:
            query += " AND videos.source = ?"
            count_query += " AND videos.source = ?"
            params.append(source_filter)
        if mid_filter:
            query += " AND videos.mid = ?"
            count_query += " AND videos.mid = ?"
            params.append(mid_filter)
        if search:
            query += " AND (videos.title LIKE ? OR uploaders.name LIKE ?)"
            count_query += " AND (videos.title LIKE ? OR uploaders.name LIKE ?)"
            search_term = f"%{search}%"
            params.extend([search_term, search_term])
            
        query += " ORDER BY videos.upload_time DESC LIMIT ? OFFSET ?"
        
        total_row = await self._fetch_one(count_query, tuple(params))
        total = total_row["total"] if total_row else 0
        
        params.extend([per_page, offset])
        items = await self._fetch_all(query, tuple(params))
        
        return {
            "items": items,
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": (total + per_page - 1) // per_page
        }

    async def get_video(self, bvid: str) -> Optional[Dict[str, Any]]:
        return await self._fetch_one("SELECT * FROM videos WHERE bvid = ?", (bvid,))

    async def delete_video(self, bvid: str) -> Optional[str]:
        video = await self.get_video(bvid)
        if not video:
            return None
        file_path = video.get("file_path")
        await self._execute("DELETE FROM videos WHERE bvid = ?", (bvid,))
        return file_path

    async def get_oldest_done_video(self) -> Optional[Dict[str, Any]]:
        return await self._fetch_one(
            "SELECT id, bvid, file_path FROM videos WHERE status='done' AND file_path IS NOT NULL ORDER BY downloaded_at ASC LIMIT 1"
        )

    async def mark_video_cleaned(self, video_id: int):
        await self._execute(
            "UPDATE videos SET status='cleaned', file_path=NULL, file_size=NULL WHERE id=?", 
            (video_id,)
        )

    async def get_pending_videos(self, limit: int) -> List[Dict[str, Any]]:
        return await self._fetch_all(
            "SELECT * FROM videos WHERE status = 'pending' ORDER BY created_at ASC LIMIT ?", 
            (limit,)
        )

    async def get_download_queue_count(self) -> int:
        row = await self._fetch_one("SELECT COUNT(*) as count FROM videos WHERE status IN ('pending', 'downloading')")
        return row["count"] if row else 0

    async def get_stats(self) -> Dict[str, Any]:
        videos_count = await self._fetch_one("SELECT COUNT(*) as count FROM videos WHERE status = 'done'")
        total_size = await self._fetch_one("SELECT SUM(file_size) as total FROM videos WHERE status = 'done'")
        queue_count = await self.get_download_queue_count()
        uploaders_count = await self._fetch_one("SELECT COUNT(*) as count FROM uploaders WHERE is_tracked = 1")
        
        return {
            "total_videos": videos_count["count"] if videos_count else 0,
            "total_size": total_size["total"] if total_size and total_size["total"] else 0,
            "queue_count": queue_count,
            "tracked_uploaders": uploaders_count["count"] if uploaders_count else 0
        }
