import React, { useEffect } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { useTranslation } from 'react-i18next';
import { Archive, Inbox, RefreshCw, Shield, ThumbsUp, TrendingDown } from 'lucide-react';

import SectionCard from './shared/SectionCard';
import EmptyState from './shared/EmptyState';
import ErrorBanner from './shared/ErrorBanner';
import LoadingPulse from './shared/LoadingPulse';
import SelectionBar from './shared/SelectionBar';
import useReducedMotion from './shared/useReducedMotion';

import { useForgetting } from './forgetting/useForgetting';
import ForgettingToolbar from './forgetting/ForgettingToolbar';
import ForgettingSummary from './forgetting/ForgettingSummary';
import ForgettingDistribution from './forgetting/ForgettingDistribution';
import ForgettingCandidateCard from './forgetting/ForgettingCandidateCard';

/** @type {[number, number, number, number]} */
const EASE_OUT = [0, 0, 0.2, 1];

/**
 * Forgetting Simulation panel — thin composition root for the maintenance
 * dashboard. All state, side effects, and the production prepare/confirm
 * archive flow live in `useForgetting`; rendering is delegated to small
 * subcomponents under `./forgetting/`.
 *
 * @param {{
 *   onInspectMemory?: (memoryId: string | number) => void,
 *   onStatsChange?: (stats: { forgetting?: number }) => void,
 * }} props
 */
export default function ForgettingPanel({ onInspectMemory, onStatsChange }) {
  const { t } = useTranslation();
  const reducedMotion = useReducedMotion();
  const {
    candidates,
    loading,
    error,
    isMock,
    selectedIds,
    busyId,
    message,
    thresholdInput,
    daysInput,
    threshold,
    simulationDays,
    setThreshold,
    setSimulationDays,
    simulationData,
    loadData,
    handleKeep,
    handleArchive,
    handleBatchArchive,
    handleBatchKeep,
    handleInspect,
    toggleSelect,
    clearSelection,
  } = useForgetting({ onInspectMemory });

  const busy = busyId !== null;
  const selectedCount = selectedIds.size;

  useEffect(() => {
    if (typeof onStatsChange === 'function') {
      onStatsChange({ forgetting: candidates.length });
    }
  }, [candidates.length, onStatsChange]);

  return (
    <SectionCard as="section" aria-label={t('maintenance.forgetting.title')}>
      <div className="flex flex-col gap-4">
        <header className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex flex-col gap-1">
            <h2
              className="font-display flex items-center gap-2 text-base font-semibold"
              style={{ color: 'var(--palace-ink)' }}
            >
              <TrendingDown
                size={16}
                strokeWidth={2}
                aria-hidden="true"
                style={{ color: 'var(--palace-accent)' }}
              />
              {t('maintenance.forgetting.title')}
            </h2>
            <p className="text-xs" style={{ color: 'var(--palace-muted)' }}>
              {t('maintenance.forgetting.subtitle')}
            </p>
          </div>
          <ForgettingToolbar
            loading={loading}
            busy={busy}
            isMock={isMock}
            selectedCount={selectedCount}
            onRefresh={loadData}
            onBatchKeep={handleBatchKeep}
            onBatchArchive={handleBatchArchive}
            t={t}
          />
        </header>

        {error ? <ErrorBanner message={error} onRetry={loadData} retryLabel={t('common.actions.refresh')} /> : null}

        <div className="grid gap-3 sm:grid-cols-2">
          <label
            htmlFor="forgetting-threshold-input"
            className="glass-card flex flex-col gap-1 rounded-xl bg-white/30 p-3"
            style={{ borderColor: 'var(--palace-line)' }}
          >
            <span
              className="text-[10px] font-semibold uppercase tracking-[0.14em]"
              style={{ color: 'var(--palace-muted)' }}
            >
              {t('maintenance.forgetting.thresholdLabel')}
            </span>
            <input
              id="forgetting-threshold-input"
              data-testid="forgetting-threshold-input"
              type="number"
              step="0.05"
              min="0"
              max="1"
              value={thresholdInput}
              onChange={(e) => setThreshold(e.target.value)}
              className="w-full rounded-lg border bg-white/80 px-2 py-1.5 text-sm focus:outline-none focus:ring-2"
              style={{ borderColor: 'var(--palace-line)', color: 'var(--palace-ink)' }}
            />
          </label>
          <label
            htmlFor="forgetting-days-input"
            className="glass-card flex flex-col gap-1 rounded-xl bg-white/30 p-3"
            style={{ borderColor: 'var(--palace-line)' }}
          >
            <span
              className="text-[10px] font-semibold uppercase tracking-[0.14em]"
              style={{ color: 'var(--palace-muted)' }}
            >
              {t('maintenance.forgetting.daysLabel')}
            </span>
            <input
              id="forgetting-days-input"
              data-testid="forgetting-days-input"
              type="number"
              min="1"
              max="365"
              value={daysInput}
              onChange={(e) => setSimulationDays(e.target.value)}
              className="w-full rounded-lg border bg-white/80 px-2 py-1.5 text-sm focus:outline-none focus:ring-2"
              style={{ borderColor: 'var(--palace-line)', color: 'var(--palace-ink)' }}
            />
          </label>
        </div>

        <div className="flex flex-col gap-2">
          <h3
            className="flex items-center gap-2 text-sm font-semibold"
            style={{ color: 'var(--palace-ink)' }}
          >
            <Shield
              size={14}
              strokeWidth={2}
              aria-hidden="true"
              style={{ color: 'var(--palace-accent)' }}
            />
            {t('maintenance.forgetting.simulationHeading')}
          </h3>
          <ForgettingSummary
            simulationData={simulationData}
            threshold={threshold}
            simulationDays={simulationDays}
            t={t}
          />
        </div>

        <ForgettingDistribution candidates={candidates} threshold={threshold} t={t} />

        <div className="flex flex-col gap-3">
          <h3
            className="flex items-center gap-2 text-sm font-semibold"
            style={{ color: 'var(--palace-ink)' }}
          >
            <Archive
              size={14}
              strokeWidth={2}
              aria-hidden="true"
              style={{ color: 'var(--palace-accent)' }}
            />
            {t('maintenance.forgetting.queueHeading')}
          </h3>

          {message ? (
            <div
              role="status"
              className="rounded-lg border bg-white/40 px-3 py-2 text-xs"
              style={{ borderColor: 'var(--palace-line)', color: 'var(--palace-muted)' }}
            >
              {message}
            </div>
          ) : null}

          {loading ? (
            <div
              className="flex items-center gap-2 text-xs"
              style={{ color: 'var(--palace-muted)' }}
            >
              <RefreshCw size={14} strokeWidth={2} className="animate-spin" aria-hidden="true" />
              {t('maintenance.forgetting.loading')}
              <LoadingPulse lines={2} className="ml-2 flex-1" />
            </div>
          ) : candidates.length === 0 ? (
            <EmptyState
              icon={Inbox}
              title={t('maintenance.forgetting.noCandidates')}
              description={t('maintenance.forgetting.subtitle')}
            />
          ) : (
            <div className="grid gap-3 lg:grid-cols-2">
              <AnimatePresence initial={false}>
                {candidates.map((candidate, index) => (
                  <motion.div
                    key={candidate.memory_id}
                    layout
                    initial={reducedMotion ? false : { opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={reducedMotion ? { opacity: 0 } : { opacity: 0, y: -8 }}
                    transition={
                      reducedMotion
                        ? { duration: 0.12 }
                        : { duration: 0.25, ease: EASE_OUT, delay: index * 0.03 }
                    }
                  >
                    <ForgettingCandidateCard
                      candidate={candidate}
                      selected={selectedIds.has(candidate.memory_id)}
                      onToggleSelect={toggleSelect}
                      onKeep={handleKeep}
                      onArchive={handleArchive}
                      onInspect={handleInspect}
                      busy={busy}
                      busyId={busyId}
                      threshold={threshold}
                      t={t}
                    />
                  </motion.div>
                ))}
              </AnimatePresence>
            </div>
          )}
        </div>
      </div>

      <SelectionBar
        count={selectedCount}
        clearLabel={t('maintenance.forgetting.deselect')}
        onClear={clearSelection}
        ariaLabel={t('maintenance.forgetting.selectionRegion')}
        countLabel={t('maintenance.shared.selected', { count: selectedCount })}
      >
        <button
          type="button"
          onClick={handleBatchKeep}
          disabled={busy}
          className="palace-btn-ghost text-xs"
        >
          <ThumbsUp size={12} strokeWidth={2} aria-hidden="true" />
          {t('maintenance.forgetting.batchKeep')}
        </button>
        <button
          type="button"
          onClick={handleBatchArchive}
          disabled={busy}
          className="inline-flex cursor-pointer items-center gap-1 rounded-lg border px-2.5 py-1 text-xs font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-45 focus:outline-none focus:ring-2"
          style={{
            background: 'rgba(244, 236, 224, 0.9)',
            borderColor: 'rgba(200, 171, 134, 0.65)',
            color: 'var(--palace-accent-2)',
          }}
        >
          <Archive size={12} strokeWidth={2} aria-hidden="true" />
          {t('maintenance.forgetting.batchArchive')}
        </button>
      </SelectionBar>
    </SectionCard>
  );
}
