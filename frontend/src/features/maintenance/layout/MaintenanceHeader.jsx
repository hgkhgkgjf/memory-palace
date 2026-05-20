import React from 'react';
import { useTranslation } from 'react-i18next';
import { Feather, RefreshCw } from 'lucide-react';
import clsx from 'clsx';

export default function MaintenanceHeader({ onRefresh, refreshing }) {
  const { t } = useTranslation();

  return (
    <header className="flex flex-col gap-3 py-6 md:flex-row md:items-center md:justify-between">
      <div className="flex items-center gap-3">
        <span
          className="flex h-11 w-11 flex-shrink-0 items-center justify-center rounded-xl border"
          style={{
            borderColor: 'var(--palace-line)',
            background: 'rgba(255, 255, 255, 0.55)',
          }}
        >
          <Feather
            size={20}
            style={{ color: 'var(--palace-accent)' }}
            aria-hidden="true"
          />
        </span>
        <div className="min-w-0">
          <h1
            className="font-display text-2xl leading-tight"
            style={{ color: 'var(--palace-ink)' }}
          >
            {t('maintenance.title')}
          </h1>
          <p
            className="text-sm leading-snug"
            style={{ color: 'var(--palace-muted)' }}
          >
            {t('maintenance.subtitle')}
          </p>
        </div>
      </div>

      <div className="flex items-center md:flex-shrink-0">
        <button
          type="button"
          onClick={onRefresh}
          disabled={refreshing}
          className="palace-btn-ghost disabled:cursor-not-allowed disabled:opacity-60"
          aria-label={t('maintenance.refresh')}
          title={t('maintenance.refresh')}
        >
          <RefreshCw
            size={16}
            className={clsx(refreshing && 'animate-spin')}
            aria-hidden="true"
          />
          <span>{t('maintenance.refresh')}</span>
        </button>
      </div>
    </header>
  );
}
