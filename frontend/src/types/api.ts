/**
 * frontend/src/types/api.ts
 * Type definitions matching Orchestrator v2 backend models.
 */

export interface RouterResult {
  agent: string;
  confidence: number;
  reasoning: string;
}

export interface ClarificationNeeded {
  candidates: string[];
  reasoning: string;
}

export interface AgentResult {
  agent: string;
  output: string;
  action_type?: string | null;
  metadata: Record<string, any>;
}

export interface ApprovalRecord {
  id: string;
  action_type: string;
  payload_json: string;
  status: 'pending' | 'approved' | 'rejected' | 'executing' | 'executed' | 'expired' | 'superseded';
  created_at: string;
  expires_at?: string | null;
  executed_at?: string | null;
  target?: string | null;
  payload_hash?: string | null;
}

export interface PipelineStepRecord {
  run_id: string;
  step_number: number;
  agent_name: string;
  input_json: string;
  output_json: string;
  latency_ms: number;
  success: boolean;
  timestamp: string;
  error?: string | null;
}

export interface PipelineRunStatus {
  run_id: string;
  pipeline_name: string;
  status: 'running' | 'completed' | 'failed';
  steps: PipelineStepRecord[];
  started_at: string;
  completed_at?: string | null;
  error?: string | null;
}

export interface EvalPerAgentMetrics {
  tp: number;
  fp: number;
  fn: number;
  precision: number;
  recall: number;
  f1: number;
}

export interface EvalMetrics {
  accuracy: number;
  correct: number;
  total: number;
  per_agent: Record<string, EvalPerAgentMetrics>;
  confusion_matrix: Record<string, Record<string, number>>;
}

export interface EvalResult {
  run_at: string;
  dataset: string;
  prompt_hash: string;
  metrics: EvalMetrics;
  results: Array<{
    id: number;
    command: string;
    expected: string;
    predicted: string | null;
    confidence: number;
    correct: boolean;
    clarification: boolean;
    ambiguous?: boolean;
  }>;
  stale?: boolean;
}

export interface EvalSummary {
  run_at: string;
  accuracy: number;
  correct: number;
  total: number;
  prompt_hash: string;
  stale: boolean;
  results_file?: string | null;
}

// ── Phase 8: Autonomous Jobs, Steps, Roster, Memory, Schedules & System Types ──

export interface JobRecord {
  id: string;
  thread_id: string;
  parent_job_id?: string | null;
  session_id?: string | null;
  schedule_id?: string | null;
  agent: string;
  goal: string;
  params?: Record<string, any>;
  status: 'queued' | 'running' | 'awaiting_approval' | 'awaiting_input' | 'succeeded' | 'failed' | 'cancelled' | 'expired';
  priority: number;
  attempts: number;
  max_attempts: number;
  not_before?: string | null;
  claimed_by?: string | null;
  claimed_at?: string | null;
  heartbeat_at?: string | null;
  step_count: number;
  max_steps: number;
  token_budget: number;
  tokens_used: number;
  cost_usd: number;
  result_json?: string | null;
  error?: string | null;
  created_at: string;
  started_at?: string | null;
  finished_at?: string | null;
}

export interface JobStepRecord {
  id: string;
  job_id: string;
  idx: number;
  kind: 'llm' | 'tool' | 'propose' | 'note' | 'error';
  name?: string | null;
  input_json?: string | null;
  output_json?: string | null;
  tokens_in?: number | null;
  tokens_out?: number | null;
  cost_usd?: number | null;
  duration_ms?: number | null;
  ok: boolean;
  created_at: string;
}

export interface AgentInfo {
  id: string;
  name: string;
  description: string;
  icon: string;
  free_capabilities: string[];
  gated_capabilities: string[];
  is_active: boolean;
  status: 'healthy' | 'degraded' | 'disabled';
  allowed_tools: string[];
  circuit_breakers: Record<string, string>;
}

export interface MemoryItemResponse {
  id: string;
  kind: 'fact' | 'preference' | 'episode_summary';
  key?: string | null;
  value: string;
  source_session_id?: string | null;
  source_message_id?: string | null;
  pending_review: boolean;
  created_at: string;
  updated_at: string;
  deleted: boolean;
}

export interface ScheduleRecord {
  id: string;
  name: string;
  agent: string;
  goal: string;
  cron_expr: string;
  is_active: boolean;
  last_run_at?: string | null;
  next_run_at?: string | null;
  created_at: string;
  updated_at: string;
}

export interface SystemFlagRecord {
  key: string;
  value: string;
  updated_at: string;
}
