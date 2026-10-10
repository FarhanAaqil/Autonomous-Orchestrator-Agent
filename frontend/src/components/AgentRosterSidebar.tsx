/**
 * frontend/src/components/AgentRosterSidebar.tsx
 * Live Agent Roster sidebar displaying real-time health, circuit breakers, and administrative toggles.
 */

import React, { useEffect, useState } from 'react';
import { api } from '../api/client';
import { AgentInfo } from '../types/api';

interface AgentRosterSidebarProps {
  onSelectAgent?: (agentId: string) => void;
  selectedAgentId?: string | null;
}

export const AgentRosterSidebar: React.FC<AgentRosterSidebarProps> = ({
  onSelectAgent,
  selectedAgentId,
}) => {
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [updatingId, setUpdatingId] = useState<string | null>(null);

  const loadAgents = async () => {
    try {
      const data = await api.getAgents();
      setAgents(data);
    } catch (err) {
      console.error('Failed to load agents:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadAgents();
    const interval = setInterval(loadAgents, 10000);
    return () => clearInterval(interval);
  }, []);

  const handleToggle = async (e: React.MouseEvent, agent: AgentInfo) => {
    e.stopPropagation();
    setUpdatingId(agent.id);
    try {
      await api.updateAgent(agent.id, !agent.is_active);
      await loadAgents();
    } catch (err: any) {
      alert(`Failed to update agent: ${err.message}`);
    } finally {
      setUpdatingId(null);
    }
  };

  const getStatusBadge = (status: string, isActive: boolean) => {
    if (!isActive) {
      return (
        <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-mono font-bold bg-slate-200 text-slate-700">
          DISABLED
        </span>
      );
    }
    if (status === 'degraded') {
      return (
        <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-mono font-bold bg-amber-100 text-amber-800 border border-amber-300">
          <span className="w-1.5 h-1.5 rounded-full bg-amber-500 animate-pulse" />
          DEGRADED
        </span>
      );
    }
    return (
      <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-mono font-bold bg-emerald-100 text-emerald-800 border border-emerald-300">
        <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
        HEALTHY
      </span>
    );
  };

  return (
    <div className="w-full h-full flex flex-col bg-surface-primary border border-surface-muted/20 rounded-2xl overflow-hidden shadow-sm">
      <div className="p-3.5 border-b border-surface-muted/20 flex items-center justify-between bg-canvas-dark/40">
        <div>
          <h3 className="font-extrabold text-xs tracking-wider text-text-primary uppercase font-mono">
            Active Agent Fleet
          </h3>
          <span className="text-[11px] text-text-muted">
            {agents.filter((a) => a.is_active).length}/{agents.length} Online
          </span>
        </div>
        <button
          onClick={loadAgents}
          className="text-xs text-text-muted hover:text-text-primary transition-colors font-mono"
          title="Refresh agent states"
        >
          ↻
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-2 space-y-1.5 divide-y divide-surface-muted/10">
        {loading ? (
          <div className="p-4 text-center text-xs text-text-muted font-mono">
            Loading agent roster...
          </div>
        ) : (
          agents.map((agent) => {
            const isSelected = selectedAgentId === agent.id;
            const hasBreakerOpen = Object.values(agent.circuit_breakers || {}).some(
              (s) => s.toLowerCase() === 'open'
            );

            return (
              <div
                key={agent.id}
                onClick={() => onSelectAgent?.(agent.id)}
                className={`p-2.5 rounded-xl transition-all cursor-pointer space-y-1.5 ${
                  isSelected
                    ? 'bg-accent-primary/10 border border-accent-primary/50'
                    : 'hover:bg-canvas-dark/40 border border-transparent'
                }`}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="font-bold text-xs text-text-primary">{agent.name}</span>
                  </div>
                  {getStatusBadge(agent.status, agent.is_active)}
                </div>

                <p className="text-[11px] text-text-muted line-clamp-1 leading-tight">
                  {agent.description}
                </p>

                {/* Capability & Circuit Indicators */}
                <div className="flex items-center justify-between pt-1">
                  <span className="text-[10px] font-mono text-text-muted">
                    {agent.allowed_tools.length} Tools
                  </span>

                  <button
                    onClick={(e) => handleToggle(e, agent)}
                    disabled={updatingId === agent.id}
                    className={`px-2 py-0.5 rounded text-[10px] font-mono font-bold transition-all ${
                      agent.is_active
                        ? 'bg-emerald-50 text-emerald-800 hover:bg-rose-50 hover:text-rose-800 border border-emerald-300'
                        : 'bg-slate-200 text-slate-700 hover:bg-emerald-100 hover:text-emerald-800'
                    }`}
                  >
                    {updatingId === agent.id ? '...' : agent.is_active ? 'Disable' : 'Enable'}
                  </button>
                </div>

                {hasBreakerOpen && (
                  <div className="text-[10px] font-mono text-amber-700 bg-amber-50 p-1 rounded border border-amber-200 mt-1">
                    ⚠ Circuit breaker tripped on upstream read API
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
};
