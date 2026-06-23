import { api } from '$lib/api';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ params, fetch }) => {
	const organizer = await api.organizer(params.slug, fetch);
	return { organizer };
};
