// Adapted from Tremor Raw Badge (Apache-2.0): https://github.com/tremorlabs/tremor
import React from 'react';
import { cx } from '../../lib/utils';

export type BadgeVariant = 'default' | 'neutral' | 'success' | 'error' | 'warning';
export interface BadgeProps extends React.ComponentPropsWithoutRef<'span'> {
  variant?: BadgeVariant;
}

const variants: Record<BadgeVariant, string> = {
  default: 'bg-lime-50 text-lime-900 ring-lime-700/20',
  neutral: 'bg-gray-50 text-gray-800 ring-gray-500/20',
  success: 'bg-emerald-50 text-emerald-900 ring-emerald-600/20',
  error: 'bg-red-50 text-red-900 ring-red-600/20',
  warning: 'bg-amber-50 text-amber-900 ring-amber-600/20',
};

export const Badge = React.forwardRef<HTMLSpanElement, BadgeProps>(
  ({ className, variant = 'default', ...props }, ref) => (
    <span
      ref={ref}
      className={cx(
        'inline-flex items-center gap-x-1 whitespace-nowrap rounded-md px-2 py-1 text-xs font-medium ring-1 ring-inset',
        variants[variant],
        className,
      )}
      {...props}
    />
  ),
);

Badge.displayName = 'Badge';
