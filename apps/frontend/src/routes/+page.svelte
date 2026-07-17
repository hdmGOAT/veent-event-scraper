<script lang="ts">
	import PageHeader from '$lib/components/PageHeader.svelte';
	import { formatDateTime, titleize } from '$lib/format';
	import type { PageData } from './$types';
	import type { Scraper } from '$lib/types';

	let { data }: { data: PageData } = $props();

	const SOCIAL_SOURCES = ['facebook_posts', 'instagram_posts', 'facebook_events'];
	const DATAIMPULSE_QUOTA_MB = 2500;

	// Derive session health per social source from last_run.error_message.
	function sessionStatus(scraper: Scraper): 'ok' | 'expired' | 'unknown' {
		if (!scraper.last_run) return 'unknown';
		if (
			scraper.last_run.status === 'failed' &&
			scraper.last_run.error_message?.includes('session_expired:')
		) {
			return 'expired';
		}
		if (scraper.last_run.status === 'success') return 'ok';
		return 'unknown';
	}

	const socialScrapers = $derived(
		data.scrapers.filter((s) => SOCIAL_SOURCES.includes(s.key))
	);

	const bandwidthPct = $derived(
		Math.min(100, Math.round((data.stats.dataimpulse_mb / DATAIMPULSE_QUOTA_MB) * 100))
	);

	// Last run across all scrapers (most recent created_at).
	const lastRun = $derived(data.recentRuns[0] ?? null);
</script>

<svelte:head>
	<title>Dashboard — Veent Scraper</title>
</svelte:head>

<PageHeader title="Dashboard" subtitle="Pipeline health and operational status" />

<div class="space-y-6 p-8">

	<!-- ── Pipeline health strip ───────────────────────────────────────────── -->
	<div class="rounded-xl border border-border bg-surface p-6">
		<h2 class="mb-4 text-base font-semibold text-heading">Pipeline Health</h2>
		<div class="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">

			<!-- Last pipeline run -->
			<div class="rounded-lg border border-border bg-surface-2 p-4">
				<div class="mb-1 text-xs font-medium uppercase tracking-wide text-muted">Last Run</div>
				{#if lastRun}
					<div class="flex items-center gap-2">
						<span class="h-2 w-2 rounded-full {lastRun.status === 'success' ? 'bg-success' : lastRun.status === 'failed' ? 'bg-error' : 'bg-warning'}"></span>
						<span class="text-sm font-medium text-heading capitalize">{lastRun.status}</span>
					</div>
					<div class="mt-1 text-xs text-muted">{titleize(lastRun.scraper_key)}</div>
					<div class="mt-1 text-xs text-muted">{formatDateTime(lastRun.created_at)}</div>
					{#if lastRun.duration_seconds != null}
						<div class="mt-1 text-xs text-muted">{lastRun.duration_seconds.toFixed(0)}s</div>
					{/if}
				{:else}
					<div class="text-sm text-muted">No runs yet</div>
				{/if}
			</div>

			<!-- DataImpulse quota -->
			<div class="rounded-lg border border-border bg-surface-2 p-4">
				<div class="mb-1 text-xs font-medium uppercase tracking-wide text-muted">DataImpulse Quota</div>
				<div class="text-lg font-semibold text-heading">{data.stats.dataimpulse_mb.toLocaleString()} MB</div>
				<div class="text-xs text-muted">of {DATAIMPULSE_QUOTA_MB.toLocaleString()} MB</div>
				<div class="mt-2 h-1.5 w-full rounded-full bg-surface">
					<div
						class="h-1.5 rounded-full transition-all {bandwidthPct > 80 ? 'bg-error' : bandwidthPct > 60 ? 'bg-warning' : 'bg-success'}"
						style="width: {bandwidthPct}%"
					></div>
				</div>
				<div class="mt-1 text-xs text-muted">{bandwidthPct}% used</div>
			</div>

			<!-- Push stats -->
			<div class="rounded-lg border border-border bg-surface-2 p-4">
				<div class="mb-1 text-xs font-medium uppercase tracking-wide text-muted">CRM Push</div>
				<div class="text-lg font-semibold text-heading">{data.stats.pending_push.toLocaleString()}</div>
				<div class="text-xs text-muted">events pending push</div>
				<a href="/scrapers" class="mt-2 block text-xs text-accent hover:underline">Trigger push →</a>
			</div>

			<!-- Data quality -->
			<div class="rounded-lg border border-border bg-surface-2 p-4">
				<div class="mb-1 text-xs font-medium uppercase tracking-wide text-muted">Data Quality</div>
				<div class="flex items-baseline gap-1">
					<span class="text-lg font-semibold text-heading">{data.stats.uncategorized.toLocaleString()}</span>
					<span class="text-xs text-muted">uncategorized</span>
				</div>
				<a href="/scrapers" class="mt-2 block text-xs text-accent hover:underline">Run categorize →</a>
			</div>
		</div>
	</div>

	<!-- ── Session status (social scrapers) ───────────────────────────────── -->
	<div class="rounded-xl border border-border bg-surface p-6">
		<div class="mb-4 flex items-center justify-between">
			<h2 class="text-base font-semibold text-heading">Session Status</h2>
			<a href="/runs?status=failed" class="text-sm font-medium text-accent hover:underline">View failures →</a>
		</div>
		<div class="divide-y divide-border">
			{#each socialScrapers as s (s.key)}
				{@const status = sessionStatus(s)}
				<div class="flex items-center justify-between py-3">
					<div class="flex items-center gap-3">
						{#if status === 'ok'}
							<span class="h-2 w-2 rounded-full bg-success"></span>
						{:else if status === 'expired'}
							<span class="h-2 w-2 rounded-full bg-error"></span>
						{:else}
							<span class="h-2 w-2 rounded-full bg-muted"></span>
						{/if}
						<span class="text-sm font-medium text-heading">{titleize(s.key)}</span>
					</div>
					<div class="text-right">
						{#if status === 'expired'}
							<span class="text-sm font-medium text-error">Session expired</span>
							{#if s.last_run?.finished_at}
								<div class="text-xs text-muted">{formatDateTime(s.last_run.finished_at)}</div>
							{/if}
						{:else if status === 'ok' && s.last_run?.finished_at}
							<span class="text-sm text-success">Active</span>
							<div class="text-xs text-muted">{formatDateTime(s.last_run.finished_at)}</div>
						{:else}
							<span class="text-sm text-muted">No data</span>
						{/if}
					</div>
				</div>
			{/each}
			{#if socialScrapers.length === 0}
				<p class="py-4 text-sm text-muted">No social scraper runs found.</p>
			{/if}
		</div>
	</div>

	<!-- ── Recent pipeline runs ────────────────────────────────────────────── -->
	<div class="rounded-xl border border-border bg-surface p-6">
		<div class="mb-4 flex items-center justify-between">
			<div>
				<h2 class="text-base font-semibold text-heading">Recent Runs</h2>
				<p class="text-sm text-muted">Last 20 scraper runs across all sources</p>
			</div>
			<a href="/runs" class="text-sm font-medium text-accent hover:underline">Full history →</a>
		</div>
		<div class="divide-y divide-border">
			{#each data.recentRuns as run (run.id)}
				<div class="flex items-center gap-4 py-3">
					<span class="h-2 w-2 shrink-0 rounded-full {
						run.status === 'success' ? 'bg-success' :
						run.status === 'failed' ? 'bg-error' :
						run.status === 'running' ? 'bg-warning animate-pulse' :
						'bg-muted'
					}"></span>
					<div class="min-w-0 flex-1">
						<div class="flex items-center gap-2">
							<span class="text-sm font-medium text-heading">{titleize(run.scraper_key)}</span>
							<code class="text-xs text-muted">{run.scraper_key}</code>
						</div>
						{#if run.status === 'failed' && run.error_message}
							<div class="mt-0.5 truncate text-xs text-error">
								{run.error_message.split('\n').pop() ?? run.error_message}
							</div>
						{/if}
					</div>
					<div class="shrink-0 text-right text-xs text-muted">
						<div class="capitalize {run.status === 'success' ? 'text-success' : run.status === 'failed' ? 'text-error' : ''}">{run.status}</div>
						<div>{formatDateTime(run.created_at)}</div>
					</div>
				</div>
			{:else}
				<p class="py-4 text-sm text-muted">No runs yet.</p>
			{/each}
		</div>
	</div>

</div>
