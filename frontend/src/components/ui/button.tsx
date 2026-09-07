import type { ButtonHTMLAttributes, ReactNode } from 'react';
import { cn } from '../../lib/utils';

export function Button({ className, variant = 'secondary', children, ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'primary' | 'secondary'; children?: ReactNode }) {
  return <button className={cn('button', `button-${variant}`, className)} {...props}>{children}</button>;
}
