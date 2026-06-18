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
	{/if}
</header>
