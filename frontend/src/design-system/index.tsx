import type { ComponentProps } from 'react';
import { Check, CircleAlert, CircleDashed, Search } from 'lucide-react';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';

export { Badge, Button, Input };

export function SampleMedia({ src, mime, name }: { src: string; mime?: string | null; name: string }) {
  return <figure className="sample-media">
    <figcaption>{name}</figcaption>
    {mime?.startsWith('audio/') ? <audio controls preload="metadata" aria-label={`Input audio: ${name}`} src={src} />
      : mime?.startsWith('video/') ? <video controls preload="metadata" aria-label={`Input video: ${name}`} src={src} />
      : mime?.startsWith('image/') ? <img src={src} alt={`Input sample: ${name}`} /> : null}
    <Button variant="outline" size="sm" asChild><a href={src} target="_blank" rel="noreferrer">Open sample</a></Button>
  </figure>;
}

export function Transcript({ text, segments }: { text?: string | null; segments?: { start?: number; end?: number; text?: string; speaker?: string }[] }) {
  const time = (value?: number) => typeof value === 'number' && Number.isFinite(value) ? `${value.toFixed(2)} s` : '';
  return <div className="transcript">
    {text && <p className="transcript-text">{text}</p>}
    {!!segments?.length && <div className="transcript-segments" role="region" aria-label="Time segments" tabIndex={0}><table><thead><tr><th>Start</th><th>End</th><th>Content</th></tr></thead><tbody>{segments.map((segment, i) => <tr key={i}><td>{time(segment.start)}</td><td>{time(segment.end)}</td><td>{segment.speaker && <strong>{segment.speaker} </strong>}{segment.text}</td></tr>)}</tbody></table></div>}
  </div>;
}

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
