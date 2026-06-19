import { useState, useEffect, useCallback } from 'react';
import {
  fetchHealth, fetchStats, fetchSkills, searchSkills, searchMemories, recallLayer1,
  fetchProcedures, searchProcedures,
  fetchEpisodes, searchEpisodes,
  fetchReflections, searchReflections,
  fetchMetrics,
} from './api';
import './App.css';

type Tab = 'overview' | 'layer1' | 'layer2' | 'layer3' | 'layer4' | 'layer5' | 'skills' | 'search';

export default function App() {
  const [tab, setTab] = useState<Tab>('overview');
  const [fontScale, setFontScale] = useState(() => localStorage.getItem('hermes-font-size') || 'large');
  
  useEffect(() => {
    document.documentElement.setAttribute('data-font', fontScale);
  }, [fontScale]);

  return (
    <div className="app">
      <header className="app-header">
        <h1>🧠 Engram</h1>
        <div className="font-controls">
          <button className={fontScale === 'small' ? 'active' : ''} onClick={() => { setFontScale('small'); localStorage.setItem('hermes-font-size', 'small'); }}>S</button>
          <button className={fontScale === 'medium' ? 'active' : ''} onClick={() => { setFontScale('medium'); localStorage.setItem('hermes-font-size', 'medium'); }}>M</button>
          <button className={fontScale === 'large' ? 'active' : ''} onClick={() => { setFontScale('large'); localStorage.setItem('hermes-font-size', 'large'); }}>L</button>
        </div>
      </header>
      
      <nav className="tabs">
        {([
          ['overview', 'Overview'],
          ['layer1', 'L1 Hot'],
          ['layer2', 'L2 Semantic'],
          ['layer3', 'L3 Procedural'],
          ['layer4', 'L4 Episodic'],
          ['layer5', 'L5 Reflect'],
          ['skills', 'Skills'],
          ['search', '🔍'],
        ] as [Tab, string][]).map(([t, label]) => (
          <button key={t} className={`tab ${tab === t ? 'active' : ''}`} onClick={() => setTab(t)}>
            {label}
          </button>
        ))}
      </nav>

      <main className="content">
        {tab === 'overview' && <OverviewPanel />}
        {tab === 'layer1' && <Layer1Panel />}
        {tab === 'layer2' && <Layer2Panel />}
        {tab === 'layer3' && <Layer3Panel />}
        {tab === 'layer4' && <Layer4Panel />}
        {tab === 'layer5' && <Layer5Panel />}
        {tab === 'skills' && <SkillsPanel />}
        {tab === 'search' && <SearchPanel />}
      </main>
    </div>
  );
}

// ── Overview ──

function OverviewPanel() {
  const [health, setHealth] = useState<any>(null);
  const [stats, setStats] = useState<any>(null);
  const [metrics, setMetrics] = useState<any>(null);
  const [error, setError] = useState('');

  const refresh = useCallback(async () => {
    try {
      const [h, s, m] = await Promise.all([fetchHealth(), fetchStats(), fetchMetrics()]);
      setHealth(h); setStats(s); setMetrics(m); setError('');
    } catch (e: any) { setError(e.message); }
  }, []);

  useEffect(() => { refresh(); const i = setInterval(refresh, 10000); return () => clearInterval(i); }, [refresh]);

  if (error) return <div className="card error">⚠️ {error}</div>;
  if (!health || !stats) return <div className="card loading">Loading...</div>;

  return (
    <div className="panel">
      <div className="card">
        <h2>Overview</h2>
        <div className="stat"><span>Status</span><span className={health.status === 'ok' ? 'green' : 'orange'}>{health.status}</span></div>
        <div className="stat"><span>Total Memories</span><span>{stats.semantic_index.total_memories}</span></div>
        <div className="stat"><span>Hot Cache</span><span>{stats.hot_cache_size}</span></div>
        <div className="stat"><span>Categories</span><span>{stats.semantic_index.categories.join(', ') || 'none'}</span></div>
        <div className="stat"><span>Model</span><span>{stats.semantic_index.embedding_model} ({stats.semantic_index.embedding_dims}d)</span></div>

        {metrics && (
          <>
            <h3 style={{ marginTop: 'calc(16px * var(--font-scale))' }}>📊 Query Metrics</h3>
            <div className="metrics-grid">
              <div className="metric-box">
                <div className="metric-value">{metrics.total_queries}</div>
                <div className="metric-label">Total Queries</div>
              </div>
              <div className="metric-box">
                <div className={`metric-value ${metrics.hit_rate >= 0.7 ? 'green' : metrics.hit_rate >= 0.4 ? 'orange' : 'red'}`}>{(metrics.hit_rate * 100).toFixed(0)}%</div>
                <div className="metric-label">Hit Rate</div>
              </div>
              <div className="metric-box">
                <div className="metric-value">{metrics.avg_score.toFixed(3)}</div>
                <div className="metric-label">Avg Score</div>
              </div>
              <div className="metric-box">
                <div className="metric-value">{metrics.median_score.toFixed(3)}</div>
                <div className="metric-label">Median Score</div>
              </div>
            </div>
            <div className="metrics-row">
              <span>Hits: <strong>{metrics.hits ?? 0}</strong></span>
              <span>Misses: <strong>{metrics.misses ?? 0}</strong></span>
              <span>Range: <strong>{(metrics.min_score ?? 0).toFixed(3)} – {(metrics.max_score ?? 0).toFixed(3)}</strong></span>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

// ── Layer 1 ──

function Layer1Panel() {
  const [items, setItems] = useState<string[]>([]);
  useEffect(() => { recallLayer1().then(setItems).catch(() => {}); }, []);
  return (
    <div className="panel">
      <div className="card">
        <h2>Layer 1: Hot Cache</h2>
        <p className="muted">Always-injected, high-priority context</p>
        {items.length ? <ul className="item-list">{items.map((m, i) => <li key={i}>{m}</li>)}</ul> : <p className="muted">Empty</p>}
      </div>
    </div>
  );
}

// ── Layer 2 ──

function Layer2Panel() {
  const [stats, setStats] = useState<any>(null);
  useEffect(() => { fetchStats().then(setStats).catch(() => {}); }, []);
  if (!stats) return <div className="card loading">Loading...</div>;
  return (
    <div className="panel">
      <div className="card">
        <h2>Layer 2: Semantic Index</h2>
        <div className="stat"><span>Total Indexed</span><span>{stats.semantic_index.total_memories}</span></div>
        <div className="stat"><span>Categories</span><span>{stats.semantic_index.categories.join(', ') || 'none'}</span></div>
        <div className="stat"><span>Model</span><span>{stats.semantic_index.embedding_model}</span></div>
        <div className="stat"><span>Dim/Persist</span><span className="path">{stats.semantic_index.embedding_dims}d · {stats.semantic_index.persist_dir}</span></div>
      </div>
    </div>
  );
}

// ── Layer 3: Procedural ──

function Layer3Panel() {
  const [procedures, setProcedures] = useState<any[]>([]);
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchProcedures().then(d => { setProcedures(d.procedures || []); setLoading(false); }).catch(() => setLoading(false));
  }, []);

  const doSearch = async () => {
    if (!query.trim()) { setResults([]); return; }
    setResults(await searchProcedures(query));
  };

  const display = results.length ? results : procedures;

  return (
    <div className="panel">
      <div className="card">
        <h2>Layer 3: Procedural Memory</h2>
        <p className="muted">Workflows and how-to procedures</p>
        <div className="search-bar">
          <input value={query} onChange={e => setQuery(e.target.value)} onKeyDown={e => e.key === 'Enter' && doSearch()}
            placeholder="Search procedures..." />
          <button onClick={doSearch}>Search</button>
        </div>
        {loading ? <p className="loading">Loading...</p> : display.length === 0 ? <p className="muted">No procedures yet</p> :
          <div className="layer-list">
            {display.map((p, i) => (
              <div key={i} className="layer-item">
                <div className="layer-item-header">
                  <strong>{p.name}</strong>
                  {p.score && <span className="badge">{p.score.toFixed(2)}</span>}
                </div>
                <div className="layer-item-meta">{p.domain}</div>
                <div className="layer-item-desc">{p.content?.slice(0, 200)}</div>
                {p.steps && <div className="layer-item-steps">{p.steps}</div>}
              </div>
            ))}
          </div>}
      </div>
    </div>
  );
}

// ── Layer 4: Episodic ──

function Layer4Panel() {
  const [episodes, setEpisodes] = useState<any[]>([]);
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchEpisodes().then(d => { setEpisodes(d.episodes || []); setLoading(false); }).catch(() => setLoading(false));
  }, []);

  const doSearch = async () => {
    if (!query.trim()) { setResults([]); return; }
    setResults(await searchEpisodes(query));
  };

  const display = results.length ? results : episodes;

  return (
    <div className="panel">
      <div className="card">
        <h2>Layer 4: Episodic Memory</h2>
        <p className="muted">Session summaries and key events</p>
        <div className="search-bar">
          <input value={query} onChange={e => setQuery(e.target.value)} onKeyDown={e => e.key === 'Enter' && doSearch()}
            placeholder="Search episodes..." />
          <button onClick={doSearch}>Search</button>
        </div>
        {loading ? <p className="loading">Loading...</p> : display.length === 0 ? <p className="muted">No episodes yet</p> :
          <div className="layer-list">
            {display.map((e, i) => (
              <div key={i} className="layer-item">
                <div className="layer-item-header">
                  <strong>{e.title}</strong>
                  {e.score && <span className="badge">{e.score.toFixed(2)}</span>}
                </div>
                <div className="layer-item-meta">{e.timestamp} · {e.outcome}</div>
                <div className="layer-item-desc">{e.content?.slice(0, 200)}</div>
                {e.tags && <div className="layer-item-tags">{e.tags.split(',').map((t: string) => <span key={t} className="tag">{t.trim()}</span>)}</div>}
              </div>
            ))}
          </div>}
      </div>
    </div>
  );
}

// ── Layer 5: Reflective ──

function Layer5Panel() {
  const [reflections, setReflections] = useState<any[]>([]);
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchReflections().then(d => { setReflections(d.reflections || []); setLoading(false); }).catch(() => setLoading(false));
  }, []);

  const doSearch = async () => {
    if (!query.trim()) { setResults([]); return; }
    setResults(await searchReflections(query));
  };

  const display = results.length ? results : reflections;

  return (
    <div className="panel">
      <div className="card">
        <h2>Layer 5: Meta/Reflective</h2>
        <p className="muted">Self-improvement insights and learnings</p>
        <div className="search-bar">
          <input value={query} onChange={e => setQuery(e.target.value)} onKeyDown={e => e.key === 'Enter' && doSearch()}
            placeholder="Search reflections..." />
          <button onClick={doSearch}>Search</button>
        </div>
        {loading ? <p className="loading">Loading...</p> : display.length === 0 ? <p className="muted">No reflections yet</p> :
          <div className="layer-list">
            {display.map((r, i) => (
              <div key={i} className="layer-item reflection">
                <div className="layer-item-header">
                  <strong>{r.topic}</strong>
                  {r.score && <span className="badge">{r.score.toFixed(2)}</span>}
                </div>
                <div className="layer-item-desc">{r.content?.slice(0, 200)}</div>
                {r.insight && <div className="reflection-insight">💡 {r.insight}</div>}
                {r.action && <div className="reflection-action">→ {r.action}</div>}
                <div className="layer-item-meta">Success: {r.success}</div>
              </div>
            ))}
          </div>}
      </div>
    </div>
  );
}

// ── Skills ──

function SkillsPanel() {
  const [skills, setSkills] = useState<any[]>([]);
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchSkills().then(data => { setSkills(data.skills || []); setLoading(false); }).catch(() => setLoading(false));
  }, []);

  const doSearch = async () => {
    if (!query.trim()) { setResults([]); return; }
    setResults(await searchSkills(query));
  };

  const display = results.length ? results : skills;

  return (
    <div className="panel">
      <div className="card">
        <h2>Skills</h2>
        <div className="search-bar">
          <input value={query} onChange={e => setQuery(e.target.value)} onKeyDown={e => e.key === 'Enter' && doSearch()}
            placeholder="Search skills..." />
          <button onClick={doSearch}>Search</button>
        </div>
        {loading ? <p className="loading">Loading...</p> :
          <div className="skills-grid">
            {display.map((s, i) => (
              <div key={i} className="skill-card">
                <div className="skill-header">
                  <strong>{s.name}</strong>
                  {s.score && <span className="badge">{s.score.toFixed(2)}</span>}
                </div>
                <div className="skill-category">{s.category}</div>
                <div className="skill-desc">{s.description?.slice(0, 150)}</div>
              </div>
            ))}
          </div>}
      </div>
    </div>
  );
}

// ── Search ──

function SearchPanel() {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<any[]>([]);
  const [status, setStatus] = useState('');

  const doSearch = async () => {
    if (!query.trim()) return;
    setStatus('Searching...');
    try {
      const data = await searchMemories(query);
      setResults(data.semantic_hits || []);
      setStatus(`${data.count} results`);
    } catch (e: any) { setStatus(`Error: ${e.message}`); }
  };

  return (
    <div className="panel">
      <div className="card">
        <h2>🔍 Search</h2>
        <div className="search-bar">
          <input value={query} onChange={e => setQuery(e.target.value)} onKeyDown={e => e.key === 'Enter' && doSearch()}
            placeholder="Search all memories..." />
          <button onClick={doSearch}>Search</button>
        </div>
        {status && <p className="muted">{status}</p>}
        {results.map((h, i) => (
          <div key={i} className="search-hit">
            <div className="hit-header">
              <strong>{h.content?.slice(0, 100)}</strong>
              <span className="badge">{h.score?.toFixed(3)}</span>
            </div>
            <span className="hit-category">{h.category}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

