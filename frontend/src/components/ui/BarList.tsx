// Adapted from Tremor Raw BarList (Apache-2.0): https://github.com/tremorlabs/tremor
import React from 'react';
import { cx } from '../../lib/utils';

export interface BarListItem {
  key?: string;
  name: string;
  value: number;
}

export interface BarListProps extends React.HTMLAttributes<HTMLDivElement> {
  data: BarListItem[];
  valueFormatter?: (value: number) => string;
  sortOrder?: 'ascending' | 'descending' | 'none';
}

export const BarList = React.forwardRef<HTMLDivElement, BarListProps>(
  (
    {
      data,
      valueFormatter = (value) => value.toLocaleString('ru-RU'),
      sortOrder = 'descending',
      className,
      ...props
    },
    ref,
  ) => {
    const items = React.useMemo(() => {
      if (sortOrder === 'none') return data;
      return [...data].sort((a, b) =>
        sortOrder === 'ascending' ? a.value - b.value : b.value - a.value,
      );
    }, [data, sortOrder]);
    const maxValue = Math.max(...items.map((item) => item.value), 0);

    return (
      <div ref={ref} className={cx('space-y-3', className)} {...props}>
        {items.map((item) => {
          const width = item.value <= 0 || maxValue === 0 ? 0 : Math.max((item.value / maxValue) * 100, 2);
          return (
            <div key={item.key ?? item.name} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 gap-y-1">
              <span className="truncate text-sm text-gray-800">{item.name}</span>
              <span className="text-sm font-medium tabular-nums text-gray-900">{valueFormatter(item.value)}</span>
              <div className="col-span-2 h-2 overflow-hidden rounded-full bg-gray-100" aria-hidden="true">
                <div className="h-full rounded-full bg-lime-600 transition-[width] duration-500" style={{ width: `${width}%` }} />
              </div>
            </div>
          );
        })}
        {items.length === 0 && <p className="text-sm text-gray-500">Нет данных для отображения</p>}
      </div>
    );
  },
);

BarList.displayName = 'BarList';
