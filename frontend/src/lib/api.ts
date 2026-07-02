// 与 FastAPI /api/* 的薄封装。dev 时 Vite proxy 转发到 8000。

export interface SessionItem {
  session_id: string;
  title?: string;
  updated_at?: string;
}

export interface HistoryMessage {
  id?: string;
  role: 'user' | 'bot' | string;
  text: string;
  image?: string | null;
}

async function jsonOrThrow<T>(r: Response): Promise<T> {
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return (await r.json()) as T;
}

export async function listSessions(): Promise<SessionItem[]> {
  const r = await fetch('/api/sessions');
  const data = await jsonOrThrow<{ sessions?: SessionItem[] }>(r);
  return data.sessions || [];
}

export async function createSession(sessionId: string): Promise<void> {
  const form = new FormData();
  form.append('session_id', sessionId);
  await fetch('/api/session', { method: 'POST', body: form });
}

export async function deleteSession(sessionId: string): Promise<void> {
  const form = new FormData();
  form.append('session_id', sessionId);
  await fetch('/api/delete', { method: 'POST', body: form });
}

export async function getHistory(sessionId: string): Promise<HistoryMessage[]> {
  const r = await fetch('/api/history?session_id=' + encodeURIComponent(sessionId));
  const data = await jsonOrThrow<{ messages?: HistoryMessage[] }>(r);
  return data.messages || [];
}

export async function deleteMessage(sessionId: string, messageId: string): Promise<boolean> {
  const form = new FormData();
  form.append('session_id', sessionId);
  form.append('message_id', messageId);
  const r = await fetch('/api/message/delete', { method: 'POST', body: form });
  const data = await jsonOrThrow<{ ok?: boolean }>(r);
  return !!data.ok;
}

// SSE 事件的联合类型：与 chat_service.stream_reply 输出对齐。
export type ChatEvent =
  | { type: 'reasoning'; delta: string }
  | { type: 'tool_start'; id: string; name: string; input?: unknown }
  | { type: 'tool_end'; id: string; output?: unknown }
  | { type: 'ids'; user_id?: string; ai_id?: string }
  | { type: 'delta'; text: string }
  | { type: 'error'; message: string }
  // 兼容旧的 {delta: "..."} 格式
  | { type?: undefined; delta?: string };

/** 发起一次 chat：返回一个可读的事件流，供上层订阅。 */
export async function streamChat(params: {
  message: string;
  sessionId: string;
  image?: File | null;
  onEvent: (evt: ChatEvent) => void;
  signal?: AbortSignal;
}): Promise<void> {
  const form = new FormData();
  form.append('message', params.message);
  form.append('session_id', params.sessionId);
  if (params.image) form.append('image', params.image);
  const resp = await fetch('/api/chat', {
    method: 'POST',
    body: form,
    signal: params.signal,
  });
  if (!resp.ok || !resp.body) throw new Error(`HTTP ${resp.status}`);
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const chunks = buffer.split('\n\n');
    buffer = chunks.pop() || '';
    for (const chunk of chunks) {
      if (!chunk.startsWith('data: ')) continue;
      const payload = chunk.slice(6);
      if (payload === '[DONE]') continue;
      try {
        const evt = JSON.parse(payload) as ChatEvent;
        params.onEvent(evt);
      } catch {
        // 忽略无法解析的行
      }
    }
  }
}

/** 简易 UUID：足以给一次前端会话打临时 id；后端会以此为主键落库。 */
export function newSessionId(): string {
  return 'web-' + Math.random().toString(36).slice(2) + Date.now().toString(36);
}
