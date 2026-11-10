/**
 * frontend/src/pages/MemoryPage.tsx
 * Long-term Semantic & Episodic Memory control plane with human-in-the-loop pending review queue.
 */

import React, { useState, useEffect, useMemo } from 'react';
import { api } from '../api/client';
import { MemoryItemResponse } from '../types/api';
import {
  Brain,
  Search,
  Check,
  X,
  Trash2,
  Edit2,
  Plus,
  RefreshCw,
  Sparkles,
  BookOpen,
  UserCheck,
  Layers,
  Calendar,
} from 'lucide-react';

export const MemoryPage: React.FC = () => {
  const [memories, setMemories] = useState<MemoryItemResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<'pending' | 'facts' | 'episodes'>('pending');
  const [searchQuery, setSearchQuery] = useState('');
  const [notification, setNotification] = useState<{ type: 'success' | 'error'; message: string } | null>(null);

  // New Memory Modal state
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [newKind, setNewKind] = useState<'fact' | 'preference' | 'episode_summary'>('fact');
  const [newKey, setNewKey] = useState('');
  const [newValue, setNewValue] = useState('');
  const [saving, setSaving] = useState(false);

  // Edit Modal state
  const [editingItem, setEditingItem] = useState<MemoryItemResponse | null>(null);
  const [editValue, setEditValue] = useState('');
  const [editKey, setEditKey] = useState('');

  // Summarize Session modal state
  const [isSummarizeOpen, setIsSummarizeOpen] = useState(false);
  const [sessionIdInput, setSessionIdInput] = useState('');
  const [summarizing, setSummarizing] = useState(false);

  const fetchMemories = async () => {
    try {
      const data = await api.getMemories({ limit: 100 });
      setMemories(data || []);
    } catch (err) {
      console.error('Failed to load memories:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchMemories();
  }, []);

  const handleConfirm = async (id: string) => {
    try {
      await api.confirmMemory(id);
      await fetchMemories();
      setNotification({ type: 'success', message: 'Memory item confirmed and promoted to active retrieval.' });
    } catch (err: any) {
      alert(`Confirm failed: ${err.message}`);
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm('Are you sure you want to delete this memory item and purge its vector embedding?')) return;
    try {
      await api.deleteMemory(id);
      await fetchMemories();
      setNotification({ type: 'success', message: 'Memory purged from both SQLite and ChromaDB vector store.' });
    } catch (err: any) {
      alert(`Delete failed: ${err.message}`);
    }
  };

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newValue.trim()) return;
    setSaving(true);
    try {
      await api.createMemory({
        kind: newKind,
        key: newKey.trim() || undefined,
        value: newValue.trim(),
        pending_review: false,
      });
      setIsCreateOpen(false);
      setNewKey('');
      setNewValue('');
      await fetchMemories();
      setNotification({ type: 'success', message: 'Memory item created successfully.' });
    } catch (err: any) {
      alert(`Create failed: ${err.message}`);
    } finally {
      setSaving(false);
    }
  };

  const handleEditSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editingItem || !editValue.trim()) return;
    try {
      await api.updateMemory(editingItem.id, {
        value: editValue.trim(),
        key: editKey.trim() || undefined,
      });
      setEditingItem(null);
      await fetchMemories();
      setNotification({ type: 'success', message: 'Memory item updated.' });
    } catch (err: any) {
      alert(`Update failed: ${err.message}`);
    }
  };

  const handleSummarizeSession = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!sessionIdInput.trim()) return;
    setSummarizing(true);
    try {
      await api.summarizeSession(sessionIdInput.trim());
      setIsSummarizeOpen(false);
      setSessionIdInput('');
      await fetchMemories();
      setNotification({ type: 'success', message: 'Session summarized and indexed into episodic memory.' });
    } catch (err: any) {
      alert(`Summarization failed: ${err.message}`);
    } finally {
      setSummarizing(false);
    }
  };

  // Filter memories
  const pendingCount = memories.filter((m) => Boolean(m.pending_review)).length;

  const filteredMemories = useMemo(() => {
    return memories.filter((item) => {
      // Tab filter
      if (activeTab === 'pending' && !item.pending_review) return false;
      if (activeTab === 'facts' && (item.pending_review || item.kind === 'episode_summary')) return false;
      if (activeTab === 'episodes' && (item.pending_review || item.kind !== 'episode_summary')) return false;

      // Search filter
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const matchesValue = item.value.toLowerCase().includes(q);
        const matchesKey = item.key ? item.key.toLowerCase().includes(q) : false;
        return matchesValue || matchesKey;
      }

      return true;
    });
  }, [memories, activeTab, searchQuery]);

  return (
    <div className="space-y-6 max-w-6xl mx-auto">
      {/* Top Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-surface-muted/20 pb-5">
        <div>
          <h2 className="text-2xl font-black text-text-primary flex items-center gap-2.5">
            <Brain className="w-6 h-6 text-accent-primary" />
            Memory & Episodic Knowledge Engine
          </h2>
          <p className="text-sm text-text-muted mt-1">
            Budgeted episodic and semantic context store with human review confirmation gates and vector purge capabilities.
          </p>
        </div>

        <div className="flex items-center gap-2.5">
          <button
            onClick={() => setIsSummarizeOpen(true)}
            className="px-3 py-2 rounded-xl bg-surface-primary hover:bg-surface-primary/80 border border-surface-muted/20 text-text-primary text-xs font-mono font-bold flex items-center gap-1.5 transition-all"
          >
            <Sparkles className="w-3.5 h-3.5 text-accent-primary" />
            <span>Summarize Session</span>
          </button>
          <button
            onClick={() => setIsCreateOpen(true)}
            className="px-4 py-2 rounded-xl bg-accent-primary hover:brightness-105 text-text-onLight text-xs font-mono font-bold flex items-center gap-1.5 shadow-md transition-all"
          >
            <Plus className="w-4 h-4" />
            <span>Add Memory</span>
          </button>
        </div>
      </div>

      {/* Notification Banner */}
      {notification && (
        <div className="p-3.5 rounded-xl bg-emerald-950/40 border border-emerald-500/40 text-emerald-300 text-xs font-mono flex items-center justify-between">
          <span>{notification.message}</span>
          <button onClick={() => setNotification(null)} className="text-text-muted hover:text-text-primary">
            ✕
          </button>
        </div>
      )}

      {/* Controls Bar: Navigation Tabs & Search Input */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div className="flex items-center gap-1 bg-surface-primary p-1 rounded-xl border border-surface-muted/20 text-xs font-mono">
          <button
            onClick={() => setActiveTab('pending')}
            className={`flex items-center gap-2 px-3 py-1.5 rounded-lg transition-all ${
              activeTab === 'pending'
                ? 'bg-accent-primary text-text-onLight font-bold'
                : 'text-text-muted hover:text-text-primary'
            }`}
          >
            <UserCheck className="w-3.5 h-3.5" />
            <span>Pending Review</span>
            {pendingCount > 0 && (
              <span className={`px-1.5 py-0.2 rounded-full text-[10px] font-bold ${
                activeTab === 'pending' ? 'bg-canvas-dark text-accent-primary' : 'bg-amber-600 text-white'
              }`}>
                {pendingCount}
              </span>
            )}
          </button>

          <button
            onClick={() => setActiveTab('facts')}
            className={`flex items-center gap-2 px-3 py-1.5 rounded-lg transition-all ${
              activeTab === 'facts'
                ? 'bg-accent-primary text-text-onLight font-bold'
                : 'text-text-muted hover:text-text-primary'
            }`}
          >
            <BookOpen className="w-3.5 h-3.5" />
            <span>Facts & Preferences</span>
          </button>

          <button
            onClick={() => setActiveTab('episodes')}
            className={`flex items-center gap-2 px-3 py-1.5 rounded-lg transition-all ${
              activeTab === 'episodes'
                ? 'bg-accent-primary text-text-onLight font-bold'
                : 'text-text-muted hover:text-text-primary'
            }`}
          >
            <Layers className="w-3.5 h-3.5" />
            <span>Episode Summaries</span>
          </button>
        </div>

        {/* Search Bar */}
        <div className="relative min-w-[240px]">
          <Search className="w-4 h-4 absolute left-3 top-2.5 text-text-muted" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search memory items..."
            className="w-full bg-surface-primary border border-surface-muted/25 rounded-xl pl-9 pr-3 py-2 text-xs text-text-primary placeholder:text-text-muted/60 focus:outline-none focus:border-accent-primary font-mono"
          />
        </div>
      </div>

      {/* Memory Cards Grid */}
      {loading ? (
        <div className="p-12 text-center text-xs font-mono text-text-muted bg-surface-primary rounded-2xl border border-surface-muted/20">
          Loading memory index...
        </div>
      ) : filteredMemories.length === 0 ? (
        <div className="p-12 text-center text-xs font-mono text-text-muted bg-surface-primary rounded-2xl border border-surface-muted/20">
          {activeTab === 'pending'
            ? 'No memory items currently awaiting confirmation.'
            : 'No memory items found matching the selected view.'}
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {filteredMemories.map((item) => (
            <div
              key={item.id}
              className={`p-5 rounded-2xl border transition-all space-y-3.5 ${
                item.pending_review
                  ? 'bg-amber-950/20 border-amber-500/30 shadow-md'
                  : 'bg-surface-primary border-surface-muted/20 shadow-sm'
              }`}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-center gap-2">
                  <span
                    className={`px-2 py-0.5 rounded text-[10px] font-mono font-bold uppercase ${
                      item.kind === 'preference'
                        ? 'bg-purple-900/40 text-purple-300 border border-purple-500/30'
                        : item.kind === 'episode_summary'
                        ? 'bg-teal-900/40 text-teal-300 border border-teal-500/30'
                        : 'bg-blue-900/40 text-blue-300 border border-blue-500/30'
                    }`}
                  >
                    {item.kind.replace('_', ' ')}
                  </span>
                  {item.key && (
                    <span className="text-xs font-mono font-bold text-accent-primary">
                      {item.key}
                    </span>
                  )}
                </div>

                {item.pending_review ? (
                  <div className="flex items-center gap-1.5">
                    <button
                      onClick={() => handleConfirm(item.id)}
                      className="px-2.5 py-1 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-mono font-bold flex items-center gap-1 transition-all shadow-sm"
                      title="Confirm into long-term memory"
                    >
                      <Check className="w-3.5 h-3.5" />
                      <span>Confirm</span>
                    </button>
                    <button
                      onClick={() => handleDelete(item.id)}
                      className="p-1 rounded-lg bg-rose-950/40 hover:bg-rose-900 text-rose-300 border border-rose-500/30 transition-colors"
                      title="Reject & Discard"
                    >
                      <X className="w-4 h-4" />
                    </button>
                  </div>
                ) : (
                  <div className="flex items-center gap-1">
                    <button
                      onClick={() => {
                        setEditingItem(item);
                        setEditKey(item.key || '');
                        setEditValue(item.value);
                      }}
                      className="p-1.5 rounded-lg bg-canvas-dark text-text-muted hover:text-text-primary border border-surface-muted/20 transition-colors"
                      title="Edit memory"
                    >
                      <Edit2 className="w-3.5 h-3.5" />
                    </button>
                    <button
                      onClick={() => handleDelete(item.id)}
                      className="p-1.5 rounded-lg bg-canvas-dark text-text-muted hover:text-rose-400 border border-surface-muted/20 transition-colors"
                      title="Purge memory"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                )}
              </div>

              {/* Memory Text Content */}
              <p className="text-sm text-text-primary leading-relaxed bg-canvas-dark/60 p-3.5 rounded-xl border border-surface-muted/15 font-sans">
                {item.value}
              </p>

              {/* Metadata Footer */}
              <div className="flex items-center justify-between text-[11px] font-mono text-text-muted pt-1 border-t border-surface-muted/10">
                <span className="truncate">#{item.id.slice(0, 8)}</span>
                <span className="flex items-center gap-1">
                  <Calendar className="w-3 h-3" />
                  {new Date(item.created_at).toLocaleDateString()}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Add Memory Modal */}
      {isCreateOpen && (
        <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-surface-primary border border-surface-muted/30 rounded-2xl max-w-lg w-full p-6 shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-surface-muted/20 pb-3">
              <h3 className="font-bold text-base text-text-primary">Record Memory Item</h3>
              <button onClick={() => setIsCreateOpen(false)} className="text-text-muted hover:text-text-primary">
                ✕
              </button>
            </div>

            <form onSubmit={handleCreate} className="space-y-4">
              <div>
                <label className="block text-xs font-mono font-bold text-text-muted uppercase mb-1">
                  Memory Kind
                </label>
                <select
                  value={newKind}
                  onChange={(e: any) => setNewKind(e.target.value)}
                  className="w-full bg-canvas-dark border border-surface-muted/30 rounded-xl px-3 py-2 text-xs text-text-primary focus:outline-none focus:border-accent-primary font-mono"
                >
                  <option value="fact">Fact (Knowledge statement)</option>
                  <option value="preference">Preference (User instruction/preference)</option>
                  <option value="episode_summary">Episode Summary</option>
                </select>
              </div>

              <div>
                <label className="block text-xs font-mono font-bold text-text-muted uppercase mb-1">
                  Topic / Key (Optional)
                </label>
                <input
                  type="text"
                  value={newKey}
                  onChange={(e) => setNewKey(e.target.value)}
                  placeholder="e.g. resume_preferences, target_company"
                  className="w-full bg-canvas-dark border border-surface-muted/30 rounded-xl px-3 py-2 text-xs text-text-primary focus:outline-none focus:border-accent-primary font-mono"
                />
              </div>

              <div>
                <label className="block text-xs font-mono font-bold text-text-muted uppercase mb-1">
                  Memory Value / Description
                </label>
                <textarea
                  rows={4}
                  value={newValue}
                  onChange={(e) => setNewValue(e.target.value)}
                  placeholder="The knowledge or preference to inject into context during retrieval..."
                  className="w-full bg-canvas-dark border border-surface-muted/30 rounded-xl p-3 text-xs text-text-primary focus:outline-none focus:border-accent-primary"
                  required
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
                  disabled={saving}
                  className="px-5 py-2 rounded-xl bg-accent-primary hover:brightness-105 text-text-onLight text-xs font-mono font-bold transition-all disabled:opacity-50"
                >
                  {saving ? 'Saving...' : 'Record Memory'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Edit Memory Modal */}
      {editingItem && (
        <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-surface-primary border border-surface-muted/30 rounded-2xl max-w-lg w-full p-6 shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-surface-muted/20 pb-3">
              <h3 className="font-bold text-base text-text-primary">Edit Memory Item</h3>
              <button onClick={() => setEditingItem(null)} className="text-text-muted hover:text-text-primary">
                ✕
              </button>
            </div>

            <form onSubmit={handleEditSubmit} className="space-y-4">
              <div>
                <label className="block text-xs font-mono font-bold text-text-muted uppercase mb-1">
                  Topic / Key
                </label>
                <input
                  type="text"
                  value={editKey}
                  onChange={(e) => setEditKey(e.target.value)}
                  className="w-full bg-canvas-dark border border-surface-muted/30 rounded-xl px-3 py-2 text-xs text-text-primary focus:outline-none focus:border-accent-primary font-mono"
                />
              </div>

              <div>
                <label className="block text-xs font-mono font-bold text-text-muted uppercase mb-1">
                  Memory Value
                </label>
                <textarea
                  rows={4}
                  value={editValue}
                  onChange={(e) => setEditValue(e.target.value)}
                  className="w-full bg-canvas-dark border border-surface-muted/30 rounded-xl p-3 text-xs text-text-primary focus:outline-none focus:border-accent-primary"
                  required
                />
              </div>

              <div className="flex justify-end gap-2 pt-3 border-t border-surface-muted/20">
                <button
                  type="button"
                  onClick={() => setEditingItem(null)}
                  className="px-4 py-2 rounded-xl bg-canvas-dark text-text-muted text-xs font-mono font-bold"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="px-5 py-2 rounded-xl bg-accent-primary hover:brightness-105 text-text-onLight text-xs font-mono font-bold transition-all"
                >
                  Save Changes
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Summarize Session Modal */}
      {isSummarizeOpen && (
        <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-surface-primary border border-surface-muted/30 rounded-2xl max-w-md w-full p-6 shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-surface-muted/20 pb-3">
              <h3 className="font-bold text-base text-text-primary">Summarize Conversation Session</h3>
              <button onClick={() => setIsSummarizeOpen(false)} className="text-text-muted hover:text-text-primary">
                ✕
              </button>
            </div>

            <form onSubmit={handleSummarizeSession} className="space-y-4">
              <p className="text-xs text-text-muted leading-relaxed">
                Provide a Conversation ID to extract key insights, decisions, and store them into episodic vector memory.
              </p>

              <div>
                <label className="block text-xs font-mono font-bold text-text-muted uppercase mb-1">
                  Conversation / Session ID
                </label>
                <input
                  type="text"
                  value={sessionIdInput}
                  onChange={(e) => setSessionIdInput(e.target.value)}
                  placeholder="e.g. conv-xyz or UUID"
                  className="w-full bg-canvas-dark border border-surface-muted/30 rounded-xl px-3 py-2 text-xs text-text-primary focus:outline-none focus:border-accent-primary font-mono"
                  required
                />
              </div>

              <div className="flex justify-end gap-2 pt-3 border-t border-surface-muted/20">
                <button
                  type="button"
                  onClick={() => setIsSummarizeOpen(false)}
                  className="px-4 py-2 rounded-xl bg-canvas-dark text-text-muted text-xs font-mono font-bold"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={summarizing}
                  className="px-5 py-2 rounded-xl bg-accent-primary hover:brightness-105 text-text-onLight text-xs font-mono font-bold transition-all disabled:opacity-50"
                >
                  {summarizing ? 'Summarizing...' : 'Summarize & Index'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
