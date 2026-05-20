import React, { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import clsx from 'clsx';
import { AnimatePresence, motion } from 'framer-motion';
import { useReducedMotion } from './useReducedMotion';

const FOCUSABLE_SELECTOR = [
  'a[href]',
  'button:not([disabled])',
  'textarea:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',');

/** @type {[number, number, number, number]} */
const EASE_OUT = [0, 0, 0.2, 1];

/**
 * @param {{
 *   open: boolean,
 *   title: string,
 *   description?: string,
 *   phrase?: string,
 *   phrasePrompt?: string,
 *   confirmLabel?: string,
 *   cancelLabel?: string,
 *   onConfirm?: (value: string) => void | Promise<void>,
 *   onCancel?: () => void,
 *   destructive?: boolean,
 *   submitting?: boolean,
 * }} props
 */
const ConfirmPhraseModal = ({
  open,
  title,
  description,
  phrase,
  phrasePrompt,
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  onConfirm,
  onCancel,
  destructive = true,
  submitting = false,
}) => {
  const [value, setValue] = useState('');
  const containerRef = useRef(null);
  const inputRef = useRef(null);
  const previouslyFocusedRef = useRef(null);
  const reducedMotion = useReducedMotion();
  const headingId = useId();
  const descriptionId = useId();

  const expected = useMemo(() => (typeof phrase === 'string' ? phrase : ''), [phrase]);
  const isMatch = expected.length > 0 && value === expected;

  useEffect(() => {
    if (!open) return undefined;

    previouslyFocusedRef.current = typeof document !== 'undefined' ? document.activeElement : null;
    setValue('');

    const focusTimer = window.setTimeout(() => {
      inputRef.current?.focus();
      inputRef.current?.select?.();
    }, 0);

    return () => {
      window.clearTimeout(focusTimer);
      const previous = previouslyFocusedRef.current;
      if (previous && typeof previous.focus === 'function') {
        try {
          previous.focus();
        } catch (error) {
          /* noop */
        }
      }
    };
  }, [open]);

  const handleKeyDown = useCallback(
    (event) => {
      if (!open) return;

      if (event.key === 'Escape') {
        event.stopPropagation();
        event.preventDefault();
        if (submitting) return;
        if (typeof onCancel === 'function') onCancel();
        return;
      }

      if (event.key !== 'Tab') return;

      const container = containerRef.current;
      if (!container) return;

      const focusable = Array.from(container.querySelectorAll(FOCUSABLE_SELECTOR)).filter(
        (node) => !node.hasAttribute('disabled') && node.getAttribute('aria-hidden') !== 'true'
      );
      if (focusable.length === 0) {
        event.preventDefault();
        return;
      }

      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const active = document.activeElement;

      if (event.shiftKey) {
        if (active === first || !container.contains(active)) {
          event.preventDefault();
          last.focus();
        }
      } else if (active === last) {
        event.preventDefault();
        first.focus();
      }
    },
    [open, onCancel, submitting]
  );

  const handleConfirm = useCallback(() => {
    if (!isMatch || submitting) return;
    if (typeof onConfirm === 'function') onConfirm(value);
  }, [isMatch, onConfirm, submitting, value]);

  const handleSubmit = useCallback(
    (event) => {
      event.preventDefault();
      handleConfirm();
    },
    [handleConfirm]
  );

  const handleBackdropClick = useCallback(() => {
    if (submitting) return;
    if (typeof onCancel === 'function') onCancel();
  }, [onCancel, submitting]);

  if (typeof document === 'undefined') return null;

  const transition = reducedMotion ? { duration: 0.12 } : { duration: 0.18, ease: EASE_OUT };

  return createPortal(
    <AnimatePresence>
      {open ? (
        <motion.div
          key="confirm-phrase-modal"
          className="fixed inset-0 z-[100] flex items-center justify-center px-4"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={transition}
          onKeyDown={handleKeyDown}
        >
          <div
            aria-hidden="true"
            onClick={handleBackdropClick}
            className="absolute inset-0"
            style={{ background: 'rgba(47, 42, 36, 0.55)' }}
          />
          <motion.div
            ref={containerRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby={headingId}
            aria-describedby={description ? descriptionId : undefined}
            className={clsx(
              'glass-card relative z-10 w-full max-w-md rounded-2xl p-6 shadow-xl'
            )}
            initial={reducedMotion ? false : { opacity: 0, scale: 0.96, y: 12 }}
            animate={reducedMotion ? { opacity: 1 } : { opacity: 1, scale: 1, y: 0 }}
            exit={reducedMotion ? { opacity: 0 } : { opacity: 0, scale: 0.96, y: 12 }}
            transition={transition}
          >
            <h2
              id={headingId}
              className="font-display text-xl"
              style={{ color: 'var(--palace-ink)' }}
            >
              {title}
            </h2>
            {description ? (
              <p
                id={descriptionId}
                className="mt-2 text-sm leading-relaxed"
                style={{ color: 'var(--palace-muted)' }}
              >
                {description}
              </p>
            ) : null}

            <form onSubmit={handleSubmit} className="mt-4 flex flex-col gap-3">
              <label
                htmlFor={`${headingId}-input`}
                className="text-xs font-medium"
                style={{ color: 'var(--palace-muted)' }}
              >
                {phrasePrompt ? <span>{phrasePrompt} </span> : null}
                <code
                  className="rounded-md px-1.5 py-0.5 font-mono text-[12px]"
                  style={{
                    background: 'rgba(212, 175, 55, 0.12)',
                    color: 'var(--palace-accent-2)',
                  }}
                >
                  {expected}
                </code>
              </label>
              <input
                ref={inputRef}
                id={`${headingId}-input`}
                type="text"
                value={value}
                onChange={(event) => setValue(event.target.value)}
                className="palace-input font-mono text-sm"
                autoComplete="off"
                autoCorrect="off"
                autoCapitalize="off"
                spellCheck={false}
              />

              <div className="mt-2 flex items-center justify-end gap-2">
                <button
                  type="button"
                  className="palace-btn-ghost"
                  onClick={onCancel}
                  disabled={submitting}
                >
                  {cancelLabel}
                </button>
                <button
                  type="submit"
                  disabled={!isMatch || submitting}
                  className={clsx(
                    'palace-btn-primary',
                    (!isMatch || submitting) && 'cursor-not-allowed opacity-50'
                  )}
                  style={
                    destructive && isMatch
                      ? {
                          background: 'linear-gradient(135deg, #a3553e 0%, #8b4533 100%)',
                          boxShadow: '0 4px 12px rgba(163, 85, 62, 0.3)',
                        }
                      : undefined
                  }
                >
                  {confirmLabel}
                </button>
              </div>
            </form>
          </motion.div>
        </motion.div>
      ) : null}
    </AnimatePresence>,
    document.body
  );
};

export default ConfirmPhraseModal;
