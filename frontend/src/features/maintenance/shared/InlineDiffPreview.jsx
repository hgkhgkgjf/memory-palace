import React, { useId, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { ChevronDown, ChevronRight, Loader2 } from 'lucide-react';
import clsx from 'clsx';
import { useTranslation } from 'react-i18next';
import DiffViewer from '../../../components/DiffViewer';
import { useReducedMotion } from './useReducedMotion';

/** @type {[number, number, number, number]} */
const EASE_OUT = [0, 0, 0.2, 1];

/**
 * @typedef {{
 *   fromLabel: string,
 *   toLabel: string,
 *   oldContent: string,
 *   newContent: string,
 *   loading?: boolean,
 *   error?: string | null,
 *   defaultOpen?: boolean,
 *   className?: string,
 * }} InlineDiffPreviewProps
 */

/**
 * Collapsible wrapper around DiffViewer with accessible expand/collapse.
 *
 * @param {InlineDiffPreviewProps} props
 */
const InlineDiffPreview = ({
  fromLabel,
  toLabel,
  oldContent,
  newContent,
  loading = false,
  error = null,
  defaultOpen = false,
  className,
}) => {
  const { t } = useTranslation();
  const [open, setOpen] = useState(Boolean(defaultOpen));
  const panelId = useId();

  // useReducedMotion already accounts for the Edge browser profile, so this
  // single value drives all motion gating in this component.
  const disableAnimation = useReducedMotion();

  const toggle = () => setOpen((prev) => !prev);

  const Chevron = open ? ChevronDown : ChevronRight;

  const transition = disableAnimation
    ? { duration: 0 }
    : { duration: 0.2, ease: EASE_OUT };

  const renderBody = () => {
    if (loading) {
      return (
        <div
          className="flex items-center gap-2 px-3 py-4 text-xs text-[color:var(--palace-muted)]"
          role="status"
          aria-live="polite"
        >
          <Loader2
            size={14}
            className={clsx(
              'text-[color:var(--palace-accent-2)]',
              !disableAnimation && 'animate-spin'
            )}
            aria-hidden="true"
          />
          <span>{t('maintenance.card.loadingDiff')}</span>
        </div>
      );
    }

    if (error) {
      return (
        <div
          className="px-3 py-3 text-xs italic text-[color:var(--palace-muted)]"
          role="alert"
        >
          {error}
        </div>
      );
    }

    return (
      <div className="px-3 py-3">
        <DiffViewer oldText={oldContent} newText={newContent} />
      </div>
    );
  };

  return (
    <div
      className={clsx(
        'overflow-hidden rounded-lg border border-[color:var(--palace-line)] bg-[rgba(255,250,244,0.7)]',
        className
      )}
      data-testid="inline-diff-preview"
    >
      <button
        type="button"
        onClick={toggle}
        aria-expanded={open}
        aria-controls={panelId}
        className={clsx(
          'flex w-full items-center gap-2 px-3 py-2 text-left text-xs font-medium text-[color:var(--palace-ink)] transition-colors',
          'hover:bg-[rgba(245,238,228,0.65)] focus:outline-none focus:ring-2 focus:ring-[rgba(179,133,79,0.35)]'
        )}
      >
        <Chevron
          size={14}
          className="shrink-0 text-[color:var(--palace-accent-2)]"
          aria-hidden="true"
        />
        <span className="flex flex-wrap items-center gap-1 truncate">
          <span className="font-mono text-[color:var(--palace-muted)]">{fromLabel}</span>
          <span aria-hidden="true" className="text-[color:var(--palace-muted)]">→</span>
          <span className="font-mono text-[color:var(--palace-accent-2)]">{toLabel}</span>
        </span>
      </button>

      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            id={panelId}
            key="diff-body"
            initial={disableAnimation ? false : { height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={transition}
            style={{ overflow: 'hidden' }}
            className="border-t border-[color:var(--palace-line)] bg-white/40"
          >
            {renderBody()}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};

export default InlineDiffPreview;
