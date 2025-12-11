# summarizer.py — Ollama backend (local, free, no API key)
# Drop-in replacement for your previous Gemini/OpenAI file.

import os
from typing import List, Dict, Optional, Any
import requests
from dotenv import load_dotenv

load_dotenv()

# Keep the same sentinel so app.py logic remains unchanged
RAG_FAILURE_CODE = "RAG_CONTEXT_INSUFFICIENT"

# Ollama settings (can override in .env)
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")

# --------- Low-level HTTP helpers ---------

def _post_json(path: str, payload: Dict[str, Any], timeout: int = 300) -> Dict[str, Any]:
    """
    POST JSON to the Ollama server and return JSON. Raises HTTPError on failure.
    """
    url = f"{OLLAMA_HOST}{path}"
    resp = requests.post(url, json=payload, timeout=timeout)
    resp.raise_for_status()
    return resp.json()

def _ollama_generate(prompt: str, temperature: float = 0.7, max_tokens: int = 800) -> str:
    """
    Call Ollama /api/generate (single-turn). Returns plain text.
    """
    data = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens
        }
    }
    try:
        res = _post_json("/api/generate", data)
        return (res or {}).get("response", "").strip()
    except Exception as e:
        return f"[ERROR] Failed to call Ollama generate: {e}"

def _ollama_chat(messages: List[Dict[str, str]], temperature: float = 0.7, max_tokens: int = 800) -> str:
    """
    Call Ollama /api/chat (multi-turn). messages = [{role:'system'|'user'|'assistant', content:'...'}]
    """
    data = {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens
        }
    }
    try:
        res = _post_json("/api/chat", data)
        msg = (res or {}).get("message") or {}
        return msg.get("content", "").strip()
    except Exception as e:
        return f"[ERROR] Failed to call Ollama chat: {e}"

# --------- Utilities ---------

def _normalize_sources(sources) -> List[Dict[str, str]]:
    """
    Accepts list[dict], list[str], or str; returns list of dicts with {title,url,snippet}.
    """
    norm: List[Dict[str, str]] = []
    if isinstance(sources, str):
        s = sources.strip()
        if s:
            norm.append({"title": "", "url": "", "snippet": s})
    elif isinstance(sources, list):
        for item in sources:
            if isinstance(item, dict):
                norm.append({
                    "title": item.get("title") or "",
                    "url": item.get("url") or item.get("link") or "",
                    "snippet": item.get("snippet") or "",
                })
            elif isinstance(item, str):
                s = item.strip()
                if s:
                    norm.append({"title": "", "url": "", "snippet": s})
    return norm

# --------- Public API used by app.py ---------

def generate_answer_from_sources(query: str, sources) -> str:
    """
    Use ONLY provided sources to answer.
    Accepts: list[dict] with keys incl. title, url, snippet, content.
    Falls back to RAG_FAILURE_CODE if insufficient.
    """
    # Normalize
    norm = []
    if isinstance(sources, list):
        for s in sources:
            if not isinstance(s, dict):
                continue
            norm.append({
                "title": s.get("title") or "",
                "url": s.get("url") or s.get("link") or "",
                "snippet": s.get("snippet") or "",
                "content": s.get("content") or ""
            })

    if not norm:
        return RAG_FAILURE_CODE

    # Build compact blocks (prefer content, fallback to snippet)
    blocks = []
    for i, s in enumerate(norm, start=1):
        body = s["content"] or s["snippet"] or ""
        if not body:
            continue
        # Hard cap per source to keep prompt size sane (already truncated in app.py)
        blocks.append(f"[{i}] {s['title']}\nURL: {s['url']}\n{body}")

    if not blocks:
        return RAG_FAILURE_CODE

    system_msg = (
        "You are a helpful research assistant. Use ONLY the provided sources to answer. "
        "Cite like [1], [2] in the text when using a source. If sources are insufficient, "
        "reply exactly: RAG_CONTEXT_INSUFFICIENT."
    )
    user_msg = f"Question: {query}\n\nSources:\n" + "\n\n".join(blocks) + "\n\nWrite a concise answer with citations."

    out = _ollama_chat(
        messages=[
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ]
    )

    if not out:
        return RAG_FAILURE_CODE
    if "RAG_CONTEXT_INSUFFICIENT" in out:
        return RAG_FAILURE_CODE
    return out.strip()


def generate_general_answer(query: str) -> str:
    """
    Non-RAG general reasoning path.
    """
    out = _ollama_chat(
        messages=[
            {"role": "system", "content": "You are a concise, friendly assistant."},
            {"role": "user", "content": query},
        ]
    )
    return out.strip() if out else "I couldn't generate an answer."

class ChatBot:
    """
    Drop-in replacement for previous ChatBot. Uses Ollama /api/chat.
    Accepts optional initial_history to match older constructor signatures.
    """
    def __init__(
        self,
        model: Optional[str] = None,
        initial_history: Optional[List[Dict[str, str]]] = None,
        **kwargs
    ):
        # Allow overriding model via argument
        if model:
            os.environ["OLLAMA_MODEL"] = model
        # Keep compatibility with app.py which may pass initial_history
        self.initial_history = initial_history or []

    def chat(
        self,
        history: Optional[List[Dict[str, str]]] = None,
        temperature: float = 0.7,
        max_output_tokens: int = 800
    ) -> str:
        msgs = (history or []) or self.initial_history
        if not msgs or msgs[0].get("role") != "system":
            msgs = [{"role": "system", "content": "You are a helpful assistant."}] + msgs
        return _ollama_chat(messages=msgs, temperature=temperature, max_tokens=max_output_tokens)

