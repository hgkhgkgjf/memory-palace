import React, { useMemo } from 'react';

const RUST_THRESHOLD_COLOR = '#a3553e';
const GRID_COLOR = 'var(--palace-line)';

/**
 * @typedef {{
 *   values: number[],
 *   width?: number,
 *   height?: number,
 *   color?: string,
 *   thresholdValue?: number,
 *   label: string,
 *   className?: string,
 * }} DecayCurveProps
 */

/**
 * Smooth decay curve. Pure SVG, deterministic rendering (no animation).
 *
 * @param {DecayCurveProps} props
 */
const DecayCurve = ({
  values,
  width = 200,
  height = 48,
  color = '#d4af37',
  thresholdValue,
  label,
  className,
}) => {
  const safeWidth = Math.max(1, Number(width) || 200);
  const safeHeight = Math.max(1, Number(height) || 48);
  const padding = 4;

  const data = useMemo(() => {
    const numeric = Array.isArray(values)
      ? values.map((v) => Number(v)).filter((v) => Number.isFinite(v))
      : [];

    const min = numeric.length > 0 ? Math.min(0, ...numeric) : 0;
    const max = numeric.length > 0 ? Math.max(1, ...numeric) : 1;
    const range = max - min || 1;
    const drawWidth = Math.max(1, safeWidth - padding * 2);
    const drawHeight = Math.max(1, safeHeight - padding * 2);

    const projectY = (value) =>
      padding + drawHeight - ((value - min) / range) * drawHeight;

    let pathData = '';
    let firstPoint = null;
    let lastPoint = null;

    if (numeric.length >= 2) {
      const step = drawWidth / (numeric.length - 1);
      const coords = numeric.map((v, idx) => ({
        x: padding + idx * step,
        y: projectY(v),
      }));
      firstPoint = coords[0];
      lastPoint = coords[coords.length - 1];

      // Smooth Catmull-Rom -> cubic Bezier conversion. Tension 0.5 gives the
      // gentle, paper-like easing the design calls for.
      const segments = [`M ${coords[0].x.toFixed(2)} ${coords[0].y.toFixed(2)}`];
      for (let i = 0; i < coords.length - 1; i += 1) {
        const p0 = coords[i - 1] || coords[i];
        const p1 = coords[i];
        const p2 = coords[i + 1];
        const p3 = coords[i + 2] || coords[i + 1];

        const cp1x = p1.x + (p2.x - p0.x) / 6;
        const cp1y = p1.y + (p2.y - p0.y) / 6;
        const cp2x = p2.x - (p3.x - p1.x) / 6;
        const cp2y = p2.y - (p3.y - p1.y) / 6;

        segments.push(
          `C ${cp1x.toFixed(2)} ${cp1y.toFixed(2)}, ${cp2x.toFixed(2)} ${cp2y.toFixed(2)}, ${p2.x.toFixed(2)} ${p2.y.toFixed(2)}`
        );
      }
      pathData = segments.join(' ');
    } else if (numeric.length === 1) {
      const midX = safeWidth / 2;
      const y = projectY(numeric[0]);
      firstPoint = { x: midX, y };
      lastPoint = { x: midX, y };
      pathData = `M ${padding.toFixed(2)} ${y.toFixed(2)} L ${(safeWidth - padding).toFixed(2)} ${y.toFixed(2)}`;
    }

    const thresholdY =
      Number.isFinite(Number(thresholdValue)) && numeric.length > 0
        ? projectY(Number(thresholdValue))
        : null;

    return { pathData, firstPoint, lastPoint, thresholdY, hasData: numeric.length >= 1 };
  }, [values, safeWidth, safeHeight, thresholdValue]);

  const gridLines = useMemo(() => {
    const drawHeight = Math.max(1, safeHeight - padding * 2);
    return [0.25, 0.5, 0.75].map((ratio) => ({
      key: `grid-${ratio}`,
      y: padding + drawHeight * ratio,
    }));
  }, [safeHeight]);

  return (
    <svg
      role="img"
      aria-label={label}
      viewBox={`0 0 ${safeWidth} ${safeHeight}`}
      width={safeWidth}
      height={safeHeight}
      preserveAspectRatio="none"
      className={className}
      style={{ display: 'block', overflow: 'visible' }}
    >
      {/* Horizontal grid lines: 25%, 50%, 75% */}
      <g aria-hidden="true">
        {gridLines.map((line) => (
          <line
            key={line.key}
            x1={padding}
            x2={safeWidth - padding}
            y1={line.y}
            y2={line.y}
            stroke={GRID_COLOR}
            strokeWidth={1}
            strokeDasharray="2 3"
            vectorEffect="non-scaling-stroke"
          />
        ))}
      </g>

      {/* Threshold line */}
      {data.thresholdY !== null && (
        <line
          x1={padding}
          x2={safeWidth - padding}
          y1={data.thresholdY}
          y2={data.thresholdY}
          stroke={RUST_THRESHOLD_COLOR}
          strokeWidth={1.25}
          strokeDasharray="4 3"
          vectorEffect="non-scaling-stroke"
          aria-hidden="true"
        />
      )}

      {/* Main decay curve */}
      {data.hasData && (
        <path
          d={data.pathData}
          fill="none"
          stroke={color}
          strokeWidth={1.5}
          strokeLinecap="round"
          strokeLinejoin="round"
          vectorEffect="non-scaling-stroke"
        />
      )}

      {/* Start point (outlined circle) */}
      {data.firstPoint && (
        <circle
          cx={data.firstPoint.x}
          cy={data.firstPoint.y}
          r={2.5}
          fill="#fff"
          stroke={color}
          strokeWidth={1.25}
          vectorEffect="non-scaling-stroke"
          aria-hidden="true"
        />
      )}

      {/* End point (filled circle) */}
      {data.lastPoint && (
        <circle
          cx={data.lastPoint.x}
          cy={data.lastPoint.y}
          r={2.5}
          fill={color}
          aria-hidden="true"
        />
      )}
    </svg>
  );
};

export default DecayCurve;
