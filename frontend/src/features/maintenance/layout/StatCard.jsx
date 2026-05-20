import React from 'react';
import { motion, useReducedMotion } from 'framer-motion';

/** @type {[number, number, number, number]} */
const EASE_OUT = [0, 0, 0.2, 1];

/**
 * @param {{
 *   id?: string,
 *   icon?: React.ComponentType<any>,
 *   label: string,
 *   value: string | number,
 *   hint?: string,
 *   color?: { bg?: string, border?: string, text?: string, icon?: string },
 * }} props
 */
export default function StatCard({ id, icon: Icon, label, value, hint, color }) {
  const prefersReducedMotion = useReducedMotion();
  const palette = color || {};

  const pulseAnimation = prefersReducedMotion
    ? { scale: 1 }
    : { scale: [1, 1.08, 1] };

  return (
    <div
      className="glass-card rounded-xl p-4"
      data-testid={id ? `maintenance-stat-${id}` : undefined}
      style={{
        background: palette.bg || 'rgba(255, 255, 255, 0.55)',
        borderColor: palette.border || 'var(--palace-line)',
      }}
    >
      <div className="flex items-center gap-2">
        {Icon ? (
          <Icon
            size={14}
            className="flex-shrink-0"
            style={{ color: palette.icon || palette.text || 'var(--palace-accent)' }}
            aria-hidden="true"
          />
        ) : null}
        <span
          className="text-[11px] font-semibold uppercase tracking-wider"
          style={{ color: 'var(--palace-muted)' }}
        >
          {label}
        </span>
      </div>
      <motion.div
        key={value}
        initial={false}
        animate={pulseAnimation}
        transition={{ duration: 0.4, ease: EASE_OUT }}
        className="font-display mt-2 text-3xl font-bold leading-none"
        style={{ color: palette.text || 'var(--palace-ink)' }}
      >
        {value}
      </motion.div>
      {hint ? (
        <div
          className="mt-2 text-[11px] leading-snug"
          style={{ color: 'var(--palace-muted)' }}
        >
          {hint}
        </div>
      ) : null}
    </div>
  );
}
