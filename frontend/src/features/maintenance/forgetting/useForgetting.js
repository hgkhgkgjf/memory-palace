import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';

import {
  confirmForgettingArchive,
  getForgettingCandidates,
  prepareForgettingArchive,
  simulateForgettingDecay,
} from '../../../lib/api';
import { confirmWithFallback, promptWithFallback } from '../../../lib/dialogs';

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

const DEFAULT_THRESHOLD_INPUT = '0.35';
const DEFAULT_DAYS_INPUT = '30';

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

const isUnsupportedError = (err) => {
  const statusCode = err?.response?.status;
  return statusCode === 404 || statusCode === 501 || err?.code === 'ERR_NETWORK';
};

/**
 * Centralized state + side effects for the Forgetting Simulation panel.
 *
 * @param {{ onInspectMemory?: (memoryId: string | number) => void }} [opts]
 */
export function useForgetting({ onInspectMemory } = {}) {
  const { t } = useTranslation();
  const [thresholdInput, setThresholdInputState] = useState(DEFAULT_THRESHOLD_INPUT);
  const [daysInput, setDaysInputState] = useState(DEFAULT_DAYS_INPUT);
  const [candidates, setCandidates] = useState(/** @type {ForgettingCandidate[]} */ ([]));
  const [simulationData, setSimulationData] = useState(/** @type {ForgettingSimulation | null} */ (null));
  const [loading, setLoading] = useState(false);
  const [busyId, setBusyId] = useState(/** @type {string | number | null} */ (null));
  const [error, setError] = useState(/** @type {string | null} */ (null));
  const [message, setMessage] = useState(/** @type {string | null} */ (null));
  const [selectedIds, setSelectedIds] = useState(/** @type {Set<string | number>} */ (new Set()));
  const [isMock, setIsMock] = useState(false);
  const mountedRef = useRef(true);
  const requestSeqRef = useRef(0);

  const threshold = useMemo(() => {
    const parsed = Number(thresholdInput);
    return Number.isFinite(parsed) && parsed >= 0 && parsed <= 1 ? parsed : 0.35;
  }, [thresholdInput]);

  const simulationDays = useMemo(() => {
    const parsed = Number(daysInput);
    return Number.isFinite(parsed) && parsed > 0 ? Math.min(365, Math.floor(parsed)) : 30;
  }, [daysInput]);

  const setThreshold = useCallback((value) => {
    setThresholdInputState(value === undefined || value === null ? '' : String(value));
  }, []);

  const setSimulationDays = useCallback((value) => {
    setDaysInputState(value === undefined || value === null ? '' : String(value));
  }, []);

  const loadData = useCallback(async () => {
    const requestSeq = requestSeqRef.current + 1;
    requestSeqRef.current = requestSeq;
    setLoading(true);
    setError(null);
    setMessage(null);
    try {
      const [simRes, candRes] = await Promise.allSettled([
        simulateForgettingDecay({ days: simulationDays }),
        getForgettingCandidates({ threshold }),
      ]);
      if (!mountedRef.current || requestSeq !== requestSeqRef.current) return;
      let mock = false;
      let simulationLookup = new Map();
      if (simRes.status === 'fulfilled' && simRes.value) {
        const sim = normalizeSimulationPayload(simRes.value, simulationDays, threshold);
        setSimulationData(sim);
        simulationLookup = new Map(
          (Array.isArray(sim.simulations) ? sim.simulations : [])
            .filter((item) => item?.memory_id !== undefined && item?.memory_id !== null)
            .map((item) => [String(item.memory_id), item])
        );
        if (sim?.is_mock) mock = true;
      } else if (simRes.status === 'rejected' && isUnsupportedError(simRes.reason)) {
        setSimulationData(createMockSimulation(simulationDays));
        mock = true;
      } else if (simRes.status === 'rejected') {
        setSimulationData(createMockSimulation(simulationDays));
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
      if (mountedRef.current && requestSeq === requestSeqRef.current) {
        setLoading(false);
      }
    }
  }, [simulationDays, threshold, t]);

  useEffect(() => {
    mountedRef.current = true;
    void loadData();
    return () => {
      mountedRef.current = false;
      requestSeqRef.current += 1;
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

  const toggleSelectAll = useCallback(() => {
    setSelectedIds((prev) => {
      if (prev.size === candidates.length && candidates.length > 0) {
        return new Set();
      }
      return new Set(candidates.map((c) => c.memory_id));
    });
  }, [candidates]);

  const clearSelection = useCallback(() => {
    setSelectedIds(new Set());
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

  // performArchive preserves the production two-step flow: prepare -> typed
  // confirmation phrase -> confirm. Falls back to mock when the backend is
  // unavailable so the dashboard remains usable in offline / unsupported
  // deployments.
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
          days: simulationDays,
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
    [simulationDays, t, threshold]
  );

  const handleArchive = useCallback((id) => performArchive([id]), [performArchive]);

  const handleBatchArchive = useCallback(() => {
    void performArchive(Array.from(selectedIds));
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

  return {
    // Data
    candidates,
    loading,
    error,
    isMock,
    selectedIds,
    busyId,
    message,
    // Simulation controls (string-input + derived numeric values)
    thresholdInput,
    daysInput,
    threshold,
    simulationDays,
    setThreshold,
    setSimulationDays,
    simulationData,
    // Actions
    loadData,
    handleKeep,
    handleArchive,
    handleBatchArchive,
    handleBatchKeep,
    handleInspect,
    toggleSelect,
    toggleSelectAll,
    clearSelection,
  };
}

export default useForgetting;
