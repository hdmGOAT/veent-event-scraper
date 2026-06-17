import { api } from '$lib/api';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ fetch }) => {
	const [scrapers, recentRuns] = await Promise.all([
		api.scrapers(fetch),
		api.scraperRuns(undefined, fetch)
	]);
	return { scrapers, recentRuns };
};
