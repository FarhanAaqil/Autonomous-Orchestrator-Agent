/**
 * frontend/src/components/SessionActivitySidebar.tsx
 * Live Session & Job Activity sidebar consuming SSE event feed with pause/resume and payload inspection.
 */

import React, { useEffect, useState, useRef } from 'react';
import { subscribeJobEvents, ConnectionStatus } from '../api/client';
import { Activity, Pause, Play, Trash2, ChevronDown, ChevronRight, Terminal } from 'lucide-react';

export interface ActivityEvent {
  id: string;
  type: string;
  timestamp: string;
  data: any;
}

interface SessionActivitySidebarProps {
  sessionId?: string | null;
  onSelectJob?: (jobId: string) => void;
  className?: string;
}

export const SessionActivitySidebar: React.FC<SessionActivitySidebarProps> = ({
  sessionId,
  onSelectJob,
  className = '',
}) => {
  const [events, setEvents] = useState<ActivityEvent[]>([]);
  const [isPaused, setIsPaused] = useState(false);
  const [status, setStatus] = useState<ConnectionStatus>('reconnecting');
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());
  const [selectedFilter, setSelectedFilter] = useState<string>('all');
  const feedEndRef = useRef<HTMLDivElement>(null);
  const isPausedRef = useRef(isPaused);
  isPausedRef.current = isPaused;

  useEffect(() => {
    const unsubscribe = subscribeJobEvents({
      onEvent: (type: string, data: any) => {
        if (isPausedRef.current) return;
        const newEvent: ActivityEvent = {
          id: `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
          type,
          timestamp: new Date().toLocaleTimeString(),
          data,
        };
        setEvents((prev) => [newEvent, ...prev].slice(0, 80));
      },
      onStatusChange: (s) => setStatus(s),
    });

    return () => unsubscribe();
  }, []);

  const toggleExpand = (id: string) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const getEventBadge = (type: string) => {
    switch (type) {
      case 'job.created':
        return <span className="px-1.5 py-0.5 rounded text-[10px] font-mono font-bold bg-blue-900/40 text-blue-300 border border-blue-500/30">CREATED</span>;
      case 'job.step':
        return <span className="px-1.5 py-0.5 rounded text-[10px] font-mono font-bold bg-amber-900/40 text-amber-300 border border-amber-500/30">STEP</span>;
      case 'job.updated':
        return <span className="px-1.5 py-0.5 rounded text-[10px] font-mono font-bold bg-purple-900/40 text-purple-300 border border-purple-500/30">UPDATE</span>;
      case 'job.completed':
        return <span className="px-1.5 py-0.5 rounded text-[10px] font-mono font-bold bg-emerald-900/40 text-emerald-300 border border-emerald-500/30">DONE</span>;
      case 'agent.status':
        return <span className="px-1.5 py-0.5 rounded text-[10px] font-mono font-bold bg-teal-900/40 text-teal-300 border border-teal-500/30">AGENT</span>;
      default:
        return <span className="px-1.5 py-0.5 rounded text-[10px] font-mono font-bold bg-slate-800 text-slate-300 border border-slate-700">{type}</span>;
    }
  };

  const filteredEvents = events.filter((ev) => {
    if (selectedFilter === 'all') return true;
    return ev.type.startsWith(selectedFilter);
  });

  return (
    <div className={`flex flex-col h-full bg-surface-primary border border-surface-muted/20 rounded-2xl overflow-hidden shadow-sm ${className}`}>
      {/* Header */}
      <div className="p-3.5 border-b border-surface-muted/20 flex items-center justify-between bg-canvas-dark/40">
        <div className="flex items-center gap-2">
          <Activity className="w-4 h-4 text-accent-primary animate-pulse" />
          <div>
            <h3 className="font-extrabold text-xs tracking-wider text-text-primary uppercase font-mono">
              Live Session Activity
            </h3>
            <span className="text-[10px] text-text-muted font-mono">
              {status === 'connected' ? 'SSE Live Stream' : status === 'reconnecting' ? 'Reconnecting...' : 'Offline'}
            </span>
          </div>
        </div>

        <div className="flex items-center gap-1.5">
          <button
            onClick={() => setIsPaused(!isPaused)}
            className={`p-1.5 rounded-lg border text-xs font-mono transition-all ${
              isPaused
                ? 'bg-amber-900/30 border-amber-600/50 text-amber-300'
                : 'bg-canvas-dark/60 border-surface-muted/30 text-text-muted hover:text-text-primary'
            }`}
            title={isPaused ? 'Resume stream' : 'Pause stream'}
          >
            {isPaused ? <Play className="w-3.5 h-3.5" /> : <Pause className="w-3.5 h-3.5" />}
          </button>
          <button
            onClick={() => setEvents([])}
            className="p-1.5 rounded-lg bg-canvas-dark/60 border border-surface-muted/30 text-text-muted hover:text-rose-400 transition-colors"
            title="Clear event buffer"
          >
            <Trash2 className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* Filter Tabs */}
      <div className="px-3 py-2 border-b border-surface-muted/10 bg-canvas-dark/20 flex items-center gap-1 overflow-x-auto text-[11px] font-mono">
        {['all', 'job', 'agent'].map((f) => (
          <button
            key={f}
            onClick={() => setSelectedFilter(f)}
            className={`px-2 py-0.5 rounded-md transition-all ${
              selectedFilter === f
                ? 'bg-accent-primary text-text-onLight font-bold'
                : 'text-text-muted hover:text-text-primary hover:bg-canvas-dark/50'
            }`}
          >
            {f.toUpperCase()}
          </button>
        ))}
        <span className="ml-auto text-[10px] text-text-muted font-mono">{filteredEvents.length} events</span>
      </div>

      {/* Event Stream List */}
      <div className="flex-1 overflow-y-auto p-2 space-y-2 font-mono">
        {filteredEvents.length === 0 ? (
          <div className="p-6 text-center text-xs text-text-muted">
            <Terminal className="w-6 h-6 mx-auto mb-2 opacity-40 text-accent-primary" />
            <p>Waiting for live events...</p>
            <p className="text-[10px] mt-1 text-text-muted/60">Jobs, step telemetry & agent state changes appear here in real time.</p>
          </div>
        ) : (
          filteredEvents.map((ev) => {
            const isExpanded = expandedIds.has(ev.id);
            const jobId = ev.data?.job_id || ev.data?.id;

            return (
              <div
                key={ev.id}
                className="p-2.5 rounded-xl bg-canvas-dark/50 border border-surface-muted/15 hover:border-surface-muted/30 transition-all text-xs"
              >
                <div className="flex items-center justify-between gap-1.5 mb-1.5">
                  <div className="flex items-center gap-1.5">
                    {getEventBadge(ev.type)}
                    <span className="text-[10px] text-text-muted">{ev.timestamp}</span>
                  </div>
                  {jobId && onSelectJob && (
                    <button
                      onClick={() => onSelectJob(jobId)}
                      className="text-[10px] text-accent-primary hover:underline font-mono"
                    >
                      #{String(jobId).slice(0, 8)}
                    </button>
                  )}
                </div>

                <div className="text-[11px] text-text-primary font-sans leading-tight">
                  {ev.data?.step_name ? (
                    <span>
                      Step <strong>{ev.data.step_number || ''}</strong>: <code className="font-mono text-accent-primary">{ev.data.step_name}</code>
                    </span>
                  ) : ev.data?.goal ? (
                    <span className="line-clamp-2">{ev.data.goal}</span>
                  ) : ev.data?.agent ? (
                    <span>Agent: <strong>{ev.data.agent}</strong> &rarr; {ev.data.status || 'updated'}</span>
                  ) : (
                    <span className="text-text-muted">Event received</span>
                  )}
                </div>

                {/* Collapsible raw data */}
                <div className="mt-1 pt-1 border-t border-surface-muted/10">
                  <button
                    onClick={() => toggleExpand(ev.id)}
                    className="flex items-center gap-1 text-[10px] text-text-muted hover:text-text-primary transition-colors"
                  >
                    {isExpanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                    <span>{isExpanded ? 'Hide payload' : 'Inspect payload'}</span>
                  </button>
                  {isExpanded && (
                    <pre className="mt-1.5 p-2 rounded-lg bg-canvas-dark/90 text-[10px] text-text-muted overflow-x-auto border border-surface-muted/20">
                      {JSON.stringify(ev.data, null, 2)}
                    </pre>
                  )}
                </div>
              </div>
            );
          })
        )}
        <div ref={feedEndRef} />
      </div>
    </div>
  );
};
