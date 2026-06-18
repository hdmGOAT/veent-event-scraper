<script lang="ts">
	import { api } from '$lib/api';
	import VenueMap from '$lib/components/VenueMap.svelte';
	import type { VenueMapPin } from '$lib/types';

	let pins = $state<VenueMapPin[]>([]);
	let loading = $state(true);
	let error = $state('');

	$effect.pre(() => {
		api
			.venueMapPins()
			.then((r) => (pins = r))
			.catch((e) => (error = String(e)))
			.finally(() => (loading = false));
	});
</script>

<svelte:head>
	<title>Venues Map — Veent Admin</title>
</svelte:head>

<div class="relative flex h-screen flex-col overflow-hidden pt-14 md:pt-0">
	<!-- Header bar -->
	<div class="flex shrink-0 items-center justify-between border-b border-border bg-surface px-6 py-3">
		<div class="flex items-center gap-3">
			<a
				href="/venues"
				class="flex items-center gap-1.5 text-sm text-muted transition-colors hover:text-text"
			>
				<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
					<path d="M15 18l-6-6 6-6"/>
				</svg>
				Venues
			</a>
			<span class="text-border">/</span>
			<span class="text-sm font-medium text-heading">Map</span>
		</div>
		<span class="text-xs text-muted">
			{#if loading}
				Loading…
			{:else if error}
				Error loading pins
			{:else}
				{pins.length} geocoded venue{pins.length !== 1 ? 's' : ''}
			{/if}
		</span>
	</div>

	<!-- Full-height map -->
	<div class="relative min-h-0 flex-1">
		{#if loading}
			<div class="flex h-full items-center justify-center bg-[#0f0f1a]">
				<span class="text-sm text-muted">Loading map…</span>
			</div>
		{:else if error}
			<div class="flex h-full items-center justify-center bg-[#0f0f1a]">
				<span class="text-sm text-danger">{error}</span>
			</div>
		{:else}
			<VenueMap {pins} height="100%" />
		{/if}
	</div>
</div>
