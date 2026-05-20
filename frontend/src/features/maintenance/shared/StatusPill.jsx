import React from 'react';
import clsx from 'clsx';
import { CATEGORY_COLORS } from './palette';

/**
 * @param {{
 *   category?: string,
 *   label: string,
 *   icon?: React.ComponentType<any>,
 *   className?: string,
 * }} props
 */
const StatusPill = ({ category, label, icon: Icon, className }) => {
  const palette = CATEGORY_COLORS[category] || CATEGORY_COLORS.review;

  return (
    <span
      className={clsx(
        'inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium',
        className
      )}
      style={{
        background: palette.bg,
        borderColor: palette.border,
        color: palette.text,
      }}
    >
      {Icon ? <Icon size={12} strokeWidth={2} style={{ color: palette.icon }} aria-hidden="true" /> : null}
      <span>{label}</span>
    </span>
  );
};

export default StatusPill;
