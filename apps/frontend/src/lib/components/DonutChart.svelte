<script lang="ts">
	import { ArcElement, Chart, DoughnutController, Legend, Tooltip } from 'chart.js';
	import { themeStore } from '$lib/theme.svelte';

	Chart.register(ArcElement, DoughnutController, Legend, Tooltip);

	let { labels, data }: { labels: string[]; data: number[] } = $props();

	let canvas: HTMLCanvasElement;

	function token(name: string): string {
		return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
	}

	$effect(() => {
		// Re-runs when labels/data change OR when the theme toggles.
		void themeStore.current;
		// Palette mixes design-system tokens with a few fixed accent hues so
		// arbitrary category counts still get distinct, on-brand colors.
		const palette = [
			token('--color-accent'),
			'#818cf8',
			token('--color-success'),
			token('--color-warning'),
			'#f472b6',
			'#fb923c',
			'#a78bfa'
		];

		const chart = new Chart(canvas, {
			type: 'doughnut',
			data: {
				labels,
				datasets: [
					{
						data,
						backgroundColor: labels.map((_, i) => palette[i % palette.length]),
						borderColor: token('--color-surface'),
						borderWidth: 2
					}
				]
			},
			options: {
				responsive: true,
				maintainAspectRatio: false,
				cutout: '62%',
				plugins: {
					legend: {
						position: 'bottom',
						labels: { color: token('--color-text'), boxWidth: 10, padding: 14, usePointStyle: true }
					},
					tooltip: {
						backgroundColor: token('--color-surface-2'),
						titleColor: token('--color-heading'),
						bodyColor: token('--color-text'),
						borderColor: token('--color-border'),
						borderWidth: 1,
						padding: 10
					}
				}
			}
		});
		return () => chart.destroy();
	});
</script>

<div class="relative h-72 w-full">
	<canvas bind:this={canvas}></canvas>
</div>
