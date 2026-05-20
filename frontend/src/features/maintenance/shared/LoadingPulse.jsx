import React from 'react';
import clsx from 'clsx';

const WIDTHS = ['100%', '85%', '70%'];

/**
 * @param {{
 *   lines?: number,
 *   className?: string,
 * }} props
 */
const LoadingPulse = ({ lines = 3, className }) => {
  const count = Math.max(1, Math.floor(lines));

  return (
    <div
      className={clsx('flex flex-col gap-2', className)}
      role="status"
      aria-busy="true"
      aria-live="polite"
    >
      {Array.from({ length: count }).map((_, index) => (
        <div
          key={index}
          className="h-3 animate-pulse rounded-full"
          style={{
            width: WIDTHS[index % WIDTHS.length],
            background: 'var(--palace-sand)',
          }}
        />
      ))}
    </div>
  );
};

export default LoadingPulse;
