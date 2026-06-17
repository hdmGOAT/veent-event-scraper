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

	$effect(() => {
		// Re-runs when labels/data change. Build, then tear down on cleanup.
		const chart = new Chart(canvas, {
			type: 'bar',
			data: {
				labels,
				datasets: [
					{
						data,
						backgroundColor: '#22d3ee',
						hoverBackgroundColor: '#67e8f9',
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
						backgroundColor: '#131c28',
						titleColor: '#e8eef5',
						bodyColor: '#c9d4e0',
						borderColor: '#1e2a38',
						borderWidth: 1,
						padding: 10,
						callbacks: { label: (c) => ` events : ${c.parsed.y}` }
					}
				},
				scales: {
					x: {
						grid: { display: false },
						border: { color: '#1e2a38' },
						ticks: { color: '#6b7a8d' }
					},
					y: {
						beginAtZero: true,
						grid: { color: '#1e2a3855' },
						border: { display: false },
						ticks: { color: '#6b7a8d' }
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
