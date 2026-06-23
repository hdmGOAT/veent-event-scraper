import { api } from '$lib/api';
import { error } from '@sveltejs/kit';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ params, fetch }) => {
	try {
		const organizer = await api.organizer(params.slug, fetch);
		return { organizer };
	} catch {
		error(404, 'Organizer not found');
	}
};
