import React, { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { AnimatePresence, motion } from 'framer-motion';
import Checkbox from '../shared/Checkbox';
import { useReducedMotion } from '../shared/useReducedMotion';
import VitalityCandidateRow from './VitalityCandidateRow';

/** @type {[number, number, number, number]} */
const EASE_OUT = [0, 0, 0.2, 1];
const REDUCE_MOTION_CANDIDATE_COUNT = 50;

/**
 * @param {{
 *   candidates: import('./useVitality').VitalityCandidate[],
 *   selectedIds: Set<string | number>,
 *   onToggleSelect: (memoryId: string | number) => void,
 *   onToggleSelectAll: () => void,
 *   disabled?: boolean,
 * }} props
 */
const VitalityCandidateTable = ({
  candidates,
  selectedIds,
  onToggleSelect,
  onToggleSelectAll,
  disabled = false,
}) => {
  const { t } = useTranslation();
  const reducedMotion = useReducedMotion();
  const shouldReduceListMotion =
    reducedMotion || candidates.length > REDUCE_MOTION_CANDIDATE_COUNT;

  const { allSelected, someSelected } = useMemo(() => {
    if (!candidates.length) return { allSelected: false, someSelected: false };
    let selectedCount = 0;
    for (const item of candidates) {
      if (selectedIds.has(item.memory_id)) selectedCount += 1;
    }
    return {
      allSelected: selectedCount === candidates.length,
      someSelected: selectedCount > 0 && selectedCount < candidates.length,
    };
  }, [candidates, selectedIds]);

  return (
    <div className="space-y-3">
      <header
        className="flex flex-wrap items-center justify-between gap-2 rounded-xl border px-3 py-2"
        style={{
          background: 'rgba(255, 255, 255, 0.45)',
          borderColor: 'var(--palace-line)',
        }}
      >
        <Checkbox
          id="vitality-select-all"
          checked={allSelected}
          indeterminate={someSelected}
          disabled={disabled || candidates.length === 0}
          onChange={onToggleSelectAll}
          label={
            allSelected
              ? t('maintenance.deselectAll')
              : t('maintenance.selectAll')
          }
        />
        <div
          className="grid grid-cols-3 gap-4 text-[10px] font-medium uppercase tracking-wider sm:gap-6"
          style={{ color: 'var(--palace-muted)' }}
          aria-hidden="true"
        >
          <span>{t('maintenance.vitality.threshold')}</span>
          <span>{t('maintenance.vitality.inactiveDays')}</span>
          <span>{t('maintenance.vitality.access', { value: '#' })}</span>
        </div>
      </header>

      <ul
        aria-label={t('maintenance.vitality.title')}
        className="space-y-2"
      >
        <AnimatePresence initial={false}>
          {candidates.map((item, index) => {
            if (shouldReduceListMotion) {
              return (
                <li key={item.memory_id}>
                  <VitalityCandidateRow
                    item={item}
                    selected={selectedIds.has(item.memory_id)}
                    onToggleSelect={onToggleSelect}
                    disabled={disabled}
                  />
                </li>
              );
            }

            const motionProps = {
              initial: { opacity: 0, y: 8 },
              animate: { opacity: 1, y: 0 },
              exit: { opacity: 0, y: -4 },
              transition: {
                duration: 0.2,
                delay: Math.min(index * 0.02, 0.2),
                ease: EASE_OUT,
              },
            };
            return (
              <motion.li
                key={item.memory_id}
                layout
                {...motionProps}
              >
                <VitalityCandidateRow
                  item={item}
                  selected={selectedIds.has(item.memory_id)}
                  onToggleSelect={onToggleSelect}
                  disabled={disabled}
                />
              </motion.li>
            );
          })}
        </AnimatePresence>
      </ul>
    </div>
  );
};

export default VitalityCandidateTable;
