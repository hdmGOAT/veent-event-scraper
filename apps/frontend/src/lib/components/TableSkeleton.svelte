<script lang="ts">
	// Placeholder loading rows for table views. Renders a <tbody> so it can drop
	// straight into an existing <table>. Width varies per column for a natural
	// shimmer; the last column is right-aligned to mirror action/icon columns.
	let { rows = 8, columns = 5 }: { rows?: number; columns?: number } = $props();

	const widths = ['w-3/4', 'w-1/2', 'w-2/3', 'w-1/3', 'w-1/2', 'w-2/5'];
</script>

<tbody class="divide-y divide-border">
	{#each Array(rows) as _, r (r)}
		<tr>
			{#each Array(columns) as _, c (c)}
				<td class="px-5 py-3">
					<div
						class="h-4 animate-pulse rounded bg-surface-2 {widths[c % widths.length]}"
						class:ml-auto={c === columns - 1}
					></div>
				</td>
			{/each}
		</tr>
	{/each}
</tbody>
