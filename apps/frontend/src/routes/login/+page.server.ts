import { error, redirect } from '@sveltejs/kit';
import { env } from '$env/dynamic/private';
import type { Actions } from './$types';
import type { Cookies } from '@sveltejs/kit';

const DJANGO_URL = (env.DJANGO_API_URL ?? 'http://localhost:8000').replace(/\/$/, '');
// Fail closed: treat every environment except an explicit `development` as
// production so cookie security (Secure flag) is never silently downgraded by a
// missing/misspelled ENVIRONMENT value. Matches hooks.server.ts.
const IS_PRODUCTION = env.ENVIRONMENT !== 'development';

// Bound the server-to-Django auth calls so a stalled backend can't hang login.
const AUTH_FETCH_TIMEOUT_MS = 5_000;

/**
 * Extract the value of a named cookie from an array of raw `Set-Cookie` header
 * strings (as returned by `Headers.getSetCookie()`). Returns '' if not found.
 */
const readSetCookieValue = (setCookies: string[], name: string): string => {
	for (const raw of setCookies) {
		const [pair] = raw.split(';');
		const eq = pair.indexOf('=');
		if (eq === -1) continue;
		if (pair.slice(0, eq).trim() === name) {
			return pair.slice(eq + 1).trim();
		}
	}
	return '';
};

/**
 * Parse a single raw `Set-Cookie` string into its name, value, and the
 * attributes SvelteKit's `cookies.set()` understands. Security flags
 * (HttpOnly / Secure / SameSite) are re-applied explicitly below so the relay
 * never downgrades the cookie posture Django set.
 */
const parseSetCookie = (
	raw: string
): { name: string; value: string; path: string; maxAge?: number; httpOnly: boolean } | null => {
	const parts = raw.split(';');
	const [pair, ...attrs] = parts;
	const eq = pair.indexOf('=');
	if (eq === -1) return null;

	const name = pair.slice(0, eq).trim();
	const value = pair.slice(eq + 1).trim();
	if (!name) return null;

	let path = '/';
	let maxAge: number | undefined;
	let httpOnly = false;

	for (const attr of attrs) {
		const [k, v] = attr.split('=');
		const key = k.trim().toLowerCase();
		if (key === 'path' && v !== undefined) path = v.trim();
		else if (key === 'max-age' && v !== undefined) {
			const n = Number(v.trim());
			if (!Number.isNaN(n)) maxAge = n;
		} else if (key === 'httponly') httpOnly = true;
	}

	return { name, value, path, maxAge, httpOnly };
};

/**
 * Relay Django's `Set-Cookie` headers to the browser via SvelteKit's cookie
 * API, re-applying HttpOnly / Secure / SameSite so the relayed cookies keep
 * Django's security posture (Risks table row 3).
 */
const relayCookies = (cookies: Cookies, setCookies: string[]): void => {
	for (const raw of setCookies) {
		const parsed = parseSetCookie(raw);
		if (!parsed) continue;
		cookies.set(parsed.name, parsed.value, {
			path: parsed.path,
			httpOnly: parsed.httpOnly,
			secure: IS_PRODUCTION,
			sameSite: 'lax',
			...(parsed.maxAge !== undefined ? { maxAge: parsed.maxAge } : {})
		});
	}
};

export const actions: Actions = {
	default: async ({ request, cookies }) => {
		const form = await request.formData();
		const username = String(form.get('username') ?? '');
		const password = String(form.get('password') ?? '');

		if (!username || !password) {
			throw redirect(303, '/login?error=1');
		}

		// Step 1: obtain a CSRF token from Django (sets the csrftoken cookie).
		let csrfToken = '';
		try {
			const csrfRes = await fetch(`${DJANGO_URL}/api/auth/csrf/`, {
				signal: AbortSignal.timeout(AUTH_FETCH_TIMEOUT_MS)
			});
			csrfToken = readSetCookieValue(csrfRes.headers.getSetCookie(), 'csrftoken');
		} catch {
			throw error(502, 'Login service unavailable');
		}

		// Step 2: POST the credentials with the CSRF double-submit (header + cookie).
		let loginRes: Response;
		try {
			loginRes = await fetch(`${DJANGO_URL}/api/auth/login/`, {
				method: 'POST',
				headers: {
					'Content-Type': 'application/json',
					'X-CSRFToken': csrfToken,
					Cookie: `csrftoken=${csrfToken}`
				},
				body: JSON.stringify({ username, password }),
				signal: AbortSignal.timeout(AUTH_FETCH_TIMEOUT_MS)
			});
		} catch {
			throw error(502, 'Login service unavailable');
		}

		if (loginRes.status === 401) {
			throw redirect(303, '/login?error=1');
		}
		if (loginRes.status === 423) {
			throw redirect(303, '/login?error=locked');
		}
		if (loginRes.status !== 200) {
			throw error(502, 'Login service unavailable');
		}

		// Step 3: relay Django's Set-Cookie headers (sessionid + csrftoken) to the
		// browser, preserving security flags, then send the user into the app.
		relayCookies(cookies, loginRes.headers.getSetCookie());

		throw redirect(303, '/');
	}
};
