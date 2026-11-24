# SFU Video Call Server - AJAX Polling Version

This is a **cPanel-compatible** video call server using mediasoup SFU with **HTTP/AJAX polling** instead of WebSockets.

## Architecture

```
Browser (AJAX) → Django (Port 8000) → SFU Server (Port 3001)
```

## Why AJAX Polling?

- Works on shared hosting (cPanel)
- No WebSocket support required
- Standard HTTP requests
- Compatible with all web servers

## Prerequisites

- Node.js 18+
- npm or yarn

## Installation

```bash
cd mediasoup-server
npm install
```

## Running the Server

```bash
npm start
```

Server runs on port 3001 with HTTP REST API.

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/room/:roomId/join` | Join/create room |
| POST | `/api/transport/:id/connect` | Connect transport |
| POST | `/api/transport/:id/produce` | Produce media |
| POST | `/api/transport/:id/consume` | Consume media |
| GET | `/api/room/:roomId/poll/:peerId` | Poll for messages |
| POST | `/api/peer/:peerId/leave` | Leave room |
| GET | `/api/room/:roomId/status` | Room status |
| GET | `/health` | Health check |

## Django Configuration

Add to `.env`:
```env
MEDIASOUP_ENABLED=True
MEDIASOUP_SERVER_URL=http://localhost:3001
MEDIASOUP_WS_URL=http://localhost:3001
VIDEO_CALL_MAX_PARTICIPANTS=50
```

## How It Works

1. Client joins room via Django API
2. Django proxies to SFU server (HTTP)
3. SFU server returns transport credentials
4. Client creates WebRTC transport directly to SFU
5. Client polls SFU for signaling messages (every 1 second)
6. Media flows directly between clients and SFU

## Media Flow

```
Participant 1 ──────── WebRTC ────────▶ SFU
                    (audio/video)
                    
Participant 2 ◀────── WebRTC ──────── SFU
                    (audio/video)
```

Each participant sends ONE stream to the SFU. The SFU forwards to all others. This scales to 30-40+ participants.

## Startup Script

Run `start_video_calls.bat` to start both servers.
