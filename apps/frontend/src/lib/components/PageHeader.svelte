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
	<div class="flex items-center gap-3">
		{#if action}
			{@render action()}
		{/if}
		<button
			type="button"
			onclick={() => themeStore.toggle()}
			aria-label={themeStore.current === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
			title={themeStore.current === 'dark' ? 'Light mode' : 'Dark mode'}
			class="flex h-8 w-8 items-center justify-center rounded-lg text-muted transition-colors hover:bg-surface-2 hover:text-heading"
		>
			{#if themeStore.current === 'dark'}
				<Sun size={16} strokeWidth={2} />
			{:else}
				<Moon size={16} strokeWidth={2} />
			{/if}
		</button>
	</div>
</header>
