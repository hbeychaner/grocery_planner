document.addEventListener("DOMContentLoaded", () => {
  const chatForm = document.getElementById("chat-form");
  const chatInput = document.getElementById("chat-input");
  const chatMessages = document.getElementById("chat-messages");
  const chatSendBtn = document.getElementById("chat-send-btn");
  const chatStatus = document.getElementById("chat-agent-status");
  const suggestions = document.getElementById("chat-suggestions");

  if (!chatForm || !chatInput || !chatMessages) return;

  function makeId() {
    return (crypto && crypto.randomUUID) ? crypto.randomUUID() : String(Date.now());
  }

  function appendMessage(text, role) {
    const div = document.createElement("div");
    div.className = `chat-msg ${role === "user" ? "chat-msg-user" : "chat-msg-bot"}`;
    div.textContent = text;
    chatMessages.appendChild(div);
    chatMessages.scrollTop = chatMessages.scrollHeight;
    return div;
  }

  function extractReply(rpcResponse) {
    if (rpcResponse.error) {
      return `Error: ${rpcResponse.error.message || JSON.stringify(rpcResponse.error)}`;
    }
    const res = rpcResponse.result || {};
    const parts =
      res.task?.status?.message?.parts ||
      res.message?.parts ||
      res.status?.message?.parts ||
      [];
    const texts = parts.map(p => p.text).filter(Boolean);
    if (texts.length > 0) return texts.join("\n");
    return JSON.stringify(res);
  }

  async function sendChatMessage(text) {
    const trimmed = text.trim();
    if (!trimmed) return;

    appendMessage(trimmed, "user");
    chatInput.value = "";
    chatInput.disabled = true;
    chatSendBtn.disabled = true;
    const typingEl = appendMessage("Thinking via FastMCP + Gemini 3.5 Flash...", "bot");

    try {
      const resp = await fetch("/a2a", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          jsonrpc: "2.0",
          id: makeId(),
          method: "SendMessage",
          params: {
            message: {
              messageId: makeId(),
              role: "ROLE_USER",
              parts: [{ text: trimmed }],
            },
          },
        }),
      });
      const data = await resp.json();
      typingEl.textContent = extractReply(data);
    } catch (err) {
      typingEl.textContent = `Request failed: ${err.message}`;
    } finally {
      chatInput.disabled = false;
      chatSendBtn.disabled = false;
      chatInput.focus();
    }
  }

  chatForm.addEventListener("submit", (e) => {
    e.preventDefault();
    sendChatMessage(chatInput.value);
  });

  if (suggestions) {
    suggestions.querySelectorAll("button[data-prompt]").forEach(btn => {
      btn.addEventListener("click", () => {
        sendChatMessage(btn.getAttribute("data-prompt") || "");
      });
    });
  }

  // Verify A2A AgentCard discovery on load
  fetch("/.well-known/agent-card.json")
    .then(r => {
      if (chatStatus) {
        chatStatus.textContent = r.ok ? "A2A Ready" : "A2A Offline";
      }
    })
    .catch(() => {
      if (chatStatus) chatStatus.textContent = "A2A Offline";
    });
});
