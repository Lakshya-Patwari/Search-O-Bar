import os
import uuid
import re
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from dotenv import load_dotenv

# RAG search + model calls (your existing modules)
from search import web_search
from summarizer import generate_answer_from_sources, generate_general_answer, ChatBot

# Sentinel from summarizer.py
RAG_FAILURE_CODE = "RAG_CONTEXT_INSUFFICIENT"

# --- Trafilatura parser (replaces newspaper3k) ---
import trafilatura

load_dotenv()

# ---------------- In-memory stores ----------------
# Conversation messages: [{"role":"user"|"assistant"|"system","content":"..."}]
SESSIONS = {}
# Full RAG sources: [{"title","url","snippet","content"}]
SOURCES = {}

# ---------------- Simple logic bypass ----------------
def is_simple_logical_query(query: str) -> bool:
    """Bypass web search for very short arithmetic/logic questions."""
    arithmetic_keywords = ['+', '-', '*', '/', 'x', 'what is', 'calculate', 'solve']
    normalized = (query or "").lower().strip()
    has_op = any(op in normalized for op in arithmetic_keywords)
    has_num = any(ch.isdigit() for ch in normalized)
    return bool(has_op and has_num and len(normalized.split()) < 7)

# ---------------- Utilities for article fetching (Trafilatura) ----------------
MAX_CHARS_PER_SOURCE = 6000  # keep prompts manageable

def _clean_text(txt: str) -> str:
    if not txt:
        return ""
    txt = re.sub(r"\s+", " ", txt)
    return txt.strip()

def fetch_full_article(url: str) -> str:
    """
    Fetch and extract main text from a webpage using Trafilatura.
    Returns clean plain text or "" on failure.
    """
    if not url:
        return ""
    try:
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            return ""
        text = trafilatura.extract(downloaded) or ""
        return _clean_text(text)
    except Exception:
        return ""

def build_full_sources(results: list) -> list:
    """
    Takes SerpAPI-like results (title/url/snippet), fetches full text,
    and returns items with: title, url, snippet, content (truncated).
    """
    full_sources = []
    for r in results or []:
        if isinstance(r, dict):
            title = r.get("title", "")
            url = r.get("url") or r.get("link") or ""
            snippet = r.get("snippet", "")
        else:
            title, url, snippet = "", "", ""

        content = fetch_full_article(url) if url else ""
        if content:
            content = content[:MAX_CHARS_PER_SOURCE]

        full_sources.append({
            "title": title,
            "url": url,
            "snippet": snippet,
            "content": content
        })
    return full_sources

def _sources_as_system_block(sources: list) -> str:
    """
    Produce a compact, numbered list for chat memory.
    Include title, url, and a short excerpt (content preferred, else snippet).
    """
    lines = []
    for i, s in enumerate(sources or [], start=1):
        title = s.get("title", "")
        url = s.get("url", "")
        body = s.get("content") or s.get("snippet") or ""
        excerpt = (body[:500] + "…") if len(body) > 500 else body
        lines.append(f"[{i}] {title}\nURL: {url}\n{excerpt}")
    return "\n\n".join(lines)

# ---------------- Session helpers ----------------
def _new_session_id() -> str:
    return str(uuid.uuid4())

def _create_initial_session(user_q: str, bot_answer_plain: str, sources: list) -> str:
    """
    Create a new session with:
      - system context listing the numbered sources
      - initial user Q and bot answer
      - raw sources stored for fast-paths
    """
    session_id = _new_session_id()
    sys_sources_block = _sources_as_system_block(sources)

    SESSIONS[session_id] = [
        {"role": "system", "content": "You are allowed to use the following RAG sources in all future responses. When the user says 'first link' or 'second link', refer to the numbered list below."},
        {"role": "system", "content": f"RAG_SOURCES:\n{sys_sources_block}"},
        {"role": "user", "content": user_q},
        {"role": "assistant", "content": bot_answer_plain},
    ]
    SOURCES[session_id] = sources or []
    print(f"Initialized new chat session : {session_id}")
    return session_id

def _append_and_get_reply(session_id: str, user_text: str) -> str:
    """
    Append a user message to session history, call the model with full history, append reply.
    Returns the assistant reply.
    """
    history = SESSIONS.get(session_id, [])
    history.append({"role": "user", "content": user_text})
    bot = ChatBot()  # Ollama-backed bot
    reply = bot.chat(history=history)
    history.append({"role": "assistant", "content": reply})
    SESSIONS[session_id] = history
    return reply

# ---------------- Link index detection ----------------
ORDINAL_TO_INDEX = {
    "first": 1, "1st": 1,
    "second": 2, "2nd": 2,
    "third": 3, "3rd": 3,
    "fourth": 4, "4th": 4,
    "fifth": 5, "5th": 5,
    "sixth": 6, "6th": 6,
    "seventh": 7, "7th": 7,
    "eighth": 8, "8th": 8,
    "ninth": 9, "9th": 9,
    "tenth": 10, "10th": 10,
}

LINK_PATTERNS = [
    r"(?:summarize|summary|details|more\s+details|explain|about)\s+(?:link\s*)?#?(\d+)",
    r"(?:summarize|summary|details|more\s+details|explain|about)\s+the\s+(\w+)\s+(?:link|one)",
    r"(?:link|#)\s*(\d+)",
    r"\b(\w+)\s+link\b",
]

def detect_link_index(user_text: str):
    """
    Return 1-based index if the user asks about a specific link (e.g., 'summarize 2', 'first link'),
    else None.
    """
    if not user_text:
        return None
    text = user_text.lower().strip()

    # Try numeric/word patterns
    for pat in LINK_PATTERNS:
        m = re.search(pat, text)
        if m:
            g = m.group(1)
            if g and g.isdigit():
                idx = int(g)
                return idx if idx >= 1 else None
            if g in ORDINAL_TO_INDEX:
                return ORDINAL_TO_INDEX[g]

    # Try pure ordinal words anywhere: "first link", "second link"
    for word, idx in ORDINAL_TO_INDEX.items():
        if re.search(rf"\b{word}\s+(?:link|one)\b", text):
            return idx

    return None

def detect_two_links(user_text: str):
    """
    Detect patterns like:
      - compare 1 and 3
      - compare #2 vs #4
      - link 1 vs link 3
      - first vs third
      - difference between 1 and 2
    Returns tuple (idx1, idx2) or None.
    """
    if not user_text:
        return None
    text = user_text.lower().strip()

    # Normalize ordinal words → numbers
    for word, num in ORDINAL_TO_INDEX.items():
        text = text.replace(word, str(num))

    # Patterns for two numbers
    m = re.search(r"(\d+)\s*(?:and|&|,|vs|versus)\s*(\d+)", text)
    if m:
        idx1 = int(m.group(1))
        idx2 = int(m.group(2))
        if idx1 >= 1 and idx2 >= 1:
            return idx1, idx2

    return None

# ---------------- Flask app ----------------
app = Flask(__name__, template_folder="templates", static_folder="static")
CORS(app)

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/chat.html")
def chat():
    return render_template("chat.html")

# ---------------- /api/ask (RAG entry) ----------------
@app.post("/api/ask")
def api_ask():
    """
    Main RAG endpoint:
    1) Try RAG (search + cite) first with full article content (Trafilatura)
    2) Fall back to general reasoning if RAG is insufficient
    3) Create a session_id and return it so the UI can "Continue in Chat"
    """
    data = request.get_json(force=True) or {}
    query = (data.get("query") or "").strip()
    if not query:
        return jsonify({"error": "Query parameter is required."}), 400

    # Decide path
    if is_simple_logical_query(query):
        print("Flowchart Path: General AI Reasoning (Simple Logic Bypass)")
        answer = generate_general_answer(query)
        results = []
        full_sources = []
    else:
        print("Flowchart Path: Search/RAG attempt...")
        results = web_search(query, count=6) or []
        full_sources = build_full_sources(results)

        if full_sources and len(results) > 0:
            print("Flowchart Path: RAG (Search, Summarizer, Summary + Sources)")
            answer = generate_answer_from_sources(query, full_sources)
            if answer == RAG_FAILURE_CODE:
                print("Switching to General AI Reasoning: RAG failed to find context in sources.")
                answer = generate_general_answer(query)
                results, full_sources = [], []
        else:
            print("Flowchart Path: General AI Reasoning (Fallback after failed search)")
            answer = generate_general_answer(query)
            results, full_sources = [], []

    # Create a chat session so chat page can continue with sources awareness
    session_id = None
    if answer and not answer.startswith("ERROR:"):
        plain_answer = answer.replace("<br>", "\n")
        session_id = _create_initial_session(query, plain_answer, full_sources)

    return jsonify({
        "answer": (answer or "").replace("\n", "<br>"),
        "sources": results,        # index page renders title/url/snippet
        "session_id": session_id,  # used by frontend to show "Continue in Chat"
    })

# ---------------- /api/chat/history ----------------
@app.get("/api/chat/history")
def api_chat_history():
    """
    Returns chat history in the UI format that chat.js expects:
    { "history": [ { "sender": "user"|"bot", "text": "<html>" }, ... ] }
    """
    session_id = (request.args.get("session_id") or "").strip()
    if not session_id:
        return jsonify({"error": "session_id is required"}), 400

    history = SESSIONS.get(session_id)
    if history is None:
        return jsonify({"error": "Invalid or missing chat session ID."}), 400

    ui_history = []
    for msg in history:
        role = (msg.get("role") or "").lower()
        content = msg.get("content") or ""
        sender = "user" if role == "user" else "bot"
        ui_history.append({
            "sender": sender,
            "text": content.replace("\n", "<br>"),
        })

    return jsonify({"history": ui_history})

# ---------------- /api/chat (follow-ups) ----------------
@app.post("/api/chat")
def api_chat():
    """
    Accepts a follow-up query and returns the model's answer,
    updating the session history.
    Includes fast-paths:
      - Compare X and Y
      - Summarize #N
    """
    data = request.get_json(force=True) or {}
    session_id = (data.get("session_id") or "").strip()
    user_msg = (data.get("query") or "").strip()

    if not session_id or not user_msg:
        return jsonify({"error": "session_id and query are required"}), 400

    if session_id not in SESSIONS:
        return jsonify({"error": "Invalid or expired chat session ID."}), 404

    print(f"Continuing chat session: {session_id}")

    try:
        # ---------- FAST-PATH: "compare X and Y" ----------
        pair = detect_two_links(user_msg)
        if pair:
            idx1, idx2 = pair
            srcs = SOURCES.get(session_id) or []
            if 1 <= idx1 <= len(srcs) and 1 <= idx2 <= len(srcs):
                s1 = srcs[idx1 - 1]
                s2 = srcs[idx2 - 1]

                sources_for_model = [
                    {
                        "title": s1.get("title", ""),
                        "url": s1.get("url", ""),
                        "snippet": s1.get("snippet", ""),
                        "content": s1.get("content", "")
                    },
                    {
                        "title": s2.get("title", ""),
                        "url": s2.get("url", ""),
                        "snippet": s2.get("snippet", ""),
                        "content": s2.get("content", "")
                    }
                ]

                question = (
                    f"Compare ONLY these two sources (# {idx1} and # {idx2}). "
                    f"Highlight similarities, differences, main arguments, tone, and key insights. "
                    f"User request: {user_msg}"
                )

                reply = generate_answer_from_sources(question, sources_for_model)
                if reply == RAG_FAILURE_CODE:
                    reply = generate_general_answer(user_msg)

                history = SESSIONS.get(session_id, [])
                history.append({"role": "user", "content": user_msg})
                history.append({"role": "assistant", "content": reply})
                SESSIONS[session_id] = history

                return jsonify({
                    "session_id": session_id,
                    "answer": reply.replace("\n", "<br>")
                })

        # ---------- FAST-PATH: "summarize #N" or "first link" ----------
        idx = detect_link_index(user_msg)
        if idx is not None:
            srcs = SOURCES.get(session_id) or []
            if 1 <= idx <= len(srcs):
                target = srcs[idx - 1]

                body = (target.get("content") or target.get("snippet") or "").strip()
                if not body:
                    # Optional: lazy fetch now if we didn't fetch earlier
                    body = fetch_full_article(target.get("url", ""))
                    target = {
                        "title": target.get("title", ""),
                        "url": target.get("url", ""),
                        "snippet": target.get("snippet", ""),
                        "content": body or ""
                    }

                question = f"Summarize ONLY the selected source (#{idx}). {user_msg}"
                reply = generate_answer_from_sources(question, [target])
                if reply == RAG_FAILURE_CODE:
                    reply = generate_general_answer(user_msg)

                history = SESSIONS.get(session_id, [])
                history.append({"role": "user", "content": user_msg})
                history.append({"role": "assistant", "content": reply})
                SESSIONS[session_id] = history

                return jsonify({
                    "session_id": session_id,
                    "answer": (reply or "").replace("\n", "<br>")
                })

        # ---------- DEFAULT: normal multi-turn chat over full history ----------
        reply = _append_and_get_reply(session_id, user_msg)
        return jsonify({
            "session_id": session_id,
            "answer": (reply or "").replace("\n", "<br>")
        })

    except Exception as e:
        print(f"Chat API Error: {e}")
        return jsonify({"error": f"An error occurred while communicating with the model. Details: {e}"}), 500

if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    debug = os.getenv("FLASK_DEBUG", "1") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug, use_reloader=False)
