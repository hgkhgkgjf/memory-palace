import React, { useMemo } from 'react';

const BUCKET_COUNT = 12;
const BUCKET_WIDTH = 1 / BUCKET_COUNT; // ~0.0833
const SVG_WIDTH = 320;
const SVG_HEIGHT = 96;
const PADDING_X = 6;
const PADDING_TOP = 8;
const PADDING_BOTTOM = 14;
const RUST_THRESHOLD_COLOR = '#a3553e';

/**
 * @param {number[]} scores
 * @returns {{ buckets: number[], total: number, max: number }}
 */
const buildBuckets = (scores) => {
  const buckets = new Array(BUCKET_COUNT).fill(0);
  let total = 0;
  for (const raw of scores) {
    const v = Number(raw);
    if (!Number.isFinite(v)) continue;
    const clamped = Math.min(0.9999999, Math.max(0, v));
    const idx = Math.min(BUCKET_COUNT - 1, Math.floor(clamped / BUCKET_WIDTH));
    buckets[idx] += 1;
    total += 1;
  }
  const max = buckets.reduce((acc, n) => (n > acc ? n : acc), 0);
  return { buckets, total, max };
};

const formatBucketLabel = (idx) => {
  const lo = idx * BUCKET_WIDTH;
  const hi = (idx + 1) * BUCKET_WIDTH;
  return `${lo.toFixed(2)}–${hi.toFixed(2)}`;
};

/**
 * Histogram of projected_score across `candidates`, with a vertical dashed
 * threshold marker. Pure SVG, deterministic, accessible via aria-label.
 *
 * @param {{
 *   candidates: import('./useForgetting').ForgettingCandidate[],
 *   threshold: number,
 *   t: (key: string, options?: object) => string,
 * }} props
 */
const ForgettingDistribution = ({ candidates, threshold, t }) => {
  const scores = useMemo(
    () =>
      (Array.isArray(candidates) ? candidates : [])
        .map((c) => Number(c?.projected_score))
        .filter((n) => Number.isFinite(n)),
    [candidates]
  );

  const { buckets, total, max } = useMemo(() => buildBuckets(scores), [scores]);

  if (!Array.isArray(candidates) || candidates.length === 0) return null;

  const innerWidth = SVG_WIDTH - PADDING_X * 2;
  const innerHeight = SVG_HEIGHT - PADDING_TOP - PADDING_BOTTOM;
  const barSlot = innerWidth / BUCKET_COUNT;
  const barWidth = Math.max(2, barSlot - 2);
  const denom = max > 0 ? max : 1;

  const safeThreshold = Number.isFinite(Number(threshold))
    ? Math.min(1, Math.max(0, Number(threshold)))
    : 0;
  const thresholdX = PADDING_X + safeThreshold * innerWidth;
  const thresholdBucket = Math.min(
    BUCKET_COUNT - 1,
    Math.floor(safeThreshold / BUCKET_WIDTH)
  );
  const belowCount = buckets.slice(0, thresholdBucket).reduce((a, b) => a + b, 0);
  const aboveCount = buckets.slice(thresholdBucket).reduce((a, b) => a + b, 0);

  const ariaLabel = t('maintenance.forgetting.distribution.title');

  return (
    <div className="flex flex-col gap-2" data-testid="forgetting-distribution">
      <div className="flex items-center justify-between text-[11px]">
        <span
          className="font-semibold uppercase tracking-[0.14em]"
          style={{ color: 'var(--palace-muted)' }}
        >
          {t('maintenance.forgetting.distribution.title')}
        </span>
        <span style={{ color: 'var(--palace-muted)' }}>
          {t('maintenance.forgetting.outOfTotal', { count: total })}
        </span>
      </div>
      <svg
        role="img"
        aria-label={ariaLabel}
        viewBox={`0 0 ${SVG_WIDTH} ${SVG_HEIGHT}`}
        className="block w-full"
        preserveAspectRatio="none"
        style={{ overflow: 'visible' }}
      >
        {/* Baseline */}
        <line
          x1={PADDING_X}
          x2={SVG_WIDTH - PADDING_X}
          y1={SVG_HEIGHT - PADDING_BOTTOM}
          y2={SVG_HEIGHT - PADDING_BOTTOM}
          stroke="var(--palace-line)"
          strokeWidth={1}
          vectorEffect="non-scaling-stroke"
          aria-hidden="true"
        />

        {/* Bars */}
        <g aria-hidden="true">
          {buckets.map((count, idx) => {
            const ratio = count / denom;
            const height = ratio * innerHeight;
            const x = PADDING_X + idx * barSlot + (barSlot - barWidth) / 2;
            const y = SVG_HEIGHT - PADDING_BOTTOM - height;
            return (
              <rect
                key={`bucket-${idx}`}
                x={x.toFixed(2)}
                y={y.toFixed(2)}
                width={barWidth.toFixed(2)}
                height={Math.max(0, height).toFixed(2)}
                rx={1.5}
                fill="var(--palace-accent)"
                fillOpacity={0.3}
                stroke="var(--palace-accent)"
                strokeOpacity={0.45}
                strokeWidth={0.75}
                vectorEffect="non-scaling-stroke"
              >
                <title>{`${formatBucketLabel(idx)}: ${count}`}</title>
              </rect>
            );
          })}
        </g>

        {/* Threshold marker */}
        <line
          x1={thresholdX.toFixed(2)}
          x2={thresholdX.toFixed(2)}
          y1={PADDING_TOP - 2}
          y2={SVG_HEIGHT - PADDING_BOTTOM + 2}
          stroke={RUST_THRESHOLD_COLOR}
          strokeWidth={1.25}
          strokeDasharray="4 3"
          vectorEffect="non-scaling-stroke"
          aria-hidden="true"
        />

        {/* X-axis end labels (0.0 and 1.0) */}
        <text
          x={PADDING_X}
          y={SVG_HEIGHT - 2}
          fontSize="9"
          fill="var(--palace-muted)"
          aria-hidden="true"
        >
          0.0
        </text>
        <text
          x={SVG_WIDTH - PADDING_X}
          y={SVG_HEIGHT - 2}
          fontSize="9"
          fill="var(--palace-muted)"
          textAnchor="end"
          aria-hidden="true"
        >
          1.0
        </text>
      </svg>

      <div
        className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px]"
        style={{ color: 'var(--palace-muted)' }}
      >
        <span className="inline-flex items-center gap-1.5">
          <span
            aria-hidden="true"
            className="inline-block h-2.5 w-3 rounded-sm"
            style={{ background: 'var(--palace-accent)', opacity: 0.3 }}
          />
          {t('maintenance.forgetting.distribution.title')}
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span
            aria-hidden="true"
            className="inline-block h-2.5 w-3"
            style={{
              borderLeft: `2px dashed ${RUST_THRESHOLD_COLOR}`,
            }}
          />
          {t('maintenance.forgetting.distribution.threshold')}: {safeThreshold.toFixed(2)}
        </span>
        <span>
          &lt; {safeThreshold.toFixed(2)}: <strong>{belowCount}</strong>
        </span>
        <span>
          &ge; {safeThreshold.toFixed(2)}: <strong>{aboveCount}</strong>
        </span>
      </div>
    </div>
  );
};

export default ForgettingDistribution;
