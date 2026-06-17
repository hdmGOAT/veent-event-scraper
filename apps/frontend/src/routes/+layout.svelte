<script lang="ts">
	import '../app.css';
	import favicon from '$lib/assets/favicon.svg';
	import Sidebar from '$lib/components/Sidebar.svelte';

	let { children } = $props();
</script>

<svelte:head>
	<link rel="icon" href={favicon} />
</svelte:head>

<div class="flex min-h-screen bg-bg text-text">
	<Sidebar />
	<main class="min-w-0 flex-1 overflow-x-hidden pt-14 md:pt-0">
		{@render children()}
	</main>
</div>
