<script lang="ts">
	// Icon convention: use lucide-svelte components.
	// Do not add inline <svg> strings. Size: 18px, strokeWidth: 2 for nav icons.
	import { Calendar, Icon, LayoutGrid, MapPin, Menu, Radio, User, Users, X, Zap } from 'lucide-svelte';
	import { page } from '$app/state';

	// Nav items. `match` decides active highlighting; the dashboard ("/") must
	// match exactly so it doesn't stay lit on every page.
	const items: { href: string; label: string; exact: boolean; icon: typeof Icon }[] = [
		{ href: '/', label: 'Dashboard', exact: true, icon: LayoutGrid },
		{ href: '/scrapers', label: 'Scraper Center', exact: false, icon: Radio },
		{ href: '/events', label: 'Events', exact: false, icon: Calendar },
		{ href: '/organizers', label: 'Organizers', exact: false, icon: Users },
		{ href: '/venues', label: 'Venues', exact: false, icon: MapPin }
	];

	function isActive(href: string, exact: boolean): boolean {
		const path = page.url.pathname;
		return exact ? path === href : path === href || path.startsWith(href + '/');
	}

	// Mobile drawer open/close. On desktop (>= md) the sidebar is always visible
	// via CSS; this state only drives the mobile overlay drawer.
	let open = $state(false);

	// Close the drawer after navigating on mobile.
	$effect(() => {
		void page.url.pathname;
		open = false;
	});
</script>

<!-- Mobile top bar with hamburger (hidden on >= md) -->
<div
	class="fixed left-0 right-0 top-0 z-30 flex items-center gap-3 border-b border-border bg-surface px-4 py-3 md:hidden"
>
	<button
		type="button"
		aria-label="Open navigation"
		onclick={() => (open = true)}
		class="text-muted transition-colors hover:text-text"
	>
		<Menu size={22} />
	</button>
	<span class="text-base font-bold tracking-wide text-heading">VEENT<span class="text-accent">.</span></span>
</div>

<!-- Backdrop (mobile only, when drawer open) -->
{#if open}
	<button
		type="button"
		aria-label="Close navigation"
		onclick={() => (open = false)}
		class="fixed inset-0 z-30 bg-black/50 md:hidden"
	></button>
{/if}

<aside
	class="fixed left-0 top-0 z-40 flex h-screen w-60 flex-col border-r border-border bg-surface transition-transform duration-200 ease-in-out md:sticky md:translate-x-0 {open
		? 'translate-x-0'
		: '-translate-x-full'}"
>
	<!-- Brand -->
	<div class="flex items-center justify-between px-5 py-5">
		<div class="flex items-center gap-2">
			<span class="flex h-8 w-8 items-center justify-center rounded-lg bg-accent/15 text-accent">
				<Zap size={18} strokeWidth={2} />
			</span>
			<span class="text-lg font-bold tracking-wide text-heading">VEENT<span class="text-accent">.</span></span>
		</div>
		<button
			type="button"
			aria-label="Close navigation"
			onclick={() => (open = false)}
			class="text-muted transition-colors hover:text-text md:hidden"
		>
			<X size={20} />
		</button>
	</div>

	<!-- Nav -->
	<nav class="flex-1 space-y-1 px-3 py-2">
		{#each items as item (item.href)}
			{@const active = isActive(item.href, item.exact)}
			{@const Icon = item.icon}
			<a
				href={item.href}
				class="flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors {active
					? 'bg-accent/10 text-accent'
					: 'text-muted hover:bg-surface-2 hover:text-text'}"
			>
				<span class="shrink-0">
					<Icon size={18} strokeWidth={2} />
				</span>
				{item.label}
			</a>
		{/each}
	</nav>

	<!-- User footer -->
	<div class="flex items-center gap-3 border-t border-border px-5 py-4">
		<span class="flex h-9 w-9 items-center justify-center rounded-full bg-surface-2 text-accent">
			<User size={18} strokeWidth={2} />
		</span>
		<div class="leading-tight">
			<div class="text-sm font-medium text-heading">Admin User</div>
			<div class="text-xs text-muted">admin@veent.io</div>
		</div>
	</div>
</aside>
