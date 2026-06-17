<script lang="ts">
	import Badge from '$lib/components/Badge.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import { api } from '$lib/api';
	import { formatDateTime, titleize } from '$lib/format';
	import type { Scraper, ScraperRun } from '$lib/types';
	import type { PageData } from './$types';

	let { data }: { data: PageData } = $props();

	// Local copy of the scraper list so we can refresh each card's last_run
	// after a run finishes, without a manual page reload. Seeded once from the
	// SSR load; subsequent updates come from api.scrapers() polling.
	// svelte-ignore state_referenced_locally
	let scrapers = $state<Scraper[]>(data.scrapers);
	// scraper_key -> active (queued/running) run, refreshed by polling.
	let runningMap = $state<Map<string, ScraperRun>>(new Map());
	// svelte-ignore state_referenced_locally
	let recentRuns = $state<ScraperRun[]>(data.recentRuns);
	// Keys currently being POST-triggered (before the response lands).
	let triggering = $state<Set<string>>(new Set());
	// Keys currently being cancelled (before the response lands).
	let cancelling = $state<Set<string>>(new Set());
	// Per-key trigger error messages.
	let errors = $state<Map<string, string>>(new Map());
	// Keys whose failure traceback is expanded.
	let expandedErrors = $state<Set<string>>(new Set());
	let showAllRuns = $state(false);

	// "Run All" in-flight flag.
	let runningAll = $state(false);
	// "Run All" error message, if any.
	let runAllError = $state<string | null>(null);

	let pollingInterval: ReturnType<typeof setInterval> | null = null;

	function startPolling() {
		if (pollingInterval === null) {
			pollingInterval = setInterval(pollActive, 2500);
		}
	}

	function stopPolling() {
		if (pollingInterval !== null) {
			clearInterval(pollingInterval);
			pollingInterval = null;
		}
	}

	async function pollActive() {
		try {
			const active = await api.activeRuns();
			const next = new Map<string, ScraperRun>();
			for (const run of active) {
				next.set(run.scraper_key, run);
			}
			runningMap = next;
			if (active.length === 0 && pollingInterval !== null) {
				stopPolling();
				// Pick up runs that just finished: refresh both the history table
				// and the per-card last_run line.
				[recentRuns, scrapers] = await Promise.all([api.scraperRuns(), api.scrapers()]);
			}
		} catch (e) {
			// Transient poll failure — leave state untouched, try again next tick.
			console.error('Failed to poll active runs', e);
		}
	}

	async function handleRun(key: string) {
		if (triggering.has(key) || runningMap.has(key)) return;
		triggering = new Set([...triggering, key]);
		errors = new Map([...errors].filter(([k]) => k !== key));
		try {
			await api.runScraper(key);
			await pollActive();
			startPolling();
		} catch (e) {
			const msg = e instanceof Error ? e.message : 'Failed to start run';
			errors = new Map([...errors, [key, msg]]);
		} finally {
			triggering = new Set([...triggering].filter((k) => k !== key));
		}
	}

	async function handleCancel(key: string, runId: number) {
		if (cancelling.has(key)) return;
		cancelling = new Set([...cancelling, key]);
		errors = new Map([...errors].filter(([k]) => k !== key));
		try {
			await api.cancelRun(runId);
			await pollActive();
		} catch (e) {
			const msg = e instanceof Error ? e.message : 'Failed to cancel run';
			errors = new Map([...errors, [key, msg]]);
		} finally {
			cancelling = new Set([...cancelling].filter((k) => k !== key));
		}
	}

	function toggleError(key: string) {
		const next = new Set(expandedErrors);
		if (next.has(key)) next.delete(key);
		else next.add(key);
		expandedErrors = next;
	}

	// Last-run line for a card, sourced from the ScraperRun history (last_run),
	// not the stale event-derived last_scraped. An active poll run takes
	// precedence over this and is rendered separately above.
	function lastRunLabel(s: Scraper): string {
		const lr = s.last_run;
		if (!lr) return 'Never run';
		const ts = lr.finished_at ?? lr.started_at;
		const when = ts ? formatDateTime(ts) : '—';
		return `Last run: ${when} · ${titleize(lr.status)}`;
	}

	function formatDuration(seconds: number | null): string {
		if (seconds === null) return '—';
		if (seconds < 1) return '<1s';
		if (seconds < 60) return `${Math.round(seconds)}s`;
		const m = Math.floor(seconds / 60);
		const s = Math.round(seconds % 60);
		return `${m}m ${s}s`;
	}

	async function handleRunAll() {
		if (runningAll) return;
		runningAll = true;
		runAllError = null;
		try {
			await api.runAll();
			await pollActive();
			startPolling();
		} catch (e) {
			runAllError = e instanceof Error ? e.message : 'Failed to trigger all scrapers';
		} finally {
			runningAll = false;
		}
	}

	$effect(() => {
		// Kick off an initial poll on mount; only keep polling if something is active.
		pollActive().then(() => {
			if (runningMap.size > 0) startPolling();
		});
		return () => stopPolling();
	});
</script>

<PageHeader title="Scraper Center" subtitle="Trigger runs and review run history">
	{#snippet action()}
		<div class="flex flex-col items-end gap-1">
			<button
				disabled={runningAll}
				onclick={handleRunAll}
				class="rounded-md bg-accent px-4 py-2 text-sm font-medium text-white transition hover:bg-accent/90 disabled:cursor-not-allowed disabled:opacity-50"
			>
				{runningAll ? 'Running All…' : 'Run All'}
			</button>
			{#if runAllError}
				<span class="text-xs text-danger">{runAllError}</span>
			{/if}
		</div>
	{/snippet}
</PageHeader>

<div class="space-y-6 p-8">
	<div class="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
		{#each scrapers as s (s.key)}
			{@const run = runningMap.get(s.key) ?? null}
			{@const isActive = run?.status === 'queued' || run?.status === 'running'}
			<div class="rounded-xl border border-border bg-surface p-5">
				<div class="flex items-start justify-between">
					<div class="flex items-center gap-2">
						<span
							class="h-2.5 w-2.5 rounded-full {s.last_run ? 'bg-success' : 'bg-muted'}"
						></span>
						<h3 class="font-semibold text-heading">{titleize(s.key)}</h3>
						{#if isActive}
							<span
								class="h-3.5 w-3.5 animate-spin rounded-full border-2 border-accent border-t-transparent"
								aria-label="Running"
							></span>
						{/if}
					</div>
					<div class="flex gap-2">
						<button
							disabled={isActive || triggering.has(s.key)}
							onclick={() => handleRun(s.key)}
							class="rounded-md border border-border px-2.5 py-1 text-xs text-text transition hover:bg-surface-2 disabled:cursor-not-allowed disabled:opacity-50"
						>
							{triggering.has(s.key) ? 'Starting…' : 'Run'}
						</button>
						{#if isActive && run}
							<button
								disabled={cancelling.has(s.key)}
								onclick={() => handleCancel(s.key, run.id)}
								class="rounded-md border border-danger/40 bg-danger-bg/40 px-2.5 py-1 text-xs text-danger transition hover:bg-danger-bg disabled:cursor-not-allowed disabled:opacity-50"
							>
								{cancelling.has(s.key) ? 'Cancelling…' : 'Cancel'}
							</button>
						{/if}
					</div>
				</div>
				<code class="mt-1 block text-xs text-muted">{s.key}</code>

				{#if run}
					<div class="mt-3">
						<Badge status={run.status} />
					</div>
				{/if}

				{#if run?.status === 'success'}
					<div class="mt-2 text-xs text-muted">
						{run.created_count} created, {run.updated_count} updated{#if run.extra_counts.organizers_created !== undefined}
							, +{run.extra_counts.organizers_created ?? 0} orgs created{/if}
					</div>
				{/if}

				{#if run?.status === 'failed' && run.error_message}
					<div class="mt-2">
						<pre
							class="overflow-x-auto whitespace-pre-wrap rounded-md bg-danger-bg/40 p-2 text-xs text-danger">{expandedErrors.has(
								s.key
							)
								? run.error_message
								: run.error_message.slice(0, 300)}</pre>
						{#if run.error_message.length > 300}
							<button
								class="mt-1 text-xs text-accent hover:underline"
								onclick={() => toggleError(s.key)}
							>
								{expandedErrors.has(s.key) ? 'show less' : 'show full'}
							</button>
						{/if}
					</div>
				{/if}

				{#if errors.has(s.key)}
					<div class="mt-2 text-xs text-danger">{errors.get(s.key)}</div>
				{/if}

				<div class="mt-4 text-sm text-muted">
					{lastRunLabel(s)}
				</div>
			</div>
		{/each}
	</div>

	<section class="space-y-3">
		<div class="flex items-center gap-2">
			<h2 class="text-lg font-semibold text-heading">Recent Runs</h2>
			<span class="rounded-full bg-surface-2 px-2 py-0.5 text-xs text-muted">{recentRuns.length}</span>
		</div>

		{#if recentRuns.length === 0}
			<p class="text-sm text-muted">No runs yet. Trigger a scraper above to get started.</p>
		{:else}
			<div class="overflow-x-auto rounded-xl border border-border">
				<table class="w-full text-left text-sm">
					<thead class="bg-surface-2 text-xs uppercase text-muted">
						<tr>
							<th class="px-4 py-2 font-medium">Scraper</th>
							<th class="px-4 py-2 font-medium">Status</th>
							<th class="px-4 py-2 font-medium">Started</th>
							<th class="px-4 py-2 font-medium">Duration</th>
							<th class="px-4 py-2 font-medium">Created</th>
							<th class="px-4 py-2 font-medium">Updated</th>
						</tr>
					</thead>
					<tbody>
						{#each showAllRuns ? recentRuns : recentRuns.slice(0, 20) as r (r.id)}
							<tr class="border-t border-border">
								<td class="px-4 py-2 text-text">{titleize(r.scraper_key)}</td>
								<td class="px-4 py-2"><Badge status={r.status} /></td>
								<td class="px-4 py-2 text-muted">{formatDateTime(r.started_at)}</td>
								<td class="px-4 py-2 text-muted">{formatDuration(r.duration_seconds)}</td>
								<td class="px-4 py-2 text-muted">{r.created_count}</td>
								<td class="px-4 py-2 text-muted">{r.updated_count}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
			{#if recentRuns.length > 20}
				<button class="text-xs text-accent hover:underline" onclick={() => (showAllRuns = !showAllRuns)}>
					{showAllRuns ? 'show fewer' : `show all ${recentRuns.length}`}
				</button>
			{/if}
		{/if}
	</section>
</div>
