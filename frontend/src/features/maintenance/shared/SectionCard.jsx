import React from 'react';
import clsx from 'clsx';

/**
 * @param {{
 *   children?: React.ReactNode,
 *   className?: string,
 *   as?: React.ElementType,
 *   [key: string]: unknown,
 * }} props
 */
const SectionCard = ({ children, className, as: Component = 'div', ...props }) => {
  return React.createElement(
    Component,
    {
      ...props,
      className: clsx('glass-card rounded-2xl p-5', className),
    },
    children
  );
};

export default SectionCard;
