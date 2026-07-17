import type { Handle } from '@sveltejs/kit';
import { env } from '$env/dynamic/private';

// Read at server startup — change in .env (or deployment environment) to point
// at the real servers. No rebuild needed; env vars are read at runtime.
// `$env/dynamic/private` reads apps/frontend/.env in dev and the real process
// environment in production (adapter-node).
const DJANGO_URL = (env.DJANGO_API_URL ?? 'http://localhost:8000').replace(/\/$/, '');
const NODE_URL = (env.NODE_API_URL ?? 'http://localhost:8001').replace(/\/$/, '');

// Fail closed: the auth gate is active for EVERY environment except an explicit
// `ENVIRONMENT=development`. A missing or misspelled value therefore keeps auth
// ON rather than silently disabling the gate (and secure cookies).
const IS_PRODUCTION = env.ENVIRONMENT !== 'development';

// Short deadline for the per-request session check so a stalled Django can't hang
// protected requests indefinitely.
const AUTH_FETCH_TIMEOUT_MS = 5_000;

// Paths that never require an authenticated Django session. `/_app/`
// (SvelteKit static chunks) is matched by prefix below.
//
// The `/api/auth/*` pre-auth endpoints must be reachable before login because
// the login form action POSTs to them (csrf → login) and logout POSTs to them.
// `/api/auth/me` is intentionally NOT public: it is callable pre-auth but
// returns 401, which the gate below interprets as "not logged in".
const PUBLIC_PATHS = [
	'/login',
	'/logout',
	'/favicon.ico',
	'/api/auth/csrf',
	'/api/auth/login',
	'/api/auth/logout'
];

const isPublicPath = (pathname: string): boolean =>
	PUBLIC_PATHS.includes(pathname) || pathname.startsWith('/_app/');

const redirectToLogin = (): Response =>
	new Response(null, { status: 302, headers: { Location: '/login' } });

// Returned when the session check cannot be completed (Django down / timeout /
// unexpected status). Fail closed — the Node upstream (/node-api/*) has no auth
// of its own, so letting requests through on a backend outage would bypass the
// gate entirely.
const authUnavailable = (): Response =>
	new Response('Authentication service unavailable', { status: 503 });

const proxyRequest = async (targetUrl: string, request: Request): Promise<Response> => {
	const headers = new Headers(request.headers);
	// Remove hop-by-hop headers that shouldn't be forwarded
	for (const h of ['host', 'connection', 'transfer-encoding']) headers.delete(h);

	const body = ['GET', 'HEAD'].includes(request.method) ? undefined : await request.arrayBuffer();

	const controller = new AbortController();
	const timeout = setTimeout(() => controller.abort(), 30_000);

	try {
		const upstream = await fetch(targetUrl, {
			method: request.method,
			headers,
			body: body ? body : undefined,
			signal: controller.signal,
		});

		const responseHeaders = new Headers(upstream.headers);
		responseHeaders.delete('transfer-encoding');

		return new Response(upstream.body, {
			status: upstream.status,
			statusText: upstream.statusText,
			headers: responseHeaders,
		});
	} catch {
		return new Response('Bad Gateway', { status: 502 });
	} finally {
		clearTimeout(timeout);
	}
};

export const handle: Handle = async ({ event, resolve }) => {
	const { pathname, search } = event.url;

	// ── Auth gate ─────────────────────────────────────────────────────────────
	// Runs first so unauthenticated users always land on /login and every route
	// — including proxied /api/* — is protected. Skipped entirely in dev so the
	// local workflow is unaffected.
	//
	// This hook runs before every `+page.server.ts` load, so individual load
	// functions do NOT need their own per-route auth guards — the gate here
	// covers all routes. That is the correct and sufficient architecture.
	if (IS_PRODUCTION) {
		if (isPublicPath(pathname)) {
			// Login/logout/static assets and the pre-auth /api/auth/* endpoints
			// must render/proxy directly.
			//
			// Fall through to the proxy blocks below (public /api/auth/* paths
			// still need proxying); non-/api public paths resolve normally.
			if (!pathname.startsWith('/api/') && !pathname.startsWith('/node-api/')) {
				return resolve(event);
			}
		} else {
			// Per-request session validation against Django. Every non-public,
			// non-asset path makes one outbound HTTP call to Django on the same
			// host — acceptable for this admin dashboard's traffic. Forward ONLY
			// the browser's Cookie header (a simple HEAD-style check); do not
			// forward the body or content-type.
			let meStatus: number;
			try {
				const meRes = await fetch(`${DJANGO_URL}/api/auth/me/`, {
					headers: {
						Cookie: event.request.headers.get('Cookie') ?? '',
						// Tell Django the original request was HTTPS. Without this the
						// server-to-server call is plain HTTP, so with DEBUG=false
						// SECURE_SSL_REDIRECT would 301-redirect it — the gate would then
						// read a non-200/401 status and fail closed, blocking every login.
						// The edge proxy (Caddy/nginx) sets X-Forwarded-Proto on browser
						// traffic; relay it, defaulting to https for the container network
						// where this server-to-server call originates.
						'X-Forwarded-Proto': event.request.headers.get('X-Forwarded-Proto') ?? 'https'
					},
					signal: AbortSignal.timeout(AUTH_FETCH_TIMEOUT_MS)
				});
				meStatus = meRes.status;
			} catch (err) {
				// Network error / timeout reaching Django — fail CLOSED (block).
				console.warn('[auth] /api/auth/me check failed; blocking request (fail-closed).', err);
				return authUnavailable();
			}
			if (meStatus === 401) {
				return redirectToLogin();
			}
			if (meStatus !== 200) {
				// Unexpected upstream status — fail closed rather than allow through.
				console.warn(`[auth] /api/auth/me returned ${meStatus}; blocking request (fail-closed).`);
				return authUnavailable();
			}
		}
	}

	// Proxy /node-api/* → NODE_URL/api/*
	if (pathname.startsWith('/node-api/')) {
		const upstreamPath = '/api/' + pathname.slice('/node-api/'.length);
		return proxyRequest(`${NODE_URL}${upstreamPath}${search}`, event.request);
	}

	// Proxy /api/* → DJANGO_URL/api/*
	if (pathname.startsWith('/api/')) {
		return proxyRequest(`${DJANGO_URL}${pathname}${search}`, event.request);
	}

	// Authenticated users get the full dashboard. The auth gate above already
	// redirects anonymous requests to /login (fail-closed), so anyone who reaches
	// here has a valid Django session and may access every route.
	return resolve(event);
};
