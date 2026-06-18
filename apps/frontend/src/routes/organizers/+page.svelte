<script lang="ts">
	import { Globe } from 'lucide-svelte';
	import { api } from '$lib/api';
	import Badge from '$lib/components/Badge.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import SortHeader from '$lib/components/SortHeader.svelte';
	import TableSkeleton from '$lib/components/TableSkeleton.svelte';
	import type { Organizer, Paginated } from '$lib/types';
	import { sortRows, toggleSort, type SortState } from '$lib/utils/sort';
	import { safeUrl } from '$lib/utils/url';

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

	let sortState = $state<SortState<Organizer>>({ key: null, direction: 'asc' });
	const sorted = $derived(sortRows(data?.results ?? [], sortState.key, sortState.direction));

	function sortBy(key: keyof Organizer) {
		sortState = toggleSort(sortState, key);
	}

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

<svelte:head>
	<title>Organizers — Veent Admin</title>
</svelte:head>

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

	<div class="overflow-hidden rounded-lg border border-border bg-surface">
		<table class="w-full text-left">
			<thead>
				<tr class="bg-surface-2">
					<th class="px-4 py-3">
						<SortHeader
							label="Organizer"
							active={sortState.key === 'name'}
							direction={sortState.direction}
							onsort={() => sortBy('name')}
						/>
					</th>
					<th
						class="px-4 py-3 text-xs font-semibold uppercase tracking-wider text-muted"
					>
						Status
					</th>
					<th class="px-4 py-3">
						<SortHeader
							label="Location"
							active={sortState.key === 'city'}
							direction={sortState.direction}
							onsort={() => sortBy('city')}
						/>
					</th>
					<th
						class="px-4 py-3 text-xs font-semibold uppercase tracking-wider text-muted"
					>
						Contact
					</th>
					<th
						class="px-4 py-3 text-right text-xs font-semibold uppercase tracking-wider text-muted"
					>
						Links
					</th>
				</tr>
			</thead>

			{#if loading && !data}
				<TableSkeleton columns={5} />
			{:else}
				<tbody>
					{#if error}
						<tr>
							<td colspan="5" class="px-4 py-10 text-center text-sm text-danger">
								Failed to load organizers: {error}
							</td>
						</tr>
					{:else if sorted.length === 0}
						<tr>
							<td colspan="5" class="px-4 py-10 text-center text-sm text-muted">
								No organizers found.
							</td>
						</tr>
					{:else}
						{#each sorted as o (o.slug)}
							{@const websiteUrl = safeUrl(o.website)}
							{@const facebookUrl = safeUrl(o.facebook_url)}
							{@const instagramUrl = safeUrl(o.instagram_url)}
							<tr
								class="border-t border-border transition-colors duration-100 hover:bg-surface-2"
							>
								<td class="px-4 py-3">
									<a
										href="/organizers/{o.slug}"
										class="font-medium text-heading hover:text-accent"
									>
										{o.name}
									</a>
									{#if o.source}
										<code
											class="ml-0 mt-0.5 block w-fit rounded bg-bg px-1 font-mono text-xs text-muted"
										>
											{o.source}
										</code>
									{/if}
								</td>
								<td class="px-4 py-3">
									<Badge status={o.status} />
								</td>
								<td class="px-4 py-3 text-sm text-text">
									{[o.city, o.country].filter(Boolean).join(', ') || '—'}
								</td>
								<td class="px-4 py-3 text-sm">
									{#if o.email}
										<a
											href="mailto:{o.email}"
											class="block truncate text-text hover:text-accent"
										>
											{o.email}
										</a>
									{/if}
									{#if o.phone}
										<span class="block text-muted">{o.phone}</span>
									{/if}
									{#if !o.email && !o.phone}
										<span class="text-muted">—</span>
									{/if}
								</td>
								<td class="px-4 py-3">
									<div class="flex items-center justify-end gap-2">
										{#if websiteUrl}
											<a
												href={websiteUrl}
												target="_blank"
												rel="noopener"
												title="Website"
												class="text-muted transition-colors hover:text-accent"
											>
												<Globe size={16} />
											</a>
										{/if}
										{#if facebookUrl}
											<a
												href={facebookUrl}
												target="_blank"
												rel="noopener"
												title="Facebook"
												class="text-muted transition-colors hover:text-accent"
											>
												<!-- lucide dropped brand glyphs; keep brand SVG (see Sidebar convention note) -->
												<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M22 12a10 10 0 1 0-11.56 9.88v-6.99H7.9V12h2.54V9.8c0-2.5 1.49-3.89 3.78-3.89 1.09 0 2.24.2 2.24.2v2.46h-1.26c-1.24 0-1.63.77-1.63 1.56V12h2.78l-.44 2.89h-2.34v6.99A10 10 0 0 0 22 12z" /></svg>
											</a>
										{/if}
										{#if instagramUrl}
											<a
												href={instagramUrl}
												target="_blank"
												rel="noopener"
												title="Instagram"
												class="text-muted transition-colors hover:text-accent"
											>
												<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="2" y="2" width="20" height="20" rx="5" /><path d="M16 11.37A4 4 0 1 1 12.63 8 4 4 0 0 1 16 11.37z" /><line x1="17.5" y1="6.5" x2="17.51" y2="6.5" /></svg>
											</a>
										{/if}
										{#if !websiteUrl && !facebookUrl && !instagramUrl}
											<span class="text-xs text-muted">—</span>
										{/if}
									</div>
								</td>
							</tr>
						{/each}
					{/if}
				</tbody>
			{/if}
		</table>
	</div>

	{#if data && data.pages > 1}
		<div class="flex items-center justify-between text-sm text-muted">
			<span>{data.total.toLocaleString()} organizers · page {data.page} of {data.pages}</span>
			<div class="flex gap-2">
				<button class="rounded-lg border border-border px-3 py-1.5 enabled:hover:bg-surface-2 disabled:opacity-40" disabled={page <= 1 || loading} onclick={() => (page -= 1)}>Previous</button>
				<button class="rounded-lg border border-border px-3 py-1.5 enabled:hover:bg-surface-2 disabled:opacity-40" disabled={page >= data.pages || loading} onclick={() => (page += 1)}>Next</button>
			</div>
		</div>
	{/if}
</div>
