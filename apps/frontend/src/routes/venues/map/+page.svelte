<script lang="ts">
	import { api } from '$lib/api';
	import VenueMap from '$lib/components/VenueMap.svelte';
	import { Maximize2, Minimize2 } from 'lucide-svelte';
	import type { VenueMapPin } from '$lib/types';

	let allPins = $state<VenueMapPin[]>([]);
	let loading = $state(true);
	let error = $state('');

	let q = $state('');
	let typeFilter = $state('');
	let statusFilter = $state('');
	let isFullscreen = $state(false);
	let mapWrapEl: HTMLDivElement;

	$effect.pre(() => {
		api
			.venueMapPins()
			.then((r) => (allPins = r))
			.catch((e) => (error = String(e)))
			.finally(() => (loading = false));
	});

	const venueTypes = $derived(
		[...new Set(
			allPins.flatMap((p) =>
				p.agents_primary_types.length ? p.agents_primary_types : p.primary_type_display ? [p.primary_type_display] : []
			)
		)].sort()
	);

	const filteredPins = $derived(
		allPins.filter((p) => {
			if (q) {
				const lq = q.toLowerCase();
				if (!p.name.toLowerCase().includes(lq) && !p.city.toLowerCase().includes(lq)) return false;
			}
			if (typeFilter) {
				const types = p.agents_primary_types.length ? p.agents_primary_types : [p.primary_type_display];
				if (!types.includes(typeFilter)) return false;
			}
			if (statusFilter && p.verification_status !== statusFilter) return false;
			return true;
		})
	);

	function toggleFullscreen() {
		if (!document.fullscreenElement) {
			mapWrapEl.requestFullscreen();
		} else {
			document.exitFullscreen();
		}
	}

	$effect(() => {
		const onFsChange = () => {
			isFullscreen = !!document.fullscreenElement;
		};
		document.addEventListener('fullscreenchange', onFsChange);
		return () => document.removeEventListener('fullscreenchange', onFsChange);
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
				{filteredPins.length} / {allPins.length} venue{allPins.length !== 1 ? 's' : ''}
			{/if}
		</span>
	</div>

	<!-- Map area with filter overlay -->
	<div bind:this={mapWrapEl} class="relative min-h-0 flex-1 bg-bg">
		{#if loading}
			<div class="flex h-full items-center justify-center">
				<span class="text-sm text-muted">Loading map…</span>
			</div>
		{:else if error}
			<div class="flex h-full items-center justify-center">
				<span class="text-sm text-danger">{error}</span>
			</div>
		{:else}
			<!-- Filter / search overlay -->
			<div class="absolute left-1/2 top-3 z-[1000] flex -translate-x-1/2 items-center gap-2">
				<!-- Search -->
				<div class="relative">
					<svg class="absolute left-2.5 top-1/2 -translate-y-1/2 text-muted" xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
						<circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/>
					</svg>
					<input
						type="search"
						placeholder="Search venues…"
						aria-label="Search venues"
						bind:value={q}
						class="h-8 rounded-lg border border-border/60 bg-surface/90 pl-7 pr-3 text-xs text-text placeholder:text-muted backdrop-blur focus:border-accent/60 focus:outline-none"
						style="width: 180px;"
					/>
				</div>

				<!-- Type filter -->
				{#if venueTypes.length > 0}
					<select
						bind:value={typeFilter}
						aria-label="Filter by type"
						class="h-8 rounded-lg border border-border/60 bg-surface/90 px-2.5 text-xs text-text backdrop-blur focus:border-accent/60 focus:outline-none"
					>
						<option value="">All types</option>
						{#each venueTypes as t (t)}
							<option value={t}>{t}</option>
						{/each}
					</select>
				{/if}

				<!-- Status filter -->
				<select
					bind:value={statusFilter}
					aria-label="Filter by status"
					class="h-8 rounded-lg border border-border/60 bg-surface/90 px-2.5 text-xs text-text backdrop-blur focus:border-accent/60 focus:outline-none"
				>
					<option value="">All statuses</option>
					<option value="pending">Pending</option>
					<option value="verified">Verified</option>
					<option value="rejected">Rejected</option>
				</select>

				<!-- Fullscreen toggle -->
				<button
					onclick={toggleFullscreen}
					title={isFullscreen ? 'Exit fullscreen' : 'Enter fullscreen'}
					aria-label={isFullscreen ? 'Exit fullscreen' : 'Enter fullscreen'}
					class="flex h-8 w-8 items-center justify-center rounded-lg border border-border/60 bg-surface/90 text-muted backdrop-blur transition-colors hover:border-accent/60 hover:text-accent"
				>
					{#if isFullscreen}
						<Minimize2 size={14} strokeWidth={2} />
					{:else}
						<Maximize2 size={14} strokeWidth={2} />
					{/if}
				</button>
			</div>

			<VenueMap pins={filteredPins} height="100%" />
		{/if}
	</div>
</div>
