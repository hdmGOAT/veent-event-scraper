import { api } from '$lib/api';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ fetch }) => {
	const scrapers = await api.scrapers(fetch);
	return { scrapers };
};
