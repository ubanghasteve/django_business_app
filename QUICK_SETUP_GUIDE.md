# Complete Guide: Connecting ZKTeco iClock880 to Your App

This guide walks you through connecting your ZKTeco iClock880 biometric device to your Django application for real-time attendance updates.

---

## Prerequisites

Before starting, ensure you have:
- [ ] Access to your Django application (running at `http://127.0.0.1:8000` or a public URL)
- [ ] Admin access to your Django app
- [ ] Network access from your computer to the biometric device (same network)
- [ ] Admin PIN for the biometric device (contact your IT vendor if unknown)

---

## Part 1: Register the Device in Your App

### Step 1.1: Access the Device Registration Page

1. Open your browser and go to:
   ```
   http://127.0.0.1:8000/attendance/devices/register
   ```

2. Log in with your admin credentials if prompted

### Step 1.2: Fill in the Device Registration Form

Enter the following information from your device:

| Field | Value from Your Device | Where to Find on Device |
|-------|----------------------|-------------------------|
| **Device Name** | `iClock880` | Device Info screen |
| **Device Serial** | `3929151501892` | Device Info screen |
| **Device IP** | Leave blank OR enter `0.0.0.0` | (We're doing push mode) |
| **Device Port** | `4370` | Default ZKTeco port |
| **Device Model** | `iClock880` | Device Info screen |
| **Firmware Version** | `ver 8.0.4.4-20190617` | Device Info screen |
| **Device Secret** | Create your own (see below) | You create this now |
| **Location** | Optional (e.g., "Main Entrance") | Your choice |

### Step 1.3: Create a Device Secret

For **Device Secret**, create a random string that you'll also configure on the device. Examples:
- `MySecret2024!`
- `attendance123`
- `zkDevice#888`

**Write this down** - you'll need to enter the exact same value on the device.

### Step 1.4: Save the Device

1. Click **Save** or **Register Device**
2. You'll be redirected to a **Setup Complete** page

### Step 1.5: Note Your Push URL

On the Setup Complete page, note the **Push URL**. It should look like:
```
http://YOUR_IP:8000/api/biometric/push
```

Keep this page open - you'll need the:
- **Push URL**
- **Device Serial** (`3929151501892`)
- **Device Secret** (what you just entered)

---

## Part 2: Configure the Biometric Device to Push

Now you need to configure your iClock880 device to send attendance records to your app.

### Step 2.1: Access the Device Menu

1. On the iClock880 touchscreen, press the **Menu** button
2. Enter the **Admin PIN** (default is often `123456`, or check with your IT)
3. Navigate to the settings

### Step 2.2: Navigate to Network/Communication Settings

The exact path depends on your firmware version. Try these in order:

**Option A:**
```
Menu → Settings → Network → Server/ADMS Settings
```

**Option B:**
```
Menu → System → Communication → Network Settings
```

**Option C:**
```
Menu → User Management → Network Settings
```

**Option D:**
Press **Menu** → Look for **"Communication"** or **"Network"** icon

### Step 2.3: Configure Server Settings

Look for these settings and change them:

| Setting | Current Value | Change To |
|---------|---------------|-----------|
| **Server Address** | `http://device.zkcserv.com` | Your Push URL (e.g., `http://192.168.1.100:8000/api/biometric/push`) |
| **Server Port** | (varies) | `8000` (or your app's port) |
| **Server Mode** | ADMS | Keep as **ADMS** |
| **Push Interval** | (varies) | Set to **1** second or enable **Real-time Push** |

### Step 2.4: Set the Device Secret (If Required)

Some devices have a field for "Device Key", "Device Code", or "Token". If available, enter the **Device Secret** you created in Step 1.3.

If there's no such field, the secret will be sent automatically by the device firmware in the request header.

### Step 2.5: Save and Exit

1. Save the settings
2. Exit back to the main screen
3. The device should now attempt to push to your app

---

## Part 3: Test the Connection

### Step 3.1: Verify Device Status in App

1. Go to: `http://127.0.0.1:8000/attendance/devices`
2. Look for your device (`iClock880`)
3. Check the **Status** column - it should show **"online"** if the device is successfully pushing

### Step 3.2: Test with a Check-in

1. Have an employee punch in/out on the device
2. Wait 2-3 seconds
3. Go to: `http://127.0.0.1:8000/attendance/logs`
4. You should see the new attendance record

### Step 3.3: Check the Setup Complete Page (Live Verification)

Go back to your Setup Complete page (`/attendance/device/X/setup-complete`) - it has a **Live Sync Verification** section that automatically shows the latest punch. If configured correctly, this will update when someone clocks in/out.

---

## Part 4: Troubleshooting

### Problem: Device shows "offline" in the app

**Possible causes:**
1. Network connectivity issue - ensure device can reach your app's server
2. Firewall blocking port 8000 - open the port or use a different port
3. Wrong Server Address configured on device

**Solution:**
- Ping your app server from the device network
- Verify the Push URL is correct
- Check firewall settings

### Problem: Records not appearing

**Possible causes:**
1. Device Secret mismatch
2. Employee not mapped (no matching Biometric UID)
3. Device Serial doesn't match exactly

**Solution:**
- Go to `/attendance/employees` and ensure employees have the correct **Biometric UID** matching what the device sends
- Verify Device Serial matches exactly (`3929151501892`)
- Check device logs for push errors

### Problem: Testing locally but device can't reach localhost

The biometric device cannot reach `127.0.0.1` or `localhost` on its own network.

**Solution - Option A: Use ngrok (Quick Test)**
```bash
# Install ngrok
pip install ngrok

# Run ngrok to expose port 8000
ngrok http 8000
```

Use the ngrok URL (e.g., `https://abc123.ngrok-free.app`) as the Server Address on the device.

**Solution - Option B: Deploy to a server**
Deploy your Django app to a server with a public IP, then use that IP as the Server Address.

---

## Part 5: Understanding Employee Mapping

For attendance records to appear correctly, employees must be mapped:

### How It Works

1. Employee punches on device → Device sends `uid` (user ID)
2. App receives the push → Looks for employee with matching `biometric_uid`
3. If found → Creates attendance record linked to that employee
4. If not found → Record is saved as "Raw Log" but not linked to any employee

### Step 5.1: Add Employees with Biometric UID

1. Go to: `http://127.0.0.1:8000/attendance/employees/create`
2. Fill in employee details
3. For **Biometric UID**, enter the UID that the device assigns to that user
   - You can find this in the device's user management screen
   - Or check the device logs when the user punches

---

## Quick Reference Summary

| Step | Action | Location |
|------|--------|----------|
| 1 | Register device in app | `/attendance/devices/register` |
| 2 | Note Push URL, Serial, Secret | Setup Complete page |
| 3 | Configure device to push | Device Menu → Network → ADMS |
| 4 | Set Server Address to Push URL | On the device |
| 5 | Set Device Secret (if available) | On the device |
| 6 | Test with check-in | Punch on device, check `/attendance/logs` |

---

## Need Help?

If you're stuck at any step, check:
1. Your device manual for exact menu paths
2. Network connectivity (ping test)
3. Firewall settings on your computer/server
4. The app's admin panel for any error logs
