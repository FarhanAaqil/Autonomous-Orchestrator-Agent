/**
 * frontend/src/pages/SchedulesPage.tsx
 * Schedules CRUD interface with visual cron builder, immediate trigger execution, and active toggles.
 */

import React, { useState, useEffect } from 'react';
import { api } from '../api/client';
import { ScheduleRecord } from '../types/api';
import {
  Calendar,
  Clock,
  Play,
  Plus,
  Trash2,
  CheckCircle2,
  AlertCircle,
  RefreshCw,
  Cpu,
  Zap,
} from 'lucide-react';

const CRON_PRESETS = [
  { label: 'Every 15 Minutes', expr: '*/15 * * * *', desc: 'Runs at :00, :15, :30, :45' },
  { label: 'Hourly', expr: '0 * * * *', desc: 'Runs at the beginning of every hour' },
  { label: 'Daily at 9:00 AM', expr: '0 9 * * *', desc: 'Runs every day at 09:00 UTC' },
  { label: 'Twice Daily (9 AM & 5 PM)', expr: '0 9,17 * * *', desc: 'Runs at 09:00 and 17:00 UTC' },
  { label: 'Weekly (Monday 9 AM)', expr: '0 9 * * 1', desc: 'Runs every Monday at 09:00 UTC' },
];

export const SchedulesPage: React.FC = () => {
  const [schedules, setSchedules] = useState<ScheduleRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [runningId, setRunningId] = useState<string | null>(null);
  const [notification, setNotification] = useState<{ type: 'success' | 'error'; message: string } | null>(null);

  // Form state
  const [name, setName] = useState('');
  const [agent, setAgent] = useState('briefing_agent');
  const [goal, setGoal] = useState('');
  const [cronExpr, setCronExpr] = useState('0 9 * * *');
  const [isActive, setIsActive] = useState(true);
  const [saving, setSaving] = useState(false);

  const fetchSchedules = async () => {
    try {
      const data = await api.getSchedules();
      setSchedules(data || []);
    } catch (err) {
      console.error('Failed to load schedules:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchSchedules();
  }, []);

  const handleToggleActive = async (sch: ScheduleRecord) => {
    try {
      await api.updateSchedule(sch.id, { is_active: !sch.is_active });
      await fetchSchedules();
    } catch (err: any) {
      alert(`Failed to update schedule status: ${err.message}`);
    }
  };

  const handleRunNow = async (sch: ScheduleRecord) => {
    setRunningId(sch.id);
    try {
      const res = await api.runSchedule(sch.id);
      setNotification({
        type: 'success',
        message: `Triggered job #${res.job_id.slice(0, 8)} for ${sch.name} successfully!`,
      });
      await fetchSchedules();
    } catch (err: any) {
      setNotification({
        type: 'error',
        message: `Execution failed: ${err.message}`,
      });
    } finally {
      setRunningId(null);
    }
  };

  const handleDelete = async (id: string, schName: string) => {
    if (!confirm(`Are you sure you want to delete schedule "${schName}"?`)) return;
    try {
      await api.deleteSchedule(id);
      await fetchSchedules();
      setNotification({
        type: 'success',
        message: `Schedule "${schName}" deleted.`,
      });
    } catch (err: any) {
      alert(`Delete failed: ${err.message}`);
    }
  };

  const handleCreateSchedule = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim() || !goal.trim() || !cronExpr.trim()) return;
    setSaving(true);
    try {
      await api.createSchedule({
        name,
        agent,
        goal,
        cron_expr: cronExpr,
        is_active: isActive,
      });
      setIsModalOpen(false);
      setName('');
      setGoal('');
      setCronExpr('0 9 * * *');
      setIsActive(true);
      await fetchSchedules();
      setNotification({
        type: 'success',
        message: `Created recurring schedule "${name}".`,
      });
    } catch (err: any) {
      alert(`Failed to create schedule: ${err.message}`);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-6 max-w-6xl mx-auto">
      {/* Top Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-surface-muted/20 pb-5">
        <div>
          <h2 className="text-2xl font-black text-text-primary flex items-center gap-2.5">
            <Calendar className="w-6 h-6 text-accent-primary" />
            Recurring Agent Schedules
          </h2>
          <p className="text-sm text-text-muted mt-1">
            Automate recurring autonomous briefings, audits, and pipeline scans on cron cadences.
          </p>
        </div>

        <div className="flex items-center gap-2.5">
          <button
            onClick={fetchSchedules}
            className="px-3 py-2 rounded-xl bg-surface-primary hover:bg-surface-primary/80 border border-surface-muted/20 text-text-primary text-xs font-mono font-bold flex items-center gap-1.5 transition-all"
            title="Refresh list"
          >
            <RefreshCw className="w-3.5 h-3.5" />
            <span>Refresh</span>
          </button>
          <button
            onClick={() => setIsModalOpen(true)}
            className="px-4 py-2 rounded-xl bg-accent-primary hover:brightness-105 text-text-onLight text-xs font-mono font-bold flex items-center gap-1.5 shadow-md transition-all"
          >
            <Plus className="w-4 h-4" />
            <span>New Schedule</span>
          </button>
        </div>
      </div>

      {/* Notification Banner */}
      {notification && (
        <div
          className={`p-4 rounded-xl border flex items-center justify-between text-xs font-mono ${
            notification.type === 'success'
              ? 'bg-emerald-950/40 border-emerald-500/40 text-emerald-300'
              : 'bg-rose-950/40 border-rose-500/40 text-rose-300'
          }`}
        >
          <div className="flex items-center gap-2">
            {notification.type === 'success' ? (
              <CheckCircle2 className="w-4 h-4" />
            ) : (
              <AlertCircle className="w-4 h-4" />
            )}
            <span>{notification.message}</span>
          </div>
          <button
            onClick={() => setNotification(null)}
            className="text-text-muted hover:text-text-primary text-xs"
          >
            ✕
          </button>
        </div>
      )}

      {/* Schedules Cards Grid */}
      {loading ? (
        <div className="p-12 text-center text-xs font-mono text-text-muted bg-surface-primary rounded-2xl border border-surface-muted/20">
          Loading scheduled automation jobs...
        </div>
      ) : schedules.length === 0 ? (
        <div className="p-12 text-center text-xs font-mono text-text-muted bg-surface-primary rounded-2xl border border-surface-muted/20">
          No schedules configured yet. Click "New Schedule" to create one.
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {schedules.map((sch) => (
            <div
              key={sch.id}
              className={`p-5 rounded-2xl border transition-all space-y-4 ${
                sch.is_active
                  ? 'bg-surface-primary border-surface-muted/25 shadow-md'
                  : 'bg-surface-primary/60 border-surface-muted/10 opacity-75'
              }`}
            >
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="flex items-center gap-2 mb-1">
                    <span className="font-bold text-sm text-text-primary">{sch.name}</span>
                    <span
                      className={`px-2 py-0.5 rounded-full text-[10px] font-mono font-bold ${
                        sch.is_active
                          ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
                          : 'bg-slate-700 text-slate-400'
                      }`}
                    >
                      {sch.is_active ? 'ACTIVE' : 'PAUSED'}
                    </span>
                  </div>
                  <div className="flex items-center gap-2 text-xs font-mono text-text-muted">
                    <Cpu className="w-3.5 h-3.5 text-accent-primary" />
                    <span>{sch.agent}</span>
                  </div>
                </div>

                <div className="flex items-center gap-2">
                  <button
                    onClick={() => handleToggleActive(sch)}
                    className={`px-2.5 py-1 rounded-lg text-xs font-mono font-bold transition-all border ${
                      sch.is_active
                        ? 'bg-canvas-dark text-text-muted hover:text-rose-300 border-surface-muted/30'
                        : 'bg-emerald-950/40 text-emerald-300 border-emerald-500/40 hover:bg-emerald-900/50'
                    }`}
                  >
                    {sch.is_active ? 'Pause' : 'Activate'}
                  </button>
                  <button
                    onClick={() => handleDelete(sch.id, sch.name)}
                    className="p-1.5 rounded-lg bg-canvas-dark text-text-muted hover:text-rose-400 border border-surface-muted/30 transition-colors"
                    title="Delete schedule"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>

              {/* Goal Description */}
              <p className="text-xs text-text-primary leading-relaxed bg-canvas-dark/50 p-3 rounded-xl border border-surface-muted/10">
                {sch.goal}
              </p>

              {/* Cron Cadence Pill & Last Run */}
              <div className="flex flex-wrap items-center justify-between gap-2 pt-2 border-t border-surface-muted/10 text-xs font-mono">
                <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-canvas-dark/80 border border-surface-muted/20 text-accent-primary font-bold">
                  <Clock className="w-3.5 h-3.5" />
                  <code>{sch.cron_expr}</code>
                </div>

                <div className="flex items-center gap-3">
                  {sch.last_run_at && (
                    <span className="text-[11px] text-text-muted">
                      Last: {new Date(sch.last_run_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                    </span>
                  )}
                  <button
                    onClick={() => handleRunNow(sch)}
                    disabled={runningId === sch.id}
                    className="px-3 py-1.5 rounded-xl bg-accent-primary hover:brightness-105 text-text-onLight text-xs font-mono font-bold flex items-center gap-1.5 shadow-sm transition-all disabled:opacity-50"
                  >
                    <Play className="w-3 h-3 fill-current" />
                    <span>{runningId === sch.id ? 'Starting...' : 'Run Now'}</span>
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* New Schedule Modal with Cron Builder */}
      {isModalOpen && (
        <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-surface-primary border border-surface-muted/30 rounded-2xl max-w-lg w-full p-6 shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-surface-muted/20 pb-3">
              <h3 className="font-bold text-base text-text-primary">Create Recurring Schedule</h3>
              <button
                onClick={() => setIsModalOpen(false)}
                className="text-text-muted hover:text-text-primary"
              >
                ✕
              </button>
            </div>

            <form onSubmit={handleCreateSchedule} className="space-y-4">
              <div>
                <label className="block text-xs font-mono font-bold text-text-muted uppercase mb-1">
                  Schedule Name
                </label>
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="e.g. Daily Executive Briefing"
                  className="w-full bg-canvas-dark border border-surface-muted/30 rounded-xl px-3 py-2 text-xs text-text-primary focus:outline-none focus:border-accent-primary"
                  required
                />
              </div>

              <div>
                <label className="block text-xs font-mono font-bold text-text-muted uppercase mb-1">
                  Target Agent
                </label>
                <select
                  value={agent}
                  onChange={(e) => setAgent(e.target.value)}
                  className="w-full bg-canvas-dark border border-surface-muted/30 rounded-xl px-3 py-2 text-xs text-text-primary focus:outline-none focus:border-accent-primary font-mono"
                >
                  <option value="briefing_agent">Daily Briefing Agent</option>
                  <option value="research_agent">Research Agent</option>
                  <option value="growth_agent">Growth & Content Agent</option>
                  <option value="critic_agent">Critic Agent</option>
                  <option value="github_agent">GitHub Agent</option>
                  <option value="email_agent">Email Agent</option>
                  <option value="job_agent">Job Search Agent</option>
                </select>
              </div>

              <div>
                <label className="block text-xs font-mono font-bold text-text-muted uppercase mb-1">
                  Execution Goal
                </label>
                <textarea
                  rows={3}
                  value={goal}
                  onChange={(e) => setGoal(e.target.value)}
                  placeholder="Directive executed whenever schedule triggers..."
                  className="w-full bg-canvas-dark border border-surface-muted/30 rounded-xl p-3 text-xs text-text-primary focus:outline-none focus:border-accent-primary"
                  required
                />
              </div>

              {/* Visual Cron Builder */}
              <div className="space-y-2">
                <label className="block text-xs font-mono font-bold text-text-muted uppercase">
                  Cadence Presets
                </label>
                <div className="grid grid-cols-2 gap-2">
                  {CRON_PRESETS.map((p) => (
                    <button
                      key={p.expr}
                      type="button"
                      onClick={() => setCronExpr(p.expr)}
                      className={`p-2.5 rounded-xl border text-left text-xs transition-all ${
                        cronExpr === p.expr
                          ? 'bg-accent-primary/10 border-accent-primary text-accent-primary font-bold'
                          : 'bg-canvas-dark/60 border-surface-muted/20 text-text-muted hover:border-surface-muted/40'
                      }`}
                    >
                      <div className="font-semibold text-text-primary text-[11px]">{p.label}</div>
                      <div className="font-mono text-[10px] text-text-muted mt-0.5">{p.expr}</div>
                    </button>
                  ))}
                </div>

                <div className="pt-2">
                  <label className="block text-[10px] font-mono text-text-muted uppercase mb-1">
                    Custom Cron Expression (min hour dom month dow)
                  </label>
                  <input
                    type="text"
                    value={cronExpr}
                    onChange={(e) => setCronExpr(e.target.value)}
                    placeholder="* * * * *"
                    className="w-full bg-canvas-dark border border-surface-muted/30 rounded-xl px-3 py-2 text-xs font-mono text-accent-primary font-bold focus:outline-none focus:border-accent-primary"
                    required
                  />
                </div>
              </div>

              <div className="flex items-center gap-2 pt-1">
                <input
                  type="checkbox"
                  id="sch-active"
                  checked={isActive}
                  onChange={(e) => setIsActive(e.target.checked)}
                  className="rounded border-surface-muted/30"
                />
                <label htmlFor="sch-active" className="text-xs text-text-primary select-none cursor-pointer">
                  Activate schedule immediately upon creation
                </label>
              </div>

              <div className="flex justify-end gap-2 pt-3 border-t border-surface-muted/20">
                <button
                  type="button"
                  onClick={() => setIsModalOpen(false)}
                  className="px-4 py-2 rounded-xl bg-canvas-dark hover:bg-canvas-dark/80 text-text-muted text-xs font-mono font-bold"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={saving}
                  className="px-5 py-2 rounded-xl bg-accent-primary hover:brightness-105 text-text-onLight text-xs font-mono font-bold transition-all disabled:opacity-50"
                >
                  {saving ? 'Saving...' : 'Create Schedule'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
