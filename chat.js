// Global variable to store the unique session ID for the multi-turn conversation
let chatSessionId = null;

const chatForm = document.getElementById("chatForm");
const chatQueryEl = document.getElementById("chatQuery");
const chatWindow = document.getElementById("chatWindow");
const loader = document.getElementById("loader");

// --- UTILITY FUNCTIONS ---
const addMessage = (text, sender) => {
    const messageDiv = document.createElement("div");
    messageDiv.classList.add("message");
    messageDiv.classList.add(`${sender}-message`);

    const p = document.createElement("p");
    p.innerHTML = text; // Assumes text is already HTML-formatted (with <br>)
    messageDiv.appendChild(p);
    chatWindow.appendChild(messageDiv);
    
    // Auto-scroll to the bottom of the chat window
    chatWindow.scrollTop = chatWindow.scrollHeight;
};

// --- INITIALIZATION LOGIC ---

// Function to parse the session ID from the URL
const getSessionIdFromUrl = () => {
    const params = new URLSearchParams(window.location.search);
    return params.get('session_id');
};

// Function to load and display the initial chat history (MODIFIED)
const loadInitialHistory = async () => {
    chatSessionId = getSessionIdFromUrl();
    
    if (!chatSessionId) {
        // If no session ID in URL, prompt the user to start a conversation first.
        addMessage("Welcome! To continue a conversation, please start a RAG search first and click the 'Continue in Chat' button.", "bot");
        return; 
    }

    loader.classList.remove("hidden");
    chatQueryEl.disabled = true; // Disable input while loading

    try {
        // Fetch the conversation history from the backend (FIXED FETCH CALL)
        const res = await fetch(`/api/chat/history?session_id=${chatSessionId}`);
        
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.error || "Failed to load chat history.");
        }

        const data = await res.json();
        
        // Display loaded history (the initial Q&A)
        data.history.forEach(msg => {
            // msg.sender will be "user" or "bot" as formatted in app.py
            addMessage(msg.text, msg.sender);
        });

        // Add a friendly continuation message
        addMessage("This chat continues the topic above. Ask me a follow-up question!", "bot");

    } catch (error) {
        console.error("History Load Error:", error);
        addMessage(`[ERROR] Failed to load previous conversation. Details: ${error.message}`, "bot-error");
    } finally {
        loader.classList.add("hidden");
        chatQueryEl.disabled = false;
        chatQueryEl.focus();
    }
};


// --- MAIN CHAT LOGIC (Modified to check for existing ID) ---

chatForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const query = chatQueryEl.value.trim();
    
    // Check if we have an active session ID before proceeding
    if (!query) return;
    if (!chatSessionId) {
        // Handle case where user is on chat.html without a session (e.g., direct URL access)
        addMessage("Please start a new conversation by asking a full question first.", "bot-error");
        return; 
    }

    // 1. Add user message and clear input
    addMessage(query, "user");
    chatQueryEl.value = "";
    loader.classList.remove("hidden");
    
    try {
        const payload = { 
            query: query,
            session_id: chatSessionId // Always send the existing session ID
        };

        const res = await fetch("/api/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });

        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.error || "Request failed");
        }

        const data = await res.json();
        
        // 4. Add bot response to chat window
        addMessage(data.answer || "I did not receive a proper response.", "bot");

    } catch (error) {
        console.error("Chat Submit Error:", error);
        addMessage(`[ERROR] ${error.message}`, "bot-error");
    } finally {
        loader.classList.add("hidden");
    }
});

// Execute on page load
loadInitialHistory();