import React from 'react';
import { useTranslation } from 'react-i18next';
import { ClipboardCheck } from 'lucide-react';

/**
 * @param {{
 *   review: import('./useVitality').VitalityPreparedReviewState,
 *   translateAction: (action: string | undefined | null) => string,
 * }} props
 */
const VitalityReviewBanner = ({ review, translateAction }) => {
  const { t } = useTranslation();
  if (!review) return null;

  return (
    <section
      role="status"
      aria-live="polite"
      className="glass-card rounded-2xl border p-4"
      style={{
        background: 'rgba(212, 175, 55, 0.08)',
        borderColor: 'rgba(212, 175, 55, 0.3)',
      }}
      data-testid="vitality-review-banner"
    >
      <header className="mb-3 flex items-center gap-2">
        <ClipboardCheck
          size={16}
          strokeWidth={2}
          style={{ color: 'var(--palace-accent)' }}
          aria-hidden="true"
        />
        <h4
          className="font-display text-sm font-semibold"
          style={{ color: 'var(--palace-ink)' }}
        >
          {t('maintenance.vitality.confirmModal.title')}
        </h4>
      </header>

      <dl
        className="grid grid-cols-1 gap-2 text-xs sm:grid-cols-2"
        style={{ color: 'var(--palace-ink)' }}
      >
        <div>
          <dt
            className="text-[10px] font-medium uppercase tracking-wider"
            style={{ color: 'var(--palace-muted)' }}
          >
            review_id
          </dt>
          <dd className="break-all font-mono">
            {t('maintenance.vitality.reviewId', { value: review.review_id })}
          </dd>
        </div>
        <div>
          <dt
            className="text-[10px] font-medium uppercase tracking-wider"
            style={{ color: 'var(--palace-muted)' }}
          >
            action
          </dt>
          <dd className="font-mono">
            {t('maintenance.vitality.action', {
              value: translateAction(review.action),
            })}
          </dd>
        </div>
        <div>
          <dt
            className="text-[10px] font-medium uppercase tracking-wider"
            style={{ color: 'var(--palace-muted)' }}
          >
            reviewer
          </dt>
          <dd className="break-all font-mono">
            {t('maintenance.vitality.reviewerValue', { value: review.reviewer })}
          </dd>
        </div>
        <div>
          <dt
            className="text-[10px] font-medium uppercase tracking-wider"
            style={{ color: 'var(--palace-muted)' }}
          >
            confirmation_phrase
          </dt>
          <dd
            className="break-all rounded-md px-2 py-1 font-mono"
            style={{
              background: 'rgba(255, 255, 255, 0.55)',
              color: 'var(--palace-accent-2)',
              border: '1px solid var(--palace-line)',
            }}
          >
            {t('maintenance.vitality.confirmationPhrase', {
              value: review.confirmation_phrase,
            })}
          </dd>
        </div>
      </dl>
    </section>
  );
};

export default VitalityReviewBanner;
