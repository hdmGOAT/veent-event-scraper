import { redirect } from '@sveltejs/kit';
import { env } from '$env/dynamic/private';
import type { RequestHandler } from './$types';

const DJANGO_URL = (env.DJANGO_API_URL ?? 'http://localhost:8000').replace(/\/$/, '');

/**
 * POST-only logout. Calls Django's logout endpoint (forwarding the browser's
 * session cookie + CSRF token), then clears the local `sessionid` + `csrftoken`
 * cookies and redirects to /login. Logout succeeds locally even if Django is
 * unreachable — a down backend must never trap the user in a logged-in shell.
 */
export const POST: RequestHandler = async ({ request, cookies }) => {
	const csrfToken = cookies.get('csrftoken') ?? '';

	try {
		await fetch(`${DJANGO_URL}/api/auth/logout/`, {
			method: 'POST',
			headers: {
				'Content-Type': 'application/json',
				Cookie: request.headers.get('Cookie') ?? '',
				'X-CSRFToken': csrfToken
			}
		});
	} catch {
		// Ignore backend errors — still clear local cookies and redirect below.
	}

	cookies.delete('sessionid', { path: '/' });
	cookies.delete('csrftoken', { path: '/' });

	throw redirect(303, '/login');
};
