// Adapted from Tremor Raw Card (Apache-2.0): https://github.com/tremorlabs/tremor
import React from 'react';
import { cx } from '../../lib/utils';

export type CardProps = React.ComponentPropsWithoutRef<'div'>;

export const Card = React.forwardRef<HTMLDivElement, CardProps>(
  ({ className, ...props }, ref) => (
    <div
      ref={ref}
      className={cx(
        'relative w-full rounded-lg border border-gray-200 bg-white p-6 text-left shadow-sm',
        className,
      )}
      {...props}
    />
  ),
);

Card.displayName = 'Card';
