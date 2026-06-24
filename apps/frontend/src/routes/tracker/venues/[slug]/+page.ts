import { api } from '$lib/api';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ params, fetch }) => {
	const venue = await api.venue(params.slug, fetch);
	return { venue };
};
