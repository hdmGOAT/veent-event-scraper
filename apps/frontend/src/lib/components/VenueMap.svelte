<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import type { VenueMapPin } from '$lib/types';

	let { pins, height = '420px' }: { pins: VenueMapPin[]; height?: string } = $props();

	let mapEl: HTMLDivElement;
	let mapInstance: import('leaflet').Map | null = null;

	onMount(async () => {
		const L = (await import('leaflet')).default;
		await import('leaflet/dist/leaflet.css');

		mapInstance = L.map(mapEl, { zoomControl: true });

		L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
			attribution: '&copy; <a href="https://carto.com/">CARTO</a>',
			subdomains: 'abcd',
			maxZoom: 19
		}).addTo(mapInstance);

		const circleStyle = {
			radius: 8,
			fillColor: '#a78bfa',
			color: '#7c3aed',
			weight: 1.5,
			opacity: 1,
			fillOpacity: 0.85
		};

		const bounds: [number, number][] = [];

		for (const pin of pins) {
			const ll: [number, number] = [pin.latitude, pin.longitude];
			bounds.push(ll);

			const typeLabel =
				pin.agents_primary_types.length > 0
					? pin.agents_primary_types.join(', ')
					: (pin.primary_type_display || '—');

			const location = [pin.city, pin.country].filter(Boolean).join(', ') || pin.address || '—';

			const ratingHtml = pin.rating != null
				? `<span class="vm-rating">★ ${pin.rating}</span>`
				: '';

			const popupHtml = `
				<div class="vm-popup">
					<a class="vm-name" href="/venues/${pin.slug}">${pin.name}</a>
					<span class="vm-type">${typeLabel}</span>
					<span class="vm-loc">${location}</span>
					${ratingHtml}
				</div>
			`;

			L.circleMarker(ll, circleStyle)
				.bindPopup(popupHtml, { className: 'vm-popup-wrap', maxWidth: 240 })
				.addTo(mapInstance!);
		}

		if (bounds.length > 0) {
			mapInstance.fitBounds(bounds, { padding: [32, 32], maxZoom: 14 });
		} else {
			mapInstance.setView([20, 0], 2);
		}
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
		gap: 3px;
		padding: 12px 14px;
		min-width: 160px;
	}

	:global(.vm-name) {
		font-size: 13px;
		font-weight: 600;
		color: #a78bfa;
		text-decoration: none;
		line-height: 1.3;
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
		padding: 1px 6px;
		align-self: flex-start;
	}

	:global(.vm-loc) {
		font-size: 11px;
		color: #64748b;
	}

	:global(.vm-rating) {
		font-size: 11px;
		color: #fbbf24;
	}

	:global(.leaflet-container) {
		background: #0f0f1a;
		font-family: inherit;
	}
</style>
