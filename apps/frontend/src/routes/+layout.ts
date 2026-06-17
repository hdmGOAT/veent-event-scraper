// Client-side render only. The dashboard talks to the Django API through the
// Vite dev proxy (/api -> :8000), which only applies to browser requests, so we
// disable SSR rather than reach the backend from the SvelteKit server.
export const ssr = false;
