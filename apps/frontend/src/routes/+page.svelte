<script lang="ts">
	import BarChart from '$lib/components/BarChart.svelte';
	import DonutChart from '$lib/components/DonutChart.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import StatCard from '$lib/components/StatCard.svelte';
	import { formatDate, titleize } from '$lib/format';
	import type { PageData } from './$types';

	let { data }: { data: PageData } = $props();

	const sourceLabels = $derived(data.bySource.map((r) => titleize(r.source)));
	const sourceData = $derived(data.bySource.map((r) => r.count));
	const catLabels = $derived(data.byCategory.map((r) => r.category));
	const catData = $derived(data.byCategory.map((r) => r.count));
</script>

<svelte:head>
	<title>Dashboard — Veent Admin</title>
</svelte:head>

<PageHeader title="Dashboard" subtitle="Platform overview and key metrics" />

<div class="space-y-6 p-8">
	<!-- Stat cards -->
	<div class="grid grid-cols-1 gap-5 sm:grid-cols-2 xl:grid-cols-4">
		<StatCard label="Total Events" value={data.stats.total_events.toLocaleString()} sub="across all sources" />
		<StatCard label="Active Sources" value={data.stats.active_sources} sub="{data.scrapers.length} scrapers registered" />
		<StatCard
			label="Organizers"
			value={data.stats.total_organizers.toLocaleString()}
			sub="{data.stats.confirmed_organizers} confirmed · {data.stats.pending_organizers} pending"
		/>
		<StatCard
			label="Venues"
			value={data.stats.total_venues.toLocaleString()}
			sub="{data.stats.verified_venues} verified"
		/>
	</div>

	<!-- Charts -->
	<div class="grid grid-cols-1 gap-6 lg:grid-cols-2">
		<div class="rounded-xl border border-border bg-surface p-6">
			<h2 class="text-base font-semibold text-heading">Events by Source</h2>
			<p class="mb-4 text-sm text-muted">All time collected</p>
			{#if sourceData.length}
				<BarChart labels={sourceLabels} data={sourceData} />
			{:else}
				<p class="py-16 text-center text-sm text-muted">No events scraped yet.</p>
			{/if}
		</div>

		<div class="rounded-xl border border-border bg-surface p-6">
			<h2 class="text-base font-semibold text-heading">Events by Category</h2>
			<p class="mb-4 text-sm text-muted">Current database</p>
			{#if catData.length}
				<DonutChart labels={catLabels} data={catData} />
			{:else}
				<p class="py-16 text-center text-sm text-muted">No categorized events yet.</p>
			{/if}
		</div>
	</div>

	<!-- Scraper activity -->
	<div class="rounded-xl border border-border bg-surface p-6">
		<div class="mb-4 flex items-center justify-between">
			<div>
				<h2 class="text-base font-semibold text-heading">Scraper Sources</h2>
				<p class="text-sm text-muted">Registered scrapers and last run</p>
			</div>
			<a href="/scrapers" class="text-sm font-medium text-accent hover:underline">Scraper Center →</a>
		</div>
		<div class="divide-y divide-border">
			{#each data.scrapers as s (s.key)}
				<div class="flex items-center justify-between py-3">
					<div class="flex items-center gap-3">
						<span class="h-2 w-2 rounded-full {s.last_scraped ? 'bg-success' : 'bg-muted'}"></span>
						<span class="font-medium text-heading">{titleize(s.key)}</span>
						<code class="text-xs text-muted">{s.key}</code>
					</div>
					<span class="text-sm text-muted">
						{s.last_scraped ? `Last run ${formatDate(s.last_scraped)}` : 'Never run'}
					</span>
				</div>
			{/each}
		</div>
	</div>
</div>
