<script lang="ts">
	import type { Snippet } from 'svelte';

	let {
		label,
		value,
		sub,
		icon
	}: {
		label: string;
		value: string | number;
		sub?: string;
		icon?: Snippet;
	} = $props();
</script>

<div class="rounded-xl border border-border bg-surface p-5">
	<div class="flex items-start justify-between">
		<span class="text-xs font-semibold uppercase tracking-wider text-muted">{label}</span>
		{#if icon}
			<span class="text-accent">{@render icon()}</span>
		{/if}
	</div>
	<div class="mt-3 text-3xl font-bold text-heading">{value}</div>
	{#if sub}
		<div class="mt-1 text-xs text-muted">{sub}</div>
	{/if}
</div>
