import type { Handle } from '@sveltejs/kit';

// Read at server startup — change in .env (or deployment environment) to point
// at the real servers. No rebuild needed; env vars are read at runtime.
const DJANGO_URL = (process.env.DJANGO_API_URL ?? 'http://localhost:8000').replace(/\/$/, '');
const NODE_URL = (process.env.NODE_API_URL ?? 'http://localhost:8001').replace(/\/$/, '');

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

	// Proxy /node-api/* → NODE_URL/api/*
	if (pathname.startsWith('/node-api/')) {
		const upstreamPath = '/api/' + pathname.slice('/node-api/'.length);
		return proxyRequest(`${NODE_URL}${upstreamPath}${search}`, event.request);
	}

	// Proxy /api/* → DJANGO_URL/api/*
	if (pathname.startsWith('/api/')) {
		return proxyRequest(`${DJANGO_URL}${pathname}${search}`, event.request);
	}

	return resolve(event);
};
