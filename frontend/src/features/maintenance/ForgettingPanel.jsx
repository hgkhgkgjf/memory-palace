import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import clsx from 'clsx';
import { useTranslation } from 'react-i18next';
import {
  AlertTriangle,
  Archive,
  CheckSquare,
  Eye,
  RefreshCw,
  Shield,
  Square,
  ThumbsUp,
  TrendingDown,
} from 'lucide-react';

import {
  confirmForgettingArchive,
  getForgettingCandidates,
  prepareForgettingArchive,
  simulateForgettingDecay,
} from '../../lib/api';
import { confirmWithFallback, promptWithFallback } from '../../lib/dialogs';

const PANEL_CLASS =
  'rounded-2xl border border-[color:var(--palace-line)] bg-[rgba(255,250,244,0.9)] p-4 shadow-[var(--palace-shadow-sm)] backdrop-blur-sm';

const DECAY_CHART_WIDTH = 280;
const DECAY_CHART_HEIGHT = 60;

/**
 * @typedef {{
 *   memory_id: string | number,
 *   title?: string | null,
 *   uri?: string | null,
 *   current_score: number,
 *   projected_score: number,
 *   last_accessed_at?: string | null,
 *   recommendation?: 'archive' | 'keep' | 'review' | string,
 *   decay_curve?: number[] | null,
 *   reason?: string | null,
 * }} ForgettingCandidate
 *
 * @typedef {{
 *   timestamp?: string | null,
 *   threshold?: number | null,
 *   total_candidates?: number,
 *   projected_archived?: number,
 *   projected_retained?: number,
 *   simulation_days?: number,
 *   is_mock?: boolean | null,
 * }} ForgettingSimulation
 */

const createMockSimulation = (days) => ({
  timestamp: new Date().toISOString(),
  threshold: 0.35,
  total_candidates: 42,
  projected_archived: 18,
  projected_retained: 24,
  simulation_days: days,
  is_mock: true,
});

/**
 * @param {number} threshold
 * @param {(key: string, options?: object) => string} t
 * @returns {ForgettingCandidate[]}
 */
const createMockCandidates = (threshold, t) => {
  const sources = [
    { id: 1001, uri: 'core://agent/stale_notes/release-rollback', title: t('maintenance.forgetting.mock.candidate1Title') },
    { id: 1002, uri: 'core://research/ml_papers/decay-models', title: t('maintenance.forgetting.mock.candidate2Title') },
    { id: 1003, uri: 'core://meeting/2026-01-17', title: t('maintenance.forgetting.mock.candidate3Title') },
    { id: 1004, uri: 'core://snippets/legacy-shell', title: t('maintenance.forgetting.mock.candidate4Title') },
    { id: 1005, uri: 'core://misc/old-draft', title: t('maintenance.forgetting.mock.candidate5Title') },
  ];
  return sources.map((s, idx) => {
    const current = Math.max(0.05, threshold - 0.05 - idx * 0.04);
    const projected = Math.max(0.0, current - 0.08 - idx * 0.01);
    return {
      memory_id: s.id,
      title: s.title,
      uri: s.uri,
      current_score: current,
      projected_score: projected,
      last_accessed_at: new Date(Date.now() - (idx + 5) * 86400000).toISOString(),
      recommendation: projected < 0.1 ? 'archive' : 'review',
      decay_curve: [
        current + 0.12,
        current + 0.08,
        current + 0.04,
        current,
        projected,
      ],
      reason: idx === 0 ? 'stale_for_60d' : 'low_access_rate',
    };
  });
};

const decayCurveValues = (curve) => {
  if (!Array.isArray(curve)) return null;
  const values = curve
    .map((point) => (Array.isArray(point) ? point[1] : point))
    .filter((value) => Number.isFinite(Number(value)))
    .map(Number);
  return values.length >= 2 ? values : null;
};

const normalizeSimulationPayload = (raw, days, threshold) => {
  if (!raw || typeof raw !== 'object') return createMockSimulation(days);
  const simulations = Array.isArray(raw.simulations) ? raw.simulations : [];
  const projectedArchived =
    raw.projected_archived ??
    simulations.filter((item) => Number(item?.projected_score) < threshold).length;
  const total = raw.total_candidates ?? raw.count ?? simulations.length;
  return {
    ...raw,
    threshold: raw.threshold ?? threshold,
    total_candidates: total,
    projected_archived: projectedArchived,
    projected_retained: raw.projected_retained ?? Math.max(0, total - projectedArchived),
    simulation_days: raw.simulation_days ?? raw.days_forward ?? days,
    simulations,
  };
};

const normalizeCandidatePayload = (candidate, simulation) => {
  if (!candidate || typeof candidate !== 'object') return candidate;
  const currentScore = candidate.current_score ?? simulation?.current_score ?? 0;
  const projectedScore = candidate.projected_score ?? simulation?.projected_score ?? currentScore;
  return {
    ...candidate,
    current_score: currentScore,
    projected_score: projectedScore,
    last_accessed_at: candidate.last_accessed_at ?? simulation?.last_accessed_at ?? null,
    days_forward: candidate.days_forward ?? simulation?.days_forward ?? null,
    recommendation: candidate.recommendation ?? 'review',
    decay_curve:
      decayCurveValues(candidate.decay_curve) ??
      decayCurveValues(simulation?.decay_curve) ??
      [currentScore, projectedScore],
  };
};

const formatScore = (value) => {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '-';
  return Number(value).toFixed(3);
};

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

/** @param {{ data: number[] | null | undefined, color: string, label: string }} props */
function DecayChart({ data, color, label }) {
  const { t } = useTranslation();
  const values = Array.isArray(data) ? data.filter((v) => Number.isFinite(Number(v))).map(Number) : [];

  if (values.length < 2) {
    return (
      <div className="flex h-[60px] items-center justify-center rounded border border-dashed border-[color:var(--palace-line)] bg-white/30 text-[10px] text-[color:var(--palace-muted)]">
        {t('maintenance.forgetting.decayUnavailable')}
      </div>
    );
  }

  const min = Math.min(0, ...values);
  const max = Math.max(...values, 1);
  const range = max - min || 1;
  const stepX = (DECAY_CHART_WIDTH - 6) / (values.length - 1);
  const path = values
    .map((v, idx) => {
      const x = 3 + idx * stepX;
      const y = DECAY_CHART_HEIGHT - 3 - ((v - min) / range) * (DECAY_CHART_HEIGHT - 6);
      return `${idx === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`;
    })
    .join(' ');

  return (
    <svg
      role="img"
      aria-label={label}
      viewBox={`0 0 ${DECAY_CHART_WIDTH} ${DECAY_CHART_HEIGHT}`}
      className="block w-full"
      preserveAspectRatio="none"
    >
      <path d={path} fill="none" stroke={color} strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

function CandidateCard({
  candidate,
  selected,
  onToggleSelect,
  onKeep,
  onArchive,
  onInspect,
  busy,
}) {
  const { t, i18n } = useTranslation();
  const id = candidate.memory_id;
  const title = candidate.title || candidate.uri || t('maintenance.forgetting.unnamedMemory');
  const recommendation = candidate.recommendation || 'review';
  const recommendationTone =
    recommendation === 'archive' ? 'warn' : recommendation === 'keep' ? 'good' : 'neutral';

  return (
    <article
      className={clsx(
        'rounded-xl border bg-[rgba(255,250,244,0.9)] p-3 transition-colors',
        selected
          ? 'border-[color:var(--palace-accent)] shadow-[var(--palace-shadow-sm)]'
          : 'border-[color:var(--palace-line)]'
      )}
      data-testid={`forgetting-candidate-${id}`}
    >
      <header className="mb-2 flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => onToggleSelect(id)}
          disabled={busy}
          aria-label={selected ? t('maintenance.forgetting.deselect') : t('maintenance.forgetting.select')}
          className="rounded p-0.5 transition-colors hover:bg-[rgba(223,214,199,0.4)] disabled:opacity-50"
        >
          {selected ? (
            <CheckSquare size={16} className="text-[color:var(--palace-accent)]" />
          ) : (
            <Square size={16} className="text-[color:var(--palace-muted)]" />
          )}
        </button>
        <code className="break-all text-[11px] font-mono text-[color:var(--palace-accent-2)]">
          #{id}
        </code>
        <span
          className={clsx(
            'rounded border px-1.5 py-0.5 text-[10px] font-medium',
            recommendationTone === 'good' && 'border-[rgba(179,133,79,0.5)] bg-[rgba(246,237,224,0.85)] text-[color:var(--palace-accent-2)]',
            recommendationTone === 'warn' && 'border-[rgba(200,171,134,0.65)] bg-[rgba(240,230,215,0.9)] text-[color:var(--palace-accent-2)]',
            recommendationTone === 'neutral' && 'border-[color:var(--palace-line)] bg-white/70 text-[color:var(--palace-muted)]'
          )}
        >
          {t(`maintenance.forgetting.recommendations.${recommendation}`, { defaultValue: recommendation })}
        </span>
      </header>
      <div className="mb-2 text-sm font-semibold text-[color:var(--palace-ink)]">{title}</div>
      {candidate.uri && (
        <div className="mb-2 break-all text-[11px] text-[color:var(--palace-muted)]">{candidate.uri}</div>
      )}
      <dl className="mb-2 grid grid-cols-3 gap-2 text-[11px]">
        <div>
          <dt className="text-[color:var(--palace-muted)]">{t('maintenance.forgetting.currentScore')}</dt>
          <dd className="font-mono font-semibold text-[color:var(--palace-ink)]">{formatScore(candidate.current_score)}</dd>
        </div>
        <div>
          <dt className="text-[color:var(--palace-muted)]">{t('maintenance.forgetting.projectedScore')}</dt>
          <dd className="font-mono font-semibold text-[color:var(--palace-accent-2)]">{formatScore(candidate.projected_score)}</dd>
        </div>
        <div>
          <dt className="text-[color:var(--palace-muted)]">{t('maintenance.forgetting.lastAccessed')}</dt>
          <dd className="font-mono text-[color:var(--palace-ink)]">{formatDateTimeShort(candidate.last_accessed_at, i18n.resolvedLanguage)}</dd>
        </div>
      </dl>
      <DecayChart
        data={candidate.decay_curve}
        color="rgba(179,133,79,0.92)"
        label={t('maintenance.forgetting.decayChartLabel', { id })}
      />
      {candidate.reason && (
        <div className="mt-2 text-[10px] uppercase tracking-[0.14em] text-[color:var(--palace-muted)]">
          {t('maintenance.forgetting.reason', { value: candidate.reason })}
        </div>
      )}
      <div className="mt-2 flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => onKeep(id)}
          disabled={busy}
          data-testid={`forgetting-keep-${id}`}
          className="inline-flex cursor-pointer items-center gap-1 rounded border border-[color:var(--palace-line)] bg-white/90 px-2 py-1 text-[11px] text-[color:var(--palace-muted)] transition-colors hover:border-[color:var(--palace-accent)] hover:text-[color:var(--palace-ink)] disabled:cursor-not-allowed disabled:opacity-45 focus:outline-none focus:ring-2 focus:ring-[rgba(179,133,79,0.35)]"
        >
          <ThumbsUp size={12} />
          {t('maintenance.forgetting.keep')}
        </button>
        <button
          type="button"
          onClick={() => onArchive(id)}
          disabled={busy}
          data-testid={`forgetting-archive-${id}`}
          className="inline-flex cursor-pointer items-center gap-1 rounded border border-[rgba(200,171,134,0.65)] bg-[rgba(244,236,224,0.9)] px-2 py-1 text-[11px] text-[color:var(--palace-accent-2)] transition-colors hover:border-[color:var(--palace-accent)] disabled:cursor-not-allowed disabled:opacity-45 focus:outline-none focus:ring-2 focus:ring-[rgba(179,133,79,0.35)]"
        >
          <Archive size={12} />
          {t('maintenance.forgetting.archive')}
        </button>
        <button
          type="button"
          onClick={() => onInspect(id)}
          disabled={busy}
          data-testid={`forgetting-inspect-${id}`}
          className="inline-flex cursor-pointer items-center gap-1 rounded border border-[color:var(--palace-line)] bg-white/90 px-2 py-1 text-[11px] text-[color:var(--palace-muted)] transition-colors hover:border-[color:var(--palace-accent)] hover:text-[color:var(--palace-ink)] disabled:cursor-not-allowed disabled:opacity-45 focus:outline-none focus:ring-2 focus:ring-[rgba(179,133,79,0.35)]"
        >
          <Eye size={12} />
          {t('maintenance.forgetting.inspect')}
        </button>
      </div>
    </article>
  );
}

/**
 * @param {{ onInspectMemory?: (memoryId: string | number) => void }} props
 */
export default function ForgettingPanel({ onInspectMemory }) {
  const { t } = useTranslation();
  const [thresholdInput, setThresholdInput] = useState('0.35');
  const [daysInput, setDaysInput] = useState('30');
  const [candidates, setCandidates] = useState(/** @type {ForgettingCandidate[]} */ ([]));
  const [simulation, setSimulation] = useState(/** @type {ForgettingSimulation | null} */ (null));
  const [loading, setLoading] = useState(false);
  const [busyId, setBusyId] = useState(/** @type {string | number | null} */ (null));
  const [error, setError] = useState(/** @type {string | null} */ (null));
  const [message, setMessage] = useState(/** @type {string | null} */ (null));
  const [selectedIds, setSelectedIds] = useState(/** @type {Set<string | number>} */ (new Set()));
  const [isMock, setIsMock] = useState(false);

  const threshold = useMemo(() => {
    const parsed = Number(thresholdInput);
    return Number.isFinite(parsed) && parsed >= 0 && parsed <= 1 ? parsed : 0.35;
  }, [thresholdInput]);

  const days = useMemo(() => {
    const parsed = Number(daysInput);
    return Number.isFinite(parsed) && parsed > 0 ? Math.min(365, Math.floor(parsed)) : 30;
  }, [daysInput]);

  const isUnsupportedError = (err) => {
    const statusCode = err?.response?.status;
    return statusCode === 404 || statusCode === 501 || err?.code === 'ERR_NETWORK';
  };

  const cancelledRef = useRef(false);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    setMessage(null);
    try {
      const [simRes, candRes] = await Promise.allSettled([
        simulateForgettingDecay({ days }),
        getForgettingCandidates({ threshold }),
      ]);
      if (cancelledRef.current) return;
      let mock = false;
      let simulationLookup = new Map();
      if (simRes.status === 'fulfilled' && simRes.value) {
        const sim = normalizeSimulationPayload(simRes.value, days, threshold);
        setSimulation(sim);
        simulationLookup = new Map(
          (Array.isArray(sim.simulations) ? sim.simulations : [])
            .filter((item) => item?.memory_id !== undefined && item?.memory_id !== null)
            .map((item) => [String(item.memory_id), item])
        );
        if (sim?.is_mock) mock = true;
      } else if (simRes.status === 'rejected' && isUnsupportedError(simRes.reason)) {
        setSimulation(createMockSimulation(days));
        mock = true;
      } else if (simRes.status === 'rejected') {
        setSimulation(createMockSimulation(days));
        mock = true;
        setError(t('maintenance.forgetting.errors.loadSimulation'));
      }

      if (candRes.status === 'fulfilled' && Array.isArray(candRes.value?.candidates)) {
        setCandidates(
          candRes.value.candidates.map((candidate) =>
            normalizeCandidatePayload(candidate, simulationLookup.get(String(candidate?.memory_id)))
          )
        );
        if (candRes.value.is_mock) mock = true;
      } else if (candRes.status === 'rejected' && isUnsupportedError(candRes.reason)) {
        setCandidates(createMockCandidates(threshold, t));
        mock = true;
      } else if (candRes.status === 'rejected') {
        setCandidates(createMockCandidates(threshold, t));
        mock = true;
        setError(t('maintenance.forgetting.errors.loadCandidates'));
      } else if (candRes.status === 'fulfilled') {
        // Server returned no candidates field - fall back to empty list.
        setCandidates([]);
      }

      setIsMock(mock);
      setSelectedIds(new Set());
    } finally {
      if (!cancelledRef.current) setLoading(false);
    }
  }, [days, threshold, t]);

  useEffect(() => {
    cancelledRef.current = false;
    void loadData();
    return () => {
      cancelledRef.current = true;
    };
  }, [loadData]);

  const toggleSelect = useCallback((id) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const handleKeep = useCallback(
    async (id) => {
      setBusyId(id);
      setMessage(null);
      try {
        setMessage(t('maintenance.forgetting.messages.kept', { id }));
        setCandidates((prev) => prev.filter((c) => c.memory_id !== id));
        setSelectedIds((prev) => {
          const next = new Set(prev);
          next.delete(id);
          return next;
        });
      } catch (_err) {
        setMessage(t('maintenance.forgetting.messages.keepFailed', { id }));
      } finally {
        setBusyId(null);
      }
    },
    [t]
  );

  const performArchive = useCallback(
    async (ids) => {
      if (!ids.length) return;
      const phrase = t('maintenance.forgetting.confirmArchive', { count: ids.length });
      const confirmResult = confirmWithFallback(phrase);
      if (!confirmResult.available) {
        setMessage(t('maintenance.errors.confirmUnavailable'));
        return;
      }
      if (!confirmResult.confirmed) return;

      setBusyId(ids.length === 1 ? ids[0] : 'batch');
      setMessage(null);
      try {
        const preparePayload = await prepareForgettingArchive({
          memory_ids: ids,
          threshold,
          days,
          archive_reason: 'maintenance_dashboard',
          archived_by: 'dashboard',
        });
        const review = preparePayload?.review || {};
        const confirmationPhrase = String(review.confirmation_phrase || '');
        if (!review.review_id || !review.token || !confirmationPhrase) {
          setMessage(t('maintenance.forgetting.messages.archiveFailed', { count: ids.length }));
          return;
        }
        const promptResult = promptWithFallback(
          t('maintenance.forgetting.executeArchive', { phrase: confirmationPhrase })
        );
        if (!promptResult.available) {
          setMessage(t('maintenance.errors.promptUnavailable'));
          return;
        }
        const typed = String(promptResult.value || '').trim();
        if (typed !== confirmationPhrase) {
          setMessage(t('maintenance.errors.confirmationMismatch'));
          return;
        }
        await confirmForgettingArchive({
          review_id: review.review_id,
          token: review.token,
          confirmation_phrase: typed,
        });
        setMessage(t('maintenance.forgetting.messages.archived', { count: ids.length }));
        const idSet = new Set(ids);
        setCandidates((prev) => prev.filter((c) => !idSet.has(c.memory_id)));
        setSelectedIds(new Set());
      } catch (err) {
        if (isUnsupportedError(err)) {
          setMessage(t('maintenance.forgetting.messages.archivedMock', { count: ids.length }));
          const idSet = new Set(ids);
          setCandidates((prev) => prev.filter((c) => !idSet.has(c.memory_id)));
          setSelectedIds(new Set());
        } else {
          setMessage(t('maintenance.forgetting.messages.archiveFailed', { count: ids.length }));
        }
      } finally {
        setBusyId(null);
      }
    },
    [days, t, threshold]
  );

  const handleInspect = useCallback(
    (id) => {
      if (typeof onInspectMemory === 'function') {
        onInspectMemory(id);
      } else {
        setMessage(t('maintenance.forgetting.messages.inspectQueued', { id }));
      }
    },
    [onInspectMemory, t]
  );

  const handleBatchArchive = useCallback(() => {
    const ids = Array.from(selectedIds);
    void performArchive(ids);
  }, [performArchive, selectedIds]);

  const handleBatchKeep = useCallback(async () => {
    const ids = Array.from(selectedIds);
    if (!ids.length) return;
    setBusyId('batch');
    setMessage(null);
    try {
      setMessage(t('maintenance.forgetting.messages.keptBatch', { count: ids.length }));
      const idSet = new Set(ids);
      setCandidates((prev) => prev.filter((c) => !idSet.has(c.memory_id)));
      setSelectedIds(new Set());
    } catch (_err) {
      setMessage(t('maintenance.forgetting.messages.keepBatchFailed', { count: ids.length }));
    } finally {
      setBusyId(null);
    }
  }, [selectedIds, t]);

  const busy = busyId !== null;

  return (
    <section aria-label={t('maintenance.forgetting.title')} className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="font-display flex items-center gap-2 text-base font-semibold text-[color:var(--palace-ink)]">
            <TrendingDown size={16} className="text-[color:var(--palace-accent)]" />
            {t('maintenance.forgetting.title')}
          </h2>
          <p className="mt-1 text-xs text-[color:var(--palace-muted)]">
            {t('maintenance.forgetting.subtitle')}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {isMock && (
            <span
              className="inline-flex items-center gap-1 rounded-full border border-[rgba(200,171,134,0.65)] bg-[rgba(244,236,224,0.92)] px-3 py-1 text-[11px] font-medium text-[color:var(--palace-accent-2)]"
              data-testid="forgetting-mock-badge"
            >
              <AlertTriangle size={12} />
              {t('maintenance.forgetting.mockBadge')}
            </span>
          )}
          <button
            type="button"
            onClick={loadData}
            disabled={loading || busy}
            data-testid="forgetting-refresh"
            className="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-[color:var(--palace-line)] bg-white/[.88] px-3 py-2 text-xs font-medium text-[color:var(--palace-muted)] transition-colors hover:border-[color:var(--palace-accent)] hover:text-[color:var(--palace-ink)] disabled:cursor-not-allowed disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-[rgba(179,133,79,0.35)]"
          >
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
            {t('maintenance.forgetting.refresh')}
          </button>
        </div>
      </div>

      {error && (
        <div
          role="alert"
          className="rounded-md border border-[rgba(143,106,69,0.45)] bg-[rgba(232,218,198,0.88)] px-3 py-2 text-xs text-[color:var(--palace-accent-2)]"
        >
          {error}
        </div>
      )}

      <div className={PANEL_CLASS}>
        <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold text-[color:var(--palace-ink)]">
          <Shield size={15} className="text-[color:var(--palace-accent)]" />
          {t('maintenance.forgetting.simulationHeading')}
        </h3>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <div className="rounded-xl border border-[color:var(--palace-line)] bg-white/80 p-3">
            <label htmlFor="forgetting-threshold-input" className="mb-1 block text-[10px] uppercase tracking-[0.14em] text-[color:var(--palace-muted)]">
              {t('maintenance.forgetting.thresholdLabel')}
            </label>
            <input
              id="forgetting-threshold-input"
              type="number"
              step="0.05"
              min="0"
              max="1"
              value={thresholdInput}
              onChange={(e) => setThresholdInput(e.target.value)}
              data-testid="forgetting-threshold-input"
              className="w-full rounded border border-[color:var(--palace-line)] bg-white px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-[rgba(179,133,79,0.35)]"
            />
          </div>
          <div className="rounded-xl border border-[color:var(--palace-line)] bg-white/80 p-3">
            <label htmlFor="forgetting-days-input" className="mb-1 block text-[10px] uppercase tracking-[0.14em] text-[color:var(--palace-muted)]">
              {t('maintenance.forgetting.daysLabel')}
            </label>
            <input
              id="forgetting-days-input"
              type="number"
              min="1"
              max="365"
              value={daysInput}
              onChange={(e) => setDaysInput(e.target.value)}
              data-testid="forgetting-days-input"
              className="w-full rounded border border-[color:var(--palace-line)] bg-white px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-[rgba(179,133,79,0.35)]"
            />
          </div>
          <div className="rounded-xl border border-[color:var(--palace-line)] bg-white/80 p-3">
            <div className="mb-1 text-[10px] uppercase tracking-[0.14em] text-[color:var(--palace-muted)]">
              {t('maintenance.forgetting.projectedArchived')}
            </div>
            <div className="text-lg font-semibold text-[color:var(--palace-accent-2)]">
              {Number(simulation?.projected_archived) || 0}
            </div>
            <div className="text-[10px] text-[color:var(--palace-muted)]">
              {t('maintenance.forgetting.outOfTotal', { count: Number(simulation?.total_candidates) || 0 })}
            </div>
          </div>
          <div className="rounded-xl border border-[color:var(--palace-line)] bg-white/80 p-3">
            <div className="mb-1 text-[10px] uppercase tracking-[0.14em] text-[color:var(--palace-muted)]">
              {t('maintenance.forgetting.projectedRetained')}
            </div>
            <div className="text-lg font-semibold text-[color:var(--palace-ink)]">
              {Number(simulation?.projected_retained) || 0}
            </div>
            <div className="text-[10px] text-[color:var(--palace-muted)]">
              {t('maintenance.forgetting.simulationDays', { count: Number(simulation?.simulation_days) || days })}
            </div>
          </div>
        </div>
      </div>

      <div className={PANEL_CLASS}>
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <h3 className="flex items-center gap-2 text-sm font-semibold text-[color:var(--palace-ink)]">
            <Archive size={15} className="text-[color:var(--palace-accent)]" />
            {t('maintenance.forgetting.queueHeading')}
          </h3>
          {selectedIds.size > 0 && (
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-[11px] text-[color:var(--palace-muted)]">
                {t('maintenance.forgetting.selectedCount', { count: selectedIds.size })}
              </span>
              <button
                type="button"
                onClick={handleBatchKeep}
                disabled={busy}
                data-testid="forgetting-batch-keep"
                className="inline-flex cursor-pointer items-center gap-1 rounded border border-[color:var(--palace-line)] bg-white/90 px-2 py-1 text-[11px] text-[color:var(--palace-muted)] transition-colors hover:border-[color:var(--palace-accent)] hover:text-[color:var(--palace-ink)] disabled:cursor-not-allowed disabled:opacity-45 focus:outline-none focus:ring-2 focus:ring-[rgba(179,133,79,0.35)]"
              >
                <ThumbsUp size={12} />
                {t('maintenance.forgetting.batchKeep')}
              </button>
              <button
                type="button"
                onClick={handleBatchArchive}
                disabled={busy}
                data-testid="forgetting-batch-archive"
                className="inline-flex cursor-pointer items-center gap-1 rounded border border-[rgba(200,171,134,0.65)] bg-[rgba(244,236,224,0.9)] px-2 py-1 text-[11px] text-[color:var(--palace-accent-2)] transition-colors hover:border-[color:var(--palace-accent)] disabled:cursor-not-allowed disabled:opacity-45 focus:outline-none focus:ring-2 focus:ring-[rgba(179,133,79,0.35)]"
              >
                <Archive size={12} />
                {t('maintenance.forgetting.batchArchive')}
              </button>
            </div>
          )}
        </div>

        {message && (
          <div
            role="status"
            className="mb-3 rounded-md border border-[color:var(--palace-line)] bg-white/80 px-3 py-2 text-xs text-[color:var(--palace-muted)]"
          >
            {message}
          </div>
        )}

        {loading ? (
          <div className="flex items-center gap-2 text-xs text-[color:var(--palace-muted)]">
            <RefreshCw size={14} className="animate-spin" />
            {t('maintenance.forgetting.loading')}
          </div>
        ) : candidates.length === 0 ? (
          <div className="rounded-xl border border-dashed border-[color:var(--palace-line)] bg-white/30 px-4 py-8 text-center text-sm text-[color:var(--palace-muted)]">
            {t('maintenance.forgetting.noCandidates')}
          </div>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {candidates.map((candidate) => (
              <CandidateCard
                key={candidate.memory_id}
                candidate={candidate}
                selected={selectedIds.has(candidate.memory_id)}
                onToggleSelect={toggleSelect}
                onKeep={handleKeep}
                onArchive={(id) => performArchive([id])}
                onInspect={handleInspect}
                busy={busy}
              />
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
