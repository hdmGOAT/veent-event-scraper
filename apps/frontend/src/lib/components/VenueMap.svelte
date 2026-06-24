<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import type * as LType from 'leaflet';
	import type { VenueMapPin } from '$lib/types';
	import { themeStore } from '$lib/theme.svelte';

	let { pins, height = '420px' }: { pins: VenueMapPin[]; height?: string } = $props();

	let mapEl: HTMLDivElement;
	let mapInstance: LType.Map | null = null;
	let markersLayer: LType.LayerGroup | null = null;
	let tileLayer: LType.TileLayer | null = null;
	let L_ref: typeof LType | null = null;
	let mapReady = $state(false);
	let initialFit = false;

	function tileUrl(theme: 'dark' | 'light'): string {
		return theme === 'light'
			? 'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png'
			: 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png';
	}

	const circleStyle = {
		radius: 8,
		fillColor: '#a78bfa',
		color: '#7c3aed',
		weight: 1.5,
		opacity: 1,
		fillOpacity: 0.85
	};

	const statusMeta: Record<string, { color: string; label: string }> = {
		verified: { color: '#22c55e', label: 'Verified' },
		rejected: { color: '#ef4444', label: 'Rejected' },
		pending: { color: '#f59e0b', label: 'Pending' }
	};

	function esc(s: string): string {
		return s
			.replace(/&/g, '&amp;')
			.replace(/</g, '&lt;')
			.replace(/>/g, '&gt;')
			.replace(/"/g, '&quot;')
			.replace(/'/g, '&#39;');
	}

	function safeUrl(url: string): string {
		try {
			const u = new URL(url);
			return u.protocol === 'http:' || u.protocol === 'https:' ? url : '';
		} catch {
			return '';
		}
	}

	function buildPopup(pin: VenueMapPin): string {
		const typeLabel =
			pin.agents_primary_types.length > 0
				? pin.agents_primary_types.join(', ')
				: pin.primary_type_display || '—';

		const location = [pin.city, pin.country].filter(Boolean).join(', ') || '—';
		const showAddress = pin.address && pin.address !== location;
		const st = statusMeta[pin.verification_status] ?? { color: '#94a3b8', label: pin.verification_status };
		const websiteHref = safeUrl(pin.website ?? '');

		return `
			<div class="vm-popup">
				<a class="vm-name" href="/venues/${esc(pin.slug)}">${esc(pin.name)}</a>
				<span class="vm-type">${esc(typeLabel)}</span>
				<span class="vm-loc">${esc(location)}</span>
				${showAddress ? `<span class="vm-addr">${esc(pin.address)}</span>` : ''}
				<div class="vm-row">
					${pin.rating != null ? `<span class="vm-rating">★ ${pin.rating}</span>` : ''}
					${pin.event_count > 0 ? `<span class="vm-events">${pin.event_count} event${pin.event_count !== 1 ? 's' : ''}</span>` : ''}
				</div>
				<div class="vm-row">
					<span class="vm-status" style="color:${st.color}">● ${esc(st.label)}</span>
					${websiteHref ? `<a class="vm-website" href="${esc(websiteHref)}" target="_blank" rel="noopener noreferrer">↗ Website</a>` : ''}
				</div>
			</div>
		`;
	}

	function renderMarkers() {
		if (!L_ref || !markersLayer || !mapInstance) return;
		markersLayer.clearLayers();
		const bounds: [number, number][] = [];
		for (const pin of pins) {
			const ll: [number, number] = [pin.latitude, pin.longitude];
			bounds.push(ll);
			L_ref.circleMarker(ll, circleStyle)
				.bindPopup(buildPopup(pin), { className: 'vm-popup-wrap', maxWidth: 280 })
				.addTo(markersLayer!);
		}
		if (!initialFit && bounds.length > 0) {
			mapInstance.fitBounds(bounds, { padding: [32, 32], maxZoom: 14 });
			initialFit = true;
		}
	}

	onMount(async () => {
		const L = await import('leaflet');
		await import('leaflet/dist/leaflet.css');
		L_ref = L;

		mapInstance = L.map(mapEl, { zoomControl: true });
		markersLayer = L.layerGroup().addTo(mapInstance);
		mapReady = true;
	});

	// Swap tile layer when theme or mapReady changes
	$effect(() => {
		const theme = themeStore.current;
		if (!mapReady || !mapInstance || !L_ref) return;
		if (tileLayer) mapInstance.removeLayer(tileLayer);
		tileLayer = L_ref.tileLayer(tileUrl(theme), {
			attribution: '&copy; <a href="https://carto.com/">CARTO</a>',
			subdomains: 'abcd',
			maxZoom: 19
		}).addTo(mapInstance);
	});

	// Re-render markers whenever pins or mapReady changes
	$effect(() => {
		if (!mapReady) return;
		renderMarkers();
	});

	onDestroy(() => {
		mapInstance?.remove();
		mapInstance = null;
	});
</script>

<div bind:this={mapEl} style="height: {height}; width: 100%;"></div>

<style>
	:global(.vm-popup-wrap .leaflet-popup-content-wrapper) {
		background: #1a1a2e;
		border: 1px solid #2d2d4e;
		border-radius: 10px;
		box-shadow: 0 4px 24px rgba(0, 0, 0, 0.5);
		color: #e2e8f0;
		padding: 0;
	}

	:global(.vm-popup-wrap .leaflet-popup-content) {
		margin: 0;
		padding: 0;
	}

	:global(.vm-popup-wrap .leaflet-popup-tip) {
		background: #1a1a2e;
	}

	:global(.vm-popup) {
		display: flex;
		flex-direction: column;
		gap: 4px;
		padding: 13px 15px;
		min-width: 180px;
	}

	:global(.vm-name) {
		font-size: 13px;
		font-weight: 600;
		color: #a78bfa;
		text-decoration: none;
		line-height: 1.3;
		margin-bottom: 2px;
	}

	:global(.vm-name:hover) {
		color: #c4b5fd;
		text-decoration: underline;
	}

	:global(.vm-type) {
		font-size: 11px;
		color: #94a3b8;
		background: #2d2d4e;
		border-radius: 4px;
		padding: 2px 7px;
		align-self: flex-start;
	}

	:global(.vm-loc) {
		font-size: 11px;
		color: #64748b;
		margin-top: 1px;
	}

	:global(.vm-addr) {
		font-size: 10px;
		color: #475569;
	}

	:global(.vm-row) {
		display: flex;
		align-items: center;
		gap: 8px;
		margin-top: 2px;
	}

	:global(.vm-rating) {
		font-size: 11px;
		color: #fbbf24;
	}

	:global(.vm-events) {
		font-size: 10px;
		color: #7c3aed;
		background: #2d1f4e;
		border-radius: 4px;
		padding: 1px 6px;
	}

	:global(.vm-status) {
		font-size: 10px;
		text-transform: capitalize;
	}

	:global(.vm-website) {
		font-size: 10px;
		color: #38bdf8;
		text-decoration: none;
		margin-left: auto;
	}

	:global(.vm-website:hover) {
		text-decoration: underline;
	}

	:global(.leaflet-container) {
		background: #0f0f1a;
		font-family: inherit;
	}
</style>
