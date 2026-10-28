// Maintenance assistant panel: a tool-calling LLM over the live platform data. Answers carry
// their sources (links into the console), unverified figures are marked, and every answer
// offers follow-up questions. The page on screen (turbine, alert) is sent as context.

import { Bot, MessageSquarePlus, Send, Sparkles, ThumbsDown, ThumbsUp, TriangleAlert, X } from "lucide-react";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { Link, useLocation, useSearchParams } from "react-router-dom";
import { ApiError } from "../api/client";
import { useAssistantStatus, useChat, useFeedback, useStarters } from "../api/hooks";
import type { ChatContext, ChatResponse } from "../api/types";
import { Markdown } from "../components/Markdown";
import { InsightsList } from "./Insights";

interface Turn {
  id: string;
  question: string;
  response?: ChatResponse;
  error?: string;
  rated?: 1 | -1;
}

interface AssistantValue {
  open: boolean;
  setOpen(open: boolean): void;
  ask(question: string): void;
}

const AssistantContext = createContext<AssistantValue>({ open: false, setOpen: () => undefined, ask: () => undefined });
export const useAssistant = () => useContext(AssistantContext);

/** What is on screen: sent with every question so "this turbine" / "this alert" resolve. */
export function usePageContext(): ChatContext {
  const { pathname } = useLocation();
  const [params] = useSearchParams();
  return useMemo(() => {
    const turbine = pathname.match(/^\/turbines\/([ABC]-\d{1,2})/)?.[1];
    const alert = pathname.startsWith("/alerts") ? params.get("id") ?? undefined : undefined;
    const page = pathname === "/" ? "fleet" : pathname.split("/")[1] || "fleet";
    return { page, turbine_id: turbine, alert_id: alert };
  }, [pathname, params]);
}

export function AssistantProvider({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState<string | null>(null);
  const ask = useCallback((q: string) => {
    setOpen(true);
    setPending(q);
  }, []);
  return (
    <AssistantContext.Provider value={{ open, setOpen, ask }}>
      {children}
      {open && <AssistantPanel onClose={() => setOpen(false)} pending={pending} clearPending={() => setPending(null)} />}
    </AssistantContext.Provider>
  );
}

export function AssistantLauncher() {
  const { open, setOpen } = useAssistant();
  return (
    <button className={`btn ${open ? "primary" : ""}`} onClick={() => setOpen(!open)} aria-expanded={open} title="Ask the maintenance assistant">
      <Sparkles size={15} /> Assistant
    </button>
  );
}

function Answer({ turn, onAsk, onRate }: { turn: Turn; onAsk: (q: string) => void; onRate: (r: 1 | -1) => void }) {
  const r = turn.response;
  if (turn.error)
    return (
      <div className="banner error" style={{ margin: 0 }}>
        {turn.error}
      </div>
    );
  if (!r)
    return (
      <div className="row subtle" role="status">
        <Bot size={14} /> Looking at the live data…
      </div>
    );
  const unverified = r.flags.includes("ungrounded_figures");
  return (
    <div className="stack" style={{ gap: 8 }}>
      <div className={r.blocked ? "banner warn" : undefined} style={r.blocked ? { margin: 0 } : undefined}>
        <Markdown>{r.answer}</Markdown>
      </div>
      {unverified && (
        <div className="subtle row" style={{ gap: 4, color: "var(--warning-ink)" }}>
          <TriangleAlert size={13} /> Some figures could not be verified against the platform data.
        </div>
      )}
      {r.citations.length > 0 && (
        <div className="row" style={{ gap: 6 }} aria-label="Sources">
          <span className="subtle">Sources:</span>
          {r.citations.map((c) =>
            c.link ? (
              <Link key={`${c.kind}-${c.ref}`} className="badge accent" to={c.link}>
                {c.label}
              </Link>
            ) : (
              <span key={`${c.kind}-${c.ref}`} className="badge outline" title={c.ref}>
                {c.label}
              </span>
            ),
          )}
        </div>
      )}
      {!r.blocked && r.message_id !== null && (
        <div className="row subtle" style={{ gap: 4 }}>
          {r.tools.length > 0 && <span>{r.tools.length} data lookups · </span>}
          <span>{(r.latency_ms / 1000).toFixed(1)} s</span>
          <span style={{ flex: 1 }} />
          <button className="btn ghost sm icon" aria-label="Helpful" aria-pressed={turn.rated === 1} onClick={() => onRate(1)} disabled={!!turn.rated}>
            <ThumbsUp size={13} />
          </button>
          <button className="btn ghost sm icon" aria-label="Not helpful" aria-pressed={turn.rated === -1} onClick={() => onRate(-1)} disabled={!!turn.rated}>
            <ThumbsDown size={13} />
          </button>
        </div>
      )}
      {r.suggestions.length > 0 && (
        <div className="stack" style={{ gap: 4 }}>
          {r.suggestions.map((s) => (
            <button key={s} className="suggestion" onClick={() => onAsk(s)}>
              {s}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function AssistantPanel({ onClose, pending, clearPending }: { onClose: () => void; pending: string | null; clearPending: () => void }) {
  const context = usePageContext();
  const status = useAssistantStatus();
  const starters = useStarters(context);
  const chat = useChat();
  const feedback = useFeedback();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [conversation, setConversation] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" }), [turns]);

  const send = useCallback(
    (question: string) => {
      const q = question.trim();
      if (!q || chat.isPending) return;
      const id = `${Date.now()}`;
      setTurns((t) => [...t, { id, question: q }]);
      setDraft("");
      chat.mutate(
        { message: q, conversation_id: conversation, context },
        {
          onSuccess: (response) => {
            setConversation(response.conversation_id);
            setTurns((t) => t.map((x) => (x.id === id ? { ...x, response } : x)));
          },
          onError: (err) =>
            setTurns((t) =>
              t.map((x) =>
                x.id === id
                  ? {
                      ...x,
                      error:
                        err instanceof ApiError && err.status === 429
                          ? "Too many questions in a short time. Please wait a minute."
                          : `The assistant could not answer: ${err.message}`,
                    }
                  : x,
              ),
            ),
        },
      );
    },
    [chat, conversation, context],
  );

  useEffect(() => {
    if (pending) {
      send(pending);
      clearPending();
    }
  }, [pending, send, clearPending]);

  const rate = (turn: Turn, rating: 1 | -1) => {
    if (!turn.response?.message_id) return;
    feedback.mutate({ id: turn.response.message_id, rating });
    setTurns((t) => t.map((x) => (x.id === turn.id ? { ...x, rated: rating } : x)));
  };

  const scope = context.alert_id ? "the open alert" : context.turbine_id ? `turbine ${context.turbine_id}` : null;

  return (
    <aside className="assistant" role="complementary" aria-label="Maintenance assistant">
      <header className="assistant-head">
        <Sparkles size={16} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <h2>Maintenance assistant</h2>
          <div className="subtle">
            {status.data?.model ? `Answers from live platform data · ${status.data.model}` : "Answers from live platform data"}
          </div>
        </div>
        <button
          className="btn ghost icon"
          onClick={() => {
            setTurns([]);
            setConversation(null);
          }}
          title="New conversation"
          aria-label="New conversation"
        >
          <MessageSquarePlus size={16} />
        </button>
        <button className="btn ghost icon" onClick={onClose} aria-label="Close assistant">
          <X size={16} />
        </button>
      </header>
      <div className="assistant-body">
        {status.data && !status.data.available && (
          <div className="banner warn">The assistant is not configured on this platform (no language model key).</div>
        )}
        {turns.length === 0 ? (
          <div className="stack" style={{ gap: 14 }}>
            <InsightsList compact />
            <div>
              <div className="subtle" style={{ fontWeight: 600, marginBottom: 6 }}>
                {scope ? `Ask about ${scope}` : "Try asking"}
              </div>
              <div className="stack" style={{ gap: 4 }}>
                {(starters.data?.suggestions ?? []).map((s) => (
                  <button key={s} className="suggestion" onClick={() => send(s)}>
                    {s}
                  </button>
                ))}
              </div>
            </div>
          </div>
        ) : (
          <div className="stack" style={{ gap: 18 }}>
            {turns.map((t) => (
              <div key={t.id} className="stack" style={{ gap: 8 }}>
                <div className="bubble-user">{t.question}</div>
                <Answer turn={t} onAsk={send} onRate={(r) => rate(t, r)} />
              </div>
            ))}
          </div>
        )}
        <div ref={endRef} />
      </div>
      <form
        className="assistant-input"
        onSubmit={(e) => {
          e.preventDefault();
          send(draft);
        }}
      >
        <textarea
          className="textarea"
          rows={2}
          maxLength={1000}
          placeholder={scope ? `Ask about ${scope}, the fleet, alerts, models…` : "Ask about the fleet, a turbine, alerts, models…"}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send(draft);
            }
          }}
          aria-label="Question"
        />
        <button className="btn primary icon" type="submit" disabled={!draft.trim() || chat.isPending} aria-label="Send">
          <Send size={15} />
        </button>
      </form>
      <div className="subtle" style={{ padding: "0 16px 10px" }}>
        Advisory only. Verify before acting; site safety procedures take precedence.
      </div>
    </aside>
  );
}
