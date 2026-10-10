/**
 * frontend/src/components/ConnectionStatusBadge.tsx
 * Real-time SSE / API connection state badge (Connected / Reconnecting / Offline).
 */

import React from 'react';
import { ConnectionStatus } from '../api/client';

interface ConnectionStatusBadgeProps {
  status: ConnectionStatus;
}

export const ConnectionStatusBadge: React.FC<ConnectionStatusBadgeProps> = ({ status }) => {
  const configs = {
    connected: {
      dot: 'bg-emerald-500 animate-pulse',
      text: 'Connected',
      classes: 'bg-emerald-50 text-emerald-800 border-emerald-300',
    },
    reconnecting: {
      dot: 'bg-amber-500 animate-ping',
      text: 'Reconnecting...',
      classes: 'bg-amber-50 text-amber-800 border-amber-300',
    },
    offline: {
      dot: 'bg-rose-500',
      text: 'Offline',
      classes: 'bg-rose-50 text-rose-800 border-rose-300',
    },
  };

  const current = configs[status] || configs.offline;

  return (
    <div
      className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-mono border font-medium transition-all ${current.classes}`}
      title={`Real-time SSE Connection: ${current.text}`}
    >
      <span className={`w-2 h-2 rounded-full ${current.dot}`} />
      <span>{current.text}</span>
    </div>
  );
};
