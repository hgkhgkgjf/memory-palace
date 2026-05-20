import React, { useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { Activity, Clock, MousePointerClick, Trash2, Lock } from 'lucide-react';
import Checkbox from '../shared/Checkbox';
import StatusPill from '../shared/StatusPill';
import { formatScore } from '../shared/formatters';

const formatDays = (value) => {
  const num = Number(value);
  return Number.isFinite(num) ? num.toFixed(1) : '--';
};

const formatAccess = (value) => {
  const num = Number(value);
  if (!Number.isFinite(num)) return value ?? 0;
  return num;
};

/**
 * @param {{
 *   item: import('./useVitality').VitalityCandidate,
 *   selected: boolean,
 *   onToggleSelect: (memoryId: string | number) => void,
 *   disabled?: boolean,
 * }} props
 */
const VitalityCandidateRow = ({ item, selected, onToggleSelect, disabled = false }) => {
  const { t } = useTranslation();
  const memoryId = item.memory_id;
  const canDelete = Boolean(item.can_delete);
  const labelContext = item.uri || `#${memoryId}`;
  const selectLabel = selected
    ? t('maintenance.vitality.deselectCandidate', { id: memoryId, uri: labelContext })
    : t('maintenance.vitality.selectCandidate', { id: memoryId, uri: labelContext });

  const handleToggle = useCallback(() => {
    if (disabled) return;
    onToggleSelect(memoryId);
  }, [disabled, memoryId, onToggleSelect]);

  return (
    <article
      className={clsx(
        'glass-card rounded-xl border p-3 transition-colors',
        selected
          ? 'border-[color:var(--palace-accent)] shadow-[0_4px_12px_rgba(212,175,55,0.18)]'
          : 'border-[color:var(--palace-line)]'
      )}
      data-testid={`vitality-candidate-${memoryId}`}
      style={{ background: 'rgba(255, 250, 244, 0.9)' }}
    >
      <div className="flex items-start gap-3">
        <div className="pt-0.5">
          <Checkbox
            checked={selected}
            disabled={disabled}
            onChange={handleToggle}
            id={`vitality-row-${memoryId}`}
            label={selectLabel}
            className="select-none"
          />
        </div>

        <div className="min-w-0 flex-1">
          <header className="mb-2 flex flex-wrap items-center gap-2">
            <code
              className="rounded px-1.5 py-0.5 text-[11px] font-mono"
              style={{
                background: 'rgba(247, 240, 226, 0.7)',
                color: 'var(--palace-accent-2)',
                border: '1px solid var(--palace-line)',
              }}
            >
              #{memoryId}
            </code>
            <StatusPill
              category={canDelete ? 'orphaned' : 'review'}
              label={
                canDelete
                  ? t('maintenance.vitality.deletable')
                  : t('maintenance.vitality.activePaths')
              }
              icon={canDelete ? Trash2 : Lock}
            />
            <span
              className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px]"
              style={{
                background: 'rgba(94, 127, 163, 0.12)',
                color: '#5e7fa3',
                border: '1px solid rgba(94, 127, 163, 0.25)',
              }}
              title={t('maintenance.vitality.vitality', {
                value: formatScore(item.vitality_score),
              })}
            >
              <Activity size={11} strokeWidth={2} aria-hidden="true" />
              <span className="font-mono">{formatScore(item.vitality_score)}</span>
            </span>
            <span
              className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px]"
              style={{
                background: 'rgba(127, 111, 93, 0.1)',
                color: 'var(--palace-muted)',
                border: '1px solid var(--palace-line)',
              }}
              title={t('maintenance.vitality.inactive', {
                value: formatDays(item.inactive_days),
              })}
            >
              <Clock size={11} strokeWidth={2} aria-hidden="true" />
              <span className="font-mono">
                {t('maintenance.vitality.inactive', {
                  value: formatDays(item.inactive_days),
                })}
              </span>
            </span>
            <span
              className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px]"
              style={{
                background: 'rgba(127, 111, 93, 0.1)',
                color: 'var(--palace-muted)',
                border: '1px solid var(--palace-line)',
              }}
              title={t('maintenance.vitality.access', {
                value: formatAccess(item.access_count),
              })}
            >
              <MousePointerClick size={11} strokeWidth={2} aria-hidden="true" />
              <span className="font-mono">
                {t('maintenance.vitality.access', {
                  value: formatAccess(item.access_count),
                })}
              </span>
            </span>
          </header>

          <div
            className="mb-2 break-all text-[11px]"
            style={{ color: 'var(--palace-muted)' }}
          >
            {item.uri || t('maintenance.vitality.noPath')}
          </div>

          {item.content_snippet ? (
            <div
              className="rounded-lg px-3 py-2 text-[12px] font-mono leading-relaxed"
              style={{
                background: 'rgba(255, 255, 255, 0.3)',
                color: 'var(--palace-ink)',
                border: '1px solid var(--palace-line)',
              }}
            >
              {item.content_snippet}
            </div>
          ) : null}
        </div>
      </div>
    </article>
  );
};

export default VitalityCandidateRow;
