# Perplexity‑Lite (Flask + JS)

A minimal, local, Perplexity-like prototype: ask a question, get an extractive summary and linked sources.

## Features
- Flask backend (`/api/ask`) that searches the web (Bing API if configured) or falls back to mock results.
- Simple extractive summarizer (no external AI key required) using frequency-based sentence scoring.
- Clean frontend with vanilla JS and CSS.

## Project Structure
```
perplexity-lite/
  app.py
  search.py
  summarizer.py
  templates/
    index.html
    chat.html
  static/
    app.js
    style.css
    chat.js
  requirements.txt
  .env
```

## Run Locally

1) Python 3.10+ recommended.

2) Create a virtual environment and install deps:
```
cd perplexity-lite
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

3) Optional: enable live web search by adding an API key

- Add your `BING_API_KEY`

4) Start the server:
```
python app.py
```
Open http://localhost:5000

## Notes
- Without an API key, you still get a working demo with mock sources.
- Swap in other providers (SerpAPI, Tavily, Google CSE) by editing `search.py`.
- Replace the extractive summarizer with an LLM call if you have an AI API key.
