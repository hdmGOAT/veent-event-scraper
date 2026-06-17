<script lang="ts">
	import {
		BarController,
		BarElement,
		CategoryScale,
		Chart,
		LinearScale,
		Tooltip
	} from 'chart.js';

	Chart.register(BarController, BarElement, CategoryScale, LinearScale, Tooltip);

	let { labels, data }: { labels: string[]; data: number[] } = $props();

	let canvas: HTMLCanvasElement;

	// Resolve a design-system CSS variable to its computed hex value. Runs only
	// in the effect (client-side, post-mount) so the document is available.
	function token(name: string): string {
		return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
	}

	$effect(() => {
		// Re-runs when labels/data change. Build, then tear down on cleanup.
		const accent = token('--color-accent');
		const surface2 = token('--color-surface-2');
		const heading = token('--color-heading');
		const text = token('--color-text');
		const border = token('--color-border');
		const muted = token('--color-muted');

		const chart = new Chart(canvas, {
			type: 'bar',
			data: {
				labels,
				datasets: [
					{
						data,
						backgroundColor: accent,
						hoverBackgroundColor: accent,
						borderRadius: 4,
						maxBarThickness: 56
					}
				]
			},
			options: {
				responsive: true,
				maintainAspectRatio: false,
				plugins: {
					legend: { display: false },
					tooltip: {
						backgroundColor: surface2,
						titleColor: heading,
						bodyColor: text,
						borderColor: border,
						borderWidth: 1,
						padding: 10,
						callbacks: { label: (c) => ` events : ${c.parsed.y}` }
					}
				},
				scales: {
					x: {
						grid: { display: false },
						border: { color: border },
						ticks: { color: muted }
					},
					y: {
						beginAtZero: true,
						grid: { color: border },
						border: { display: false },
						ticks: { color: muted }
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
