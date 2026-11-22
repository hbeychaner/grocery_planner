import { useState, type FormEvent } from "react";
import { Bot, Send } from "lucide-react";
import { sendA2AMessage } from "../api";

interface ChatMessage {
  id: string;
  role: "user" | "bot";
  text: string;
}

const SUGGESTIONS = [
  "Compare butter prices between Rohlík and Košík",
  "Where is whole milk cheaper right now?",
  "Show dairy averages in comparison mode",
];

export function ChatSidebar() {
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: "welcome",
      role: "bot",
      text: "Hello. I am your A2A Grocery Assistant connected to the FastMCP server. Ask me to compare prices, check your watchlist, or analyze Czech vs. US trends.",
    },
  ]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);

  async function submitPrompt(text: string) {
    const trimmed = text.trim();
    if (!trimmed || sending) return;

    const userMsg: ChatMessage = { id: `${Date.now()}-u`, role: "user", text: trimmed };
    const pendingId = `${Date.now()}-b`;
    setMessages((prev) => [
      ...prev,
      userMsg,
      { id: pendingId, role: "bot", text: "Querying FastMCP + Gemini 3.5 Flash..." },
    ]);
    setInput("");
    setSending(true);

    try {
      const reply = await sendA2AMessage(trimmed);
      setMessages((prev) =>
        prev.map((m) => (m.id === pendingId ? { ...m, text: reply } : m))
      );
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Request failed";
      setMessages((prev) =>
        prev.map((m) => (m.id === pendingId ? { ...m, text: `Error: ${msg}` } : m))
      );
    } finally {
      setSending(false);
    }
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    submitPrompt(input);
  }

  return (
    <aside className="w-full lg:w-96 shrink-0 lg:sticky lg:top-4 lg:h-[min(660px,calc(100vh-2rem))] rounded-2xl border border-slate-200 bg-white shadow-xs flex flex-col overflow-hidden">
      <div className="px-4 py-3 border-b border-slate-200 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Bot className="w-4 h-4 text-indigo-600" />
          <div>
            <h2 className="text-sm font-semibold text-slate-900">AI Assistant</h2>
            <p className="text-[11px] text-slate-500">A2A &bull; FastMCP &bull; Gemini 3.5 Flash</p>
          </div>
        </div>
        <span className="inline-flex items-center gap-1.5 text-[11px] font-medium px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
          Ready
        </span>
      </div>

      <div className="px-3 py-2 border-b border-slate-100 flex flex-wrap gap-1.5">
        {SUGGESTIONS.map((s) => (
          <button
            key={s}
            type="button"
            disabled={sending}
            onClick={() => submitPrompt(s)}
            className="text-[11px] px-2.5 py-1 rounded-md border border-slate-200 bg-slate-50 text-slate-600 hover:bg-slate-100 transition cursor-pointer"
          >
            {s.split(" ").slice(0, 3).join(" ")}...
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-3 bg-slate-50/70">
        {messages.map((m) => (
          <div
            key={m.id}
            className={`max-w-[88%] rounded-xl px-3.5 py-2.5 text-xs leading-relaxed whitespace-pre-wrap break-words ${
              m.role === "user"
                ? "ml-auto bg-indigo-600 text-white rounded-br-xs"
                : "mr-auto bg-white text-slate-800 border border-slate-200 rounded-bl-xs shadow-2xs"
            }`}
          >
            {m.text}
          </div>
        ))}
      </div>

      <form onSubmit={handleSubmit} className="p-3 border-t border-slate-200 bg-white flex gap-2">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          disabled={sending}
          placeholder="Ask about prices, deals, or trends..."
          className="flex-1 px-3 py-2 rounded-lg border border-slate-300 text-xs focus:outline-none focus:ring-2 focus:ring-indigo-500"
        />
        <button
          type="submit"
          disabled={sending || !input.trim()}
          className="inline-flex items-center justify-center px-3 py-2 rounded-lg bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50 transition cursor-pointer"
        >
          <Send className="w-3.5 h-3.5" />
        </button>
      </form>
    </aside>
  );
}
