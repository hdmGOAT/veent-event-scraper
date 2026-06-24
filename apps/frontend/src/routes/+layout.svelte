<script lang="ts">
	import '../app.css';
	import favicon from '$lib/assets/favicon.svg';
	import Sidebar from '$lib/components/Sidebar.svelte';
	import { page } from '$app/state';

	let { children } = $props();

	const isTrackerRoute = $derived(page.url.pathname.startsWith('/tracker'));
</script>

<svelte:head>
	<link rel="icon" href={favicon} />
</svelte:head>

{#if isTrackerRoute}
	<div class="min-h-screen bg-bg text-text">
		{@render children()}
	</div>
{:else}
	<div class="flex min-h-screen bg-bg text-text">
		<Sidebar />
		<main class="min-w-0 flex-1 overflow-x-hidden pt-14 md:pt-0">
			{@render children()}
		</main>
	</div>
{/if}
