

**User**

How can I possibly get all those informations from my office ZKTeco biometrics device? So that I can use it to fill the Registeration form (http://127.0.0.1:8000/attendance/devices/register ) that will help my app and the device to be in sync? 

---

**Cursor**


Creating a short guide on where to get each value for the registration form from your ZKTeco device and adding it to the app so users can follow it.



Adding a "Where to get this information" guide to the registration page and creating a short reference doc.



Adding a short pointer in the top alert to the new guide:



Making the collapse button work in both Bootstrap 4 and 5:



Summary of what’s in place and how to use it:

---

## 1. **Guide added on the registration page**

On **http://127.0.0.1:8000/attendance/devices/register** there is now a **“Where to get this information from your ZKTeco device”** section (with a Show/Hide button) that explains, per form field, how to get or set the value. Below is the same information in one place.

---

## 2. **How to get each value from your office ZKTeco device**

| What you need | Where / how to get it |
|---------------|------------------------|
| **Device name** | You choose it (e.g. “Reception”, “Main Gate”). Not read from the device. |
| **Device serial** | **On device:** Menu → **Device Info** / **System Info** / **About** → **Serial Number** or **SN**. Copy it exactly. **On PC:** ZKAccess / ZKBioAccess → connect to device → **Device Management** / **Device Info** →  **Serial No.** **On web:** Open `http://<device-IP>` in a browser → **Device** / **System Info** → **Serial Number**. |
| **Device IP** | **On device:** Menu → **Network** / **TCP/IP** → **IP Address** (e.g. 192.168.1.100). Optional for the form; you can leave it blank if you only use push. |
| **Device port** | Usually **4370** (ZKTeco default). On device: Menu → **Network** → **Port**. Use 4370 unless you changed it. |
| **Device secret** | **You define it:** (1) Enter a strong password in the registration form. (2) On the device (or in ZKAccess): find **Push URL** / **Webhook** / **HTTP Push** / **Real-Time Push** → set **Secret** / **Token** / **API Key** to the **exact same** value. The device will send this when pushing attendance. |
| **Device model / Location** | Optional. Model is often on a label (e.g. ZKT Ecko, K40). Location is for you (e.g. “Ground floor”). |

---

## 3. **Quick steps at the office**

1. **Serial:** On the device go to **Menu → Device Info** (or **System Info** / **About**) and note the **Serial Number**. Type it exactly into the form (no extra spaces).  
2. **Secret:** Decide a password, type it in the **Device secret** field in the form, then set the **same** value in the device under Push/Webhook/HTTP Push settings (Secret / Token / API Key).  
3. **IP (optional):** Menu → **Network** → **IP Address** if you want to fill it; otherwise leave **Device IP** blank.  
4. **Port:** Leave **4370** unless you know you changed it.  
5. Submit the form, then on the next page copy the **Push URL** and set it in the device in the same Push/Webhook/HTTP Push section.  

After that, the device and app stay in sync when the device pushes (real time or batch). The new section on the registration page is there so you can follow this directly while filling the form at the office.

