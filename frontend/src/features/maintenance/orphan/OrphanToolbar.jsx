import React from 'react';
import { useTranslation } from 'react-i18next';
import { Archive, Loader2, RefreshCw, Trash2 } from 'lucide-react';
import clsx from 'clsx';
import { CATEGORY_COLORS } from '../shared/palette';
import { useReducedMotion } from '../shared/useReducedMotion';

/**
 * @param {{
 *   selectedCount: number,
 *   totalCount: number,
 *   onDelete: () => void,
 *   onRefresh: () => void,
 *   deleting: boolean,
 *   loading: boolean,
 * }} props
 */
export default function OrphanToolbar({
  selectedCount,
  totalCount,
  onDelete,
  onRefresh,
  deleting,
  loading,
}) {
  const { t } = useTranslation();
  const reducedMotion = useReducedMotion();
  const orphanedPalette = CATEGORY_COLORS.orphaned;
  const hasSelection = selectedCount > 0;

  return (
    <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
      <div className="flex items-center gap-2">
        <h3
          className="flex items-center gap-2 text-xs font-bold uppercase tracking-widest"
          style={{ color: 'var(--palace-ink)' }}
        >
          <Archive
            size={14}
            aria-hidden="true"
            style={{ color: 'var(--palace-accent)' }}
          />
          {t('maintenance.orphanCleanup')}
        </h3>
        <span
          className="rounded-full px-2 py-0.5 text-[11px]"
          style={{
            background: 'rgba(255, 255, 255, 0.55)',
            color: 'var(--palace-muted)',
            border: '1px solid var(--palace-line)',
          }}
        >
          {t('maintenance.total', { count: totalCount })}
        </span>
      </div>

      <div className="flex items-center gap-2">
        {hasSelection ? (
          <button
            type="button"
            onClick={onDelete}
            disabled={deleting}
            className={clsx(
              'inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-medium transition',
              'disabled:cursor-not-allowed disabled:opacity-60'
            )}
            style={{
              background: orphanedPalette.bg,
              borderColor: orphanedPalette.border,
              color: orphanedPalette.text,
            }}
          >
            {deleting ? (
              <Loader2
                size={13}
                aria-hidden="true"
                className={reducedMotion ? '' : 'animate-spin'}
                style={{ color: orphanedPalette.icon }}
              />
            ) : (
              <Trash2
                size={13}
                aria-hidden="true"
                style={{ color: orphanedPalette.icon }}
              />
            )}
            {t('maintenance.deleteOrphans', { count: selectedCount })}
          </button>
        ) : null}

        <button
          type="button"
          onClick={onRefresh}
          disabled={loading || deleting}
          className="palace-btn-ghost disabled:cursor-not-allowed disabled:opacity-60"
          aria-label={t('maintenance.refresh')}
          title={t('maintenance.refresh')}
        >
          <RefreshCw
            size={14}
            aria-hidden="true"
            className={loading && !reducedMotion ? 'animate-spin' : ''}
          />
          <span className="sr-only">{t('maintenance.refresh')}</span>
        </button>
      </div>
    </div>
  );
}
