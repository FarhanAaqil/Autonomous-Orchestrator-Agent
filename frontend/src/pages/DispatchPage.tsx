/**
 * frontend/src/pages/DispatchPage.tsx
 * Natural language command dispatch with sticky-bottom scroll sentinel and "Jump to latest" control.
 */

import React, { useState, useEffect, useRef } from 'react';
import { CommandInput } from '../components/CommandInput';
import { ClarificationPrompt } from '../components/ClarificationPrompt';
import { api } from '../api/client';
import { AgentResult, ClarificationNeeded } from '../types/api';
import { Cpu, Zap, ArrowDown, User, Bot, AlertCircle } from 'lucide-react';

interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  agent?: string;
  timestamp: string;
  metadata?: Record<string, any>;
  actionType?: string;
}

const SUGGESTIONS = [
  'Tailor my resume for a Senior Machine Learning Engineer role at DeepMind',
  'Write a research paper on federated learning for IoT edge devices',
  'Draft a tech blog post for Hashnode about building multi-agent systems',
  'Critique this cover letter and suggest improvements for higher ATS score',
  'Help me with my career project',
];

export const DispatchPage: React.FC = () => {
  const [isLoading, setIsLoading] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [clarification, setClarification] = useState<ClarificationNeeded | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Sticky-bottom scroll state & refs
  const [isPinned, setIsPinned] = useState(true);
  const sentinelRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // IntersectionObserver on sentinel to determine if viewport is at bottom
  useEffect(() => {
    const sentinel = sentinelRef.current;
    if (!sentinel) return;

    const observer = new IntersectionObserver(
      (entries) => {
        const [entry] = entries;
        setIsPinned(entry.isIntersecting);
      },
      {
        root: containerRef.current,
        threshold: 0.1,
      }
    );

    observer.observe(sentinel);
    return () => observer.disconnect();
  }, []);

  // When new messages arrive, auto-scroll if and only if pinned
  useEffect(() => {
    if (isPinned && sentinelRef.current) {
      sentinelRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages, isPinned]);

  const scrollToBottom = () => {
    if (sentinelRef.current) {
      sentinelRef.current.scrollIntoView({ behavior: 'smooth' });
      setIsPinned(true);
    }
  };

  const handleCommand = async (cmd: string) => {
    setIsLoading(true);
    setError(null);
    setClarification(null);

    const userMsg: ChatMessage = {
      id: `u-${Date.now()}`,
      role: 'user',
      content: cmd,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    };

    setMessages((prev) => [...prev, userMsg]);

    try {
      const data: AgentResult = await api.dispatch(cmd);
      const assistantMsg: ChatMessage = {
        id: `a-${Date.now()}`,
        role: 'assistant',
        content: data.output,
        agent: data.agent,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        metadata: data.metadata,
        actionType: data.action_type,
      };
      setMessages((prev) => [...prev, assistantMsg]);
    } catch (err: any) {
      if (err.isClarification) {
        setClarification({
          candidates: err.candidates || [],
          reasoning: err.reasoning || 'Confidence below threshold.',
        });
      } else {
        setError(err.message || 'An error occurred while dispatching command.');
      }
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="flex flex-col h-[calc(100vh-6rem)] max-w-5xl mx-auto space-y-4">
      {/* Header */}
      <div className="flex-shrink-0">
        <h2 className="text-2xl font-black text-text-primary flex items-center gap-2.5">
          <Zap className="w-6 h-6 text-accent-primary" />
          Natural Language Dispatch
        </h2>
        <p className="text-sm text-text-muted mt-1">
          Route instructions to specialist agents through the measured LLM routing engine with live streaming.
        </p>
      </div>

      {/* Chat Messages Container */}
      <div
        ref={containerRef}
        className="flex-1 overflow-y-auto bg-surface-primary/40 rounded-2xl border border-surface-muted/20 p-5 space-y-4 relative shadow-inner"
      >
        {messages.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-center p-8 text-text-muted space-y-3">
            <div className="w-12 h-12 rounded-2xl bg-accent-primary/10 flex items-center justify-center text-accent-primary">
              <Bot className="w-6 h-6" />
            </div>
            <h4 className="font-bold text-sm text-text-primary">Executive Dispatch Chat</h4>
            <p className="text-xs max-w-md">
              Send instructions to the multi-agent core. The measured router automatically matches your intent to the optimal specialist agent.
            </p>
          </div>
        ) : (
          messages.map((m) => (
            <div
              key={m.id}
              className={`flex gap-3.5 ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}
            >
              {m.role === 'assistant' && (
                <div className="w-8 h-8 rounded-xl bg-accent-primary/20 border border-accent-primary/30 flex items-center justify-center text-accent-primary flex-shrink-0 mt-0.5">
                  <Bot className="w-4 h-4" />
                </div>
              )}

              <div
                className={`max-w-2xl rounded-2xl p-4 shadow-sm space-y-2 ${
                  m.role === 'user'
                    ? 'bg-accent-primary text-text-onLight rounded-br-sm'
                    : 'bg-surface-primary border border-surface-muted/25 text-text-primary rounded-bl-sm'
                }`}
              >
                {m.role === 'assistant' && (
                  <div className="flex items-center justify-between gap-3 pb-2 border-b border-surface-muted/15 text-xs font-mono">
                    <span className="font-bold text-accent-primary flex items-center gap-1.5">
                      <Cpu className="w-3.5 h-3.5" />
                      {m.agent}
                    </span>
                    <span className="text-[10px] text-text-muted">{m.timestamp}</span>
                  </div>
                )}

                <div className="text-sm whitespace-pre-wrap leading-relaxed font-sans">
                  {m.content}
                </div>

                {m.actionType && (
                  <div className="mt-2 p-2.5 rounded-xl bg-amber-500/15 border border-amber-500/30 text-xs flex items-center justify-between">
                    <span className="text-amber-200">
                      Approval queued for external action: <code className="font-mono text-accent-primary">{m.actionType}</code>
                    </span>
                    <a
                      href="#approvals"
                      className="px-2.5 py-1 rounded-lg bg-accent-primary text-text-onLight text-[11px] font-mono font-bold"
                    >
                      Approvals &rarr;
                    </a>
                  </div>
                )}

                {m.role === 'user' && (
                  <div className="text-[10px] opacity-70 text-right font-mono mt-1">
                    {m.timestamp}
                  </div>
                )}
              </div>

              {m.role === 'user' && (
                <div className="w-8 h-8 rounded-xl bg-surface-primary border border-surface-muted/30 flex items-center justify-center text-text-muted flex-shrink-0 mt-0.5">
                  <User className="w-4 h-4" />
                </div>
              )}
            </div>
          ))
        )}

        {/* Clarification Prompt */}
        {clarification && (
          <ClarificationPrompt
            data={clarification}
            onSelectCandidate={(agent) =>
              handleCommand(`[Target: ${agent}] ${clarification.reasoning}`)
            }
          />
        )}

        {/* Error Alert */}
        {error && (
          <div className="p-4 rounded-xl bg-rose-950/40 border border-rose-500/40 text-rose-300 text-xs flex items-center gap-2 font-mono">
            <AlertCircle className="w-4 h-4" />
            <span>{error}</span>
          </div>
        )}

        {/* Bottom Sentinel */}
        <div ref={sentinelRef} className="h-2" />

        {/* Floating "Jump to latest" Pill */}
        {!isPinned && messages.length > 0 && (
          <button
            onClick={scrollToBottom}
            className="sticky bottom-3 left-1/2 -translate-x-1/2 mx-auto px-4 py-2 rounded-full bg-accent-primary hover:brightness-105 text-text-onLight text-xs font-mono font-bold shadow-xl border border-white/20 flex items-center gap-1.5 transition-all animate-bounce z-10"
          >
            <ArrowDown className="w-3.5 h-3.5" />
            <span>Jump to latest ↓</span>
          </button>
        )}
      </div>

      {/* Suggestion Chips */}
      <div className="flex flex-wrap items-center gap-1.5 flex-shrink-0">
        <span className="text-[11px] text-text-muted font-medium mr-1">Suggestions:</span>
        {SUGGESTIONS.map((s, idx) => (
          <button
            key={idx}
            onClick={() => handleCommand(s)}
            disabled={isLoading}
            className="text-[11px] px-2.5 py-1 rounded-xl bg-surface-primary hover:bg-surface-primary/80 border border-surface-muted/20 text-text-primary transition-all disabled:opacity-40 truncate max-w-xs"
          >
            {s}
          </button>
        ))}
      </div>

      {/* Command Input Bar */}
      <div className="flex-shrink-0">
        <CommandInput onSubmit={handleCommand} isLoading={isLoading} />
      </div>
    </div>
  );
};
