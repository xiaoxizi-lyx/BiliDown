import httpx
import time
import hashlib
import urllib.parse
from functools import reduce
from typing import Dict, Any, Tuple
import logging

log = logging.getLogger("bilidown.wbi")

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
        query.append(f"{urllib.parse.quote(k)}={urllib.parse.quote(val)}")
        
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
    
    wbi_img = json_data['data']['wbi_img']
    img_url = wbi_img['img_url']
    sub_url = wbi_img['sub_url']
    
    img_key = img_url.rsplit('/', 1)[1].split('.')[0]
    sub_key = sub_url.rsplit('/', 1)[1].split('.')[0]
    
    _wbi_keys_cache = {
        "img_key": img_key,
        "sub_key": sub_key,
        "timestamp": now
    }
    
    return img_key, sub_key

async def fetch_creator_videos(mid: int, page: int = 1, page_size: int = 30) -> Dict[str, Any]:
    async with httpx.AsyncClient(headers={"User-Agent": "Mozilla/5.0"}) as client:
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
        
        resp = await client.get('https://api.bilibili.com/x/space/wbi/arc/search', params=signed_params)
        resp.raise_for_status()
        
        data = resp.json()
        if data.get("code") != 0:
            log.error(f"Failed to fetch videos for {mid}: {data.get('message')}")
            return {"list": {"vlist": []}, "page": {"count": 0}}
            
        return data["data"]

async def get_uploader_info(mid: int) -> Dict[str, Any]:
    async with httpx.AsyncClient(headers={"User-Agent": "Mozilla/5.0"}) as client:
        resp = await client.get('https://api.bilibili.com/x/space/acc/info', params={"mid": mid})
        resp.raise_for_status()
        
        data = resp.json()
        if data.get("code") != 0:
            log.error(f"Failed to fetch uploader info for {mid}: {data.get('message')}")
            return {"name": f"Unknown({mid})", "face_url": ""}
            
        return {
            "name": data["data"]["name"],
            "face_url": data["data"]["face"]
        }
