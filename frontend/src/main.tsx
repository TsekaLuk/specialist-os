import { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { ArrowLeft, Clipboard, FileUp, Search, SlidersHorizontal } from 'lucide-react';
import { Button } from './components/ui/button';
import './styles.css';

type Capability = { capability: string; family: string; status: string; preview?: string; json: string; latency_ms?: number; command?: string[] };
type Manifest = { results: Capability[] };

export function App() {
  const [manifest, setManifest] = useState<Manifest>({ results: [] });
  const [selected, setSelected] = useState('vision.detect');
  const [query, setQuery] = useState('');
  const [evidence, setEvidence] = useState<unknown>(null);
  const [copied, setCopied] = useState(false);
  useEffect(() => { fetch('/core15-20260907/demo.json').then(r => r.json()).then(setManifest); }, []);
  const item = manifest.results.find(result => result.capability === selected) ?? manifest.results[0];
  useEffect(() => { if (!item) return; fetch(`/core15-20260907/assets/${item.json}`).then(r => r.json()).then(setEvidence); }, [item]);
  const groups = useMemo(() => manifest.results.filter(x => x.capability.includes(query) || x.family.includes(query)).reduce<Record<string, Capability[]>>((acc, value) => { (acc[value.family] ??= []).push(value); return acc; }, {}), [manifest, query]);
  const copyCommand = async () => { await navigator.clipboard?.writeText((item?.command ?? []).join(' ')); setCopied(true); setTimeout(() => setCopied(false), 1400); };
  if (!item) return <div className="loading">Loading workspace…</div>;
  return <div className="app">
    <header className="topbar"><img src="/core15-20260907/assets/logo.png" /><div><div className="brand">Specialist OS</div><div className="product-label">Capability Workspace</div></div><a href="/core15-20260907/index.html" className="back"><ArrowLeft size={15} /> Gallery</a></header>
    <div className="shell">
      <aside className="sidebar"><div className="side-title">Capabilities <span>{manifest.results.length}</span></div><label className="search"><Search size={15}/><input value={query} onChange={e => setQuery(e.target.value)} placeholder="Filter capabilities" /></label><div className="cap-list">{Object.entries(groups).map(([family, entries]) => <section key={family}><div className="family">{family}</div>{entries.map(entry => <button className={entry.capability === selected ? 'cap active' : 'cap'} key={entry.capability} onClick={() => setSelected(entry.capability)}><span>{entry.capability}</span><small>{entry.status}</small></button>)}</section>)}</div></aside>
      <main className="content"><div className="eyebrow">{item.family}</div><div className="title-row"><div><h1>{item.capability}</h1><p>Run a local capability, inspect its output, and keep the evidence attached to the result.</p></div><span className="status"><i /> {item.status}</span></div><section className="input-panel"><div><div className="section-label">INPUT ASSET</div><h2>Choose a local file</h2><p>The selected file is passed to the real Specialist CLI.</p></div><Button><FileUp size={16}/> Choose file</Button></section><section className="result-panel"><div className="panel-head"><div><div className="section-label">RESULT</div><h2>Execution output</h2></div><span>{item.latency_ms ? `${(item.latency_ms / 1000).toFixed(2)} s` : 'Recorded run'}</span></div>{item.preview && <img className="preview" src={`/core15-20260907/assets/${item.preview}`} />}{evidence && <pre>{JSON.stringify(evidence, null, 2)}</pre>}</section></main>
      <aside className="inspector"><div className="inspector-title"><SlidersHorizontal size={17}/> Run settings</div><label className="field-label">BACKEND<select><option>real</option></select></label><label className="field-label">OPTIONS<textarea defaultValue={'{"no_cache":true}'} /></label><Button variant="primary" onClick={copyCommand}><Clipboard size={16}/> {copied ? 'Copied' : 'Copy CLI command'}</Button><div className="evidence"><div className="section-label">PROVENANCE</div><p>Provider and input hashes remain attached to this run.</p><pre>{JSON.stringify({ capability: item.capability, status: item.status, command: item.command }, null, 2)}</pre></div></aside>
    </div>
  </div>;
}

export default App;

createRoot(document.getElementById('root')!).render(<App />);
