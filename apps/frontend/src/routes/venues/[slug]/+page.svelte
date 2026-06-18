<script lang="ts">
	import Badge from '$lib/components/Badge.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import { formatDate } from '$lib/format';
	import { safeUrl } from '$lib/utils/url';
	import type { PageData } from './$types';

	let { data }: { data: PageData } = $props();
	const v = $derived(data.venue);
	const websiteUrl = $derived(safeUrl(v?.website));
	const sourceUrl = $derived(safeUrl(v?.source_url));
</script>

<svelte:head>
	<title>{v?.name ?? 'Venue'} — Veent Admin</title>
</svelte:head>

<PageHeader title={v?.name ?? 'Venue'} subtitle="Venue profile" />

<div class="p-8">
	<a href="/venues" class="mb-5 inline-flex items-center gap-1 text-sm text-muted hover:text-accent">
		<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="19" y1="12" x2="5" y2="12" /><polyline points="12 19 5 12 12 5" /></svg>
		Back to venues
	</a>

	<div class="grid grid-cols-1 gap-6 lg:grid-cols-3">
		<!-- Info card -->
		<aside class="lg:col-span-1">
			<div class="rounded-xl border border-border bg-surface p-6">
				<div class="flex items-start justify-between gap-3">
					<h2 class="text-lg font-semibold text-heading">{v.name}</h2>
					<Badge status={v.verification_status} />
				</div>
				{#if v.about}
					<p class="mt-3 text-sm leading-relaxed text-text">{v.about}</p>
				{/if}

				<dl class="mt-5 space-y-3 text-sm">
					{#if v.city || v.country}
						<div>
							<dt class="text-xs uppercase tracking-wider text-muted">Location</dt>
							<dd class="mt-0.5 text-text">{[v.city, v.country].filter(Boolean).join(', ')}</dd>
						</div>
					{/if}
					{#if v.address}
						<div>
							<dt class="text-xs uppercase tracking-wider text-muted">Address</dt>
							<dd class="mt-0.5 text-text">{v.address}</dd>
						</div>
					{/if}
					{#if websiteUrl}
						<div>
							<dt class="text-xs uppercase tracking-wider text-muted">Website</dt>
							<dd class="mt-0.5"><a href={websiteUrl} target="_blank" rel="noopener" class="break-all text-accent hover:underline">{v.website}</a></dd>
						</div>
					{/if}
					{#if v.rating}
						<div>
							<dt class="text-xs uppercase tracking-wider text-muted">Rating</dt>
							<dd class="mt-0.5 text-text">{v.rating}</dd>
						</div>
					{/if}
					{#if v.primary_type_display}
						<div>
							<dt class="text-xs uppercase tracking-wider text-muted">Type</dt>
							<dd class="mt-0.5 text-text">{v.primary_type_display}</dd>
						</div>
					{/if}
					{#if v.agents_primary_types && v.agents_primary_types.length > 0}
						<div>
							<dt class="text-xs uppercase tracking-wider text-muted">Categories</dt>
							<dd class="mt-1 flex flex-wrap gap-1">
								{#each v.agents_primary_types as t}
									<Badge category={t} />
								{/each}
							</dd>
						</div>
					{/if}
				</dl>

				<div class="mt-5 border-t border-border pt-4 text-xs text-muted">
					<div>Source: <code>{v.source || '—'}</code></div>
					{#if sourceUrl}
						<a href={sourceUrl} target="_blank" rel="noopener" class="break-all text-accent hover:underline">View source page</a>
					{/if}
					<div class="mt-1">Last scraped: {formatDate(v.scraped_at)}</div>
				</div>
			</div>
		</aside>

		<!-- Events -->
		<section class="lg:col-span-2">
			<div class="rounded-xl border border-border bg-surface">
				<div class="border-b border-border px-6 py-4">
					<h2 class="text-base font-semibold text-heading">Events ({v.events.length})</h2>
				</div>
				{#if v.events.length === 0}
					<p class="px-6 py-10 text-center text-muted">No events linked to this venue yet.</p>
				{:else}
					<table class="w-full text-sm">
						<thead>
							<tr class="border-b border-border text-left text-xs uppercase tracking-wider text-muted">
								<th class="px-6 py-3 font-semibold">Event</th>
								<th class="px-6 py-3 font-semibold">Starts</th>
								<th class="px-6 py-3 font-semibold">Category</th>
								<th class="px-6 py-3 font-semibold">Organizer</th>
							</tr>
						</thead>
						<tbody class="divide-y divide-border">
							{#each v.events as e (e.slug)}
								<tr class="transition-colors hover:bg-surface-2">
									<td class="px-6 py-3 font-medium text-heading">{e.name}</td>
									<td class="px-6 py-3 text-muted">{formatDate(e.starts_at)}</td>
									<td class="px-6 py-3">
										{#if e.category}<Badge category={e.category} />{:else}<span class="text-muted">—</span>{/if}
									</td>
									<td class="px-6 py-3 text-muted">{e.organizer || '—'}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				{/if}
			</div>
		</section>
	</div>
</div>
