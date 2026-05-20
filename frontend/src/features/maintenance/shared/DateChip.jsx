import React, { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { formatDateTime } from '../../../lib/format';

const MS = {
  minute: 60 * 1000,
  hour: 60 * 60 * 1000,
  day: 24 * 60 * 60 * 1000,
  week: 7 * 24 * 60 * 60 * 1000,
  month: 30 * 24 * 60 * 60 * 1000,
  year: 365 * 24 * 60 * 60 * 1000,
};

/**
 * @param {number} deltaMs
 * @returns {{ value: number, unit: Intl.RelativeTimeFormatUnit }}
 */
const getRelativeParts = (deltaMs) => {
  const abs = Math.abs(deltaMs);
  if (abs < MS.minute) return { value: Math.round(abs / 1000), unit: 'second' };
  if (abs < MS.hour) return { value: Math.round(abs / MS.minute), unit: 'minute' };
  if (abs < MS.day) return { value: Math.round(abs / MS.hour), unit: 'hour' };
  if (abs < MS.week) return { value: Math.round(abs / MS.day), unit: 'day' };
  if (abs < MS.month) return { value: Math.round(abs / MS.week), unit: 'week' };
  if (abs < MS.year) return { value: Math.round(abs / MS.month), unit: 'month' };
  return { value: Math.round(abs / MS.year), unit: 'year' };
};

/**
 * @param {Date} date
 * @param {string | undefined} lng
 */
const formatRelative = (date, lng) => {
  const delta = date.getTime() - Date.now();
  const { value, unit } = getRelativeParts(delta);
  try {
    const formatter = new Intl.RelativeTimeFormat(lng || undefined, { numeric: 'auto', style: 'short' });
    return formatter.format(delta >= 0 ? value : -value, unit);
  } catch (error) {
    return delta >= 0 ? `in ${value}${unit[0]}` : `${value}${unit[0]} ago`;
  }
};

/**
 * @param {{
 *   date?: string | number | Date | null,
 *   className?: string,
 *   fallback?: string,
 * }} props
 */
const DateChip = ({ date, className, fallback = '—' }) => {
  const { i18n } = useTranslation();
  const lng = i18n?.resolvedLanguage || i18n?.language;

  const { relative, absolute } = useMemo(() => {
    if (!date) return { relative: fallback, absolute: '' };
    const parsed = new Date(date);
    if (Number.isNaN(parsed.getTime())) return { relative: fallback, absolute: '' };
    return {
      relative: formatRelative(parsed, lng),
      absolute:
        formatDateTime(parsed, lng, {
          dateStyle: 'medium',
          timeStyle: 'short',
        }) || parsed.toISOString(),
    };
  }, [date, lng, fallback]);

  return (
    <span
      className={clsx('inline-block text-[11px]', className)}
      style={{ color: 'var(--palace-muted)' }}
      title={absolute || undefined}
    >
      {relative}
    </span>
  );
};

export default DateChip;
