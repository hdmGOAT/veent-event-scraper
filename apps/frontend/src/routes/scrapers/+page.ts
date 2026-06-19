import { api } from '$lib/api';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ fetch }) => {
	const [scrapers, recentRuns, proxySetting] = await Promise.all([
		api.scrapers(fetch),
		api.scraperRuns(undefined, fetch),
		api.getProxySetting(fetch)
	]);
	return { scrapers, recentRuns, proxyEnabled: proxySetting.enabled };
};
