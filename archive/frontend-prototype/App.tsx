/**
 * frontend/src/App.tsx
 * Application shell with MP072 design tokens, persistent navigation, and all Phase 8 views and sidebars.
 */

import React, { useState, useEffect } from 'react';
import { DispatchPage } from './pages/DispatchPage';
import { JobsPage } from './pages/JobsPage';
import { SchedulesPage } from './pages/SchedulesPage';
import { MemoryPage } from './pages/MemoryPage';
import { PipelinesPage } from './pages/PipelinesPage';
import { RunDetailPage } from './pages/RunDetailPage';
import { ApprovalsPage } from './pages/ApprovalsPage';
import { EvalPage } from './pages/EvalPage';
import { SettingsPage } from './pages/SettingsPage';
import { AgentRosterSidebar } from './components/AgentRosterSidebar';
import { SessionActivitySidebar } from './components/SessionActivitySidebar';
import { ConnectionStatusBadge } from './components/ConnectionStatusBadge';
import { api, subscribeJobEvents, ConnectionStatus } from './api/client';
import {
  Zap,
  Briefcase,
  Calendar,
  Brain,
  Workflow,
  ShieldCheck,
  BarChart3,
  Settings,
  Bot,
  Layers,
  Users,
  Activity,
} from 'lucide-react';

export type TabType =
  | 'dispatch'
  | 'jobs'
  | 'schedules'
  | 'memory'
  | 'pipelines'
  | 'runs'
  | 'approvals'
  | 'eval'
  | 'settings';

export const App: React.FC = () => {
  const [activeTab, setActiveTab] = useState<TabType>('dispatch');
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [pendingApprovalsCount, setPendingApprovalsCount] = useState(0);
  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>('reconnecting');
  const [showAgentRoster, setShowAgentRoster] = useState(false);
  const [showLiveActivity, setShowLiveActivity] = useState(false);

  // Subscribe to SSE connection status
  useEffect(() => {
    const unsub = subscribeJobEvents({
      onEvent: () => {},
      onStatusChange: (status) => setConnectionStatus(status),
    });
    return () => unsub();
  }, []);

  // Poll approvals count
  useEffect(() => {
    const pollApprovals = async () => {
      try {
        const data = await api.getApprovals('pending');
        setPendingApprovalsCount(data.total || 0);
      } catch {}
    };

    pollApprovals();
    const interval = setInterval(pollApprovals, 5000);
    return () => clearInterval(interval);
  }, []);

  const handleNavigateToRun = (runId: string) => {
    setActiveRunId(runId);
    setActiveTab('runs');
  };

  const navItems = [
    { id: 'dispatch', label: 'Dispatch', icon: Zap },
    { id: 'jobs', label: 'Jobs Timeline', icon: Briefcase },
    { id: 'schedules', label: 'Schedules', icon: Calendar },
    { id: 'memory', label: 'Memory', icon: Brain },
    { id: 'pipelines', label: 'Pipelines', icon: Workflow },
    {
      id: 'approvals',
      label: 'Approvals',
      icon: ShieldCheck,
      badge: pendingApprovalsCount > 0 ? pendingApprovalsCount : null,
    },
    { id: 'eval', label: 'Metrics & Eval', icon: BarChart3 },
    { id: 'settings', label: 'Settings', icon: Settings },
  ];

  return (
    <div className="min-h-screen bg-canvas-dark text-text-primary flex flex-col md:flex-row font-sans selection:bg-accent-primary selection:text-text-onLight">
      {/* Sidebar Navigation */}
      <aside className="w-full md:w-64 bg-surface-primary border-b md:border-b-0 md:border-r border-surface-muted/20 flex flex-col justify-between p-5 flex-shrink-0">
        <div className="space-y-6">
          {/* Brand Header */}
          <div className="flex items-center gap-3 px-2">
            <div className="w-10 h-10 rounded-2xl bg-accent-primary flex items-center justify-center text-text-onLight shadow-lg shadow-accent-primary/20">
              <Bot className="w-6 h-6" />
            </div>
            <div>
              <h1 className="font-extrabold text-lg text-[#EEE9DF] tracking-tight leading-none">
                Orchestrator
              </h1>
              <span className="text-[11px] font-mono text-accent-primary font-bold tracking-widest uppercase mt-0.5 block">
                Agent v2 Core
              </span>
            </div>
          </div>

          {/* Navigation Links */}
          <nav className="space-y-1" aria-label="Main Navigation">
            {navItems.map((item) => {
              const Icon = item.icon;
              const isActive = activeTab === item.id;
              return (
                <button
                  key={item.id}
                  onClick={() => {
                    setActiveTab(item.id as TabType);
                    if (item.id === 'pipelines') setActiveRunId(null);
                  }}
                  className={`w-full flex items-center justify-between px-3.5 py-2.5 rounded-xl text-xs font-semibold transition-all ${
                    isActive
                      ? 'bg-accent-primary text-text-onLight shadow-md'
                      : 'text-text-muted hover:text-text-primary hover:bg-canvas-dark/50'
                  }`}
                >
                  <div className="flex items-center gap-2.5">
                    <Icon className="w-4 h-4" />
                    <span>{item.label}</span>
                  </div>
                  {item.badge !== null && item.badge !== undefined && (
                    <span
                      className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${
                        isActive
                          ? 'bg-canvas-dark text-accent-primary'
                          : 'bg-state-warning text-[#EEE9DF]'
                      }`}
                    >
                      {item.badge}
                    </span>
                  )}
                </button>
              );
            })}

            {activeRunId && (
              <button
                onClick={() => setActiveTab('runs')}
                className={`w-full flex items-center gap-2.5 px-3.5 py-2.5 rounded-xl text-xs font-semibold transition-all ${
                  activeTab === 'runs'
                    ? 'bg-accent-primary text-text-onLight shadow-md'
                    : 'text-accent-primary/80 hover:bg-canvas-dark/50'
                }`}
              >
                <Layers className="w-4 h-4" />
                <span className="truncate">Run #{activeRunId.slice(0, 6)}</span>
              </button>
            )}
          </nav>
        </div>

        {/* Sidebar Footer: Connection State & Docs Link */}
        <div className="pt-6 border-t border-surface-muted/10 space-y-2">
          <div className="flex items-center justify-between">
            <ConnectionStatusBadge status={connectionStatus} />
            <a
              href="/docs"
              target="_blank"
              rel="noreferrer"
              className="text-[11px] text-accent-primary hover:underline font-mono"
            >
              Docs &rarr;
            </a>
          </div>

          <div className="flex gap-1.5 pt-1">
            <button
              onClick={() => setShowAgentRoster(!showAgentRoster)}
              className={`flex-1 py-1.5 rounded-lg border text-[11px] font-mono flex items-center justify-center gap-1 transition-all ${
                showAgentRoster
                  ? 'bg-accent-primary/10 border-accent-primary text-accent-primary font-bold'
                  : 'bg-canvas-dark/40 border-surface-muted/20 text-text-muted hover:text-text-primary'
              }`}
            >
              <Users className="w-3.5 h-3.5" />
              <span>Fleet</span>
            </button>
            <button
              onClick={() => setShowLiveActivity(!showLiveActivity)}
              className={`flex-1 py-1.5 rounded-lg border text-[11px] font-mono flex items-center justify-center gap-1 transition-all ${
                showLiveActivity
                  ? 'bg-accent-primary/10 border-accent-primary text-accent-primary font-bold'
                  : 'bg-canvas-dark/40 border-surface-muted/20 text-text-muted hover:text-text-primary'
              }`}
            >
              <Activity className="w-3.5 h-3.5" />
              <span>Events</span>
            </button>
          </div>
        </div>
      </aside>

      {/* Main Content Area */}
      <main className="flex-1 p-6 md:p-8 overflow-y-auto min-w-0">
        {activeTab === 'dispatch' && <DispatchPage />}
        {activeTab === 'jobs' && <JobsPage />}
        {activeTab === 'schedules' && <SchedulesPage />}
        {activeTab === 'memory' && <MemoryPage />}
        {activeTab === 'pipelines' && (
          <PipelinesPage onNavigateToRun={handleNavigateToRun} />
        )}
        {activeTab === 'runs' &&
          (activeRunId ? (
            <RunDetailPage
              runId={activeRunId}
              onBack={() => setActiveTab('pipelines')}
            />
          ) : (
            <PipelinesPage onNavigateToRun={handleNavigateToRun} />
          ))}
        {activeTab === 'approvals' && <ApprovalsPage />}
        {activeTab === 'eval' && <EvalPage />}
        {activeTab === 'settings' && <SettingsPage />}
      </main>

      {/* Optional Sidebars */}
      {showAgentRoster && (
        <aside className="w-80 border-l border-surface-muted/20 p-4 bg-canvas-dark/40 flex-shrink-0 hidden xl:block">
          <AgentRosterSidebar />
        </aside>
      )}

      {showLiveActivity && (
        <aside className="w-80 border-l border-surface-muted/20 p-4 bg-canvas-dark/40 flex-shrink-0 hidden xl:block">
          <SessionActivitySidebar />
        </aside>
      )}
    </div>
  );
};

export default App;
