<script lang="ts">
	import '../app.css';
	import { onMount } from 'svelte';
	import favicon from '$lib/assets/favicon.svg';
	import Sidebar from '$lib/components/Sidebar.svelte';
	import { page } from '$app/state';
	import { themeStore } from '$lib/theme.svelte';

	let { children } = $props();

	// Bare routes render without the dashboard shell (no sidebar / logout / footer):
	// the auth pages a logged-out user sees.
	const isBareRoute = $derived(
		page.url.pathname === '/login' || page.url.pathname === '/logout'
	);

	onMount(() => {
		themeStore.init();
	});
</script>

<svelte:head>
	<link rel="icon" href={favicon} />
</svelte:head>

{#if isBareRoute}
	<div class="min-h-screen bg-bg text-text">
		{@render children()}
	</div>
{:else}
	<div class="flex min-h-screen bg-bg text-text">
		<Sidebar />
		<main class="min-w-0 flex-1 overflow-x-hidden pt-14 md:pt-0">
			<div class="flex justify-end px-4 pt-2">
				<form method="POST" action="/logout" class="inline">
					<button type="submit" class="text-sm text-muted hover:text-text">Logout</button>
				</form>
			</div>
			{@render children()}
		</main>
	</div>
{/if}
