/**
 * Returns a safe, renderable href for an untrusted (scraped) URL, or `null`.
 *
 * Scraped organizer/website URLs are attacker-influenced, so binding them
 * directly to `href` risks `javascript:`/`data:` scheme injection (XSS). This
 * guard only allows `http:`/`https:`; scheme-less values (e.g. `www.foo.com`)
 * are upgraded to `https://`. Anything else returns `null` so the caller can
 * skip rendering the link.
 */
export function safeUrl(raw: string | null | undefined): string | null {
	if (!raw) return null;
	const trimmed = raw.trim();
	if (!trimmed) return null;

	const candidate = /^https?:\/\//i.test(trimmed)
		? trimmed
		: `https://${trimmed.replace(/^\/+/, '')}`;

	try {
		const url = new URL(candidate);
		return url.protocol === 'http:' || url.protocol === 'https:' ? url.href : null;
	} catch {
		return null;
	}
}
