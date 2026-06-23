<script lang="ts">
	import { api } from '$lib/api';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import type { SearchQuery } from '$lib/types';
	import type { ScraperRunStatus } from '$lib/types';
	import { Play, PlayCircle, Plus, RefreshCw, Search, Trash2, ToggleLeft, ToggleRight } from 'lucide-svelte';

	let { data } = $props();

	// ── State ────────────────────────────────────────────────────────────────
	let queries = $state<SearchQuery[]>(data.queries);
	let sourceFilter = $state('');
	let showAddForm = $state(false);
	let newQuery = $state('');
	let adding = $state(false);
	let addError = $state('');
	let addSummary = $state('');

	// Per-row run state: query id → partial run shape (only scraper_key is needed for polling)
	let runningRows = $state<Map<number, { id: number; status: ScraperRunStatus; scraper_key: string } | null>>(new Map());
	let runningAll = $state(false);
	let runAllError = $state('');

	let deletingIds = $state(new Set<number>());
	let togglingIds = $state(new Set<number>());

	let pollTimer: ReturnType<typeof setInterval> | null = null;

	// ── Derived ───────────────────────────────────────────────────────────────
	const sources = $derived([...new Set(queries.map((q) => q.source))].sort());
	const filtered = $derived(
		sourceFilter ? queries.filter((q) => q.source === sourceFilter) : queries
	);
	const activeCount = $derived(filtered.filter((q) => q.is_active).length);
	const anyRunning = $derived(runningRows.size > 0 || runningAll);

	// ── Polling active runs ───────────────────────────────────────────────────
	function startPolling() {
		if (pollTimer) return;
		pollTimer = setInterval(pollActiveRuns, 2500);
	}

	function stopPolling() {
		if (pollTimer) {
			clearInterval(pollTimer);
			pollTimer = null;
		}
	}

	async function pollActiveRuns() {
		if (runningRows.size === 0 && !runningAll) {
			stopPolling();
			return;
		}
		try {
			const active = await api.activeRuns();
			const activeKeys = new Set(active.map((r) => r.scraper_key));

			// Update per-row run state
			for (const [qid, run] of runningRows) {
				if (!run) continue;
				const stillActive = activeKeys.has(run.scraper_key);
				if (!stillActive) {
					// Run finished — refresh query stats and remove from map
					runningRows = new Map([...runningRows].filter(([k]) => k !== qid));
					queries = await api.searchQueries();
				}
			}

			// Update "run all" state
			if (runningAll) {
				const activeSources = new Set(active.map((r) => r.scraper_key));
				const allSourcesDone = sources
					.filter((s) => filtered.some((q) => q.source === s && q.is_active))
					.every((s) => !activeSources.has(s));
				if (allSourcesDone) {
					runningAll = false;
					queries = await api.searchQueries();
				}
			}

			if (runningRows.size === 0 && !runningAll) stopPolling();
		} catch {
			// Ignore poll errors
		}
	}

	// ── Actions ───────────────────────────────────────────────────────────────
	async function refresh() {
		queries = await api.searchQueries();
	}

	async function handleAdd() {
		if (!newQuery.trim()) return;
		const tokens = newQuery
			.split(',')
			.map((t) => t.trim())
			.filter((t) => t.length > 0);
		if (tokens.length === 0) return;

		adding = true;
		addError = '';
		addSummary = '';
		let added = 0;
		let skipped = 0;
		const created: SearchQuery[] = [];
		for (const token of tokens) {
			try {
				created.push(await api.createSearchQuery({ query: token }));
				added += 1;
			} catch {
				// Most likely a 409 (already exists); count as skipped and continue.
				skipped += 1;
			}
		}

		if (created.length > 0) {
			queries = [...queries, ...created];
		}

		if (tokens.length > 1) {
			addSummary = `${added} added, ${skipped} already existed`;
		} else if (skipped > 0) {
			addError = 'Query already exists';
		}

		if (added > 0) {
			newQuery = '';
			if (tokens.length === 1) showAddForm = false;
		}
		adding = false;
	}

	async function handleToggle(sq: SearchQuery) {
		togglingIds = new Set([...togglingIds, sq.id]);
		try {
			const updated = await api.updateSearchQuery(sq.id, { is_active: !sq.is_active });
			queries = queries.map((q) => (q.id === sq.id ? updated : q));
		} finally {
			togglingIds = new Set([...togglingIds].filter((id) => id !== sq.id));
		}
	}

	async function handleDelete(sq: SearchQuery) {
		if (!confirm(`Delete query "${sq.query}"?`)) return;
		deletingIds = new Set([...deletingIds, sq.id]);
		try {
			await api.deleteSearchQuery(sq.id);
			queries = queries.filter((q) => q.id !== sq.id);
		} finally {
			deletingIds = new Set([...deletingIds].filter((id) => id !== sq.id));
		}
	}

	async function handleRunSingle(sq: SearchQuery) {
		if (runningRows.has(sq.id)) return;
		try {
			const run = await api.runSearchQuery(sq.id);
			// Fetch the full run detail so we have scraper_key for polling
			runningRows = new Map([...runningRows, [sq.id, run]]);
			startPolling();
		} catch (e) {
			alert(e instanceof Error ? e.message : 'Failed to start run');
		}
	}

	async function handleRunAll() {
		if (runningAll) return;
		runAllError = '';
		runningAll = true;
		try {
			// Collect unique sources from currently active+filtered queries
			const activeSources = [...new Set(
				filtered.filter((q) => q.is_active).map((q) => q.source)
			)];
			if (activeSources.length === 0) {
				runAllError = 'No active queries to run.';
				runningAll = false;
				return;
			}
			await Promise.allSettled(activeSources.map((src) => api.runScraper(src)));
			startPolling();
		} catch (e) {
			runAllError = e instanceof Error ? e.message : 'Failed to start run';
			runningAll = false;
		}
	}

	function isRowRunning(sq: SearchQuery): boolean {
		return runningRows.has(sq.id);
	}

	function formatDate(iso: string | null) {
		if (!iso) return '—';
		return new Date(iso).toLocaleString('en-PH', {
			month: 'short', day: 'numeric', year: 'numeric',
			hour: '2-digit', minute: '2-digit'
		});
	}
</script>

<div class="mx-auto max-w-5xl px-4 py-8 md:px-8">
	<PageHeader title="Search Queries">
		{#snippet action()}
			<button
				onclick={refresh}
				title="Refresh list"
				class="rounded-md border border-border px-3 py-1.5 text-sm text-muted transition hover:bg-surface-2 hover:text-text"
			>
				<RefreshCw size={14} />
			</button>

			<!-- Run All -->
			<button
				onclick={handleRunAll}
				disabled={runningAll || activeCount === 0}
				title="Trigger all active queries"
				class="flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-sm font-medium transition
					{runningAll
						? 'cursor-not-allowed border-warning/40 bg-warning/10 text-warning opacity-80'
						: 'text-text hover:bg-surface-2 disabled:cursor-not-allowed disabled:opacity-40'}"
			>
				<PlayCircle size={14} />
				{runningAll ? 'Running…' : 'Run All'}
			</button>

			<button
				onclick={() => { showAddForm = !showAddForm; addError = ''; }}
				class="flex items-center gap-1.5 rounded-md bg-accent/15 px-3 py-1.5 text-sm font-medium text-accent transition hover:bg-accent/25"
			>
				<Plus size={14} />
				Add Query
			</button>
		{/snippet}
	</PageHeader>

	{#if runAllError}
		<p class="mb-4 rounded-lg bg-danger-bg px-4 py-2 text-sm text-danger">{runAllError}</p>
	{/if}

	<!-- Add query form -->
	{#if showAddForm}
		<div class="mb-6 rounded-xl border border-border bg-surface p-5">
			<p class="mb-4 text-sm font-medium text-heading">New Search Query</p>
			<div class="flex flex-col gap-3 sm:flex-row sm:items-end">
				<div class="flex-1">
					<label for="new-query" class="mb-1 block text-xs text-muted">Search term</label>
					<input
						id="new-query"
						type="text"
						placeholder="e.g. events in CDO, tech events, startup"
						bind:value={newQuery}
						onkeydown={(e) => e.key === 'Enter' && handleAdd()}
						class="w-full rounded-md border border-border bg-surface-2 px-3 py-2 text-sm text-text placeholder:text-muted focus:border-accent focus:outline-none"
					/>
				</div>
				<div class="flex gap-2">
					<button
						onclick={handleAdd}
						disabled={adding || !newQuery.trim()}
						class="rounded-md bg-accent px-4 py-2 text-sm font-medium text-bg transition hover:bg-accent/90 disabled:cursor-not-allowed disabled:opacity-50"
					>
						{adding ? 'Adding…' : 'Add'}
					</button>
					<button
						onclick={() => { showAddForm = false; addError = ''; addSummary = ''; newQuery = ''; }}
						class="rounded-md border border-border px-4 py-2 text-sm text-muted transition hover:bg-surface-2 hover:text-text"
					>
						Cancel
					</button>
				</div>
			</div>
			{#if addError}
				<p class="mt-2 text-xs text-danger">{addError}</p>
			{/if}
			{#if addSummary}
				<p class="mt-2 text-xs text-success">{addSummary}</p>
			{/if}
		</div>
	{/if}

	<!-- Source filter tabs -->
	{#if sources.length > 1}
		<div class="mb-4 flex gap-1">
			<button
				onclick={() => (sourceFilter = '')}
				class="rounded-md px-3 py-1.5 text-xs font-medium transition {sourceFilter === '' ? 'bg-accent/15 text-accent' : 'text-muted hover:bg-surface-2 hover:text-text'}"
			>All</button>
			{#each sources as src (src)}
				<button
					onclick={() => (sourceFilter = src)}
					class="rounded-md px-3 py-1.5 text-xs font-medium transition {sourceFilter === src ? 'bg-accent/15 text-accent' : 'text-muted hover:bg-surface-2 hover:text-text'}"
				>{src}</button>
			{/each}
		</div>
	{/if}

	<!-- Stats row -->
	<div class="mb-4 flex items-center gap-4 text-xs text-muted">
		<span>{filtered.length} {filtered.length === 1 ? 'query' : 'queries'}</span>
		<span class="text-success">{activeCount} active</span>
		{#if filtered.length - activeCount > 0}
			<span class="text-warning">{filtered.length - activeCount} paused</span>
		{/if}
		{#if anyRunning}
			<span class="flex items-center gap-1 text-accent">
				<span class="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-accent"></span>
				Running…
			</span>
		{/if}
	</div>

	<!-- Table -->
	{#if filtered.length === 0}
		<div class="flex flex-col items-center justify-center gap-3 rounded-xl border border-border bg-surface py-16 text-center">
			<span class="flex h-12 w-12 items-center justify-center rounded-full bg-surface-2 text-muted">
				<Search size={22} />
			</span>
			<p class="text-sm text-muted">No search queries yet.</p>
			<button
				onclick={() => (showAddForm = true)}
				class="flex items-center gap-1.5 rounded-md bg-accent/15 px-3 py-1.5 text-sm font-medium text-accent transition hover:bg-accent/25"
			>
				<Plus size={14} /> Add your first query
			</button>
		</div>
	{:else}
		<div class="overflow-hidden rounded-xl border border-border bg-surface">
			<table class="w-full text-sm">
				<thead>
					<tr class="border-b border-border text-left">
						<th class="px-4 py-3 text-xs font-medium text-muted">Query</th>
						<th class="px-4 py-3 text-xs font-medium text-muted">Events found</th>
						<th class="px-4 py-3 text-xs font-medium text-muted">Last run</th>
						<th class="px-4 py-3 text-xs font-medium text-muted">Active</th>
						<th class="px-4 py-3 text-xs font-medium text-muted"></th>
					</tr>
				</thead>
				<tbody class="divide-y divide-border">
					{#each filtered as sq (sq.id)}
						{@const running = isRowRunning(sq)}
						<tr class="group transition {running ? 'bg-accent/5' : 'hover:bg-surface-2'}">
							<td class="px-4 py-3 font-medium text-text">{sq.query}</td>
							<td class="px-4 py-3 tabular-nums text-text">{sq.events_found_count.toLocaleString()}</td>
							<td class="px-4 py-3 text-muted">{formatDate(sq.last_run_at)}</td>
							<td class="px-4 py-3">
								<button
									onclick={() => handleToggle(sq)}
									disabled={togglingIds.has(sq.id)}
									title={sq.is_active ? 'Pause this query' : 'Activate this query'}
									class="text-muted transition hover:text-accent disabled:cursor-not-allowed disabled:opacity-50"
								>
									{#if sq.is_active}
										<ToggleRight size={22} class="text-success" />
									{:else}
										<ToggleLeft size={22} />
									{/if}
								</button>
							</td>
							<td class="px-4 py-3">
								<div class="flex items-center gap-2 opacity-0 transition group-hover:opacity-100 {running ? '!opacity-100' : ''}">
									<!-- Run single -->
									<button
										onclick={() => handleRunSingle(sq)}
										disabled={running || !sq.is_active}
										title={!sq.is_active ? 'Activate query to run it' : running ? 'Running…' : 'Run this query'}
										class="flex items-center gap-1 rounded-md border border-border px-2 py-1 text-xs font-medium transition
											{running
												? 'border-accent/40 bg-accent/10 text-accent'
												: 'text-muted hover:border-accent/40 hover:bg-accent/10 hover:text-accent disabled:cursor-not-allowed disabled:opacity-40'}"
									>
										{#if running}
											<span class="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-accent"></span>
											Running…
										{:else}
											<Play size={11} />
											Run
										{/if}
									</button>

									<!-- Delete -->
									<button
										onclick={() => handleDelete(sq)}
										disabled={deletingIds.has(sq.id) || running}
										title="Delete query"
										class="text-muted transition hover:text-danger disabled:cursor-not-allowed disabled:opacity-40"
									>
										<Trash2 size={15} />
									</button>
								</div>
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{/if}
</div>
