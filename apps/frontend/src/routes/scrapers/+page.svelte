<script lang="ts">
	import PageHeader from '$lib/components/PageHeader.svelte';
	import { formatDateTime, titleize } from '$lib/format';
	import type { PageData } from './$types';

	let { data }: { data: PageData } = $props();
</script>

<PageHeader title="Scraper Center" subtitle="Registered data sources and their last run" />

<div class="space-y-5 p-8">
	<p class="rounded-lg border border-border bg-surface-2/40 px-4 py-3 text-sm text-muted">
		Scrapers run via the <code class="text-text">manage.py scrape &lt;source&gt;</code> command (OS cron / manual). Triggering runs from the UI is not wired up yet.
	</p>

	<div class="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
		{#each data.scrapers as s (s.key)}
			<div class="rounded-xl border border-border bg-surface p-5">
				<div class="flex items-start justify-between">
					<div class="flex items-center gap-2">
						<span class="h-2.5 w-2.5 rounded-full {s.last_scraped ? 'bg-success' : 'bg-muted'}"></span>
						<h3 class="font-semibold text-heading">{titleize(s.key)}</h3>
					</div>
					<button
						disabled
						title="Run from UI not yet supported"
						class="cursor-not-allowed rounded-md border border-border px-2.5 py-1 text-xs text-muted opacity-50"
					>
						Run
					</button>
				</div>
				<code class="mt-1 block text-xs text-muted">{s.key}</code>
				<div class="mt-4 text-sm text-muted">
					{s.last_scraped ? `Last run: ${formatDateTime(s.last_scraped)}` : 'Never run'}
				</div>
			</div>
		{/each}
	</div>
</div>
