import { api } from '$lib/api';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ fetch }) => {
	const [stats, scrapers, recentRuns] = await Promise.all([
		api.stats(fetch),
		api.scrapers(fetch),
		api.scraperRuns({ limit: 20 }, fetch),
	]);
	return { stats, scrapers, recentRuns };
};
