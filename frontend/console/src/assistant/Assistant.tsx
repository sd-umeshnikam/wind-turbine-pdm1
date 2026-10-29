// Maintenance assistant panel: a tool-calling LLM over the live platform data. Answers carry
// their sources (links into the console), unverified figures are marked, and every answer
// offers follow-up questions. The page on screen (turbine, alert) is sent as context.
// The conversation lives in the provider, so closing the panel keeps it and an answer that
// arrives while the panel is closed is still shown on reopening.

import { MessageSquarePlus, Send, Sparkles, ThumbsDown, ThumbsUp, TriangleAlert, X } from "lucide-react";
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
import { ErrorBoundary } from "../components/ErrorBoundary";
import { Markdown } from "../components/Markdown";
import { TurbineLoader } from "../components/TurbineLoader";
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

function errorText(err: unknown): string {
  if (err instanceof ApiError && err.status === 429) return "Too many questions in a short time. Please wait a minute.";
  return `The assistant could not answer: ${err instanceof Error ? err.message : String(err)}`;
}

/** One conversation: its turns, the server conversation id and the unsent draft. */
function useConversation() {
  const chat = useChat();
  const feedback = useFeedback();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [conversation, setConversation] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  // Bumped by "New conversation": answers to questions from an earlier session are dropped.
  const session = useRef(0);
  const busy = turns.some((t) => !t.response && !t.error);
  const update = (id: string, patch: Partial<Turn>) => setTurns((t) => t.map((x) => (x.id === id ? { ...x, ...patch } : x)));

  const send = (question: string, context: ChatContext): boolean => {
    const q = question.trim();
    if (!q || busy) return false;
    const id = `${Date.now()}`;
    const epoch = session.current;
    setTurns((t) => [...t, { id, question: q }]);
    setDraft("");
    chat.mutateAsync({ message: q, conversation_id: conversation, context }).then(
      (response) => {
        if (epoch !== session.current) return;
        setConversation(response.conversation_id);
        update(id, { response });
      },
      (err: unknown) => {
        if (epoch === session.current) update(id, { error: errorText(err) });
      },
    );
    return true;
  };

  const reset = () => {
    session.current += 1;
    setTurns([]);
    setConversation(null);
    setDraft("");
  };

  const rate = (turn: Turn, rating: 1 | -1) => {
    if (!turn.response?.message_id) return;
    feedback.mutate({ id: turn.response.message_id, rating });
    update(turn.id, { rated: rating });
  };

  return { turns, busy, draft, setDraft, send, reset, rate };
}

type Conversation = ReturnType<typeof useConversation>;

export function AssistantProvider({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState<string | null>(null);
  const conversation = useConversation();
  const ask = useCallback((q: string) => {
    setOpen(true);
    setPending(q);
  }, []);
  return (
    <AssistantContext.Provider value={{ open, setOpen, ask }}>
      {children}
      {open && (
        <aside className="assistant" role="complementary" aria-label="Maintenance assistant">
          <ErrorBoundary area="the assistant">
            <AssistantPanel
              onClose={() => setOpen(false)}
              conversation={conversation}
              pending={pending}
              clearPending={() => setPending(null)}
            />
          </ErrorBoundary>
        </aside>
      )}
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
  if (!r) return <TurbineLoader label="Looking at the live data…" />;
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

function AssistantPanel({
  onClose,
  conversation,
  pending,
  clearPending,
}: {
  onClose: () => void;
  conversation: Conversation;
  pending: string | null;
  clearPending: () => void;
}) {
  const context = usePageContext();
  const status = useAssistantStatus();
  const starters = useStarters(context);
  const { turns, busy, draft, setDraft, reset, rate } = conversation;
  const send = (question: string) => conversation.send(question, context);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" }), [turns]);

  // A question asked from elsewhere in the console; held until the current answer arrives.
  useEffect(() => {
    if (pending && conversation.send(pending, context)) clearPending();
  }, [pending, conversation, context, clearPending]);

  const scope = context.alert_id ? "the open alert" : context.turbine_id ? `turbine ${context.turbine_id}` : null;

  return (
    <>
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
          onClick={reset}
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
        <button className="btn primary icon" type="submit" disabled={!draft.trim() || busy} aria-label="Send">
          <Send size={15} />
        </button>
      </form>
      <div className="subtle" style={{ padding: "0 16px 10px" }}>
        Advisory only. Verify before acting; site safety procedures take precedence.
      </div>
    </>
  );
}
