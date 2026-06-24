<script lang="ts">
	import { Check, Inbox, NotebookPen, X } from 'lucide-svelte';
	import { api } from '$lib/api';
	import Badge from '$lib/components/Badge.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import SortHeader from '$lib/components/SortHeader.svelte';
	import TableSkeleton from '$lib/components/TableSkeleton.svelte';
	import { formatDate } from '$lib/format';
	import type { EventRow, Organizer, Paginated } from '$lib/types';
	import { sortRows, toggleSort, type SortState } from '$lib/utils/sort';
	import { safeUrl } from '$lib/utils/url';
	import type { PageData } from './$types';

	let { data }: { data: PageData } = $props();

	const PAGE_SIZE = 25;
	const DONE_STORAGE_KEY = 'tracker_done_events';

	// ---------------------------------------------------------------------------
	// Tab state — persists across switches (each tab keeps its own state below).
	// ---------------------------------------------------------------------------
	type TabId = 'events' | 'organizers';
	let activeTab = $state<TabId>('events');

	// ===========================================================================
	// Done-events persistence (localStorage). Read once on mount, write on change.
	// ===========================================================================
	let doneEvents = $state<Set<string>>(new Set());

	$effect(() => {
		// Initialise from localStorage exactly once (client only).
		try {
			const raw = localStorage.getItem(DONE_STORAGE_KEY);
			if (raw) {
				const parsed: unknown = JSON.parse(raw);
				if (Array.isArray(parsed)) {
					doneEvents = new Set(parsed.filter((v): v is string => typeof v === 'string'));
				}
			}
		} catch {
			// Corrupt/unavailable storage — start empty rather than crash.
			doneEvents = new Set();
		}
	});

	function isDone(slug: string): boolean {
		return doneEvents.has(slug);
	}

	function toggleDone(slug: string) {
		// Optimistic, instant local update. Reassign the Set so Svelte reacts.
		const next = new Set(doneEvents);
		if (next.has(slug)) next.delete(slug);
		else next.add(slug);
		doneEvents = next;
		try {
			localStorage.setItem(DONE_STORAGE_KEY, JSON.stringify([...next]));
		} catch {
			// Storage write failed (quota/private mode) — keep in-memory state.
		}
	}

	// ===========================================================================
	// EVENTS TAB
	// ===========================================================================
	let evSearchInput = $state('');
	let evQuery = $state('');
	let evCategory = $state('');
	let evDate = $state(''); // '' | 'upcoming' | 'past'
	let evDone = $state(''); // '' | 'done' | 'notdone'
	let evPage = $state(1);

	let evData = $state<Paginated<EventRow> | null>(data.events);
	let evLoading = $state(false);
	let evError = $state('');

	let evSort = $state<SortState<EventRow>>({ key: null, direction: 'asc' });
	function evSortBy(key: keyof EventRow) {
		evSort = toggleSort(evSort, key);
	}

	// Debounced search.
	let evTimer: ReturnType<typeof setTimeout>;
	function onEvSearch(value: string) {
		clearTimeout(evTimer);
		evTimer = setTimeout(() => {
			evPage = 1;
			evQuery = value;
		}, 300);
	}

	// Unique categories: combine `category` and flattened `agent_categories`.
	const evCategories = $derived.by(() => {
		const set = new Set<string>();
		for (const e of evData?.results ?? []) {
			if (e.category) set.add(e.category);
			for (const c of e.agent_categories ?? []) {
				if (c) set.add(c);
			}
		}
		return [...set].sort((a, b) => a.localeCompare(b));
	});

	const evFiltersActive = $derived(
		evQuery !== '' || evCategory !== '' || evDate !== '' || evDone !== ''
	);

	function clearEvFilters() {
		evSearchInput = '';
		evQuery = '';
		evCategory = '';
		evDate = '';
		evDone = '';
		evPage = 1;
	}

	// Client-side category/done filtering layered on top of server results.
	// (The API supports q/source/category/upcoming; agent_categories and the
	// "done" state are client-only, so we filter the loaded page here.)
	const evFiltered = $derived.by(() => {
		let rows = evData?.results ?? [];

		if (evCategory) {
			rows = rows.filter(
				(e) => e.category === evCategory || (e.agent_categories ?? []).includes(evCategory)
			);
		}

		if (evDate === 'past') {
			const now = Date.now();
			rows = rows.filter((e) => {
				if (!e.starts_at) return false;
				const t = new Date(e.starts_at).getTime();
				return !Number.isNaN(t) && t < now;
			});
		}

		if (evDone === 'done') {
			rows = rows.filter((e) => doneEvents.has(e.slug));
		} else if (evDone === 'notdone') {
			rows = rows.filter((e) => !doneEvents.has(e.slug));
		}

		return rows;
	});

	const evSorted = $derived(sortRows(evFiltered, evSort.key, evSort.direction));

	// Reset to page 1 whenever a server-affecting filter changes.
	function onEvServerFilterChange() {
		evPage = 1;
	}

	// Fetch events on filter/page change. `upcoming` maps to the API param;
	// 'past' is handled client-side (no API param), so we don't send it.
	$effect(() => {
		const _q = evQuery;
		const _date = evDate;
		const _page = evPage;
		evLoading = true;
		evError = '';
		api
			.events({
				q: _q,
				upcoming: _date === 'upcoming' ? 1 : undefined,
				page: _page
			})
			.then((r) => (evData = r))
			.catch((e) => (evError = String(e)))
			.finally(() => (evLoading = false));
	});

	// ===========================================================================
	// ORGANIZERS TAB
	// ===========================================================================
	let orgSearchInput = $state('');
	let orgQuery = $state('');
	let orgStatus = $state('');
	let orgCity = $state('');
	let orgCountry = $state('');
	let orgPage = $state(1);

	let orgData = $state<Paginated<Organizer> | null>(data.organizers);
	let orgLoading = $state(false);
	let orgError = $state('');

	let orgSort = $state<SortState<Organizer>>({ key: null, direction: 'asc' });
	function orgSortBy(key: keyof Organizer) {
		orgSort = toggleSort(orgSort, key);
	}

	// Per-row status overrides — keyed by slug. Avoids mutating derived state.
	let orgStatusMap = $state<Record<string, string>>({});
	function getOrgStatus(slug: string, fallback: string): string {
		return orgStatusMap[slug] ?? fallback;
	}

	let orgTimer: ReturnType<typeof setTimeout>;
	function onOrgSearch(value: string) {
		clearTimeout(orgTimer);
		orgTimer = setTimeout(() => {
			orgPage = 1;
			orgQuery = value;
		}, 300);
	}

	const orgCities = $derived.by(() => {
		const set = new Set<string>();
		for (const o of orgData?.results ?? []) {
			if (o.city) set.add(o.city);
		}
		return [...set].sort((a, b) => a.localeCompare(b));
	});

	const orgFiltersActive = $derived(
		orgQuery !== '' || orgStatus !== '' || orgCity !== '' || orgCountry.trim() !== ''
	);

	function clearOrgFilters() {
		orgSearchInput = '';
		orgQuery = '';
		orgStatus = '';
		orgCity = '';
		orgCountry = '';
		orgPage = 1;
	}

	// Client-side source/city/country filtering on top of server results.
	const orgFiltered = $derived.by(() => {
		let rows = orgData?.results ?? [];
		if (orgCity) rows = rows.filter((o) => o.city === orgCity);
		if (orgCountry.trim()) {
			const needle = orgCountry.trim().toLowerCase();
			rows = rows.filter((o) => (o.country ?? '').toLowerCase().includes(needle));
		}
		return rows;
	});

	const orgSorted = $derived(sortRows(orgFiltered, orgSort.key, orgSort.direction));

	function onOrgServerFilterChange() {
		orgPage = 1;
	}

	// Fetch organizers on q/status/page change (server-supported params only).
	$effect(() => {
		const _q = orgQuery;
		const _status = orgStatus;
		const _page = orgPage;
		orgLoading = true;
		orgError = '';
		api
			.organizers({ q: _q, status: _status, page: _page })
			.then((r) => (orgData = r))
			.catch((e) => (orgError = String(e)))
			.finally(() => (orgLoading = false));
	});

	// ===========================================================================
	// NOTES
	// ===========================================================================
	let notesMap = $state<Record<string, import('$lib/types').TrackerNote>>({});
	let openNoteKey = $state<string | null>(null);
	let noteEditorContent = $state('');
	let noteSaving = $state(false);

	$effect(() => {
		const init: Record<string, import('$lib/types').TrackerNote> = {};
		for (const n of data.notes) {
			const key = n.event_slug ? `event:${n.event_slug}` : `organizer:${n.organizer_slug}`;
			init[key] = n;
		}
		notesMap = init;
	});

	function openNote(key: string) {
		openNoteKey = key;
		noteEditorContent = notesMap[key]?.content ?? '';
	}

	function closeNote() {
		openNoteKey = null;
	}

	async function saveNote(entityType: 'event' | 'organizer', slug: string) {
		const key = `${entityType}:${slug}`;
		noteSaving = true;
		try {
			const saved = await api.upsertNote(entityType, slug, noteEditorContent.trim());
			notesMap = { ...notesMap, [key]: saved };
			closeNote();
		} finally {
			noteSaving = false;
		}
	}

	async function deleteNote(key: string) {
		const note = notesMap[key];
		if (!note) return;
		await api.deleteNote(note.id);
		const next = { ...notesMap };
		delete next[key];
		notesMap = next;
		closeNote();
	}
</script>

<svelte:head>
	<title>Tracker — Veent Admin</title>
</svelte:head>

<PageHeader title="Tracker" subtitle="Track scraped events and organizers" />

<div class="space-y-5 p-8">
	<!-- Tab switcher -->
	<div class="flex gap-6 border-b border-border">
		<button
			type="button"
			onclick={() => (activeTab = 'events')}
			class="-mb-px border-b-2 px-1 py-2.5 text-sm font-medium transition-colors {activeTab ===
			'events'
				? 'border-accent text-accent'
				: 'border-transparent text-muted hover:text-text'}"
		>
			Events
		</button>
		<button
			type="button"
			onclick={() => (activeTab = 'organizers')}
			class="-mb-px border-b-2 px-1 py-2.5 text-sm font-medium transition-colors {activeTab ===
			'organizers'
				? 'border-accent text-accent'
				: 'border-transparent text-muted hover:text-text'}"
		>
			Organizers
		</button>
	</div>

	<!-- ===================================================================== -->
	<!-- EVENTS TAB                                                             -->
	<!-- ===================================================================== -->
	{#if activeTab === 'events'}
		<!-- Filters bar -->
		<div class="mb-4 flex flex-wrap items-center gap-3">
			<input
				type="search"
				placeholder="Search events..."
				bind:value={evSearchInput}
				oninput={(e) => onEvSearch(e.currentTarget.value)}
				class="rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text placeholder:text-muted focus:border-accent focus:outline-none"
			/>

			<select
				bind:value={evCategory}
				class="rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text focus:border-accent focus:outline-none"
			>
				<option value="">All Categories</option>
				{#each evCategories as c (c)}
					<option value={c}>{c}</option>
				{/each}
			</select>

			<select
				bind:value={evDate}
				onchange={onEvServerFilterChange}
				class="rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text focus:border-accent focus:outline-none"
			>
				<option value="">All Dates</option>
				<option value="upcoming">Upcoming</option>
				<option value="past">Past</option>
			</select>

			<select
				bind:value={evDone}
				class="rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text focus:border-accent focus:outline-none"
			>
				<option value="">All</option>
				<option value="done">Done</option>
				<option value="notdone">Not Done</option>
			</select>

			{#if evFiltersActive}
				<button
					type="button"
					onclick={clearEvFilters}
					class="flex items-center gap-1.5 rounded-lg border border-border bg-surface px-3 py-2 text-sm text-muted transition-colors hover:text-text"
				>
					<X size={14} />
					Clear filters
				</button>
			{/if}
		</div>

		<div class="overflow-hidden rounded-xl border border-border bg-surface">
			<table class="w-full text-sm">
				<thead>
					<tr class="border-b border-border text-left text-xs uppercase tracking-wider text-muted">
						<th class="px-5 py-3 font-semibold">Done</th>
						<th class="px-5 py-3">
							<SortHeader
								label="Event Name"
								active={evSort.key === 'name'}
								direction={evSort.direction}
								onsort={() => evSortBy('name')}
							/>
						</th>
						<th class="px-5 py-3">
							<SortHeader
								label="Organizer"
								active={evSort.key === 'organizer'}
								direction={evSort.direction}
								onsort={() => evSortBy('organizer')}
							/>
						</th>
						<th class="px-5 py-3">
							<SortHeader
								label="Category"
								active={evSort.key === 'category'}
								direction={evSort.direction}
								onsort={() => evSortBy('category')}
							/>
						</th>
						<th class="px-5 py-3">
							<SortHeader
								label="Date"
								active={evSort.key === 'starts_at'}
								direction={evSort.direction}
								onsort={() => evSortBy('starts_at')}
							/>
						</th>
						<th class="px-5 py-3 font-semibold">Venue</th>
						<th class="px-5 py-3 font-semibold">Note</th>
					</tr>
				</thead>
				{#if evLoading && !evData}
					<TableSkeleton columns={7} />
				{:else}
					<tbody class="divide-y divide-border">
						{#if evError}
							<tr>
								<td colspan="7" class="px-5 py-8 text-center text-sm text-danger">{evError}</td>
							</tr>
						{:else if evSorted.length === 0}
							<tr>
								<td colspan="7" class="px-5 py-10 text-center text-sm text-muted">
									<div class="flex flex-col items-center gap-2">
										<Inbox size={28} class="text-muted/50" />
										<span>No events found.</span>
									</div>
								</td>
							</tr>
						{:else}
							{#each evSorted as e (e.slug)}
								{@const done = isDone(e.slug)}
								{@const eventUrl = safeUrl(e.url)}
								{@const evNoteKey = `event:${e.slug}`}
								{@const evNote = notesMap[evNoteKey]}
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
										{#if eventUrl}
											<a href={eventUrl} target="_blank" rel="noopener" class="hover:text-accent {done ? 'line-through' : ''}">{e.name}</a>
										{:else}
											<span class={done ? 'line-through' : ''}>{e.name}</span>
										{/if}
									</td>
									<td class="px-5 py-3 text-muted">
										{#if e.organizer && e.organizer_slug}
											<a href="/tracker/organizers/{e.organizer_slug}" class="hover:text-accent hover:underline"
												>{e.organizer}</a
											>
										{:else}
											{e.organizer || '—'}
										{/if}
									</td>
									<td class="px-5 py-3">
										{#if e.agent_categories && e.agent_categories.length > 0}
											{#each e.agent_categories as cat (cat)}
												<Badge category={cat} />
											{/each}
										{:else if e.category}
											<Badge category={e.category} />
										{:else}
											<span class="text-muted">—</span>
										{/if}
									</td>
									<td class="px-5 py-3 text-muted">{formatDate(e.starts_at)}</td>
									<td class="px-5 py-3 text-muted">
										{#if e.venue && e.venue_slug}
											<a href="/tracker/venues/{e.venue_slug}" class="hover:text-accent hover:underline"
												>{e.venue}</a
											>
										{:else}
											{e.venue || '—'}
										{/if}
									</td>
									<td class="px-5 py-3">
										<button
											type="button"
											onclick={() => openNoteKey === evNoteKey ? closeNote() : openNote(evNoteKey)}
											title={evNote?.content ?? 'Add note'}
											class="flex items-center gap-1 text-xs {evNote ? 'text-accent' : 'text-muted hover:text-text'}"
										>
											<NotebookPen size={14} />
											{#if evNote}
												<span class="max-w-[80px] truncate">{evNote.content}</span>
											{/if}
										</button>
									</td>
								</tr>
								{#if openNoteKey === evNoteKey}
									<tr>
										<td colspan="7" class="bg-surface-2 px-5 py-3">
											<div class="flex flex-col gap-2">
												<textarea
													value={noteEditorContent}
												oninput={(ev) => (noteEditorContent = ev.currentTarget.value)}
													rows={3}
													placeholder="Add a note..."
													class="w-full resize-none rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text placeholder:text-muted focus:border-accent focus:outline-none"
												></textarea>
												<div class="flex items-center gap-2">
													<button
														type="button"
														onclick={() => saveNote('event', e.slug)}
														disabled={noteSaving}
														class="rounded-lg bg-accent px-3 py-1.5 text-xs font-medium text-surface disabled:opacity-50"
													>{noteSaving ? 'Saving…' : 'Save'}</button>
													{#if evNote}
														<button
															type="button"
															onclick={() => deleteNote(evNoteKey)}
															class="text-xs text-danger hover:underline"
														>Delete note</button>
													{/if}
													<button
														type="button"
														onclick={closeNote}
														class="ml-auto text-xs text-muted hover:text-text"
													>Cancel</button>
												</div>
											</div>
										</td>
									</tr>
								{/if}
							{/each}
						{/if}
					</tbody>
				{/if}
			</table>
		</div>

		{#if evData && evData.pages > 1}
			<div class="flex items-center justify-between text-sm text-muted">
				<span>Page {evData.page} of {evData.pages}</span>
				<div class="flex gap-2">
					<button
						class="rounded-lg border border-border px-3 py-1.5 enabled:hover:bg-surface-2 disabled:opacity-40"
						disabled={evPage <= 1 || evLoading}
						onclick={() => (evPage -= 1)}>Previous</button
					>
					<button
						class="rounded-lg border border-border px-3 py-1.5 enabled:hover:bg-surface-2 disabled:opacity-40"
						disabled={evPage >= evData.pages || evLoading}
						onclick={() => (evPage += 1)}>Next</button
					>
				</div>
			</div>
		{/if}
	{/if}

	<!-- ===================================================================== -->
	<!-- ORGANIZERS TAB                                                         -->
	<!-- ===================================================================== -->
	{#if activeTab === 'organizers'}
		<!-- Filters bar -->
		<div class="mb-4 flex flex-wrap items-center gap-3">
			<input
				type="search"
				placeholder="Search organizers..."
				bind:value={orgSearchInput}
				oninput={(e) => onOrgSearch(e.currentTarget.value)}
				class="rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text placeholder:text-muted focus:border-accent focus:outline-none"
			/>

			<select
				bind:value={orgStatus}
				onchange={onOrgServerFilterChange}
				class="rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text focus:border-accent focus:outline-none"
			>
				<option value="">All Statuses</option>
				<option value="pending">Pending</option>
				<option value="confirmed">Confirmed</option>
				<option value="rejected">Rejected</option>
			</select>

			<select
				bind:value={orgCity}
				class="rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text focus:border-accent focus:outline-none"
			>
				<option value="">All Cities</option>
				{#each orgCities as c (c)}
					<option value={c}>{c}</option>
				{/each}
			</select>


			{#if orgFiltersActive}
				<button
					type="button"
					onclick={clearOrgFilters}
					class="flex items-center gap-1.5 rounded-lg border border-border bg-surface px-3 py-2 text-sm text-muted transition-colors hover:text-text"
				>
					<X size={14} />
					Clear filters
				</button>
			{/if}
		</div>

		<div class="overflow-hidden rounded-xl border border-border bg-surface">
			<table class="w-full text-sm">
				<thead>
					<tr class="border-b border-border text-left text-xs uppercase tracking-wider text-muted">
						<th class="px-5 py-3">
							<SortHeader
								label="Name"
								active={orgSort.key === 'name'}
								direction={orgSort.direction}
								onsort={() => orgSortBy('name')}
							/>
						</th>
						<th class="px-5 py-3">
							<SortHeader
								label="Status"
								active={orgSort.key === 'status'}
								direction={orgSort.direction}
								onsort={() => orgSortBy('status')}
							/>
						</th>
						<th class="px-5 py-3">
							<SortHeader
								label="City"
								active={orgSort.key === 'city'}
								direction={orgSort.direction}
								onsort={() => orgSortBy('city')}
							/>
						</th>
						<th class="px-5 py-3 font-semibold">Phone</th>
						<th class="px-5 py-3 font-semibold">Email</th>
						<th class="px-5 py-3 text-right font-semibold">Events</th>
						<th class="px-5 py-3 font-semibold">Note</th>
					</tr>
				</thead>
				{#if orgLoading && !orgData}
					<TableSkeleton columns={7} />
				{:else}
					<tbody class="divide-y divide-border">
						{#if orgError}
							<tr>
								<td colspan="7" class="px-5 py-8 text-center text-sm text-danger">{orgError}</td>
							</tr>
						{:else if orgSorted.length === 0}
							<tr>
								<td colspan="7" class="px-5 py-10 text-center text-sm text-muted">
									<div class="flex flex-col items-center gap-2">
										<Inbox size={28} class="text-muted/50" />
										<span>No organizers found.</span>
									</div>
								</td>
							</tr>
						{:else}
							{#each orgSorted as o (o.slug)}
								{@const currentStatus = getOrgStatus(o.slug, o.status)}
								{@const orgNoteKey = `organizer:${o.slug}`}
								{@const orgNote = notesMap[orgNoteKey]}
								<tr class="transition-colors hover:bg-surface-2">
									<td class="px-5 py-3">
										<a href="/tracker/organizers/{o.slug}" class="font-medium text-heading hover:text-accent"
											>{o.name}</a
										>
									</td>
									<td class="px-5 py-3">
										<select
											value={currentStatus}
											onchange={async (ev) => {
												const next = ev.currentTarget.value;
												const prev = currentStatus;
												orgStatusMap[o.slug] = next;
												try {
													await api.updateOrganizerStatus(o.slug, next);
												} catch {
													orgStatusMap[o.slug] = prev;
												}
											}}
											class="rounded border border-border bg-surface px-2 py-1 text-xs focus:border-accent focus:outline-none
												{currentStatus === 'confirmed' ? 'text-success' : currentStatus === 'rejected' ? 'text-danger' : 'text-warning'}"
										>
											<option value="pending">Pending</option>
											<option value="confirmed">Confirmed</option>
											<option value="rejected">Rejected</option>
										</select>
									</td>
									<td class="px-5 py-3 text-muted">{o.city || '—'}</td>
									<td class="px-5 py-3 text-muted">{o.phone || '—'}</td>
									<td class="px-5 py-3 text-muted">
										{#if o.email}
											<a href="mailto:{o.email}" class="hover:text-accent">{o.email}</a>
										{:else}
											—
										{/if}
									</td>
									<td class="px-5 py-3 text-right">
										<a href="/tracker-organization-events/{o.slug}" class="text-accent hover:underline">View</a>
									</td>
									<td class="px-5 py-3">
										<button
											type="button"
											onclick={() => openNoteKey === orgNoteKey ? closeNote() : openNote(orgNoteKey)}
											title={orgNote?.content ?? 'Add note'}
											class="flex items-center gap-1 text-xs {orgNote ? 'text-accent' : 'text-muted hover:text-text'}"
										>
											<NotebookPen size={14} />
											{#if orgNote}
												<span class="max-w-[80px] truncate">{orgNote.content}</span>
											{/if}
										</button>
									</td>
								</tr>
								{#if openNoteKey === orgNoteKey}
									<tr>
										<td colspan="7" class="bg-surface-2 px-5 py-3">
											<div class="flex flex-col gap-2">
												<textarea
													value={noteEditorContent}
												oninput={(ev) => (noteEditorContent = ev.currentTarget.value)}
													rows={3}
													placeholder="Add a note..."
													class="w-full resize-none rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text placeholder:text-muted focus:border-accent focus:outline-none"
												></textarea>
												<div class="flex items-center gap-2">
													<button
														type="button"
														onclick={() => saveNote('organizer', o.slug)}
														disabled={noteSaving}
														class="rounded-lg bg-accent px-3 py-1.5 text-xs font-medium text-surface disabled:opacity-50"
													>{noteSaving ? 'Saving…' : 'Save'}</button>
													{#if orgNote}
														<button
															type="button"
															onclick={() => deleteNote(orgNoteKey)}
															class="text-xs text-danger hover:underline"
														>Delete note</button>
													{/if}
													<button
														type="button"
														onclick={closeNote}
														class="ml-auto text-xs text-muted hover:text-text"
													>Cancel</button>
												</div>
											</div>
										</td>
									</tr>
								{/if}
							{/each}
						{/if}
					</tbody>
				{/if}
			</table>
		</div>

		{#if orgData && orgData.pages > 1}
			<div class="flex items-center justify-between text-sm text-muted">
				<span>Page {orgData.page} of {orgData.pages}</span>
				<div class="flex gap-2">
					<button
						class="rounded-lg border border-border px-3 py-1.5 enabled:hover:bg-surface-2 disabled:opacity-40"
						disabled={orgPage <= 1 || orgLoading}
						onclick={() => (orgPage -= 1)}>Previous</button
					>
					<button
						class="rounded-lg border border-border px-3 py-1.5 enabled:hover:bg-surface-2 disabled:opacity-40"
						disabled={orgPage >= orgData.pages || orgLoading}
						onclick={() => (orgPage += 1)}>Next</button
					>
				</div>
			</div>
		{/if}
	{/if}
</div>
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   