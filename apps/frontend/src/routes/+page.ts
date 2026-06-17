import { api } from '$lib/api';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ fetch }) => {
	const [stats, bySource, byCategory, scrapers] = await Promise.all([
		api.stats(fetch),
		api.eventsBySource(fetch),
		api.eventsByCategory(fetch),
		api.scrapers(fetch)
	]);
	return { stats, bySource, byCategory, scrapers };
};
