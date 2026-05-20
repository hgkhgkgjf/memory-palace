import React from 'react';
import { motion } from 'framer-motion';
import { Activity, Archive, ShieldCheck, CalendarClock } from 'lucide-react';
import useReducedMotion from '../shared/useReducedMotion';

/** @type {[number, number, number, number]} */
const EASE_OUT = [0, 0, 0.2, 1];

const formatNumber = (value, fallback = 0) => {
  const num = Number(value);
  return Number.isFinite(num) ? num : fallback;
};

/**
 * Stat strip summarising the projected decay simulation result.
 *
 * @param {{
 *   simulationData: import('./useForgetting').ForgettingSimulation | null | undefined,
 *   threshold: number,
 *   simulationDays: number,
 *   t: (key: string, options?: object) => string,
 * }} props
 */
const ForgettingSummary = ({ simulationData, threshold, simulationDays, t }) => {
  const reducedMotion = useReducedMotion();
  if (!simulationData) return null;

  const total = formatNumber(simulationData.total_candidates, 0);
  const archived = formatNumber(simulationData.projected_archived, 0);
  const retained = formatNumber(simulationData.projected_retained, 0);
  const days = formatNumber(simulationData.simulation_days, simulationDays);
  const effectiveThreshold = formatNumber(simulationData.threshold, threshold);

  const items = [
    {
      key: 'total',
      icon: Activity,
      label: t('maintenance.forgetting.summary.totalCandidates'),
      value: total,
      hint: `${t('maintenance.forgetting.distribution.threshold')}: ${effectiveThreshold.toFixed(2)}`,
      tone: 'var(--palace-ink)',
    },
    {
      key: 'archived',
      icon: Archive,
      label: t('maintenance.forgetting.summary.projectedArchived'),
      value: archived,
      hint: t('maintenance.forgetting.outOfTotal', { count: total }),
      tone: 'var(--palace-accent-2)',
    },
    {
      key: 'retained',
      icon: ShieldCheck,
      label: t('maintenance.forgetting.summary.projectedRetained'),
      value: retained,
      hint: t('maintenance.forgetting.outOfTotal', { count: total }),
      tone: 'var(--palace-ink)',
    },
    {
      key: 'days',
      icon: CalendarClock,
      label: t('maintenance.forgetting.summary.simulationDays'),
      value: days,
      hint: t('maintenance.forgetting.simulationDays', { count: days }),
      tone: 'var(--palace-ink)',
    },
  ];

  return (
    <div className="flex flex-wrap gap-3 sm:flex-nowrap" data-testid="forgetting-summary">
      {items.map((item, index) => {
        const Icon = item.icon;
        return (
          <motion.div
            key={item.key}
            initial={reducedMotion ? false : { opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={
              reducedMotion
                ? { duration: 0 }
                : { duration: 0.25, ease: EASE_OUT, delay: index * 0.04 }
            }
            className="glass-card flex min-w-[140px] flex-1 items-start gap-3 rounded-xl bg-white/30 p-3"
            style={{ borderColor: 'var(--palace-line)' }}
          >
            <Icon
              size={16}
              strokeWidth={1.75}
              aria-hidden="true"
              style={{ color: 'var(--palace-accent)' }}
              className="mt-0.5 shrink-0"
            />
            <div className="flex flex-col gap-0.5">
              <span
                className="text-[10px] font-semibold uppercase tracking-[0.14em]"
                style={{ color: 'var(--palace-muted)' }}
              >
                {item.label}
              </span>
              <span
                className="font-display text-2xl font-semibold leading-none"
                style={{ color: item.tone }}
              >
                {item.value}
              </span>
              <span className="text-sm" style={{ color: 'var(--palace-muted)' }}>
                {item.hint}
              </span>
            </div>
          </motion.div>
        );
      })}
    </div>
  );
};

export default ForgettingSummary;
