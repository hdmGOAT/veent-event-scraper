<script lang="ts">
	import { ArcElement, Chart, DoughnutController, Legend, Tooltip } from 'chart.js';

	Chart.register(ArcElement, DoughnutController, Legend, Tooltip);

	let { labels, data }: { labels: string[]; data: number[] } = $props();

	// Palette cycles for arbitrary category counts.
	const palette = ['#22d3ee', '#818cf8', '#34d399', '#fbbf24', '#f472b6', '#fb923c', '#a78bfa'];

	let canvas: HTMLCanvasElement;

	$effect(() => {
		const chart = new Chart(canvas, {
			type: 'doughnut',
			data: {
				labels,
				datasets: [
					{
						data,
						backgroundColor: labels.map((_, i) => palette[i % palette.length]),
						borderColor: '#0f1620',
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
						labels: { color: '#c9d4e0', boxWidth: 10, padding: 14, usePointStyle: true }
					},
					tooltip: {
						backgroundColor: '#131c28',
						titleColor: '#e8eef5',
						bodyColor: '#c9d4e0',
						borderColor: '#1e2a38',
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
