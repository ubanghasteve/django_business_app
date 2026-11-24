

**User**

Am saying that if I use their system or the device they use to loginto the app. can I be able to check their ip that the system is showing?

---

**Cursor**


Yes. If you’re using **their** computer/device, you can see the IP that system is using and compare it to the IP in your app’s login logs.

---

## On their computer (when you’re sitting at it)

Use one of these to see the **public IP** that device is using **right now**:

### Option 1 – Command Prompt

```cmd
curl -s https://api.ipify.org
```

*(If `curl` isn’t available, use Option 2 or 3.)*

### Option 2 – PowerShell

```powershell
(Invoke-WebRequest -Uri "https://api.ipify.org" -UseBasicParsing).Content
```

### Option 3 – Command Prompt (no curl, DNS method)

```cmd
nslookup myip.opendns.com resolver1.opendns.com
```

Then look for the line that shows an address like `41.203.123.45` — that’s the public IP.

---

## What to do with it

1. Run one of the commands above on **their** device.
2. Note the IP it shows.
3. In your app (Django Admin → **UserSession**, or your session/activity views), find the login(s) for that user and check the **ip_address** stored for those logins.
4. If the IP from their device **matches** the IP in the log, that’s consistent with that device (or another device on the same network) being used for that login.

So yes: **using their system, you can check the IP that system is showing** with those commands and then compare it to the IP you have in your app.

---

**User**

What if they used their phone, what should I use to rveal the ip of their phone that matches with what is in the app. when I get hold of their phone?

---

**Cursor**


When you have their phone, you can see the IP that device is using the same way you do on a PC: ask “what is my IP?” from that device, then compare it to the IP in your app.

---

## On their phone (when you have it)

Use the **browser** on the phone (Chrome, Safari, etc.). No need to install anything.

### Step 1 – Open the browser on their phone  
(Safari on iPhone, Chrome on Android, etc.)

### Step 2 – Go to one of these sites

- **https://api.ipify.org**  
  The page will show **only** the IP (e.g. `102.89.45.123`).

- **https://whatismyip.com**  
  Shows the IP clearly on the page.

- **https://ifconfig.me**  
  Shows IP and some other info.

### Step 3 – Note the IP shown  
That is the **public IP** the phone is using **right now** (Wi‑Fi or mobile data).

### Step 4 – Compare with your app  
In Django Admin (or your session/activity views), open **UserSession** (or **UserActivity**) for that user and check the **ip_address** for the login you care about.

- **If it matches** → That phone (or another device on the same network) could have been used for that login.
- **If it doesn’t match** → They might be on a different network now (e.g. different Wi‑Fi or mobile data), or a different device was used.

---

## Things to keep in mind

- **Mobile data**: The IP often changes when they switch towers or reconnect. So the current IP might not match the one at login time.
- **Wi‑Fi**: If they’re on the same Wi‑Fi as when they logged in, the IP is more likely to match.
- **Same idea as PC**: You’re not “reading” the app from the phone; you’re making the **phone** show its current IP, then you compare that to the IP **your app** already stored for that login.

So: **on their phone, open the browser, go to https://api.ipify.org (or whatismyip.com), note the IP, then compare it to the IP in your app.**

