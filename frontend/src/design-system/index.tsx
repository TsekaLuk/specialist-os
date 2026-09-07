import type { ComponentProps } from 'react';
import { Check, CircleAlert, CircleDashed, Search } from 'lucide-react';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';

export { Badge, Button, Input };

export function StatusBadge({ status }: { status: string }) {
  const success = status === 'ok';
  const failed = status === 'error';
  const Icon = success ? Check : failed ? CircleAlert : CircleDashed;
  return <Badge variant={success ? 'success' : failed ? 'destructive' : 'outline'} aria-label={`Run status: ${status}`}><Icon aria-hidden="true" /><span>{status}</span></Badge>;
}

export function SearchInput(props: ComponentProps<typeof Input>) {
  return <div className="ds-search"><Search aria-hidden="true" /><Input type="search" {...props} /></div>;
}

export function NavigationItem({ active, children, ...props }: ComponentProps<typeof Button> & { active: boolean }) {
  return <Button variant="ghost" className="ds-navigation-item" aria-current={active ? 'page' : undefined} {...props}>{children}</Button>;
}
