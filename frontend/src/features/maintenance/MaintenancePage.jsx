import React, { useEffect, useMemo, useState, useCallback, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Trash2, Feather, AlertTriangle, RefreshCw,
  ChevronDown, ChevronUp, ArrowRight, Unlink, Archive, CheckSquare, Square, Minus
} from 'lucide-react';
import DiffViewer from '../../components/DiffViewer';
import {
  queryVitalityCleanupCandidates,
  prepareVitalityCleanup,
  confirmVitalityCleanup,
  triggerVitalityDecay,
  extractApiError,
  extractApiErrorCode,
  listOrphanMemories,
  getOrphanMemoryDetail,
  deleteOrphanMemory,
} from '../../lib/api';
import { formatDateTime } from '../../lib/format';
import { alertWithFallback, confirmWithFallback, promptWithFallback } from '../../lib/dialogs';
import ForgettingPanel from './ForgettingPanel';

const VITALITY_PREPARE_MAX_SELECTIONS = 100;
const DEFAULT_VITALITY_REVIEWER = 'maintenance_dashboard';
const ORPHAN_DELETE_CONCURRENCY = 4;

/**
 * @template T,R
 * @param {T[]} items
 * @param {number} limit
 * @param {(item: T, index: number) => Promise<R>} worker
 * @returns {Promise<R[]>}
 */
const mapWithConcurrency = async (items, limit, worker) => {
  const results = new Array(items.length);
  let nextIndex = 0;
  const workerCount = Math.min(Math.max(1, limit), items.length);

  await Promise.all(Array.from({ length: workerCount }, async () => {
    while (true) {
      const currentIndex = nextIndex;
      nextIndex += 1;
      if (currentIndex >= items.length) return;
      results[currentIndex] = await worker(items[currentIndex], currentIndex);
    }
  }));

  return results;
};

/**
 * @typedef {{ error: unknown, fallbackKey: string }} ApiErrorState
 * @typedef {{ type: 'translation', key: string, values?: Record<string, string | number> }} TranslationErrorState
 * @typedef {{ id?: string | number, paths?: string[], content?: string }} MigrationTarget
 * @typedef {{
 *   id: string | number,
 *   category?: string,
 *   created_at?: string,
 *   content_snippet?: string,
 *   migrated_to?: string | number | null,
 *   migration_target?: MigrationTarget | null,
 * }} OrphanEntry
 * @typedef {{ content?: string, migration_target?: MigrationTarget | null, errorState?: ApiErrorState }} OrphanDetail
 * @typedef {{ reason?: string }} VitalityDecayMeta
 * @typedef {{ status?: string, decay?: VitalityDecayMeta | null }} VitalityQueryMetaState
 * @typedef {{
 *   memory_id: string | number,
 *   state_hash?: string,
 *   can_delete?: boolean,
 *   uri?: string,
 *   content_snippet?: string,
 *   vitality_score?: string | number | null,
 *   inactive_days?: string | number | null,
 *   access_count?: string | number | null,
 * }} VitalityCandidate
 * @typedef {{
 *   review_id: string,
 *   token: string,
 *   confirmation_phrase: string,
 *   action?: string,
 *   reviewer?: string,
 * }} VitalityPreparedReviewState
 * @typedef {{
 *   status?: string,
 *   deleted_count?: number,
 *   kept_count?: number,
 *   skipped_count?: number,
 *   error_count?: number,
 * }} VitalityCleanupResultState
 * @typedef {number | string} NumericInputState
 */

/**
 * @param {string | number | Date | null | undefined} value
 * @param {string | undefined} lng
 * @param {string} fallback
 */
const formatDateTimeOrUnknown = (value, lng, fallback) => {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return fallback;
  return formatDateTime(parsed, lng, {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }) || fallback;
};

/** @param {unknown} value */
const normalizePaths = (value) => (Array.isArray(value) ? value : []);

const shouldPreservePreparedReviewAfterConfirmError = (error, detailCode) => {
  if (detailCode === 'confirmation_phrase_mismatch') {
    return true;
  }

  if (
    detailCode === 'maintenance_auth_failed'
    || detailCode === 'setup_access_denied'
    || detailCode === 'mcp_sse_auth_failed'
  ) {
    return true;
  }

  if (Number(error?.response?.status) === 401) {
    return true;
  }

  if (error?.response) {
    return false;
  }

  const errorCode = String(error?.code || '').trim().toUpperCase();
  if (errorCode === 'ECONNABORTED' || errorCode === 'ERR_NETWORK') {
    return true;
  }

  const message = String(error?.message || '').trim().toLowerCase();
  if (!message) {
    return false;
  }
  return (
    message === 'network error'
    || message === 'failed to fetch'
    || (message.includes('timeout of') && message.includes('ms exceeded'))
  );
};

export default function MaintenancePage() {
  const { t, i18n } = useTranslation();
  const [orphans, setOrphans] = useState(/** @type {OrphanEntry[]} */ ([]));
  const [loading, setLoading] = useState(false);
  const [errorState, setErrorState] = useState(/** @type {ApiErrorState | null} */ (null));

  const [expandedId, setExpandedId] = useState(/** @type {string | number | null} */ (null));
  const [detailData, setDetailData] = useState(/** @type {{ [key: string]: OrphanDetail }} */ ({}));
  const [detailLoading, setDetailLoading] = useState(/** @type {string | number | null} */ (null));

  const [selectedIds, setSelectedIds] = useState(/** @type {Set<string | number>} */ (new Set()));
  const [batchDeleting, setBatchDeleting] = useState(false);
  const [orphanActionMessage, setOrphanActionMessage] = useState(/** @type {string | null} */ (null));

  const [vitalityCandidates, setVitalityCandidates] = useState(/** @type {VitalityCandidate[]} */ ([]));
  const [vitalityLoading, setVitalityLoading] = useState(false);
  const [vitalityErrorState, setVitalityErrorState] = useState(
    /** @type {ApiErrorState | TranslationErrorState | string | null} */ (null)
  );
  const [vitalitySelectedIds, setVitalitySelectedIds] = useState(
    /** @type {Set<string | number>} */ (new Set())
  );
  const [vitalityThreshold, setVitalityThreshold] = useState(/** @type {NumericInputState} */ (0.35));
  const [vitalityInactiveDays, setVitalityInactiveDays] = useState(/** @type {NumericInputState} */ (14));
  const [vitalityLimit, setVitalityLimit] = useState(/** @type {NumericInputState} */ (80));
  const [vitalityDomain, setVitalityDomain] = useState('');
  const [vitalityPathPrefix, setVitalityPathPrefix] = useState('');
  const [vitalityReviewer, setVitalityReviewer] = useState(DEFAULT_VITALITY_REVIEWER);
  const [vitalityProcessing, setVitalityProcessing] = useState(false);
  const [vitalityPreparedReview, setVitalityPreparedReview] = useState(
    /** @type {VitalityPreparedReviewState | null} */ (null)
  );
  const [vitalityLastResult, setVitalityLastResult] = useState(
    /** @type {VitalityCleanupResultState | null} */ (null)
  );
  const [vitalityQueryMeta, setVitalityQueryMeta] = useState(
    /** @type {VitalityQueryMetaState | null} */ (null)
  );
  const orphanRequestSeqRef = useRef(0);
  const detailRequestSeqRef = useRef(0);
  const vitalityRequestSeqRef = useRef(0);
  const vitalityPrepareSeqRef = useRef(0);
  const mountedRef = useRef(false);
  const translateRef = useRef(t);
  const vitalityFiltersRef = useRef({
    threshold: vitalityThreshold,
    inactiveDays: vitalityInactiveDays,
    limit: vitalityLimit,
    domain: vitalityDomain,
    pathPrefix: vitalityPathPrefix,
  });
  translateRef.current = t;
  vitalityFiltersRef.current = {
    threshold: vitalityThreshold,
    inactiveDays: vitalityInactiveDays,
    limit: vitalityLimit,
    domain: vitalityDomain,
    pathPrefix: vitalityPathPrefix,
  };
  const error = useMemo(() => {
    if (!errorState) return null;
    return `${t('maintenance.errors.loadOrphans')}: ${extractApiError(
      errorState.error,
      t(errorState.fallbackKey)
    )}`;
  }, [errorState, t]);
  const vitalityError = useMemo(() => {
    if (!vitalityErrorState) return null;
    if (typeof vitalityErrorState === 'string') return vitalityErrorState;
    if ('type' in vitalityErrorState && vitalityErrorState.type === 'translation') {
      return t(vitalityErrorState.key, vitalityErrorState.values || {});
    }
    if ('error' in vitalityErrorState) {
      return extractApiError(vitalityErrorState.error, t(vitalityErrorState.fallbackKey));
    }
    return null;
  }, [t, vitalityErrorState]);

  /** @param {string | undefined | null} action */
  const translateVitalityAction = useCallback((action) => {
    if (!action) {
      return t('maintenance.vitality.reviewFallback');
    }
    return t(`maintenance.vitality.actionLabels.${action}`, { defaultValue: action });
  }, [t]);

  const invalidatePreparedReview = useCallback(() => {
    vitalityPrepareSeqRef.current += 1;
    if (mountedRef.current) {
      setVitalityPreparedReview(null);
    }
  }, []);

  const loadOrphans = useCallback(async () => {
    if (!mountedRef.current) return;
    const requestSeq = orphanRequestSeqRef.current + 1;
    orphanRequestSeqRef.current = requestSeq;
    setLoading(true);
    setErrorState(null);
    setSelectedIds(new Set());
    try {
      const data = await listOrphanMemories();
      if (!mountedRef.current || requestSeq !== orphanRequestSeqRef.current) return;
      setOrphans(Array.isArray(data) ? data : []);
    } catch (err) {
      if (!mountedRef.current || requestSeq !== orphanRequestSeqRef.current) return;
      setErrorState({ error: err, fallbackKey: 'maintenance.errors.loadOrphans' });
    } finally {
      if (!mountedRef.current || requestSeq !== orphanRequestSeqRef.current) return;
      setLoading(false);
    }
  }, []);

  const loadVitalityCandidates = useCallback(
    /**
     * @param {{
     *   forceDecay?: boolean,
     *   thresholdValue?: NumericInputState,
     *   inactiveDaysValue?: NumericInputState,
     *   limitValue?: NumericInputState,
     *   domainValue?: string,
     *   pathPrefixValue?: string,
     * }} [options]
     */
    async (options = {}) => {
      if (!mountedRef.current) return;
      const {
        forceDecay = false,
        thresholdValue,
        inactiveDaysValue,
        limitValue,
        domainValue,
        pathPrefixValue,
      } = options;
      const requestSeq = vitalityRequestSeqRef.current + 1;
      vitalityRequestSeqRef.current = requestSeq;
      setVitalityLoading(true);
      setVitalityErrorState(null);
      invalidatePreparedReview();
      try {
        const translate = translateRef.current;
        const latestFilters = vitalityFiltersRef.current;
        const thresholdRaw = String(thresholdValue ?? latestFilters.threshold ?? '').trim();
        const inactiveDaysRaw = String(
          inactiveDaysValue ?? latestFilters.inactiveDays ?? ''
        ).trim();
        const limitRaw = String(limitValue ?? latestFilters.limit ?? '').trim();
        if (!thresholdRaw) {
          throw new Error(translate('maintenance.errors.thresholdRequired'));
        }
        if (!inactiveDaysRaw) {
          throw new Error(translate('maintenance.errors.inactiveDaysRequired'));
        }
        if (!limitRaw) {
          throw new Error(translate('maintenance.errors.limitRequired'));
        }
        const parsedThreshold = Number(thresholdRaw);
        const parsedInactiveDays = Number(inactiveDaysRaw);
        const parsedLimit = Number(limitRaw);
        const domainRaw = String(domainValue ?? latestFilters.domain ?? '').trim();
        const pathPrefixRaw = String(pathPrefixValue ?? latestFilters.pathPrefix ?? '').trim();
        if (!Number.isFinite(parsedThreshold) || parsedThreshold < 0) {
          throw new Error(translate('maintenance.errors.thresholdNonNegative'));
        }
        if (!Number.isFinite(parsedInactiveDays) || parsedInactiveDays < 0) {
          throw new Error(translate('maintenance.errors.inactiveDaysNonNegative'));
        }
        if (
          !Number.isFinite(parsedLimit)
          || !Number.isInteger(parsedLimit)
          || parsedLimit < 1
          || parsedLimit > 500
        ) {
          throw new Error(translate('maintenance.errors.limitRange'));
        }
        if (forceDecay) {
          await triggerVitalityDecay({ force: true, reason: 'maintenance.manual_refresh' });
          if (!mountedRef.current || requestSeq !== vitalityRequestSeqRef.current) return;
        }
        /** @type {{ threshold: number, inactive_days: number, limit: number, domain?: string, path_prefix?: string }} */
        const payload = {
          threshold: parsedThreshold,
          inactive_days: parsedInactiveDays,
          limit: parsedLimit,
        };
        if (domainRaw) {
          payload.domain = domainRaw;
        }
        if (pathPrefixRaw) {
          payload.path_prefix = pathPrefixRaw;
        }
        const res = await queryVitalityCleanupCandidates(payload);
        if (!mountedRef.current || requestSeq !== vitalityRequestSeqRef.current) return;
        setVitalityCandidates(Array.isArray(res.items) ? res.items : []);
        setVitalityQueryMeta({
          status: res?.status || 'ok',
          decay: res?.decay || null,
        });
        setVitalitySelectedIds(new Set());
      } catch (err) {
        if (!mountedRef.current || requestSeq !== vitalityRequestSeqRef.current) return;
        setVitalityQueryMeta(null);
        setVitalityErrorState({
          error: err,
          fallbackKey: 'maintenance.errors.loadVitalityCandidates',
        });
      } finally {
        if (!mountedRef.current || requestSeq !== vitalityRequestSeqRef.current) return;
        setVitalityLoading(false);
      }
    },
    [invalidatePreparedReview]
  );

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      orphanRequestSeqRef.current += 1;
      detailRequestSeqRef.current += 1;
      vitalityRequestSeqRef.current += 1;
      vitalityPrepareSeqRef.current += 1;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    const safeLoadOrphans = async () => {
      if (cancelled) return;
      await loadOrphans();
    };
    const safeLoadVitality = async () => {
      if (cancelled) return;
      await loadVitalityCandidates();
    };
    void safeLoadOrphans();
    void safeLoadVitality();
    return () => {
      cancelled = true;
    };
  }, [loadOrphans, loadVitalityCandidates]);

  /**
   * @param {string | number} id
   * @param {import('react').MouseEvent<HTMLButtonElement>} e
   */
  const toggleSelect = useCallback((id, e) => {
    e.stopPropagation();
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  /** @param {OrphanEntry[]} items */
  const toggleSelectAll = useCallback((items) => {
    const ids = items.map(i => i.id);
    setSelectedIds(prev => {
      const next = new Set(prev);
      const allSelected = ids.every(id => next.has(id));
      if (allSelected) {
        ids.forEach(id => next.delete(id));
      } else {
        ids.forEach(id => next.add(id));
      }
      return next;
    });
  }, []);

  /** @param {string | number} memoryId */
  const toggleVitalitySelect = useCallback((memoryId) => {
    if (vitalityProcessing) return;
    setVitalitySelectedIds(prev => {
      const next = new Set(prev);
      if (next.has(memoryId)) next.delete(memoryId);
      else next.add(memoryId);
      return next;
    });
    invalidatePreparedReview();
  }, [invalidatePreparedReview, vitalityProcessing]);

  const toggleVitalitySelectAll = useCallback(() => {
    if (vitalityProcessing) return;
    const ids = vitalityCandidates.map(item => item.memory_id);
    setVitalitySelectedIds(prev => {
      const next = new Set(prev);
      const allSelected = ids.length > 0 && ids.every(id => next.has(id));
      if (allSelected) {
        ids.forEach(id => next.delete(id));
      } else {
        ids.forEach(id => next.add(id));
      }
      return next;
    });
    invalidatePreparedReview();
  }, [invalidatePreparedReview, vitalityCandidates, vitalityProcessing]);

  const handleBatchDelete = async () => {
    const count = selectedIds.size;
    if (count === 0) return;
    setOrphanActionMessage(null);
    const confirmResult = confirmWithFallback(t('maintenance.prompts.deleteMemories', { count }));
    if (!confirmResult.available) {
      setOrphanActionMessage(t('maintenance.errors.confirmUnavailable'));
      return;
    }
    if (!confirmResult.confirmed) return;

    setBatchDeleting(true);
    const toDelete = [...selectedIds];
    const failed = [];

    try {
      const outcomes = await mapWithConcurrency(
        toDelete,
        ORPHAN_DELETE_CONCURRENCY,
        async (id) => {
          try {
            await deleteOrphanMemory(id);
            return { id, ok: true };
          } catch {
            return { id, ok: false };
          }
        }
      );
      outcomes.forEach(({ id, ok }) => {
        if (!ok) failed.push(id);
      });
    } finally {
      if (mountedRef.current) {
        setBatchDeleting(false);
      }
    }

    if (!mountedRef.current) return;

    const failedSet = new Set(failed);
    setOrphans(prev => prev.filter(item => !toDelete.includes(item.id) || failedSet.has(item.id)));
    setSelectedIds(new Set(failed));

    if (expandedId && toDelete.includes(expandedId) && !failedSet.has(expandedId)) {
      setExpandedId(null);
    }

    if (failed.length > 0) {
      const message = t('maintenance.errors.deleteSummary', {
        failed: failed.length,
        count,
        ids: failed.join(', '),
      });
        if (!alertWithFallback(message)) {
          setOrphanActionMessage(message);
        }
      }
  };

  /** @param {'keep' | 'delete' | string} action */
  const prepareVitalityReview = async (action) => {
    const selectedRows = vitalityCandidates.filter(item => vitalitySelectedIds.has(item.memory_id));
    if (selectedRows.length === 0) return;
    const normalizedAction = action === 'keep' ? 'keep' : 'delete';
    const reviewRows = normalizedAction === 'delete'
      ? selectedRows.filter(item => item.can_delete)
      : selectedRows;
    if (reviewRows.length === 0) {
      invalidatePreparedReview();
      setVitalityErrorState({
        type: 'translation',
        key:
          normalizedAction === 'delete'
            ? 'maintenance.errors.noDeletableSelected'
            : 'maintenance.errors.noCandidateSelected',
      });
      return;
    }
    if (reviewRows.length > VITALITY_PREPARE_MAX_SELECTIONS) {
      invalidatePreparedReview();
      setVitalityErrorState({
        type: 'translation',
        key: 'maintenance.errors.tooManySelections',
        values: {
          count: reviewRows.length,
          max: VITALITY_PREPARE_MAX_SELECTIONS,
        },
      });
      return;
    }

    const prepareSeq = vitalityPrepareSeqRef.current + 1;
    vitalityPrepareSeqRef.current = prepareSeq;
    setVitalityProcessing(true);
    setVitalityErrorState(null);
    try {
      const payload = await prepareVitalityCleanup({
        action: normalizedAction,
        reviewer: vitalityReviewer.trim() || DEFAULT_VITALITY_REVIEWER,
        selections: reviewRows.map(item => ({
          memory_id: item.memory_id,
          state_hash: item.state_hash,
        })),
      });
      const review = payload?.review;
      if (
        !review
        || typeof review !== 'object'
        || !review.review_id
        || !review.token
        || !review.confirmation_phrase
      ) {
        throw new Error(t('maintenance.errors.invalidReviewPayload'));
      }
      if (!mountedRef.current || prepareSeq !== vitalityPrepareSeqRef.current) return;
      setVitalityPreparedReview({ ...review, action: review.action || normalizedAction });
      setVitalityLastResult(null);
    } catch (err) {
      if (!mountedRef.current || prepareSeq !== vitalityPrepareSeqRef.current) return;
      setVitalityPreparedReview(null);
      setVitalityErrorState({
        error: err,
        fallbackKey: 'maintenance.errors.prepareCleanup',
      });
    } finally {
      if (!mountedRef.current || prepareSeq !== vitalityPrepareSeqRef.current) return;
      setVitalityProcessing(false);
    }
  };

  const handlePrepareVitalityDelete = async () => {
    await prepareVitalityReview('delete');
  };

  const handlePrepareVitalityKeep = async () => {
    await prepareVitalityReview('keep');
  };

  const handleConfirmVitalityCleanup = async () => {
    if (!vitalityPreparedReview) return;
    const action = vitalityPreparedReview.action || 'delete';

    const promptResult = promptWithFallback(
      t('maintenance.prompts.executeCleanup', {
        action,
        phrase: vitalityPreparedReview.confirmation_phrase,
      })
    );
    if (!promptResult.available) {
      setVitalityErrorState({
        type: 'translation',
        key: 'maintenance.errors.promptUnavailable',
      });
      return;
    }
    const typed = promptResult.value;
    if (typed === null) return;
    if (typed.trim() !== vitalityPreparedReview.confirmation_phrase) {
      setVitalityErrorState({
        type: 'translation',
        key: 'maintenance.errors.confirmationMismatch',
      });
      return;
    }

    setVitalityProcessing(true);
    setVitalityErrorState(null);
    try {
      const payload = await confirmVitalityCleanup({
        review_id: vitalityPreparedReview.review_id,
        token: vitalityPreparedReview.token,
        confirmation_phrase: typed,
      });
      if (!mountedRef.current) return;
      setVitalityLastResult(payload);
      invalidatePreparedReview();
      await Promise.all([loadOrphans(), loadVitalityCandidates()]);
    } catch (err) {
      if (!mountedRef.current) return;
      const detailCode = extractApiErrorCode(err);
      setVitalityErrorState({
        error: err,
        fallbackKey: 'maintenance.errors.confirmCleanup',
      });
      if (!shouldPreservePreparedReviewAfterConfirmError(err, detailCode)) {
        invalidatePreparedReview();
        await loadVitalityCandidates();
      }
    } finally {
      if (mountedRef.current) {
        setVitalityProcessing(false);
      }
    }
  };

  /** @param {string | number} id */
  const handleExpand = async (id) => {
    if (expandedId === id) {
      detailRequestSeqRef.current += 1;
      setExpandedId(null);
      setDetailLoading(null);
      return;
    }
    setExpandedId(id);
    const requestSeq = detailRequestSeqRef.current + 1;
    detailRequestSeqRef.current = requestSeq;

    if (detailData[id]) {
      setDetailLoading(null);
      return;
    }

    setDetailLoading(id);
    try {
      const data = await getOrphanMemoryDetail(id);
      if (!mountedRef.current || requestSeq !== detailRequestSeqRef.current) return;
      setDetailData(prev => ({ ...prev, [id]: data }));
    } catch (err) {
      if (!mountedRef.current || requestSeq !== detailRequestSeqRef.current) return;
      setDetailData(prev => ({
        ...prev,
        [id]: {
          errorState: { error: err, fallbackKey: 'maintenance.errors.loadOrphanDetail' },
        },
      }));
    } finally {
      if (!mountedRef.current || requestSeq !== detailRequestSeqRef.current) return;
      setDetailLoading(null);
    }
  };

  const deprecated = orphans.filter(o => o.category === 'deprecated');
  const orphaned = orphans.filter(o => o.category === 'orphaned');
  const vitalitySelectedCount = vitalityCandidates.filter(
    item => vitalitySelectedIds.has(item.memory_id)
  ).length;
  const vitalityCanDeleteCount = vitalityCandidates.filter(item => item.can_delete).length;
  const vitalitySelectedCanDelete = vitalityCandidates.filter(
    item => vitalitySelectedIds.has(item.memory_id) && item.can_delete
  ).length;

  /** @param {OrphanEntry} item */
  const renderCard = (item) => {
    const isExpanded = expandedId === item.id;
    const detail = detailData[item.id];
    const isLoadingDetail = detailLoading === item.id;
    const isChecked = selectedIds.has(item.id);
    const migrationTargetPaths = normalizePaths(item?.migration_target?.paths);
    const detailMigrationPaths = normalizePaths(detail?.migration_target?.paths);

    return (
      <div key={item.id} className="group relative rounded-lg border border-stone-700/40 bg-stone-900 transition-all hover:border-amber-700/45 hover:shadow-[0_0_14px_rgba(245,158,11,0.12)]">
        <div
          className="flex items-start gap-3 p-4 cursor-pointer select-none"
          onClick={() => handleExpand(item.id)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' || event.key === ' ') {
              event.preventDefault();
              void handleExpand(item.id);
            }
          }}
          role="button"
          tabIndex={0}
          aria-expanded={isExpanded}
          aria-label={String(item.content_snippet || item.id)}
        >
          <button
            onClick={(e) => toggleSelect(item.id, e)}
            className="mt-0.5 flex-shrink-0 p-0.5 rounded transition-colors hover:bg-stone-700/30"
          >
            {isChecked ? (
              <CheckSquare size={18} className="text-amber-400" />
            ) : (
              <Square size={18} className="text-stone-600 group-hover:text-stone-500" />
            )}
          </button>

          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap mb-1.5">
              <span className="text-[11px] font-mono text-stone-400 bg-stone-800/80 px-1.5 py-0.5 rounded">
                #{item.id}
              </span>
              {item.category === 'deprecated' ? (
                <span className="text-[10px] font-mono text-amber-300 bg-amber-900/40 px-1.5 py-0.5 rounded flex items-center gap-1">
                  <Archive size={9} /> {t('maintenance.card.deprecated')}
                </span>
              ) : (
                <span className="text-[10px] font-mono text-rose-300 bg-rose-900/40 px-1.5 py-0.5 rounded flex items-center gap-1">
                  <Unlink size={9} /> {t('maintenance.card.orphaned')}
                </span>
              )}
              {item.migrated_to && (
                <span className="text-[10px] font-mono text-amber-300 bg-amber-900/30 px-1.5 py-0.5 rounded">
                  → #{item.migrated_to}
                </span>
              )}
              <span className="text-[11px] text-stone-500">
                {formatDateTimeOrUnknown(item.created_at, i18n.resolvedLanguage, t('common.states.unknown'))}
              </span>
            </div>

            {item.migration_target && migrationTargetPaths.length > 0 && (
              <div className="flex items-center gap-1.5 flex-wrap mb-2">
                <ArrowRight size={12} className="text-amber-400/70 flex-shrink-0" />
                {migrationTargetPaths.map((p, i) => (
                  <span key={i} className="text-[11px] font-mono text-amber-300/90 bg-amber-900/25 px-1.5 py-0.5 rounded border border-amber-800/30">
                    {p}
                  </span>
                ))}
              </div>
            )}
            {item.migration_target && migrationTargetPaths.length === 0 && (
              <div className="flex items-center gap-1.5 mb-2">
                <ArrowRight size={12} className="text-stone-500 flex-shrink-0" />
                <span className="text-[11px] text-stone-500 italic">
                  {t('maintenance.card.targetNoPaths', { id: item.migration_target.id })}
                </span>
              </div>
            )}

            <div className="bg-stone-900/60 rounded p-2.5 text-[12px] text-stone-400 font-mono leading-relaxed line-clamp-3">
              {item.content_snippet}
            </div>
          </div>

          <div className="mt-1 flex-shrink-0 text-stone-500">
            {isExpanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
          </div>
        </div>

        {isExpanded && (
          <div className="border-t border-stone-700/30 p-5 bg-stone-900">
            {isLoadingDetail ? (
              <div className="flex items-center gap-3 text-stone-500 py-4">
                <div className="w-4 h-4 border-2 border-amber-500/30 border-t-amber-500 rounded-full animate-spin"></div>
                <span className="text-xs">{t('maintenance.card.loadingFullContent')}</span>
              </div>
            ) : detail?.errorState ? (
              <div className="text-rose-400 text-xs py-2">
                {t('maintenance.card.errorPrefix')}{' '}
                {extractApiError(detail.errorState.error, t(detail.errorState.fallbackKey))}
              </div>
            ) : detail ? (
              <div className="space-y-4">
                <div>
                  <h4 className="text-[11px] uppercase tracking-widest text-stone-500 mb-2 font-semibold">
                    {detail.migration_target ? t('maintenance.card.oldVersion') : t('maintenance.card.fullContent')}
                  </h4>
                  <div className="bg-stone-900 rounded p-4 border border-stone-800/60 text-[12px] text-stone-300 font-mono leading-relaxed whitespace-pre-wrap max-h-64 overflow-y-auto custom-scrollbar">
                    {detail.content}
                  </div>
                </div>

                {detail.migration_target && (
                  <div>
                    <h4 className="text-[11px] uppercase tracking-widest text-stone-500 mb-2 font-semibold flex items-center gap-2">
                      <span>{t('maintenance.card.diffTitle', { from: item.id, to: detail.migration_target.id })}</span>
                      {detailMigrationPaths.length > 0 && (
                        <span className="text-amber-400/70 normal-case tracking-normal font-normal">
                          ({detailMigrationPaths[0]})
                        </span>
                      )}
                    </h4>
                    <div className="bg-stone-900 rounded border border-stone-800/60 p-4 max-h-96 overflow-y-auto custom-scrollbar">
                      <DiffViewer
                        oldText={detail.content}
                        newText={detail.migration_target.content}
                      />
                    </div>
                  </div>
                )}
              </div>
            ) : null}
          </div>
        )}
      </div>
    );
  };

  /**
   * @param {import('react').ReactNode} icon
   * @param {string} label
   * @param {string} color
   * @param {OrphanEntry[]} items
   */
  const renderSectionHeader = (icon, label, color, items) => {
    const allSelected = items.length > 0 && items.every(i => selectedIds.has(i.id));
    const someSelected = items.some(i => selectedIds.has(i.id));

    return (
      <div className="flex items-center gap-3 mb-4">
        <button
          onClick={() => toggleSelectAll(items)}
          className="p-0.5 rounded transition-colors hover:bg-stone-700/30"
          title={allSelected ? t('maintenance.deselectAll') : t('maintenance.selectAll')}
        >
          {allSelected ? (
            <CheckSquare size={16} className={color} />
          ) : someSelected ? (
            <Minus size={16} className={color} />
          ) : (
            <Square size={16} className="text-stone-600" />
          )}
        </button>
        {icon}
        <h3 className={`text-xs font-bold uppercase tracking-widest ${color}`}>
          {label}
        </h3>
        <span className="text-[11px] text-stone-500 bg-stone-800/80 px-2 py-0.5 rounded-full">
          {items.length}
        </span>
      </div>
    );
  };

  return (
    <div className="palace-harmonized flex h-full flex-col overflow-hidden bg-stone-950 text-stone-200 font-sans selection:bg-amber-500/30 selection:text-amber-100 md:flex-row">
      <div className="w-full flex-shrink-0 bg-stone-900 border-b border-stone-700/30 flex flex-col p-4 md:w-72 md:border-b-0 md:border-r md:p-6">
        <div className="mb-4 md:mb-8">
          <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-xl border border-amber-800/30 bg-amber-950/30 shadow-[0_0_20px_rgba(245,158,11,0.1)]">
            <Feather className="text-amber-400" size={24} />
          </div>
          <h1 className="font-display mb-2 text-xl text-amber-50">{t('maintenance.title')}</h1>
          <p className="text-[12px] text-stone-400 leading-relaxed">{t('maintenance.subtitle')}</p>
        </div>

        <div className="mt-2 grid grid-cols-3 gap-2 md:mt-auto md:block md:space-y-3">
          <div className="bg-stone-800/40 rounded-lg p-3 border border-stone-700/40 md:p-4">
            <div className="text-stone-400 text-xs uppercase font-bold tracking-wider mb-1">{t('maintenance.stats.deprecated')}</div>
            <div className="text-2xl font-mono text-amber-400 md:text-3xl">{deprecated.length}</div>
            <div className="text-stone-500 text-[11px] mt-1">{t('maintenance.stats.deprecatedHint')}</div>
          </div>
          <div className="bg-stone-800/40 rounded-lg p-3 border border-stone-700/40 md:p-4">
            <div className="text-stone-400 text-xs uppercase font-bold tracking-wider mb-1">{t('maintenance.stats.orphaned')}</div>
            <div className="text-2xl font-mono text-rose-400 md:text-3xl">{orphaned.length}</div>
            <div className="text-stone-500 text-[11px] mt-1">{t('maintenance.stats.orphanedHint')}</div>
          </div>
          <div className="bg-stone-800/40 rounded-lg p-3 border border-stone-700/40 md:p-4">
            <div className="text-stone-400 text-xs uppercase font-bold tracking-wider mb-1">{t('maintenance.stats.lowVitality')}</div>
            <div className="text-2xl font-mono text-sky-400 md:text-3xl">{vitalityCandidates.length}</div>
            <div className="text-stone-500 text-[11px] mt-1">{t('maintenance.stats.lowVitalityHint', { count: vitalityCanDeleteCount })}</div>
          </div>
        </div>
      </div>

      <div className="flex-1 flex flex-col min-h-0 min-w-0 bg-stone-950 relative overflow-hidden">
        <div className="h-14 flex items-center justify-between px-4 border-b border-stone-700/30 bg-stone-950/90 backdrop-blur-md sticky top-0 z-10 md:px-8">
          <h2 className="text-sm font-bold text-stone-300 uppercase tracking-widest flex items-center gap-2">
            <Trash2 size={14} /> {t('maintenance.console')}
          </h2>
          <div className="flex items-center gap-2">
            {selectedIds.size > 0 && (
              <button
                onClick={handleBatchDelete}
                disabled={batchDeleting}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md bg-rose-900/40 text-rose-300 hover:bg-rose-900/60 border border-rose-800/40 transition-colors disabled:opacity-50"
              >
                {batchDeleting ? (
                  <div className="w-3 h-3 border-2 border-rose-400/30 border-t-rose-400 rounded-full animate-spin"></div>
                ) : (
                  <Trash2 size={13} />
                )}
                {t('maintenance.deleteOrphans', { count: selectedIds.size })}
              </button>
            )}
            <button
              onClick={() => {
                loadOrphans();
                loadVitalityCandidates();
              }}
              disabled={loading || vitalityLoading || vitalityProcessing}
              className="p-2 text-stone-400 hover:text-amber-400 hover:bg-stone-700/40 rounded-full transition-all disabled:opacity-50"
              title={t('maintenance.refresh')}
            >
              <RefreshCw size={16} className={loading || vitalityLoading ? 'animate-spin' : ''} />
            </button>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-4 custom-scrollbar md:p-8">
          <div className="max-w-5xl mx-auto space-y-8">
            <section>
              <div className="mb-4 flex items-center justify-between">
                <h3 className="text-xs font-bold uppercase tracking-widest text-amber-300 flex items-center gap-2">
                  <Archive size={14} /> {t('maintenance.orphanCleanup')}
                </h3>
                <span className="text-[11px] text-stone-500 bg-stone-800/80 px-2 py-0.5 rounded-full">
                  {t('maintenance.total', { count: orphans.length })}
                </span>
              </div>
              {loading ? (
                <div className="flex items-center gap-2 text-xs text-stone-500">
                  <div className="w-3 h-3 border-2 border-amber-500/30 border-t-amber-500 rounded-full animate-spin"></div>
                  {t('maintenance.scanningOrphans')}
                </div>
              ) : error ? (
                <div className="text-rose-400 bg-rose-950/20 border border-rose-800/40 p-4 rounded-lg flex items-center gap-3">
                  <AlertTriangle size={18} />
                  <span className="text-sm">{error}</span>
                </div>
              ) : orphans.length === 0 ? (
                <div className="rounded-lg border border-stone-800 bg-stone-900/40 p-4 text-sm text-stone-500">
                  {t('maintenance.noOrphans')}
                </div>
              ) : (
                <div className="space-y-8">
                  {orphanActionMessage ? (
                    <div
                      role="alert"
                      className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-4 text-sm text-amber-200"
                    >
                      {orphanActionMessage}
                    </div>
                  ) : null}
                  {deprecated.length > 0 && (
                    <section>
                      {renderSectionHeader(
                        <Archive size={16} className="text-amber-400/80" />,
                        t('maintenance.deprecatedVersions'),
                        'text-amber-400/80',
                        deprecated
                      )}
                      <div className="space-y-2">
                        {deprecated.map(renderCard)}
                      </div>
                    </section>
                  )}

                  {orphaned.length > 0 && (
                    <section>
                      {renderSectionHeader(
                        <Unlink size={16} className="text-rose-400/80" />,
                        t('maintenance.orphanedMemories'),
                        'text-rose-400/80',
                        orphaned
                      )}
                      <div className="space-y-2">
                        {orphaned.map(renderCard)}
                      </div>
                    </section>
                  )}
                </div>
              )}
            </section>

            <section className="rounded-lg border border-stone-800/80 bg-stone-900/30 p-5">
              <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
                <h3 className="text-xs font-bold uppercase tracking-widest text-sky-300 flex items-center gap-2">
                  <Trash2 size={14} /> {t('maintenance.vitality.title')}
                </h3>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => loadVitalityCandidates({ forceDecay: true })}
                    disabled={vitalityLoading || vitalityProcessing}
                    className="px-2.5 py-1 text-[11px] rounded border border-sky-800/50 text-sky-200 hover:bg-sky-900/30 disabled:opacity-50"
                  >
                    {t('maintenance.vitality.runDecay')}
                  </button>
                </div>
              </div>

              <div className="mb-4 flex flex-wrap items-center gap-3 text-xs">
                <label className="flex items-center gap-1 text-stone-400">
                  {t('maintenance.vitality.threshold')}
                  <input
                    type="number"
                    min="0"
                    step="0.01"
                    value={vitalityThreshold}
                    onChange={(e) => {
                      setVitalityThreshold(e.target.value);
                      invalidatePreparedReview();
                    }}
                    disabled={vitalityProcessing}
                    className="w-20 rounded border border-stone-700 bg-stone-900 px-2 py-1 text-stone-200"
                  />
                </label>
                <label className="flex items-center gap-1 text-stone-400">
                  {t('maintenance.vitality.inactiveDays')}
                  <input
                    type="number"
                    min="0"
                    step="1"
                    value={vitalityInactiveDays}
                    onChange={(e) => {
                      setVitalityInactiveDays(e.target.value);
                      invalidatePreparedReview();
                    }}
                    disabled={vitalityProcessing}
                    className="w-20 rounded border border-stone-700 bg-stone-900 px-2 py-1 text-stone-200"
                  />
                </label>
                <label className="flex items-center gap-1 text-stone-400">
                  {t('maintenance.vitality.limit')}
                  <input
                    type="number"
                    min="1"
                    max="500"
                    step="1"
                    value={vitalityLimit}
                    onChange={(e) => {
                      setVitalityLimit(e.target.value);
                      invalidatePreparedReview();
                    }}
                    disabled={vitalityProcessing}
                    className="w-20 rounded border border-stone-700 bg-stone-900 px-2 py-1 text-stone-200"
                  />
                </label>
                <label className="flex items-center gap-1 text-stone-400">
                  {t('maintenance.vitality.domain')}
                  <input
                    type="text"
                    value={vitalityDomain}
                    onChange={(e) => {
                      setVitalityDomain(e.target.value);
                      invalidatePreparedReview();
                    }}
                    disabled={vitalityProcessing}
                    className="w-24 rounded border border-stone-700 bg-stone-900 px-2 py-1 text-stone-200"
                    placeholder={t('maintenance.vitality.optional')}
                    aria-label={t('maintenance.vitality.domain')}
                  />
                </label>
                <label className="flex items-center gap-1 text-stone-400">
                  {t('maintenance.vitality.pathPrefix')}
                  <input
                    type="text"
                    value={vitalityPathPrefix}
                    onChange={(e) => {
                      setVitalityPathPrefix(e.target.value);
                      invalidatePreparedReview();
                    }}
                    disabled={vitalityProcessing}
                    className="w-32 rounded border border-stone-700 bg-stone-900 px-2 py-1 text-stone-200"
                    placeholder={t('maintenance.vitality.optional')}
                    aria-label={t('maintenance.vitality.pathPrefix')}
                  />
                </label>
                <label className="flex items-center gap-1 text-stone-400">
                  {t('maintenance.vitality.reviewer')}
                  <input
                    type="text"
                    value={vitalityReviewer}
                    onChange={(e) => {
                      setVitalityReviewer(e.target.value);
                      invalidatePreparedReview();
                    }}
                    disabled={vitalityProcessing}
                    className="w-36 rounded border border-stone-700 bg-stone-900 px-2 py-1 text-stone-200"
                    placeholder={t('maintenance.vitality.reviewerPlaceholder', {
                      value: DEFAULT_VITALITY_REVIEWER,
                    })}
                  />
                </label>
                <button
                  onClick={() => loadVitalityCandidates()}
                  disabled={vitalityLoading || vitalityProcessing}
                  className="px-2.5 py-1 text-[11px] rounded border border-stone-700 text-stone-200 hover:bg-stone-800/60 disabled:opacity-50"
                >
                  {t('maintenance.vitality.applyFilters')}
                </button>
                <button
                  onClick={toggleVitalitySelectAll}
                  disabled={vitalityCandidates.length === 0 || vitalityProcessing}
                  className="px-2.5 py-1 text-[11px] rounded border border-stone-700 text-stone-300 hover:bg-stone-800/60 disabled:opacity-50"
                >
                  {vitalityCandidates.length > 0 && vitalityCandidates.every(item => vitalitySelectedIds.has(item.memory_id))
                    ? t('maintenance.deselectAll')
                    : t('maintenance.selectAll')}
                </button>
              </div>

              <div className="mb-4 flex flex-wrap items-center gap-2">
                <button
                  onClick={handlePrepareVitalityKeep}
                  disabled={vitalitySelectedCount === 0 || vitalityProcessing}
                  className="px-3 py-1.5 text-xs rounded bg-sky-900/40 text-sky-200 border border-sky-800/50 hover:bg-sky-900/60 disabled:opacity-50"
                >
                  {t('maintenance.vitality.prepareKeep', { count: vitalitySelectedCount })}
                </button>
                <button
                  onClick={handlePrepareVitalityDelete}
                  disabled={vitalitySelectedCanDelete === 0 || vitalityProcessing}
                  className="px-3 py-1.5 text-xs rounded bg-amber-900/40 text-amber-200 border border-amber-800/50 hover:bg-amber-900/60 disabled:opacity-50"
                >
                  {t('maintenance.vitality.prepareDelete', { count: vitalitySelectedCanDelete })}
                </button>
                <button
                  onClick={handleConfirmVitalityCleanup}
                  disabled={!vitalityPreparedReview || vitalityProcessing}
                  className="px-3 py-1.5 text-xs rounded bg-rose-900/40 text-rose-200 border border-rose-800/50 hover:bg-rose-900/60 disabled:opacity-50"
                >
                  {t('maintenance.vitality.confirmAction', {
                    action: translateVitalityAction(vitalityPreparedReview?.action),
                  })}
                </button>
                {vitalityPreparedReview && (
                  <button
                    onClick={invalidatePreparedReview}
                    disabled={vitalityProcessing}
                  className="px-3 py-1.5 text-xs rounded border border-stone-700 text-stone-300 hover:bg-stone-800/60 disabled:opacity-50"
                >
                    {t('maintenance.vitality.discardReview')}
                  </button>
                )}
                <span className="text-xs text-stone-500">
                  {t('maintenance.vitality.selectionSummary', {
                    selected: vitalitySelectedCount,
                    deletable: vitalitySelectedCanDelete,
                  })}
                </span>
              </div>

              {vitalityPreparedReview && (
                <div className="mb-4 rounded border border-amber-800/40 bg-amber-950/20 p-3 text-xs text-amber-200">
                  <div>{t('maintenance.vitality.reviewId', { value: vitalityPreparedReview.review_id })}</div>
                  <div>{t('maintenance.vitality.action', { value: translateVitalityAction(vitalityPreparedReview.action) })}</div>
                  <div>{t('maintenance.vitality.reviewerValue', { value: vitalityPreparedReview.reviewer })}</div>
                  <div>{t('maintenance.vitality.confirmationPhrase', { value: vitalityPreparedReview.confirmation_phrase })}</div>
                </div>
              )}

              {vitalityQueryMeta?.status === 'degraded' && (
                <div className="mb-4 rounded border border-amber-800/40 bg-amber-950/20 p-3 text-xs text-amber-200">
                  <div>{t('maintenance.vitality.degradedStatus')}</div>
                  <div>{t('maintenance.vitality.reason', { value: vitalityQueryMeta?.decay?.reason || t('common.states.unknown') })}</div>
                </div>
              )}

              {vitalityLastResult && (
                <div className="mb-4 rounded border border-sky-800/40 bg-sky-950/20 p-3 text-xs text-sky-200">
                  <div>{t('maintenance.vitality.status', { value: vitalityLastResult.status })}</div>
                  <div>{t('maintenance.vitality.resultSummary', {
                    deleted: vitalityLastResult.deleted_count,
                    kept: vitalityLastResult.kept_count,
                    skipped: vitalityLastResult.skipped_count,
                    errors: vitalityLastResult.error_count,
                  })}</div>
                </div>
              )}

              {vitalityLoading ? (
                <div className="flex items-center gap-2 text-xs text-stone-500">
                  <div className="w-3 h-3 border-2 border-sky-500/30 border-t-sky-500 rounded-full animate-spin"></div>
                  {t('maintenance.vitality.loading')}
                </div>
              ) : vitalityError ? (
                <div className="rounded border border-rose-800/40 bg-rose-950/20 p-3 text-xs text-rose-300">
                  {typeof vitalityError === 'string' ? vitalityError : JSON.stringify(vitalityError)}
                </div>
              ) : vitalityCandidates.length === 0 ? (
                <div className="rounded border border-stone-800 bg-stone-900/40 p-3 text-xs text-stone-500">
                  {t('maintenance.vitality.noCandidates')}
                </div>
              ) : (
                <div className="space-y-2">
                  {vitalityCandidates.map((item) => (
                    <div
                      key={item.memory_id}
                      className="rounded border border-stone-800 bg-stone-900/50 p-3"
                    >
                      <div className="flex flex-wrap items-center gap-2 mb-1.5">
                        <button
                          onClick={() => toggleVitalitySelect(item.memory_id)}
                          disabled={vitalityProcessing}
                          className="p-0.5 rounded hover:bg-stone-700/40 disabled:opacity-50"
                        >
                          {vitalitySelectedIds.has(item.memory_id) ? (
                            <CheckSquare size={14} className="text-sky-300" />
                          ) : (
                            <Square size={14} className="text-stone-500" />
                          )}
                        </button>
                        <span className="text-[11px] font-mono text-stone-300 bg-stone-800 px-1.5 py-0.5 rounded">
                          #{item.memory_id}
                        </span>
                        <span className="text-[11px] text-sky-300 bg-sky-900/30 px-1.5 py-0.5 rounded">
                          {t('maintenance.vitality.vitality', { value: Number(item.vitality_score || 0).toFixed(3) })}
                        </span>
                        <span className="text-[11px] text-stone-400 bg-stone-800/70 px-1.5 py-0.5 rounded">
                          {t('maintenance.vitality.inactive', { value: Number(item.inactive_days || 0).toFixed(1) })}
                        </span>
                        <span className="text-[11px] text-stone-400 bg-stone-800/70 px-1.5 py-0.5 rounded">
                          {t('maintenance.vitality.access', { value: item.access_count || 0 })}
                        </span>
                        <span className={`text-[10px] px-1.5 py-0.5 rounded ${item.can_delete ? 'text-rose-300 bg-rose-900/30' : 'text-amber-300 bg-amber-900/30'}`}>
                          {item.can_delete ? t('maintenance.vitality.deletable') : t('maintenance.vitality.activePaths')}
                        </span>
                      </div>
                      <div className="text-[11px] text-stone-500 mb-1.5">
                        {item.uri || t('maintenance.vitality.noPath')}
                      </div>
                      <div className="rounded bg-stone-900 p-2 text-[12px] text-stone-400 font-mono leading-relaxed">
                        {item.content_snippet}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </section>

            <section className="rounded-lg border border-stone-800/80 bg-stone-900/30 p-5">
              <ForgettingPanel />
            </section>
          </div>
        </div>
      </div>
    </div>
  );
}
