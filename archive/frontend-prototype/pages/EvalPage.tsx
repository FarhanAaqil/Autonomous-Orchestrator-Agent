/**
 * frontend/src/pages/EvalPage.tsx
 * Router accuracy evaluation dashboard, confusion matrix heatmap, workflow success rate, and daily cost.
 */

import React, { useEffect, useState } from 'react';
import { api } from '../api/client';
import { EvalResult, EvalSummary, JobRecord } from '../types/api';
import { ConfusionMatrixHeatmap } from '../components/ConfusionMatrixHeatmap';
import { AgentPrecisionRecallTable } from '../components/AgentPrecisionRecallTable';
import { EvalTrendChart } from '../components/EvalTrendChart';
import { BarChart3, RefreshCw, AlertTriangle, CheckCircle2, TrendingUp, Coins, CheckCircle, Activity } from 'lucide-react';

export const EvalPage: React.FC = () => {
  const [evalData, setEvalData] = useState<EvalResult | null>(null);
  const [history, setHistory] = useState<EvalSummary[]>([]);
  const [jobs, setJobs] = useState<JobRecord[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isTriggering, setIsTriggering] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchEval = async () => {
    setIsLoading(true);
    try {
      const [latest, hist, jobsRes] = await Promise.all([
        api.getLatestEval().catch(() => null),
        api.getEvalHistory().catch(() => ({ runs: [], total: 0 })),
        api.getJobs({ limit: 100 }).catch(() => ({ items: [], total: 0, limit: 100, offset: 0 })),
      ]);
      if (latest && 'metrics' in latest) {
        setEvalData(latest);
      }
      if (hist && hist.runs) {
        setHistory(hist.runs);
      }
      if (jobsRes && jobsRes.items) {
        setJobs(jobsRes.items);
      }
      setError(null);
    } catch (err: any) {
      setError(err.message || 'Failed to load evaluation metrics.');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchEval();
  }, []);

  const handleTriggerEval = async () => {
    setIsTriggering(true);
    try {
      await api.triggerEval();
      await fetchEval();
    } catch (err: any) {
      setError(err.message || 'Failed to execute eval run.');
    } finally {
      setIsTriggering(false);
    }
  };

  // Compute workflow success rate & total daily cost from jobs
  const completedJobs = jobs.filter((j) => ['succeeded', 'failed'].includes(j.status));
  const succeededJobs = jobs.filter((j) => j.status === 'succeeded');
  const workflowSuccessRate = completedJobs.length > 0
    ? (succeededJobs.length / completedJobs.length) * 100
    : 100.0;
  const totalCostUsd = jobs.reduce((acc, j) => acc + (Number(j.cost_usd) || 0), 0);

  return (
    <div className="space-y-6 max-w-5xl mx-auto">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-2xl font-black text-text-primary flex items-center gap-2.5">
            <BarChart3 className="w-6 h-6 text-accent-primary" />
            Router Accuracy &amp; System Performance Telemetry
          </h2>
          <p className="text-sm text-text-muted mt-1">
            Empirical benchmark metrics against 27 ground-truth commands, workflow completion rate, and aggregate inference costs.
          </p>
        </div>

        <button
          onClick={handleTriggerEval}
          disabled={isTriggering}
          className="px-5 py-2.5 bg-accent-primary hover:brightness-105 text-text-onLight font-bold text-xs rounded-pill flex items-center gap-2 transition-all shadow-md active:scale-95 disabled:opacity-50 self-start sm:self-auto"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${isTriggering ? 'animate-spin' : ''}`} />
          <span>{isTriggering ? 'Running Benchmark...' : 'Run Benchmark Now'}</span>
        </button>
      </div>

      {error && (
        <div className="bg-state-danger/20 border border-state-danger/40 text-[#EEE9DF] rounded-2xl p-4 text-xs">
          {error}
        </div>
      )}

      {evalData && (
        <>
          {/* Staleness Warning Banner */}
          {evalData.stale && (
            <div className="bg-state-warning/20 border border-state-warning text-[#EEE9DF] rounded-2xl p-4 flex items-center gap-3 text-xs">
              <AlertTriangle className="w-5 h-5 text-accent-primary flex-shrink-0" />
              <div>
                <strong className="text-accent-primary">Prompt Drift Detected:</strong> The system prompt has been modified since the last eval run. Click &quot;Run Benchmark Now&quot; to re-evaluate current router accuracy.
              </div>
            </div>
          )}

          {/* Headline Stats Cards: Accuracy, Success Rate, Daily Cost, Benchmark */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div className="bg-surface-primary rounded-2xl p-5 border border-surface-muted/20 shadow-lg">
              <span className="text-xs font-semibold text-text-muted uppercase tracking-wider">
                Overall Accuracy
              </span>
              <div className="text-3xl font-black text-accent-primary mt-1 tabular-nums font-mono">
                {(evalData.metrics.accuracy * 100).toFixed(1)}%
              </div>
              <span className="text-xs text-text-muted mt-1 block">
                {evalData.metrics.correct} / {evalData.metrics.total} commands correct
              </span>
            </div>

            <div className="bg-surface-primary rounded-2xl p-5 border border-surface-muted/20 shadow-lg">
              <span className="text-xs font-semibold text-text-muted uppercase tracking-wider">
                Workflow Success
              </span>
              <div className="text-3xl font-black text-emerald-400 mt-1 tabular-nums font-mono">
                {workflowSuccessRate.toFixed(1)}%
              </div>
              <span className="text-xs text-text-muted mt-1 block">
                {succeededJobs.length} / {completedJobs.length || 1} completed jobs
              </span>
            </div>

            <div className="bg-surface-primary rounded-2xl p-5 border border-surface-muted/20 shadow-lg">
              <span className="text-xs font-semibold text-text-muted uppercase tracking-wider">
                Daily Token Cost
              </span>
              <div className="text-3xl font-black text-accent-primary mt-1 tabular-nums font-mono">
                ${totalCostUsd.toFixed(4)}
              </div>
              <span className="text-xs text-text-muted mt-1 block">
                Aggregated inference spend
              </span>
            </div>

            <div className="bg-surface-primary rounded-2xl p-5 border border-surface-muted/20 shadow-lg">
              <span className="text-xs font-semibold text-text-muted uppercase tracking-wider">
                Benchmark Suite
              </span>
              <div className="text-xl font-bold text-text-primary mt-2 font-mono">
                fixed_set.json
              </div>
              <span className="text-xs text-text-muted mt-1 block">
                27 curated commands
              </span>
            </div>
          </div>

          {/* Inset Heatmap Panel */}
          <ConfusionMatrixHeatmap matrix={evalData.metrics.confusion_matrix} />

          {/* Inset Tabular Precision/Recall Panel */}
          <AgentPrecisionRecallTable perAgent={evalData.metrics.per_agent} />

          {/* Historical Trend Chart */}
          <EvalTrendChart runs={history} />
        </>
      )}

      {isLoading && !evalData && (
        <div className="flex justify-center p-12 text-text-muted">
          <RefreshCw className="w-8 h-8 animate-spin text-accent-primary" />
        </div>
      )}
    </div>
  );
};
