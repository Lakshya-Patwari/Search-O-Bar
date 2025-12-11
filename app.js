const form = document.getElementById("askForm");
const queryEl = document.getElementById("query");
const loader = document.getElementById("loader");
const result = document.getElementById("result");
const answerEl =document.getElementById("answer");
const sourcesEl = document.getElementById("sources");
const themeToggle = document.getElementById("themeToggle");

// NEW: Element for the chat handoff button
const chatHandoffContainer = document.getElementById("chatHandoffContainer");

themeToggle?.addEventListener("click", () => {
  document.documentElement.classList.toggle("light");
});

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const query = queryEl.value.trim();
  if (!query) return;

  loader.classList.remove("hidden");
  result.classList.add("hidden");
  answerEl.textContent = "";
  sourcesEl.innerHTML = "";
  
  // NEW: Clear the handoff button container for a new search
  chatHandoffContainer.innerHTML = "";
  chatHandoffContainer.classList.add("hidden");


  try {
    const res = await fetch("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query }),
    });
    
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.error || "Request failed");
    }
    
    const data = await res.json();
    answerEl.innerHTML = (data.answer || "No answer.").replace(/\n/g, "<br>");

    // 1. Render Sources
    (data.sources || []).forEach((s, i) => {
      const li = document.createElement("li");
      const a = document.createElement("a");
      a.href = s.url;
      a.target = "_blank";
      a.rel = "noreferrer";
      a.textContent = `${i + 1}. ${s.title}`;
      const p = document.createElement("div");
      p.textContent = s.snippet || "";
      li.appendChild(a);
      li.appendChild(p);
      sourcesEl.appendChild(li);
    });

    // 2. NEW: Add the Chat Handoff Button
    if (data.session_id) {
        const chatButton = document.createElement("a");
        // Pass the session_id to the chat page via URL parameter
        chatButton.href = `/chat.html?session_id=${data.session_id}`; 
        chatButton.classList.add("start-chat-button"); // Add class for styling
        chatButton.textContent = "Continue in Chat (Ask Follow-ups)";
        
        chatHandoffContainer.appendChild(chatButton);
        chatHandoffContainer.classList.remove("hidden");
    } else {
        chatHandoffContainer.classList.add("hidden");
    }
    
  } catch (error) {
    console.error("Fetch Error:", error);
    answerEl.innerHTML = `[ERROR] ${error.message}`;
  } finally {
    loader.classList.add("hidden");
    result.classList.remove("hidden");
  }
});

// Note: Ensure you have updated index.html to include:
// <div id="chatHandoffContainer" class="handoff-container hidden"></div>
// inside the <section id="result"> element.