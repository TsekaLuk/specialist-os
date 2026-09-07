import { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { ArrowLeft, Clipboard, Search, SlidersHorizontal } from 'lucide-react';
import { Button } from './components/ui/button';
import './styles.css';

type Capability = { capability: string; family: string; status: string; preview?: string; json: string; latency_ms?: number; command?: string[]; media?: { src: string; mime: string; sha256: string }[] };
type Manifest = { results: Capability[] };

export function App() {
  const [manifest, setManifest] = useState<Manifest>({ results: [] });
  const [selected, setSelected] = useState(() => location.hash.slice(1) || 'vision.detect');
  const [query, setQuery] = useState('');
  const [evidence, setEvidence] = useState<unknown>(null);
  const [copied, setCopied] = useState(false);
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
  useEffect(() => {
    const box = document.querySelector<HTMLElement>('.input-panel');
    if (!box) return;
    box.tabIndex = 0;
    const onFocus = () => box.classList.add('is-focused');
    const onBlur = () => box.classList.remove('is-focused');
    box.addEventListener('focus', onFocus); box.addEventListener('blur', onBlur);
    return () => { box.removeEventListener('focus', onFocus); box.removeEventListener('blur', onBlur); };
  }, [item]);
  const groups = useMemo(() => manifest.results.filter(x => x.capability.includes(query) || x.family.includes(query)).reduce<Record<string, Capability[]>>((acc, value) => { (acc[value.family] ??= []).push(value); return acc; }, {}), [manifest, query]);
  const copyCommand = async () => { await navigator.clipboard?.writeText((item?.command ?? []).join(' ')); setCopied(true); setTimeout(() => setCopied(false), 1400); };
  if (!item) return <div className="loading">{error || 'Loading workspace…'}</div>;
  return <div className="app">
    <header className="topbar"><img src="./assets/logo.png" alt="Specialist OS" /><div><div className="brand">Specialist OS</div><div className="product-label">Capability Workspace</div></div><a href="../music-singing/index.html" className="back"><ArrowLeft size={15} /> Music Studio</a></header>
    <div className="shell">
      <aside className="sidebar"><div className="side-title">Capabilities <span>{manifest.results.length}</span></div><label className="search"><Search size={15}/><input aria-label="Filter capabilities" value={query} onChange={e => setQuery(e.target.value)} placeholder="Filter capabilities" /></label><div className="cap-list">{Object.entries(groups).map(([family, entries]) => <section key={family}><div className="family">{family}</div>{entries.map(entry => <button aria-current={entry.capability === item.capability ? 'page' : undefined} className={entry.capability === item.capability ? 'cap active' : 'cap'} key={entry.capability} onClick={() => { setSelected(entry.capability); location.hash = entry.capability; }}><span>{entry.capability}</span><small>{entry.status}</small></button>)}</section>)}</div></aside>
      <main className="content"><div className="eyebrow">{item.family}</div><div className="title-row"><div><h1>{item.capability}</h1></div><span className="status"><i /> {item.status}</span></div><section className="result-panel"><div className="panel-head"><div><div className="section-label">RESULT</div><h2>Execution output</h2></div><span>{item.latency_ms ? `${(item.latency_ms / 1000).toFixed(2)} s` : 'Recorded run'}</span></div>{error && <p role="alert">{error}</p>}{item.preview && <img className="preview" src={`./assets/${item.preview}`} alt={`${item.capability} result`} />}{item.media?.map(media => <figure className="media-output" key={media.sha256}><figcaption>{media.src}</figcaption>{media.mime.startsWith('audio/') ? <audio controls preload="metadata" aria-label={media.src}><source src={`./assets/${media.src}`} type={media.mime}/></audio> : <video controls preload="metadata" src={`./assets/${media.src}`} /> }<a href={`./assets/${media.src}`} download>Download</a></figure>)}{evidence !== null && <details><summary>Execution JSON</summary><pre>{JSON.stringify(evidence, null, 2)}</pre></details>}</section></main>
      <aside className="inspector"><div className="inspector-title"><SlidersHorizontal size={17}/> Run settings</div><label className="field-label">BACKEND<select><option>real</option></select></label><label className="field-label">OPTIONS<textarea defaultValue={'{"no_cache":true}'} /></label><Button variant="primary" onClick={copyCommand}><Clipboard size={16}/> {copied ? 'Copied' : 'Copy CLI command'}</Button><div className="evidence"><div className="section-label">PROVENANCE</div><p>Provider and input hashes remain attached to this run.</p><pre>{JSON.stringify({ capability: item.capability, status: item.status, command: item.command }, null, 2)}</pre></div></aside>
    </div>
  </div>;
}

export default App;

createRoot(document.getElementById('root')!).render(<App />);
