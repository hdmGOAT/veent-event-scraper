<script lang="ts">
	import { api } from '$lib/api';
	import Badge from '$lib/components/Badge.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import SortHeader from '$lib/components/SortHeader.svelte';
	import TableSkeleton from '$lib/components/TableSkeleton.svelte';
	import { formatDateTime } from '$lib/format';
	import type { CategoryCount, EventRow, Paginated, SourceCount } from '$lib/types';

	let q = $state('');
	let source = $state('');
	let category = $state('');
	let ordering = $state('');
	let upcoming = $state(false);
	let page = $state(1);
	let data = $state<Paginated<EventRow> | null>(null);
	let loading = $state(true);
	let error = $state('');
	let sources = $state<SourceCount[]>([]);
	let categories = $state<CategoryCount[]>([]);

	// Load filter options once on mount
	$effect.pre(() => {
		api
			.eventsBySource()
			.then((r) => (sources = r))
			.catch(() => {});
		api
			.eventsByCategory()
			.then((r) => (categories = r))
			.catch(() => {});
	});

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
		const _q = q;
		const _source = source;
		const _category = category;
		const _ordering = ordering;
		const _upcoming = upcoming;
		const _page = page;
		loading = true;
		error = '';
		api
			.events({ q: _q, source: _source, category: _category, ordering: _ordering, upcoming: _upcoming ? 1 : undefined, page: _page })
			.then((r) => (data = r))
			.catch((e) => (error = String(e)))
			.finally(() => (loading = false));
	});

	function colActive(col: string): boolean {
		return ordering === col || ordering === `-${col}`;
	}
	function colDirection(col: string): 'asc' | 'desc' {
		return ordering === `-${col}` ? 'desc' : 'asc';
	}
	function toggleOrdering(col: string) {
		if (ordering === col) {
			ordering = `-${col}`;
		} else if (ordering === `-${col}`) {
			ordering = col;
		} else {
			ordering = col;
		}
		page = 1;
	}
</script>

<svelte:head>
	<title>Events — Veent Admin</title>
</svelte:head>

<PageHeader title="Events" subtitle="Raw scraped events across all sources" />

<div class="space-y-5 p-8">
	<div class="flex flex-wrap items-center gap-3">
		<input
			type="search"
			placeholder="Search events by name or description…"
			oninput={(e) => onSearch(e.currentTarget.value)}
			class="w-full max-w-md rounded-lg border border-border bg-surface px-4 py-2 text-sm text-text placeholder:text-muted focus:border-accent focus:outline-none"
		/>

		{#if sources.length > 0}
			<select
				bind:value={source}
				onchange={() => (page = 1)}
				class="rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text focus:border-accent focus:outline-none"
			>
				<option value="">All sources</option>
				{#each sources as s (s.source)}
					<option value={s.source}>{s.source} ({s.count})</option>
				{/each}
			</select>
		{/if}

		{#if categories.length > 0}
			<select
				bind:value={category}
				onchange={() => (page = 1)}
				class="rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text focus:border-accent focus:outline-none"
			>
				<option value="">All categories</option>
				{#each categories as c (c.category)}
					<option value={c.category}>{c.category} ({c.count})</option>
				{/each}
			</select>
		{/if}

		<label class="flex cursor-pointer items-center gap-2 text-sm text-muted">
			<input
				type="checkbox"
				bind:checked={upcoming}
				onchange={() => (page = 1)}
				class="h-4 w-4 rounded accent-accent"
			/>
			Upcoming only
		</label>
	</div>

	<div class="overflow-hidden rounded-xl border border-border bg-surface">
		<table class="w-full text-sm">
			<thead>
				<tr class="border-b border-border text-left text-xs uppercase tracking-wider text-muted">
					<th class="px-5 py-3">
						<SortHeader label="Event" active={colActive('name')} direction={colDirection('name')} onsort={() => toggleOrdering('name')} />
					</th>
					<th class="px-5 py-3">
						<SortHeader label="Starts" active={colActive('starts_at')} direction={colDirection('starts_at')} onsort={() => toggleOrdering('starts_at')} />
					</th>
					<th class="px-5 py-3 font-semibold">Category</th>
					<th class="px-5 py-3 font-semibold">Venue</th>
					<th class="px-5 py-3 font-semibold">Organizer</th>
					<th class="px-5 py-3 font-semibold">Source</th>
				</tr>
			</thead>
			{#if loading && !data}
				<TableSkeleton columns={6} />
			{:else}
				<tbody class="divide-y divide-border">
					{#if error}
						<tr><td colspan="6" class="px-5 py-8 text-center text-sm text-danger">{error}</td></tr>
					{:else if data && data.results.length === 0}
						<tr><td colspan="6" class="px-5 py-8 text-center text-sm text-muted">No results found.</td></tr>
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
								{#if e.agent_categories && e.agent_categories.length > 0}
									{#each e.agent_categories as cat}
										<Badge category={cat} />
									{/each}
								{:else if e.category}
									<Badge category={e.category} />
								{:else}
									<span class="text-muted">—</span>
								{/if}
							</td>
							<td class="px-5 py-3 text-muted">
								{#if e.venue && e.venue_slug}
									<a href="/venues/{e.venue_slug}" class="hover:text-accent hover:underline">{e.venue}</a>
								{:else}
									{e.venue || '—'}
								{/if}
							</td>
							<td class="px-5 py-3 text-muted">
								{#if e.organizer && e.organizer_slug}
									<a href="/organizers/{e.organizer_slug}" class="hover:text-accent hover:underline">{e.organizer}</a>
								{:else}
									{e.organizer || '—'}
								{/if}
							</td>
							<td class="px-5 py-3"><code class="text-xs text-muted">{e.source || '—'}</code></td>
						</tr>
						{/each}
					{/if}
				</tbody>
			{/if}
		</table>
	</div>

	{#if data && data.pages > 1}
		<div class="flex items-center justify-between text-sm text-muted">
			<span>{data.total.toLocaleString()} events · page {data.page} of {data.pages}</span>
			<div class="flex gap-2">
				<button
					class="rounded-lg border border-border px-3 py-1.5 enabled:hover:bg-surface-2 disabled:opacity-40"
					disabled={page <= 1 || loading}
					onclick={() => (page -= 1)}>Previous</button
				>
				<button
					class="rounded-lg border border-border px-3 py-1.5 enabled:hover:bg-surface-2 disabled:opacity-40"
					disabled={page >= data.pages || loading}
					onclick={() => (page += 1)}>Next</button
				>
			</div>
		</div>
	{/if}
</div>
