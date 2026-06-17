<script lang="ts">
	import { api } from '$lib/api';
	import Badge from '$lib/components/Badge.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import type { Organizer, Paginated } from '$lib/types';

	const tabs = [
		{ label: 'All', value: '' },
		{ label: 'Pending', value: 'pending' },
		{ label: 'Confirmed', value: 'confirmed' },
		{ label: 'Rejected', value: 'rejected' }
	];

	let q = $state('');
	let status = $state('');
	let page = $state(1);
	let data = $state<Paginated<Organizer> | null>(null);
	let loading = $state(true);
	let error = $state('');

	let timer: ReturnType<typeof setTimeout>;
	function onSearch(value: string) {
		clearTimeout(timer);
		timer = setTimeout(() => {
			page = 1;
			q = value;
		}, 300);
	}

	function setStatus(value: string) {
		page = 1;
		status = value;
	}

	$effect(() => {
		const _q = q;
		const _status = status;
		const _page = page;
		loading = true;
		error = '';
		api
			.organizers({ q: _q, status: _status, page: _page })
			.then((r) => (data = r))
			.catch((e) => (error = String(e)))
			.finally(() => (loading = false));
	});
</script>

<PageHeader title="Organizers" subtitle="Event organizers and their contact details" />

<div class="space-y-5 p-8">
	<div class="flex flex-wrap items-center justify-between gap-4">
		<!-- Status tabs -->
		<div class="flex gap-1 rounded-lg border border-border bg-surface p-1">
			{#each tabs as tab (tab.value)}
				<button
					onclick={() => setStatus(tab.value)}
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
			placeholder="Search by name, city, or email…"
			oninput={(e) => onSearch(e.currentTarget.value)}
			class="w-full max-w-xs rounded-lg border border-border bg-surface px-4 py-2 text-sm text-text placeholder:text-muted focus:border-accent focus:outline-none"
		/>
	</div>

	{#if error}
		<p class="rounded-lg border border-danger/40 bg-danger-bg/40 px-4 py-3 text-sm text-danger">
			Failed to load organizers: {error}
		</p>
	{/if}

	{#if loading && !data}
		<p class="py-10 text-center text-muted">Loading…</p>
	{:else if data && data.results.length === 0}
		<p class="py-10 text-center text-muted">No organizers found.</p>
	{:else if data}
		<div class="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
			{#each data.results as o (o.slug)}
				<a
					href="/organizers/{o.slug}"
					class="group block rounded-xl border border-border bg-surface p-5 transition-colors hover:border-accent/50"
				>
					<div class="flex items-start justify-between gap-3">
						<h3 class="font-semibold text-heading group-hover:text-accent">{o.name}</h3>
						<Badge status={o.status} />
					</div>
					{#if o.city || o.country}
						<p class="mt-1 text-sm text-muted">{[o.city, o.country].filter(Boolean).join(', ')}</p>
					{/if}

					<div class="mt-4 space-y-1.5 text-sm">
						{#if o.email}
							<div class="flex items-center gap-2 text-muted">
								<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="4" width="20" height="16" rx="2" /><path d="m22 7-10 5L2 7" /></svg>
								<span class="truncate">{o.email}</span>
							</div>
						{/if}
						{#if o.phone}
							<div class="flex items-center gap-2 text-muted">
								<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z" /></svg>
								<span class="truncate">{o.phone}</span>
							</div>
						{/if}
					</div>

					<div class="mt-4 flex items-center gap-3 text-muted">
						{#if o.website}
							<span title="Has website" class="text-accent">
								<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10" /><line x1="2" y1="12" x2="22" y2="12" /><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" /></svg>
							</span>
						{/if}
						{#if o.facebook_url}
							<span title="Facebook"><svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M22 12a10 10 0 1 0-11.56 9.88v-6.99H7.9V12h2.54V9.8c0-2.5 1.49-3.89 3.78-3.89 1.09 0 2.24.2 2.24.2v2.46h-1.26c-1.24 0-1.63.77-1.63 1.56V12h2.78l-.44 2.89h-2.34v6.99A10 10 0 0 0 22 12z" /></svg></span>
						{/if}
						{#if o.instagram_url}
							<span title="Instagram"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="2" width="20" height="20" rx="5" /><path d="M16 11.37A4 4 0 1 1 12.63 8 4 4 0 0 1 16 11.37z" /><line x1="17.5" y1="6.5" x2="17.51" y2="6.5" /></svg></span>
						{/if}
						{#if !o.website && !o.facebook_url && !o.instagram_url && !o.email && !o.phone}
							<span class="text-xs italic">No contact details</span>
						{/if}
					</div>
				</a>
			{/each}
		</div>

		{#if data.pages > 1}
			<div class="flex items-center justify-between text-sm text-muted">
				<span>{data.total.toLocaleString()} organizers · page {data.page} of {data.pages}</span>
				<div class="flex gap-2">
					<button class="rounded-lg border border-border px-3 py-1.5 enabled:hover:bg-surface-2 disabled:opacity-40" disabled={page <= 1} onclick={() => (page -= 1)}>Previous</button>
					<button class="rounded-lg border border-border px-3 py-1.5 enabled:hover:bg-surface-2 disabled:opacity-40" disabled={page >= data.pages} onclick={() => (page += 1)}>Next</button>
				</div>
			</div>
		{/if}
	{/if}
</div>
