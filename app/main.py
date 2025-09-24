#!/usr/bin/env python3
"""
Ultra-Minimal File Sharing App
All features in one file: OIDC auth, upload/download, expiration, limits
"""
import os, secrets, sqlite3, asyncio, uvicorn, aiofiles, uuid, logging, time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, File, UploadFile, HTTPException, Request, Form, Depends, BackgroundTasks, Header
from fastapi.responses import FileResponse, RedirectResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from authlib.integrations.starlette_client import OAuth, OAuthError
from starlette.middleware.sessions import SessionMiddleware

# Config
DB = os.getenv("DATABASE_PATH", "app.db")
UPLOADS = Path("uploads")
UPLOADS.mkdir(exist_ok=True)
OIDC_ID = os.getenv("OIDC_CLIENT_ID")
OIDC_SECRET = os.getenv("OIDC_CLIENT_SECRET") 
OIDC_URL = os.getenv("OIDC_DISCOVERY_URL")
SESSION_KEY = os.getenv("SESSION_SECRET", secrets.token_hex(32))
APP_TITLE = os.getenv("APP_TITLE", "Simple Filedrop")
APP_SUBTITLE = os.getenv("APP_SUBTITLE", "Simple file sharing")
CORS_ALLOWED_ORIGINS = os.getenv("CORS_ALLOWED_ORIGINS", "").split(",")
DEV_MODE = os.getenv("DEV_MODE", "false").lower() == "true"
MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE", str(100 * 1024 * 1024)))  # 100MB default
BUILD_TIMESTAMP = int(time.time())  # Build timestamp for cache busting

# Database
def init_db():
    conn = sqlite3.connect(DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS files (
        id INTEGER PRIMARY KEY, filename TEXT, token TEXT UNIQUE, 
        expires_at TIMESTAMP, max_downloads INTEGER, download_count INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    conn.commit(); conn.close()

def cleanup():
    conn = sqlite3.connect(DB)
    cursor = conn.execute("SELECT token, filename FROM files WHERE expires_at < ? OR (max_downloads IS NOT NULL AND download_count >= max_downloads)", (datetime.utcnow(),))
    for token, filename in cursor: (UPLOADS / f"{token}-{filename}").unlink(missing_ok=True)
    conn.execute("DELETE FROM files WHERE expires_at < ? OR (max_downloads IS NOT NULL AND download_count >= max_downloads)", (datetime.utcnow(),))
    conn.commit(); conn.close()

# App
app = FastAPI(title="File Share")

# Configure max request body size to match MAX_FILE_SIZE
from fastapi.middleware.trustedhost import TrustedHostMiddleware
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["*"])

# Configure body size limit for large file uploads
import uvicorn
from starlette.middleware.base import BaseHTTPMiddleware

class MaxBodySizeMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_body_size: int):
        super().__init__(app)
        self.max_body_size = max_body_size

    async def dispatch(self, request, call_next):
        if request.headers.get("content-length"):
            content_length = int(request.headers.get("content-length", 0))
            if content_length > self.max_body_size:
                return JSONResponse(
                    status_code=413,
                    content={"detail": f"Request body too large. Maximum size: {self.max_body_size // (1024*1024)}MB"}
                )
        return await call_next(request)

app.add_middleware(MaxBodySizeMiddleware, max_body_size=MAX_FILE_SIZE)
app.add_middleware(SessionMiddleware, 
    secret_key=SESSION_KEY, 
    same_site="strict")
app.add_middleware(CORSMiddleware, 
    allow_origins=CORS_ALLOWED_ORIGINS, 
    allow_credentials=True, 
    allow_methods=["GET", "POST", "DELETE"], 
    allow_headers=["Content-Type", "Authorization", "X-Requested-With"])

upload_progress = {}

# Auth
oauth = OAuth()
if OIDC_ID: oauth.register('oidc', client_id=OIDC_ID, client_secret=OIDC_SECRET, server_metadata_url=OIDC_URL, client_kwargs={'scope': 'openid profile email'})

def auth(request: Request): 
    if not OIDC_ID and not DEV_MODE:
        raise HTTPException(401, "Authentication required - OIDC not configured")
    return DEV_MODE or request.session.get('user')

@app.get("/auth/login")
async def login(request: Request): return await oauth.oidc.authorize_redirect(request, os.getenv("OIDC_REDIRECT_URI", "http://localhost:8000/auth/callback"))

@app.get("/auth/callback") 
async def callback(request: Request):
    try: 
        token = await oauth.oidc.authorize_access_token(request)
        request.session['user'] = token.get('userinfo')
        return RedirectResponse("/")
    except OAuthError as e:
        logging.warning(f"OAuth error during callback: {type(e).__name__}")
        raise HTTPException(400, "Authentication failed")
    except Exception as e:
        logging.error(f"Unexpected error during auth callback: {type(e).__name__}")
        raise HTTPException(500, "Authentication service temporarily unavailable")

@app.post("/auth/logout")
async def logout(request: Request): request.session.clear(); return {"ok": True}

@app.get("/auth/me")
async def me(request: Request):
    return {"authenticated": auth(request)}


@app.get("/api/config")
async def config():
    return {
        "title": APP_TITLE,
        "subtitle": APP_SUBTITLE,
        "max_file_size": MAX_FILE_SIZE,
        "build_timestamp": BUILD_TIMESTAMP
    }


# API
@app.post("/api/upload")
async def upload(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    max_downloads: Optional[int] = Form(None, ge=1, le=1000),
    expiration_days: int = Form(1, ge=1, le=30),
    authenticated: bool = Depends(auth),
):
    if not authenticated:
        raise HTTPException(401, "Auth required")
    if not file.filename:
        raise HTTPException(400, "No file")
    
    # Check file size
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > MAX_FILE_SIZE:
        raise HTTPException(413, f"File too large. Maximum size: {MAX_FILE_SIZE // (1024*1024)}MB")
    
    # Additional file size check during upload
    file_size = 0

    clean_filename = os.path.basename(file.filename)
    token = secrets.token_urlsafe(16)
    expires = datetime.utcnow() + timedelta(days=expiration_days)
    path = UPLOADS / f"{token}-{clean_filename}"
    upload_id = str(uuid.uuid4())

    upload_progress[upload_id] = {"total": 0, "uploaded": 0, "status": "starting"}
    
    try:
        total_size = int(request.headers.get("content-length", 0))
        upload_progress[upload_id]["total"] = total_size
        
        async with aiofiles.open(path, 'wb') as f:
            while chunk := await file.read(1024 * 1024):  # Read in 1MB chunks
                file_size += len(chunk)
                if file_size > MAX_FILE_SIZE:
                    await f.close()
                    path.unlink(missing_ok=True)  # Clean up partial file
                    raise HTTPException(413, f"File too large. Maximum size: {MAX_FILE_SIZE // (1024*1024)}MB")
                
                await f.write(chunk)
                upload_progress[upload_id]["uploaded"] += len(chunk)
                upload_progress[upload_id]["status"] = "uploading"

        conn = sqlite3.connect(DB)
        conn.execute(
            "INSERT INTO files (filename, token, expires_at, max_downloads) VALUES (?, ?, ?, ?)",
            (clean_filename, token, expires, max_downloads),
        )
        conn.commit()
        conn.close()
        
        upload_progress[upload_id]["status"] = "completed"
        background_tasks.add_task(cleanup_upload_progress, upload_id)

        return JSONResponse(content={"token": token, "expires_at": expires.isoformat(), "max_downloads": max_downloads, "upload_id": upload_id})

    except HTTPException:
        # Re-raise HTTP exceptions (like file size limit)
        upload_progress[upload_id]["status"] = "failed"
        background_tasks.add_task(cleanup_upload_progress, upload_id)
        raise
    except Exception as e:
        logging.error(f"Upload failed: {type(e).__name__} - {str(e)[:100]}")
        upload_progress[upload_id]["status"] = "failed"
        background_tasks.add_task(cleanup_upload_progress, upload_id)
        # Clean up partial file if it exists
        if 'path' in locals():
            path.unlink(missing_ok=True)
        raise HTTPException(500, "Upload failed due to an internal error")

@app.get("/api/upload/progress/{upload_id}")
async def get_upload_progress(upload_id: str):
    progress = upload_progress.get(upload_id)
    if not progress:
        raise HTTPException(404, "Upload not found")
    return JSONResponse(content=progress)

async def cleanup_upload_progress(upload_id: str):
    await asyncio.sleep(300)  # Keep progress for 5 minutes
    upload_progress.pop(upload_id, None)

@app.get("/api/files")
async def files(authenticated: bool = Depends(auth)):
    if not authenticated: raise HTTPException(401, "Auth required")
    conn = sqlite3.connect(DB)
    cursor = conn.execute("SELECT id, filename, token, expires_at, max_downloads, download_count FROM files WHERE expires_at > ?", (datetime.utcnow(),))
    result = [{"id": r[0], "filename": r[1], "share_id": r[2], "expires_at": r[3], "max_downloads": r[4], "download_count": r[5]} for r in cursor]
    conn.close(); return result

@app.get("/share/{token}")
async def download(token: str, background_tasks: BackgroundTasks):
    conn = sqlite3.connect(DB)
    cursor = conn.execute("SELECT filename, expires_at, max_downloads, download_count FROM files WHERE token = ?", (token,))
    row = cursor.fetchone()
    if not row: raise HTTPException(404, "Not found")
    
    filename, expires_at, max_downloads, download_count = row
    if datetime.fromisoformat(expires_at.replace('Z', '+00:00')) < datetime.utcnow(): raise HTTPException(410, "Expired")
    if max_downloads and download_count >= max_downloads: raise HTTPException(410, "Limit reached")
    
    path = UPLOADS / f"{token}-{filename}"
    if not path.exists(): raise HTTPException(404, "File missing")
    
    # Increment download count
    new_download_count = download_count + 1
    conn.execute("UPDATE files SET download_count = ? WHERE token = ?", (new_download_count, token))
    conn.commit()
    
    # Check if max downloads reached after this download
    if max_downloads and new_download_count >= max_downloads:
        # Delete from database immediately
        conn.execute("DELETE FROM files WHERE token = ?", (token,))
        conn.commit()
        conn.close()
        
        # Schedule file deletion after response is sent
        background_tasks.add_task(cleanup_file, path)
        
        return FileResponse(path, filename=filename)
    else:
        conn.close()
        return FileResponse(path, filename=filename)

def cleanup_file(file_path: Path):
    """Delete file after download is complete"""
    try:
        file_path.unlink(missing_ok=True)
    except Exception:
        pass  # Ignore errors during cleanup

@app.delete("/api/files/{file_id}")
async def delete(file_id: int, authenticated: bool = Depends(auth)):
    if not authenticated: raise HTTPException(401, "Auth required")
    conn = sqlite3.connect(DB)
    cursor = conn.execute("SELECT token, filename FROM files WHERE id = ?", (file_id,))
    row = cursor.fetchone()
    if not row: raise HTTPException(404, "Not found")
    
    token, filename = row
    (UPLOADS / f"{token}-{filename}").unlink(missing_ok=True)
    conn.execute("DELETE FROM files WHERE id = ?", (file_id,))
    conn.commit(); conn.close()
    return {"ok": True}

# Frontend
@app.get("/")
async def index():
    # Read the HTML template and inject build timestamp
    with open("static/index.html", "r") as f:
        html_content = f.read()

    # Replace placeholders with actual values
    html_content = html_content.replace("{{BUILD_TIMESTAMP}}", str(BUILD_TIMESTAMP))

    return HTMLResponse(content=html_content)

# Serve static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Startup
async def startup():
    init_db(); cleanup()
    asyncio.create_task(periodic_cleanup())

async def periodic_cleanup():
    while True: await asyncio.sleep(3600); cleanup()

if __name__ == "__main__":
    asyncio.run(startup())
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        timeout_keep_alive=300,  # 5 minutes
        limit_max_requests=None,
        limit_concurrency=None
    )