import adapter from '@sveltejs/adapter-node';
import { sveltekit } from '@sveltejs/kit/vite';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig, loadEnv } from 'vite';

export default defineConfig(({ mode }) => {
	// Load apps/frontend/.env so DJANGO_API_URL / NODE_API_URL are available to the
	// Vite dev proxy below. Server code (hooks.server.ts, login/+page.server.ts) reads
	// the same file at runtime via `$env/dynamic/private`, so we no longer mutate
	// process.env here — SvelteKit loads these vars in dev and reads the real process
	// environment in production (adapter-node).
	const env = loadEnv(mode, process.cwd(), '');
	const djangoUrl = env.DJANGO_API_URL ?? 'http://localhost:8000';
	const nodeUrl = env.NODE_API_URL ?? 'http://localhost:8001';

	return {
		plugins: [
			tailwindcss(),
			sveltekit({
				// NOTE: when SvelteKit options are passed inline here, svelte.config.js is
				// ignored entirely — the adapter must be configured on this object, not there.
				// adapter-node produces apps/frontend/build/index.js (see docs/deployment §5.4).
				adapter: adapter(),
				compilerOptions: {
					// Force runes mode for the project, except for libraries. Can be removed in svelte 6.
					runes: ({ filename }) =>
						filename.split(/[/\\]/).includes('node_modules') ? undefined : true
				}
			})
		],
		server: {
			// Dev-only proxy. In production, hooks.server.ts takes over using the same env vars.
			proxy: {
				'/node-api': {
					target: nodeUrl,
					changeOrigin: true,
					rewrite: (path) => path.replace(/^\/node-api/, '/api')
				},
				'/api': {
					target: djangoUrl,
					changeOrigin: true
				}
			}
		}
	};
});
