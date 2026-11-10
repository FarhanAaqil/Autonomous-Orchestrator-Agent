/**
 * frontend/src/pages/JobsPage.tsx
 * Autonomous Jobs Timeline and execution control plane with step trace inspection.
 */

import React, { useState, useEffect, useCallback } from 'react';
import { api, subscribeJobEvents } from '../api/client';
import { JobRecord, JobStepRecord } from '../types/api';
import {
  Briefcase,
  Play,
  XCircle,
  MessageSquare,
  Clock,
  Coins,
  ChevronDown,
  ChevronRight,
  Filter,
  RefreshCw,
  Plus,
  Terminal,
  Cpu,
  Layers,
} from 'lucide-react';

export const JobsPage: React.FC = () => {
  const [jobs, setJobs] = useState<JobRecord[]>([]);
  const [total, setTotal] = useState(0);
  const [selectedJob, setSelectedJob] = useState<JobRecord | null>(null);
  const [steps, setSteps] = useState<JobStepRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingSteps, setLoadingSteps] = useState(false);
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [expandedSteps, setExpandedSteps] = useState<Set<string>>(new Set());

  // Answer question modal state
  const [answerText, setAnswerText] = useState('');
  const [answering, setAnswering] = useState(false);

  // New Job modal state
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [newAgent, setNewAgent] = useState('research_agent');
  const [newGoal, setNewGoal] = useState('');
  const [newPriority, setNewPriority] = useState(0);
  const [creating, setCreating] = useState(false);

  const fetchJobs = useCallback(async () => {
    try {
      const params: any = { limit: 50 };
      if (statusFilter !== 'all') params.status = statusFilter;
      const res = await api.getJobs(params);
      setJobs(res.items || []);
      setTotal(res.total || 0);
      if (selectedJob) {
        const updated = (res.items || []).find((j) => j.id === selectedJob.id);
        if (updated) setSelectedJob(updated);
      }
    } catch (err) {
      console.error('Failed to load jobs:', err);
    } finally {
      setLoading(false);
    }
  }, [statusFilter, selectedJob?.id]);

  useEffect(() => {
    fetchJobs();
  }, [fetchJobs]);

  // Live SSE listener for real-time updates
  useEffect(() => {
    const unsub = subscribeJobEvents({
      onEvent: (event, data) => {
        if (event.startsWith('job.')) {
          fetchJobs();
          if (selectedJob && (data.job_id === selectedJob.id || data.id === selectedJob.id)) {
            fetchSteps(selectedJob.id);
          }
        }
      },
    });
    return () => unsub();
  }, [selectedJob?.id, fetchJobs]);

  const fetchSteps = async (jobId: string) => {
    setLoadingSteps(true);
    try {
      const data = await api.getJobSteps(jobId);
      setSteps(data || []);
    } catch (err) {
      console.error('Failed to load job steps:', err);
    } finally {
      setLoadingSteps(false);
    }
  };

  const handleSelectJob = (job: JobRecord) => {
    setSelectedJob(job);
    fetchSteps(job.id);
    setExpandedSteps(new Set());
  };

  const handleCancelJob = async (jobId: string) => {
    if (!confirm('Are you sure you want to cancel this job?')) return;
    try {
      await api.cancelJob(jobId);
      fetchJobs();
    } catch (err: any) {
      alert(`Cancel failed: ${err.message}`);
    }
  };

  const handleAnswerJob = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedJob || !answerText.trim()) return;
    setAnswering(true);
    try {
      await api.answerJob(selectedJob.id, answerText);
      setAnswerText('');
      fetchJobs();
      fetchSteps(selectedJob.id);
    } catch (err: any) {
      alert(`Failed to submit answer: ${err.message}`);
    } finally {
      setAnswering(false);
    }
  };

  const handleCreateJob = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newGoal.trim()) return;
    setCreating(true);
    try {
      const created = await api.createJob({
        agent: newAgent,
        goal: newGoal,
        priority: Number(newPriority),
      });
      setIsCreateOpen(false);
      setNewGoal('');
      fetchJobs();
      handleSelectJob(created);
    } catch (err: any) {
      alert(`Failed to create job: ${err.message}`);
    } finally {
      setCreating(false);
    }
  };

  const toggleStepExpand = (stepId: string) => {
    setExpandedSteps((prev) => {
      const next = new Set(prev);
      if (next.has(stepId)) next.delete(stepId);
      else next.add(stepId);
      return next;
    });
  };

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'queued':
        return <span className="px-2 py-0.5 rounded-full text-xs font-mono font-bold bg-slate-700 text-slate-300">QUEUED</span>;
      case 'running':
        return <span className="px-2 py-0.5 rounded-full text-xs font-mono font-bold bg-amber-500/20 text-amber-300 border border-amber-500/30 animate-pulse">RUNNING</span>;
      case 'awaiting_input':
        return <span className="px-2 py-0.5 rounded-full text-xs font-mono font-bold bg-blue-500/20 text-blue-300 border border-blue-500/30">AWAITING INPUT</span>;
      case 'succeeded':
        return <span className="px-2 py-0.5 rounded-full text-xs font-mono font-bold bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">SUCCEEDED</span>;
      case 'failed':
        return <span className="px-2 py-0.5 rounded-full text-xs font-mono font-bold bg-rose-500/20 text-rose-300 border border-rose-500/30">FAILED</span>;
      case 'cancelled':
        return <span className="px-2 py-0.5 rounded-full text-xs font-mono font-bold bg-slate-800 text-slate-400">CANCELLED</span>;
      default:
        return <span className="px-2 py-0.5 rounded-full text-xs font-mono font-bold bg-slate-800 text-slate-300">{status}</span>;
    }
  };

  const getStepKindBadge = (kind: string) => {
    switch (kind) {
      case 'tool_call':
        return <span className="px-1.5 py-0.5 rounded text-[10px] font-mono font-bold bg-indigo-900/40 text-indigo-300 border border-indigo-500/30">TOOL</span>;
      case 'propose':
        return <span className="px-1.5 py-0.5 rounded text-[10px] font-mono font-bold bg-amber-900/40 text-amber-300 border border-amber-500/30">PROPOSE</span>;
      case 'llm_call':
        return <span className="px-1.5 py-0.5 rounded text-[10px] font-mono font-bold bg-purple-900/40 text-purple-300 border border-purple-500/30">LLM</span>;
      case 'ask_user':
        return <span className="px-1.5 py-0.5 rounded text-[10px] font-mono font-bold bg-blue-900/40 text-blue-300 border border-blue-500/30">ASK USER</span>;
      case 'final':
        return <span className="px-1.5 py-0.5 rounded text-[10px] font-mono font-bold bg-emerald-900/40 text-emerald-300 border border-emerald-500/30">FINAL</span>;
      case 'error':
        return <span className="px-1.5 py-0.5 rounded text-[10px] font-mono font-bold bg-rose-900/40 text-rose-300 border border-rose-500/30">ERROR</span>;
      default:
        return <span className="px-1.5 py-0.5 rounded text-[10px] font-mono font-bold bg-slate-800 text-slate-300">{kind}</span>;
    }
  };

  return (
    <div className="space-y-6 max-w-7xl mx-auto">
      {/* Top Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-surface-muted/20 pb-5">
        <div>
          <h2 className="text-2xl font-black text-text-primary flex items-center gap-2.5">
            <Briefcase className="w-6 h-6 text-accent-primary" />
            Autonomous Jobs & Execution Timeline
          </h2>
          <p className="text-sm text-text-muted mt-1">
            Inspect autonomous agent loop execution, step traces, tool observations, token budgets, and human-in-the-loop controls.
          </p>
        </div>

        <div className="flex items-center gap-2.5">
          <button
            onClick={() => fetchJobs()}
            className="px-3 py-2 rounded-xl bg-surface-primary hover:bg-surface-primary/80 border border-surface-muted/20 text-text-primary text-xs font-mono font-bold flex items-center gap-1.5 transition-all"
            title="Refresh jobs"
          >
            <RefreshCw className="w-3.5 h-3.5" />
            <span>Refresh</span>
          </button>
          <button
            onClick={() => setIsCreateOpen(true)}
            className="px-4 py-2 rounded-xl bg-accent-primary hover:brightness-105 text-text-onLight text-xs font-mono font-bold flex items-center gap-1.5 shadow-md transition-all"
          >
            <Plus className="w-4 h-4" />
            <span>New Job</span>
          </button>
        </div>
      </div>

      {/* Main Grid: Jobs List on Left, Selected Job Trace on Right */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Left Column: Job Queue List */}
        <div className="lg:col-span-5 space-y-4">
          {/* Status Filter Tabs */}
          <div className="flex items-center gap-1 bg-surface-primary p-1 rounded-xl border border-surface-muted/20 overflow-x-auto text-xs font-mono">
            {['all', 'running', 'awaiting_input', 'queued', 'succeeded', 'failed'].map((st) => (
              <button
                key={st}
                onClick={() => setStatusFilter(st)}
                className={`px-2.5 py-1.5 rounded-lg transition-all capitalize whitespace-nowrap ${
                  statusFilter === st
                    ? 'bg-accent-primary text-text-onLight font-bold'
                    : 'text-text-muted hover:text-text-primary'
                }`}
              >
                {st.replace('_', ' ')}
              </button>
            ))}
          </div>

          {/* Job Cards */}
          <div className="space-y-2.5">
            {loading ? (
              <div className="p-8 text-center text-xs font-mono text-text-muted bg-surface-primary rounded-2xl border border-surface-muted/20">
                Loading jobs queue...
              </div>
            ) : jobs.length === 0 ? (
              <div className="p-8 text-center text-xs font-mono text-text-muted bg-surface-primary rounded-2xl border border-surface-muted/20">
                No jobs found in this status.
              </div>
            ) : (
              jobs.map((job) => {
                const isSelected = selectedJob?.id === job.id;
                return (
                  <div
                    key={job.id}
                    onClick={() => handleSelectJob(job)}
                    className={`p-4 rounded-2xl cursor-pointer transition-all border ${
                      isSelected
                        ? 'bg-surface-primary border-accent-primary shadow-lg ring-1 ring-accent-primary/50'
                        : 'bg-surface-primary/70 hover:bg-surface-primary border-surface-muted/20'
                    }`}
                  >
                    <div className="flex items-center justify-between mb-2">
                      <div className="flex items-center gap-2">
                        <Cpu className="w-4 h-4 text-accent-primary" />
                        <span className="font-mono text-xs font-bold text-text-primary">{job.agent}</span>
                      </div>
                      {getStatusBadge(job.status)}
                    </div>

                    <p className="text-sm text-text-primary font-medium line-clamp-2 mb-3">
                      {job.goal}
                    </p>

                    <div className="flex items-center justify-between text-[11px] font-mono text-text-muted pt-2 border-t border-surface-muted/10">
                      <span className="truncate">#{job.id.slice(0, 8)}</span>
                      <div className="flex items-center gap-3">
                        <span className="flex items-center gap-1">
                          <Layers className="w-3 h-3 text-text-muted" />
                          {job.steps_count || 0} steps
                        </span>
                        <span className="flex items-center gap-1">
                          <Coins className="w-3 h-3 text-text-muted" />
                          ${Number(job.cost_usd || 0).toFixed(4)}
                        </span>
                      </div>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>

        {/* Right Column: Detailed Job Timeline & Controls */}
        <div className="lg:col-span-7">
          {selectedJob ? (
            <div className="bg-surface-primary rounded-2xl border border-surface-muted/20 p-6 space-y-6 shadow-xl">
              {/* Job Summary Banner */}
              <div className="border-b border-surface-muted/20 pb-5 space-y-3">
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-xs font-mono text-accent-primary font-bold">
                        Job #{selectedJob.id}
                      </span>
                      {getStatusBadge(selectedJob.status)}
                    </div>
                    <h3 className="text-lg font-bold text-text-primary leading-snug">
                      {selectedJob.goal}
                    </h3>
                  </div>

                  {/* Actions */}
                  {['queued', 'running', 'awaiting_input'].includes(selectedJob.status) && (
                    <button
                      onClick={() => handleCancelJob(selectedJob.id)}
                      className="px-3 py-1.5 rounded-xl bg-rose-500/20 hover:bg-rose-500/30 text-rose-300 border border-rose-500/40 text-xs font-mono font-bold flex items-center gap-1.5 transition-all"
                    >
                      <XCircle className="w-3.5 h-3.5" />
                      <span>Cancel</span>
                    </button>
                  )}
                </div>

                {/* Telemetry Stats Bar */}
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 pt-2 text-xs font-mono">
                  <div className="p-2.5 rounded-xl bg-canvas-dark/60 border border-surface-muted/10">
                    <span className="text-[10px] text-text-muted uppercase block">Agent</span>
                    <span className="font-bold text-text-primary truncate block">{selectedJob.agent}</span>
                  </div>
                  <div className="p-2.5 rounded-xl bg-canvas-dark/60 border border-surface-muted/10">
                    <span className="text-[10px] text-text-muted uppercase block">Tokens</span>
                    <span className="font-bold text-text-primary block">{selectedJob.tokens_used || 0}</span>
                  </div>
                  <div className="p-2.5 rounded-xl bg-canvas-dark/60 border border-surface-muted/10">
                    <span className="text-[10px] text-text-muted uppercase block">Cost USD</span>
                    <span className="font-bold text-accent-primary block">${Number(selectedJob.cost_usd || 0).toFixed(4)}</span>
                  </div>
                  <div className="p-2.5 rounded-xl bg-canvas-dark/60 border border-surface-muted/10">
                    <span className="text-[10px] text-text-muted uppercase block">Created</span>
                    <span className="font-bold text-text-muted truncate block">
                      {new Date(selectedJob.created_at).toLocaleTimeString()}
                    </span>
                  </div>
                </div>

                {/* Awaiting Input Prompt & Reply Box */}
                {selectedJob.status === 'awaiting_input' && (
                  <form onSubmit={handleAnswerJob} className="mt-4 p-4 rounded-xl bg-blue-950/30 border border-blue-500/40 space-y-3">
                    <div className="flex items-center gap-2 text-blue-300 text-xs font-bold font-mono">
                      <MessageSquare className="w-4 h-4" />
                      <span>Agent is asking for human clarification:</span>
                    </div>
                    {selectedJob.pending_question && (
                      <div className="text-sm text-text-primary bg-canvas-dark/80 p-3 rounded-lg border border-blue-500/20 font-mono">
                        {selectedJob.pending_question}
                      </div>
                    )}
                    <div className="flex gap-2">
                      <input
                        type="text"
                        value={answerText}
                        onChange={(e) => setAnswerText(e.target.value)}
                        placeholder="Type answer or directive to continue execution..."
                        className="flex-1 bg-canvas-dark px-3 py-2 rounded-xl border border-surface-muted/30 text-xs text-text-primary focus:outline-none focus:border-accent-primary"
                        required
                      />
                      <button
                        type="submit"
                        disabled={answering}
                        className="px-4 py-2 rounded-xl bg-accent-primary hover:brightness-105 text-text-onLight text-xs font-mono font-bold transition-all disabled:opacity-50"
                      >
                        {answering ? 'Submitting...' : 'Send Directive'}
                      </button>
                    </div>
                  </form>
                )}
              </div>

              {/* Step Timeline */}
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <h4 className="text-xs font-extrabold uppercase font-mono tracking-wider text-text-primary flex items-center gap-2">
                    <Terminal className="w-4 h-4 text-accent-primary" />
                    Step Trace & Tool Execution Timeline ({steps.length})
                  </h4>
                  <button
                    onClick={() => fetchSteps(selectedJob.id)}
                    className="text-xs text-text-muted hover:text-text-primary font-mono"
                  >
                    Refresh steps ↻
                  </button>
                </div>

                {loadingSteps ? (
                  <div className="p-8 text-center text-xs font-mono text-text-muted">
                    Loading execution steps...
                  </div>
                ) : steps.length === 0 ? (
                  <div className="p-6 text-center text-xs font-mono text-text-muted bg-canvas-dark/40 rounded-xl border border-surface-muted/10">
                    No steps recorded yet. Job may be in queue or initializing.
                  </div>
                ) : (
                  <div className="space-y-3">
                    {steps.map((st) => {
                      const isExpanded = expandedSteps.has(st.id);
                      return (
                        <div
                          key={st.id}
                          className="rounded-xl bg-canvas-dark/60 border border-surface-muted/20 overflow-hidden text-xs transition-all"
                        >
                          <div
                            onClick={() => toggleStepExpand(st.id)}
                            className="p-3 flex items-center justify-between cursor-pointer hover:bg-canvas-dark/90 transition-colors"
                          >
                            <div className="flex items-center gap-2.5">
                              <span className="w-6 h-6 rounded-lg bg-surface-primary flex items-center justify-center font-mono font-bold text-accent-primary text-[11px]">
                                {st.step_number}
                              </span>
                              {getStepKindBadge(st.step_kind)}
                              <span className="font-mono font-bold text-text-primary">
                                {st.action_name || st.step_kind}
                              </span>
                            </div>

                            <div className="flex items-center gap-3 font-mono text-[11px] text-text-muted">
                              {st.latency_ms !== undefined && (
                                <span>{st.latency_ms}ms</span>
                              )}
                              {st.tokens_used !== undefined && (
                                <span>{st.tokens_used} tok</span>
                              )}
                              {isExpanded ? (
                                <ChevronDown className="w-4 h-4 text-text-muted" />
                              ) : (
                                <ChevronRight className="w-4 h-4 text-text-muted" />
                              )}
                            </div>
                          </div>

                          {/* Expanded Step Inspection */}
                          {isExpanded && (
                            <div className="p-3 border-t border-surface-muted/15 space-y-3 bg-canvas-dark/90 font-mono text-[11px]">
                              {st.thought && (
                                <div>
                                  <span className="text-[10px] text-text-muted uppercase block mb-1">Agent Thought / Rational</span>
                                  <p className="text-text-primary whitespace-pre-wrap bg-surface-primary/40 p-2.5 rounded-lg border border-surface-muted/10 font-sans text-xs">
                                    {st.thought}
                                  </p>
                                </div>
                              )}

                              {st.input_data && Object.keys(st.input_data).length > 0 && (
                                <div>
                                  <span className="text-[10px] text-text-muted uppercase block mb-1">Step Input</span>
                                  <pre className="p-2.5 rounded-lg bg-black/40 text-text-primary overflow-x-auto border border-surface-muted/10 text-[10px]">
                                    {JSON.stringify(st.input_data, null, 2)}
                                  </pre>
                                </div>
                              )}

                              {st.output_data && (
                                <div>
                                  <span className="text-[10px] text-text-muted uppercase block mb-1">Observation / Result</span>
                                  <pre className="p-2.5 rounded-lg bg-black/40 text-emerald-300 overflow-x-auto border border-surface-muted/10 text-[10px]">
                                    {typeof st.output_data === 'string'
                                      ? st.output_data
                                      : JSON.stringify(st.output_data, null, 2)}
                                  </pre>
                                </div>
                              )}

                              {st.error && (
                                <div className="p-2.5 rounded-lg bg-rose-950/40 border border-rose-500/30 text-rose-300">
                                  <span className="text-[10px] font-bold block mb-1">Step Error</span>
                                  <span>{st.error}</span>
                                </div>
                              )}
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            </div>
          ) : (
            <div className="h-full min-h-[400px] flex flex-col items-center justify-center p-8 text-center bg-surface-primary rounded-2xl border border-surface-muted/20 text-text-muted">
              <Briefcase className="w-12 h-12 mb-3 opacity-30 text-accent-primary" />
              <h4 className="font-bold text-sm text-text-primary">No Job Selected</h4>
              <p className="text-xs max-w-sm mt-1">
                Select any autonomous job from the queue on the left to inspect its real-time step timeline and observations.
              </p>
            </div>
          )}
        </div>
      </div>

      {/* New Job Modal */}
      {isCreateOpen && (
        <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-surface-primary border border-surface-muted/30 rounded-2xl max-w-lg w-full p-6 shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-surface-muted/20 pb-3">
              <h3 className="font-bold text-base text-text-primary">Dispatch New Autonomous Job</h3>
              <button
                onClick={() => setIsCreateOpen(false)}
                className="text-text-muted hover:text-text-primary"
              >
                ✕
              </button>
            </div>

            <form onSubmit={handleCreateJob} className="space-y-4">
              <div>
                <label className="block text-xs font-mono font-bold text-text-muted uppercase mb-1">
                  Target Agent
                </label>
                <select
                  value={newAgent}
                  onChange={(e) => setNewAgent(e.target.value)}
                  className="w-full bg-canvas-dark border border-surface-muted/30 rounded-xl px-3 py-2 text-xs text-text-primary focus:outline-none focus:border-accent-primary font-mono"
                >
                  <option value="research_agent">Research Agent (Deep Search + arXiv)</option>
                  <option value="career_agent">Career Agent (Resume & Cover Letter)</option>
                  <option value="growth_agent">Growth Agent (Content & Social Strategy)</option>
                  <option value="critic_agent">Critic Agent (Audit & Verification)</option>
                  <option value="github_agent">GitHub Agent (Repos, Issues, PRs)</option>
                  <option value="email_agent">Email Agent (Inbox & Drafts)</option>
                  <option value="linkedin_agent">LinkedIn Agent (Profiles & Posts)</option>
                  <option value="job_agent">Job Search Agent (Scraping & Alerts)</option>
                  <option value="briefing_agent">Daily Briefing Agent (Executive Summary)</option>
                </select>
              </div>

              <div>
                <label className="block text-xs font-mono font-bold text-text-muted uppercase mb-1">
                  Goal / Directive
                </label>
                <textarea
                  rows={4}
                  value={newGoal}
                  onChange={(e) => setNewGoal(e.target.value)}
                  placeholder="Describe the objective for the autonomous worker..."
                  className="w-full bg-canvas-dark border border-surface-muted/30 rounded-xl p-3 text-xs text-text-primary focus:outline-none focus:border-accent-primary"
                  required
                />
              </div>

              <div>
                <label className="block text-xs font-mono font-bold text-text-muted uppercase mb-1">
                  Priority (Default: 0)
                </label>
                <input
                  type="number"
                  value={newPriority}
                  onChange={(e) => setNewPriority(Number(e.target.value))}
                  className="w-full bg-canvas-dark border border-surface-muted/30 rounded-xl px-3 py-2 text-xs text-text-primary focus:outline-none focus:border-accent-primary font-mono"
                />
              </div>

              <div className="flex justify-end gap-2 pt-3 border-t border-surface-muted/20">
                <button
                  type="button"
                  onClick={() => setIsCreateOpen(false)}
                  className="px-4 py-2 rounded-xl bg-canvas-dark hover:bg-canvas-dark/80 text-text-muted text-xs font-mono font-bold"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={creating}
                  className="px-5 py-2 rounded-xl bg-accent-primary hover:brightness-105 text-text-onLight text-xs font-mono font-bold transition-all disabled:opacity-50"
                >
                  {creating ? 'Enqueuing...' : 'Create & Enqueue'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
