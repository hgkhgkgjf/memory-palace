import React from 'react';
import clsx from 'clsx';
import { AlertTriangle, RefreshCw } from 'lucide-react';

/**
 * @param {{
 *   message: React.ReactNode,
 *   onRetry?: () => void | Promise<void>,
 *   retryLabel?: string,
 *   className?: string,
 * }} props
 */
const ErrorBanner = ({ message, onRetry, retryLabel = 'Retry', className }) => {
  return (
    <div
      role="alert"
      className={clsx(
        'flex items-start gap-3 rounded-xl border px-4 py-3 text-sm',
        className
      )}
      style={{
        background: 'rgba(163, 85, 62, 0.08)',
        borderColor: 'rgba(163, 85, 62, 0.25)',
        color: 'var(--palace-ink)',
      }}
    >
      <AlertTriangle
        size={18}
        strokeWidth={2}
        style={{ color: '#a3553e' }}
        className="mt-0.5 shrink-0"
        aria-hidden="true"
      />
      <div className="flex-1 leading-relaxed">{message}</div>
      {onRetry ? (
        <button
          type="button"
          onClick={onRetry}
          className="inline-flex shrink-0 items-center gap-1 rounded-lg border px-2 py-1 text-xs font-medium transition"
          style={{
            borderColor: 'rgba(163, 85, 62, 0.3)',
            color: '#a3553e',
            background: 'rgba(255, 255, 255, 0.4)',
          }}
        >
          <RefreshCw size={12} strokeWidth={2} aria-hidden="true" />
          {retryLabel}
        </button>
      ) : null}
    </div>
  );
};

export default ErrorBanner;
