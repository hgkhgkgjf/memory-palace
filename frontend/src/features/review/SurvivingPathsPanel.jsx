import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  AlertTriangle,
  Check,
  Copy,
  Link2,
  Unlink2,
} from 'lucide-react';
import clsx from 'clsx';

export function parseUri(raw) {
  if (typeof raw !== 'string' || !raw.trim()) {
    return { protocol: '', segments: [], resource: String(raw ?? '') };
  }
  const match = raw.match(/^([a-z][a-z0-9+\-.]*:\/\/)(.*)$/i);
  const protocol = match ? match[1] : '';
  const body = match ? match[2] : raw;
  const parts = body.split('/').filter(Boolean);
  if (parts.length === 0) {
    return { protocol, segments: [], resource: body };
  }
  const resource = parts.pop();
  return { protocol, segments: parts, resource };
}

async function copyTextToClipboard(text) {
  if (typeof navigator !== 'undefined' && navigator.clipboard && navigator.clipboard.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      // fall through to legacy path
    }
  }
  if (typeof document === 'undefined') return false;
  // Wrap the entire fallback (createElement + style + appendChild + execCommand)
  // in a single try so that any extreme DOM exception still resolves to `false`
  // instead of throwing, preserving the boolean contract.
  let ta;
  try {
    ta = document.createElement('textarea');
    ta.value = text;
    ta.setAttribute('readonly', '');
    ta.style.position = 'fixed';
    ta.style.top = '0';
    ta.style.left = '0';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand('copy');
    return Boolean(ok);
  } catch {
    return false;
  } finally {
    if (ta && ta.parentNode) ta.parentNode.removeChild(ta);
  }
}

function OrphanWarning({ t }) {
  return (
    <aside
      role="alert"
      aria-labelledby="surviving-paths-orphan-heading"
      className={clsx(
        'relative mb-8 overflow-hidden rounded-xl p-5',
        'bg-gradient-to-br from-rose-950/40 to-stone-950/40',
        'border border-rose-800/50 ring-1 ring-rose-900/40',
        'backdrop-blur-sm',
        'shadow-[0_0_0_1px_rgba(190,18,60,0.08),0_8px_24px_-8px_rgba(190,18,60,0.25)]',
      )}
    >
      <div
        aria-hidden="true"
        className="absolute inset-x-0 top-0 h-[3px] rounded-t-xl"
        style={{
          backgroundImage:
            'repeating-linear-gradient(45deg,rgba(244,63,94,0.55) 0 6px,transparent 6px 12px)',
        }}
      />

      <header className="mb-3 flex items-start gap-3">
        <div className="shrink-0 rounded-lg border border-rose-800/60 bg-rose-950/60 p-2">
          <Unlink2 size={32} className="text-rose-300" aria-hidden="true" />
        </div>
        <div className="min-w-0 flex-1">
          <p className="mb-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-rose-400/80">
            {t('review.orphan.kicker')}
          </p>
          <h3
            id="surviving-paths-orphan-heading"
            className="text-sm font-semibold tracking-wide text-rose-100"
          >
            {t('review.orphan.title')}
          </h3>
        </div>
      </header>

      <p className="text-xs leading-relaxed text-rose-100/85">
        {t('review.orphan.body')}
      </p>

      <div className="mt-3 flex items-center gap-2 text-[11px] font-medium text-rose-300/90">
        <AlertTriangle size={12} aria-hidden="true" className="text-rose-400" />
        <span>{t('review.orphan.irreversible')}</span>
      </div>
    </aside>
  );
}

function PathBreadcrumb({ uri, copied, copyFailed, onCopy, t }) {
  const { protocol, segments, resource } = parseUri(uri);
  const displayProtocol = protocol || '';
  const displayResource = resource || uri;

  return (
    <div
      className={clsx(
        'group relative flex items-center gap-2 rounded-lg',
        'border border-stone-800/40 bg-stone-950/40',
        'px-3.5 py-2.5',
        'hover:border-amber-800/40 hover:bg-stone-950/60',
        'focus-within:border-amber-700/50 focus-within:bg-stone-950/70',
        'transition-[border-color,background-color] duration-200',
      )}
    >
      <div
        className="flex min-w-0 flex-1 items-baseline truncate font-mono text-xs"
        title={uri}
      >
        {displayProtocol ? (
          <span className="shrink-0 text-stone-500" aria-label={t('review.paths.protocolLabel')}>
            {displayProtocol}
          </span>
        ) : null}
        {segments.map((seg, i) => (
          <React.Fragment key={`${i}-${seg}`}>
            <span className="shrink-0 truncate text-stone-500">{seg}</span>
            <span aria-hidden="true" className="shrink-0 text-stone-500">/</span>
          </React.Fragment>
        ))}
        <span className="truncate font-semibold text-stone-100">
          {displayResource}
        </span>
      </div>

      <button
        type="button"
        onClick={onCopy}
        aria-label={t('review.paths.copyUri', { uri })}
        className={clsx(
          'ml-auto shrink-0 rounded p-1 text-stone-500',
          // Default opacity-60 keeps the button visible on touch devices;
          // hover-capable devices upgrade to full opacity on hover/focus.
          'opacity-60 group-hover:opacity-100 group-focus-within:opacity-100',
          'focus:opacity-100 focus:outline-none focus:ring-1 focus:ring-amber-700/50',
          'hover:bg-stone-800/60 hover:text-amber-300',
          'transition-opacity duration-150',
        )}
      >
        {copied ? (
          <Check size={12} className="text-emerald-400" aria-hidden="true" />
        ) : (
          <Copy size={12} aria-hidden="true" />
        )}
      </button>

      {copied ? (
        <span
          role="status"
          className={clsx(
            'pointer-events-none absolute -top-7 right-0',
            'rounded border border-emerald-900/40 bg-stone-950/90 px-2 py-0.5',
            'font-mono text-[10px] uppercase tracking-wider text-emerald-400',
          )}
        >
          {t('review.paths.copied')}
        </span>
      ) : null}

      {copyFailed ? (
        <span
          role="status"
          className={clsx(
            'pointer-events-none absolute -top-7 right-0',
            'rounded border border-rose-900/40 bg-stone-950/90 px-2 py-0.5',
            'font-mono text-[10px] uppercase tracking-wider text-rose-400',
          )}
        >
          {t('review.paths.copyFailed')}
        </span>
      ) : null}
    </div>
  );
}

function SurvivingPathsPanel({ survivingPaths }) {
  const { t } = useTranslation();
  const [copiedIndex, setCopiedIndex] = useState(null);
  const [failedIndex, setFailedIndex] = useState(null);
  const copyTimerRef = useRef(null);
  const failTimerRef = useRef(null);
  const mountedRef = useRef(true);

  const handleCopy = useCallback(async (uri, index) => {
    const ok = await copyTextToClipboard(uri);
    // Guard against state updates if the component unmounted while we were
    // awaiting the async clipboard call.
    if (!mountedRef.current) return;
    if (ok) {
      setFailedIndex(null);
      setCopiedIndex(index);
      if (copyTimerRef.current) window.clearTimeout(copyTimerRef.current);
      copyTimerRef.current = window.setTimeout(() => {
        setCopiedIndex(null);
        copyTimerRef.current = null;
      }, 1500);
    } else {
      setCopiedIndex(null);
      setFailedIndex(index);
      if (failTimerRef.current) window.clearTimeout(failTimerRef.current);
      failTimerRef.current = window.setTimeout(() => {
        setFailedIndex(null);
        failTimerRef.current = null;
      }, 1500);
    }
  }, []);

  // Clear any pending timers on unmount and flip the mounted flag so any
  // in-flight async clipboard calls skip their setState side-effects.
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      if (copyTimerRef.current) window.clearTimeout(copyTimerRef.current);
      if (failTimerRef.current) window.clearTimeout(failTimerRef.current);
    };
  }, []);

  // When the path list changes (e.g. user switches snapshots), reset transient
  // feedback so a previous "copied" tag does not bleed across snapshots.
  useEffect(() => {
    setCopiedIndex(null);
    setFailedIndex(null);
    if (copyTimerRef.current) {
      window.clearTimeout(copyTimerRef.current);
      copyTimerRef.current = null;
    }
    if (failTimerRef.current) {
      window.clearTimeout(failTimerRef.current);
      failTimerRef.current = null;
    }
  }, [survivingPaths]);

  if (!Array.isArray(survivingPaths)) return null;

  if (survivingPaths.length === 0) {
    return <OrphanWarning t={t} />;
  }

  const count = survivingPaths.length;
  const summary = t('review.paths.summary', { count });

  return (
    <section
      role="region"
      aria-labelledby="surviving-paths-heading"
      className="mb-8 rounded-xl border border-stone-800/60 bg-stone-900/50 p-4 backdrop-blur-sm"
    >
      <header className="mb-3 flex items-center gap-2">
        <Link2 size={12} className="text-stone-500" aria-hidden="true" />
        <h3
          id="surviving-paths-heading"
          className="text-xs font-bold uppercase tracking-widest text-stone-500"
        >
          {t('review.paths.sectionLabel')}
        </h3>
      </header>

      <p className="mb-3 text-xs text-stone-500">{summary}</p>

      <ul role="list" className="space-y-2">
        {survivingPaths.map((path, i) => (
          <li key={`${i}-${path}`}>
            <PathBreadcrumb
              uri={path}
              copied={copiedIndex === i}
              copyFailed={failedIndex === i}
              onCopy={() => handleCopy(path, i)}
              t={t}
            />
          </li>
        ))}
      </ul>
    </section>
  );
}

export default SurvivingPathsPanel;
