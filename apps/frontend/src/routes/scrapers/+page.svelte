<script lang="ts">
	import Badge from '$lib/components/Badge.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import { api, nodeApi } from '$lib/api';
	import { formatDateTime, titleize } from '$lib/format';
	import type { Scraper, ScraperRun, SearchQuery } from '$lib/types';
	import type { PageData } from './$types';

	let { data }: { data: PageData } = $props();

	// svelte-ignore state_referenced_locally
	let proxyEnabled = $state<boolean>(data.proxyEnabled);
	let proxyToggling = $state(false);
	let proxyError = $state<string | null>(null);

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
	// Keys whose log terminal is expanded (collapsed by default).
	let expandedLogs = $state<Set<string>>(new Set());
	let showAllRuns = $state(false);

	// Keyword picker modal state (for scrapers with supports_keywords).
	let keywordPickerKey = $state<string | null>(null);
	let allKeywords = $state<SearchQuery[]>([]);
	let selectedKeywordIds = $state<Set<number>>(new Set());
	let keywordsLoading = $state(false);
	let keywordPickerError = $state<string | null>(null);

	// Two-step picker: step 1 = keyword selection, step 2 = location selection.
	let pickerStep = $state<1 | 2>(1);
	let selectedLocations = $state<Set<string>>(new Set());
	const AVAILABLE_LOCATIONS = ['philippines', 'singapore'];

	// "Run All" in-flight flag.
	let runningAll = $state(false);
	// "Run All" error message, if any.
	let runAllError = $state<string | null>(null);

	// ── Node scraper state (mirrors python state above) ──────────────────────
	let nodeRunningMap = $state<Map<string, ScraperRun>>(new Map());
	let nodeTriggering = $state<Set<string>>(new Set());
	let nodeCancelling = $state<Set<string>>(new Set());
	let nodeErrors = $state<Map<string, string>>(new Map());
	let nodeRunningAll = $state(false);
	let nodeRunAllError = $state<string | null>(null);

	// "Deduplicate" in-flight flag and result/error messages.
	let deduplicating = $state(false);
	let dedupError = $state<string | null>(null);
	let dedupOutput = $state<string | null>(null);

	// AI script buttons — fire-and-forget; show "Started" confirmation briefly.
	let scriptRunning = $state<Record<string, boolean>>({});
	let scriptError = $state<Record<string, string | null>>({});
	let scriptStarted = $state<Record<string, boolean>>({});

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
			const [active, nodeActive] = await Promise.allSettled([
				api.activeRuns(),
				nodeApi.activeRuns()
			]);

			if (active.status === 'fulfilled') {
				const next = new Map<string, ScraperRun>();
				for (const run of active.value) next.set(run.scraper_key, run);
				runningMap = next;
				if (active.value.length === 0 && (nodeActive.status !== 'fulfilled' || nodeActive.value.length === 0) && pollingInterval !== null) {
					stopPolling();
					[recentRuns, scrapers] = await Promise.all([api.scraperRuns(), api.scrapers()]);
				}
			}

			if (nodeActive.status === 'fulfilled') {
				const next = new Map<string, ScraperRun>();
				for (const run of nodeActive.value) next.set(run.scraper_key, run);
				nodeRunningMap = next;
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

	async function openKeywordPicker(key: string) {
		keywordPickerKey = key;
		selectedKeywordIds = new Set();
		pickerStep = 1;
		selectedLocations = new Set();
		keywordPickerError = null;
		keywordsLoading = true;
		try {
			allKeywords = await api.searchQueries();
		} catch (e) {
			keywordPickerError = e instanceof Error ? e.message : 'Failed to load keywords';
		} finally {
			keywordsLoading = false;
		}
	}

	function closeKeywordPicker() {
		keywordPickerKey = null;
		allKeywords = [];
		selectedKeywordIds = new Set();
		pickerStep = 1;
		selectedLocations = new Set();
		keywordPickerError = null;
	}

	function toggleKeyword(id: number) {
		const next = new Set(selectedKeywordIds);
		if (next.has(id)) next.delete(id);
		else next.add(id);
		selectedKeywordIds = next;
	}

	function selectAllKeywordsThenNext() {
		const ids = allKeywords.filter((k) => k.is_active).map((k) => k.id);
		selectedKeywordIds = new Set(ids);
		pickerStep = 2;
	}

	async function handleRunFinal(key: string, overrideIds?: number[]) {
		const ids = overrideIds ?? [...selectedKeywordIds];
		if (ids.length === 0) return;
		if (triggering.has(key) || runningMap.has(key)) return;
		const locs = [...selectedLocations];
		triggering = new Set([...triggering, key]);
		errors = new Map([...errors].filter(([k]) => k !== key));
		closeKeywordPicker();
		try {
			await api.runScraper(key, {
				query_ids: ids,
				...(locs.length > 0 ? { locations: locs } : {})
			});
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

	function toggleLog(key: string) {
		const next = new Set(expandedLogs);
		if (next.has(key)) next.delete(key);
		else next.add(key);
		expandedLogs = next;
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
		const total = Math.round(seconds);
		if (total < 60) return `${total}s`;
		const m = Math.floor(total / 60);
		const s = total % 60;
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

	async function handleNodeRun(key: string) {
		if (nodeTriggering.has(key) || nodeRunningMap.has(key)) return;
		nodeTriggering = new Set([...nodeTriggering, key]);
		nodeErrors = new Map([...nodeErrors].filter(([k]) => k !== key));
		try {
			await nodeApi.runScraper(key);
			await pollActive();
			startPolling();
		} catch (e) {
			const msg = e instanceof Error ? e.message : 'Failed to start node run';
			nodeErrors = new Map([...nodeErrors, [key, msg]]);
		} finally {
			nodeTriggering = new Set([...nodeTriggering].filter((k) => k !== key));
		}
	}

	async function handleNodeCancel(key: string, runId: number) {
		if (nodeCancelling.has(key)) return;
		nodeCancelling = new Set([...nodeCancelling, key]);
		nodeErrors = new Map([...nodeErrors].filter(([k]) => k !== key));
		try {
			await nodeApi.cancelRun(runId);
			await pollActive();
		} catch (e) {
			const msg = e instanceof Error ? e.message : 'Failed to cancel node run';
			nodeErrors = new Map([...nodeErrors, [key, msg]]);
		} finally {
			nodeCancelling = new Set([...nodeCancelling].filter((k) => k !== key));
		}
	}

	async function handleNodeRunAll() {
		if (nodeRunningAll) return;
		nodeRunningAll = true;
		nodeRunAllError = null;
		try {
			await nodeApi.runAll();
			await pollActive();
			startPolling();
		} catch (e) {
			nodeRunAllError = e instanceof Error ? e.message : 'Failed to trigger all node scrapers';
		} finally {
			nodeRunningAll = false;
		}
	}

	async function handleScript(scriptName: string) {
		if (scriptRunning[scriptName]) return;
		scriptRunning = { ...scriptRunning, [scriptName]: true };
		scriptError = { ...scriptError, [scriptName]: null };
		scriptStarted = { ...scriptStarted, [scriptName]: false };
		try {
			await api.runScript(scriptName);
			scriptStarted = { ...scriptStarted, [scriptName]: true };
			setTimeout(() => {
				scriptStarted = { ...scriptStarted, [scriptName]: false };
			}, 4000);
		} catch (e) {
			scriptError = {
				...scriptError,
				[scriptName]: e instanceof Error ? e.message : 'Failed to start'
			};
		} finally {
			scriptRunning = { ...scriptRunning, [scriptName]: false };
		}
	}

	async function handleProxyToggle() {
		if (proxyToggling) return;
		proxyToggling = true;
		proxyError = null;
		try {
			const result = await api.setProxySetting(!proxyEnabled);
			proxyEnabled = result.enabled;
		} catch (e) {
			proxyError = e instanceof Error ? e.message : 'Failed to toggle proxy';
		} finally {
			proxyToggling = false;
		}
	}

	async function handleDedup() {
		if (deduplicating) return;
		deduplicating = true;
		dedupError = null;
		dedupOutput = null;
		try {
			const result = await api.deduplicate();
			dedupOutput = result.output;
		} catch (e) {
			dedupError = e instanceof Error ? e.message : 'Dedup failed';
		} finally {
			deduplicating = false;
		}
	}

	$effect(() => {
		// Kick off an initial poll on mount; only keep polling if something is active.
		pollActive().then(() => {
			if (runningMap.size > 0 || nodeRunningMap.size > 0) startPolling();
		});
		return () => stopPolling();
	});

	// Auto-scroll action: keeps <pre> pinned to the bottom as log lines arrive.
	function autoscroll(node: HTMLElement) {
		const obs = new MutationObserver(() => { node.scrollTop = node.scrollHeight; });
		obs.observe(node, { childList: true, subtree: true, characterData: true });
		node.scrollTop = node.scrollHeight;
		return { destroy() { obs.disconnect(); } };
	}

	// Show only the last 30 lines in the card to keep it compact.
	function trimLog(raw: string | null): string {
		if (!raw) return '';
		return raw.split('\n').filter(Boolean).slice(-30).join('\n');
	}
</script>

<svelte:head>
	<title>Scrapers — Veent Admin</title>
</svelte:head>

<PageHeader title="Scraper Center" subtitle="Trigger runs and review run history">
	{#snippet action()}
		<div class="flex flex-col items-end gap-1">
			<div class="flex items-center gap-2">
				<button
					disabled={proxyToggling}
					onclick={handleProxyToggle}
					class="flex items-center gap-2 rounded-md border px-3 py-2 text-sm font-medium transition
						{proxyEnabled
							? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20'
							: 'border-border bg-surface-2 text-muted hover:bg-surface'}"
					title="Toggle rotating proxy for all scrapers"
				>
					<span class="relative flex h-4 w-4 shrink-0 items-center justify-center">
						{#if proxyEnabled}
							<span class="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-50"></span>
							<span class="relative inline-flex h-2.5 w-2.5 rounded-full bg-emerald-400"></span>
						{:else}
							<span class="inline-flex h-2.5 w-2.5 rounded-full bg-muted/50"></span>
						{/if}
					</span>
					{proxyToggling ? 'Updating…' : proxyEnabled ? 'Proxy On' : 'Proxy Off'}
				</button>
				<button
					disabled={scriptRunning['categorize-events']}
					onclick={() => handleScript('categorize-events')}
					class="rounded-md bg-violet-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-violet-500 disabled:cursor-not-allowed disabled:opacity-50"
				>
					{scriptRunning['categorize-events'] ? 'Starting…' : scriptStarted['categorize-events'] ? 'Started ✓' : 'Categorize Events'}
				</button>
				<button
					disabled={scriptRunning['classify-venues']}
					onclick={() => handleScript('classify-venues')}
					class="rounded-md bg-violet-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-violet-500 disabled:cursor-not-allowed disabled:opacity-50"
				>
					{scriptRunning['classify-venues'] ? 'Starting…' : scriptStarted['classify-venues'] ? 'Started ✓' : 'Classify Venues'}
				</button>
				<button
					disabled={deduplicating}
					onclick={handleDedup}
					class="rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-50"
				>
					{deduplicating ? 'Deduplicating…' : 'Deduplicate'}
				</button>
				<button
					disabled={runningAll}
					onclick={handleRunAll}
					class="rounded-md bg-accent px-4 py-2 text-sm font-medium text-white transition hover:bg-accent/90 disabled:cursor-not-allowed disabled:opacity-50"
				>
					{runningAll ? 'Running…' : 'Run All Python'}
				</button>
				<button
					disabled={nodeRunningAll}
					onclick={handleNodeRunAll}
					class="rounded-md bg-sky-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-sky-500 disabled:cursor-not-allowed disabled:opacity-50"
				>
					{nodeRunningAll ? 'Running…' : 'Run All Node'}
				</button>
			</div>
			{#if scriptError['categorize-events']}
				<span class="text-xs text-danger">{scriptError['categorize-events']}</span>
			{/if}
			{#if scriptError['classify-venues']}
				<span class="text-xs text-danger">{scriptError['classify-venues']}</span>
			{/if}
			{#if dedupError}
				<span class="text-xs text-danger">{dedupError}</span>
			{/if}
			{#if dedupOutput}
				<span class="text-xs whitespace-pre text-green-600">{dedupOutput}</span>
			{/if}
			{#if runAllError}
				<span class="text-xs text-danger">{runAllError}</span>
			{/if}
			{#if nodeRunAllError}
				<span class="text-xs text-danger">{nodeRunAllError}</span>
			{/if}
			{#if proxyError}
				<span class="text-xs text-danger">{proxyError}</span>
			{/if}
		</div>
	{/snippet}
</PageHeader>

<div class="space-y-6 p-8">
	<div class="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
		{#each scrapers as s (s.key)}
			{@const activeRun = runningMap.get(s.key) ?? null}
			{@const isActive = activeRun?.status === 'queued' || activeRun?.status === 'running'}
			{@const run = activeRun ?? recentRuns.find((r) => r.scraper_key === s.key) ?? null}
			{@const nodeActiveRun = nodeRunningMap.get(s.key) ?? null}
			{@const nodeIsActive = nodeActiveRun?.status === 'queued' || nodeActiveRun?.status === 'running'}
			<div class="rounded-xl border border-border bg-surface p-5">
				<div class="flex items-start justify-between">
					<div class="flex items-center gap-2">
						<span
							class="h-2.5 w-2.5 rounded-full {s.last_run ? 'bg-success' : 'bg-muted'}"
						></span>
						<h3 class="font-semibold text-heading">{titleize(s.key)}</h3>
						{#if isActive || nodeIsActive}
							<span
								class="h-3.5 w-3.5 animate-spin rounded-full border-2 border-accent border-t-transparent"
								aria-label="Running"
							></span>
						{/if}
					</div>
					<div class="flex flex-wrap gap-1.5">
						<!-- Python run button -->
						<button
							disabled={isActive || triggering.has(s.key)}
							onclick={() => (s.supports_keywords ? openKeywordPicker(s.key) : handleRun(s.key))}
							class="rounded-md border border-border px-2.5 py-1 text-xs text-text transition hover:bg-surface-2 disabled:cursor-not-allowed disabled:opacity-50"
						>
							{triggering.has(s.key) ? 'Starting…' : 'Run Python'}
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
						<!-- Node run button -->
						<button
							disabled={nodeIsActive || nodeTriggering.has(s.key)}
							onclick={() => handleNodeRun(s.key)}
							class="rounded-md border border-sky-500/40 bg-sky-500/10 px-2.5 py-1 text-xs text-sky-400 transition hover:bg-sky-500/20 disabled:cursor-not-allowed disabled:opacity-50"
						>
							{nodeTriggering.has(s.key) ? 'Starting…' : 'Run Node'}
						</button>
						{#if nodeIsActive && nodeActiveRun}
							<button
								disabled={nodeCancelling.has(s.key)}
								onclick={() => handleNodeCancel(s.key, nodeActiveRun.id)}
								class="rounded-md border border-danger/40 bg-danger-bg/40 px-2.5 py-1 text-xs text-danger transition hover:bg-danger-bg disabled:cursor-not-allowed disabled:opacity-50"
							>
								{nodeCancelling.has(s.key) ? 'Cancelling…' : 'Cancel'}
							</button>
						{/if}
					</div>
				</div>
				<code class="mt-1 block text-xs text-muted">{s.key}</code>

				{#if run}
					<div class="mt-3 flex items-center gap-2">
						<Badge status={run.status} />
						{#if run.status === 'failed' && run.error_message}
							<button
								onclick={() => toggleError(s.key)}
								class="text-xs text-danger/70 hover:text-danger transition"
								title={expandedErrors.has(s.key) ? 'Hide error' : 'Show error'}
							>
								{expandedErrors.has(s.key) ? '− error' : '+ error'}
							</button>
						{/if}
						{#if run.log_output && (isActive || run.status === 'success' || run.status === 'failed')}
							<button
								onclick={() => toggleLog(s.key)}
								class="text-xs text-muted hover:text-text transition"
								title={expandedLogs.has(s.key) ? 'Hide logs' : 'Show logs'}
							>
								{expandedLogs.has(s.key) ? '− logs' : '+ logs'}
							</button>
						{/if}
					</div>
				{/if}

				{#if run?.status === 'success'}
					<div class="mt-2 text-xs text-muted">
						{run.created_count} created, {run.updated_count} updated{#if run.extra_counts.organizers_created !== undefined}
							, +{run.extra_counts.organizers_created ?? 0} orgs created{/if}
					</div>
				{/if}

				{#if run?.status === 'failed' && run.error_message && expandedErrors.has(s.key)}
					<div class="mt-2">
						<pre class="h-36 overflow-y-auto whitespace-pre-wrap rounded-md bg-neutral-950 p-2 text-xs leading-relaxed text-danger font-mono">{run.error_message}</pre>
					</div>
				{/if}

				{#if run?.log_output && expandedLogs.has(s.key) && (isActive || run.status === 'success' || run.status === 'failed')}
					<div class="mt-3">
						<pre
							use:autoscroll
							class="h-36 overflow-y-auto rounded-md bg-neutral-950 p-2 text-xs leading-relaxed text-green-400 font-mono whitespace-pre-wrap"
						>{trimLog(run.log_output)}</pre>
					</div>
				{/if}

				{#if errors.has(s.key)}
					<div class="mt-2 text-xs text-danger">{errors.get(s.key)}</div>
				{/if}

				<!-- Node run status (compact) -->
				{#if nodeActiveRun}
					<div class="mt-2 flex items-center gap-1.5">
						<span class="text-xs text-sky-400/70">Node</span>
						<Badge status={nodeActiveRun.status} />
					</div>
				{/if}

				{#if nodeErrors.has(s.key)}
					<div class="mt-1 text-xs text-danger">{nodeErrors.get(s.key)}</div>
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

{#if keywordPickerKey}
	<div
		class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
		role="dialog"
		aria-modal="true"
	>
		<div class="flex max-h-[80vh] w-full max-w-lg flex-col rounded-xl border border-border bg-surface shadow-xl">
			<div class="flex items-center justify-between border-b border-border px-5 py-4">
				<h3 class="font-semibold text-heading">
					{#if pickerStep === 1}
						Select keywords — {titleize(keywordPickerKey)}
					{:else}
						Select locations — {titleize(keywordPickerKey)}
					{/if}
				</h3>
				<button
					onclick={closeKeywordPicker}
					class="text-muted transition hover:text-text"
					aria-label="Close"
				>✕</button>
			</div>

			{#if pickerStep === 1}
				<div class="flex-1 overflow-y-auto px-5 py-4">
					{#if keywordsLoading}
						<div class="flex items-center justify-center py-10">
							<span class="h-6 w-6 animate-spin rounded-full border-2 border-accent border-t-transparent" aria-label="Loading"></span>
						</div>
					{:else if keywordPickerError}
						<p class="text-sm text-danger">{keywordPickerError}</p>
					{:else if allKeywords.length === 0}
						<p class="text-sm text-muted">No keywords found. Add some on the Search Queries page.</p>
					{:else}
						<ul class="space-y-1">
							{#each allKeywords as kw (kw.id)}
								<li>
									<label
										class="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm {kw.is_active ? 'text-text hover:bg-surface-2' : 'text-muted opacity-60'}"
									>
										<input
											type="checkbox"
											disabled={!kw.is_active}
											checked={selectedKeywordIds.has(kw.id)}
											onchange={() => toggleKeyword(kw.id)}
											class="h-4 w-4 rounded border-border"
										/>
										<span class="truncate">{kw.query}</span>
										{#if !kw.is_active}
											<span class="ml-auto text-xs text-muted">inactive</span>
										{/if}
									</label>
								</li>
							{/each}
						</ul>
					{/if}
				</div>

				<div class="flex items-center justify-between gap-2 border-t border-border px-5 py-4">
					<button
						onclick={closeKeywordPicker}
						class="rounded-md border border-border px-3 py-1.5 text-sm text-text transition hover:bg-surface-2"
					>Cancel</button>
					<div class="flex gap-2">
						<button
							disabled={keywordsLoading || allKeywords.filter((k) => k.is_active).length === 0}
							onclick={selectAllKeywordsThenNext}
							class="rounded-md border border-border px-3 py-1.5 text-sm text-text transition hover:bg-surface-2 disabled:cursor-not-allowed disabled:opacity-50"
						>Select All → Next</button>
						<button
							disabled={selectedKeywordIds.size === 0}
							onclick={() => (pickerStep = 2)}
							class="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-white transition hover:bg-accent/90 disabled:cursor-not-allowed disabled:opacity-50"
						>Next →</button>
					</div>
				</div>
			{:else}
				<div class="flex-1 overflow-y-auto px-5 py-4">
					<p class="text-sm font-medium text-heading">Select locations</p>
					<p class="mt-1 text-xs text-muted">Each selected keyword will be searched once per location.</p>
					<div class="mt-4 space-y-2">
						{#each AVAILABLE_LOCATIONS as loc}
							<label class="flex items-center gap-2 text-sm text-text cursor-pointer">
								<input
									type="checkbox"
									checked={selectedLocations.has(loc)}
									onchange={(e) => {
										if (e.currentTarget.checked) selectedLocations.add(loc);
										else selectedLocations.delete(loc);
										selectedLocations = selectedLocations; // trigger reactivity
									}}
									class="accent-accent"
								/>
								<span class="capitalize">{loc}</span>
							</label>
						{/each}
					</div>
					<p class="mt-4 text-xs text-muted">Running {selectedKeywordIds.size} keyword(s)</p>
				</div>

				<div class="flex items-center justify-between gap-2 border-t border-border px-5 py-4">
					<button
						onclick={closeKeywordPicker}
						class="rounded-md border border-border px-3 py-1.5 text-sm text-text transition hover:bg-surface-2"
					>Cancel</button>
					<div class="flex gap-2">
						<button
							onclick={() => (pickerStep = 1)}
							class="rounded-md border border-border px-3 py-1.5 text-sm text-text transition hover:bg-surface-2"
						>← Back</button>
						<button
							onclick={() => handleRunFinal(keywordPickerKey!)}
							class="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-white transition hover:bg-accent/90"
						>Run</button>
					</div>
				</div>
			{/if}
		</div>
	</div>
{/if}
