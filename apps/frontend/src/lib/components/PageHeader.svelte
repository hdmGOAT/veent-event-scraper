<script lang="ts">
	import type { Snippet } from 'svelte';

	let {
		title,
		subtitle,
		action
	}: { title: string; subtitle?: string; action?: Snippet } = $props();
</script>

<header class="flex items-center justify-between border-b border-border bg-surface/40 px-8 py-5">
	<div>
		<h1 class="text-xl font-semibold text-heading">{title}</h1>
		{#if subtitle}
			<p class="mt-0.5 text-sm text-muted">{subtitle}</p>
		{/if}
	</div>
	{#if action}
		<div class="flex items-center gap-4">
			{@render action()}
		</div>
	{:else}
		<div class="flex items-center gap-4 text-sm text-muted">
			<span>{new Date().toLocaleString(undefined, { month: 'short', day: 'numeric' })}</span>
			<span class="flex h-8 w-8 items-center justify-center rounded-full bg-surface-2 text-accent">
				<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" /><path d="M13.73 21a2 2 0 0 1-3.46 0" /></svg>
			</span>
		</div>
	{/if}
</header>
