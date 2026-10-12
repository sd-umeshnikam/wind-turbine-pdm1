// Client for the turbine assistant (local-stack/chatbot). Same-origin by default:
// nginx proxies /api/chat in Docker, and vite.config.ts proxies it in `npm run dev`.
const CHAT_URL = (import.meta.env.VITE_CHAT_URL as string | undefined) ?? "/api/chat";

export interface ChatTurn {
  role: "user" | "assistant";
  content: string;
}

export interface ChatSource {
  id: string;
  title: string;
  snippet: string;
  origin: string;
  score: number;
}

export interface ChatReply {
  answer: string;
  mode: "llm" | "retrieval_only" | "guardrail" | "greeting";
  sources: ChatSource[];
  turbines: string[];
  live_sources: string[];
  guardrail: { blocked?: boolean; reason?: string; flags?: string[]; ungrounded_figures?: string[] };
}

export interface ChatHealth {
  status: string;
  llm_configured: boolean;
  knowledge_chunks: number;
}

export async function sendChat(message: string, history: ChatTurn[], turbineId?: string): Promise<ChatReply> {
  const res = await fetch(CHAT_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, history: history.slice(-6), turbine_id: turbineId }),
  });
  if (!res.ok) throw new Error(`Assistant returned ${res.status}`);
  return res.json();
}

export async function getChatHealth(): Promise<ChatHealth> {
  const res = await fetch(`${CHAT_URL}/health`);
  if (!res.ok) throw new Error(`Assistant returned ${res.status}`);
  return res.json();
}
