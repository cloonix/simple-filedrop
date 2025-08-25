# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

**Local Development Setup:**
```bash
# Create and activate virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate   # Windows

# Install dependencies
pip install -r requirements.txt

# Set environment for testing (optional - disables OIDC auth)
export OIDC_CLIENT_ID=""  # Empty to disable auth

# Run application
python app/main.py
```

**Docker Development:**
```bash
# Build and start with Docker Compose
docker-compose up -d

# View logs
docker-compose logs -f

# Stop application
docker-compose down
```

**Configuration:**
- Copy `.env.example` to `.env` and configure environment variables
- Set `DEV_MODE=true` for development without OIDC authentication
- Configure OIDC settings for production authentication

## Architecture Overview

**Single-File Backend Philosophy:**
- All backend logic consolidated in `app/main.py` (~264 lines)
- FastAPI application with SQLite database, OIDC auth, and file management
- Minimal dependencies for maximum maintainability

**Key Components:**

1. **Authentication (`app/main.py:60-91`)**
   - OIDC/OAuth integration using authlib
   - Session-based authentication with secure cookies
   - Development mode bypass for testing

2. **File Management (`app/main.py:99-244`)**
   - Upload with progress tracking and size limits
   - Download with token-based access and limits
   - Automatic cleanup of expired/limit-reached files
   - Background tasks for periodic cleanup

3. **Database Schema (`app/main.py:32-38`)**
   - SQLite with files table: id, filename, token, expires_at, max_downloads, download_count, created_at
   - Tokens are URL-safe random strings for secure file access

4. **Frontend (`app/static/`)**
   - Single-page Vue.js 3 application (`app.js`)
   - Glassmorphism dark theme with Tailwind CSS (`styles.css`)
   - Drag & drop file upload with progress indicators (`index.html`)

**File Storage:**
- Files stored in `uploads/` directory with format: `{token}-{filename}`
- Database tracks metadata while filesystem stores actual files
- Automatic cleanup removes both database entries and files

**Security Features:**
- OIDC authentication required for all operations (unless DEV_MODE)
- Cryptographically secure tokens for file access
- File size limits and download count restrictions
- Automatic expiration and cleanup
- No direct file system exposure

## Environment Variables

Required for production:
- `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, `OIDC_DISCOVERY_URL` - OIDC authentication
- `SESSION_SECRET` - Secure session encryption key

Optional configuration:
- `DATABASE_PATH` - SQLite database location (default: app.db)
- `MAX_FILE_SIZE` - Upload size limit in bytes (default: 100MB)
- `APP_TITLE`, `APP_SUBTITLE` - Custom branding
- `DEV_MODE` - Disable auth for development (default: false)
- `CORS_ALLOWED_ORIGINS` - CORS configuration

## API Structure

**Authentication endpoints:** `/auth/login`, `/auth/callback`, `/auth/logout`, `/auth/me`
**File operations:** `/api/upload`, `/api/files`, `/share/{token}`, `/api/files/{id}`
**Frontend:** Static files served from `/static/`, main app at `/`

## Testing and Development Notes

- No package.json - this is a Python/FastAPI application, not Node.js
- No formal test framework configured - manual testing via web interface
- Use `DEV_MODE=true` or empty `OIDC_CLIENT_ID` to disable authentication for testing
- Application runs on port 8000 by default
- Background cleanup task runs every hour to remove expired files