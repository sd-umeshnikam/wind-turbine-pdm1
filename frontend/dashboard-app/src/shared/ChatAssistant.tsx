import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { useLocation } from "react-router-dom";
import { getChatHealth, sendChat, type ChatReply, type ChatTurn } from "../api/chat";
import "./ChatAssistant.css";

const MAX_CHARS = 1000;

interface Message extends ChatTurn {
  reply?: ChatReply;
  error?: boolean;
}

function turbineFromPath(pathname: string): string | undefined {
  return pathname.match(/^\/(?:assets|twin|forecasts)\/([^/]+)/)?.[1];
}

function suggestions(turbineId?: string): string[] {
  return turbineId
    ? [`What failures has ${turbineId} had?`, `What is the remaining life of ${turbineId}?`, "What does P10 mean?"]
    : ["Why does Farm C have so many pitch faults?", "How does the gearbox fail?", "What does P10 mean?"];
}

function Reply({ reply }: { reply: ChatReply }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      {reply.mode === "retrieval_only" && <span className="chat-tag">Limited mode</span>}
      {reply.guardrail.flags?.includes("ungrounded_figures") && (
        <span className="chat-tag warn">Unverified figures</span>
      )}
      {reply.sources.length + reply.live_sources.length > 0 && (
        <div className="chat-sources">
          <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
            {open ? "Hide" : "Show"} sources ({reply.sources.length + reply.live_sources.length})
          </button>
          {open && (
            <ol>
              {reply.live_sources.map((label) => (
                <li key={label}>
                  <strong>LIVE · {label}</strong>
                </li>
              ))}
              {reply.sources.map((s, i) => (
                <li key={s.id}>
                  <strong>
                    S{i + 1} · {s.title}
                  </strong>
                  <span>{s.origin}</span>
                </li>
              ))}
            </ol>
          )}
        </div>
      )}
    </>
  );
}

export function ChatAssistant() {
  const { pathname } = useLocation();
  const turbineId = turbineFromPath(pathname);
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [llmReady, setLlmReady] = useState<boolean | null>(null);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open || llmReady !== null) return;
    getChatHealth()
      .then((h) => setLlmReady(h.llm_configured))
      .catch(() => setLlmReady(false));
  }, [open, llmReady]);

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight });
  }, [messages, busy]);

  async function ask(text: string) {
    const question = text.trim();
    if (!question || busy) return;
    const history: ChatTurn[] = messages.filter((m) => !m.error).map(({ role, content }) => ({ role, content }));
    setMessages((m) => [...m, { role: "user", content: question }]);
    setInput("");
    setBusy(true);
    try {
      const reply = await sendChat(question, history, turbineId);
      setMessages((m) => [...m, { role: "assistant", content: reply.answer, reply }]);
    } catch {
      setMessages((m) => [
        ...m,
        { role: "assistant", content: "Assistant unavailable. Try again.", error: true },
      ]);
    } finally {
      setBusy(false);
    }
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    void ask(input);
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void ask(input);
    }
  }

  return (
    <>
      {open && (
        <section
          className="chat-panel"
          role="dialog"
          aria-label="Turbine assistant"
          onKeyDown={(e) => e.key === "Escape" && setOpen(false)}
        >
          <header className="chat-header">
            <div>
              <strong>Turbine Assistant</strong>
              <span className="chat-sub">
                {llmReady === false ? "Limited mode" : "Answers from platform data"}
                {turbineId && ` · viewing ${turbineId}`}
              </span>
            </div>
            <button type="button" className="chat-close" aria-label="Close assistant" onClick={() => setOpen(false)}>
              ×
            </button>
          </header>

          <div className="chat-messages" ref={listRef} aria-live="polite">
            {messages.length === 0 && (
              <div className="chat-empty">
                <p>Ask about turbines, failures, alerts or remaining life.</p>
                {suggestions(turbineId).map((s) => (
                  <button key={s} type="button" className="chat-suggestion" onClick={() => void ask(s)}>
                    {s}
                  </button>
                ))}
              </div>
            )}
            {messages.map((m, i) => (
              <div
                key={i}
                className={`chat-msg ${m.role}${m.reply?.mode === "guardrail" ? " blocked" : ""}${m.error ? " error" : ""}`}
              >
                <p>{m.content}</p>
                {m.reply && <Reply reply={m.reply} />}
              </div>
            ))}
            {busy && <div className="chat-msg assistant typing">Thinking…</div>}
          </div>

          <form className="chat-input" onSubmit={onSubmit}>
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value.slice(0, MAX_CHARS))}
              onKeyDown={onKeyDown}
              placeholder={turbineId ? `Ask about ${turbineId} or the fleet…` : "Ask a question…"}
              rows={2}
              aria-label="Your question"
              disabled={busy}
              autoFocus
            />
            <div className="chat-input-row">
              <span className="chat-count">
                {input.length}/{MAX_CHARS}
              </span>
              <button type="submit" disabled={busy || !input.trim()}>
                Send
              </button>
            </div>
          </form>
        </section>
      )}

      <button
        type="button"
        className="chat-launcher"
        aria-label={open ? "Close assistant" : "Open turbine assistant"}
        onClick={() => setOpen((o) => !o)}
      >
        <svg viewBox="0 0 24 24" width="24" height="24" aria-hidden="true">
          <path
            fill="currentColor"
            d="M4 4h16a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H9l-5 4v-4H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2Zm3 6.5a1.5 1.5 0 1 0 0 .01Zm5 0a1.5 1.5 0 1 0 0 .01Zm5 0a1.5 1.5 0 1 0 0 .01Z"
          />
        </svg>
        <span>Ask</span>
      </button>
    </>
  );
}
