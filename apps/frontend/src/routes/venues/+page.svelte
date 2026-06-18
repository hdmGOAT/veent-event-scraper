<script lang="ts">
	import { api } from '$lib/api';
	import Badge from '$lib/components/Badge.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import SortHeader from '$lib/components/SortHeader.svelte';
	import TableSkeleton from '$lib/components/TableSkeleton.svelte';
	import type { Paginated, VenueRow } from '$lib/types';

	const tabs = [
		{ label: 'All', value: '' },
		{ label: 'Pending', value: 'pending' },
		{ label: 'Verified', value: 'verified' },
		{ label: 'Rejected', value: 'rejected' }
	];

	let q = $state('');
	let status = $state('');
	let ordering = $state('');
	let venueType = $state('');
	let venueTypes = $state<string[]>([]);
	let page = $state(1);
	let data = $state<Paginated<VenueRow> | null>(null);
	let loading = $state(true);
	let error = $state('');

	$effect.pre(() => {
		api
			.venueTypes()
			.then((r) => (venueTypes = r))
			.catch(() => {});
	});

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
		const _status = status;
		const _ordering = ordering;
		const _type = venueType;
		const _page = page;
		loading = true;
		error = '';
		api
			.venues({ q: _q, status: _status, ordering: _ordering, type: _type, page: _page })
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
	<title>Venues — Veent Admin</title>
</svelte:head>

<PageHeader title="Venues" subtitle="Scraped venues and verification status" />

<div class="space-y-5 p-8">
	<div class="flex flex-wrap items-center justify-between gap-4">
		<div class="flex gap-1 rounded-lg border border-border bg-surface p-1">
			{#each tabs as tab (tab.value)}
				<button
					onclick={() => {
						page = 1;
						ordering = '';
						status = tab.value;
					}}
					class="rounded-md px-3 py-1.5 text-sm font-medium transition-colors {status === tab.value
						? 'bg-accent/15 text-accent'
						: 'text-muted hover:text-text'}"
				>
					{tab.label}
				</button>
			{/each}
		</div>

		<input
			type="search"
			placeholder="Search by name or city…"
			oninput={(e) => onSearch(e.currentTarget.value)}
			class="w-full max-w-xs rounded-lg border border-border bg-surface px-4 py-2 text-sm text-text placeholder:text-muted focus:border-accent focus:outline-none"
		/>

		{#if venueTypes.length > 0}
			<select
				bind:value={venueType}
				onchange={() => (page = 1)}
				class="rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text focus:border-accent focus:outline-none"
			>
				<option value="">All types</option>
				{#each venueTypes as t (t)}
					<option value={t}>{t}</option>
				{/each}
			</select>
		{/if}
	</div>

	<div class="overflow-hidden rounded-xl border border-border bg-surface">
		<table class="w-full text-sm">
			<thead>
				<tr class="border-b border-border text-left text-xs uppercase tracking-wider text-muted">
					<th class="px-5 py-3">
						<SortHeader label="Venue" active={colActive('name')} direction={colDirection('name')} onsort={() => toggleOrdering('name')} />
					</th>
					<th class="px-5 py-3 font-semibold">Type</th>
					<th class="px-5 py-3">
						<SortHeader label="City" active={colActive('city')} direction={colDirection('city')} onsort={() => toggleOrdering('city')} />
					</th>
					<th class="px-5 py-3">
						<SortHeader label="Rating" active={colActive('rating')} direction={colDirection('rating')} onsort={() => toggleOrdering('rating')} />
					</th>
					<th class="px-5 py-3">
						<SortHeader label="Events" active={colActive('event_count')} direction={colDirection('event_count')} onsort={() => toggleOrdering('event_count')} />
					</th>
					<th class="px-5 py-3 font-semibold">Status</th>
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
						{#each data.results as v (v.slug)}
						<tr class="transition-colors hover:bg-surface-2">
							<td class="px-5 py-3 font-medium text-heading">{v.name}</td>
							<td class="px-5 py-3 text-muted">{v.agents_primary_types.length ? v.agents_primary_types.join(', ') : (v.primary_type_display || '—')}</td>
							<td class="px-5 py-3 text-muted">{[v.city, v.country].filter(Boolean).join(', ') || '—'}</td>
							<td class="px-5 py-3 text-muted">{v.rating != null ? `★ ${v.rating}` : '—'}</td>
							<td class="px-5 py-3 text-muted">{v.event_count}</td>
							<td class="px-5 py-3"><Badge status={v.verification_status} /></td>
						</tr>
						{/each}
					{/if}
				</tbody>
			{/if}
		</table>
	</div>

	{#if data && data.pages > 1}
		<div class="flex items-center justify-between text-sm text-muted">
			<span>{data.total.toLocaleString()} venues · page {data.page} of {data.pages}</span>
			<div class="flex gap-2">
				<button class="rounded-lg border border-border px-3 py-1.5 enabled:hover:bg-surface-2 disabled:opacity-40" disabled={page <= 1 || loading} onclick={() => (page -= 1)}>Previous</button>
				<button class="rounded-lg border border-border px-3 py-1.5 enabled:hover:bg-surface-2 disabled:opacity-40" disabled={page >= data.pages || loading} onclick={() => (page += 1)}>Next</button>
			</div>
		</div>
	{/if}
</div>
