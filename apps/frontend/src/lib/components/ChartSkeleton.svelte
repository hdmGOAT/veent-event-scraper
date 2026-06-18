<div class="mt-4 space-y-3">
	<div class="flex items-end gap-2 px-2" style="height: 160px;">
		{#each [60, 85, 45, 100, 70, 55, 90, 40] as h}
			<div
				class="animate-pulse flex-1 rounded-t bg-surface-2"
				style="height: {h}%"
			></div>
		{/each}
	</div>
	<div class="h-3 w-full animate-pulse rounded bg-surface-2"></div>
</div>
