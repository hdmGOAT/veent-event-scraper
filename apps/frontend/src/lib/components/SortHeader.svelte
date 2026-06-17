<script lang="ts">
	// Clickable column header for client-side sortable tables. Shows a neutral
	// chevron when inactive and a directional chevron (accent) when active.
	import { ChevronDown, ChevronsUpDown, ChevronUp } from 'lucide-svelte';
	import type { SortDirection } from '$lib/utils/sort';

	let {
		label,
		active = false,
		direction = 'asc',
		onsort
	}: {
		label: string;
		active?: boolean;
		direction?: SortDirection;
		onsort: () => void;
	} = $props();
</script>

<button
	type="button"
	onclick={onsort}
	class="flex items-center gap-1 text-xs font-semibold uppercase tracking-wider transition-colors {active
		? 'text-heading'
		: 'text-muted hover:text-text'}"
>
	{label}
	{#if !active}
		<ChevronsUpDown size={14} class="text-muted" />
	{:else if direction === 'asc'}
		<ChevronUp size={14} class="text-accent" />
	{:else}
		<ChevronDown size={14} class="text-accent" />
	{/if}
</button>
