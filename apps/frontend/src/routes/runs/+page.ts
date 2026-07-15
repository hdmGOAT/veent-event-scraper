import { api } from '$lib/api';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ fetch, url }) => {
	const status = url.searchParams.get('status') ?? '';
	const scraper_key = url.searchParams.get('scraper_key') ?? '';
	const runs = await api.scraperRuns({ limit: 100, status: status || undefined, scraper_key: scraper_key || undefined }, fetch);
	return { runs, statusFilter: status, keyFilter: scraper_key };
};
