import httpx
import time
import hashlib
import urllib.parse
from functools import reduce
from typing import Dict, Any, Tuple
import logging

from app.cookie_helper import get_cookie_dict

log = logging.getLogger("bilidown.wbi")

def get_bili_client(cookies_file: str = "cookies.txt") -> httpx.AsyncClient:
    cookies = get_cookie_dict(cookies_file)
    cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Referer": "https://www.bilibili.com",
        "Origin": "https://www.bilibili.com",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-site",
    }
    if cookie_str:
        headers["Cookie"] = cookie_str
    return httpx.AsyncClient(headers=headers, cookies=cookies, timeout=15.0)

MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
    33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40,
    61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11,
    36, 20, 34, 44, 52
]

_wbi_keys_cache: Dict[str, Any] = {"img_key": "", "sub_key": "", "timestamp": 0}

def get_mixin_key(orig: str) -> str:
    return reduce(lambda s, i: s + orig[i], MIXIN_KEY_ENC_TAB, '')[:32]

def enc_wbi(params: dict, img_key: str, sub_key: str) -> dict:
    mixin_key = get_mixin_key(img_key + sub_key)
    curr_time = round(time.time())
    params['wts'] = curr_time
    
    # Sort and format params
    sorted_params = sorted(params.items())
    query = []
    for k, v in sorted_params:
        # Strip specific characters as per Bilibili requirements
        val = str(v).replace("!", "").replace("'", "").replace("(", "").replace(")", "").replace("*", "")
        query.append(f"{urllib.parse.quote(str(k))}={urllib.parse.quote(str(val))}")
        
    query_str = '&'.join(query)
    hash_str = query_str + mixin_key
    wbi_sign = hashlib.md5(hash_str.encode('utf-8')).hexdigest()
    
    params['w_rid'] = wbi_sign
    return params

async def get_wbi_keys(client: httpx.AsyncClient) -> Tuple[str, str]:
    global _wbi_keys_cache
    now = time.time()
    
    # Cache for 30 minutes (1800 seconds)
    if now - _wbi_keys_cache["timestamp"] < 1800 and _wbi_keys_cache["img_key"]:
        return _wbi_keys_cache["img_key"], _wbi_keys_cache["sub_key"]
        
    resp = await client.get('https://api.bilibili.com/x/web-interface/nav')
    resp.raise_for_status()
    json_data = resp.json()
    
    wbi_img = json_data.get('data', {}).get('wbi_img', {})
    img_url = wbi_img.get('img_url', '')
    sub_url = wbi_img.get('sub_url', '')
    
    if img_url and sub_url:
        img_key = img_url.rsplit('/', 1)[1].split('.')[0]
        sub_key = sub_url.rsplit('/', 1)[1].split('.')[0]
        _wbi_keys_cache = {
            "img_key": img_key,
            "sub_key": sub_key,
            "timestamp": now
        }
        return img_key, sub_key

    # Hardcoded fallback keys if nav endpoint changes
    return "ea1ae52e550d478e99d6d4a4a7e87f08", "45f38fb907ee42c3a02d4be31b812835"

async def fetch_creator_videos(mid: int, page: int = 1, page_size: int = 30, cookies_file: str = "cookies.txt") -> Dict[str, Any]:
    async with get_bili_client(cookies_file) as client:
        img_key, sub_key = await get_wbi_keys(client)
        
        params = {
            "mid": mid,
            "ps": page_size,
            "tid": 0,
            "pn": page,
            "keyword": "",
            "order": "pubdate",
            "order_avoided": "true"
        }
        
        signed_params = enc_wbi(params, img_key, sub_key)
        
        resp = await client.get(
            'https://api.bilibili.com/x/space/wbi/arc/search',
            params=signed_params,
            headers={
                "Referer": f"https://space.bilibili.com/{mid}/video",
                "Origin": "https://space.bilibili.com"
            }
        )
        resp.raise_for_status()
        
        data = resp.json()
        if data.get("code") != 0:
            log.error(f"Failed to fetch videos for {mid}: {data.get('message')}")
            return {"list": {"vlist": []}, "page": {"count": 0}}
            
        return data["data"]

async def get_uploader_info(mid: int, cookies_file: str = "cookies.txt") -> Dict[str, Any]:
    async with get_bili_client(cookies_file) as client:
        # Strategy 1: WBI signed acc/info
        try:
            img_key, sub_key = await get_wbi_keys(client)
            params = enc_wbi({"mid": mid}, img_key, sub_key)
            resp = await client.get(
                'https://api.bilibili.com/x/space/wbi/acc/info',
                params=params,
                headers={
                    "Referer": f"https://space.bilibili.com/{mid}",
                    "Origin": "https://space.bilibili.com"
                }
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("code") == 0 and "data" in data:
                    return {
                        "name": data["data"].get("name", f"UP主_{mid}"),
                        "face_url": data["data"].get("face", "")
                    }
                log.warning(f"wbi/acc/info returned code {data.get('code')}: {data.get('message')}, trying fallback card API...")
        except Exception as e:
            log.warning(f"Error calling wbi/acc/info for {mid}: {e}, trying fallback...")

        # Strategy 2: Web-interface Card API
        try:
            resp = await client.get(
                'https://api.bilibili.com/x/web-interface/card',
                params={"mid": mid},
                headers={
                    "Referer": f"https://space.bilibili.com/{mid}",
                    "Origin": "https://space.bilibili.com"
                }
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("code") == 0 and "data" in data and "card" in data["data"]:
                    card = data["data"]["card"]
                    return {
                        "name": card.get("name", f"UP主_{mid}"),
                        "face_url": card.get("face", "")
                    }
                log.warning(f"card API returned code {data.get('code')}: {data.get('message')}")
        except Exception as e:
            log.warning(f"Error calling card API for {mid}: {e}")

        # Strategy 3: Graceful fallback so user is never blocked from tracking
        log.info(f"Using fallback display name for {mid}")
        return {
            "name": f"UP主_{mid}",
            "face_url": ""
        }
