import io
import pickle
import aiohttp
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

TOKEN_FILE = "/root/rjbot/token.pickle"
DRIVE_FOLDER_ID = "1LXrAch1OLTix-w50xDJuzRZxgmess1If"

def get_drive_service():
    with open(TOKEN_FILE, "rb") as f:
        creds = pickle.load(f)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(TOKEN_FILE, "wb") as f:
            pickle.dump(creds, f)
    return build("drive", "v3", credentials=creds)

async def upload_receipt_to_drive(bot, file_id: str, filename: str, date_str: str) -> str:
    return await upload_telegram_file_to_drive(bot, file_id, filename, "image/jpeg")


async def upload_telegram_file_to_drive(bot, file_id: str, filename: str, mime_type: str = "image/jpeg") -> str:
    try:
        from config import BOT_TOKEN
        tg_file = await bot.get_file(file_id)
        url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{tg_file.file_path}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return ""
                file_bytes = await resp.read()
        service = get_drive_service()
        file_metadata = {"name": filename, "parents": [DRIVE_FOLDER_ID]}
        media = MediaIoBaseUpload(io.BytesIO(file_bytes), mimetype=mime_type, resumable=False)
        uploaded = service.files().create(
            body=file_metadata, media_body=media, fields="id"
        ).execute()
        service.permissions().create(
            fileId=uploaded["id"],
            body={"type": "anyone", "role": "reader"}
        ).execute()
        drive_id = uploaded.get("id", "")
        if mime_type.startswith("video"):
            link = f"https://drive.google.com/file/d/{drive_id}/view" if drive_id else ""
        else:
            link = f"https://drive.google.com/thumbnail?id={drive_id}&sz=w200" if drive_id else ""
        print(f"Uploaded: {filename} -> {link}")
        return link
    except Exception as e:
        print(f"Upload error: {e}")
        return ""
