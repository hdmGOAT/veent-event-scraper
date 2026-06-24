<script lang="ts">
	import { Moon, Sun } from 'lucide-svelte';
	import Badge from '$lib/components/Badge.svelte';
	import { formatDate } from '$lib/format';
	import { themeStore } from '$lib/theme.svelte';
	import { safeUrl } from '$lib/utils/url';
	import type { PageData } from './$types';

	let { data }: { data: PageData } = $props();
	const o = $derived(data.organizer);
	const websiteUrl = $derived(safeUrl(o?.website));
	const facebookUrl = $derived(safeUrl(o?.facebook_url));
	const instagramUrl = $derived(safeUrl(o?.instagram_url));
	const sourceUrl = $derived(safeUrl(o?.source_url));
</script>

<svelte:head>
	<title>{o?.name ?? 'Organizer'} — Tracker</title>
</svelte:head>

<div class="p-8">
	<div class="mb-5 flex items-center justify-between">
		<a href="/tracker" class="inline-flex items-center gap-1 text-sm text-muted hover:text-accent">
			<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="19" y1="12" x2="5" y2="12" /><polyline points="12 19 5 12 12 5" /></svg>
			Back to Tracker
		</a>
		<button
			type="button"
			onclick={() => themeStore.toggle()}
			aria-label={themeStore.current === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
			class="flex h-8 w-8 items-center justify-center rounded-lg text-muted transition-colors hover:bg-surface-2 hover:text-heading"
		>
			{#if themeStore.current === 'dark'}
				<Sun size={16} strokeWidth={2} />
			{:else}
				<Moon size={16} strokeWidth={2} />
			{/if}
		</button>
	</div>

	<div class="grid grid-cols-1 gap-6 lg:grid-cols-3">
		<!-- Contact card -->
		<aside class="lg:col-span-1">
			<div class="rounded-xl border border-border bg-surface p-6">
				<div class="flex items-start justify-between gap-3">
					<h2 class="text-lg font-semibold text-heading">{o.name}</h2>
					<Badge status={o.status} />
				</div>
				{#if o.description}
					<p class="mt-3 text-sm leading-relaxed text-text">{o.description}</p>
				{/if}

				<dl class="mt-5 space-y-3 text-sm">
					{#if websiteUrl}
						<div>
							<dt class="text-xs uppercase tracking-wider text-muted">Website</dt>
							<dd class="mt-0.5"><a href={websiteUrl} target="_blank" rel="noopener" class="break-all text-accent hover:underline">{o.website}</a></dd>
						</div>
					{/if}
					{#if o.email}
						<div>
							<dt class="text-xs uppercase tracking-wider text-muted">Email</dt>
							<dd class="mt-0.5"><a href="mailto:{o.email}" class="break-all text-accent hover:underline">{o.email}</a></dd>
						</div>
					{/if}
					{#if o.phone}
						<div>
							<dt class="text-xs uppercase tracking-wider text-muted">Phone</dt>
							<dd class="mt-0.5 text-text">{o.phone}</dd>
						</div>
					{/if}
					{#if o.address || o.city || o.country}
						<div>
							<dt class="text-xs uppercase tracking-wider text-muted">Address</dt>
							<dd class="mt-0.5 text-text">{[o.address, o.city, o.country].filter(Boolean).join(', ')}</dd>
						</div>
					{/if}
				</dl>

				{#if facebookUrl || instagramUrl}
					<div class="mt-5 flex gap-3 border-t border-border pt-4">
						{#if facebookUrl}
							<a href={facebookUrl} target="_blank" rel="noopener" title="Facebook" class="text-muted hover:text-accent">
								<svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><path d="M22 12a10 10 0 1 0-11.56 9.88v-6.99H7.9V12h2.54V9.8c0-2.5 1.49-3.89 3.78-3.89 1.09 0 2.24.2 2.24.2v2.46h-1.26c-1.24 0-1.63.77-1.63 1.56V12h2.78l-.44 2.89h-2.34v6.99A10 10 0 0 0 22 12z" /></svg>
							</a>
						{/if}
						{#if instagramUrl}
							<a href={instagramUrl} target="_blank" rel="noopener" title="Instagram" class="text-muted hover:text-accent">
								<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="2" width="20" height="20" rx="5" /><path d="M16 11.37A4 4 0 1 1 12.63 8 4 4 0 0 1 16 11.37z" /><line x1="17.5" y1="6.5" x2="17.51" y2="6.5" /></svg>
							</a>
						{/if}
					</div>
				{/if}

				<div class="mt-5 border-t border-border pt-4 text-xs text-muted">
					{#if sourceUrl}
						<a href={sourceUrl} target="_blank" rel="noopener" class="break-all text-accent hover:underline">View source page</a>
					{/if}
					<div class="mt-1">Last scraped: {formatDate(o.scraped_at)}</div>
				</div>
			</div>
		</aside>

		<!-- Events -->
		<section class="lg:col-span-2">
			<div class="rounded-xl border border-border bg-surface">
				<div class="border-b border-border px-6 py-4">
					<h2 class="text-base font-semibold text-heading">Events ({o.events.length})</h2>
				</div>
				{#if o.events.length === 0}
					<p class="px-6 py-10 text-center text-muted">No events linked to this organizer yet.</p>
				{:else}
					<table class="w-full text-sm">
						<thead>
							<tr class="border-b border-border text-left text-xs uppercase tracking-wider text-muted">
								<th class="px-6 py-3 font-semibold">Event</th>
								<th class="px-6 py-3 font-semibold">Starts</th>
								<th class="px-6 py-3 font-semibold">Category</th>
								<th class="px-6 py-3 font-semibold">Venue</th>
							</tr>
						</thead>
						<tbody class="divide-y divide-border">
							{#each o.events as e (e.slug)}
								<tr class="transition-colors hover:bg-surface-2">
									<td class="px-6 py-3 font-medium text-heading">{e.name}</td>
									<td class="px-6 py-3 text-muted">{formatDate(e.starts_at)}</td>
									<td class="px-6 py-3">
										{#if e.category}<Badge category={e.category} />{:else}<span class="text-muted">—</span>{/if}
									</td>
									<td class="px-6 py-3 text-muted">{e.venue ?? '—'}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				{/if}
			</div>
		</section>
	</div>
</div>
