<script lang="ts">
	import { page } from '$app/state';

	// Nav items. `match` decides active highlighting; the dashboard ("/") must
	// match exactly so it doesn't stay lit on every page.
	const items = [
		{ href: '/', label: 'Dashboard', exact: true, icon: 'grid' },
		{ href: '/scrapers', label: 'Scraper Center', exact: false, icon: 'radio' },
		{ href: '/events', label: 'Events', exact: false, icon: 'calendar' },
		{ href: '/organizers', label: 'Organizers', exact: false, icon: 'users' },
		{ href: '/venues', label: 'Venues', exact: false, icon: 'pin' }
	];

	function isActive(href: string, exact: boolean): boolean {
		const path = page.url.pathname;
		return exact ? path === href : path === href || path.startsWith(href + '/');
	}
</script>

<aside class="flex h-screen w-60 flex-col border-r border-border bg-surface">
	<!-- Brand -->
	<div class="flex items-center gap-2 px-5 py-5">
		<span class="flex h-8 w-8 items-center justify-center rounded-lg bg-accent/15 text-accent">
			<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" /></svg>
		</span>
		<span class="text-lg font-bold tracking-wide text-heading">VEENT<span class="text-accent">.</span></span>
	</div>

	<!-- Nav -->
	<nav class="flex-1 space-y-1 px-3 py-2">
		{#each items as item (item.href)}
			{@const active = isActive(item.href, item.exact)}
			<a
				href={item.href}
				class="flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors {active
					? 'bg-accent/10 text-accent'
					: 'text-muted hover:bg-surface-2 hover:text-text'}"
			>
				<span class="shrink-0">
					{#if item.icon === 'grid'}
						<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7" /><rect x="14" y="3" width="7" height="7" /><rect x="14" y="14" width="7" height="7" /><rect x="3" y="14" width="7" height="7" /></svg>
					{:else if item.icon === 'radio'}
						<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="2" /><path d="M4.93 19.07a10 10 0 0 1 0-14.14M7.76 16.24a6 6 0 0 1 0-8.49M16.24 7.76a6 6 0 0 1 0 8.49M19.07 4.93a10 10 0 0 1 0 14.14" /></svg>
					{:else if item.icon === 'calendar'}
						<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="18" rx="2" /><line x1="16" y1="2" x2="16" y2="6" /><line x1="8" y1="2" x2="8" y2="6" /><line x1="3" y1="10" x2="21" y2="10" /></svg>
					{:else if item.icon === 'users'}
						<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" /><circle cx="9" cy="7" r="4" /><path d="M23 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75" /></svg>
					{:else if item.icon === 'pin'}
						<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z" /><circle cx="12" cy="10" r="3" /></svg>
					{/if}
				</span>
				{item.label}
			</a>
		{/each}
	</nav>

	<!-- User footer -->
	<div class="flex items-center gap-3 border-t border-border px-5 py-4">
		<span class="flex h-9 w-9 items-center justify-center rounded-full bg-surface-2 text-accent">
			<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" /><circle cx="12" cy="7" r="4" /></svg>
		</span>
		<div class="leading-tight">
			<div class="text-sm font-medium text-heading">Admin User</div>
			<div class="text-xs text-muted">admin@veent.io</div>
		</div>
	</div>
</aside>
