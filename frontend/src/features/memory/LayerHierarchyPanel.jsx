import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import clsx from 'clsx';
import { useTranslation } from 'react-i18next';
import {
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  FileText,
  Layers,
  Network,
  RefreshCw,
} from 'lucide-react';

import { getLayeringSummaries, getLayeringSummaryDetail } from '../../lib/api';

const PANEL_CLASS =
  'rounded-2xl border border-[color:var(--palace-line)] bg-[rgba(255,250,244,0.9)] p-4 shadow-[var(--palace-shadow-sm)] backdrop-blur-sm';

/**
 * @typedef {{
 *   layer: 'L0' | 'L1' | 'L2',
 *   count?: number,
 *   storage_bytes?: number,
 * }} LayerStat
 *
 * @typedef {{
 *   id: string | number,
 *   title?: string | null,
 *   summary?: string | null,
 *   confidence?: number | null,
 *   review_state?: string | null,
 *   created_at?: string | null,
 *   source_memory_ids?: Array<string | number> | null,
 *   l1_count?: number | null,
 *   l0_count?: number | null,
 * }} L2Summary
 *
 * @typedef {{
 *   id: string | number,
 *   uri?: string | null,
 *   title?: string | null,
 *   content?: string | null,
 *   priority?: number | null,
 *   created_at?: string | null,
 * }} L1Memory
 *
 * @typedef {{
 *   timestamp?: string | null,
 *   layer_stats?: LayerStat[] | null,
 *   summaries?: L2Summary[] | null,
 *   is_mock?: boolean | null,
 * }} LayeringPayload
 *
 * @typedef {{
 *   summary?: L2Summary | null,
 *   source_memories?: L1Memory[] | null,
 *   is_mock?: boolean | null,
 * }} L2DetailPayload
 */

/**
 * @param {(key: string, options?: object) => string} t
 * @returns {LayeringPayload}
 */
const createMockSummaryPayload = (t) => ({
  timestamp: new Date().toISOString(),
  is_mock: true,
  layer_stats: [
    { layer: 'L0', count: 12480, storage_bytes: 4_320_000 },
    { layer: 'L1', count: 642, storage_bytes: 1_280_000 },
    { layer: 'L2', count: 48, storage_bytes: 96_000 },
  ],
  summaries: [
    {
      id: 'l2-001',
      title: t('memory.layerHierarchy.mock.summary1Title'),
      summary: t('memory.layerHierarchy.mock.summary1Body'),
      confidence: 0.86,
      review_state: 'approved',
      created_at: new Date(Date.now() - 4 * 86400000).toISOString(),
      source_memory_ids: [801, 802, 803, 804, 805, 806, 807, 808],
      l1_count: 8,
      l0_count: 124,
    },
    {
      id: 'l2-002',
      title: t('memory.layerHierarchy.mock.summary2Title'),
      summary: t('memory.layerHierarchy.mock.summary2Body'),
      confidence: 0.74,
      review_state: 'pending',
      created_at: new Date(Date.now() - 9 * 86400000).toISOString(),
      source_memory_ids: [901, 902, 903, 904, 905],
      l1_count: 5,
      l0_count: 78,
    },
    {
      id: 'l2-003',
      title: t('memory.layerHierarchy.mock.summary3Title'),
      summary: t('memory.layerHierarchy.mock.summary3Body'),
      confidence: 0.62,
      review_state: 'flagged',
      created_at: new Date(Date.now() - 14 * 86400000).toISOString(),
      source_memory_ids: [1101, 1102, 1103],
      l1_count: 3,
      l0_count: 52,
    },
  ],
});

const createMockDetailPayload = (id, t) => ({
  is_mock: true,
  summary: {
    id,
    title: t('memory.layerHierarchy.mock.detailTitle', { id }),
    summary: t('memory.layerHierarchy.mock.detailBody'),
    confidence: 0.72,
    review_state: 'pending',
    source_memory_ids: [9001, 9002, 9003],
  },
  source_memories: [
    { id: 9001, uri: 'core://notes/alpha', title: t('memory.layerHierarchy.mock.atomicTitle', { id: 9001 }), content: t('memory.layerHierarchy.mock.atomicContent', { id: 9001 }), priority: 5 },
    { id: 9002, uri: 'core://notes/beta', title: t('memory.layerHierarchy.mock.atomicTitle', { id: 9002 }), content: t('memory.layerHierarchy.mock.atomicContent', { id: 9002 }), priority: 3 },
    { id: 9003, uri: 'core://notes/gamma', title: t('memory.layerHierarchy.mock.atomicTitle', { id: 9003 }), content: t('memory.layerHierarchy.mock.atomicContent', { id: 9003 }), priority: 7 },
  ],
});

const formatBytes = (value) => {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '-';
  const bytes = Number(value);
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`;
};

const formatPercent = (value) => {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '-';
  return `${(Number(value) * 100).toFixed(1)}%`;
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

const isUnsupportedError = (err) => {
  const statusCode = err?.response?.status;
  return statusCode === 404 || statusCode === 501 || err?.code === 'ERR_NETWORK';
};

function ReviewStateBadge({ state }) {
  const { t } = useTranslation();
  const tone =
    state === 'approved'
      ? 'good'
      : state === 'flagged' || state === 'rejected'
      ? 'warn'
      : 'neutral';
  return (
    <span
      className={clsx(
        'inline-flex items-center rounded border px-1.5 py-0.5 text-[10px] font-medium',
        tone === 'good' && 'border-[rgba(179,133,79,0.5)] bg-[rgba(246,237,224,0.85)] text-[color:var(--palace-accent-2)]',
        tone === 'warn' && 'border-[rgba(200,171,134,0.65)] bg-[rgba(240,230,215,0.9)] text-[color:var(--palace-accent-2)]',
        tone === 'neutral' && 'border-[color:var(--palace-line)] bg-white/80 text-[color:var(--palace-muted)]'
      )}
    >
      {t(`memory.layerHierarchy.reviewStates.${state || 'unknown'}`, {
        defaultValue: state || t('memory.layerHierarchy.reviewStates.unknown'),
      })}
    </span>
  );
}

function L1MemoryRow({ memory, expanded, onToggle }) {
  const { t } = useTranslation();
  return (
    <li className="rounded border border-[color:var(--palace-line)] bg-white/70 p-2 text-xs text-[color:var(--palace-muted)]">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={expanded}
        className="flex w-full items-start gap-2 text-left"
        data-testid={`layer-hierarchy-l1-toggle-${memory.id}`}
      >
        {expanded ? (
          <ChevronDown size={14} className="mt-0.5 shrink-0 text-[color:var(--palace-accent)]" />
        ) : (
          <ChevronRight size={14} className="mt-0.5 shrink-0 text-[color:var(--palace-muted)]" />
        )}
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <code className="text-[10px] font-mono text-[color:var(--palace-accent-2)]">
              #{memory.id}
            </code>
            <span className="font-semibold text-[color:var(--palace-ink)]">
              {memory.title || memory.uri || t('memory.layerHierarchy.untitledMemory')}
            </span>
          </div>
          {memory.uri && (
            <div className="mt-0.5 break-all text-[10px] text-[color:var(--palace-muted)]">{memory.uri}</div>
          )}
        </div>
      </button>
      {expanded && (
        <div className="mt-2 rounded bg-white/80 p-2 text-[11px] leading-relaxed text-[color:var(--palace-ink)] whitespace-pre-wrap">
          {memory.content || t('memory.layerHierarchy.noContent')}
        </div>
      )}
    </li>
  );
}

function L2SummaryNode({ summary, expanded, onToggle, detail, detailLoading, expandedL1Ids, onToggleL1 }) {
  const { t, i18n } = useTranslation();
  const sourceIds = Array.isArray(summary.source_memory_ids) ? summary.source_memory_ids : [];
  const detailMemories = Array.isArray(detail?.source_memories) ? detail.source_memories : [];

  return (
    <li className="rounded-xl border border-[color:var(--palace-line)] bg-white/80 p-3" data-testid={`layer-hierarchy-l2-${summary.id}`}>
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={expanded}
        className="flex w-full items-start gap-2 text-left"
      >
        {expanded ? (
          <ChevronDown size={16} className="mt-1 shrink-0 text-[color:var(--palace-accent)]" />
        ) : (
          <ChevronRight size={16} className="mt-1 shrink-0 text-[color:var(--palace-muted)]" />
        )}
        <div className="min-w-0 flex-1">
          <div className="mb-1 flex flex-wrap items-center gap-2">
            <code className="text-[10px] font-mono text-[color:var(--palace-accent-2)]">
              #{summary.id}
            </code>
            <ReviewStateBadge state={summary.review_state} />
            <span className="text-[11px] text-[color:var(--palace-muted)]">
              {t('memory.layerHierarchy.confidence', { value: formatPercent(summary.confidence) })}
            </span>
          </div>
          <div className="text-sm font-semibold text-[color:var(--palace-ink)]">
            {summary.title || t('memory.layerHierarchy.untitledSummary')}
          </div>
          {summary.summary && (
            <p className="mt-1 text-[12px] leading-relaxed text-[color:var(--palace-muted)]">{summary.summary}</p>
          )}
          <div className="mt-2 flex flex-wrap gap-3 text-[10px] text-[color:var(--palace-muted)]">
            <span>{t('memory.layerHierarchy.l1Count', { count: Number(summary.l1_count) || sourceIds.length })}</span>
            <span>{t('memory.layerHierarchy.l0Count', { count: Number(summary.l0_count) || 0 })}</span>
            <span>{t('memory.layerHierarchy.createdAt', { value: formatDateTimeShort(summary.created_at, i18n.resolvedLanguage) })}</span>
          </div>
        </div>
      </button>

      {expanded && (
        <div className="mt-3 border-t border-[color:var(--palace-line)] pt-3">
          {detailLoading ? (
            <div className="flex items-center gap-2 text-xs text-[color:var(--palace-muted)]">
              <RefreshCw size={12} className="animate-spin" />
              {t('memory.layerHierarchy.loadingDetail')}
            </div>
          ) : (
            <>
              <div className="mb-2 text-[11px] uppercase tracking-[0.14em] text-[color:var(--palace-accent-2)]">
                {t('memory.layerHierarchy.provenanceHeading')}
              </div>
              {sourceIds.length === 0 ? (
                <div className="text-[11px] text-[color:var(--palace-muted)]">
                  {t('memory.layerHierarchy.noSources')}
                </div>
              ) : (
                <div className="mb-3 flex flex-wrap gap-1">
                  {sourceIds.map((srcId) => (
                    <code
                      key={srcId}
                      className="rounded border border-[color:var(--palace-line)] bg-white/90 px-1.5 py-0.5 text-[10px] font-mono text-[color:var(--palace-muted)]"
                    >
                      #{srcId}
                    </code>
                  ))}
                </div>
              )}
              <div className="mb-2 text-[11px] uppercase tracking-[0.14em] text-[color:var(--palace-accent-2)]">
                {t('memory.layerHierarchy.sourceMemoriesHeading')}
              </div>
              {detailMemories.length === 0 ? (
                <div className="rounded border border-dashed border-[color:var(--palace-line)] bg-white/30 px-3 py-3 text-[11px] text-[color:var(--palace-muted)]">
                  {t('memory.layerHierarchy.noL1Loaded')}
                </div>
              ) : (
                <ul className="space-y-2">
                  {detailMemories.map((mem) => (
                    <L1MemoryRow
                      key={mem.id}
                      memory={mem}
                      expanded={expandedL1Ids.has(String(mem.id))}
                      onToggle={() => onToggleL1(String(mem.id))}
                    />
                  ))}
                </ul>
              )}
            </>
          )}
        </div>
      )}
    </li>
  );
}

export default function LayerHierarchyPanel() {
  const { t } = useTranslation();
  const [payload, setPayload] = useState(/** @type {LayeringPayload | null} */ (null));
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(/** @type {string | null} */ (null));
  const [isMock, setIsMock] = useState(false);
  const [expandedSummaryId, setExpandedSummaryId] = useState(/** @type {string | number | null} */ (null));
  const [summaryDetail, setSummaryDetail] = useState(/** @type {Record<string, L2DetailPayload>} */ ({}));
  const [detailLoadingId, setDetailLoadingId] = useState(/** @type {string | number | null} */ (null));
  const [expandedL1Ids, setExpandedL1Ids] = useState(/** @type {Set<string>} */ (new Set()));

  const cancelledRef = useRef(false);

  const loadPayload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getLayeringSummaries();
      if (cancelledRef.current) return;
      const usedMock = !data || data.is_mock === true;
      setPayload(usedMock ? createMockSummaryPayload(t) : data);
      setIsMock(usedMock);
    } catch (err) {
      if (cancelledRef.current) return;
      if (isUnsupportedError(err)) {
        setPayload(createMockSummaryPayload(t));
        setIsMock(true);
        setError(null);
      } else {
        setPayload(createMockSummaryPayload(t));
        setIsMock(true);
        setError(t('memory.layerHierarchy.errors.loadSummaries'));
      }
    } finally {
      if (!cancelledRef.current) setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    cancelledRef.current = false;
    void loadPayload();
    return () => {
      cancelledRef.current = true;
    };
  }, [loadPayload]);

  const handleToggleSummary = useCallback(
    async (id) => {
      const key = String(id);
      setExpandedL1Ids(new Set());
      if (String(expandedSummaryId) === key) {
        setExpandedSummaryId(null);
        return;
      }
      setExpandedSummaryId(id);
      if (summaryDetail[key]) return;
      setDetailLoadingId(id);
      try {
        const detail = await getLayeringSummaryDetail(id);
        if (cancelledRef.current) return;
        if (detail && !detail.is_mock) {
          setSummaryDetail((prev) => ({ ...prev, [key]: detail }));
        } else {
          setSummaryDetail((prev) => ({ ...prev, [key]: detail || createMockDetailPayload(id, t) }));
        }
      } catch (err) {
        if (cancelledRef.current) return;
        if (isUnsupportedError(err)) {
          setSummaryDetail((prev) => ({ ...prev, [key]: createMockDetailPayload(id, t) }));
        } else {
          setSummaryDetail((prev) => ({ ...prev, [key]: createMockDetailPayload(id, t) }));
          setError(t('memory.layerHierarchy.errors.loadDetail', { id }));
        }
      } finally {
        if (!cancelledRef.current) setDetailLoadingId(null);
      }
    },
    [expandedSummaryId, summaryDetail, t]
  );

  const handleToggleL1 = useCallback((memoryId) => {
    setExpandedL1Ids((prev) => {
      const next = new Set(prev);
      const key = String(memoryId);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }, []);

  const layerStats = useMemo(() => {
    const map = new Map();
    const arr = Array.isArray(payload?.layer_stats) ? payload.layer_stats : [];
    arr.forEach((s) => {
      if (s && typeof s.layer === 'string') {
        map.set(s.layer, s);
      }
    });
    return map;
  }, [payload]);

  const summaries = useMemo(() => {
    const arr = Array.isArray(payload?.summaries) ? payload.summaries : [];
    return arr;
  }, [payload]);

  return (
    <section
      aria-label={t('memory.layerHierarchy.title')}
      className="space-y-4"
      data-testid="layer-hierarchy-panel"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="font-display flex items-center gap-2 text-base font-semibold text-[color:var(--palace-ink)]">
            <Layers size={16} className="text-[color:var(--palace-accent)]" />
            {t('memory.layerHierarchy.title')}
          </h2>
          <p className="mt-1 text-xs text-[color:var(--palace-muted)]">
            {t('memory.layerHierarchy.subtitle')}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {isMock && (
            <span
              className="inline-flex items-center gap-1 rounded-full border border-[rgba(200,171,134,0.65)] bg-[rgba(244,236,224,0.92)] px-3 py-1 text-[11px] font-medium text-[color:var(--palace-accent-2)]"
              data-testid="layer-hierarchy-mock-badge"
            >
              <AlertTriangle size={12} />
              {t('memory.layerHierarchy.mockBadge')}
            </span>
          )}
          <button
            type="button"
            onClick={loadPayload}
            disabled={loading}
            data-testid="layer-hierarchy-refresh"
            className="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-[color:var(--palace-line)] bg-white/[.88] px-3 py-2 text-xs font-medium text-[color:var(--palace-muted)] transition-colors hover:border-[color:var(--palace-accent)] hover:text-[color:var(--palace-ink)] disabled:cursor-not-allowed disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-[rgba(179,133,79,0.35)]"
          >
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
            {t('memory.layerHierarchy.refresh')}
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
          <Network size={15} className="text-[color:var(--palace-accent)]" />
          {t('memory.layerHierarchy.layerStatsHeading')}
        </h3>
        <div className="grid gap-3 sm:grid-cols-3">
          {['L0', 'L1', 'L2'].map((layer) => {
            const stat = layerStats.get(layer) || {};
            return (
              <div
                key={layer}
                className="rounded-xl border border-[color:var(--palace-line)] bg-white/80 p-3"
                data-testid={`layer-hierarchy-stat-${layer}`}
              >
                <div className="mb-1 text-[10px] uppercase tracking-[0.14em] text-[color:var(--palace-accent-2)]">
                  {t(`memory.layerHierarchy.layers.${layer}`)}
                </div>
                <div className="text-lg font-semibold text-[color:var(--palace-ink)]">
                  {(Number(stat.count) || 0).toLocaleString()}
                </div>
                <div className="text-[11px] text-[color:var(--palace-muted)]">
                  {t('memory.layerHierarchy.storageUsage', { value: formatBytes(stat.storage_bytes) })}
                </div>
                <div className="mt-1 text-[10px] text-[color:var(--palace-muted)]">
                  {t(`memory.layerHierarchy.layerDescriptions.${layer}`)}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      <div className={PANEL_CLASS}>
        <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold text-[color:var(--palace-ink)]">
          <FileText size={15} className="text-[color:var(--palace-accent)]" />
          {t('memory.layerHierarchy.summariesHeading')}
        </h3>
        {loading ? (
          <div className="flex items-center gap-2 text-xs text-[color:var(--palace-muted)]">
            <RefreshCw size={14} className="animate-spin" />
            {t('memory.layerHierarchy.loading')}
          </div>
        ) : summaries.length === 0 ? (
          <div className="rounded-xl border border-dashed border-[color:var(--palace-line)] bg-white/30 px-4 py-8 text-center text-sm text-[color:var(--palace-muted)]">
            {t('memory.layerHierarchy.noSummaries')}
          </div>
        ) : (
          <ul className="space-y-3" aria-label={t('memory.layerHierarchy.title')}>
            {summaries.map((summary) => (
              <L2SummaryNode
                key={summary.id}
                summary={summary}
                expanded={String(expandedSummaryId) === String(summary.id)}
                onToggle={() => handleToggleSummary(summary.id)}
                detail={summaryDetail[String(summary.id)]}
                detailLoading={detailLoadingId !== null && String(detailLoadingId) === String(summary.id)}
                expandedL1Ids={expandedL1Ids}
                onToggleL1={handleToggleL1}
              />
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
