import { api } from '$lib/api';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ fetch }) => {
	const queries = await api.searchQueries({}, fetch);
	return { queries };
};
