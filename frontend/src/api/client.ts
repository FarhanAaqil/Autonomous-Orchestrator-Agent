/**
 * frontend/src/api/client.ts
 * Typed HTTP & SSE client wrapping Orchestrator v2 endpoints with auto-reconnect.
 */

import {
  AgentInfo,
  AgentResult,
  ApprovalRecord,
  ClarificationNeeded,
  EvalResult,
  EvalSummary,
  JobRecord,
  JobStepRecord,
  MemoryItemResponse,
  PipelineRunStatus,
  RouterResult,
  ScheduleRecord,
  SystemFlagRecord,
} from '../types/api';

const API_BASE = import.meta.env?.VITE_API_BASE_URL || '';

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const url = `${API_BASE}${path}`;
  const headers = new Headers(options.headers || {});

  if (!headers.has('Content-Type') && options.body && typeof options.body === 'string') {
    headers.set('Content-Type', 'application/json');
  }

  const response = await fetch(url, { ...options, headers });

  if (response.status === 422) {
    const data = await response.json();
    throw { isClarification: true, ...data };
  }

  if (!response.ok) {
    let errDetail = response.statusText;
    try {
      const errJson = await response.json();
      errDetail = errJson.detail || errJson.error || JSON.stringify(errJson);
    } catch {}
    throw new Error(`API Error (${response.status}): ${errDetail}`);
  }

  return response.json();
}

export type ConnectionStatus = 'connected' | 'reconnecting' | 'offline';

export interface SSEOptions {
  onEvent: (event: string, data: any) => void;
  onStatusChange?: (status: ConnectionStatus) => void;
  url?: string;
}

/**
 * Resilient SSE subscriber supporting exponential backoff reconnects and Last-Event-ID tracking.
 */
export function subscribeJobEvents({
  onEvent,
  onStatusChange,
  url = '/jobs/events',
}: SSEOptions): () => void {
  let isClosed = false;
  let lastEventId: string | null = null;
  let retryDelay = 1000;
  let activeEventSource: EventSource | null = null;
  let reconnectTimer: any = null;

  function connect() {
    if (isClosed) return;

    onStatusChange?.('reconnecting');
    const fullUrl = `${API_BASE}${url}${lastEventId ? `?last_event_id=${encodeURIComponent(lastEventId)}` : ''}`;

    try {
      activeEventSource = new EventSource(fullUrl);

      activeEventSource.onopen = () => {
        retryDelay = 1000;
        onStatusChange?.('connected');
      };

      activeEventSource.onmessage = (e) => {
        if (e.lastEventId) {
          lastEventId = e.lastEventId;
        }
        try {
          const parsed = JSON.parse(e.data);
          onEvent(parsed.event || 'message', parsed.data || parsed);
        } catch {
          onEvent('raw', e.data);
        }
      };

      // Listen for custom event names
      const knownEvents = ['job.created', 'job.updated', 'job.step', 'job.completed', 'agent.status'];
      for (const evName of knownEvents) {
        activeEventSource.addEventListener(evName, (e: any) => {
          if (e.lastEventId) {
            lastEventId = e.lastEventId;
          }
          try {
            const parsed = JSON.parse(e.data);
            onEvent(evName, parsed.data || parsed);
          } catch {
            onEvent(evName, e.data);
          }
        });
      }

      activeEventSource.onerror = () => {
        if (activeEventSource) {
          activeEventSource.close();
          activeEventSource = null;
        }
        onStatusChange?.('offline');
        if (!isClosed) {
          reconnectTimer = setTimeout(() => {
            retryDelay = Math.min(retryDelay * 1.5, 15000);
            connect();
          }, retryDelay);
        }
      };
    } catch {
      onStatusChange?.('offline');
      if (!isClosed) {
        reconnectTimer = setTimeout(connect, retryDelay);
      }
    }
  }

  connect();

  return () => {
    isClosed = true;
    if (reconnectTimer) clearTimeout(reconnectTimer);
    if (activeEventSource) {
      activeEventSource.close();
      activeEventSource = null;
    }
    onStatusChange?.('offline');
  };
}

export const api = {
  // ── Dispatch & Route ──
  route: (command: string) =>
    request<RouterResult>('/route', {
      method: 'POST',
      body: JSON.stringify({ command }),
    }),

  dispatch: (command: string, context: Record<string, any> = {}) =>
    request<AgentResult>('/dispatch', {
      method: 'POST',
      body: JSON.stringify({ command, context }),
    }),

  // ── Autonomous Jobs (Phase 5 & 8) ──
  getJobs: (params: { status?: string; agent?: string; limit?: number; offset?: number } = {}) => {
    const q = new URLSearchParams();
    if (params.status) q.set('status', params.status);
    if (params.agent) q.set('agent', params.agent);
    if (params.limit) q.set('limit', String(params.limit));
    if (params.offset) q.set('offset', String(params.offset));
    const qs = q.toString() ? `?${q.toString()}` : '';
    return request<{ items: JobRecord[]; total: number; limit: number; offset: number }>(`/jobs${qs}`);
  },

  getJob: (id: string) => request<JobRecord>(`/jobs/${id}`),

  getJobSteps: (id: string) => request<JobStepRecord[]>(`/jobs/${id}/steps`),

  createJob: (body: { agent: string; goal: string; params?: Record<string, any>; priority?: number }) =>
    request<JobRecord>('/jobs', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  cancelJob: (id: string) =>
    request<{ status: string; id: string }>(`/jobs/${id}/cancel`, {
      method: 'POST',
    }),

  answerJob: (id: string, answer: string) =>
    request<{ status: string; id: string }>(`/jobs/${id}/answer`, {
      method: 'POST',
      body: JSON.stringify({ answer }),
    }),

  // ── Schedules (Phase 8) ──
  getSchedules: () => request<ScheduleRecord[]>('/schedules'),

  createSchedule: (body: { name: string; agent: string; goal: string; cron_expr: string; is_active?: boolean }) =>
    request<ScheduleRecord>('/schedules', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  updateSchedule: (id: string, body: Partial<{ name: string; agent: string; goal: string; cron_expr: string; is_active: boolean }>) =>
    request<ScheduleRecord>(`/schedules/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    }),

  deleteSchedule: (id: string) =>
    request<{ deleted: boolean; id: string }>(`/schedules/${id}`, {
      method: 'DELETE',
    }),

  runSchedule: (id: string) =>
    request<{ status: string; schedule_id: string; job_id: string; agent: string; goal: string }>(`/schedules/${id}/run`, {
      method: 'POST',
    }),

  // ── Memory (Phase 7 & 8) ──
  getMemories: (params: { kind?: string; pending_review?: boolean; limit?: number } = {}) => {
    const q = new URLSearchParams();
    if (params.kind) q.set('kind', params.kind);
    if (params.pending_review !== undefined) q.set('pending_review', String(params.pending_review));
    if (params.limit) q.set('limit', String(params.limit));
    const qs = q.toString() ? `?${q.toString()}` : '';
    return request<MemoryItemResponse[]>(`/memory${qs}`);
  },

  createMemory: (body: { kind: string; value: string; key?: string; pending_review?: boolean }) =>
    request<MemoryItemResponse>('/memory', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  updateMemory: (id: string, body: { value?: string; key?: string; pending_review?: boolean }) =>
    request<MemoryItemResponse>(`/memory/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    }),

  confirmMemory: (id: string) =>
    request<MemoryItemResponse>(`/memory/${id}/confirm`, {
      method: 'POST',
    }),

  deleteMemory: (id: string) =>
    request<{ deleted: boolean; id: string }>(`/memory/${id}`, {
      method: 'DELETE',
    }),

  summarizeSession: (sessionId: string) =>
    request<MemoryItemResponse>(`/memory/summarize/${sessionId}`, {
      method: 'POST',
    }),

  // ── Agent Roster & Controls (Phase 6) ──
  getAgents: () => request<AgentInfo[]>('/agents'),

  updateAgent: (id: string, isActive: boolean) =>
    request<AgentInfo>(`/agents/${id}`, {
      method: 'PATCH',
      body: JSON.stringify({ is_active: isActive }),
    }),

  // ── System Guardrails & Settings ──
  getSystemFlags: () => request<SystemFlagRecord[]>('/system/flags'),

  toggleKillSwitch: (on: boolean) =>
    request<{ kill_switch: string; updated_at: string }>('/system/kill-switch', {
      method: 'POST',
      body: JSON.stringify({ on }),
    }),

  setDailyBudget: (budget: number) =>
    request<{ daily_budget_usd: number; updated_at: string }>('/system/budget', {
      method: 'POST',
      body: JSON.stringify({ daily_budget_usd: budget }),
    }),

  // ── Pipelines ──
  startPipeline: (pipelineName: string, command: string) =>
    request<{ run_id: string; pipeline_name: string; status: string }>(`/pipeline/${pipelineName}`, {
      method: 'POST',
      body: JSON.stringify({ command }),
    }),

  getRun: (runId: string) => request<PipelineRunStatus>(`/runs/${runId}`),

  // ── Approvals ──
  getApprovals: (status?: string) => {
    const q = status ? `?status=${encodeURIComponent(status)}` : '';
    return request<{ items: ApprovalRecord[]; total: number }>(`/approvals${q}`);
  },

  approve: (approvalId: string, expectedHash?: string) =>
    request<{ id: string; status: string }>(`/approvals/${approvalId}/approve`, {
      method: 'POST',
      body: expectedHash ? JSON.stringify({ expected_hash: expectedHash }) : undefined,
    }),

  reject: (approvalId: string) =>
    request<{ id: string; status: string }>(`/approvals/${approvalId}/reject`, {
      method: 'POST',
    }),

  execute: (approvalId: string) =>
    request<{ id: string; status: string }>(`/approvals/${approvalId}/execute`, {
      method: 'POST',
    }),

  // ── Router Eval ──
  getLatestEval: () => request<EvalResult>('/router/eval'),

  getEvalHistory: () =>
    request<{ runs: EvalSummary[]; total: number }>('/router/evals'),

  triggerEval: () =>
    request<{ eval_id: string; status: string; accuracy?: number }>('/router/eval', {
      method: 'POST',
    }),
};
