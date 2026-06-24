<script lang="ts">
	import type { Snippet } from 'svelte';
	import { Moon, Sun } from 'lucide-svelte';
	import { themeStore } from '$lib/theme.svelte';

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
	<div class="flex items-center gap-4">
		{#if action}
			{@render action()}
		{/if}
		<button
			type="button"
			onclick={() => themeStore.toggle()}
			title={themeStore.current === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
			class="rounded-lg p-1.5 text-muted transition-colors hover:text-accent"
		>
			{#if themeStore.current === 'dark'}
				<Sun size={18} strokeWidth={2} />
			{:else}
				<Moon size={18} strokeWidth={2} />
			{/if}
		</button>
	</div>
</header>
