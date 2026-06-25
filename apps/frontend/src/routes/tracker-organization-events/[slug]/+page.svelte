<script lang="ts">
	import { ArrowLeft, Check, ExternalLink, Inbox, X } from 'lucide-svelte';
	import Badge from '$lib/components/Badge.svelte';
	import SortHeader from '$lib/components/SortHeader.svelte';
	import { formatDate } from '$lib/format';
	import { sortRows, toggleSort, type SortState } from '$lib/utils/sort';
	import { safeUrl } from '$lib/utils/url';
	import type { PageData } from './$types';

	let { data }: { data: PageData } = $props();

	const DONE_STORAGE_KEY = 'tracker_done_events';

	// ---------------------------------------------------------------------------
	// Done state (shared localStorage key with /tracker)
	// ---------------------------------------------------------------------------
	let doneEvents = $state<Set<string>>(new Set());

	$effect(() => {
		try {
			const raw = localStorage.getItem(DONE_STORAGE_KEY);
			if (raw) {
				const parsed: unknown = JSON.parse(raw);
				if (Array.isArray(parsed))
					doneEvents = new Set(parsed.filter((v): v is string => typeof v === 'string'));
			}
		} catch {
			doneEvents = new Set();
		}
	});

	function toggleDone(slug: string) {
		const next = new Set(doneEvents);
		if (next.has(slug)) next.delete(slug);
		else next.add(slug);
		doneEvents = next;
		try {
			localStorage.setItem(DONE_STORAGE_KEY, JSON.stringify([...next]));
		} catch {}
	}

	// ---------------------------------------------------------------------------
	// Search + filter + sort
	// ---------------------------------------------------------------------------
	let searchInput = $state('');
	let query = $state('');
	let filterCategory = $state('');
	let filterDone = $state('');

	let sortState = $state<SortState<(typeof data.organizer.events)[0]>>({
		key: null,
		direction: 'asc'
	});

	let timer: ReturnType<typeof setTimeout>;
	function onSearch(value: string) {
		clearTimeout(timer);
		timer = setTimeout(() => (query = value), 300);
	}

	const categories = $derived.by(() => {
		const set = new Set<string>();
		for (const e of data.organizer.events) if (e.category) set.add(e.category);
		return [...set].sort((a, b) => a.localeCompare(b));
	});

	const filtersActive = $derived(query !== '' || filterCategory !== '' || filterDone !== '');

	function clearFilters() {
		searchInput = '';
		query = '';
		filterCategory = '';
		filterDone = '';
	}

	const filtered = $derived.by(() => {
		let rows = data.organizer.events;
		if (query) {
			const q = query.toLowerCase();
			rows = rows.filter(
				(e) => e.name.toLowerCase().includes(q) || (e.venue ?? '').toLowerCase().includes(q)
			);
		}
		if (filterCategory) rows = rows.filter((e) => e.category === filterCategory);
		if (filterDone === 'done') rows = rows.filter((e) => doneEvents.has(e.slug));
		else if (filterDone === 'notdone') rows = rows.filter((e) => !doneEvents.has(e.slug));
		return rows;
	});

	const sorted = $derived(sortRows(filtered, sortState.key, sortState.direction));
</script>

<svelte:head>
	<title>{data.organizer.name} — Tracker</title>
</svelte:head>

<div class="space-y-6 p-8">
	<!-- Back + header -->
	<div>
		<a
			href="/tracker"
			class="mb-4 inline-flex items-center gap-1.5 text-sm text-muted transition-colors hover:text-text"
		>
			<ArrowLeft size={15} />
			Back to Tracker
		</a>

		<h1 class="text-2xl font-bold text-heading">{data.organizer.name}</h1>

		<div class="mt-1 flex flex-wrap gap-4 text-sm text-muted">
			{#if data.organizer.city || data.organizer.country}
				<span>{[data.organizer.city, data.organizer.country].filter(Boolean).join(', ')}</span>
			{/if}
			{#if data.organizer.email}
				<a href="mailto:{data.organizer.email}" class="hover:text-accent"
					>{data.organizer.email}</a
				>
			{/if}
			{#if data.organizer.website}
				{@const ws = safeUrl(data.organizer.website)}
				{#if ws}
					<a href={ws} target="_blank" rel="noopener" class="hover:text-accent"
						>{data.organizer.website}</a
					>
				{/if}
			{/if}
			<span class="text-muted">{data.organizer.events.length} event{data.organizer.events.length !== 1 ? 's' : ''}</span>
		</div>
	</div>

	<!-- Filters -->
	<div class="flex flex-wrap items-center gap-3">
		<input
			type="search"
			placeholder="Search events..."
			bind:value={searchInput}
			oninput={(e) => onSearch(e.currentTarget.value)}
			class="rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text placeholder:text-muted focus:border-accent focus:outline-none"
		/>

		<select
			bind:value={filterCategory}
			class="rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text focus:border-accent focus:outline-none"
		>
			<option value="">All Categories</option>
			{#each categories as c (c)}
				<option value={c}>{c}</option>
			{/each}
		</select>

		<select
			bind:value={filterDone}
			class="rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text focus:border-accent focus:outline-none"
		>
			<option value="">All</option>
			<option value="done">Done</option>
			<option value="notdone">Not Done</option>
		</select>

		{#if filtersActive}
			<button
				type="button"
				onclick={clearFilters}
				class="flex items-center gap-1.5 rounded-lg border border-border bg-surface px-3 py-2 text-sm text-muted transition-colors hover:text-text"
			>
				<X size={14} />
				Clear filters
			</button>
		{/if}
	</div>

	<!-- Events table -->
	<div class="overflow-hidden rounded-xl border border-border bg-surface">
		<table class="w-full text-sm">
			<thead>
				<tr class="border-b border-border text-left text-xs uppercase tracking-wider text-muted">
					<th class="px-5 py-3 font-semibold">Done</th>
					<th class="px-5 py-3">
						<SortHeader
							label="Event Name"
							active={sortState.key === 'name'}
							direction={sortState.direction}
							onsort={() => (sortState = toggleSort(sortState, 'name'))}
						/>
					</th>
					<th class="px-5 py-3">
						<SortHeader
							label="Category"
							active={sortState.key === 'category'}
							direction={sortState.direction}
							onsort={() => (sortState = toggleSort(sortState, 'category'))}
						/>
					</th>
					<th class="px-5 py-3">
						<SortHeader
							label="Date"
							active={sortState.key === 'starts_at'}
							direction={sortState.direction}
							onsort={() => (sortState = toggleSort(sortState, 'starts_at'))}
						/>
					</th>
					<th class="px-5 py-3 font-semibold">Venue</th>
					<th class="px-5 py-3 text-right font-semibold">Actions</th>
				</tr>
			</thead>
			<tbody class="divide-y divide-border">
				{#if sorted.length === 0}
					<tr>
						<td colspan="6" class="px-5 py-10 text-center text-sm text-muted">
							<div class="flex flex-col items-center gap-2">
								<Inbox size={28} class="text-muted/50" />
								<span>No events found.</span>
							</div>
						</td>
					</tr>
				{:else}
					{#each sorted as e (e.slug)}
						{@const done = doneEvents.has(e.slug)}
						<tr class="transition-colors hover:bg-surface-2 {done ? 'opacity-60' : ''}">
							<td class="px-5 py-3">
								<button
									type="button"
									aria-label={done ? 'Mark as not done' : 'Mark as done'}
									onclick={() => toggleDone(e.slug)}
									class="flex h-5 w-5 items-center justify-center rounded border transition-colors {done
										? 'border-accent bg-accent text-surface'
										: 'border-border text-transparent hover:border-accent'}"
								>
									<Check size={14} strokeWidth={3} />
								</button>
							</td>
							<td class="px-5 py-3 font-medium text-heading">
								<span class={done ? 'line-through' : ''}>{e.name}</span>
							</td>
							<td class="px-5 py-3">
								{#if e.category}
									<Badge category={e.category} />
								{:else}
									<span class="text-muted">—</span>
								{/if}
							</td>
							<td class="px-5 py-3 text-muted">{formatDate(e.starts_at)}</td>
							<td class="px-5 py-3 text-muted">{e.venue || '—'}</td>
							<td class="px-5 py-3 text-right">
								<a
									href="/tracker/organizers/{data.organizer.slug}"
									class="inline-flex text-muted transition-colors hover:text-accent"
									title="Back to organizer"
								>
									<ExternalLink size={16} />
								</a>
							</td>
						</tr>
					{/each}
				{/if}
			</tbody>
		</table>
	</div>
</div>
