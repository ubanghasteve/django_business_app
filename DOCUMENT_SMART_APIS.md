# Smart Document APIs – Handwriting & Professional Structuring

## How to get the APIs and add them to `.env`

1. **Copy the template**  
   Copy `.env.example` to `.env` (or open your existing `.env`).

2. **Choose one provider** (Google or Azure) and get credentials:

   **Google Document AI**
   - Go to [Google Cloud Console](https://console.cloud.google.com/).
   - Create or select a project → enable **“Document AI API”**.
   - Go to **Document AI** → **Processors** → **Create processor** → choose **“Document OCR”** → create.
   - Note: **Processor ID** (long string), **Location** (e.g. `us`), and **Project ID** (in the console header or project settings).
   - Go to **IAM & Admin** → **Service accounts** → **Create service account** → **Keys** → **Add key** → **JSON** → download the JSON file and save it somewhere safe (e.g. `C:\keys\my-docai-key.json`).

   **Azure Document Intelligence**
   - Go to [Azure Portal](https://portal.azure.com/) → **Create a resource** → search **“Document Intelligence”** → create (use F0 free tier if you want).
   - Open the resource → **Keys and Endpoint** → copy **Key 1** and **Endpoint** (e.g. `https://your-name.cognitiveservices.azure.com/`).

3. **Add the variables to `.env`**  
   Open `.env` and add the lines for your chosen option (see **Option A** or **Option B** in `.env.example`). Use your real values; do not commit `.env` to git.

4. **Restart the app**  
   Restart Django (e.g. `python manage.py runserver` or your server) so it reloads `.env`. The app reads these from `.env` and uses them for smart extraction when a user uploads a document or image.

---

This guide describes **APIs and libraries you can install** so your app can:

- **Read handwritten content** from photos (e.g. handwritten analyses, notes, forms).
- **Structure documents automatically** (titles, paragraphs, tables, lists) and present data in a clear, professional order.
- **Compute data accurately** from any uploaded file, picture, or document and return reliable results.

---

## Recommended APIs (install one or both)

### 1. **Google Cloud Document AI** (best for handwriting + structure)

- **Handwriting:** Strong support for **handwritten text** in 50+ languages.
- **Structure:** Detects blocks, paragraphs, lines, tables, headings; keeps reading order.
- **Use case:** Photos of handwritten notes, handwritten forms, mixed printed + handwritten docs.

**Install:**

```bash
pip install google-cloud-documentai
```

**Setup:**

1. Create a [Google Cloud project](https://console.cloud.google.com/) and enable **Document AI API**.
2. Create a **Document OCR** processor (or **Form Parser** for forms) in the Document AI console; note **Processor ID**, **Location** (e.g. `us`), and **Project ID**.
3. Create a **service account** and download a JSON key. Set:

   ```bash
   set GOOGLE_APPLICATION_CREDENTIALS=C:\path\to\your-key.json
   ```

4. In your app (e.g. `.env` or environment):

   ```
   USE_SMART_EXTRACTION=1
   DOCUMENT_AI_PROJECT_ID=your-project-id
   DOCUMENT_AI_LOCATION=us
   DOCUMENT_AI_PROCESSOR_ID=your-processor-id
   ```

**Pricing:** Pay per page; new Google Cloud accounts get free credit.

**If `pip install` fails (timeout or network):**
- Ensure you have a stable internet connection; try a different network or VPN if behind a firewall.
- Increase pip timeout and use a specific version to avoid long resolver backtracking:
  ```bash
  pip install --default-timeout=300 google-cloud-documentai==3.6.0
  ```
- If PyPI is unreachable, try installing from another machine and copying the environment, or use **Azure** (often fewer dependencies and smaller download).

---

### 2. **Azure AI Document Intelligence** (formerly Form Recognizer)

- **Handwriting:** OCR includes handwriting recognition.
- **Structure:** Layout model gives **layout analysis** (titles, paragraphs, tables, selection marks).
- **Use case:** Invoices, receipts, forms, and general documents; good for structured + handwritten.

**Install:**

```bash
pip install azure-ai-documentintelligence
```

**Setup:**

1. Create a [Document Intelligence](https://portal.azure.com/) resource; note **Endpoint** and **Key**.
2. In your app (e.g. `.env`):

   ```
   USE_SMART_EXTRACTION=1
   AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT=https://your-resource.cognitiveservices.azure.com/
   AZURE_DOCUMENT_INTELLIGENCE_KEY=your-key
   ```

**Pricing:** Per-page; see Azure pricing page.

**If install fails:** Azure’s package often has fewer dependencies; try:
  ```bash
  pip install --default-timeout=300 azure-ai-documentintelligence
  ```

---

## How the app uses these APIs

When **smart extraction** is enabled (`USE_SMART_EXTRACTION=1` and the chosen provider is configured):

1. **Upload (PDF or image)** → The system first tries **Google Document AI** or **Azure Document Intelligence** (whichever you configured).
2. **Cloud API returns:**
   - Full text (including **handwritten** when supported).
   - **Structured layout:** blocks, lines, paragraphs, tables in reading order.
3. **App normalizes** this into:
   - `text` – full document text.
   - `tables` – list of tables (rows/cells).
   - `layout_lines` – lines in reading order for consistent analysis.
4. **Existing pipeline** (smart analyzer, statement/invoice logic, validation) runs on this normalized data, so you get:
   - **Structured, professional presentation** of content.
   - **Accurate computation** (totals, debits/credits, balances, etc.).

If the cloud API is not configured or fails (e.g. network error), the app **falls back** to built-in extraction (Tesseract OCR for images, pdfplumber for PDFs).

---

## Optional: extra Python libraries (no API key)

- **EasyOCR** – Open-source OCR; can help with some handwriting and multiple languages:

  ```bash
  pip install easyocr
  ```

  (Integration is optional; the app does not use it by default.)

- **PaddleOCR** – Good accuracy and table detection; can be self-hosted:

  ```bash
  pip install paddlepaddle paddleocr
  ```

These are alternatives or supplements; the **cloud APIs above** are the ones that make the app “super smart” for **handwritten** and **layout-aware** structuring out of the box.

---

## Summary

| Goal                         | What to install / configure                    |
|-----------------------------|-------------------------------------------------|
| Handwritten photos          | **Google Document AI** or **Azure Document Intelligence** + `USE_SMART_EXTRACTION=1` |
| Automatic structuring       | Same; both APIs return layout (blocks, tables, order). |
| Accurate computation        | Already in the app; smart extraction feeds the same pipeline for consistent results. |

After installing one of the cloud SDKs and setting the environment variables, the app will use that API when available and fall back to local OCR/PDF extraction otherwise.
