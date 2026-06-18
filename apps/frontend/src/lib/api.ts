// Thin typed fetch client for the Django JSON API.
//
// In dev, Vite proxies "/api/*" to the Django server (see vite.config.ts), so
// requests are same-origin and need no CORS. Pass the SvelteKit `fetch` from a
// load function when available so SSR requests are handled correctly.

import type {
	CategoryCount,
	EventRow,
	Organizer,
	OrganizerDetail,
	Paginated,
	RunAllResult,
	Scraper,
	ScraperRun,
	ScraperRunStatus,
	SourceCount,
	Stats,
	VenueDetail,
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

function qs(params: Record<string, string | number | undefined>): string {
	const sp = new URLSearchParams();
	for (const [k, v] of Object.entries(params)) {
		if (v !== undefined && v !== '') sp.set(k, String(v));
	}
	const s = sp.toString();
	return s ? `?${s}` : '';
}

export const api = {
	stats: (f?: Fetch) => get<Stats>('/stats/', f),
	eventsBySource: (f?: Fetch) => get<SourceCount[]>('/events/by-source/', f),
	eventsByCategory: (f?: Fetch) => get<CategoryCount[]>('/events/by-category/', f),
	events: (
		params: { q?: string; source?: string; category?: string; page?: number } = {},
		f?: Fetch
	) => get<Paginated<EventRow>>(`/events/${qs(params)}`, f),
	organizers: (params: { q?: string; status?: string; page?: number } = {}, f?: Fetch) =>
		get<Paginated<Organizer>>(`/organizers/${qs(params)}`, f),
	organizer: (slug: string, f?: Fetch) => get<OrganizerDetail>(`/organizers/${slug}/`, f),
	venues: (params: { q?: string; status?: string; page?: number } = {}, f?: Fetch) =>
		get<Paginated<VenueRow>>(`/venues/${qs(params)}`, f),
	venue: (slug: string, f?: Fetch) => get<VenueDetail>(`/venues/${slug}/`, f),
	scrapers: (f?: Fetch) => get<Scraper[]>('/scrapers/', f),
	runScraper: (key: string) => post<{ id: number; status: ScraperRunStatus }>(`/scrapers/${key}/run/`),
	runAll: () => post<RunAllResult>('/scrapers/run-all/'),
	scraperRuns: (limit?: number, f?: Fetch) =>
		get<ScraperRun[]>(`/scrapers/runs/${limit ? `?limit=${limit}` : ''}`, f),
	activeRuns: (f?: Fetch) => get<ScraperRun[]>('/scrapers/runs/active/', f),
	scraperRun: (id: number, f?: Fetch) => get<ScraperRun>(`/scrapers/runs/${id}/`, f),
	cancelRun: (id: number) => post<ScraperRun>(`/scrapers/runs/${id}/cancel/`)
};
