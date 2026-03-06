from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.templating import Jinja2Templates
import yt_dlp
import os, shutil, tempfile, json, time
from typing import Optional
from pathlib import Path

app = FastAPI(title="AnyDownloader", version="2.0.0")
templates = Jinja2Templates(directory="templates")

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

HISTORY_FILE = "history.json"

def load_history() -> list:
    if not Path(HISTORY_FILE).exists():
        return []
    try:
        with open(HISTORY_FILE, "r") as f:
            return json.load(f)
    except:
        return []

def save_history(entry: dict):
    history = load_history()
    history.insert(0, entry)
    history = history[:50]
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f)

@app.get("/")
def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/api/info")
def get_info(url: str = Query(...)):
    try:
        opts = {"quiet": True, "no_warnings": True, "skip_download": True}
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)

        formats = []
        seen = set()
        for f in info.get("formats", []):
            res = f.get("resolution") or f.get("format_note", "")
            ext = f.get("ext", "")
            key = f"{res}-{ext}"
            if key in seen:
                continue
            seen.add(key)
            vcodec = f.get("vcodec", "none")
            acodec = f.get("acodec", "none")
            if vcodec == "none" and acodec == "none":
                continue
            formats.append({
                "format_id": f.get("format_id"),
                "ext": ext,
                "resolution": res,
                "fps": f.get("fps"),
                "vcodec": vcodec,
                "acodec": acodec,
                "filesize": f.get("filesize") or f.get("filesize_approx"),
                "has_video": vcodec != "none",
                "has_audio": acodec != "none",
            })

        return {
            "title": info.get("title"),
            "thumbnail": info.get("thumbnail"),
            "duration": info.get("duration"),
            "uploader": info.get("uploader"),
            "platform": info.get("extractor_key"),
            "webpage_url": info.get("webpage_url"),
            "formats": formats,
        }
    except yt_dlp.utils.DownloadError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/download")
def download(
    url: str = Query(...),
    format: Optional[str] = Query("bestvideo+bestaudio/best"),
    audio_only: bool = Query(False),
    title: Optional[str] = Query(None),
    thumbnail: Optional[str] = Query(None),
    platform: Optional[str] = Query(None),
):
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "%(title)s.%(ext)s")
            opts = {
                "quiet": True,
                "no_warnings": True,
                "noplaylist": True,
                "outtmpl": output_path,
            }

            if audio_only:
                opts["format"] = "bestaudio/best"
                opts["postprocessors"] = [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }]
            else:
                opts["format"] = format
                opts["merge_output_format"] = "mp4"

            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)

            files = os.listdir(tmpdir)
            if not files:
                raise HTTPException(status_code=500, detail="File tidak ditemukan")

            src = os.path.join(tmpdir, files[0])
            filename = files[0]
            persistent_path = f"/tmp/{int(time.time()*1000)}_{filename}"
            shutil.copy2(src, persistent_path)
            filesize = os.path.getsize(persistent_path)

        media_type = "audio/mpeg" if audio_only else "video/mp4"

        save_history({
            "id": str(int(time.time() * 1000)),
            "url": url,
            "title": title or info.get("title", "Unknown"),
            "thumbnail": thumbnail or info.get("thumbnail", ""),
            "platform": platform or info.get("extractor_key", ""),
            "filename": filename,
            "type": "audio" if audio_only else "video",
            "format": "MP3" if audio_only else format,
            "timestamp": int(time.time()),
            "filesize": filesize,
        })

        def stream_file():
            try:
                with open(persistent_path, "rb") as f:
                    while chunk := f.read(512 * 1024):
                        yield chunk
            finally:
                try:
                    os.remove(persistent_path)
                except:
                    pass

        return StreamingResponse(
            stream_file(),
            media_type=media_type,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Content-Length": str(filesize),
            }
        )

    except yt_dlp.utils.DownloadError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/history")
def get_history():
    return load_history()

@app.delete("/api/history")
def clear_history():
    with open(HISTORY_FILE, "w") as f:
        json.dump([], f)
    return {"status": "cleared"}

@app.delete("/api/history/{item_id}")
def delete_history_item(item_id: str):
    history = load_history()
    history = [h for h in history if h.get("id") != item_id]
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f)
    return {"status": "deleted"}

@app.get("/api/health")
def health():
    return {"status": "ok"}