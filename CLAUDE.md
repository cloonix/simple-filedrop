# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Simple Filedrop is an ultra-minimal file sharing application built with FastAPI backend and Vue.js frontend. The entire backend is contained in a single file (`app/main.py`) for maximum simplicity and maintainability.

## Development Commands

### Running the Application
```bash
# Development mode (from project root)
cd app
python -m pip install -r ../requirements.txt
python main.py

# Production with Docker
docker-compose up -d

# Disable auth for testing
export OIDC_CLIENT_ID=""
python app/main.py
```

### Database and Cleanup
- SQLite database is automatically initialized on startup
- Automatic cleanup runs every hour to remove expired files
- Database schema is created in `init_db()` function in main.py:30

## Architecture

### Single-File Backend Design
- **All backend logic in `app/main.py`** (~220 lines total)
- FastAPI application with OIDC authentication, file upload/download, and automatic cleanup
- SQLite database for file metadata tracking
- Background tasks for file cleanup and upload progress tracking

### Frontend Structure
- `static/index.html` - Main HTML structure
- `static/styles.css` - Tailwind CSS with dark glassmorphism theme  
- `static/app.js` - Vue.js 3 application with reactive state management

### Key Components
- **Authentication**: OIDC integration via authlib, session-based auth
- **File Management**: Upload with progress tracking, download limits, automatic expiration
- **Database**: Single table `files` with metadata (filename, token, expires_at, max_downloads, download_count)
- **File Storage**: Files stored in `uploads/` directory with format `{token}-{filename}`

## Configuration

Environment variables are loaded from `.env` file:
- `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, `OIDC_DISCOVERY_URL` - OIDC authentication
- `DATABASE_PATH` - SQLite database location (default: `app.db`)
- `SESSION_SECRET` - Session encryption key
- `APP_TITLE`, `APP_SUBTITLE` - Configurable application branding

## Key Patterns

### File Upload Flow
1. Upload creates unique token via `secrets.token_urlsafe(16)`
2. File stored as `{token}-{filename}` in uploads directory
3. Metadata stored in database with expiration and download limits
4. Upload progress tracked in memory (`upload_progress` dict)

### Authentication Pattern
- `auth()` dependency function checks session or allows bypass if `OIDC_CLIENT_ID` is unset
- OIDC callback stores user info in session
- All API endpoints except `/share/{token}` require authentication

### Cleanup System
- `cleanup()` function removes expired files and database entries
- `periodic_cleanup()` runs every 3600 seconds
- Files with reached download limits are immediately cleaned up after download

## Dependencies

Core dependencies from `requirements.txt`:
- `fastapi` - Web framework
- `uvicorn` - ASGI server
- `aiofiles` - Async file operations
- `authlib` - OIDC authentication
- `python-multipart` - File upload support