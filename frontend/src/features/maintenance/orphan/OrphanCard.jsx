import React from 'react';
import clsx from 'clsx';
import { AnimatePresence, motion } from 'framer-motion';
import {
  Archive,
  ArrowRight,
  ChevronDown,
  ChevronUp,
  Loader2,
  Unlink,
} from 'lucide-react';
import { extractApiError } from '../../../lib/api';
import Checkbox from '../shared/Checkbox';
import DateChip from '../shared/DateChip';
import InlineDiffPreview from '../shared/InlineDiffPreview';
import StatusPill from '../shared/StatusPill';
import { useReducedMotion } from '../shared/useReducedMotion';
import { normalizePaths } from './useOrphans';

/** @type {[number, number, number, number]} */
const EASE_OUT = [0, 0, 0.2, 1];

/**
 * @typedef {import('./useOrphans').OrphanEntry} OrphanEntry
 * @typedef {import('./useOrphans').OrphanDetail} OrphanDetail
 */

/**
 * @param {{
 *   item: OrphanEntry,
 *   isExpanded: boolean,
 *   isChecked: boolean,
 *   isLoadingDetail: boolean,
 *   detail?: OrphanDetail,
 *   onToggleSelect: (id: string | number, event?: { stopPropagation?: () => void }) => void,
 *   onExpand: (id: string | number) => void,
 *   t: (key: string, options?: object) => string,
 * }} props
 */
export default function OrphanCard({
  item,
  isExpanded,
  isChecked,
  isLoadingDetail,
  detail,
  onToggleSelect,
  onExpand,
  t,
}) {
  const reducedMotion = useReducedMotion();
  const isDeprecated = item.category === 'deprecated';
  const migrationTargetPaths = normalizePaths(item?.migration_target?.paths);
  const detailMigrationPaths = normalizePaths(detail?.migration_target?.paths);
  const Chevron = isExpanded ? ChevronUp : ChevronDown;
  const itemLabel = item.content_snippet || `#${item.id}`;
  const checkboxLabel = t(
    isChecked ? 'maintenance.orphan.deselectMemory' : 'maintenance.orphan.selectMemory',
    { id: item.id, label: itemLabel }
  );

  const handleCheckboxChange = (_, event) => {
    if (event && typeof event.stopPropagation === 'function') {
      event.stopPropagation();
    }
    onToggleSelect(item.id, event);
  };

  const expandTransition = reducedMotion
    ? { duration: 0 }
    : { duration: 0.22, ease: EASE_OUT };

  return (
    <div
      className={clsx(
        'group glass-card rounded-xl transition-all duration-200',
        'hover:shadow-[var(--palace-shadow-md,0_4px_18px_rgba(0,0,0,0.08))]'
      )}
      style={{
        borderColor: isExpanded
          ? 'rgba(179, 133, 79, 0.3)'
          : 'var(--palace-line)',
      }}
      onMouseEnter={(event) => {
        event.currentTarget.style.borderColor = 'rgba(179, 133, 79, 0.3)';
      }}
      onMouseLeave={(event) => {
        if (!isExpanded) {
          event.currentTarget.style.borderColor = 'var(--palace-line)';
        }
      }}
    >
      <div className="flex items-start gap-3 p-4">
        <div
          className="mt-0.5 flex-shrink-0"
          onClick={(event) => event.stopPropagation()}
          onKeyDown={(event) => event.stopPropagation()}
        >
          <Checkbox
            checked={isChecked}
            onChange={handleCheckboxChange}
            label={checkboxLabel}
          />
        </div>

        <button
          type="button"
          aria-expanded={isExpanded}
          aria-label={String(item.content_snippet || item.id)}
          onClick={() => onExpand(item.id)}
          className="flex min-w-0 flex-1 cursor-pointer select-none items-start gap-3 rounded-lg text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-[rgba(179,133,79,0.45)]"
        >
          <span className="min-w-0 flex-1">
            <span className="mb-2 flex flex-wrap items-center gap-2">
              <span
                className="rounded-md px-1.5 py-0.5 font-mono text-[11px]"
                style={{
                  background: 'rgba(255, 255, 255, 0.55)',
                  color: 'var(--palace-muted)',
                  border: '1px solid var(--palace-line)',
                }}
              >
                #{item.id}
              </span>

              <StatusPill
                category={isDeprecated ? 'deprecated' : 'orphaned'}
                label={
                  isDeprecated
                    ? t('maintenance.card.deprecated')
                    : t('maintenance.card.orphaned')
                }
                icon={isDeprecated ? Archive : Unlink}
              />

              {item.migrated_to ? (
                <span
                  className="inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 font-mono text-[11px]"
                  style={{
                    background: 'rgba(184, 150, 46, 0.10)',
                    borderColor: 'rgba(184, 150, 46, 0.28)',
                    color: '#8a6e1f',
                  }}
                >
                  <ArrowRight size={10} aria-hidden="true" />#{item.migrated_to}
                </span>
              ) : null}

              <DateChip date={item.created_at} fallback={t('common.states.unknown')} />
            </span>

            {item.migration_target && migrationTargetPaths.length > 0 ? (
              <span className="mb-2 flex flex-wrap items-center gap-1.5">
                <ArrowRight
                  size={12}
                  aria-hidden="true"
                  style={{ color: 'var(--palace-accent)' }}
                  className="flex-shrink-0 opacity-80"
                />
                {migrationTargetPaths.map((p, idx) => (
                  <code
                    key={`${p}-${idx}`}
                    className="rounded border px-1.5 py-0.5 font-mono text-[11px]"
                    style={{
                      background: 'rgba(255, 250, 244, 0.7)',
                      borderColor: 'var(--palace-line)',
                      color: 'var(--palace-accent-2, var(--palace-accent))',
                    }}
                  >
                    {p}
                  </code>
                ))}
              </span>
            ) : null}

            {item.migration_target && migrationTargetPaths.length === 0 ? (
              <span className="mb-2 flex items-center gap-1.5">
                <ArrowRight
                  size={12}
                  aria-hidden="true"
                  style={{ color: 'var(--palace-muted)' }}
                  className="flex-shrink-0"
                />
                <span
                  className="text-[11px] italic"
                  style={{ color: 'var(--palace-muted)' }}
                >
                  {t('maintenance.card.targetNoPaths', {
                    id: item.migration_target.id,
                  })}
                </span>
              </span>
            ) : null}

            <span
              className="block rounded-md p-2.5 font-mono text-[12px] leading-relaxed line-clamp-3"
              style={{
                background: 'rgba(255, 255, 255, 0.3)',
                color: 'var(--palace-muted)',
                border: '1px solid var(--palace-line)',
              }}
            >
              {item.content_snippet}
            </span>
          </span>

          <span
            className="mt-1 flex-shrink-0"
            style={{ color: 'var(--palace-muted)' }}
          >
            <Chevron size={16} aria-hidden="true" />
          </span>
        </button>
      </div>

      <AnimatePresence initial={false}>
        {isExpanded ? (
          <motion.div
            key={`detail-${item.id}`}
            initial={reducedMotion ? false : { height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={expandTransition}
            style={{ overflow: 'hidden' }}
            className="border-t"
          >
            <div
              className="p-5"
              style={{
                borderColor: 'var(--palace-line)',
                background: 'rgba(255, 250, 244, 0.45)',
              }}
            >
              {isLoadingDetail ? (
                <div
                  className="flex items-center gap-3 py-3 text-xs"
                  style={{ color: 'var(--palace-muted)' }}
                  role="status"
                  aria-live="polite"
                >
                  <Loader2
                    size={14}
                    aria-hidden="true"
                    className={reducedMotion ? '' : 'animate-spin'}
                    style={{ color: 'var(--palace-accent)' }}
                  />
                  <span>{t('maintenance.card.loadingFullContent')}</span>
                </div>
              ) : detail?.errorState ? (
                <div
                  className="py-2 text-xs"
                  style={{ color: '#a3553e' }}
                  role="alert"
                >
                  {t('maintenance.card.errorPrefix')}{' '}
                  {extractApiError(
                    detail.errorState.error,
                    t(detail.errorState.fallbackKey)
                  )}
                </div>
              ) : detail ? (
                <div className="space-y-4">
                  {detail.migration_target ? (
                    <InlineDiffPreview
                      fromLabel={`#${item.id}`}
                      toLabel={`#${detail.migration_target.id}${
                        detailMigrationPaths.length > 0
                          ? ` (${detailMigrationPaths[0]})`
                          : ''
                      }`}
                      oldContent={detail.content || ''}
                      newContent={detail.migration_target.content || ''}
                      defaultOpen
                    />
                  ) : (
                    <div>
                      <h4
                        className="mb-2 text-[11px] font-semibold uppercase tracking-widest"
                        style={{ color: 'var(--palace-muted)' }}
                      >
                        {t('maintenance.card.fullContent')}
                      </h4>
                      <div
                        className="custom-scrollbar max-h-64 overflow-y-auto rounded-md p-4 font-mono text-[12px] leading-relaxed whitespace-pre-wrap"
                        style={{
                          background: 'rgba(255, 255, 255, 0.55)',
                          border: '1px solid var(--palace-line)',
                          color: 'var(--palace-ink)',
                        }}
                      >
                        {detail.content}
                      </div>
                    </div>
                  )}
                </div>
              ) : null}
            </div>
          </motion.div>
        ) : null}
      </AnimatePresence>
    </div>
  );
}
