import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Activity, AlertTriangle, CheckCircle2, RefreshCw, Trash2 } from 'lucide-react';
import SectionCard from '../shared/SectionCard';
import EmptyState from '../shared/EmptyState';
import ErrorBanner from '../shared/ErrorBanner';
import LoadingPulse from '../shared/LoadingPulse';
import SelectionBar from '../shared/SelectionBar';
import ConfirmPhraseModal from '../shared/ConfirmPhraseModal';
import VitalityFiltersForm from './VitalityFiltersForm';
import VitalityActions from './VitalityActions';
import VitalityReviewBanner from './VitalityReviewBanner';
import VitalityCandidateTable from './VitalityCandidateTable';
import useVitality from './useVitality';

/**
 * @param {{
 *   reloadOrphans?: () => Promise<void> | void,
 *   onStatsChange?: (stats: { lowVitality?: number, lowVitalityActionable?: number }) => void,
 * }} props
 */
const VitalityPanel = ({ reloadOrphans, onStatsChange }) => {
  const { t } = useTranslation();
  const vitality = useVitality({ reloadOrphans });
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [confirmSubmitting, setConfirmSubmitting] = useState(false);
  const confirmSubmittingRef = useRef(false);

  const {
    candidates,
    loading,
    error,
    queryMeta,
    lastResult,
    selectedIds,
    processing,
    preparedReview,
    filters,
    setters,
    selectedCount,
    canDeleteCount,
    selectedCanDelete,
    loadCandidates,
    toggleSelect,
    toggleSelectAll,
    clearSelection,
    prepareKeep,
    prepareDelete,
    confirmCleanup,
    invalidatePreparedReview,
    translateAction,
  } = vitality;

  const refreshDisabled = loading || processing;
  const preparedReviewCount =
    preparedReview?.selection_count
    ?? (preparedReview?.action === 'delete' ? selectedCanDelete : selectedCount);

  useEffect(() => {
    if (typeof onStatsChange === 'function') {
      onStatsChange({
        lowVitality: candidates.length,
        lowVitalityActionable: canDeleteCount,
      });
    }
  }, [canDeleteCount, candidates.length, onStatsChange]);

  const handleApplyFilters = useCallback(() => {
    void loadCandidates();
  }, [loadCandidates]);

  const handleRunDecay = useCallback(() => {
    void loadCandidates({ forceDecay: true });
  }, [loadCandidates]);

  const handleConfirmClick = useCallback(() => {
    if (!preparedReview) return;
    setConfirmOpen(true);
  }, [preparedReview]);

  const handleConfirmModalSubmit = useCallback(async (typedPhrase) => {
    if (!preparedReview || confirmSubmittingRef.current) return;
    confirmSubmittingRef.current = true;
    setConfirmSubmitting(true);
    try {
      const succeeded = await confirmCleanup(typedPhrase);
      if (succeeded) {
        setConfirmOpen(false);
      } else {
        setConfirmOpen(false);
      }
    } finally {
      confirmSubmittingRef.current = false;
      setConfirmSubmitting(false);
    }
  }, [confirmCleanup, preparedReview]);

  const handleConfirmModalCancel = useCallback(() => {
    if (confirmSubmitting) return;
    setConfirmOpen(false);
  }, [confirmSubmitting]);

  const renderBody = () => {
    if (loading) {
      return (
        <div className="py-2" aria-live="polite">
          <LoadingPulse lines={4} />
          <p
            className="mt-3 text-xs"
            style={{ color: 'var(--palace-muted)' }}
          >
            {t('maintenance.vitality.loading')}
          </p>
        </div>
      );
    }

    if (error) {
      return (
        <ErrorBanner
          message={typeof error === 'string' ? error : String(error)}
          onRetry={() => void loadCandidates()}
          retryLabel={t('maintenance.shared.retry')}
        />
      );
    }

    if (candidates.length === 0) {
      return (
        <EmptyState
          icon={Activity}
          title={t('maintenance.vitality.noCandidates')}
          description={t('maintenance.vitality.title')}
          action={{
            label: t('maintenance.vitality.runDecay'),
            onClick: handleRunDecay,
          }}
        />
      );
    }

    return (
      <VitalityCandidateTable
        candidates={candidates}
        selectedIds={selectedIds}
        onToggleSelect={toggleSelect}
        onToggleSelectAll={toggleSelectAll}
        disabled={processing}
      />
    );
  };

  return (
    <>
      <SectionCard className="space-y-4" data-testid="vitality-panel">
        <header className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2
              className="font-display flex items-center gap-2 text-base font-semibold"
              style={{ color: 'var(--palace-ink)' }}
            >
              <Trash2
                size={16}
                strokeWidth={2}
                style={{ color: 'var(--palace-accent)' }}
                aria-hidden="true"
              />
              {t('maintenance.vitality.title')}
            </h2>
            <p
              className="mt-1 max-w-prose text-xs"
              style={{ color: 'var(--palace-muted)' }}
            >
              {t('maintenance.subtitle')}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={handleRunDecay}
              disabled={refreshDisabled}
              className="palace-btn-ghost"
              data-testid="vitality-run-decay"
            >
              <RefreshCw
                size={14}
                strokeWidth={2}
                className={loading ? 'animate-spin' : ''}
                aria-hidden="true"
              />
              {t('maintenance.vitality.runDecay')}
            </button>
          </div>
        </header>

        <VitalityFiltersForm
          filters={filters}
          setters={setters}
          onApply={handleApplyFilters}
          onInvalidate={invalidatePreparedReview}
          disabled={processing}
        />

        <VitalityActions
          selectedCount={selectedCount}
          canDeleteCount={canDeleteCount}
          selectedCanDelete={selectedCanDelete}
          processing={processing}
          preparedReview={preparedReview}
          onPrepareKeep={prepareKeep}
          onPrepareDelete={prepareDelete}
          onConfirm={handleConfirmClick}
          onDiscard={invalidatePreparedReview}
          translateAction={translateAction}
        />

        {preparedReview ? (
          <VitalityReviewBanner
            review={preparedReview}
            translateAction={translateAction}
          />
        ) : null}

        {queryMeta?.status === 'degraded' ? (
          <div
            role="status"
            aria-live="polite"
            className="flex items-start gap-2 rounded-xl border px-3 py-2 text-xs"
            style={{
              background: 'rgba(212, 175, 55, 0.08)',
              borderColor: 'rgba(212, 175, 55, 0.3)',
              color: 'var(--palace-accent-2)',
            }}
          >
            <AlertTriangle
              size={14}
              strokeWidth={2}
              className="mt-0.5 shrink-0"
              aria-hidden="true"
            />
            <div>
              <div>{t('maintenance.vitality.degradedStatus')}</div>
              <div>
                {t('maintenance.vitality.reason', {
                  value: queryMeta?.decay?.reason || t('common.states.unknown'),
                })}
              </div>
            </div>
          </div>
        ) : null}

        {lastResult ? (
          <div
            role="status"
            aria-live="polite"
            className="flex items-start gap-2 rounded-xl border px-3 py-2 text-xs"
            style={{
              background: 'rgba(94, 127, 163, 0.08)',
              borderColor: 'rgba(94, 127, 163, 0.25)',
              color: '#5e7fa3',
            }}
          >
            <CheckCircle2
              size={14}
              strokeWidth={2}
              className="mt-0.5 shrink-0"
              aria-hidden="true"
            />
            <div>
              <div>{t('maintenance.vitality.status', { value: lastResult.status })}</div>
              <div>
                {t('maintenance.vitality.resultSummary', {
                  deleted: lastResult.deleted_count,
                  kept: lastResult.kept_count,
                  skipped: lastResult.skipped_count,
                  errors: lastResult.error_count,
                })}
              </div>
            </div>
          </div>
        ) : null}

        {renderBody()}
      </SectionCard>

      <SelectionBar
        count={selectedCount}
        onClear={clearSelection}
        clearLabel={t('maintenance.shared.clearSelection')}
        ariaLabel={t('maintenance.vitality.selectionRegion')}
        countLabel={t('maintenance.shared.selected', { count: selectedCount })}
      >
        <span className="text-xs" style={{ color: 'var(--palace-muted)' }}>
          {t('maintenance.shared.selectionSummary', {
            selected: selectedCount,
            actionable: selectedCanDelete,
          })}
        </span>
        <button
          type="button"
          onClick={prepareKeep}
          disabled={processing || selectedCount === 0}
          className="palace-btn-ghost"
        >
          {t('maintenance.vitality.prepareKeep', { count: selectedCount })}
        </button>
        <button
          type="button"
          onClick={prepareDelete}
          disabled={processing || selectedCanDelete === 0}
          className="palace-btn-primary"
        >
          {t('maintenance.vitality.prepareDelete', { count: selectedCanDelete })}
        </button>
      </SelectionBar>

      <ConfirmPhraseModal
        open={confirmOpen && Boolean(preparedReview)}
        title={t('maintenance.vitality.confirmModal.title')}
        description={t('maintenance.vitality.confirmModal.body', {
          action: translateAction(preparedReview?.action),
          count: preparedReviewCount,
        })}
        phrase={preparedReview?.confirmation_phrase || ''}
        phrasePrompt={t('maintenance.vitality.confirmModal.phrasePrompt')}
        confirmLabel={t('maintenance.vitality.confirmModal.confirm')}
        cancelLabel={t('maintenance.vitality.confirmModal.cancel')}
        onConfirm={handleConfirmModalSubmit}
        onCancel={handleConfirmModalCancel}
        destructive={preparedReview?.action !== 'keep'}
        submitting={confirmSubmitting}
      />
    </>
  );
};

export default VitalityPanel;
