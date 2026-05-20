import React from 'react';
import clsx from 'clsx';
import { AnimatePresence, motion } from 'framer-motion';
import { X } from 'lucide-react';
import { useReducedMotion } from './useReducedMotion';

/** @type {[number, number, number, number]} */
const EASE_OUT = [0, 0, 0.2, 1];

/**
 * @param {{
 *   count?: number,
 *   children?: React.ReactNode,
 *   onClear?: () => void,
 *   clearLabel?: string,
 *   className?: string,
 *   ariaLabel: string,
 *   countLabel?: string,
 * }} props
 */
const SelectionBar = ({
  count = 0,
  children,
  onClear,
  clearLabel = 'Clear',
  className,
  ariaLabel,
  countLabel,
}) => {
  const reducedMotion = useReducedMotion();
  const visible = count > 0;

  const motionProps = reducedMotion
    ? { initial: false, animate: { opacity: 1 }, exit: { opacity: 0 }, transition: { duration: 0.12 } }
    : {
        initial: { opacity: 0, y: 24 },
        animate: { opacity: 1, y: 0 },
        exit: { opacity: 0, y: 24 },
        transition: { duration: 0.22, ease: EASE_OUT },
      };

  return (
    <AnimatePresence>
      {visible ? (
        <motion.div
          key="selection-bar"
          role="region"
          aria-label={ariaLabel}
          className={clsx(
            'pointer-events-auto fixed inset-x-0 bottom-4 z-40 mx-auto flex w-full max-w-3xl items-center gap-3 rounded-2xl border px-4 py-3 shadow-lg',
            className
          )}
          style={{
            background: 'var(--palace-glass-bg)',
            backdropFilter: reducedMotion ? 'none' : 'blur(var(--palace-glass-blur))',
            WebkitBackdropFilter: reducedMotion ? 'none' : 'blur(var(--palace-glass-blur))',
            borderColor: 'var(--palace-line)',
            boxShadow: 'var(--palace-glass-shadow)',
          }}
          {...motionProps}
        >
          <div className="flex flex-1 items-center gap-2 text-sm" style={{ color: 'var(--palace-ink)' }}>
            <span
              className="inline-flex h-6 min-w-[24px] items-center justify-center rounded-full px-1.5 text-xs font-semibold text-white"
              style={{ background: 'var(--palace-accent)' }}
            >
              {count}
            </span>
            {countLabel ? (
              <span style={{ color: 'var(--palace-muted)' }}>{countLabel}</span>
            ) : null}
          </div>

          <div className="flex flex-wrap items-center justify-end gap-2">{children}</div>

          {onClear ? (
            <button
              type="button"
              onClick={onClear}
              className="palace-btn-ghost"
              aria-label={clearLabel}
            >
              <X size={14} strokeWidth={2} aria-hidden="true" />
              <span className="sr-only">{clearLabel}</span>
            </button>
          ) : null}
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
};

export default SelectionBar;
