import React from 'react';
import { useTranslation } from 'react-i18next';
import { Check, ShieldCheck, Trash2, X } from 'lucide-react';

/**
 * @param {{
 *   selectedCount: number,
 *   canDeleteCount: number,
 *   selectedCanDelete: number,
 *   processing: boolean,
 *   preparedReview: import('./useVitality').VitalityPreparedReviewState | null,
 *   onPrepareKeep: () => void,
 *   onPrepareDelete: () => void,
 *   onConfirm: () => void,
 *   onDiscard: () => void,
 *   translateAction: (action: string | undefined | null) => string,
 * }} props
 */
const VitalityActions = ({
  selectedCount,
  canDeleteCount,
  selectedCanDelete,
  processing,
  preparedReview,
  onPrepareKeep,
  onPrepareDelete,
  onConfirm,
  onDiscard,
  translateAction,
}) => {
  const { t } = useTranslation();

  const keepDisabled = processing || selectedCount === 0;
  const deleteDisabled = processing || selectedCanDelete === 0;
  const confirmDisabled = processing || !preparedReview;

  return (
    <div
      role="toolbar"
      aria-label={t('maintenance.vitality.title')}
      className="flex flex-wrap items-center gap-2"
    >
      <button
        type="button"
        onClick={onPrepareKeep}
        disabled={keepDisabled}
        aria-disabled={keepDisabled}
        className="palace-btn-ghost"
        style={
          keepDisabled
            ? undefined
            : {
                color: '#5e7fa3',
                background: 'rgba(94, 127, 163, 0.08)',
                borderColor: 'rgba(94, 127, 163, 0.25)',
              }
        }
      >
        <ShieldCheck size={14} strokeWidth={2} aria-hidden="true" />
        {t('maintenance.vitality.prepareKeep', { count: selectedCount })}
      </button>

      <button
        type="button"
        onClick={onPrepareDelete}
        disabled={deleteDisabled}
        aria-disabled={deleteDisabled}
        className="palace-btn-ghost"
        style={
          deleteDisabled
            ? undefined
            : {
                color: 'var(--palace-accent-2)',
                background: 'rgba(212, 175, 55, 0.1)',
                borderColor: 'rgba(212, 175, 55, 0.32)',
              }
        }
      >
        <Trash2 size={14} strokeWidth={2} aria-hidden="true" />
        {t('maintenance.vitality.prepareDelete', { count: selectedCanDelete })}
      </button>

      <button
        type="button"
        onClick={onConfirm}
        disabled={confirmDisabled}
        aria-disabled={confirmDisabled}
        className="palace-btn-primary"
      >
        <Check size={14} strokeWidth={2} aria-hidden="true" />
        {t('maintenance.vitality.confirmAction', {
          action: translateAction(preparedReview?.action),
        })}
      </button>

      {preparedReview ? (
        <button
          type="button"
          onClick={onDiscard}
          disabled={processing}
          className="palace-btn-ghost"
        >
          <X size={14} strokeWidth={2} aria-hidden="true" />
          {t('maintenance.vitality.discardReview')}
        </button>
      ) : null}

      <span
        className="ml-auto text-xs"
        style={{ color: 'var(--palace-muted)' }}
        aria-live="polite"
      >
        {t('maintenance.vitality.selectionSummary', {
          selected: selectedCount,
          deletable: selectedCanDelete,
        })}
        {canDeleteCount > 0 ? (
          <span className="ml-2 text-[11px] opacity-75">
            {' '}
            ({t('maintenance.stats.lowVitalityHint', { count: canDeleteCount })})
          </span>
        ) : null}
      </span>
    </div>
  );
};

export default VitalityActions;
