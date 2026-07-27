import time
import hashlib
import aiohttp
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from config import WANWAY_APPID, WANWAY_KEY, WANWAY_BASE_URL, BIKES

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

_token_cache = {"token": None, "expires_at": 0}

def _md5(text: str) -> str:
    import hashlib
    return hashlib.md5(text.encode()).hexdigest()

async def _get_token():
    now = time.time()
    if _token_cache["token"] and now < _token_cache["expires_at"]:
        return _token_cache["token"]
    ts = int(now)
    signature = _md5(_md5(WANWAY_KEY) + str(ts))
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{WANWAY_BASE_URL}/auth",
            json={"appid": WANWAY_APPID, "time": ts, "signature": signature}
        ) as resp:
            data = await resp.json(content_type=None)
            if data.get("code") == 0:
                _token_cache["token"] = data["accessToken"]
                _token_cache["expires_at"] = now + 5400
                return _token_cache["token"]
    return None

@app.get("/bikes")
async def get_bikes():
    token = await _get_token()
    if not token:
        return JSONResponse({"error": "auth failed"}, headers={"Access-Control-Allow-Origin": "*"})
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{WANWAY_BASE_URL}/device/status",
            headers={"accessToken": token}
        ) as resp:
            data = await resp.json(content_type=None)
            result = []
            for d in data.get("data", []):
                imei = d.get("imei", "")
                bike = BIKES.get(imei, {})
                result.append({
                    "imei": imei,
                    "name": bike.get("name", imei),
                    "type": bike.get("type", "unknown"),
                    "lat": float(d.get("lat", 0)),
                    "lng": float(d.get("lng", 0)),
                    "speed": d.get("speed", 0),
                    "acc": d.get("accStatus", False),
                    "voltage": d.get("extVoltage", 0),
                    "gpsTime": d.get("gpsTime", 0),
                })
            return JSONResponse({"bikes": result}, headers={"Access-Control-Allow-Origin": "*"})

@app.options("/bikes")
async def options_bikes():
    return JSONResponse({}, headers={
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, OPTIONS",
        "Access-Control-Allow-Headers": "*",
    })
