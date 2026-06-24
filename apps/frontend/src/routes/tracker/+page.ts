import { api } from '$lib/api';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ fetch }) => {
	const [events, organizers, notes] = await Promise.all([
		api.events({ page: 1 }, fetch),
		api.organizers({ page: 1 }, fetch),
		api.trackerNotes(fetch).catch(() => [] as import('$lib/types').TrackerNote[])
	]);
	return { events, organizers, notes };
};
