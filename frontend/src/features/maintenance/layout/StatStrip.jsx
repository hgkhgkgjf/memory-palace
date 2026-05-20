import React from 'react';
import { motion, useReducedMotion } from 'framer-motion';
import StatCard from './StatCard';

/** @type {[number, number, number, number]} */
const EASE_OUT = [0, 0, 0.2, 1];

export default function StatStrip({ stats }) {
  const prefersReducedMotion = useReducedMotion();
  const items = Array.isArray(stats) ? stats : [];

  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      {items.map((stat, index) => (
        <motion.div
          key={stat.label || stat.id || index}
          initial={prefersReducedMotion ? false : { opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={
            prefersReducedMotion
              ? { duration: 0 }
              : { duration: 0.3, ease: EASE_OUT, delay: index * 0.04 }
          }
        >
          <StatCard
            icon={stat.icon}
            id={stat.id}
            label={stat.label}
            value={stat.value}
            hint={stat.hint}
            color={stat.color}
          />
        </motion.div>
      ))}
    </div>
  );
}
