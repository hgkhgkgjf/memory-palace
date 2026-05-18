import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import clsx from 'clsx';
import { useTranslation } from 'react-i18next';
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Database,
  Gauge,
  Radar,
  RefreshCw,
  Search,
  TimerReset,
  WifiOff,
  Wrench,
  Zap,
} from 'lucide-react';
import {
  cancelIndexJob,
  extractApiError,
  getIndexJob,
  getMaintenanceAuthState,
  getObservabilitySummary,
  retryIndexJob,
  runObservabilitySearch,
  subscribeMaintenanceAuthChanges,
  triggerIndexRebuild,
  triggerMemoryReindex,
  triggerSleepConsolidation,
} from '../../lib/api';
import { formatDateTime as formatDateTimeValue, formatNumber as formatNumberValue } from '../../lib/format';
import { bindEventSourceListeners, createEventSource, DEFAULT_SSE_REFRESH_EVENT_NAMES } from '../../lib/sse';
import SearchQualityPanel from './SearchQualityPanel';

const MODE_OPTIONS = ['hybrid', 'semantic', 'keyword'];
const PANEL_CLASS =
  'rounded-2xl border border-[color:var(--palace-line)] bg-[rgba(255,250,244,0.9)] p-4 shadow-[var(--palace-shadow-sm)] backdrop-blur-sm';
const INPUT_CLASS =
  'w-full rounded-lg border border-[color:var(--palace-line)] bg-white/90 px-3 py-2 text-sm text-[color:var(--palace-ink)] placeholder:text-[color:var(--palace-muted)] focus:outline-none focus:ring-2 focus:ring-[color:var(--palace-accent)]/35 focus:border-[color:var(--palace-accent)]';
const LABEL_CLASS = 'mb-2 block text-xs font-medium uppercase tracking-[0.14em] text-[color:var(--palace-muted)]';

/**
 * @typedef {{
 *   error: unknown,
 *   fallbackKey: string,
 *   fallbackValues?: Record<string, string | number | boolean | null | undefined>,
 * }} ObservabilityErrorState
 */

/**
 * @typedef {{
 *   job_id?: string | null,
 *   status?: string | null,
 *   task_type?: string | null,
 *   reason?: string | null,
 *   memory_id?: number | null,
 *   cancel_reason?: string | null,
 *   requested_at?: string | null,
 *   started_at?: string | null,
 *   finished_at?: string | null,
 *   error?: string | null,
 *   result?: {
 *     error?: string | null,
 *     degrade_reasons?: string[] | null,
 *   } | null,
 * }} IndexJob
 */

/**
 * @typedef {{
 *   source?: string | null,
 *   match_type?: string | null,
 *   priority?: number | null,
 *   updated_at?: string | null,
 * }} SearchResultMetadata
 */

/**
 * @typedef {{
 *   final?: number | null,
 * }} SearchResultScores
 */

/**
 * @typedef {{
 *   uri?: string | null,
 *   snippet?: string | null,
 *   memory_id?: number | null,
 *   metadata?: SearchResultMetadata | null,
 *   scores?: SearchResultScores | null,
 * }} SearchResultItem
 */

/**
 * @typedef {{
 *   latency_ms?: number | null,
 *   mode_applied?: string | null,
 *   interaction_tier?: string | null,
 *   intent_applied?: string | null,
 *   intent?: string | null,
 *   intent_llm_attempted?: boolean | null,
 *   strategy_template_applied?: string | null,
 *   strategy_template?: string | null,
 *   intent_profile?: { strategy_template?: string | null } | null,
 *   degraded?: boolean | null,
 *   degrade_reasons?: string[] | null,
 *   counts?: {
 *     session?: number | null,
 *     global?: number | null,
 *     returned?: number | null,
 *   } | null,
 *   results?: SearchResultItem[] | null,
 * }} SearchDiagnostics
 */

/**
 * @typedef {{
 *   status?: string | null,
 *   timestamp?: string | null,
 *   search_stats?: {
 *     total_queries?: number | null,
 *     degraded_queries?: number | null,
 *     cache_hit_ratio?: number | null,
 *     cache_hit_queries?: number | null,
 *     latency_ms?: {
 *       avg?: number | null,
 *       p95?: number | null,
 *     } | null,
 *     mode_breakdown?: Record<string, number> | null,
 *     intent_breakdown?: Record<string, number> | null,
 *     strategy_hit_breakdown?: Record<string, number> | null,
 *   } | null,
 *   health?: {
 *     index?: { degraded?: boolean | null } | null,
 *     runtime?: {
 *       index_worker?: {
 *         active_job_id?: string | null,
 *         recent_jobs?: IndexJob[] | null,
 *         queue_depth?: number | null,
 *         cancelling_jobs?: number | null,
 *         sleep_pending?: boolean | null,
 *         last_error?: string | null,
 *       } | null,
 *       sleep_consolidation?: { reason?: string | null } | null,
 *       sm_lite?: {
 *         degraded?: boolean | null,
 *         reason?: string | null,
 *         session_cache?: {
 *           session_count?: number | null,
 *           total_hits?: number | null,
 *         } | null,
 *         flush_tracker?: {
 *           session_count?: number | null,
 *           pending_events?: number | null,
 *         } | null,
 *       } | null,
 *     } | null,
 *   } | null,
 *   index_latency?: {
 *     avg_ms?: number | null,
 *     samples?: number | null,
 *   } | null,
 *   sleep_consolidation?: {
 *     reason?: string | null,
 *   } | null,
 *   cleanup_query_stats?: {
 *     total_queries?: number | null,
 *     slow_queries?: number | null,
 *     slow_threshold_ms?: number | null,
 *     full_scan_queries?: number | null,
 *     index_hit_ratio?: number | null,
 *     latency_ms?: { p95?: number | null } | null,
 *   } | null,
 *   reflection_workflow?: {
 *     prepared?: number | null,
 *     executed?: number | null,
 *     rolled_back?: number | null,
 *   } | null,
 * }} ObservabilitySummary
 */

/**
 * @typedef {{
 *   query: string,
 *   mode: string,
 *   maxResults: string,
 *   candidateMultiplier: string,
 *   includeSession: boolean,
 *   sessionId: string,
 *   domain: string,
 *   pathPrefix: string,
 *   scopeHint: string,
 *   maxPriority: string,
 * }} SearchFormState
 */

/**
 * @typedef {{
 *   query: string,
 *   mode: string,
 *   max_results: number,
 *   candidate_multiplier: number,
 *   include_session: boolean,
 *   session_id: string | null,
 *   filters: {
 *     domain?: string,
 *     path_prefix?: string,
 *     max_priority?: number,
 *   },
 *   scope_hint?: string,
 * }} ObservabilitySearchPayload
 */

/**
 * @typedef {{
 *   job_id?: string | null,
 * }} JobActionResponse
 */

const coerceTranslationText = (value, fallback = '') =>
  typeof value === 'string' ? value : fallback;

const toTranslationCount = (value) => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
};

const formatNumber = (value, lng) => {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return '-';
  }
  return formatNumberValue(value, lng) || '-';
};

const formatMs = (value) => {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return '-';
  }
  return `${Number(value).toFixed(1)} ms`;
};

const formatDateTime = (value, lng) => {
  if (!value || typeof value !== 'string') {
    return '-';
  }
  return formatDateTimeValue(value, lng, {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }) || value;
};

const getMaintenanceAuthFingerprint = () => {
  const authState = getMaintenanceAuthState();
  if (!authState?.key) return '';
  return `${authState.mode === 'bearer' ? 'bearer' : 'header'}:${authState.key}`;
};

const normalizeObservabilityToken = (value) => {
  if (value === null || value === undefined) return '';
  return String(value)
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '');
};

const translateObservabilityToken = (t, group, value, fallback = '-') => {
  const normalized = normalizeObservabilityToken(value);
  if (!normalized) return fallback;
  const key = `observability.${group}.${normalized}`;
  const translated = t(key);
  return translated && translated !== key ? translated : String(value);
};

const translateObservabilityBoolean = (t, value) =>
  t(`observability.booleans.${value ? 'true' : 'false'}`);

const translateOptionalObservabilityBoolean = (t, value, fallback = '-') => (
  value === null || value === undefined
    ? fallback
    : translateObservabilityBoolean(t, Boolean(value))
);

const formatObservabilityRequestTarget = (t, jobId) => (
  jobId
    ? t('observability.messages.jobTarget', { jobId: String(jobId) })
    : t('observability.messages.syncTarget')
);

const coerceNonNegativeNumber = (value, fallback = 0) => {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : fallback;
};

const parseOptionalNonNegativeInteger = (rawValue, label, t) => {
  const normalized = String(rawValue ?? '').trim();
  if (!normalized) return null;
  if (!/^\d+$/.test(normalized)) {
    throw new Error(t('observability.validation.nonNegativeInteger', { label }));
  }
  const parsed = Number(normalized);
  if (!Number.isSafeInteger(parsed)) {
    throw new Error(t('observability.validation.nonNegativeInteger', { label }));
  }
  return parsed;
};

const parseRequiredIntegerInRange = (
  rawValue,
  label,
  t,
  { min = 1, max = Number.MAX_SAFE_INTEGER } = {}
) => {
  const normalized = String(rawValue ?? '').trim();
  if (!normalized) {
    throw new Error(t('observability.validation.required', { label }));
  }
  if (!/^\d+$/.test(normalized)) {
    throw new Error(t('observability.validation.integer', { label }));
  }
  const parsed = Number(normalized);
  if (!Number.isSafeInteger(parsed) || parsed < min || parsed > max) {
    throw new Error(t('observability.validation.range', { label, min, max }));
  }
  return parsed;
};

const getJobStatusTone = (status) => {
  if (status === 'succeeded') return 'good';
  if (status === 'failed' || status === 'dropped') return 'danger';
  if (status === 'cancelled' || status === 'cancelling') return 'warn';
  return 'neutral';
};

const isRetryEndpointUnsupported = (error) => {
  const statusCode = error?.response?.status;
  if (statusCode === 405) return true;
  if (statusCode !== 404) return false;

  const detail = error?.response?.data?.detail;
  const detailParts = [];
  const pushDetailPart = (value) => {
    if (typeof value !== 'string') return;
    const normalized = value.trim().toLowerCase();
    if (!normalized || detailParts.includes(normalized)) return;
    detailParts.push(normalized);
  };

  if (typeof detail === 'string') {
    pushDetailPart(detail);
  } else if (detail && typeof detail === 'object') {
    pushDetailPart(detail.error);
    pushDetailPart(detail.reason);
    pushDetailPart(detail.message);
    if (detailParts.length === 0) {
      try {
        pushDetailPart(JSON.stringify(detail));
      } catch (_error) {
        // ignore non-serializable details
      }
    }
  }
  const detailText = detailParts.join(' | ');
  const hasNotFoundSignature =
    detailText.includes('not found') || detailText.includes('not_found');
  if (!hasNotFoundSignature) return false;

  // New retry endpoint and old backend route mismatch should fallback to legacy calls.
  // But explicit job-not-found from new backend should not fallback.
  if (detailText.includes('job_not_found')) return false;
  if (detailText.includes('job') && detailText.includes('not found')) return false;
  return true;
};

function StatCard({ icon: Icon, label, value, hint, tone = 'neutral' }) {
  return (
    <div
      className={clsx(
        'rounded-2xl border p-4 backdrop-blur-sm transition duration-200 shadow-[var(--palace-shadow-sm)]',
        tone === 'good' && 'border-[rgba(179,133,79,0.45)] bg-[rgba(251,245,236,0.9)]',
        tone === 'warn' && 'border-[rgba(200,171,134,0.65)] bg-[rgba(244,236,224,0.92)]',
        tone === 'danger' && 'border-[rgba(143,106,69,0.5)] bg-[rgba(236,224,207,0.88)]',
        tone === 'neutral' && 'border-[color:var(--palace-line)] bg-[rgba(255,250,244,0.9)]'
      )}
    >
      <div className="mb-3 flex items-center justify-between">
        <span className="text-[11px] uppercase tracking-[0.16em] text-[color:var(--palace-muted)]">{label}</span>
        <Icon size={14} className="text-[color:var(--palace-accent-2)]" />
      </div>
      <div className="text-2xl font-semibold text-[color:var(--palace-ink)]">{value}</div>
      <div className="mt-1 text-xs text-[color:var(--palace-muted)]">{hint}</div>
    </div>
  );
}

function Badge({ children, tone = 'neutral' }) {
  return (
    <span
      className={clsx(
        'inline-flex items-center rounded border px-2 py-0.5 text-[11px] font-medium',
        tone === 'good' && 'border-[rgba(179,133,79,0.5)] bg-[rgba(246,237,224,0.85)] text-[color:var(--palace-accent-2)]',
        tone === 'warn' && 'border-[rgba(200,171,134,0.65)] bg-[rgba(240,230,215,0.9)] text-[color:var(--palace-accent-2)]',
        tone === 'danger' && 'border-[rgba(143,106,69,0.45)] bg-[rgba(232,218,198,0.9)] text-[color:var(--palace-accent-2)]',
        tone === 'neutral' && 'border-[color:var(--palace-line)] bg-[rgba(255,250,244,0.84)] text-[color:var(--palace-muted)]'
      )}
    >
      {children}
    </span>
  );
}

function ResultCard({ item }) {
  const { t, i18n } = useTranslation();
  const finalScore = item?.scores?.final;
  const scoreText = finalScore === undefined ? '-' : Number(finalScore).toFixed(4);
  const uri = item?.uri || '-';
  const snippet = item?.snippet || t('observability.result.emptySnippet');
  const metadata = item?.metadata || {};
  const source = metadata.source || metadata.match_type || 'global';
  const sourceLabel = translateObservabilityToken(t, 'sources', source, source);
  const localeKey = i18n.resolvedLanguage || i18n.language || 'en';
  const updatedAtLabel = metadata.updated_at
    ? formatDateTime(metadata.updated_at, localeKey)
    : t('observability.result.updatedAtUnknown');

  return (
    <article className="rounded-2xl border border-[color:var(--palace-line)] bg-[rgba(255,250,244,0.9)] p-4 shadow-[var(--palace-shadow-sm)] transition duration-200 hover:border-[color:var(--palace-accent-2)] hover:shadow-[var(--palace-shadow-md)]">
      <header className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <code className="break-all text-xs text-[color:var(--palace-accent-2)]">{uri}</code>
        <div className="flex items-center gap-2">
          <Badge tone="neutral">{t('observability.result.score', { value: scoreText })}</Badge>
          <Badge tone={source === 'session_queue' ? 'good' : 'neutral'}>{sourceLabel}</Badge>
        </div>
      </header>
      <p className="mb-3 whitespace-pre-wrap text-sm leading-relaxed text-[color:var(--palace-ink)]">{snippet}</p>
      <footer className="flex flex-wrap gap-2 text-[11px] text-[color:var(--palace-muted)]">
        <span>{t('observability.result.memory', { value: item?.memory_id ?? '-' })}</span>
        <span>{t('observability.result.priority', { value: metadata.priority ?? '-' })}</span>
        <span>{updatedAtLabel}</span>
      </footer>
    </article>
  );
}

export default function ObservabilityPage() {
  const { t, i18n } = useTranslation();
  const [summary, setSummary] = useState(/** @type {ObservabilitySummary | null} */ (null));
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [summaryErrorState, setSummaryErrorState] = useState(/** @type {ObservabilityErrorState | null} */ (null));
  const [authRefreshToken, setAuthRefreshToken] = useState(0);

  const [searching, setSearching] = useState(false);
  const [searchErrorState, setSearchErrorState] = useState(/** @type {ObservabilityErrorState | null} */ (null));
  const [searchResult, setSearchResult] = useState(/** @type {SearchDiagnostics | null} */ (null));

  const [rebuilding, setRebuilding] = useState(false);
  const [rebuildMessage, setRebuildMessage] = useState(/** @type {string | null} */ (null));
  const [sleepConsolidating, setSleepConsolidating] = useState(false);
  const [jobActionKey, setJobActionKey] = useState(/** @type {string | null} */ (null));
  const [activeJob, setActiveJob] = useState(/** @type {IndexJob | null} */ (null));
  const [activeJobLoading, setActiveJobLoading] = useState(false);
  const [detailJobErrorState, setDetailJobErrorState] = useState(/** @type {ObservabilityErrorState | null} */ (null));
  const [inspectedJobId, setInspectedJobId] = useState(/** @type {string | null} */ (null));
  const [sseConnected, setSseConnected] = useState(true);
  const summaryRequestSeqRef = useRef(0);
  const maintenanceAuthFingerprint = getMaintenanceAuthFingerprint();
  const maintenanceAuthFingerprintRef = useRef(maintenanceAuthFingerprint);
  const sseFocusReconnectNeededRef = useRef(false);
  const initialDefaultQuery = coerceTranslationText(
    i18n.t('observability.defaultQuery', { lng: i18n.resolvedLanguage || i18n.language || 'en' }),
  );
  const previousDefaultQueryRef = useRef(initialDefaultQuery);

  const [form, setForm] = useState(/** @returns {SearchFormState} */ (() => ({
    query: initialDefaultQuery,
    mode: 'hybrid',
    maxResults: '8',
    candidateMultiplier: '4',
    includeSession: true,
    sessionId: 'api-observability',
    domain: '',
    pathPrefix: '',
    scopeHint: '',
    maxPriority: '',
  })));
  const activeJobId = summary?.health?.runtime?.index_worker?.active_job_id || null;
  const detailJobId = inspectedJobId || activeJobId || null;
  const summaryTimestamp = summary?.timestamp || '';
  const localeKey = i18n.resolvedLanguage || i18n.language || 'en';
  const summaryError = useMemo(() => {
    if (!summaryErrorState) return null;
    return extractApiError(summaryErrorState.error, i18n.t(summaryErrorState.fallbackKey, { lng: localeKey }));
  }, [summaryErrorState, i18n, localeKey]);
  const searchError = useMemo(() => {
    if (!searchErrorState) return null;
    return extractApiError(searchErrorState.error, i18n.t(searchErrorState.fallbackKey, { lng: localeKey }));
  }, [searchErrorState, i18n, localeKey]);
  const detailJobError = useMemo(() => {
    if (!detailJobErrorState) return null;
    return extractApiError(
      detailJobErrorState.error,
      coerceTranslationText(i18n.t(detailJobErrorState.fallbackKey, {
        lng: localeKey,
        ...(detailJobErrorState.fallbackValues || {}),
      }))
    );
  }, [detailJobErrorState, i18n, localeKey]);

  useEffect(() => {
    const nextDefaultQuery = coerceTranslationText(
      i18n.t('observability.defaultQuery', { lng: localeKey }),
    );
    setForm((prev) => {
      const shouldUpdate = prev.query === previousDefaultQueryRef.current;
      previousDefaultQueryRef.current = nextDefaultQuery;
      if (!shouldUpdate) return prev;
      return { ...prev, query: nextDefaultQuery };
    });
  }, [i18n, localeKey]);

  const loadSummary = useCallback(async () => {
    const requestSeq = summaryRequestSeqRef.current + 1;
    summaryRequestSeqRef.current = requestSeq;
    setSummaryLoading(true);
    setSummaryErrorState(null);
    try {
      const data = await getObservabilitySummary();
      if (requestSeq !== summaryRequestSeqRef.current) return;
      setSummary(data);
    } catch (err) {
      if (requestSeq !== summaryRequestSeqRef.current) return;
      setSummaryErrorState({
        error: err,
        fallbackKey: 'observability.summaryError',
      });
    } finally {
      if (requestSeq !== summaryRequestSeqRef.current) return;
      setSummaryLoading(false);
    }
  }, []);

  useEffect(() => {
    loadSummary();
  }, [loadSummary]);

  useEffect(() => {
    if (maintenanceAuthFingerprint === maintenanceAuthFingerprintRef.current) {
      return;
    }
    maintenanceAuthFingerprintRef.current = maintenanceAuthFingerprint;
    setAuthRefreshToken((value) => value + 1);
  }, [maintenanceAuthFingerprint]);

  useEffect(() => {
    const handleAuthChange = ({ force = false } = {}) => {
      const nextFingerprint = getMaintenanceAuthFingerprint();
      if (!force && nextFingerprint === maintenanceAuthFingerprintRef.current) {
        return;
      }
      maintenanceAuthFingerprintRef.current = nextFingerprint;
      setAuthRefreshToken((value) => value + 1);
    };
    const handleFocus = () => {
      if (!sseFocusReconnectNeededRef.current) {
        return;
      }
      handleAuthChange({ force: true });
    };

    const detach = subscribeMaintenanceAuthChanges(handleAuthChange);
    window.addEventListener('focus', handleFocus);

    return () => {
      detach();
      window.removeEventListener('focus', handleFocus);
    };
  }, []);

  useEffect(() => {
    let eventSource;
    try {
      sseFocusReconnectNeededRef.current = false;
      setSseConnected(true);
      const maintenanceAuth = getMaintenanceAuthState();
      eventSource = createEventSource('/sse/', {
        auth: maintenanceAuth
          ? {
            key: maintenanceAuth.key,
            mode: maintenanceAuth.mode === 'bearer' ? 'bearer' : 'header',
          }
          : null,
        resolveAuth: () => {
          const currentAuth = getMaintenanceAuthState();
          return currentAuth
            ? {
              key: currentAuth.key,
              mode: currentAuth.mode === 'bearer' ? 'bearer' : 'header',
            }
            : null;
        },
      });
    } catch (_error) {
      setSseConnected(false);
      return undefined;
    }

    const handleSseOpen = () => {
      sseFocusReconnectNeededRef.current = false;
      setSseConnected(true);
    };
    const refreshFromLiveEvent = () => {
      sseFocusReconnectNeededRef.current = false;
      setSseConnected(true);
      void loadSummary();
    };
    const handleSseError = (event = {}) => {
      const error = event?.error;
      if (error?.retryable === false) {
        sseFocusReconnectNeededRef.current = true;
      }
      setSseConnected(false);
    };
    const detachListeners = bindEventSourceListeners(
      eventSource,
      DEFAULT_SSE_REFRESH_EVENT_NAMES,
      refreshFromLiveEvent,
    );
    eventSource?.addEventListener?.('open', handleSseOpen);
    eventSource?.addEventListener?.('error', handleSseError);

    return () => {
      detachListeners();
      eventSource?.removeEventListener?.('open', handleSseOpen);
      eventSource?.removeEventListener?.('error', handleSseError);
      if (typeof eventSource?.close === 'function') {
        eventSource.close();
      }
    };
  }, [authRefreshToken, loadSummary]);

  useEffect(() => {
    let disposed = false;
    if (!detailJobId) {
      setActiveJob(null);
      setActiveJobLoading(false);
      setDetailJobErrorState(null);
      return () => {
        disposed = true;
      };
    }

    const loadActiveJob = async () => {
      setActiveJob(null);
      setActiveJobLoading(true);
      setDetailJobErrorState(null);
      try {
        const payload = /** @type {{ job?: IndexJob | null } | null} */ (await getIndexJob(detailJobId));
        if (!disposed) {
          setActiveJob(payload?.job || null);
        }
      } catch (err) {
        if (!disposed) {
          setActiveJob(null);
          setDetailJobErrorState({
            error: err,
            fallbackKey: 'observability.messages.activeJobLoadFailed',
            fallbackValues: { job: detailJobId },
          });
          const statusCode = err?.response?.status;
          if (statusCode === 404) {
            setInspectedJobId((prev) => (prev === detailJobId ? null : prev));
          }
        }
      } finally {
        if (!disposed) {
          setActiveJobLoading(false);
        }
      }
    };

    loadActiveJob();
    return () => {
      disposed = true;
    };
  }, [detailJobId, summaryTimestamp]);

  /**
   * @param {keyof SearchFormState} name
   * @param {SearchFormState[keyof SearchFormState]} value
   */
  const onFieldChange = (name, value) => {
    setForm((prev) => ({ ...prev, [name]: value }));
  };

  /** @param {React.FormEvent<HTMLFormElement>} event */
  const runSearch = async (event) => {
    event.preventDefault();
    setSearching(true);
    setSearchErrorState(null);
    setRebuildMessage(null);
    try {
      const filters = {};
      if (form.domain.trim()) filters.domain = form.domain.trim();
      if (form.pathPrefix.trim()) filters.path_prefix = form.pathPrefix.trim();
      const maxPriority = parseOptionalNonNegativeInteger(
        form.maxPriority,
        t('observability.maxPriorityFilter'),
        t,
      );
      if (maxPriority !== null) {
        filters.max_priority = maxPriority;
      }

      /** @type {ObservabilitySearchPayload} */
      const payload = {
        query: form.query,
        mode: form.mode,
        max_results: parseRequiredIntegerInRange(form.maxResults, t('observability.maxResults'), t, {
          min: 1,
          max: 50,
        }),
        candidate_multiplier: parseRequiredIntegerInRange(
          form.candidateMultiplier,
          t('observability.candidateMultiplier'),
          t,
          { min: 1, max: 20 }
        ),
        include_session: form.includeSession,
        session_id: form.sessionId.trim() || null,
        filters,
      };
      if (form.scopeHint.trim()) {
        payload.scope_hint = form.scopeHint.trim();
      }

      const data = /** @type {SearchDiagnostics} */ (await runObservabilitySearch(payload));
      setSearchResult(data);
      await loadSummary();
    } catch (err) {
      setSearchErrorState({
        error: err,
        fallbackKey: 'observability.diagnosticSearchFailed',
      });
    } finally {
      setSearching(false);
    }
  };

  const handleRebuild = async () => {
    setRebuilding(true);
    setRebuildMessage(null);
    try {
      const data = await triggerIndexRebuild({
        reason: 'observability_console',
        wait: false,
      });
      const requestTarget = formatObservabilityRequestTarget(t, data?.job_id);
      setRebuildMessage(t('observability.messages.rebuildRequested', { job: requestTarget }));
      await loadSummary();
    } catch (err) {
      setRebuildMessage(t('observability.messages.rebuildFailed', { detail: extractApiError(err) }));
    } finally {
      setRebuilding(false);
    }
  };

  const handleSleepConsolidation = async () => {
    setSleepConsolidating(true);
    setRebuildMessage(null);
    try {
      const data = await triggerSleepConsolidation({
        reason: 'observability_console',
        wait: false,
      });
      const requestTarget = formatObservabilityRequestTarget(t, data?.job_id);
      setRebuildMessage(t('observability.messages.sleepRequested', { job: requestTarget }));
      await loadSummary();
    } catch (err) {
      setRebuildMessage(t('observability.messages.sleepFailed', { detail: extractApiError(err) }));
    } finally {
      setSleepConsolidating(false);
    }
  };

  /** @param {string | null | undefined} jobId */
  const handleCancelJob = async (jobId) => {
    if (!jobId) return;
    const actionKey = `cancel:${jobId}`;
    setJobActionKey(actionKey);
    setRebuildMessage(null);
    try {
      await cancelIndexJob(jobId, { reason: 'observability_console_cancel' });
      setRebuildMessage(t('observability.messages.cancelRequested', { job: jobId }));
      await loadSummary();
    } catch (err) {
      const statusCode = err?.response?.status;
      const detail = extractApiError(err, t('observability.messages.cancelRequestFailed'));
      const normalizedDetail = detail.trim().toLowerCase();
      const isJobNotFound =
        normalizedDetail.includes('job_not_found') ||
        (normalizedDetail.includes('job') && normalizedDetail.includes('not found'));
      const isAlreadyFinalized =
        normalizedDetail.includes('job_already_finalized') ||
        (normalizedDetail.includes('already') && normalizedDetail.includes('final'));
      if (statusCode === 404) {
        if (isJobNotFound) {
          setRebuildMessage(
            t('observability.messages.cancelSkipped', {
              job: jobId,
              detail: t('observability.messages.cancelJobNotFoundDetail'),
            })
          );
          await loadSummary();
        } else {
          setRebuildMessage(t('observability.messages.cancelFailed', { job: jobId, detail }));
        }
      } else if (statusCode === 409) {
        if (isAlreadyFinalized) {
          setRebuildMessage(
            t('observability.messages.cancelSkipped', {
              job: jobId,
              detail: t('observability.messages.cancelAlreadyFinalizedDetail'),
            })
          );
          await loadSummary();
        } else {
          setRebuildMessage(t('observability.messages.cancelFailed', { job: jobId, detail }));
        }
      } else {
        setRebuildMessage(t('observability.messages.cancelFailed', { job: jobId, detail }));
      }
    } finally {
      setJobActionKey(null);
    }
  };

  /** @param {IndexJob | null | undefined} job */
  const handleRetryJob = async (job) => {
    const jobId = job?.job_id;
    if (!jobId) return;
    const actionKey = `retry:${jobId}`;
    setJobActionKey(actionKey);
    setRebuildMessage(null);

    const retryReason = `retry:${jobId}`;
    const taskType = String(job?.task_type || '');
    const retryMemoryId = Number(job?.memory_id);
    try {
      /** @type {JobActionResponse | null} */
      let payload = null;
      try {
        payload = /** @type {JobActionResponse | null} */ (await retryIndexJob(jobId, { reason: retryReason }));
      } catch (err) {
        if (isRetryEndpointUnsupported(err)) {
          if (taskType === 'reindex_memory' && Number.isInteger(retryMemoryId) && retryMemoryId > 0) {
            payload = /** @type {JobActionResponse | null} */ (await triggerMemoryReindex(retryMemoryId, {
              reason: retryReason,
              wait: false,
            }));
          } else if (taskType === 'rebuild_index') {
            payload = /** @type {JobActionResponse | null} */ (await triggerIndexRebuild({
              reason: retryReason,
              wait: false,
            }));
          } else if (taskType === 'sleep_consolidation') {
            payload = /** @type {JobActionResponse | null} */ (await triggerSleepConsolidation({
              reason: retryReason,
              wait: false,
            }));
          } else {
            throw new Error(t('observability.messages.retryUnsupported', {
              taskType: taskType || 'unknown',
            }));
          }
        } else {
          throw err;
        }
      }
      const requestTarget = formatObservabilityRequestTarget(t, payload?.job_id);
      setRebuildMessage(t('observability.messages.retryRequested', { job: requestTarget }));
      await loadSummary();
    } catch (err) {
      setRebuildMessage(t('observability.messages.retryFailed', {
        job: jobId,
        detail: extractApiError(err),
      }));
    } finally {
      setJobActionKey(null);
    }
  };

  const searchStats = summary?.search_stats || {};
  const latency = searchStats.latency_ms || {};
  const health = summary?.health || {};
  const indexHealth = health.index || {};
  const runtime = health.runtime || {};
  const worker = runtime.index_worker || {};
  const sleepConsolidation = runtime.sleep_consolidation || summary?.sleep_consolidation || {};
  const smLite = runtime.sm_lite || {};
  const smSession = smLite.session_cache || {};
  const smFlush = smLite.flush_tracker || {};
  const indexLatency = summary?.index_latency || {};
  const cleanupQueryStats = summary?.cleanup_query_stats || {};
  const cleanupLatency = cleanupQueryStats.latency_ms || {};
  const reflectionWorkflow = summary?.reflection_workflow || null;
  const recentJobs = Array.isArray(worker.recent_jobs) ? worker.recent_jobs : [];
  const viewingActiveJob = Boolean(detailJobId && activeJobId && detailJobId === activeJobId);

  const modeBreakdown = useMemo(() => {
    const breakdown = searchStats.mode_breakdown || {};
    return Object.entries(breakdown);
  }, [searchStats.mode_breakdown]);

  const intentBreakdown = useMemo(() => {
    const breakdown = searchStats.intent_breakdown || {};
    return Object.entries(breakdown);
  }, [searchStats.intent_breakdown]);

  const strategyBreakdown = useMemo(() => {
    const breakdown = searchStats.strategy_hit_breakdown || {};
    return Object.entries(breakdown);
  }, [searchStats.strategy_hit_breakdown]);
  const runtimeStatusLabel = translateObservabilityToken(
    t,
    'statusValues',
    summary?.status,
    t('common.states.unknown'),
  );
  const reflectionWorkflowSummary = useMemo(() => {
    if (!reflectionWorkflow || typeof reflectionWorkflow !== 'object') return null;
    const prepared = coerceNonNegativeNumber(reflectionWorkflow.prepared);
    const executed = coerceNonNegativeNumber(reflectionWorkflow.executed);
    const rolledBack = coerceNonNegativeNumber(reflectionWorkflow.rolled_back);
    return t('observability.runtime.reflectionWorkflow', {
      prepared,
      executed,
      rolledBack,
    });
  }, [reflectionWorkflow, t]);

  return (
    <div className="palace-harmonized flex h-full flex-col overflow-hidden bg-[color:var(--palace-bg)] text-[color:var(--palace-ink)] selection:bg-[rgba(179,133,79,0.28)] selection:text-[color:var(--palace-ink)]">
      <header className="border-b border-[color:var(--palace-line)] bg-[radial-gradient(circle_at_top_right,rgba(198,165,126,0.24),rgba(241,232,220,0.72),rgba(246,242,234,0.92)_58%)] px-6 py-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="font-display flex items-center gap-2 text-lg text-[color:var(--palace-ink)]">
              <Radar size={18} className="text-[color:var(--palace-accent)]" />
              {t('observability.title')}
            </h1>
            <p className="mt-1 text-sm text-[color:var(--palace-muted)]">
              {t('observability.subtitle')}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={loadSummary}
              disabled={summaryLoading}
              className="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-[color:var(--palace-line)] bg-white/88 px-3 py-2 text-xs font-medium text-[color:var(--palace-muted)] transition-colors hover:border-[color:var(--palace-accent)] hover:text-[color:var(--palace-ink)] disabled:cursor-not-allowed disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-[color:var(--palace-accent)]/35"
            >
              <RefreshCw size={14} className={summaryLoading ? 'animate-spin' : ''} />
              {t('observability.refresh')}
            </button>
            <button
              type="button"
              onClick={handleRebuild}
              disabled={rebuilding}
              className="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-[color:var(--palace-accent)] bg-[linear-gradient(135deg,rgba(198,165,126,0.38),rgba(255,250,244,0.9))] px-3 py-2 text-xs font-medium text-[color:var(--palace-ink)] transition-colors hover:border-[color:var(--palace-accent-2)] hover:bg-[linear-gradient(135deg,rgba(190,154,112,0.42),rgba(255,250,244,0.95))] disabled:cursor-not-allowed disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-[color:var(--palace-accent)]/35"
            >
              {rebuilding ? (
                <RefreshCw size={14} className="animate-spin" />
              ) : (
                <Wrench size={14} />
              )}
              {t('observability.rebuildIndex')}
            </button>
            <button
              type="button"
              onClick={handleSleepConsolidation}
              disabled={sleepConsolidating}
              className="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-[color:var(--palace-line)] bg-white/88 px-3 py-2 text-xs font-medium text-[color:var(--palace-muted)] transition-colors hover:border-[color:var(--palace-accent)] hover:text-[color:var(--palace-ink)] disabled:cursor-not-allowed disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-[color:var(--palace-accent)]/35"
            >
              {sleepConsolidating ? (
                <RefreshCw size={14} className="animate-spin" />
              ) : (
                <TimerReset size={14} />
              )}
              {t('observability.sleepConsolidation')}
            </button>
          </div>
        </div>
        {rebuildMessage && (
          <p className="mt-3 text-xs text-[color:var(--palace-muted)]">{rebuildMessage}</p>
        )}
        {!sseConnected && (
          <div
            role="status"
            aria-live="polite"
            className="mt-3 inline-flex items-center gap-2 rounded-md border border-amber-300/70 bg-amber-50/90 px-3 py-2 text-xs text-amber-800"
          >
            <WifiOff size={13} />
            {t('common.states.connectionLost')}
          </div>
        )}
        {summaryError && (
          <div className="mt-3 inline-flex items-center gap-2 rounded-md border border-[rgba(143,106,69,0.45)] bg-[rgba(232,218,198,0.88)] px-3 py-2 text-xs text-[color:var(--palace-accent-2)]">
            <AlertTriangle size={13} />
            {summaryError}
          </div>
        )}
      </header>

      <main className="flex-1 overflow-y-auto px-6 py-5">
        <section className="mb-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-6">
          <StatCard
            icon={Search}
            label={t('observability.stats.queries')}
            value={formatNumber(searchStats.total_queries, i18n.resolvedLanguage)}
            hint={t('observability.stats.degraded', {
              count: toTranslationCount(searchStats.degraded_queries),
            })}
            tone="neutral"
          />
          <StatCard
            icon={TimerReset}
            label={t('observability.stats.latency')}
            value={formatMs(latency.avg)}
            hint={t('observability.stats.p95Hint', {
              value: formatMs(latency.p95),
            })}
            tone="neutral"
          />
          <StatCard
            icon={Zap}
            label={t('observability.stats.cacheHitRatio')}
            value={`${((searchStats.cache_hit_ratio || 0) * 100).toFixed(1)}%`}
            hint={t('observability.stats.hitQueries', {
              count: toTranslationCount(searchStats.cache_hit_queries),
            })}
            tone={searchStats.cache_hit_ratio > 0.4 ? 'good' : 'neutral'}
          />
          <StatCard
            icon={Gauge}
            label={t('observability.stats.indexLatency')}
            value={formatMs(indexLatency.avg_ms)}
            hint={t('observability.stats.samples', {
              count: toTranslationCount(indexLatency.samples),
            })}
            tone={indexLatency.samples > 0 ? 'neutral' : 'warn'}
          />
          <StatCard
            icon={Database}
            label={t('observability.stats.cleanupP95')}
            value={formatMs(cleanupLatency.p95)}
            hint={t('observability.stats.slow', {
              count: toTranslationCount(cleanupQueryStats.slow_queries),
              threshold: formatMs(cleanupQueryStats.slow_threshold_ms),
            })}
            tone={cleanupQueryStats.slow_queries > 0 ? 'warn' : 'neutral'}
          />
          <StatCard
            icon={Activity}
            label={t('observability.stats.cleanupIndexHit')}
            value={`${((cleanupQueryStats.index_hit_ratio || 0) * 100).toFixed(1)}%`}
            hint={t('observability.stats.fullScan', {
              count: toTranslationCount(cleanupQueryStats.full_scan_queries),
            })}
            tone={cleanupQueryStats.index_hit_ratio >= 0.9 ? 'good' : cleanupQueryStats.index_hit_ratio >= 0.5 ? 'neutral' : 'warn'}
          />
        </section>

        <div className="mb-5">
          <SearchQualityPanel />
        </div>

        <section className="grid gap-4 xl:grid-cols-[360px_1fr]">
          <div className="space-y-4">
            <form
              onSubmit={runSearch}
              noValidate
              className={PANEL_CLASS}
            >
              <h2 className="mb-4 flex items-center gap-2 text-sm font-semibold text-[color:var(--palace-ink)]">
                <Activity size={15} className="text-[color:var(--palace-accent)]" />
                {t('observability.searchConsole')}
              </h2>

              <label htmlFor="obs-query-input" className={LABEL_CLASS}>
                {t('observability.query')}
              </label>
              <input
                id="obs-query-input"
                name="query"
                value={form.query}
                onChange={(e) => onFieldChange('query', e.target.value)}
                className={`mb-3 ${INPUT_CLASS}`}
                placeholder={t('observability.placeholders.query')}
              />

              <div className="mb-3 grid grid-cols-2 gap-2">
                <div>
                  <label htmlFor="obs-mode-select" className={LABEL_CLASS}>
                    {t('observability.mode')}
                  </label>
                  <select
                    id="obs-mode-select"
                    name="mode"
                    value={form.mode}
                    onChange={(e) => onFieldChange('mode', e.target.value)}
                    className={INPUT_CLASS}
                  >
                    {MODE_OPTIONS.map((option) => (
                      <option key={option} value={option}>
                        {t(`observability.modes.${option}`, { defaultValue: option })}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label htmlFor="obs-session-id-input" className={LABEL_CLASS}>
                    {t('observability.sessionId')}
                  </label>
                  <input
                    id="obs-session-id-input"
                    name="session_id"
                    value={form.sessionId}
                    onChange={(e) => onFieldChange('sessionId', e.target.value)}
                    className={INPUT_CLASS}
                    placeholder={t('observability.placeholders.sessionId')}
                  />
                </div>
              </div>

              <div className="mb-3 grid grid-cols-2 gap-2">
                <div>
                  <label htmlFor="obs-max-results-input" className={LABEL_CLASS}>
                    {t('observability.maxResults')}
                  </label>
                  <input
                    id="obs-max-results-input"
                    name="max_results"
                    type="number"
                    min="1"
                    max="50"
                    value={form.maxResults}
                    onChange={(e) => onFieldChange('maxResults', e.target.value)}
                    className={INPUT_CLASS}
                  />
                </div>
                <div>
                  <label htmlFor="obs-candidate-multiplier-input" className={LABEL_CLASS}>
                    {t('observability.candidateMultiplier')}
                  </label>
                  <input
                    id="obs-candidate-multiplier-input"
                    name="candidate_multiplier"
                    type="number"
                    min="1"
                    max="20"
                    value={form.candidateMultiplier}
                    onChange={(e) => onFieldChange('candidateMultiplier', e.target.value)}
                    className={INPUT_CLASS}
                  />
                </div>
              </div>

              <div className="mb-3 grid grid-cols-2 gap-2">
                <input
                  id="obs-domain-filter-input"
                  name="domain_filter"
                  aria-label={t('observability.domainFilter')}
                  value={form.domain}
                  onChange={(e) => onFieldChange('domain', e.target.value)}
                  className={INPUT_CLASS}
                  placeholder={t('observability.placeholders.domainFilter')}
                />
                <input
                  id="obs-path-prefix-input"
                  name="path_prefix"
                  aria-label={t('observability.pathPrefixFilter')}
                  value={form.pathPrefix}
                  onChange={(e) => onFieldChange('pathPrefix', e.target.value)}
                  className={INPUT_CLASS}
                  placeholder={t('observability.placeholders.pathPrefix')}
                />
              </div>

              <div className="mb-3">
                <input
                  id="obs-scope-hint-input"
                  name="scope_hint"
                  aria-label={t('observability.scopeHint')}
                  value={form.scopeHint}
                  onChange={(e) => onFieldChange('scopeHint', e.target.value)}
                  className={INPUT_CLASS}
                  placeholder={t('observability.placeholders.scopeHint')}
                />
              </div>

              <div className="mb-4 flex items-center justify-between gap-2">
                <input
                  id="obs-max-priority-input"
                  name="max_priority"
                  type="number"
                  min="0"
                  step="1"
                  aria-label={t('observability.maxPriorityFilter')}
                  value={form.maxPriority}
                  onChange={(e) => onFieldChange('maxPriority', e.target.value)}
                  className={INPUT_CLASS}
                  placeholder={t('observability.placeholders.maxPriority')}
                />
                <label
                  htmlFor="obs-include-session-checkbox"
                  className="inline-flex cursor-pointer items-center gap-2 text-xs text-[color:var(--palace-muted)]"
                >
                  <input
                    id="obs-include-session-checkbox"
                    name="include_session"
                    type="checkbox"
                    checked={form.includeSession}
                    onChange={(e) => onFieldChange('includeSession', e.target.checked)}
                    className="h-4 w-4 rounded border-[color:var(--palace-line)] bg-white text-[color:var(--palace-accent)] focus:ring-[color:var(--palace-accent)]/40"
                  />
                  {t('observability.includeSessionFirst')}
                </label>
              </div>

              <button
                type="submit"
                disabled={searching}
                className="inline-flex w-full cursor-pointer items-center justify-center gap-2 rounded-lg border border-[color:var(--palace-accent)] bg-[linear-gradient(135deg,rgba(198,165,126,0.34),rgba(255,250,244,0.92))] px-3 py-2 text-sm font-medium text-[color:var(--palace-ink)] transition-colors hover:border-[color:var(--palace-accent-2)] hover:bg-[linear-gradient(135deg,rgba(191,154,110,0.42),rgba(255,250,244,0.95))] disabled:cursor-not-allowed disabled:opacity-60 focus:outline-none focus:ring-2 focus:ring-[color:var(--palace-accent)]/35"
              >
                {searching ? (
                  <RefreshCw size={14} className="animate-spin" />
                ) : (
                  <Search size={14} />
                )}
                {t('observability.runDiagnosticSearch')}
              </button>

              {searchError && (
                <div className="mt-3 rounded-md border border-[rgba(143,106,69,0.45)] bg-[rgba(232,218,198,0.88)] px-3 py-2 text-xs text-[color:var(--palace-accent-2)]">
                  {searchError}
                </div>
              )}
            </form>

            <div className={PANEL_CLASS}>
              <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold text-[color:var(--palace-ink)]">
                <Database size={15} className="text-[color:var(--palace-accent)]" />
                {t('observability.runtimeSnapshot')}
              </h3>
              <div className="space-y-2 text-xs text-[color:var(--palace-muted)]">
                <p className="flex items-center gap-2">
                  {summary?.status === 'ok' ? (
                    <CheckCircle2 size={13} className="text-[color:var(--palace-accent)]" />
                  ) : (
                    <AlertTriangle size={13} className="text-[color:var(--palace-accent-2)]" />
                  )}
                  {t('observability.runtime.status', { value: runtimeStatusLabel })}
                </p>
                <p>{t('observability.runtime.indexDegraded', { value: translateObservabilityBoolean(t, Boolean(indexHealth.degraded)) })}</p>
                <p>{t('observability.runtime.queueDepth', { value: worker.queue_depth ?? '-' })}</p>
                <p>{t('observability.runtime.activeJob', { value: worker.active_job_id || '-' })}</p>
                <p>{t('observability.runtime.cancellingJobs', { value: worker.cancelling_jobs ?? 0 })}</p>
                <p>{t('observability.runtime.lastWorkerError', { value: worker.last_error || '-' })}</p>
                <p>{t('observability.runtime.sleepPending', { value: translateObservabilityBoolean(t, Boolean(worker.sleep_pending)) })}</p>
                <p>{t('observability.runtime.sleepLastReason', { value: sleepConsolidation.reason || '-' })}</p>
                <p>{t('observability.runtime.smLiteSessions', { value: smSession.session_count ?? '-' })}</p>
                <p>{t('observability.runtime.smLitePendingEvents', { value: smFlush.pending_events ?? '-' })}</p>
                <p>{t('observability.runtime.smLiteDegraded', { value: translateObservabilityBoolean(t, Boolean(smLite.degraded)) })}</p>
                <p>{t('observability.runtime.smLiteReason', { value: smLite.reason || '-' })}</p>
                <p>{t('observability.runtime.cleanupQueries', { value: formatNumber(cleanupQueryStats.total_queries, i18n.resolvedLanguage) })}</p>
                {reflectionWorkflowSummary && <p>{reflectionWorkflowSummary}</p>}
                <p>{t('observability.runtime.updatedAt', { value: summary?.timestamp || '-' })}</p>
              </div>
            </div>

            <div className={PANEL_CLASS}>
              <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold text-[color:var(--palace-ink)]">
                <Wrench size={15} className="text-[color:var(--palace-accent)]" />
                {t('observability.indexTaskQueue')}
              </h3>
              {activeJobLoading && (
                <p className="mb-2 text-xs text-[color:var(--palace-muted)]">
                  {t('observability.job.loadingActive')}
                </p>
              )}
              {detailJobError && (
                <p className="mb-2 text-xs text-[color:var(--palace-accent-2)]">
                  {detailJobError}
                </p>
              )}
              {detailJobId && activeJob && (
                (() => {
                  const jobId = String(activeJob.job_id || detailJobId);
                  const status = String(activeJob.status || 'unknown');
                  const taskType = String(activeJob.task_type || 'unknown');
                  const statusLabel = translateObservabilityToken(t, 'statusValues', status, status);
                  const taskTypeLabel = translateObservabilityToken(t, 'taskTypes', taskType, taskType);
                  const canCancel = ['queued', 'running', 'cancelling'].includes(status);
                  const canRetry = ['failed', 'dropped', 'cancelled'].includes(status);
                  const cancelPending = jobActionKey === `cancel:${jobId}`;
                  const retryPending = jobActionKey === `retry:${jobId}`;
                  const errorText = activeJob?.error || activeJob?.result?.error || '-';
                  const degradeReasons = Array.isArray(activeJob?.result?.degrade_reasons)
                    ? activeJob.result.degrade_reasons.join(', ')
                    : '-';
                  return (
                    <article className="mb-3 rounded-xl border border-[color:var(--palace-accent)]/45 bg-[rgba(255,248,238,0.9)] p-3 text-xs text-[color:var(--palace-muted)]">
                      <div className="mb-2 flex flex-wrap items-center gap-2">
                        <Badge tone={viewingActiveJob ? 'good' : 'neutral'}>
                          {viewingActiveJob ? t('observability.job.active') : t('observability.job.detail')}
                        </Badge>
                        <code className="text-[11px] text-[color:var(--palace-accent-2)]">{jobId}</code>
                        <Badge tone={getJobStatusTone(status)}>{statusLabel}</Badge>
                        <Badge tone="neutral">{taskTypeLabel}</Badge>
                      </div>
                      <div className="space-y-1">
                        <p>{t('observability.job.reason', { value: activeJob?.reason || '-' })}</p>
                        <p>{t('observability.job.memory', { value: activeJob?.memory_id ?? '-' })}</p>
                        <p>{t('observability.job.error', { value: errorText })}</p>
                        <p>{t('observability.job.cancelReason', { value: activeJob?.cancel_reason || '-' })}</p>
                        <p>{t('observability.job.degradeReasons', { value: degradeReasons || '-' })}</p>
                        <p>{t('observability.job.requested', { value: formatDateTime(activeJob?.requested_at, i18n.resolvedLanguage) })}</p>
                        <p>{t('observability.job.started', { value: formatDateTime(activeJob?.started_at, i18n.resolvedLanguage) })}</p>
                        <p>{t('observability.job.finished', { value: formatDateTime(activeJob?.finished_at, i18n.resolvedLanguage) })}</p>
                      </div>
                      <div className="mt-3 flex flex-wrap gap-2">
                        <button
                          type="button"
                          disabled={!canCancel || cancelPending}
                          onClick={() => handleCancelJob(jobId)}
                          className="inline-flex cursor-pointer items-center gap-1 rounded border border-[color:var(--palace-line)] bg-white/90 px-2 py-1 text-[11px] text-[color:var(--palace-muted)] transition-colors hover:border-[color:var(--palace-accent)] hover:text-[color:var(--palace-ink)] disabled:cursor-not-allowed disabled:opacity-45"
                        >
                          {cancelPending ? <RefreshCw size={12} className="animate-spin" /> : <AlertTriangle size={12} />}
                          {t('observability.job.cancel')}
                        </button>
                        <button
                          type="button"
                          disabled={!canRetry || retryPending}
                          onClick={() => handleRetryJob(activeJob)}
                          className="inline-flex cursor-pointer items-center gap-1 rounded border border-[color:var(--palace-line)] bg-white/90 px-2 py-1 text-[11px] text-[color:var(--palace-muted)] transition-colors hover:border-[color:var(--palace-accent)] hover:text-[color:var(--palace-ink)] disabled:cursor-not-allowed disabled:opacity-45"
                        >
                          {retryPending ? <RefreshCw size={12} className="animate-spin" /> : <RefreshCw size={12} />}
                          {t('observability.job.retry')}
                        </button>
                        {inspectedJobId && (
                          <button
                            type="button"
                            onClick={() => setInspectedJobId(null)}
                            className="inline-flex cursor-pointer items-center gap-1 rounded border border-[color:var(--palace-line)] bg-white/90 px-2 py-1 text-[11px] text-[color:var(--palace-muted)] transition-colors hover:border-[color:var(--palace-accent)] hover:text-[color:var(--palace-ink)]"
                          >
                            {activeJobId ? t('observability.job.backToActive') : t('observability.job.clearDetail')}
                          </button>
                        )}
                      </div>
                    </article>
                  );
                })()
              )}
              {recentJobs.length === 0 ? (
                <p className="text-xs text-[color:var(--palace-muted)]">
                  {t('observability.job.noRecentJobs')}
                </p>
              ) : (
                <div className="space-y-2">
                  {recentJobs.map((job) => {
                    const jobId = String(job?.job_id || 'unknown-job');
                    const status = String(job?.status || 'unknown');
                    const taskType = String(job?.task_type || 'unknown');
                    const statusLabel = translateObservabilityToken(t, 'statusValues', status, status);
                    const taskTypeLabel = translateObservabilityToken(t, 'taskTypes', taskType, taskType);
                    const canCancel = ['queued', 'running', 'cancelling'].includes(status);
                    const canRetry = ['failed', 'dropped', 'cancelled'].includes(status);
                    const cancelPending = jobActionKey === `cancel:${jobId}`;
                    const retryPending = jobActionKey === `retry:${jobId}`;
                    const errorText = job?.error || job?.result?.error || '-';

                    return (
                      <article
                        key={jobId}
                        className="rounded-xl border border-[color:var(--palace-line)] bg-[rgba(255,250,244,0.84)] p-3 text-xs text-[color:var(--palace-muted)]"
                      >
                        <div className="mb-2 flex flex-wrap items-center gap-2">
                          <code className="text-[11px] text-[color:var(--palace-accent-2)]">{jobId}</code>
                          <Badge tone={getJobStatusTone(status)}>{statusLabel}</Badge>
                          <Badge tone="neutral">{taskTypeLabel}</Badge>
                        </div>
                        <div className="space-y-1">
                          <p>{t('observability.job.reason', { value: job?.reason || '-' })}</p>
                          <p>{t('observability.job.memory', { value: job?.memory_id ?? '-' })}</p>
                          <p>{t('observability.job.error', { value: errorText })}</p>
                          <p>{t('observability.job.requested', { value: formatDateTime(job?.requested_at, i18n.resolvedLanguage) })}</p>
                          <p>{t('observability.job.started', { value: formatDateTime(job?.started_at, i18n.resolvedLanguage) })}</p>
                          <p>{t('observability.job.finished', { value: formatDateTime(job?.finished_at, i18n.resolvedLanguage) })}</p>
                        </div>
                        <div className="mt-3 flex flex-wrap gap-2">
                          <button
                            type="button"
                            disabled={!canCancel || cancelPending}
                            onClick={() => handleCancelJob(jobId)}
                            className="inline-flex cursor-pointer items-center gap-1 rounded border border-[color:var(--palace-line)] bg-white/90 px-2 py-1 text-[11px] text-[color:var(--palace-muted)] transition-colors hover:border-[color:var(--palace-accent)] hover:text-[color:var(--palace-ink)] disabled:cursor-not-allowed disabled:opacity-45"
                          >
                            {cancelPending ? <RefreshCw size={12} className="animate-spin" /> : <AlertTriangle size={12} />}
                            {t('observability.job.cancel')}
                          </button>
                          <button
                            type="button"
                            disabled={!canRetry || retryPending}
                            onClick={() => handleRetryJob(job)}
                            className="inline-flex cursor-pointer items-center gap-1 rounded border border-[color:var(--palace-line)] bg-white/90 px-2 py-1 text-[11px] text-[color:var(--palace-muted)] transition-colors hover:border-[color:var(--palace-accent)] hover:text-[color:var(--palace-ink)] disabled:cursor-not-allowed disabled:opacity-45"
                          >
                            {retryPending ? <RefreshCw size={12} className="animate-spin" /> : <RefreshCw size={12} />}
                            {t('observability.job.retry')}
                          </button>
                          <button
                            type="button"
                            onClick={() => setInspectedJobId(jobId)}
                            className="inline-flex cursor-pointer items-center gap-1 rounded border border-[color:var(--palace-line)] bg-white/90 px-2 py-1 text-[11px] text-[color:var(--palace-muted)] transition-colors hover:border-[color:var(--palace-accent)] hover:text-[color:var(--palace-ink)]"
                          >
                            {t('observability.job.inspect')}
                          </button>
                        </div>
                      </article>
                    );
                  })}
                </div>
              )}
            </div>

            {modeBreakdown.length > 0 && (
              <div className={PANEL_CLASS}>
                <h3 className="mb-3 text-sm font-semibold text-[color:var(--palace-ink)]">{t('observability.breakdown.mode')}</h3>
                <div className="flex flex-wrap gap-2">
                  {modeBreakdown.map(([mode, count]) => (
                    <Badge key={mode} tone="neutral">
                      {translateObservabilityToken(t, 'modes', mode, mode)}: {count}
                    </Badge>
                  ))}
                </div>
              </div>
            )}

            {intentBreakdown.length > 0 && (
              <div className={PANEL_CLASS}>
                <h3 className="mb-3 text-sm font-semibold text-[color:var(--palace-ink)]">{t('observability.breakdown.intent')}</h3>
                <div className="flex flex-wrap gap-2">
                  {intentBreakdown.map(([intent, count]) => (
                    <Badge key={intent} tone="neutral">
                      {translateObservabilityToken(t, 'intents', intent, intent)}: {count}
                    </Badge>
                  ))}
                </div>
              </div>
            )}

            {strategyBreakdown.length > 0 && (
              <div className={PANEL_CLASS}>
                <h3 className="mb-3 text-sm font-semibold text-[color:var(--palace-ink)]">{t('observability.breakdown.strategy')}</h3>
                <div className="flex flex-wrap gap-2">
                  {strategyBreakdown.map(([strategy, count]) => (
                    <Badge key={strategy} tone="neutral">
                      {translateObservabilityToken(t, 'strategies', strategy, strategy)}: {count}
                    </Badge>
                  ))}
                </div>
              </div>
            )}
          </div>

          <div className="space-y-4">
            <div className={PANEL_CLASS}>
              <h2 className="mb-3 text-sm font-semibold text-[color:var(--palace-ink)]">{t('observability.searchDiagnostics')}</h2>
              {!searchResult ? (
                <p className="text-sm text-[color:var(--palace-muted)]">
                  {t('observability.noSearchRun')}
                </p>
              ) : (
                <div className="space-y-3 text-xs text-[color:var(--palace-muted)]">
                  <div className="flex flex-wrap gap-2">
                    <Badge tone="neutral">{t('observability.diagnostics.latency', { value: formatMs(searchResult.latency_ms) })}</Badge>
                    <Badge tone="neutral">{t('observability.diagnostics.mode', {
                      value: translateObservabilityToken(t, 'modes', searchResult.mode_applied, searchResult.mode_applied || 'unknown'),
                    })}</Badge>
                    <Badge tone="neutral">
                      {t('observability.diagnostics.interactionTier', {
                        value: translateObservabilityToken(
                          t,
                          'interactionTiers',
                          searchResult.interaction_tier,
                          searchResult.interaction_tier || '-',
                        ),
                      })}
                    </Badge>
                    <Badge tone="neutral">
                      {t('observability.diagnostics.intent', {
                        value: translateObservabilityToken(
                          t,
                          'intents',
                          searchResult.intent_applied || searchResult.intent || 'unknown',
                          searchResult.intent_applied || searchResult.intent || 'unknown',
                        ),
                      })}
                    </Badge>
                    <Badge tone="neutral">
                      {t('observability.diagnostics.intentLlmAttempted', {
                        value: translateOptionalObservabilityBoolean(t, searchResult.intent_llm_attempted),
                      })}
                    </Badge>
                    <Badge tone="neutral">
                      {t('observability.diagnostics.strategy', {
                        value: translateObservabilityToken(
                          t,
                          'strategies',
                          searchResult.strategy_template_applied
                            || searchResult.strategy_template
                            || searchResult.intent_profile?.strategy_template
                            || 'default',
                          searchResult.strategy_template_applied
                            || searchResult.strategy_template
                            || searchResult.intent_profile?.strategy_template
                            || 'default',
                        ),
                      })}
                    </Badge>
                    <Badge tone={searchResult.degraded ? 'warn' : 'good'}>
                      {t('observability.diagnostics.degraded', {
                        value: translateObservabilityBoolean(t, Boolean(searchResult.degraded)),
                      })}
                    </Badge>
                    <Badge tone="neutral">
                      {t('observability.diagnostics.counts', {
                        session: searchResult.counts?.session ?? 0,
                        global: searchResult.counts?.global ?? 0,
                        returned: searchResult.counts?.returned ?? 0,
                      })}
                    </Badge>
                  </div>
                  {Array.isArray(searchResult.degrade_reasons) && searchResult.degrade_reasons.length > 0 && (
                    <div className="rounded-lg border border-[rgba(198,165,126,0.55)] bg-[rgba(240,230,215,0.78)] p-3">
                      <div className="mb-2 text-[11px] uppercase tracking-[0.14em] text-[color:var(--palace-accent-2)]">
                        {t('observability.diagnostics.degradeReasons')}
                      </div>
                      <div className="flex flex-wrap gap-2">
                        {searchResult.degrade_reasons.map((reason) => (
                          <Badge key={reason} tone="warn">
                            {reason}
                          </Badge>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>

            <div className="space-y-3">
              {searching && (
                <div className="flex items-center gap-2 rounded-lg border border-[color:var(--palace-line)] bg-[rgba(255,250,244,0.86)] px-3 py-2 text-sm text-[color:var(--palace-muted)]">
                  <RefreshCw size={14} className="animate-spin" />
                  {t('observability.runningQuery')}
                </div>
              )}
              {!searching && searchResult?.results?.length === 0 && (
                <div className="rounded-lg border border-[color:var(--palace-line)] bg-[rgba(255,250,244,0.86)] px-3 py-3 text-sm text-[color:var(--palace-muted)]">
                  {t('observability.noMatchedSnippets')}
                </div>
              )}
              {(searchResult?.results || []).map((item, idx) => (
                <ResultCard key={`${item.uri || 'result'}-${idx}`} item={item} />
              ))}
            </div>
          </div>
        </section>
      </main>
    </div>
  );
}
