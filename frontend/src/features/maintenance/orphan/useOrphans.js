import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  deleteOrphanMemory,
  extractApiError,
  getOrphanMemoryDetail,
  listOrphanMemories,
} from '../../../lib/api';
import { alertWithFallback, confirmWithFallback } from '../../../lib/dialogs';

/**
 * @typedef {{ error: unknown, fallbackKey: string }} ApiErrorState
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
 */

const ORPHAN_DELETE_CONCURRENCY = 4;

/**
 * Run an async worker over a list with a bounded concurrency window. Preserves
 * input order in the returned results array.
 *
 * @template T, R
 * @param {T[]} items
 * @param {number} limit
 * @param {(item: T, index: number) => Promise<R>} worker
 * @returns {Promise<R[]>}
 */
const mapWithConcurrency = async (items, limit, worker) => {
  const results = new Array(items.length);
  let nextIndex = 0;
  const workerCount = Math.min(Math.max(1, limit), items.length);

  await Promise.all(
    Array.from({ length: workerCount }, async () => {
      // eslint-disable-next-line no-constant-condition
      while (true) {
        const currentIndex = nextIndex;
        nextIndex += 1;
        if (currentIndex >= items.length) return;
        results[currentIndex] = await worker(items[currentIndex], currentIndex);
      }
    })
  );

  return results;
};

/** @param {unknown} value */
export const normalizePaths = (value) => (Array.isArray(value) ? value : []);

/**
 * Encapsulates all orphan-cleanup state, requests, and selection bookkeeping.
 * The hook is intentionally self-contained so that the panel composition layer
 * remains a pure rendering surface.
 *
 * @returns {{
 *   orphans: OrphanEntry[],
 *   deprecated: OrphanEntry[],
 *   orphaned: OrphanEntry[],
 *   loading: boolean,
 *   error: string | null,
 *   expandedId: string | number | null,
 *   detailData: { [key: string]: OrphanDetail },
 *   detailLoading: string | number | null,
 *   selectedIds: Set<string | number>,
 *   batchDeleting: boolean,
 *   orphanActionMessage: string | null,
 *   loadOrphans: () => Promise<void>,
 *   handleExpand: (id: string | number) => Promise<void>,
 *   toggleSelect: (id: string | number, event?: { stopPropagation?: () => void }) => void,
 *   toggleSelectAll: (items: OrphanEntry[]) => void,
 *   handleBatchDelete: () => Promise<void>,
 *   clearSelection: () => void,
 * }}
 */
export default function useOrphans() {
  const { t } = useTranslation();

  const [orphans, setOrphans] = useState(/** @type {OrphanEntry[]} */ ([]));
  const [loading, setLoading] = useState(false);
  const [errorState, setErrorState] = useState(/** @type {ApiErrorState | null} */ (null));

  const [expandedId, setExpandedId] = useState(
    /** @type {string | number | null} */ (null)
  );
  const [detailData, setDetailData] = useState(
    /** @type {{ [key: string]: OrphanDetail }} */ ({})
  );
  const [detailLoading, setDetailLoading] = useState(
    /** @type {string | number | null} */ (null)
  );

  const [selectedIds, setSelectedIds] = useState(
    /** @type {Set<string | number>} */ (new Set())
  );
  const [batchDeleting, setBatchDeleting] = useState(false);
  const [orphanActionMessage, setOrphanActionMessage] = useState(
    /** @type {string | null} */ (null)
  );

  const orphanRequestSeqRef = useRef(0);
  const detailRequestSeqRef = useRef(0);
  const mountedRef = useRef(false);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      orphanRequestSeqRef.current += 1;
      detailRequestSeqRef.current += 1;
    };
  }, []);

  const error = useMemo(() => {
    if (!errorState) return null;
    return `${t('maintenance.errors.loadOrphans')}: ${extractApiError(
      errorState.error,
      t(errorState.fallbackKey)
    )}`;
  }, [errorState, t]);

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

  useEffect(() => {
    let cancelled = false;
    const safeLoadOrphans = async () => {
      if (cancelled) return;
      await loadOrphans();
    };
    void safeLoadOrphans();
    return () => {
      cancelled = true;
    };
  }, [loadOrphans]);

  /**
   * @param {string | number} id
   * @param {{ stopPropagation?: () => void } | undefined} [event]
   */
  const toggleSelect = useCallback((id, event) => {
    if (event && typeof event.stopPropagation === 'function') {
      event.stopPropagation();
    }
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  /** @param {OrphanEntry[]} items */
  const toggleSelectAll = useCallback((items) => {
    const ids = items.map((i) => i.id);
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
  }, []);

  const clearSelection = useCallback(() => {
    setSelectedIds(new Set());
  }, []);

  /** @param {string | number} id */
  const handleExpand = useCallback(
    async (id) => {
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
        setDetailData((prev) => ({ ...prev, [id]: data }));
      } catch (err) {
        if (!mountedRef.current || requestSeq !== detailRequestSeqRef.current) return;
        setDetailData((prev) => ({
          ...prev,
          [id]: {
            errorState: { error: err, fallbackKey: 'maintenance.errors.loadOrphanDetail' },
          },
        }));
      } finally {
        if (!mountedRef.current || requestSeq !== detailRequestSeqRef.current) return;
        setDetailLoading(null);
      }
    },
    [detailData, expandedId]
  );

  const handleBatchDelete = useCallback(async () => {
    const count = selectedIds.size;
    if (count === 0) return;
    setOrphanActionMessage(null);
    const confirmResult = confirmWithFallback(
      t('maintenance.prompts.deleteMemories', { count })
    );
    if (!confirmResult.available) {
      setOrphanActionMessage(t('maintenance.errors.confirmUnavailable'));
      return;
    }
    if (!confirmResult.confirmed) return;

    setBatchDeleting(true);
    const toDelete = [...selectedIds];
    /** @type {{ id: string | number, error: unknown }[]} */
    const failed = [];

    try {
      const outcomes = await mapWithConcurrency(
        toDelete,
        ORPHAN_DELETE_CONCURRENCY,
        async (id) => {
          try {
            await deleteOrphanMemory(id);
            return { id, ok: true };
          } catch (error) {
            return { id, ok: false, error };
          }
        }
      );
      outcomes.forEach(({ id, ok, error }) => {
        if (!ok) failed.push({ id, error });
      });
    } finally {
      if (mountedRef.current) {
        setBatchDeleting(false);
      }
    }

    if (!mountedRef.current) return;

    const failedIds = failed.map((item) => item.id);
    const failedSet = new Set(failedIds);
    setOrphans((prev) =>
      prev.filter((item) => !toDelete.includes(item.id) || failedSet.has(item.id))
    );
    setSelectedIds(new Set(failedIds));

    if (expandedId && toDelete.includes(expandedId) && !failedSet.has(expandedId)) {
      setExpandedId(null);
    }

    if (failed.length > 0) {
      const message = t('maintenance.errors.deleteSummary', {
        failed: failed.length,
        count,
        ids: failed
          .map(({ id, error }) => `${id}: ${extractApiError(error, t('maintenance.errors.deleteFailed'))}`)
          .join(', '),
      });
      if (!alertWithFallback(message)) {
        setOrphanActionMessage(message);
      }
    }
  }, [expandedId, selectedIds, t]);

  const deprecated = useMemo(
    () => orphans.filter((o) => o.category === 'deprecated'),
    [orphans]
  );
  const orphaned = useMemo(
    () => orphans.filter((o) => o.category === 'orphaned'),
    [orphans]
  );

  return {
    orphans,
    deprecated,
    orphaned,
    loading,
    error,
    expandedId,
    detailData,
    detailLoading,
    selectedIds,
    batchDeleting,
    orphanActionMessage,
    loadOrphans,
    handleExpand,
    toggleSelect,
    toggleSelectAll,
    handleBatchDelete,
    clearSelection,
  };
}
