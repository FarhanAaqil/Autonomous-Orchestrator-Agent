import type { components } from './generated';
type Schemas = components['schemas'];
export type Job = Schemas['JobRecord'];
export type Approval = Schemas['ApprovalRecord'];
export type Schedule = Schemas['ScheduleRecord'];
export type Memory = Schemas['MemoryItemResponse'];
export type Agent = Schemas['AgentInfo'];
export type Message = Schemas['MessageResponse'];
export type Conversation = Schemas['ConversationResponse'];
export type User = { id: string; username: string; role: 'administrator' | 'operator' | 'viewer' };
export type Session = { user: User; csrf_token: string };
export type Page<T> = { items: T[]; total: number; limit: number; offset: number };
export type EventData = Record<string, unknown>;
let csrf = '';
export function setSession(session: Session | null) { csrf = session?.csrf_token || ''; }
export function expired() { setSession(null); window.dispatchEvent(new Event('session-expired')); }
export class ApiError extends Error {
  status: number;
  data: EventData;
  constructor(status: number, data: EventData) {
    const detail = typeof data.detail === 'string' ? data.detail : typeof data.error === 'string' ? data.error : 'Check the fields and try again.';
    super(status === 403 ? 'You do not have permission for this action, or your session needs refreshing.' : detail);
    this.status = status; this.data = data;
  }
}
export async function request<T>(path: string, method = 'GET', body?: unknown, signal?: AbortSignal): Promise<T> {
  const response = await fetch(path, {method, credentials: 'same-origin', signal,
    headers: { ...(body === undefined ? {} : {'Content-Type': 'application/json'}), ...(method === 'GET' ? {} : {'X-CSRF-Token': csrf}) },
    body: body === undefined ? undefined : JSON.stringify(body)});
  const data = await response.json().catch(() => ({detail: 'The server returned an unreadable response.'}));
  if (path === '/ready' && response.status === 503) return data as T;
  if (!response.ok) { if (response.status === 401 && path !== '/auth/login') expired(); throw new ApiError(response.status, data); }
  return data as T;
}
export function parseEvent(block: string): {event: string; data: EventData} | null {
  let event = 'message'; const lines: string[] = [];
  for (const line of block.split('\n')) {
    if (line.startsWith('event:')) event = line.slice(6).trim();
    if (line.startsWith('data:')) lines.push(line.slice(5).trimStart());
  }
  if (!lines.length) return null;
  return {event, data: JSON.parse(lines.join('\n')) as EventData};
}
export async function dispatch(command: string, conversation_id: string | null, receive: (event: string, data: EventData) => void, signal: AbortSignal) {
  const response = await fetch('/dispatch/stream', {method: 'POST', credentials: 'same-origin', signal,
    headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrf}, body: JSON.stringify({command, conversation_id})});
  if (!response.ok) { if (response.status === 401) expired(); throw new ApiError(response.status, await response.json()); }
  if (!response.body) throw new Error('Response streaming is unavailable.');
  const reader = response.body.getReader(); const decoder = new TextDecoder(); let buffer = '';
  let doneEvent = false;
  try {
    while (true) {
      const {done, value} = await reader.read();
      buffer += decoder.decode(value, {stream: !done}).replace(/\r\n/g, '\n');
      let end: number;
      while ((end = buffer.indexOf('\n\n')) >= 0) {
        const parsed = parseEvent(buffer.slice(0, end)); buffer = buffer.slice(end + 2);
        if (!parsed) continue;
        if (parsed.event === 'session.expired') { expired(); throw new Error('Your session expired. Please sign in again.'); }
        if (parsed.event === 'error') throw new ApiError(400, parsed.data);
        if (['done', 'clarification'].includes(parsed.event)) doneEvent = true;
        receive(parsed.event, parsed.data);
      }
      if (done) break;
    }
    if (!doneEvent) throw new Error('The connection ended before completion. Check the saved conversation before retrying.');
  } finally { await reader.cancel(); reader.releaseLock(); }
}
export function subscribe(onEvent: (event: string) => void, onStatus: (status: string) => void) {
  const source = new EventSource('/jobs/events', {withCredentials: true});
  source.onopen = () => onStatus('Live');
  source.onerror = () => {onStatus('Reconnecting'); void request<Session>('/auth/session').catch(() => {});};
  const names = ['job.created', 'job.claimed', 'job.status_changed', 'job.step', 'snapshot.required'];
  names.forEach(name => source.addEventListener(name, () => onEvent(name)));
  source.addEventListener('session.expired', () => { source.close(); expired(); });
  // Native EventSource reconnects with Last-Event-ID. No credentials in URLs.
  return () => source.close();
}
export function pretty(value: unknown) {
  if (typeof value === 'string') { try { return JSON.stringify(JSON.parse(value), null, 2); } catch { return value; } }
  return JSON.stringify(value, null, 2);
}
