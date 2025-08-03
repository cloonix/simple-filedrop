#!/usr/bin/env python3
"""
Ultra-Minimal File Sharing App
All features in one file: OIDC auth, upload/download, expiration, limits
"""
import os, secrets, sqlite3, asyncio, uvicorn, aiofiles
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, File, UploadFile, HTTPException, Request, Form, Depends, BackgroundTasks
from fastapi.responses import FileResponse, RedirectResponse, HTMLResponse
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
app.add_middleware(SessionMiddleware, secret_key=SESSION_KEY)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# Auth
oauth = OAuth()
if OIDC_ID: oauth.register('oidc', client_id=OIDC_ID, client_secret=OIDC_SECRET, server_metadata_url=OIDC_URL, client_kwargs={'scope': 'openid profile email'})

def auth(request: Request): return not OIDC_ID or request.session.get('user')

@app.get("/auth/login")
async def login(request: Request): return await oauth.oidc.authorize_redirect(request, os.getenv("OIDC_REDIRECT_URI", "http://localhost:8000/auth/callback"))

@app.get("/auth/callback") 
async def callback(request: Request):
    try: token = await oauth.oidc.authorize_access_token(request); request.session['user'] = token.get('userinfo'); return RedirectResponse("/")
    except: raise HTTPException(400, "Auth failed")

@app.post("/auth/logout")
async def logout(request: Request): request.session.clear(); return {"ok": True}

@app.get("/auth/me")
async def me(request: Request): return {"authenticated": auth(request)}

# API
@app.post("/api/upload")
async def upload(file: UploadFile = File(...), max_downloads: Optional[int] = Form(None), expiration_days: int = Form(1), authenticated: bool = Depends(auth)):
    if not authenticated: raise HTTPException(401, "Auth required")
    if not file.filename: raise HTTPException(400, "No file")
    
    clean_filename = os.path.basename(file.filename)
    
    token = secrets.token_urlsafe(16)
    expires = datetime.utcnow() + timedelta(days=expiration_days)
    path = UPLOADS / f"{token}-{clean_filename}"
    
    async with aiofiles.open(path, 'wb') as f: await f.write(await file.read())
    
    conn = sqlite3.connect(DB)
    conn.execute("INSERT INTO files (filename, token, expires_at, max_downloads) VALUES (?, ?, ?, ?)", (clean_filename, token, expires, max_downloads))
    conn.commit(); conn.close()
    
    return {"token": token, "expires_at": expires.isoformat(), "max_downloads": max_downloads}

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
    return FileResponse("static/index.html")

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
    uvicorn.run(app, host="0.0.0.0", port=8000)