import { useState, useEffect, useCallback } from 'react';
import {
  fetchHealth, fetchStats, fetchSkills, searchSkills, searchMemories,
  fetchProcedures, searchProcedures,
  fetchEpisodes, searchEpisodes,
  fetchReflections, searchReflections,
  fetchMetrics, fetchHotCache,
} from './api';
import './App.css';

type Tab = 'overview' | 'layer1' | 'layer2' | 'layer3' | 'layer4' | 'layer5' | 'skills' | 'search' | 'how';

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
          ['how', 'How'],
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
        {tab === 'how' && <HowPanel />}
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
  const [total, setTotal] = useState(0);
  useEffect(() => { fetchHotCache().then(d => { setItems(d.items); setTotal(d.total); }).catch(() => {}); }, []);
  return (
    <div className="panel">
      <div className="card">
        <h2>Layer 1: Hot Cache</h2>
        <p className="muted">Always-injected, high-priority context (showing {items.length} of {total} total)</p>
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

// ── How It Works ──

function HowPanel() {
  return (
    <div className="panel">
      <div className="card how-page">
        <h2>🧠 How Engram Works</h2>
        <p className="muted">A self-contained 5-layer memory system with NO external cron jobs. Everything runs inside the Engram process.</p>

        <div className="how-flow">
          <div className="flow-step">
            <div className="flow-num">1</div>
            <div className="flow-body">
              <strong>Layer 1: Hot Cache</strong>
              <p>In-memory, persisted to disk. Auto-populated from every write and every recall top hit. Last 30 items kept, last 15 returned. Survives restarts via JSON dump/load.</p>
            </div>
          </div>
          <div className="flow-arrow">↓</div>
          <div className="flow-step">
            <div className="flow-num">2</div>
            <div className="flow-body">
              <strong>Layer 2: Semantic Index</strong>
              <p>ChromaDB (all-MiniLM-L6-v2, 384-dim). All new memories land here. <strong>Dedup-on-write:</strong> content with score ≥ 0.85 merges instead of duplicating (returns existing ID, boosts importance).</p>
            </div>
          </div>
          <div className="flow-arrow">↓</div>
          <div className="flow-step">
            <div className="flow-num">3</div>
            <div className="flow-body">
              <strong>Layer 3: Procedural</strong>
              <p><em>Auto-promoted from L2:</em> memories recalled ≥ 8 times with importance ≥ 0.6 become workflows/procedures.</p>
            </div>
          </div>
          <div className="flow-arrow">↓</div>
          <div className="flow-step">
            <div className="flow-num">4</div>
            <div className="flow-body">
              <strong>Layer 4: Episodic</strong>
              <p><em>Auto-promoted from L3:</em> memories recalled ≥ 15 times with importance ≥ 0.75 become session patterns.</p>
            </div>
          </div>
          <div className="flow-arrow">↓</div>
          <div className="flow-step">
            <div className="flow-num">5</div>
            <div className="flow-body">
              <strong>Layer 5: Reflective</strong>
              <p><em>Auto-promoted from L4:</em> memories recalled ≥ 25 times with importance ≥ 0.85 become hardened insights.</p>
            </div>
          </div>
        </div>

        <h3>⚙️ Automation Pipeline (no cron)</h3>
        <div className="how-section">
          <div className="how-steps">
            <div className="how-step"><span>1</span> <strong>Dedup-on-write:</strong> Before every store, semantic check at 0.85. Duplicate = merge importance, return existing ID. No cruft.</div>
            <div className="how-step"><span>2</span> <strong>Auto-consolidation:</strong> Daemon thread every 30 min. Decays memories {">"}30 days old (reduces importance by age). Purges entries below 0.05.</div>
            <div className="how-step"><span>3</span> <strong>Layer promotion:</strong> In the same consolidation tick, frequently-recalled memories graduate: L2→L3 (8 recalls), L3→L4 (15), L4→L5 (25).</div>
            <div className="how-step"><span>4</span> <strong>L1 persistence:</strong> Hot cache saves to l1_hot_cache.json on shutdown, reloads on startup. Self-pruning at 30 items.</div>
            <div className="how-step"><span>5</span> <strong>Unified recall:</strong> One POST /recall searches all 5 layers. Ranked by combined_score = semantic × 0.6 + importance × 0.4.</div>
          </div>
        </div>

        <h3>📊 Metrics</h3>
        <div className="how-section">
          <p>Every recall query auto-logs to the metrics system on the Overview tab: hit rate, avg score, median, range, categories, and a recent query log.</p>
        </div>

        <h3>💾 Storage</h3>
        <div className="how-section">
          <table className="how-table">
            <thead><tr><th>Component</th><th>Tech</th><th>Details</th></tr></thead>
            <tbody>
              <tr><td>Vector DB</td><td>ChromaDB</td><td>Embedded, no server. all-MiniLM-L6-v2, 384-dim</td></tr>
              <tr><td>Server</td><td>Python stdlib</td><td>http.server, zero deps</td></tr>
              <tr><td>Dashboard</td><td>React + Vite + TS</td><td>Mobile-first, font-toggle</td></tr>
              <tr><td>Persistence</td><td>Filesystem</td><td>ENGRAM_DATA_DIR (F:\hermes\.hermes\engram_data)</td></tr>
            </tbody>
          </table>
        </div>

        <h3>🔌 API</h3>
        <div className="how-section">
          <table className="how-table">
            <thead><tr><th>Method</th><th>Path</th><th>Layer</th><th>Description</th></tr></thead>
            <tbody>
              <tr><td>GET</td><td>/health</td><td>-</td><td>Alive check</td></tr>
              <tr><td>GET</td><td>/stats</td><td>-</td><td>Layer counts + consolidation status</td></tr>
              <tr><td>POST</td><td>/remember</td><td>2</td><td>Store (dedup auto-applied)</td></tr>
              <tr><td>POST</td><td>/recall</td><td>1-5</td><td>Unified search: hot_cache + unified ranked + per-layer buckets</td></tr>
              <tr><td>POST</td><td>/consolidate</td><td>-</td><td>Manual consolidation tick</td></tr>
              <tr><td>POST</td><td>/skills/search</td><td>3</td><td>Find skills</td></tr>
              <tr><td>POST</td><td>/procedures/*</td><td>3</td><td>Store/search/list procedures</td></tr>
              <tr><td>POST</td><td>/episodes/*</td><td>4</td><td>Store/search/list episodes</td></tr>
              <tr><td>POST</td><td>/reflect|reflections/*</td><td>5</td><td>Store/search/list reflections</td></tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
