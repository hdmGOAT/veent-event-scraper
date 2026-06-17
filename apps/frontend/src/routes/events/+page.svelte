<script lang="ts">
	import { api } from '$lib/api';
	import Badge from '$lib/components/Badge.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import { formatDateTime } from '$lib/format';
	import type { EventRow, Paginated } from '$lib/types';

	let q = $state('');
	let page = $state(1);
	let data = $state<Paginated<EventRow> | null>(null);
	let loading = $state(true);
	let error = $state('');

	// Debounce search so we don't fire a request per keystroke.
	let timer: ReturnType<typeof setTimeout>;
	function onSearch(value: string) {
		clearTimeout(timer);
		timer = setTimeout(() => {
			page = 1;
			q = value;
		}, 300);
	}

	$effect(() => {
		// Re-runs whenever q or page change.
		const _q = q;
		const _page = page;
		loading = true;
		error = '';
		api
			.events({ q: _q, page: _page })
			.then((r) => (data = r))
			.catch((e) => (error = String(e)))
			.finally(() => (loading = false));
	});
</script>

<PageHeader title="Events" subtitle="Raw scraped events across all sources" />

<div class="space-y-5 p-8">
	<input
		type="search"
		placeholder="Search events by name or description…"
		oninput={(e) => onSearch(e.currentTarget.value)}
		class="w-full max-w-md rounded-lg border border-border bg-surface px-4 py-2 text-sm text-text placeholder:text-muted focus:border-accent focus:outline-none"
	/>

	{#if error}
		<p class="rounded-lg border border-danger/40 bg-danger-bg/40 px-4 py-3 text-sm text-danger">
			Failed to load events: {error}
		</p>
	{/if}

	<div class="overflow-hidden rounded-xl border border-border bg-surface">
		<table class="w-full text-sm">
			<thead>
				<tr class="border-b border-border text-left text-xs uppercase tracking-wider text-muted">
					<th class="px-5 py-3 font-semibold">Event</th>
					<th class="px-5 py-3 font-semibold">Starts</th>
					<th class="px-5 py-3 font-semibold">Category</th>
					<th class="px-5 py-3 font-semibold">Venue</th>
					<th class="px-5 py-3 font-semibold">Organizer</th>
					<th class="px-5 py-3 font-semibold">Source</th>
				</tr>
			</thead>
			<tbody class="divide-y divide-border">
				{#if loading && !data}
					<tr><td colspan="6" class="px-5 py-10 text-center text-muted">Loading…</td></tr>
				{:else if data && data.results.length === 0}
					<tr><td colspan="6" class="px-5 py-10 text-center text-muted">No events found.</td></tr>
				{:else if data}
					{#each data.results as e (e.slug)}
						<tr class="transition-colors hover:bg-surface-2">
							<td class="px-5 py-3 font-medium text-heading">
								{#if e.url}
									<a href={e.url} target="_blank" rel="noopener" class="hover:text-accent">{e.name}</a>
								{:else}
									{e.name}
								{/if}
							</td>
							<td class="px-5 py-3 text-muted">{formatDateTime(e.starts_at)}</td>
							<td class="px-5 py-3">
								{#if e.category}<Badge status={e.category} />{:else}<span class="text-muted">—</span>{/if}
							</td>
							<td class="px-5 py-3 text-muted">{e.venue ?? '—'}</td>
							<td class="px-5 py-3 text-muted">{e.organizer || '—'}</td>
							<td class="px-5 py-3"><code class="text-xs text-muted">{e.source || '—'}</code></td>
						</tr>
					{/each}
				{/if}
			</tbody>
		</table>
	</div>

	{#if data && data.pages > 1}
		<div class="flex items-center justify-between text-sm text-muted">
			<span>{data.total.toLocaleString()} events · page {data.page} of {data.pages}</span>
			<div class="flex gap-2">
				<button
					class="rounded-lg border border-border px-3 py-1.5 enabled:hover:bg-surface-2 disabled:opacity-40"
					disabled={page <= 1}
					onclick={() => (page -= 1)}>Previous</button
				>
				<button
					class="rounded-lg border border-border px-3 py-1.5 enabled:hover:bg-surface-2 disabled:opacity-40"
					disabled={page >= data.pages}
					onclick={() => (page += 1)}>Next</button
				>
			</div>
		</div>
	{/if}
</div>
