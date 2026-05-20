import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  queryVitalityCleanupCandidates,
  prepareVitalityCleanup,
  confirmVitalityCleanup,
  triggerVitalityDecay,
  extractApiError,
  extractApiErrorCode,
} from '../../../lib/api';

const VITALITY_PREPARE_MAX_SELECTIONS = 100;
export const DEFAULT_VITALITY_REVIEWER = 'maintenance_dashboard';

/**
 * @typedef {{ error: unknown, fallbackKey: string }} ApiErrorState
 * @typedef {{ type: 'translation', key: string, values?: Record<string, string | number> }} TranslationErrorState
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
 *   selection_count?: number,
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
 * Preserve the prepared review across recoverable confirm errors so the
 * reviewer can retry without redoing the prepare step.
 */
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

/**
 * Vitality cleanup hook. Encapsulates all candidate-loading, selection,
 * prepare, and confirm flows for the Vitality panel. Auto-loads candidates
 * on mount.
 *
 * @param {{ reloadOrphans?: () => Promise<void> | void }} [options]
 */
export default function useVitality({ reloadOrphans } = {}) {
  const { t } = useTranslation();

  const [candidates, setCandidates] = useState(/** @type {VitalityCandidate[]} */ ([]));
  const [loading, setLoading] = useState(false);
  const [errorState, setErrorState] = useState(
    /** @type {ApiErrorState | TranslationErrorState | string | null} */ (null)
  );
  const [selectedIds, setSelectedIds] = useState(
    /** @type {Set<string | number>} */ (new Set())
  );

  const [threshold, setThreshold] = useState(/** @type {NumericInputState} */ (0.35));
  const [inactiveDays, setInactiveDays] = useState(/** @type {NumericInputState} */ (14));
  const [limit, setLimit] = useState(/** @type {NumericInputState} */ (80));
  const [domain, setDomain] = useState('');
  const [pathPrefix, setPathPrefix] = useState('');
  const [reviewer, setReviewer] = useState(DEFAULT_VITALITY_REVIEWER);

  const [processing, setProcessing] = useState(false);
  const [preparedReview, setPreparedReview] = useState(
    /** @type {VitalityPreparedReviewState | null} */ (null)
  );
  const [lastResult, setLastResult] = useState(
    /** @type {VitalityCleanupResultState | null} */ (null)
  );
  const [queryMeta, setQueryMeta] = useState(
    /** @type {VitalityQueryMetaState | null} */ (null)
  );

  const mountedRef = useRef(false);
  const requestSeqRef = useRef(0);
  const prepareSeqRef = useRef(0);
  const translateRef = useRef(t);
  const filtersRef = useRef({ threshold, inactiveDays, limit, domain, pathPrefix });
  const reloadOrphansRef = useRef(reloadOrphans);

  translateRef.current = t;
  filtersRef.current = { threshold, inactiveDays, limit, domain, pathPrefix };
  reloadOrphansRef.current = reloadOrphans;

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      requestSeqRef.current += 1;
      prepareSeqRef.current += 1;
    };
  }, []);

  const invalidatePreparedReview = useCallback(() => {
    prepareSeqRef.current += 1;
    if (mountedRef.current) {
      setPreparedReview(null);
    }
  }, []);

  const loadCandidates = useCallback(
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
      const requestSeq = requestSeqRef.current + 1;
      requestSeqRef.current = requestSeq;
      setLoading(true);
      setErrorState(null);
      invalidatePreparedReview();
      try {
        const translate = translateRef.current;
        const latestFilters = filtersRef.current;
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
          if (!mountedRef.current || requestSeq !== requestSeqRef.current) return;
        }
        /** @type {{ threshold: number, inactive_days: number, limit: number, domain?: string, path_prefix?: string }} */
        const payload = {
          threshold: parsedThreshold,
          inactive_days: parsedInactiveDays,
          limit: parsedLimit,
        };
        if (domainRaw) payload.domain = domainRaw;
        if (pathPrefixRaw) payload.path_prefix = pathPrefixRaw;
        const res = await queryVitalityCleanupCandidates(payload);
        if (!mountedRef.current || requestSeq !== requestSeqRef.current) return;
        setCandidates(Array.isArray(res.items) ? res.items : []);
        setQueryMeta({
          status: res?.status || 'ok',
          decay: res?.decay || null,
        });
        setSelectedIds(new Set());
      } catch (err) {
        if (!mountedRef.current || requestSeq !== requestSeqRef.current) return;
        setQueryMeta(null);
        setErrorState({
          error: err,
          fallbackKey: 'maintenance.errors.loadVitalityCandidates',
        });
      } finally {
        if (!mountedRef.current || requestSeq !== requestSeqRef.current) return;
        setLoading(false);
      }
    },
    [invalidatePreparedReview]
  );

  useEffect(() => {
    let cancelled = false;
    const run = async () => {
      if (cancelled) return;
      await loadCandidates();
    };
    void run();
    return () => {
      cancelled = true;
    };
  }, [loadCandidates]);

  /** @param {string | number} memoryId */
  const toggleSelect = useCallback(
    (memoryId) => {
      if (processing) return;
      setSelectedIds((prev) => {
        const next = new Set(prev);
        if (next.has(memoryId)) next.delete(memoryId);
        else next.add(memoryId);
        return next;
      });
      invalidatePreparedReview();
    },
    [invalidatePreparedReview, processing]
  );

  const toggleSelectAll = useCallback(() => {
    if (processing) return;
    const ids = candidates.map((item) => item.memory_id);
    setSelectedIds((prev) => {
      const next = new Set(prev);
      const allSelected = ids.length > 0 && ids.every((id) => next.has(id));
      if (allSelected) {
        ids.forEach((id) => next.delete(id));
      } else {
        ids.forEach((id) => next.add(id));
      }
      return next;
    });
    invalidatePreparedReview();
  }, [candidates, invalidatePreparedReview, processing]);

  const clearSelection = useCallback(() => {
    if (processing) return;
    setSelectedIds(new Set());
    invalidatePreparedReview();
  }, [invalidatePreparedReview, processing]);

  /** @param {'keep' | 'delete' | string} action */
  const prepareReview = useCallback(
    async (action) => {
      const selectedRows = candidates.filter((item) => selectedIds.has(item.memory_id));
      if (selectedRows.length === 0) return;
      const normalizedAction = action === 'keep' ? 'keep' : 'delete';
      const reviewRows = normalizedAction === 'delete'
        ? selectedRows.filter((item) => item.can_delete)
        : selectedRows;
      if (reviewRows.length === 0) {
        invalidatePreparedReview();
        setErrorState({
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
        setErrorState({
          type: 'translation',
          key: 'maintenance.errors.tooManySelections',
          values: {
            count: reviewRows.length,
            max: VITALITY_PREPARE_MAX_SELECTIONS,
          },
        });
        return;
      }

      const prepareSeq = prepareSeqRef.current + 1;
      prepareSeqRef.current = prepareSeq;
      setProcessing(true);
      setErrorState(null);
      try {
        const payload = await prepareVitalityCleanup({
          action: normalizedAction,
          reviewer: reviewer.trim() || DEFAULT_VITALITY_REVIEWER,
          selections: reviewRows.map((item) => ({
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
          throw new Error(translateRef.current('maintenance.errors.invalidReviewPayload'));
        }
        if (!mountedRef.current || prepareSeq !== prepareSeqRef.current) return;
        setPreparedReview({
          ...review,
          action: review.action || normalizedAction,
          selection_count: reviewRows.length,
        });
        setLastResult(null);
      } catch (err) {
        if (!mountedRef.current || prepareSeq !== prepareSeqRef.current) return;
        setPreparedReview(null);
        setErrorState({
          error: err,
          fallbackKey: 'maintenance.errors.prepareCleanup',
        });
      } finally {
        if (!mountedRef.current || prepareSeq !== prepareSeqRef.current) return;
        setProcessing(false);
      }
    },
    [candidates, invalidatePreparedReview, reviewer, selectedIds]
  );

  const prepareKeep = useCallback(() => prepareReview('keep'), [prepareReview]);
  const prepareDelete = useCallback(() => prepareReview('delete'), [prepareReview]);

  /**
   * Confirm the prepared review with the user-typed confirmation phrase.
   * The caller is responsible for collecting the phrase via UI (e.g.
   * ConfirmPhraseModal). Returns true on success.
   *
   * @param {string} typedPhrase
   */
  const confirmCleanup = useCallback(
    async (typedPhrase) => {
      if (processing) return false;
      if (!preparedReview) return false;
      if (typeof typedPhrase !== 'string') return false;
      const trimmed = typedPhrase.trim();
      if (trimmed !== preparedReview.confirmation_phrase) {
        setErrorState({
          type: 'translation',
          key: 'maintenance.errors.confirmationMismatch',
        });
        return false;
      }

      setProcessing(true);
      setErrorState(null);
      try {
        const payload = await confirmVitalityCleanup({
          review_id: preparedReview.review_id,
          token: preparedReview.token,
          confirmation_phrase: trimmed,
        });
        if (!mountedRef.current) return false;
        setLastResult(payload);
        invalidatePreparedReview();
        const reload = reloadOrphansRef.current;
        await Promise.all([
          reload ? Promise.resolve(reload()) : Promise.resolve(),
          loadCandidates(),
        ]);
        return true;
      } catch (err) {
        if (!mountedRef.current) return false;
        const detailCode = extractApiErrorCode(err);
        setErrorState({
          error: err,
          fallbackKey: 'maintenance.errors.confirmCleanup',
        });
        if (!shouldPreservePreparedReviewAfterConfirmError(err, detailCode)) {
          invalidatePreparedReview();
          await loadCandidates();
        }
        return false;
      } finally {
        if (mountedRef.current) {
          setProcessing(false);
        }
      }
    },
    [invalidatePreparedReview, loadCandidates, preparedReview, processing]
  );

  /** @param {string | undefined | null} action */
  const translateAction = useCallback(
    (action) => {
      if (!action) {
        return t('maintenance.vitality.reviewFallback');
      }
      return t(`maintenance.vitality.actionLabels.${action}`, { defaultValue: action });
    },
    [t]
  );

  const error = useMemo(() => {
    if (!errorState) return null;
    if (typeof errorState === 'string') return errorState;
    if ('type' in errorState && errorState.type === 'translation') {
      return t(errorState.key, errorState.values || {});
    }
    if ('error' in errorState) {
      return extractApiError(errorState.error, t(errorState.fallbackKey));
    }
    return null;
  }, [errorState, t]);

  const selectedCount = useMemo(
    () => candidates.filter((item) => selectedIds.has(item.memory_id)).length,
    [candidates, selectedIds]
  );
  const canDeleteCount = useMemo(
    () => candidates.filter((item) => item.can_delete).length,
    [candidates]
  );
  const selectedCanDelete = useMemo(
    () =>
      candidates.filter((item) => selectedIds.has(item.memory_id) && item.can_delete).length,
    [candidates, selectedIds]
  );

  return {
    candidates,
    loading,
    error,
    errorState,
    queryMeta,
    lastResult,
    selectedIds,
    processing,
    preparedReview,
    filters: { threshold, inactiveDays, limit, domain, pathPrefix, reviewer },
    setters: {
      setThreshold,
      setInactiveDays,
      setLimit,
      setDomain,
      setPathPrefix,
      setReviewer,
    },
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
  };
}
