import React, { useCallback, useRef } from 'react';
import clsx from 'clsx';

export default function MaintenanceTabs({ activeTab, onTabChange, tabs, baseId }) {
  const tabRefs = useRef(new Map());
  const items = Array.isArray(tabs) ? tabs : [];

  const focusTabAt = useCallback(
    (index) => {
      const target = items[index];
      if (!target) return;
      const node = tabRefs.current.get(target.id);
      if (node) {
        node.focus();
      }
      onTabChange?.(target.id);
    },
    [items, onTabChange],
  );

  const handleKeyDown = useCallback(
    (event, index) => {
      const lastIndex = items.length - 1;
      if (lastIndex < 0) return;

      switch (event.key) {
        case 'ArrowRight': {
          event.preventDefault();
          const next = index >= lastIndex ? 0 : index + 1;
          focusTabAt(next);
          break;
        }
        case 'ArrowLeft': {
          event.preventDefault();
          const prev = index <= 0 ? lastIndex : index - 1;
          focusTabAt(prev);
          break;
        }
        case 'Home': {
          event.preventDefault();
          focusTabAt(0);
          break;
        }
        case 'End': {
          event.preventDefault();
          focusTabAt(lastIndex);
          break;
        }
        default:
          break;
      }
    },
    [focusTabAt, items.length],
  );

  return (
    <div
      role="tablist"
      aria-orientation="horizontal"
      className="scrollbar-hide -mx-1 flex gap-1 overflow-x-auto px-1"
    >
      {items.map((tab, index) => {
        const isActive = tab.id === activeTab;
        const Icon = tab.icon;
        return (
          <button
            key={tab.id}
            ref={(node) => {
              if (node) {
                tabRefs.current.set(tab.id, node);
              } else {
                tabRefs.current.delete(tab.id);
              }
            }}
            id={`${baseId}-tab-${tab.id}`}
            role="tab"
            type="button"
            aria-selected={isActive}
            aria-controls={`${baseId}-panel-${tab.id}`}
            tabIndex={isActive ? 0 : -1}
            onClick={() => onTabChange?.(tab.id)}
            onKeyDown={(event) => handleKeyDown(event, index)}
            className={clsx(
              'flex flex-shrink-0 items-center gap-2 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors',
              'focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-1',
              isActive
                ? 'border bg-white/60 shadow-sm'
                : 'border border-transparent hover:bg-white/30',
            )}
            style={
              isActive
                ? {
                    color: 'var(--palace-ink)',
                    borderColor: 'var(--palace-line)',
                  }
                : {
                    color: 'var(--palace-muted)',
                  }
            }
          >
            {Icon ? <Icon size={16} aria-hidden="true" /> : null}
            <span>{tab.label}</span>
          </button>
        );
      })}
    </div>
  );
}
