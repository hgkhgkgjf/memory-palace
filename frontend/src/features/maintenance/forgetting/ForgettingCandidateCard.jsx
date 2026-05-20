import React from 'react';
import clsx from 'clsx';
import { useTranslation } from 'react-i18next';
import { Archive, Eye, ThumbsUp, ShieldCheck, AlertTriangle, ScanSearch } from 'lucide-react';

import DecayCurve from '../shared/DecayCurve';
import Checkbox from '../shared/Checkbox';
import StatusPill from '../shared/StatusPill';
import { formatScore } from '../shared/formatters';

const formatDateTimeShort = (value, lng) => {
  if (!value) return '-';
  try {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return date.toLocaleDateString(lng || 'en');
  } catch (_error) {
    return String(value);
  }
};

const RECOMMENDATION_CATEGORY = {
  archive: 'archive',
  keep: 'keep',
  review: 'review',
};

const RECOMMENDATION_ICON = {
  archive: AlertTriangle,
  keep: ShieldCheck,
  review: ScanSearch,
};

/**
 * Single candidate card. The container is a glass card; busy state disables
 * actions and dims the row.
 *
 * @param {{
 *   candidate: import('./useForgetting').ForgettingCandidate,
 *   selected: boolean,
 *   onToggleSelect: (id: string | number) => void,
 *   onKeep: (id: string | number) => void,
 *   onArchive: (id: string | number) => void,
 *   onInspect: (id: string | number) => void,
 *   busy: boolean,
 *   busyId: string | number | null,
 *   threshold?: number,
 *   t?: (key: string, options?: object) => string,
 * }} props
 */
const ForgettingCandidateCard = ({
  candidate,
  selected,
  onToggleSelect,
  onKeep,
  onArchive,
  onInspect,
  busy,
  busyId,
  threshold,
  t: tProp,
}) => {
  const { t: tHook, i18n } = useTranslation();
  const t = tProp || tHook;

  const id = candidate.memory_id;
  const title = candidate.title || candidate.uri || t('maintenance.forgetting.unnamedMemory');
  const recommendation = candidate.recommendation || 'review';
  const category = RECOMMENDATION_CATEGORY[recommendation] || 'review';
  const RecommendationIcon = RECOMMENDATION_ICON[recommendation] || ScanSearch;

  const rowBusy = Boolean(busy);
  const thisBusy = busyId === id;

  return (
    <article
      data-testid={`forgetting-candidate-${id}`}
      className={clsx(
        'glass-card relative flex flex-col gap-3 rounded-2xl bg-white/30 p-4 transition-shadow',
        selected ? 'shadow-[var(--palace-shadow-sm)] ring-1 ring-[color:var(--palace-accent)]' : null,
        thisBusy ? 'opacity-80' : null
      )}
      style={{ borderColor: 'var(--palace-line)' }}
      aria-busy={thisBusy || undefined}
    >
      <header className="flex flex-wrap items-start gap-2">
        <Checkbox
          checked={selected}
          onChange={() => onToggleSelect(id)}
          disabled={rowBusy}
          label={t(
            selected
              ? 'maintenance.forgetting.deselectCandidate'
              : 'maintenance.forgetting.selectCandidate',
            { id, title }
          )}
        />
        <code
          className="break-all text-[11px] font-mono"
          style={{ color: 'var(--palace-accent-2)' }}
        >
          #{id}
        </code>
        <div className="ml-auto">
          <StatusPill
            category={category}
            icon={RecommendationIcon}
            label={t(`maintenance.forgetting.recommendations.${recommendation}`, {
              defaultValue: recommendation,
            })}
          />
        </div>
      </header>

      <div className="flex flex-col gap-1">
        <h3
          className="font-display text-sm font-semibold leading-snug"
          style={{ color: 'var(--palace-ink)' }}
        >
          {title}
        </h3>
        {candidate.uri ? (
          <p
            className="break-all text-[11px] font-mono"
            style={{ color: 'var(--palace-muted)' }}
          >
            {candidate.uri}
          </p>
        ) : null}
      </div>

      <dl className="grid grid-cols-3 gap-2 text-[11px]">
        <div className="flex flex-col">
          <dt style={{ color: 'var(--palace-muted)' }}>
            {t('maintenance.forgetting.currentScore')}
          </dt>
          <dd
            className="font-mono text-sm font-semibold"
            style={{ color: 'var(--palace-ink)' }}
          >
            {formatScore(candidate.current_score)}
          </dd>
        </div>
        <div className="flex flex-col">
          <dt style={{ color: 'var(--palace-muted)' }}>
            {t('maintenance.forgetting.projectedScore')}
          </dt>
          <dd
            className="font-mono text-sm font-semibold"
            style={{ color: 'var(--palace-accent-2)' }}
          >
            {formatScore(candidate.projected_score)}
          </dd>
        </div>
        <div className="flex flex-col">
          <dt style={{ color: 'var(--palace-muted)' }}>
            {t('maintenance.forgetting.lastAccessed')}
          </dt>
          <dd className="font-mono text-sm" style={{ color: 'var(--palace-ink)' }}>
            {formatDateTimeShort(candidate.last_accessed_at, i18n?.resolvedLanguage)}
          </dd>
        </div>
      </dl>

      <DecayCurve
        values={Array.isArray(candidate.decay_curve) ? candidate.decay_curve : []}
        width={280}
        height={56}
        thresholdValue={threshold}
        color="var(--palace-accent)"
        label={t('maintenance.forgetting.decayChartLabel', { id })}
        className="w-full"
      />

      {candidate.reason ? (
        <div
          className="text-[10px] uppercase tracking-[0.14em]"
          style={{ color: 'var(--palace-muted)' }}
        >
          {t('maintenance.forgetting.reason', { value: candidate.reason })}
        </div>
      ) : null}

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => onKeep(id)}
          disabled={rowBusy}
          data-testid={`forgetting-keep-${id}`}
          className="palace-btn-ghost text-[11px]"
        >
          <ThumbsUp size={12} strokeWidth={2} aria-hidden="true" />
          {t('maintenance.forgetting.keep')}
        </button>
        <button
          type="button"
          onClick={() => onArchive(id)}
          disabled={rowBusy}
          data-testid={`forgetting-archive-${id}`}
          className="inline-flex cursor-pointer items-center gap-1 rounded-lg border px-2.5 py-1 text-[11px] font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-45 focus:outline-none focus:ring-2"
          style={{
            background: 'rgba(244, 236, 224, 0.9)',
            borderColor: 'rgba(200, 171, 134, 0.65)',
            color: 'var(--palace-accent-2)',
          }}
        >
          <Archive size={12} strokeWidth={2} aria-hidden="true" />
          {t('maintenance.forgetting.archive')}
        </button>
        <button
          type="button"
          onClick={() => onInspect(id)}
          disabled={rowBusy}
          data-testid={`forgetting-inspect-${id}`}
          className="palace-btn-ghost text-[11px]"
        >
          <Eye size={12} strokeWidth={2} aria-hidden="true" />
          {t('maintenance.forgetting.inspect')}
        </button>
      </div>
    </article>
  );
};

export default ForgettingCandidateCard;
