// Thin typed fetch client for the Django JSON API.
//
// In dev, Vite proxies "/api/*" to the Django server (see vite.config.ts), so
// requests are same-origin and need no CORS. Pass the SvelteKit `fetch` from a
// load function when available so SSR requests are handled correctly.

import type {
	CategoryCount,
	DedupResult,
	EventRow,
	Organizer,
	OrganizerDetail,
	Paginated,
	RunAllResult,
	Scraper,
	ScraperRun,
	ScraperRunStatus,
	ScriptStartResult,
	SearchQuery,
	SourceCount,
	Stats,
	VenueDetail,
	VenueMapPin,
	VenueRow
} from './types';

type Fetch = typeof fetch;

async function get<T>(path: string, fetchFn: Fetch = fetch): Promise<T> {
	const res = await fetchFn(`/api${path}`);
	if (!res.ok) {
		throw new Error(`API ${path} failed: ${res.status} ${res.statusText}`);
	}
	return res.json() as Promise<T>;
}

function getCsrfToken(): string {
	return (
		document.cookie
			.split(';')
			.find((c) => c.trim().startsWith('csrftoken='))
			?.split('=')[1] ?? ''
	);
}

async function post<T>(path: string): Promise<T> {
	const res = await fetch(`/api${path}`, {
		method: 'POST',
		headers: {
			'X-CSRFToken': getCsrfToken(),
			'Content-Type': 'application/json'
		},
		credentials: 'include'
	});
	if (!res.ok) {
		throw new Error(`API ${path} failed: ${res.status} ${res.statusText}`);
	}
	return res.json() as Promise<T>;
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
	const res = await fetch(`/api${path}`, {
		method: 'POST',
		headers: { 'X-CSRFToken': getCsrfToken(), 'Content-Type': 'application/json' },
		credentials: 'include',
		body: JSON.stringify(body)
	});
	if (!res.ok) {
		const err = await res.json().catch(() => ({}));
		throw new Error((err as { error?: string }).error ?? `API ${path} failed: ${res.status}`);
	}
	return res.json() as Promise<T>;
}

async function patch<T>(path: string, body: unknown): Promise<T> {
	const res = await fetch(`/api${path}`, {
		method: 'PATCH',
		headers: { 'X-CSRFToken': getCsrfToken(), 'Content-Type': 'application/json' },
		credentials: 'include',
		body: JSON.stringify(body)
	});
	if (!res.ok) {
		const err = await res.json().catch(() => ({}));
		throw new Error((err as { error?: string }).error ?? `API ${path} failed: ${res.status}`);
	}
	return res.json() as Promise<T>;
}

async function del(path: string): Promise<void> {
	const res = await fetch(`/api${path}`, {
		method: 'DELETE',
		headers: { 'X-CSRFToken': getCsrfToken() },
		credentials: 'include'
	});
	if (!res.ok) {
		throw new Error(`API ${path} failed: ${res.status} ${res.statusText}`);
	}
}

function qs(params: Record<string, string | number | undefined>): string {
	const sp = new URLSearchParams();
	for (const [k, v] of Object.entries(params)) {
		if (v !== undefined && v !== '') sp.set(k, String(v));
	}
	const s = sp.toString();
	return s ? `?${s}` : '';
}

// ---------------------------------------------------------------------------
// Node scraper API — hits /node-api/* (proxied to node-scraper on :8001).
// No Django CSRF needed; Hono has its own CORS allow-list.
// ---------------------------------------------------------------------------

async function nodeGet<T>(path: string): Promise<T> {
	const res = await fetch(`/node-api${path}`);
	if (!res.ok) throw new Error(`Node API ${path} failed: ${res.status} ${res.statusText}`);
	return res.json() as Promise<T>;
}

async function nodePost<T>(path: string): Promise<T> {
	const res = await fetch(`/node-api${path}`, { method: 'POST', headers: { 'Content-Type': 'application/json' } });
	if (!res.ok) {
		const err = await res.json().catch(() => ({}));
		throw new Error((err as { error?: string }).error ?? `Node API ${path} failed: ${res.status}`);
	}
	return res.json() as Promise<T>;
}

export const nodeApi = {
	scrapers: () => nodeGet<Scraper[]>('/scrapers'),
	runScraper: (key: string) => nodePost<{ id: number; status: ScraperRunStatus }>(`/scrapers/${encodeURIComponent(key)}/run`),
	runAll: () => nodePost<RunAllResult>('/scrapers/run-all'),
	scraperRuns: (limit?: number) => nodeGet<ScraperRun[]>(`/scrapers/runs${limit ? `?limit=${limit}` : ''}`),
	activeRuns: () => nodeGet<ScraperRun[]>('/scrapers/runs/active'),
	cancelRun: (id: number) => nodePost<ScraperRun>(`/scrapers/runs/${id}/cancel`)
};

export const api = {
	stats: (f?: Fetch) => get<Stats>('/stats/', f),
	eventsBySource: (f?: Fetch) => get<SourceCount[]>('/events/by-source/', f),
	eventsByCategory: (f?: Fetch) => get<CategoryCount[]>('/events/by-category/', f),
	events: (
		params: { q?: string; source?: string; category?: string; ordering?: string; upcoming?: 1; page?: number } = {},
		f?: Fetch
	) => get<Paginated<EventRow>>(`/events/${qs(params)}`, f),
	organizers: (params: { q?: string; status?: string; page?: number } = {}, f?: Fetch) =>
		get<Paginated<Organizer>>(`/organizers/${qs(params)}`, f),
	organizer: (slug: string, f?: Fetch) => get<OrganizerDetail>(`/organizers/${slug}/`, f),
	venues: (params: { q?: string; status?: string; ordering?: string; type?: string; page?: number } = {}, f?: Fetch) =>
		get<Paginated<VenueRow>>(`/venues/${qs(params)}`, f),
	venueTypes: (f?: Fetch) => get<string[]>('/venues/types/', f),
	venueMapPins: (f?: Fetch) => get<VenueMapPin[]>('/venues/map/', f),
	venue: (slug: string, f?: Fetch) => get<VenueDetail>(`/venues/${slug}/`, f),
	scrapers: (f?: Fetch) => get<Scraper[]>('/scrapers/', f),
	runScraper: (key: string, body?: { query_ids?: number[]; locations?: string[] }) =>
		body && Object.keys(body).length > 0
			? postJson<{ id: number; status: ScraperRunStatus }>(`/scrapers/${key}/run/`, body)
			: post<{ id: number; status: ScraperRunStatus }>(`/scrapers/${key}/run/`),
	runAll: () => post<RunAllResult>('/scrapers/run-all/'),
	deduplicate: () => post<DedupResult>('/scrapers/dedup/'),
	runScript: (scriptName: string) => post<ScriptStartResult>(`/scripts/${scriptName}/run/`),
	scraperRuns: (limit?: number, f?: Fetch) =>
		get<ScraperRun[]>(`/scrapers/runs/${limit ? `?limit=${limit}` : ''}`, f),
	activeRuns: (f?: Fetch) => get<ScraperRun[]>('/scrapers/runs/active/', f),
	scraperRun: (id: number, f?: Fetch) => get<ScraperRun>(`/scrapers/runs/${id}/`, f),
	cancelRun: (id: number) => post<ScraperRun>(`/scrapers/runs/${id}/cancel/`),
	searchQueries: (params: { source?: string } = {}, f?: Fetch) =>
		get<SearchQuery[]>(`/search-queries/${qs(params)}`, f),
	createSearchQuery: (body: { query: string; source?: string; is_active?: boolean }) =>
		postJson<SearchQuery>('/search-queries/', body),
	updateSearchQuery: (id: number, body: { query?: string; is_active?: boolean; source?: string }) =>
		patch<SearchQuery>(`/search-queries/${id}/`, body),
	deleteSearchQuery: (id: number) => del(`/search-queries/${id}/`),
	runSearchQuery: (id: number) =>
		post<{ id: number; status: ScraperRunStatus; scraper_key: string }>(`/search-queries/${id}/run/`),
	getProxySetting: (f?: Fetch) => get<{ enabled: boolean }>('/settings/proxy/', f),
	setProxySetting: (enabled: boolean) => postJson<{ enabled: boolean }>('/settings/proxy/', { enabled })
};
