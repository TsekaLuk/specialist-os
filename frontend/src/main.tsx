import { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { ArrowLeft, Clipboard, SlidersHorizontal } from 'lucide-react';
import { Button, NavigationItem, SampleMedia, SearchInput, StatusBadge, Transcript } from './design-system';
import { serializeCommand } from './lib/command.mjs';
import './styles.css';

type Capability = { capability: string; family: string; status: string; preview?: string; preview_unavailable?: boolean; cached?: boolean; json: string; latency_ms?: number; command?: string[]; command_origin?: string; media?: { src: string; mime: string; sha256: string }[]; input_sample?: { name: string; text?: string; src?: string | null; mime?: string | null }; result_view?: { text?: string | null; segments?: { start?: number; end?: number; text?: string; speaker?: string }[] } };
type Manifest = { results: Capability[] };

export function App() {
  const [manifest, setManifest] = useState<Manifest>({ results: [] });
  const [selected, setSelected] = useState(() => location.hash.slice(1) || 'vision.detect');
  const [query, setQuery] = useState('');
  const [evidence, setEvidence] = useState<unknown>(null);
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState('');
  const [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    fetch('./demo.json', { signal: controller.signal }).then(r => { if (!r.ok) throw new Error('Cannot load capability manifest'); return r.json(); }).then(setManifest).catch(e => { if (e.name !== 'AbortError') setError(e.message); });
    const changed = () => setSelected(location.hash.slice(1) || 'vision.detect');
    addEventListener('hashchange', changed);
    return () => { controller.abort(); removeEventListener('hashchange', changed); };
  }, []);
  const item = manifest.results.find(result => result.capability === selected) ?? manifest.results[0];
  useEffect(() => {
    if (!item) return;
    const controller = new AbortController();
    setEvidence(null); setError('');
    fetch(`./assets/${item.json}`, { signal: controller.signal }).then(r => { if (!r.ok) throw new Error('Cannot load execution output'); return r.json(); }).then(setEvidence).catch(e => { if (e.name !== 'AbortError') setError(e.message); });
    return () => controller.abort();
  }, [item]);
  useEffect(() => { setCopied(false); setCopyError(''); }, [item]);
  useEffect(() => {
    if (!copied) return;
    const timer = setTimeout(() => setCopied(false), 1400);
    return () => clearTimeout(timer);
  }, [copied]);
  const groups = useMemo(() => manifest.results.filter(x => x.capability.includes(query) || x.family.includes(query)).reduce<Record<string, Capability[]>>((acc, value) => { (acc[value.family] ??= []).push(value); return acc; }, {}), [manifest, query]);
  const command = useMemo(() => {
    try { return serializeCommand(item?.command); } catch { return ''; }
  }, [item]);
  const copyCommand = async () => {
    setCopied(false); setCopyError('');
    try {
      if (!navigator.clipboard) throw new Error('Clipboard unavailable');
      await navigator.clipboard.writeText(command);
      setCopied(true);
    } catch { setCopyError('Could not copy command'); }
  };
  if (!item) return <div className="loading">{error || 'Loading workspace…'}</div>;
  return <div className="app">
    <header className="topbar"><img src="./assets/logo.png" alt="Specialist OS" /><div><div className="brand">Specialist OS</div><div className="product-label">Capability Workspace</div></div><a href="../music-singing/index.html" className="back"><ArrowLeft size={15} /> Music Studio</a></header>
    <div className="shell">
      <aside className="sidebar"><div className="side-title">Capabilities <span>{manifest.results.length}</span></div><SearchInput aria-label="Filter capabilities" value={query} onChange={e => setQuery(e.target.value)} placeholder="Filter capabilities" /><div className="cap-list">{Object.entries(groups).map(([family, entries]) => <section key={family}><div className="family">{family}</div>{entries.map(entry => <NavigationItem active={entry.capability === item.capability} key={entry.capability} onClick={() => { setSelected(entry.capability); location.hash = entry.capability; }}><span>{entry.capability}</span><small>{entry.status}</small></NavigationItem>)}</section>)}</div></aside>
      <main className="content">
        <div className="eyebrow">{item.family}</div>
        <div className="title-row"><div><h1>{item.capability}</h1></div><StatusBadge status={item.status} /></div>
        <section className="input-sample" aria-label="Input sample">
          <div className="section-label">INPUT SAMPLE</div>
          {item.input_sample?.src ? <SampleMedia key={item.input_sample.src} src={`./assets/${item.input_sample.src}`} mime={item.input_sample.mime} name={item.input_sample.name} /> : item.input_sample?.text !== undefined ? <Transcript text={item.input_sample.text} /> : <p>Input sample unavailable</p>}
        </section>
        <section className="result-panel">
          <div className="panel-head"><div><div className="section-label">RESULT</div><h2>Execution output</h2></div><span>{item.cached ? 'Cached result' : item.latency_ms ? `${(item.latency_ms / 1000).toFixed(2)} s` : 'Recorded run'}</span></div>
          {error && <p role="alert">{error}</p>}
          {item.result_view && <Transcript text={item.result_view.text} segments={item.result_view.segments} />}
          {item.preview_unavailable && <p role="status">Preview artifact unavailable</p>}
          {item.preview && <img className="preview" src={`./assets/${item.preview}`} alt={`${item.capability} result`} />}
          {item.media?.map(media => <figure className="media-output" key={media.sha256}><figcaption>{media.src}</figcaption>{media.mime.startsWith('audio/') ? <audio controls preload="metadata" aria-label={media.src}><source src={`./assets/${media.src}`} type={media.mime}/></audio> : <video controls preload="metadata" src={`./assets/${media.src}`} /> }<a href={`./assets/${media.src}`} download>Download</a></figure>)}
          {evidence !== null && <details><summary>Execution JSON</summary><pre>{JSON.stringify(evidence, null, 2)}</pre></details>}
        </section>
      </main>
      <aside className="inspector"><div className="inspector-title"><SlidersHorizontal size={17}/> {item.command_origin === 'reconstructed' ? 'Replay command' : 'Recorded command'}</div><div className="evidence"><pre aria-label="CLI command">{command || 'Command unavailable'}</pre></div><Button className="copy-command" disabled={!command} onClick={copyCommand}><Clipboard size={16}/> {copied ? 'Copied' : 'Copy CLI command'}</Button>{copyError && <p role="alert">{copyError}</p>}<div className="evidence"><div className="section-label">PROVENANCE</div><pre>{JSON.stringify({ capability: item.capability, status: item.status, command_origin: item.command_origin, command: item.command }, null, 2)}</pre></div></aside>
    </div>
  </div>;
}

export default App;

createRoot(document.getElementById('root')!).render(<App />);
