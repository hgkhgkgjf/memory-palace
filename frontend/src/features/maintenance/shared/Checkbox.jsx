import React, { useEffect, useId, useRef } from 'react';
import clsx from 'clsx';

/**
 * @param {{
 *   checked?: boolean,
 *   indeterminate?: boolean,
 *   onChange?: (checked: boolean, event: React.ChangeEvent<HTMLInputElement>) => void,
 *   label?: string,
 *   id?: string,
 *   disabled?: boolean,
 *   className?: string,
 * }} props
 */
const Checkbox = ({
  checked = false,
  indeterminate = false,
  onChange,
  label,
  id,
  disabled = false,
  className,
}) => {
  const inputRef = useRef(null);
  const autoId = useId();
  const inputId = id || `checkbox-${autoId}`;

  useEffect(() => {
    if (inputRef.current) {
      inputRef.current.indeterminate = Boolean(indeterminate) && !checked;
    }
  }, [indeterminate, checked]);

  return (
    <label
      htmlFor={inputId}
      className={clsx(
        'inline-flex items-center gap-2',
        disabled ? 'cursor-not-allowed opacity-50' : 'cursor-pointer',
        className
      )}
    >
      <input
        ref={inputRef}
        id={inputId}
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(event) => {
          if (typeof onChange === 'function') onChange(event.target.checked, event);
        }}
        aria-label={label || undefined}
        className="h-4 w-4 rounded border focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-1"
        style={{
          accentColor: 'var(--palace-accent)',
          borderColor: 'var(--palace-line)',
          // @ts-ignore CSS variable used as Tailwind ring color fallback
          '--tw-ring-color': 'var(--palace-accent)',
        }}
      />
      {label ? (
        <span className="sr-only">{label}</span>
      ) : null}
    </label>
  );
};

export default Checkbox;
