import React, { useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { Archive, Loader2, Trash2 } from 'lucide-react';
import EmptyState from '../shared/EmptyState';
import ErrorBanner from '../shared/ErrorBanner';
import LoadingPulse from '../shared/LoadingPulse';
import SectionCard from '../shared/SectionCard';
import SelectionBar from '../shared/SelectionBar';
import { CATEGORY_COLORS } from '../shared/palette';
import { useReducedMotion } from '../shared/useReducedMotion';
import OrphanList from './OrphanList';
import OrphanToolbar from './OrphanToolbar';
import useOrphans from './useOrphans';

/**
 * @param {{
 *   onStatsChange?: (stats: { deprecated?: number, orphaned?: number }) => void,
 *   registerReload?: (reload: (() => Promise<void>) | null) => void,
 * }} props
 */
export default function OrphanPanel({ onStatsChange, registerReload }) {
  const { t } = useTranslation();
  const reducedMotion = useReducedMotion();
  const {
    orphans,
    deprecated,
    orphaned,
    loading,
    error,
    expandedId,
    detailData,
    detailLoading,
    selectedIds,
    batchDeleting,
    orphanActionMessage,
    loadOrphans,
    handleExpand,
    toggleSelect,
    toggleSelectAll,
    handleBatchDelete,
    clearSelection,
  } = useOrphans();

  const selectedCount = selectedIds.size;
  const orphanedPalette = CATEGORY_COLORS.orphaned;

  useEffect(() => {
    if (typeof registerReload !== 'function') return undefined;
    registerReload(loadOrphans);
    return () => registerReload(null);
  }, [loadOrphans, registerReload]);

  useEffect(() => {
    if (typeof onStatsChange === 'function') {
      onStatsChange({
        deprecated: deprecated.length,
        orphaned: orphaned.length,
      });
    }
  }, [deprecated.length, onStatsChange, orphaned.length]);

  const renderBody = () => {
    if (loading) {
      return (
        <div className="space-y-4" aria-live="polite">
          <div
            className="flex items-center gap-2 text-xs"
            style={{ color: 'var(--palace-muted)' }}
          >
            <Loader2
              size={14}
              aria-hidden="true"
              className={reducedMotion ? '' : 'animate-spin'}
              style={{ color: 'var(--palace-accent)' }}
            />
            <span>{t('maintenance.scanningOrphans')}</span>
          </div>
          <LoadingPulse lines={4} />
        </div>
      );
    }

    if (error) {
      return (
        <ErrorBanner
          message={error}
          retryLabel={t('maintenance.shared.retry')}
          onRetry={loadOrphans}
        />
      );
    }

    if (orphans.length === 0) {
      return (
        <EmptyState
          icon={Archive}
          title={t('maintenance.tabs.orphans')}
          description={t('maintenance.noOrphans')}
          action={{
            label: t('maintenance.refresh'),
            onClick: loadOrphans,
          }}
        />
      );
    }

    return (
      <OrphanList
        deprecated={deprecated}
        orphaned={orphaned}
        selectedIds={selectedIds}
        expandedId={expandedId}
        detailData={detailData}
        detailLoading={detailLoading}
        onToggleSelect={toggleSelect}
        onToggleSelectAll={toggleSelectAll}
        onExpand={handleExpand}
        t={t}
      />
    );
  };

  return (
    <>
      <SectionCard>
        <OrphanToolbar
          selectedCount={selectedCount}
          totalCount={orphans.length}
          onDelete={handleBatchDelete}
          onRefresh={loadOrphans}
          deleting={batchDeleting}
          loading={loading}
        />

        {orphanActionMessage ? (
          <div
            role="alert"
            className="mb-4 rounded-xl border px-4 py-3 text-sm"
            style={{
              background: 'rgba(184, 150, 46, 0.10)',
              borderColor: 'rgba(184, 150, 46, 0.28)',
              color: 'var(--palace-ink)',
            }}
          >
            {orphanActionMessage}
          </div>
        ) : null}

        {renderBody()}
      </SectionCard>

      <SelectionBar
        count={selectedCount}
        onClear={clearSelection}
        clearLabel={t('maintenance.shared.clearSelection')}
        ariaLabel={t('maintenance.orphan.selectionRegion')}
        countLabel={t('maintenance.shared.selected', { count: selectedCount })}
      >
        <button
          type="button"
          onClick={handleBatchDelete}
          disabled={batchDeleting}
          className="inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-medium transition disabled:cursor-not-allowed disabled:opacity-60"
          style={{
            background: orphanedPalette.bg,
            borderColor: orphanedPalette.border,
            color: orphanedPalette.text,
          }}
        >
          {batchDeleting ? (
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
      </SelectionBar>
    </>
  );
}
