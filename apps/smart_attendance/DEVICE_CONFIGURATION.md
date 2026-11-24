# Biometric Device Configuration Guide

This guide describes how to configure biometric devices (fingerprint, face, etc.) to integrate with the Smart Attendance system, including **offline buffering**, **batch push on reconnect**, and **ZKTeco pull sync**.

---

## 1. Overview

Devices can push attendance logs to the application in two ways:

| Method | Endpoint | Use Case |
|--------|----------|----------|
| **Single push** | `POST /api/biometric/push` | Real-time: one log per request |
| **Batch push** | `POST /api/biometric/push/batch` | Offline recovery: many logs in one request |

**Recommended:** Configure devices to use **batch push** when reconnecting after offline periods. Use single push for real-time logs when the network is available.

---

## 2. Authentication

All push endpoints require device authentication:

- **`device_serial`** – Unique identifier (e.g. `ICLOCK88001`)
- **`device_secret`** – Secret key configured when the device was registered

Provide the secret via:

1. **Header** (preferred): `X-Device-Secret: your_secret`
2. **Body** (single push only): `device_secret` field

---

## 3. Single Push API

**Endpoint:** `POST /api/biometric/push`

**Request body:**
```json
{
  "device_serial": "ICLOCK88001",
  "uid": "104",
  "timestamp": "2026-03-06 08:00:01",
  "verify_mode": "fingerprint",
  "punch_type": "checkin"
}
```

**Fields:**
- `device_serial` (required) – Device identifier
- `uid` (required) – Employee biometric UID
- `timestamp` (required) – Format: `YYYY-MM-DD HH:MM:SS`
- `verify_mode` (required) – e.g. `fingerprint`, `face`, `card`
- `punch_type` (required) – e.g. `checkin`, `checkout`

**Success:** `200 OK` with `{"status": "ok"}`

---

## 4. Batch Push API (Offline Recovery)

**Endpoint:** `POST /api/biometric/push/batch`

Use this when the device reconnects and needs to send **all buffered logs** collected while offline.

**Request body:**
```json
{
  "device_serial": "ICLOCK88001",
  "logs": [
    {
      "uid": "104",
      "timestamp": "2026-03-06 08:00:01",
      "verify_mode": "fingerprint",
      "punch_type": "checkin"
    },
    {
      "uid": "105",
      "timestamp": "2026-03-06 08:15:22",
      "verify_mode": "fingerprint",
      "punch_type": "checkout"
    }
  ]
}
```

**Fields:**
- `device_serial` (required) – Device identifier (shared for all logs)
- `logs` (required) – Array of log objects (max 10,000 per request)
- Each log: `uid`, `timestamp`, `verify_mode`, `punch_type` (same as single push)

**Headers:**
- `X-Device-Secret: your_secret` (or `device_secret` in body)

**Success:** `200 OK` with `{"status": "ok", "message": "Batch queued for processing"}`

**Behavior:**
- Authenticates once for the whole batch
- Skips logs already synced (older than `last_sync_time`)
- Enqueues new logs for processing
- Duplicate detection applies (same employee + timestamp + device)

---

## 5. Device Firmware Configuration

### 5.1 Offline Buffering

Configure the device to **buffer logs locally** when the network is unavailable:

| Setting | Recommended Value | Description |
|---------|-------------------|-------------|
| **Buffer when offline** | Enabled | Store logs in device memory when server unreachable |
| **Buffer capacity** | 10,000+ logs | Match expected offline duration |
| **Buffer persistence** | Non-volatile | Survive power loss |
| **Timestamp format** | `YYYY-MM-DD HH:MM:SS` | Must match API format |

### 5.2 On Reconnect: Push Buffered Logs

When the device detects network connectivity:

1. **Preferred:** Send all buffered logs in one request to `/api/biometric/push/batch`
   - Build `logs` array from buffer
   - Single HTTP request
   - Faster and more efficient

2. **Fallback:** If batch endpoint is unavailable, send each log to `/api/biometric/push` in a loop
   - One POST per log
   - Works but slower for large buffers

### 5.3 Reconnect Logic (Pseudocode)

```
ON network_reconnect:
  IF buffer_not_empty:
    IF batch_endpoint_available:
      POST /api/biometric/push/batch
        body: { device_serial, logs: buffer }
      clear_buffer()
    ELSE:
      FOR each log IN buffer:
        POST /api/biometric/push
          body: log
      clear_buffer()
```

### 5.4 Real-Time vs Batch

| Scenario | Action |
|----------|--------|
| **Online** | Push each log immediately to `/api/biometric/push` |
| **Offline** | Buffer logs locally |
| **Reconnect** | Push all buffered logs to `/api/biometric/push/batch` |

---

## 6. Base URL

Replace `https://your-domain.com` with your application URL:

- Single: `https://your-domain.com/api/biometric/push`
- Batch: `https://your-domain.com/api/biometric/push/batch`

---

## 7. Error Handling

| Status | Meaning |
|--------|---------|
| 200 | Success – logs queued |
| 400 | Invalid payload (missing fields, bad format) |
| 403 | Authentication failed (wrong device_serial or secret) |

On 4xx, do **not** clear the buffer. Retry after a delay or when configuration is corrected.

---

## 8. Summary Checklist

- [ ] Device registered in Smart Attendance with `device_serial` and `device_secret`
- [ ] Offline buffering enabled with sufficient capacity
- [ ] Buffer stored in non-volatile memory
- [ ] On reconnect: call batch endpoint with all buffered logs
- [ ] Fallback: loop over single push if batch unavailable
- [ ] Timestamps in `YYYY-MM-DD HH:MM:SS` format
- [ ] Authentication via `X-Device-Secret` header

---

## 9. ZKTeco Pull Sync (App Pulls from Devices)

For **ZKTeco** devices, you can run a single command that connects to devices, pulls attendance logs, and keeps everything in sync—no cron or Celery needed.

### Setup

1. Install pyzk: `pip install pyzk`
2. Register devices in Smart Attendance with correct **device_ip** and **device_port** (default 4370)
3. Ensure the machine running the command can reach the devices on the network

### Run

```bash
python manage.py zk_pull_sync
```

Leave this running in a terminal. It will:
- Connect to each registered ZKTeco device every 30 seconds (configurable)
- Pull new attendance logs since last sync
- Process the queue immediately
- Update the dashboard in near real-time

### Options

```bash
# Sync every 60 seconds instead of 30
python manage.py zk_pull_sync --interval 60

# Run once and exit (useful for cron)
python manage.py zk_pull_sync --once

# Process more queue items per cycle
python manage.py zk_pull_sync --batch-size 2000
```

### Network Requirement

The machine running `zk_pull_sync` must be able to reach the device IPs (e.g. same LAN as the ZKTeco devices). If your Django app runs on a remote server, run `zk_pull_sync` on a machine that has network access to the devices, or use push mode instead.
