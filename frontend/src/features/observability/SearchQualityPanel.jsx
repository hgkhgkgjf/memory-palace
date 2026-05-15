import React, { useCallback, useEffect, useMemo, useState } from 'react';
import clsx from 'clsx';
import { useTranslation } from 'react-i18next';
import {
  AlertTriangle,
  Gauge,
  RefreshCw,
  Sigma,
  Target,
  TrendingUp,
} from 'lucide-react';

import { getSearchQualityMetrics } from '../../lib/api';

const PANEL_CLASS =
  'rounded-2xl border border-[color:var(--palace-line)] bg-[rgba(255,250,244,0.9)] p-4 shadow-[var(--palace-shadow-sm)] backdrop-blur-sm';

const MODE_KEYS = ['hybrid', 'semantic', 'keyword'];

const SPARKLINE_WIDTH = 280;
const SPARKLINE_HEIGHT = 70;
const SPARKLINE_PADDING = 4;

/**
 * @typedef {{
 *   mode: string,
 *   mrr_at_8?: number | null,
 *   recall_at_8?: number | null,
 *   p95_latency_ms?: number | null,
 *   sample_count?: number | null,
 * }} ModeQuality
 *
 * @typedef {{
 *   timestamp: string,
 *   mrr_at_8?: number | null,
 *   recall_at_8?: number | null,
 *   p95_latency_ms?: number | null,
 * }} QualityHistoryPoint
 *
 * @typedef {{
 *   fts5_weight?: number | null,
 *   vector_weight?: number | null,
 *   rrf_weight?: number | null,
 *   fts5_contribution?: number | null,
 *   vector_contribution?: number | null,
 *   rrf_contribution?: number | null,
 * }} ChannelContribution
 *
 * @typedef {{
 *   enabled?: boolean | null,
 *   k?: number | null,
 *   reason?: string | null,
 * }} RrfStatus
 *
 * @typedef {{
 *   timestamp?: string | null,
 *   modes?: ModeQuality[] | null,
 *   channel_contribution?: ChannelContribution | null,
 *   rrf?: RrfStatus | null,
 *   history?: QualityHistoryPoint[] | null,
 *   sample_window_days?: number | null,
 *   is_mock?: boolean | null,
 * }} SearchQualityMetrics
 */

/** @returns {SearchQualityMetrics} */
const createMockQualityMetrics = () => {
  const now = Date.now();
  /** @type {QualityHistoryPoint[]} */
  const history = Array.from({ length: 12 }, (_, idx) => {
    const ts = new Date(now - (11 - idx) * 24 * 60 * 60 * 1000).toISOString();
    return {
      timestamp: ts,
      mrr_at_8: 0.55 + Math.sin(idx / 2) * 0.07,
      recall_at_8: 0.68 + Math.cos(idx / 3) * 0.05,
      p95_latency_ms: 130 + Math.sin(idx / 4) * 12,
    };
  });
  return {
    timestamp: new Date().toISOString(),
    is_mock: true,
    sample_window_days: 14,
    modes: [
      { mode: 'hybrid', mrr_at_8: 0.612, recall_at_8: 0.722, p95_latency_ms: 142, sample_count: 1240 },
      { mode: 'semantic', mrr_at_8: 0.541, recall_at_8: 0.681, p95_latency_ms: 168, sample_count: 642 },
      { mode: 'keyword', mrr_at_8: 0.488, recall_at_8: 0.601, p95_latency_ms: 92, sample_count: 824 },
    ],
    channel_contribution: {
      fts5_weight: 0.45,
      vector_weight: 0.4,
      rrf_weight: 0.15,
      fts5_contribution: 0.41,
      vector_contribution: 0.46,
      rrf_contribution: 0.13,
    },
    rrf: { enabled: true, k: 60, reason: 'production' },
    history,
  };
};

const formatPercent = (value, fractionDigits = 1) => {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return '-';
  }
  return `${(Number(value) * 100).toFixed(fractionDigits)}%`;
};

const formatRatio = (value, fractionDigits = 3) => {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return '-';
  }
  return Number(value).toFixed(fractionDigits);
};

const formatMs = (value) => {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return '-';
  }
  return `${Number(value).toFixed(1)} ms`;
};

/**
 * @param {{ history: QualityHistoryPoint[], metricKey: 'mrr_at_8' | 'recall_at_8' | 'p95_latency_ms', label: string, color: string }} props
 */
function Sparkline({ history, metricKey, label, color }) {
  const { t } = useTranslation();
  const points = Array.isArray(history) ? history : [];
  const numericPoints = points
    .map((p) => Number(p?.[metricKey]))
    .filter((n) => Number.isFinite(n));

  if (numericPoints.length < 2) {
    return (
      <div className="flex h-[70px] items-center justify-center rounded border border-dashed border-[color:var(--palace-line)] bg-white/30 text-[11px] text-[color:var(--palace-muted)]">
        {t('observability.searchQuality.notEnoughData')}
      </div>
    );
  }

  const min = Math.min(...numericPoints);
  const max = Math.max(...numericPoints);
  const range = max - min || 1;
  const stepX = (SPARKLINE_WIDTH - SPARKLINE_PADDING * 2) / (numericPoints.length - 1);

  const path = numericPoints
    .map((value, idx) => {
      const x = SPARKLINE_PADDING + idx * stepX;
      const y = SPARKLINE_HEIGHT - SPARKLINE_PADDING - ((value - min) / range) * (SPARKLINE_HEIGHT - SPARKLINE_PADDING * 2);
      return `${idx === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`;
    })
    .join(' ');

  return (
    <div className="relative">
      <svg
        role="img"
        aria-label={label}
        viewBox={`0 0 ${SPARKLINE_WIDTH} ${SPARKLINE_HEIGHT}`}
        className="block w-full"
        preserveAspectRatio="none"
      >
        <path
          d={path}
          fill="none"
          stroke={color}
          strokeWidth="1.6"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
      <div className="mt-1 flex justify-between text-[10px] text-[color:var(--palace-muted)]">
        <span>{t('observability.searchQuality.sparklineMin', { value: typeof min === 'number' ? min.toFixed(3) : '-' })}</span>
        <span>{t('observability.searchQuality.sparklineMax', { value: typeof max === 'number' ? max.toFixed(3) : '-' })}</span>
      </div>
    </div>
  );
}

/**
 * @param {{
 *   label: React.ReactNode,
 *   value: React.ReactNode,
 *   hint?: React.ReactNode,
 *   tone?: 'neutral' | 'good' | 'warn',
 * }} props
 */
function MetricCell({ label, value, hint, tone = 'neutral' }) {
  return (
    <div
      className={clsx(
        'rounded-xl border p-3 text-xs',
        tone === 'good' && 'border-[rgba(179,133,79,0.45)] bg-[rgba(251,245,236,0.9)] text-[color:var(--palace-ink)]',
        tone === 'warn' && 'border-[rgba(200,171,134,0.65)] bg-[rgba(244,236,224,0.92)] text-[color:var(--palace-ink)]',
        tone === 'neutral' && 'border-[color:var(--palace-line)] bg-[rgba(255,250,244,0.85)] text-[color:var(--palace-muted)]'
      )}
    >
      <div className="mb-1 text-[10px] uppercase tracking-[0.14em] text-[color:var(--palace-muted)]">
        {label}
      </div>
      <div className="text-base font-semibold text-[color:var(--palace-ink)]">{value}</div>
      {hint ? <div className="mt-1 text-[11px] text-[color:var(--palace-muted)]">{hint}</div> : null}
    </div>
  );
}

export default function SearchQualityPanel() {
  const { t, i18n } = useTranslation();
  const [metrics, setMetrics] = useState(/** @type {SearchQualityMetrics | null} */ (null));
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(/** @type {string | null} */ (null));
  const [isMock, setIsMock] = useState(false);

  const loadMetrics = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getSearchQualityMetrics();
      const usedMock = !data || data.is_mock === true;
      setMetrics(usedMock ? createMockQualityMetrics() : data);
      setIsMock(usedMock);
    } catch (err) {
      // Endpoint may not yet be implemented - fall back to mock data for development.
      const statusCode = err?.response?.status;
      if (statusCode === 404 || statusCode === 501 || err?.code === 'ERR_NETWORK') {
        setMetrics(createMockQualityMetrics());
        setIsMock(true);
        setError(null);
      } else {
        setMetrics(createMockQualityMetrics());
        setIsMock(true);
        setError(t('observability.searchQuality.errors.loadMetrics'));
      }
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void loadMetrics();
  }, [loadMetrics]);

  const modesByKey = useMemo(() => {
    const map = new Map();
    const arr = Array.isArray(metrics?.modes) ? metrics.modes : [];
    arr.forEach((m) => {
      if (m && typeof m.mode === 'string') {
        map.set(m.mode, m);
      }
    });
    return map;
  }, [metrics]);

  const channel = metrics?.channel_contribution || {};
  const rrf = metrics?.rrf || {};
  const history = Array.isArray(metrics?.history) ? metrics.history : [];

  const lastUpdatedLabel = useMemo(() => {
    if (!metrics?.timestamp) return t('observability.searchQuality.notAvailable');
    try {
      const date = new Date(metrics.timestamp);
      if (Number.isNaN(date.getTime())) return metrics.timestamp;
      return date.toLocaleString(i18n.resolvedLanguage || 'en');
    } catch (_error) {
      return String(metrics.timestamp);
    }
  }, [metrics, i18n.resolvedLanguage, t]);

  return (
    <section
      aria-label={t('observability.searchQuality.title')}
      className="space-y-4"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="font-display flex items-center gap-2 text-base font-semibold text-[color:var(--palace-ink)]">
            <Target size={16} className="text-[color:var(--palace-accent)]" />
            {t('observability.searchQuality.title')}
          </h2>
          <p className="mt-1 text-xs text-[color:var(--palace-muted)]">
            {t('observability.searchQuality.subtitle')}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {isMock && (
            <span
              className="inline-flex items-center gap-1 rounded-full border border-[rgba(200,171,134,0.65)] bg-[rgba(244,236,224,0.92)] px-3 py-1 text-[11px] font-medium text-[color:var(--palace-accent-2)]"
              data-testid="search-quality-mock-badge"
            >
              <AlertTriangle size={12} />
              {t('observability.searchQuality.mockBadge')}
            </span>
          )}
          <button
            type="button"
            onClick={loadMetrics}
            disabled={loading}
            data-testid="search-quality-refresh"
            className="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-[color:var(--palace-line)] bg-white/[.88] px-3 py-2 text-xs font-medium text-[color:var(--palace-muted)] transition-colors hover:border-[color:var(--palace-accent)] hover:text-[color:var(--palace-ink)] disabled:cursor-not-allowed disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-[rgba(179,133,79,0.35)]"
          >
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
            {t('observability.searchQuality.refresh')}
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

      {/* Per-mode quality grid */}
      <div className={PANEL_CLASS}>
        <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold text-[color:var(--palace-ink)]">
          <Sigma size={15} className="text-[color:var(--palace-accent)]" />
          {t('observability.searchQuality.perModeHeading')}
        </h3>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {MODE_KEYS.map((mode) => {
            const data = modesByKey.get(mode) || {};
            return (
              <div
                key={mode}
                className="rounded-xl border border-[color:var(--palace-line)] bg-white/80 p-3"
                data-testid={`search-quality-mode-${mode}`}
              >
                <div className="mb-2 text-xs font-semibold uppercase tracking-[0.14em] text-[color:var(--palace-accent-2)]">
                  {t(`observability.searchQuality.modes.${mode}`)}
                </div>
                <dl className="grid grid-cols-3 gap-2 text-[11px]">
                  <div>
                    <dt className="text-[color:var(--palace-muted)]">{t('observability.searchQuality.mrr')}</dt>
                    <dd className="font-semibold text-[color:var(--palace-ink)]">{formatRatio(data.mrr_at_8)}</dd>
                  </div>
                  <div>
                    <dt className="text-[color:var(--palace-muted)]">{t('observability.searchQuality.recall')}</dt>
                    <dd className="font-semibold text-[color:var(--palace-ink)]">{formatRatio(data.recall_at_8)}</dd>
                  </div>
                  <div>
                    <dt className="text-[color:var(--palace-muted)]">{t('observability.searchQuality.p95')}</dt>
                    <dd className="font-semibold text-[color:var(--palace-ink)]">{formatMs(data.p95_latency_ms)}</dd>
                  </div>
                </dl>
                <div className="mt-2 text-[10px] text-[color:var(--palace-muted)]">
                  {t('observability.searchQuality.sampleCount', { count: Number(data.sample_count) || 0 })}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Channel contribution + RRF status */}
      <div className="grid gap-4 lg:grid-cols-2">
        <div className={PANEL_CLASS}>
          <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold text-[color:var(--palace-ink)]">
            <TrendingUp size={15} className="text-[color:var(--palace-accent)]" />
            {t('observability.searchQuality.channelHeading')}
          </h3>
          <div className="grid grid-cols-3 gap-2">
            <MetricCell
              label={t('observability.searchQuality.channels.fts5')}
              value={formatPercent(channel.fts5_contribution)}
              hint={t('observability.searchQuality.weight', { value: formatPercent(channel.fts5_weight) })}
            />
            <MetricCell
              label={t('observability.searchQuality.channels.vector')}
              value={formatPercent(channel.vector_contribution)}
              hint={t('observability.searchQuality.weight', { value: formatPercent(channel.vector_weight) })}
            />
            <MetricCell
              label={t('observability.searchQuality.channels.rrf')}
              value={formatPercent(channel.rrf_contribution)}
              hint={t('observability.searchQuality.weight', { value: formatPercent(channel.rrf_weight) })}
            />
          </div>
          <div className="mt-3 text-[11px] text-[color:var(--palace-muted)]">
            {t('observability.searchQuality.contributionExplain')}
          </div>
        </div>

        <div className={PANEL_CLASS} data-testid="search-quality-rrf-status">
          <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold text-[color:var(--palace-ink)]">
            <Gauge size={15} className="text-[color:var(--palace-accent)]" />
            {t('observability.searchQuality.rrfHeading')}
          </h3>
          <div className="grid grid-cols-2 gap-2">
            <MetricCell
              label={t('observability.searchQuality.rrfStatus')}
              value={
                rrf.enabled
                  ? t('observability.searchQuality.rrfEnabled')
                  : t('observability.searchQuality.rrfDisabled')
              }
              tone={rrf.enabled ? 'good' : 'warn'}
            />
            <MetricCell
              label={t('observability.searchQuality.rrfK')}
              value={
                rrf.k === null || rrf.k === undefined
                  ? '-'
                  : String(rrf.k)
              }
              hint={
                rrf.reason
                  ? t('observability.searchQuality.rrfReason', { value: rrf.reason })
                  : null
              }
            />
          </div>
        </div>
      </div>

      {/* Time series chart */}
      <div className={PANEL_CLASS}>
        <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold text-[color:var(--palace-ink)]">
          <TrendingUp size={15} className="text-[color:var(--palace-accent)]" />
          {t('observability.searchQuality.timeSeriesHeading')}
        </h3>
        <div className="grid gap-3 md:grid-cols-3">
          <div>
            <div className="mb-1 text-[11px] font-semibold text-[color:var(--palace-accent-2)]">
              {t('observability.searchQuality.mrrTrend')}
            </div>
            <Sparkline
              history={history}
              metricKey="mrr_at_8"
              label={t('observability.searchQuality.mrrTrend')}
              color="rgba(179,133,79,0.92)"
            />
          </div>
          <div>
            <div className="mb-1 text-[11px] font-semibold text-[color:var(--palace-accent-2)]">
              {t('observability.searchQuality.recallTrend')}
            </div>
            <Sparkline
              history={history}
              metricKey="recall_at_8"
              label={t('observability.searchQuality.recallTrend')}
              color="rgba(143,106,69,0.92)"
            />
          </div>
          <div>
            <div className="mb-1 text-[11px] font-semibold text-[color:var(--palace-accent-2)]">
              {t('observability.searchQuality.latencyTrend')}
            </div>
            <Sparkline
              history={history}
              metricKey="p95_latency_ms"
              label={t('observability.searchQuality.latencyTrend')}
              color="rgba(120,90,55,0.92)"
            />
          </div>
        </div>
        <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-[11px] text-[color:var(--palace-muted)]">
          <span>
            {t('observability.searchQuality.windowDays', {
              count: Number(metrics?.sample_window_days) || history.length || 0,
            })}
          </span>
          <span>{t('observability.searchQuality.lastUpdated', { value: lastUpdatedLabel })}</span>
        </div>
      </div>
    </section>
  );
}
