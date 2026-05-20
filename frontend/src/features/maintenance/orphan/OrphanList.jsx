import React from 'react';
import { Archive, Unlink } from 'lucide-react';
import Checkbox from '../shared/Checkbox';
import { CATEGORY_COLORS } from '../shared/palette';
import OrphanCard from './OrphanCard';

/**
 * @typedef {import('./useOrphans').OrphanEntry} OrphanEntry
 * @typedef {import('./useOrphans').OrphanDetail} OrphanDetail
 */

/**
 * @param {{
 *   icon: React.ComponentType<any>,
 *   label: string,
 *   color: { text: string, icon: string },
 *   items: OrphanEntry[],
 *   selectedIds: Set<string | number>,
 *   onToggleSelectAll: (items: OrphanEntry[]) => void,
 *   selectGroupLabel: string,
 *   deselectGroupLabel: string,
 * }} props
 */
function GroupHeader({
  icon: Icon,
  label,
  color,
  items,
  selectedIds,
  onToggleSelectAll,
  selectGroupLabel,
  deselectGroupLabel,
}) {
  const allSelected =
    items.length > 0 && items.every((item) => selectedIds.has(item.id));
  const someSelected = !allSelected && items.some((item) => selectedIds.has(item.id));

  const handleChange = () => {
    onToggleSelectAll(items);
  };

  return (
    <div className="mb-3 flex items-center gap-3">
      <Checkbox
        checked={allSelected}
        indeterminate={someSelected}
        onChange={handleChange}
        label={allSelected ? deselectGroupLabel : selectGroupLabel}
      />
      <Icon
        size={16}
        style={{ color: color.icon }}
        aria-hidden="true"
        className="flex-shrink-0"
      />
      <h3
        className="text-xs font-bold uppercase tracking-widest"
        style={{ color: color.text }}
      >
        {label}
      </h3>
      <span
        className="rounded-full px-2 py-0.5 text-[11px]"
        style={{
          background: 'rgba(255, 255, 255, 0.55)',
          color: 'var(--palace-muted)',
          border: '1px solid var(--palace-line)',
        }}
      >
        {items.length}
      </span>
    </div>
  );
}

/**
 * @param {{
 *   deprecated: OrphanEntry[],
 *   orphaned: OrphanEntry[],
 *   selectedIds: Set<string | number>,
 *   expandedId: string | number | null,
 *   detailData: { [key: string]: OrphanDetail },
 *   detailLoading: string | number | null,
 *   onToggleSelect: (id: string | number, event?: { stopPropagation?: () => void }) => void,
 *   onToggleSelectAll: (items: OrphanEntry[]) => void,
 *   onExpand: (id: string | number) => void,
 *   t: (key: string, options?: object) => string,
 * }} props
 */
export default function OrphanList({
  deprecated,
  orphaned,
  selectedIds,
  expandedId,
  detailData,
  detailLoading,
  onToggleSelect,
  onToggleSelectAll,
  onExpand,
  t,
}) {
  const deprecatedLabel = t('maintenance.deprecatedVersions');
  const orphanedLabel = t('maintenance.orphanedMemories');
  const getSelectGroupLabel = (label) => t('maintenance.orphan.selectGroup', { group: label });
  const getDeselectGroupLabel = (label) =>
    t('maintenance.orphan.deselectGroup', { group: label });

  /** @param {OrphanEntry[]} items */
  const renderItems = (items) =>
    items.map((item) => (
      <OrphanCard
        key={item.id}
        item={item}
        isExpanded={expandedId === item.id}
        isChecked={selectedIds.has(item.id)}
        isLoadingDetail={detailLoading === item.id}
        detail={detailData[item.id]}
        onToggleSelect={onToggleSelect}
        onExpand={onExpand}
        t={t}
      />
    ));

  return (
    <div className="space-y-8">
      {deprecated.length > 0 ? (
        <section aria-label={deprecatedLabel}>
          <GroupHeader
            icon={Archive}
            label={deprecatedLabel}
            color={CATEGORY_COLORS.deprecated}
            items={deprecated}
            selectedIds={selectedIds}
            onToggleSelectAll={onToggleSelectAll}
            selectGroupLabel={getSelectGroupLabel(deprecatedLabel)}
            deselectGroupLabel={getDeselectGroupLabel(deprecatedLabel)}
          />
          <div className="space-y-2">{renderItems(deprecated)}</div>
        </section>
      ) : null}

      {orphaned.length > 0 ? (
        <section aria-label={orphanedLabel}>
          <GroupHeader
            icon={Unlink}
            label={orphanedLabel}
            color={CATEGORY_COLORS.orphaned}
            items={orphaned}
            selectedIds={selectedIds}
            onToggleSelectAll={onToggleSelectAll}
            selectGroupLabel={getSelectGroupLabel(orphanedLabel)}
            deselectGroupLabel={getDeselectGroupLabel(orphanedLabel)}
          />
          <div className="space-y-2">{renderItems(orphaned)}</div>
        </section>
      ) : null}
    </div>
  );
}
