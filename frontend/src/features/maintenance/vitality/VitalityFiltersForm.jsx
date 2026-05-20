import React, { useCallback, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { Filter, RotateCcw } from 'lucide-react';
import { DEFAULT_VITALITY_REVIEWER } from './useVitality';

const validateFilters = ({ threshold, inactiveDays, limit }) => {
  /** @type {Record<string, string>} */
  const errors = {};
  const thresholdRaw = String(threshold ?? '').trim();
  const inactiveDaysRaw = String(inactiveDays ?? '').trim();
  const limitRaw = String(limit ?? '').trim();

  if (!thresholdRaw) {
    errors.threshold = 'maintenance.errors.thresholdRequired';
  } else {
    const value = Number(thresholdRaw);
    if (!Number.isFinite(value) || value < 0) {
      errors.threshold = 'maintenance.errors.thresholdNonNegative';
    }
  }

  if (!inactiveDaysRaw) {
    errors.inactiveDays = 'maintenance.errors.inactiveDaysRequired';
  } else {
    const value = Number(inactiveDaysRaw);
    if (!Number.isFinite(value) || value < 0) {
      errors.inactiveDays = 'maintenance.errors.inactiveDaysNonNegative';
    }
  }

  if (!limitRaw) {
    errors.limit = 'maintenance.errors.limitRequired';
  } else {
    const value = Number(limitRaw);
    if (
      !Number.isFinite(value)
      || !Number.isInteger(value)
      || value < 1
      || value > 500
    ) {
      errors.limit = 'maintenance.errors.limitRange';
    }
  }

  return errors;
};

/**
 * @param {{
 *   filters: { threshold: number | string, inactiveDays: number | string, limit: number | string, domain: string, pathPrefix: string, reviewer: string },
 *   setters: {
 *     setThreshold: (value: number | string) => void,
 *     setInactiveDays: (value: number | string) => void,
 *     setLimit: (value: number | string) => void,
 *     setDomain: (value: string) => void,
 *     setPathPrefix: (value: string) => void,
 *     setReviewer: (value: string) => void,
 *   },
 *   onApply: () => void,
 *   onReset?: () => void,
 *   onInvalidate?: () => void,
 *   disabled?: boolean,
 * }} props
 */
const VitalityFiltersForm = ({
  filters,
  setters,
  onApply,
  onReset,
  onInvalidate,
  disabled = false,
}) => {
  const { t } = useTranslation();
  const [touched, setTouched] = useState({
    threshold: false,
    inactiveDays: false,
    limit: false,
  });

  const errors = useMemo(() => validateFilters(filters), [filters]);
  const hasErrors = Object.keys(errors).length > 0;

  const onChangeFactory = useCallback(
    /** @param {(value: string) => void} setter */
    /** @param {keyof typeof touched} [field] */
    (setter, field) => (event) => {
      setter(event.target.value);
      if (field) {
        setTouched((prev) => ({ ...prev, [field]: true }));
      }
      if (typeof onInvalidate === 'function') onInvalidate();
    },
    [onInvalidate]
  );

  const handleApply = useCallback(() => {
    setTouched({ threshold: true, inactiveDays: true, limit: true });
    if (hasErrors) return;
    onApply();
  }, [hasErrors, onApply]);

  const handleReset = useCallback(() => {
    setters.setThreshold(0.35);
    setters.setInactiveDays(14);
    setters.setLimit(80);
    setters.setDomain('');
    setters.setPathPrefix('');
    setters.setReviewer(DEFAULT_VITALITY_REVIEWER);
    setTouched({ threshold: false, inactiveDays: false, limit: false });
    if (typeof onReset === 'function') onReset();
    if (typeof onInvalidate === 'function') onInvalidate();
  }, [onInvalidate, onReset, setters]);

  const renderError = (field) => {
    if (!touched[field] || !errors[field]) return null;
    return (
      <p
        className="mt-1 text-[11px]"
        style={{ color: '#a3553e' }}
        id={`vitality-${field}-error`}
        role="alert"
      >
        {t(errors[field])}
      </p>
    );
  };

  const fieldLabel = (text) => (
    <span
      className="mb-1 inline-block text-[11px] font-medium uppercase tracking-wider"
      style={{ color: 'var(--palace-muted)' }}
    >
      {text}
    </span>
  );

  return (
    <form
      className="space-y-3"
      onSubmit={(event) => {
        event.preventDefault();
        handleApply();
      }}
    >
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <label className="flex flex-col" htmlFor="vitality-filter-threshold">
          {fieldLabel(t('maintenance.vitality.threshold'))}
          <input
            id="vitality-filter-threshold"
            type="number"
            min="0"
            step="0.01"
            value={filters.threshold}
            onChange={onChangeFactory(setters.setThreshold, 'threshold')}
            onBlur={() => setTouched((prev) => ({ ...prev, threshold: true }))}
            disabled={disabled}
            aria-invalid={Boolean(touched.threshold && errors.threshold)}
            aria-describedby={
              touched.threshold && errors.threshold
                ? 'vitality-threshold-error'
                : undefined
            }
            className={clsx(
              'palace-input',
              touched.threshold && errors.threshold && 'border-[color:#a3553e]'
            )}
          />
          {renderError('threshold')}
        </label>

        <label className="flex flex-col" htmlFor="vitality-filter-inactive-days">
          {fieldLabel(t('maintenance.vitality.inactiveDays'))}
          <input
            id="vitality-filter-inactive-days"
            type="number"
            min="0"
            step="1"
            value={filters.inactiveDays}
            onChange={onChangeFactory(setters.setInactiveDays, 'inactiveDays')}
            onBlur={() => setTouched((prev) => ({ ...prev, inactiveDays: true }))}
            disabled={disabled}
            aria-invalid={Boolean(touched.inactiveDays && errors.inactiveDays)}
            aria-describedby={
              touched.inactiveDays && errors.inactiveDays
                ? 'vitality-inactiveDays-error'
                : undefined
            }
            className={clsx(
              'palace-input',
              touched.inactiveDays && errors.inactiveDays && 'border-[color:#a3553e]'
            )}
          />
          {renderError('inactiveDays')}
        </label>

        <label className="flex flex-col" htmlFor="vitality-filter-limit">
          {fieldLabel(t('maintenance.vitality.limit'))}
          <input
            id="vitality-filter-limit"
            type="number"
            min="1"
            max="500"
            step="1"
            value={filters.limit}
            onChange={onChangeFactory(setters.setLimit, 'limit')}
            onBlur={() => setTouched((prev) => ({ ...prev, limit: true }))}
            disabled={disabled}
            aria-invalid={Boolean(touched.limit && errors.limit)}
            aria-describedby={
              touched.limit && errors.limit ? 'vitality-limit-error' : undefined
            }
            className={clsx(
              'palace-input',
              touched.limit && errors.limit && 'border-[color:#a3553e]'
            )}
          />
          {renderError('limit')}
        </label>

        <label className="flex flex-col" htmlFor="vitality-filter-domain">
          {fieldLabel(t('maintenance.vitality.domain'))}
          <input
            id="vitality-filter-domain"
            type="text"
            value={filters.domain}
            onChange={onChangeFactory(setters.setDomain)}
            disabled={disabled}
            placeholder={t('maintenance.vitality.optional')}
            aria-label={t('maintenance.vitality.domain')}
            className="palace-input"
          />
        </label>

        <label className="flex flex-col" htmlFor="vitality-filter-path-prefix">
          {fieldLabel(t('maintenance.vitality.pathPrefix'))}
          <input
            id="vitality-filter-path-prefix"
            type="text"
            value={filters.pathPrefix}
            onChange={onChangeFactory(setters.setPathPrefix)}
            disabled={disabled}
            placeholder={t('maintenance.vitality.optional')}
            aria-label={t('maintenance.vitality.pathPrefix')}
            className="palace-input"
          />
        </label>

        <label className="flex flex-col" htmlFor="vitality-filter-reviewer">
          {fieldLabel(t('maintenance.vitality.reviewer'))}
          <input
            id="vitality-filter-reviewer"
            type="text"
            value={filters.reviewer}
            onChange={onChangeFactory(setters.setReviewer)}
            disabled={disabled}
            placeholder={t('maintenance.vitality.reviewerPlaceholder', {
              value: DEFAULT_VITALITY_REVIEWER,
            })}
            className="palace-input"
          />
        </label>
      </div>

      <div className="flex flex-wrap items-center gap-2 pt-1">
        <button
          type="submit"
          className="palace-btn-primary"
          disabled={disabled || hasErrors}
          aria-disabled={disabled || hasErrors}
        >
          <Filter size={14} strokeWidth={2} aria-hidden="true" />
          {t('maintenance.vitality.applyFilters')}
        </button>
        <button
          type="button"
          className="palace-btn-ghost"
          onClick={handleReset}
          disabled={disabled}
        >
          <RotateCcw size={14} strokeWidth={2} aria-hidden="true" />
          {t('maintenance.vitality.resetFilters')}
        </button>
      </div>
    </form>
  );
};

export default VitalityFiltersForm;
