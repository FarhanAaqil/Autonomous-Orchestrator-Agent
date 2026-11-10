/**
 * frontend/src/pages/SettingsPage.tsx
 * Executive Control Settings with emergency kill switch toggle, daily budget ceiling, and system flags.
 */

import React, { useState, useEffect } from 'react';
import { api } from '../api/client';
import { SystemFlagRecord, AgentInfo } from '../types/api';
import {
  Settings,
  ShieldAlert,
  Coins,
  Cpu,
  Palette,
  CheckCircle2,
  AlertTriangle,
  RefreshCw,
  Sliders,
} from 'lucide-react';

export const SettingsPage: React.FC = () => {
  const [flags, setFlags] = useState<SystemFlagRecord[]>([]);
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [killSwitchActive, setKillSwitchActive] = useState(false);
  const [budgetCeiling, setBudgetCeiling] = useState('10.00');
  const [isSavingBudget, setIsSavingBudget] = useState(false);
  const [isTogglingKill, setIsTogglingKill] = useState(false);
  const [notification, setNotification] = useState<{ type: 'success' | 'error'; message: string } | null>(null);

  // Appearance state
  const [selectedTheme, setSelectedTheme] = useState('silver');

  const fetchSettings = async () => {
    try {
      const [flagsData, agentsData] = await Promise.all([
        api.getSystemFlags().catch(() => []),
        api.getAgents().catch(() => []),
      ]);
      setFlags(flagsData);
      setAgents(agentsData);

      // Extract current flags
      const killFlag = flagsData.find((f) => f.key === 'kill_switch');
      setKillSwitchActive(killFlag ? killFlag.value.toLowerCase() === 'true' : false);

      const budgetFlag = flagsData.find((f) => f.key === 'daily_budget_usd');
      if (budgetFlag) setBudgetCeiling(budgetFlag.value);
    } catch (err) {
      console.error('Failed to load settings:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchSettings();
  }, []);

  const handleToggleKillSwitch = async () => {
    const nextState = !killSwitchActive;
    const warningMsg = nextState
      ? 'EMERGENCY ACTION: Activating the Kill Switch will immediately abort all running agent jobs and refuse new autonomous dispatches. Proceed?'
      : 'Deactivate the Kill Switch and resume autonomous agent operations?';

    if (!confirm(warningMsg)) return;

    setIsTogglingKill(true);
    try {
      await api.toggleKillSwitch(nextState);
      setKillSwitchActive(nextState);
      await fetchSettings();
      setNotification({
        type: nextState ? 'error' : 'success',
        message: nextState
          ? 'EMERGENCY KILL SWITCH ACTIVATED — All agent queues paused.'
          : 'Kill switch deactivated. Normal execution restored.',
      });
    } catch (err: any) {
      alert(`Failed to update kill switch: ${err.message}`);
    } finally {
      setIsTogglingKill(false);
    }
  };

  const handleSaveBudget = async (e: React.FormEvent) => {
    e.preventDefault();
    const val = parseFloat(budgetCeiling);
    if (isNaN(val) || val <= 0) {
      alert('Please enter a valid positive number for the budget ceiling.');
      return;
    }

    setIsSavingBudget(true);
    try {
      await api.setDailyBudget(val);
      await fetchSettings();
      setNotification({
        type: 'success',
        message: `Daily budget ceiling updated to $${val.toFixed(2)} USD.`,
      });
    } catch (err: any) {
      alert(`Failed to update budget: ${err.message}`);
    } finally {
      setIsSavingBudget(false);
    }
  };

  return (
    <div className="space-y-6 max-w-5xl mx-auto">
      {/* Top Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-surface-muted/20 pb-5">
        <div>
          <h2 className="text-2xl font-black text-text-primary flex items-center gap-2.5">
            <Settings className="w-6 h-6 text-accent-primary" />
            System Control & Security Settings
          </h2>
          <p className="text-sm text-text-muted mt-1">
            Global emergency guardrails, daily token expenditure ceilings, and model governance.
          </p>
        </div>

        <button
          onClick={fetchSettings}
          className="px-3 py-2 rounded-xl bg-surface-primary hover:bg-surface-primary/80 border border-surface-muted/20 text-text-primary text-xs font-mono font-bold flex items-center gap-1.5 transition-all self-start md:self-auto"
        >
          <RefreshCw className="w-3.5 h-3.5" />
          <span>Refresh</span>
        </button>
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
          <span>{notification.message}</span>
          <button onClick={() => setNotification(null)} className="text-text-muted hover:text-text-primary">
            ✕
          </button>
        </div>
      )}

      {/* Guardrails Section */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Emergency Kill Switch Card */}
        <div className={`p-6 rounded-2xl border transition-all space-y-4 ${
          killSwitchActive
            ? 'bg-rose-950/30 border-rose-500/60 shadow-xl ring-1 ring-rose-500/40'
            : 'bg-surface-primary border-surface-muted/20'
        }`}>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <span className={`p-2 rounded-xl ${killSwitchActive ? 'bg-rose-500/20 text-rose-400' : 'bg-surface-muted/10 text-text-muted'}`}>
                <ShieldAlert className="w-5 h-5" />
              </span>
              <div>
                <h3 className="text-sm font-bold text-text-primary">Emergency Kill Switch</h3>
                <span className="text-[11px] font-mono text-text-muted">Global Loop Interruption</span>
              </div>
            </div>

            <span
              className={`px-2.5 py-1 rounded-full text-[10px] font-mono font-bold ${
                killSwitchActive
                  ? 'bg-rose-500 text-white animate-pulse'
                  : 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
              }`}
            >
              {killSwitchActive ? 'ACTIVE / HALTED' : 'NORMAL / INACTIVE'}
            </span>
          </div>

          <p className="text-xs text-text-muted leading-relaxed">
            When triggered, every autonomous agent loop checks this flag before each tool call and aborts immediately. Workers refuse newly claimed jobs.
          </p>

          <button
            onClick={handleToggleKillSwitch}
            disabled={isTogglingKill}
            className={`w-full py-2.5 rounded-xl font-mono text-xs font-bold transition-all shadow-md flex items-center justify-center gap-2 ${
              killSwitchActive
                ? 'bg-emerald-600 hover:bg-emerald-500 text-white'
                : 'bg-rose-600 hover:bg-rose-500 text-white'
            }`}
          >
            {killSwitchActive ? (
              <>
                <CheckCircle2 className="w-4 h-4" />
                <span>Deactivate Kill Switch & Resume</span>
              </>
            ) : (
              <>
                <AlertTriangle className="w-4 h-4" />
                <span>Activate Emergency Kill Switch</span>
              </>
            )}
          </button>
        </div>

        {/* Daily Budget Ceiling Card */}
        <div className="p-6 rounded-2xl bg-surface-primary border border-surface-muted/20 space-y-4">
          <div className="flex items-center gap-2.5">
            <span className="p-2 rounded-xl bg-accent-primary/10 text-accent-primary">
              <Coins className="w-5 h-5" />
            </span>
            <div>
              <h3 className="text-sm font-bold text-text-primary">Daily Budget Ceiling</h3>
              <span className="text-[11px] font-mono text-text-muted">Autonomous Cost Hard Stop</span>
            </div>
          </div>

          <p className="text-xs text-text-muted leading-relaxed">
            Sets the daily expenditure ceiling across all Groq and OpenAI model inference calls. Once breached, subsequent steps abort with <code className="font-mono text-accent-primary">BudgetExceededError</code>.
          </p>

          <form onSubmit={handleSaveBudget} className="flex gap-2">
            <div className="relative flex-1">
              <span className="absolute left-3 top-2.5 text-xs font-mono text-text-muted">$</span>
              <input
                type="number"
                step="0.01"
                min="0.10"
                value={budgetCeiling}
                onChange={(e) => setBudgetCeiling(e.target.value)}
                className="w-full bg-canvas-dark border border-surface-muted/30 rounded-xl pl-7 pr-3 py-2 text-xs font-mono font-bold text-accent-primary focus:outline-none focus:border-accent-primary"
                required
              />
            </div>
            <button
              type="submit"
              disabled={isSavingBudget}
              className="px-4 py-2 rounded-xl bg-accent-primary hover:brightness-105 text-text-onLight text-xs font-mono font-bold transition-all disabled:opacity-50"
            >
              {isSavingBudget ? 'Saving...' : 'Set Budget'}
            </button>
          </form>
        </div>
      </div>

      {/* System Flags Table */}
      <div className="p-6 rounded-2xl bg-surface-primary border border-surface-muted/20 space-y-4">
        <h3 className="text-xs font-extrabold uppercase font-mono tracking-wider text-text-primary flex items-center gap-2">
          <Sliders className="w-4 h-4 text-accent-primary" />
          Active System Flags & Configurations
        </h3>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs font-mono">
            <thead>
              <tr className="border-b border-surface-muted/20 text-text-muted">
                <th className="p-2.5">Key</th>
                <th className="p-2.5">Value</th>
                <th className="p-2.5 text-right">Last Updated</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-surface-muted/10">
              {flags.map((flag) => (
                <tr key={flag.key}>
                  <td className="p-2.5 font-bold text-accent-primary">{flag.key}</td>
                  <td className="p-2.5 text-text-primary">{flag.value}</td>
                  <td className="p-2.5 text-right text-text-muted">
                    {new Date(flag.updated_at).toLocaleString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Theme & Aesthetics Selector */}
      <div className="p-6 rounded-2xl bg-surface-primary border border-surface-muted/20 space-y-4">
        <div className="flex items-center gap-2.5">
          <Palette className="w-5 h-5 text-accent-primary" />
          <div>
            <h3 className="text-sm font-bold text-text-primary">Executive Tone & Aesthetics</h3>
            <span className="text-[11px] font-mono text-text-muted">MP072 Curated Metallic Silver Palettes</span>
          </div>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          {[
            { id: 'light', label: 'Silver Light', hex: '#DCE2E9', desc: 'Soft metallic morning tone' },
            { id: 'silver', label: 'Metallic Silver', hex: '#B0B8C4', desc: 'True metallic control plane' },
            { id: 'deep', label: 'Deep Silver', hex: '#96A0AF', desc: 'High-contrast focused executive' },
          ].map((theme) => (
            <button
              key={theme.id}
              onClick={() => setSelectedTheme(theme.id)}
              className={`p-3.5 rounded-xl border text-left transition-all ${
                selectedTheme === theme.id
                  ? 'bg-accent-primary/10 border-accent-primary shadow-sm'
                  : 'bg-canvas-dark/50 border-surface-muted/20 hover:border-surface-muted/40'
              }`}
            >
              <div className="flex items-center justify-between mb-1">
                <span className="font-bold text-xs text-text-primary">{theme.label}</span>
                <span
                  className="w-4 h-4 rounded-full border border-black/20"
                  style={{ backgroundColor: theme.hex }}
                />
              </div>
              <p className="text-[10px] text-text-muted">{theme.desc}</p>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
};
