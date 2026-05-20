import React from 'react';
import { AlertTriangle, Archive, RefreshCw, ThumbsUp } from 'lucide-react';

/**
 * Top toolbar above the candidate queue: refresh + mock badge + batch actions.
 *
 * @param {{
 *   loading: boolean,
 *   busy: boolean,
 *   isMock: boolean,
 *   selectedCount: number,
 *   onRefresh: () => void,
 *   onBatchKeep: () => void,
 *   onBatchArchive: () => void,
 *   t: (key: string, options?: object) => string,
 * }} props
 */
const ForgettingToolbar = ({
  loading,
  busy,
  isMock,
  selectedCount,
  onRefresh,
  onBatchKeep,
  onBatchArchive,
  t,
}) => {
  const hasSelection = selectedCount > 0;

  return (
    <div
      className="flex flex-wrap items-center gap-2"
      role="toolbar"
      aria-label={t('maintenance.forgetting.title')}
    >
      {isMock ? (
        <span
          data-testid="forgetting-mock-badge"
          className="inline-flex items-center gap-1 rounded-full border px-3 py-1 text-[11px] font-medium"
          style={{
            background: 'rgba(244, 236, 224, 0.92)',
            borderColor: 'rgba(200, 171, 134, 0.65)',
            color: 'var(--palace-accent-2)',
          }}
        >
          <AlertTriangle size={12} strokeWidth={2} aria-hidden="true" />
          {t('maintenance.forgetting.mockBadge')}
        </span>
      ) : null}

      {hasSelection ? (
        <span
          className="text-[11px] font-medium"
          style={{ color: 'var(--palace-muted)' }}
        >
          {t('maintenance.forgetting.selectedCount', { count: selectedCount })}
        </span>
      ) : null}

      {hasSelection ? (
        <button
          type="button"
          onClick={onBatchKeep}
          disabled={busy}
          data-testid="forgetting-batch-keep"
          className="palace-btn-ghost text-[11px]"
        >
          <ThumbsUp size={12} strokeWidth={2} aria-hidden="true" />
          {t('maintenance.forgetting.batchKeep')}
        </button>
      ) : null}

      {hasSelection ? (
        <button
          type="button"
          onClick={onBatchArchive}
          disabled={busy}
          data-testid="forgetting-batch-archive"
          className="inline-flex cursor-pointer items-center gap-1 rounded-lg border px-2.5 py-1 text-[11px] font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-45 focus:outline-none focus:ring-2"
          style={{
            background: 'rgba(244, 236, 224, 0.9)',
            borderColor: 'rgba(200, 171, 134, 0.65)',
            color: 'var(--palace-accent-2)',
          }}
        >
          <Archive size={12} strokeWidth={2} aria-hidden="true" />
          {t('maintenance.forgetting.batchArchive')}
        </button>
      ) : null}

      <button
        type="button"
        onClick={onRefresh}
        disabled={loading || busy}
        data-testid="forgetting-refresh"
        className="palace-btn-ghost"
      >
        <RefreshCw
          size={14}
          strokeWidth={2}
          className={loading ? 'animate-spin' : undefined}
          aria-hidden="true"
        />
        {t('maintenance.forgetting.refresh')}
      </button>
    </div>
  );
};

export default ForgettingToolbar;
