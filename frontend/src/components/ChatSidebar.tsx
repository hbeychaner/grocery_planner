import { useState, type FormEvent } from "react";
import { Bot, CheckCircle2, ChevronDown, ChevronRight, Loader2, Send, Wrench, XCircle } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { streamAgentChat, type AgentStreamEvent } from "../api";
import { useLang } from "../i18n";

interface AgentStep {
  id: string;
  kind: "thought" | "tool";
  label: string;
  detail?: string;
  status: "running" | "done" | "error";
}

interface ChatMessage {
  id: string;
  role: "user" | "bot";
  text: string;
  steps?: AgentStep[];
  streaming?: boolean;
  stepsOpen?: boolean;
}

const SUGGESTIONS_EN = [
  "Compare butter prices between Rohlík and Košík",
  "Where is whole milk cheaper right now?",
  "Show dairy averages in comparison mode",
];

const SUGGESTIONS_CS = [
  "Porovnej ceny másla na Rohlíku a Košíku",
  "Kde je teď levnější plnotučné mléko?",
  "Jaké jsou dnešní slevy na mléčné výrobky?",
];

function formatToolName(rawName: string): string {
  const clean = rawName
    .replace(/_api_v1_.*$/, "")
    .replace(/_/g, " ")
    .trim();
  return clean || rawName;
}

export function ChatSidebar() {
  const { lang, t } = useLang();
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: "welcome",
      role: "bot",
      text: t(
        "Hi! Ask me to compare prices between Rohlík and Košík, find active discounts, or check grocery price trends.",
        "Ahoj! Zeptejte se mě na srovnání cen mezi Rohlíkem a Košíkem, aktuální slevy nebo vývoj cen potravin."
      ),
    },
  ]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);

  function toggleSteps(msgId: string) {
    setMessages((prev) =>
      prev.map((m) => (m.id === msgId ? { ...m, stepsOpen: !m.stepsOpen } : m))
    );
  }

  async function submitPrompt(text: string) {
    const trimmed = text.trim();
    if (!trimmed || sending) return;

    const userMsg: ChatMessage = { id: `${Date.now()}-u`, role: "user", text: trimmed };
    const botId = `${Date.now()}-b`;
    setMessages((prev) => [
      ...prev,
      userMsg,
      {
        id: botId,
        role: "bot",
        text: "",
        steps: [],
        streaming: true,
        stepsOpen: true,
      },
    ]);
    setInput("");
    setSending(true);

    try {
      await streamAgentChat(trimmed, (ev: AgentStreamEvent) => {
        setMessages((prev) =>
          prev.map((m) => {
            if (m.id !== botId) return m;
            const steps = [...(m.steps || [])];

            if (ev.type === "thought") {
              steps.push({
                id: `thought-${steps.length}`,
                kind: "thought",
                label: ev.text,
                status: "done",
              });
              return { ...m, steps };
            }

            if (ev.type === "tool_call") {
              const argsText = Object.keys(ev.args || {}).length
                ? JSON.stringify(ev.args)
                : "";
              steps.push({
                id: `tool-${ev.turn}-${ev.name}-${steps.length}`,
                kind: "tool",
                label: formatToolName(ev.name),
                detail: argsText || undefined,
                status: "running",
              });
              return { ...m, steps };
            }

            if (ev.type === "tool_result") {
              const idx = [...steps]
                .reverse()
                .findIndex((s) => s.kind === "tool" && s.status === "running");
              if (idx !== -1) {
                const realIdx = steps.length - 1 - idx;
                steps[realIdx] = {
                  ...steps[realIdx],
                  status: ev.ok ? "done" : "error",
                  detail: ev.summary,
                };
              }
              return { ...m, steps };
            }

            if (ev.type === "answer") {
              return {
                ...m,
                text: ev.text,
                streaming: false,
                stepsOpen: false,
              };
            }

            if (ev.type === "error") {
              return {
                ...m,
                text: `Error: ${ev.message}`,
                streaming: false,
              };
            }

            return m;
          })
        );
      });
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Request failed";
      setMessages((prev) =>
        prev.map((m) =>
          m.id === botId ? { ...m, text: `Error: ${msg}`, streaming: false } : m
        )
      );
    } finally {
      setSending(false);
    }
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    submitPrompt(input);
  }

  const suggestions = lang === "cs" ? SUGGESTIONS_CS : SUGGESTIONS_EN;

  return (
    <aside className="w-full lg:w-96 shrink-0 lg:sticky lg:top-4 lg:h-[min(660px,calc(100vh-2rem))] rounded-2xl border border-slate-200 bg-white shadow-xs flex flex-col overflow-hidden">
      <div className="px-4 py-3 border-b border-slate-200 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Bot className="w-4 h-4 text-indigo-600" />
          <div>
            <h2 className="text-sm font-semibold text-slate-900">
              {t("Grocery Assistant", "Asistent nákupů")}
            </h2>
            <p className="text-[11px] text-slate-500">
              {t("Prices, discounts & trends", "Ceny, slevy a vývoj cen")}
            </p>
          </div>
        </div>
        <span className="inline-flex items-center gap-1.5 text-[11px] font-medium px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
          {t("Ready", "Připraven")}
        </span>
      </div>

      <div className="px-3 py-2 border-b border-slate-100 flex flex-wrap gap-1.5">
        {suggestions.map((s) => (
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
            className={`max-w-[90%] rounded-xl px-3.5 py-2.5 text-xs leading-relaxed break-words ${
              m.role === "user"
                ? "ml-auto bg-indigo-600 text-white rounded-br-xs whitespace-pre-wrap"
                : "mr-auto bg-white text-slate-800 border border-slate-200 rounded-bl-xs shadow-2xs space-y-2"
            }`}
          >
            {m.role === "bot" && ((m.steps && m.steps.length > 0) || m.streaming) && (
              <div className="rounded-lg border border-slate-200 bg-slate-50/90 overflow-hidden">
                <button
                  type="button"
                  onClick={() => toggleSteps(m.id)}
                  className="w-full px-2.5 py-1.5 flex items-center justify-between gap-2 text-[11px] font-medium text-slate-600 hover:bg-slate-100 cursor-pointer"
                >
                  <span className="inline-flex items-center gap-1.5">
                    {m.streaming ? (
                      <Loader2 className="w-3 h-3 animate-spin text-indigo-600" />
                    ) : (
                      <CheckCircle2 className="w-3 h-3 text-emerald-600" />
                    )}
                    <span>
                      {m.streaming
                        ? t("Working...", "Pracuji...")
                        : t(
                            `Thought process (${m.steps?.length || 0} steps)`,
                            `Postup (${m.steps?.length || 0} kroků)`
                          )}
                    </span>
                  </span>
                  {m.stepsOpen ? (
                    <ChevronDown className="w-3.5 h-3.5 text-slate-400" />
                  ) : (
                    <ChevronRight className="w-3.5 h-3.5 text-slate-400" />
                  )}
                </button>

                {m.stepsOpen && (
                  <div className="px-2.5 py-2 border-t border-slate-200 space-y-1.5 text-[11px] text-slate-600">
                    {(!m.steps || m.steps.length === 0) && m.streaming && (
                      <div className="text-slate-400 italic">
                        {t("Thinking...", "Přemýšlím...")}
                      </div>
                    )}
                    {(m.steps || []).map((step) => (
                      <div key={step.id} className="space-y-0.5">
                        <div className="flex items-start gap-1.5">
                          {step.kind === "tool" ? (
                            step.status === "running" ? (
                              <Loader2 className="w-3 h-3 mt-0.5 shrink-0 animate-spin text-indigo-600" />
                            ) : step.status === "error" ? (
                              <XCircle className="w-3 h-3 mt-0.5 shrink-0 text-red-500" />
                            ) : (
                              <Wrench className="w-3 h-3 mt-0.5 shrink-0 text-slate-400" />
                            )
                          ) : (
                            <span className="w-1.5 h-1.5 mt-1.5 rounded-full bg-indigo-400 shrink-0" />
                          )}
                          <span className="font-medium text-slate-700 capitalize">
                            {step.label}
                          </span>
                        </div>
                        {step.detail && (
                          <div className="pl-4 text-[10px] text-slate-400 font-mono truncate">
                            {step.detail}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {m.text && (
              <div className="space-y-2 [&>h1]:text-sm [&>h1]:font-bold [&>h2]:text-xs [&>h2]:font-bold [&>h3]:text-xs [&>h3]:font-semibold [&>h3]:text-slate-900 [&>p]:leading-relaxed [&>ul]:list-disc [&>ul]:pl-4 [&>ul]:space-y-1 [&>ol]:list-decimal [&>ol]:pl-4 [&>ol]:space-y-1 [&>hr]:border-slate-200 [&>hr]:my-2 [&_strong]:font-semibold [&_a]:text-indigo-600 [&_a]:underline [&_code]:bg-slate-100 [&_code]:px-1 [&_code]:rounded [&_table]:w-full [&_table]:text-[11px] [&_th]:text-left [&_th]:border-b [&_th]:border-slate-200 [&_th]:py-1 [&_td]:border-b [&_td]:border-slate-100 [&_td]:py-1">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{m.text}</ReactMarkdown>
              </div>
            )}
          </div>
        ))}
      </div>

      <form onSubmit={handleSubmit} className="p-3 border-t border-slate-200 bg-white flex gap-2">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          disabled={sending}
          placeholder={t("Ask about prices, deals, or trends...", "Zeptejte se na ceny, slevy nebo vývoj...")}
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
