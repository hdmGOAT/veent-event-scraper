<script lang="ts">
	import '../app.css';
	import { onMount } from 'svelte';
	import favicon from '$lib/assets/favicon.svg';
	import Sidebar from '$lib/components/Sidebar.svelte';
	import { themeStore } from '$lib/theme.svelte';

	let { children } = $props();

	onMount(() => {
		themeStore.init();
	});
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
