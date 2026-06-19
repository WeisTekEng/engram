// Engram API client
const BASE = '';

interface Stats {
  semantic_index: {
    total_memories: number;
    categories: string[];
    persist_dir: string;
    embedding_model: string;
    embedding_dims: number;
  };
  hot_cache_size: number;
  budget_max_chars: number;
  persist_dir: string;
}

interface Health {
  status: string;
  layers: Record<string, string>;
  total_memories: number;
  uptime_seconds: number;
}

interface Skill {
  name: string;
  description: string;
  category: string;
  score: number;
}

interface SearchHit {
  content: string;
  score: number;
  category: string;
}

interface RecallResult {
  query: string;
  count: number;
  hot_cache: string[];
  semantic_hits: SearchHit[];
}

// ── Core ──

export async function fetchHealth(): Promise<Health> {
  const res = await fetch(`${BASE}/health`);
  return res.json();
}

export async function fetchStats(): Promise<Stats> {
  const res = await fetch(`${BASE}/stats`);
  return res.json();
}

export async function fetchLayers() {
  const res = await fetch(`${BASE}/layers`);
  return res.json();
}

// ── Layer 2: Skills ──

export async function fetchSkills(): Promise<{ skills: Skill[]; count: number }> {
  const res = await fetch(`${BASE}/skills/list`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({}),
  });
  return res.json();
}

export async function searchSkills(query: string): Promise<Skill[]> {
  const res = await fetch(`${BASE}/skills/search`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, limit: 20 }),
  });
  const data = await res.json();
  return data.skills || [];
}

// ── Search ──

export async function searchMemories(query: string): Promise<RecallResult> {
  const res = await fetch(`${BASE}/recall`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, limit: 20, min_score: 0.2 }),
  });
  return res.json();
}

export async function recallLayer1(): Promise<string[]> {
  const res = await fetch(`${BASE}/recall`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query: 'current', layers: [1] }),
  });
  const data = await res.json();
  return data.hot_cache || [];
}

// ── Layer 3: Procedural ──

export async function fetchProcedures(): Promise<{ procedures: { name: string; content: string; steps?: string; domain?: string; score?: number }[]; count: number }> {
  const res = await fetch(`${BASE}/procedures/list`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
  });
  return res.json();
}

export async function searchProcedures(query: string): Promise<any[]> {
  const res = await fetch(`${BASE}/procedures/search`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, limit: 20 }),
  });
  const data = await res.json();
  return data.procedures || [];
}

// ── Layer 4: Episodic ──

export async function fetchEpisodes(): Promise<{ episodes: { title: string; content: string; timestamp?: string; tags?: string; outcome?: string; score?: number }[]; count: number }> {
  const res = await fetch(`${BASE}/episodes/list`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
  });
  return res.json();
}

export async function searchEpisodes(query: string): Promise<any[]> {
  const res = await fetch(`${BASE}/episodes/search`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, limit: 20 }),
  });
  const data = await res.json();
  return data.episodes || [];
}

// ── Layer 5: Reflective ──

export async function fetchReflections(): Promise<{ reflections: { topic: string; content: string; insight?: string; action?: string; success?: string; score?: number }[]; count: number }> {
  const res = await fetch(`${BASE}/reflections/list`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
  });
  return res.json();
}

export async function searchReflections(query: string): Promise<any[]> {
  const res = await fetch(`${BASE}/reflections/search`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, limit: 20 }),
  });
  const data = await res.json();
  return data.reflections || [];
}
