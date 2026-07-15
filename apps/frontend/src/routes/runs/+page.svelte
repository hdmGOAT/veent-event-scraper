<script lang="ts">
	import PageHeader from '$lib/components/PageHeader.svelte';
	import { api } from '$lib/api';
	import { formatDateTime, titleize } from '$lib/format';
	import type { ScraperRun } from '$lib/types';
	import type { PageData } from './$types';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';

	let { data }: { data: PageData } = $props();

	let runs = $state<ScraperRun[]>(data.runs);
	let statusFilter = $state(data.statusFilter);
	let expandedIds = $state<Set<number>>(new Set());
	let loadingLogIds = $state<Set<number>>(new Set());
	let logCache = $state<Map<number, string>>(new Map());

	const STATUS_OPTIONS = [
		{ value: '', label: 'All' },
		{ value: 'success', label: 'Success' },
		{ value: 'failed', label: 'Failed' },
		{ value: 'running', label: 'Running' },
		{ value: 'cancelled', label: 'Cancelled' },
	];

	function statusColor(status: string) {
		return status === 'success' ? 'text-success' :
			status === 'failed' ? 'text-error' :
			status === 'running' ? 'text-warning' :
			'text-muted';
	}

	function statusDot(status: string) {
		return status === 'success' ? 'bg-success' :
			status === 'failed' ? 'bg-error' :
			status === 'running' ? 'bg-warning animate-pulse' :
			'bg-muted';
	}

	function duration(run: ScraperRun): string {
		if (run.duration_seconds == null) return '—';
		const s = run.duration_seconds;
		if (s < 60) return `${s.toFixed(0)}s`;
		return `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`;
	}

	function isSessionExpired(run: ScraperRun): boolean {
		return run.status === 'failed' && (run.error_message ?? '').includes('session_expired:');
	}

	function lastErrorLine(msg: string): string {
		const lines = msg.trim().split('\n').filter(Boolean);
		return lines[lines.length - 1] ?? msg;
	}

	async function toggleLog(run: ScraperRun) {
		if (expandedIds.has(run.id)) {
			expandedIds.delete(run.id);
			expandedIds = new Set(expandedIds);
			return;
		}
		expandedIds.add(run.id);
		expandedIds = new Set(expandedIds);

		if (!logCache.has(run.id)) {
			loadingLogIds.add(run.id);
			loadingLogIds = new Set(loadingLogIds);
			try {
				const detail = await api.scraperRun(run.id);
				logCache.set(run.id, detail.log_output ?? '(no log output)');
				logCache = new Map(logCache);
			} finally {
				loadingLogIds.delete(run.id);
				loadingLogIds = new Set(loadingLogIds);
			}
		}
	}

	async function applyFilter(newStatus: string) {
		statusFilter = newStatus;
		const params = new URLSearchParams(page.url.searchParams);
		if (newStatus) params.set('status', newStatus);
		else params.delete('status');
		await goto(`?${params.toString()}`, { replaceState: true });
		runs = await api.scraperRuns({ limit: 100, status: newStatus || undefined });
	}
</script>

<svelte:head>
	<title>Pipeline Runs — Veent Scraper</title>
</svelte:head>

<PageHeader title="Pipeline Runs" subtitle="Full scraper run history with logs" />

<div class="p-8 space-y-4">

	<!-- Filter bar -->
	<div class="flex flex-wrap gap-2">
		{#each STATUS_OPTIONS as opt (opt.value)}
			<button
				type="button"
				onclick={() => applyFilter(opt.value)}
				class="rounded-full px-3 py-1 text-sm font-medium transition-colors {statusFilter === opt.value
					? 'bg-accent text-white'
					: 'bg-surface-2 text-muted hover:text-text'}"
			>
				{opt.label}
			</button>
		{/each}
	</div>

	<!-- Run list -->
	<div class="rounded-xl border border-border bg-surface overflow-hidden">
		{#if runs.length === 0}
			<p class="py-12 text-center text-sm text-muted">No runs found.</p>
		{/if}

		{#each runs as run (run.id)}
			{@const expanded = expandedIds.has(run.id)}
			{@const loadingLog = loadingLogIds.has(run.id)}
			{@const sessionExpired = isSessionExpired(run)}

			<div class="border-b border-border last:border-b-0">
				<!-- Row -->
				<button
					type="button"
					onclick={() => toggleLog(run)}
					class="flex w-full items-start gap-4 px-6 py-4 text-left hover:bg-surface-2 transition-colors"
				>
					<span class="mt-1.5 h-2 w-2 shrink-0 rounded-full {statusDot(run.status)}"></span>

					<div class="min-w-0 flex-1">
						<div class="flex flex-wrap items-center gap-x-3 gap-y-1">
							<span class="font-medium text-heading">{titleize(run.scraper_key)}</span>
							<code class="text-xs text-muted">{run.scraper_key}</code>
							{#if sessionExpired}
								<span class="rounded-full bg-error/10 px-2 py-0.5 text-xs font-medium text-error">Session Expired</span>
							{/if}
						</div>

						<div class="mt-1 flex flex-wrap gap-x-4 gap-y-0.5 text-xs text-muted">
							<span class="{statusColor(run.status)} font-medium capitalize">{run.status}</span>
							<span>{formatDateTime(run.created_at)}</span>
							<span>{duration(run)}</span>
							{#if run.created_count || run.updated_count}
								<span>+{run.created_count} created · {run.updated_count} updated</span>
							{/if}
						</div>

						{#if run.status === 'failed' && run.error_message && !sessionExpired}
							<div class="mt-1 text-xs text-error font-mono truncate">
								{lastErrorLine(run.error_message)}
							</div>
						{/if}
						{#if sessionExpired}
							<div class="mt-1 text-xs text-error">
								Cookies expired — update {run.scraper_key.includes('instagram') ? 'IG' : 'FB'} session cookies and re-run.
							</div>
						{/if}
					</div>

					<span class="shrink-0 text-xs text-muted mt-1">{expanded ? '▲' : '▼'}</span>
				</button>

				<!-- Expandable log -->
				{#if expanded}
					<div class="border-t border-border bg-black/60 px-6 py-4">
						{#if loadingLog}
							<p class="text-xs text-muted">Loading logs…</p>
						{:else if run.status === 'failed' && run.error_message}
							<div class="mb-4">
								<div class="mb-1 text-xs font-medium uppercase tracking-wide text-error">Error</div>
								<pre class="whitespace-pre-wrap font-mono text-xs text-error/90 leading-relaxed">{run.error_message}</pre>
							</div>
						{/if}
						{#if logCache.has(run.id)}
							<div class="mb-1 text-xs font-medium uppercase tracking-wide text-muted">Log Output</div>
							<pre class="max-h-96 overflow-y-auto whitespace-pre-wrap font-mono text-xs text-text/80 leading-relaxed">{logCache.get(run.id)}</pre>
						{:else if !loadingLog}
							<p class="text-xs text-muted">(no log output captured)</p>
						{/if}
					</div>
				{/if}
			</div>
		{/each}
	</div>
</div>
