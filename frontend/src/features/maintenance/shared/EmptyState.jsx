import React from 'react';
import clsx from 'clsx';

/**
 * @param {{
 *   icon?: React.ComponentType<any>,
 *   title?: string,
 *   description?: string,
 *   action?: { label: string, onClick: () => void | Promise<void> },
 *   className?: string,
 * }} props
 */
const EmptyState = ({ icon: Icon, title, description, action, className }) => {
  return (
    <div
      className={clsx(
        'flex flex-col items-center justify-center gap-3 px-6 py-10 text-center',
        className
      )}
    >
      {Icon ? (
        <Icon
          size={40}
          strokeWidth={1.5}
          style={{ color: 'var(--palace-muted)' }}
          aria-hidden="true"
        />
      ) : null}
      {title ? (
        <h3
          className="font-display text-lg"
          style={{ color: 'var(--palace-ink)' }}
        >
          {title}
        </h3>
      ) : null}
      {description ? (
        <p className="max-w-sm text-sm" style={{ color: 'var(--palace-muted)' }}>
          {description}
        </p>
      ) : null}
      {action ? (
        <button
          type="button"
          onClick={action.onClick}
          className="palace-btn-ghost mt-1"
        >
          {action.label}
        </button>
      ) : null}
    </div>
  );
};

export default EmptyState;
