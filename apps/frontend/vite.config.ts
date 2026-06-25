import { sveltekit } from '@sveltejs/kit/vite';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig, loadEnv } from 'vite';

export default defineConfig(({ mode }) => {
	// Load root .env (two levels up from apps/frontend) so DJANGO_API_URL / NODE_API_URL
	// are available to the Vite dev proxy without having to duplicate them here.
	const rootEnv = loadEnv(mode, '../../', '');
	const djangoUrl = rootEnv.DJANGO_API_URL ?? 'http://localhost:8000';
	const nodeUrl = rootEnv.NODE_API_URL ?? 'http://localhost:8001';

	// Inject root .env vars into process.env so hooks.server.ts can read them at SSR runtime.
	Object.assign(process.env, rootEnv);

	return {
		plugins: [
			tailwindcss(),
			sveltekit({
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
