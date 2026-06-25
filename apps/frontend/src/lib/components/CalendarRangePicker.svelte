<script lang="ts">
	import { ChevronLeft, ChevronRight } from 'lucide-svelte';

	interface Props {
		dateFrom?: string;
		dateTo?: string;
		onApply: (from: string, to: string) => void;
		onClear: () => void;
		onClose: () => void;
	}

	let { dateFrom = '', dateTo = '', onApply, onClear, onClose }: Props = $props();

	const MONTHS = [
		'January','February','March','April','May','June',
		'July','August','September','October','November','December'
	];
	const DAYS = ['SUN','MON','TUE','WED','THU','FRI','SAT'];

	const now = new Date();
	let viewYear = $state(dateFrom ? +dateFrom.slice(0, 4) : now.getFullYear());
	let viewMonth = $state(dateFrom ? +dateFrom.slice(5, 7) - 1 : now.getMonth());

	let draftFrom = $state(dateFrom);
	let draftTo   = $state(dateTo);
	let hoverDate = $state('');

	const cells = $derived.by(() => {
		const firstDay    = new Date(viewYear, viewMonth, 1).getDay();
		const daysInMonth = new Date(viewYear, viewMonth + 1, 0).getDate();
		const out: (number | null)[] = Array(firstDay).fill(null);
		for (let d = 1; d <= daysInMonth; d++) out.push(d);
		return out;
	});

	function str(y: number, m: number, d: number) {
		return `${y}-${String(m + 1).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
	}

	function dayStr(d: number) {
		return str(viewYear, viewMonth, d);
	}

	function handleClick(day: number) {
		const s = dayStr(day);
		if (!draftFrom || (draftFrom && draftTo)) {
			draftFrom = s;
			draftTo   = '';
		} else if (s === draftFrom) {
			// clicking same start — reset
			draftFrom = '';
		} else if (s < draftFrom) {
			draftTo   = draftFrom;
			draftFrom = s;
		} else {
			draftTo = s;
		}
		hoverDate = '';
	}

	function status(day: number) {
		const s   = dayStr(day);
		const end = draftTo || (draftFrom ? hoverDate : '');
		const lo  = draftFrom && end ? (draftFrom <= end ? draftFrom : end) : '';
		const hi  = draftFrom && end ? (draftFrom <= end ? end : draftFrom) : '';

		const isStart  = !!lo && s === lo;
		const isEnd    = !!hi && s === hi && hi !== lo;
		const isSingle = !!lo && s === lo && lo === hi;
		const inRange  = !!(lo && hi && s > lo && s < hi);
		const hasEnd   = !!(draftTo || hoverDate);

		return { isStart, isEnd, isSingle, inRange, hasEnd };
	}

	function prevMonth() {
		if (viewMonth === 0) { viewYear--; viewMonth = 11; } else viewMonth--;
	}
	function nextMonth() {
		if (viewMonth === 11) { viewYear++; viewMonth = 0; } else viewMonth++;
	}

	function formatDisplay(d: string) {
		if (!d) return '';
		const [y, m, day] = d.split('-');
		return `${MONTHS[+m - 1].slice(0, 3)} ${+day}, ${y}`;
	}
</script>

<!-- Backdrop -->
<button
	type="button"
	class="fixed inset-0 z-40 bg-black/60 backdrop-blur-sm"
	onclick={onClose}
	aria-label="Close"
></button>

<!-- Modal -->
<div class="fixed left-1/2 top-1/2 z-50 w-[340px] -translate-x-1/2 -translate-y-1/2 select-none rounded-2xl border border-border bg-surface shadow-2xl">

	<!-- Month navigation -->
	<div class="flex items-center justify-between px-5 py-4">
		<button
			type="button"
			onclick={prevMonth}
			class="flex h-8 w-8 items-center justify-center rounded-full text-muted transition-colors hover:bg-surface-2 hover:text-text"
		>
			<ChevronLeft size={16} />
		</button>
		<span class="text-sm font-bold text-heading tracking-wide">
			{MONTHS[viewMonth]} {viewYear}
		</span>
		<button
			type="button"
			onclick={nextMonth}
			class="flex h-8 w-8 items-center justify-center rounded-full text-muted transition-colors hover:bg-surface-2 hover:text-text"
		>
			<ChevronRight size={16} />
		</button>
	</div>

	<div class="px-3 pb-3">
		<!-- Day-of-week headers -->
		<div class="mb-1 grid grid-cols-7">
			{#each DAYS as d}
				<div class="py-1 text-center text-[10px] font-semibold uppercase tracking-wider text-muted">
					{d}
				</div>
			{/each}
		</div>

		<!-- Day grid -->
		<div class="grid grid-cols-7">
			{#each cells as day}
				{#if day === null}
					<div class="h-10"></div>
				{:else}
					{@const { isStart, isEnd, isSingle, inRange, hasEnd } = status(day)}
					<div class="relative flex h-10 items-center justify-center">

						<!-- Range fill — runs behind the circles -->
						{#if inRange}
							<div class="pointer-events-none absolute inset-y-[5px] left-0 right-0 bg-accent/20"></div>
						{/if}
						<!-- Half-fill on start side -->
						{#if isStart && hasEnd}
							<div class="pointer-events-none absolute inset-y-[5px] left-1/2 right-0 bg-accent/20"></div>
						{/if}
						<!-- Half-fill on end side -->
						{#if isEnd}
							<div class="pointer-events-none absolute inset-y-[5px] left-0 right-1/2 bg-accent/20"></div>
						{/if}

						<!-- Day circle -->
						<button
							type="button"
							onclick={() => handleClick(day)}
							onmouseenter={() => { if (draftFrom && !draftTo) hoverDate = dayStr(day); }}
							onmouseleave={() => (hoverDate = '')}
							class="relative z-10 flex h-9 w-9 items-center justify-center rounded-full text-sm transition-colors
								{isStart || isEnd || isSingle
									? 'bg-accent font-semibold text-white shadow-md'
									: inRange
									? 'font-medium text-text hover:bg-accent/30'
									: 'text-muted hover:bg-surface-2 hover:text-text'}"
						>
							{day}
						</button>
					</div>
				{/if}
			{/each}
		</div>
	</div>

	<!-- Selected range pill display -->
	<div class="mx-3 mb-3 flex items-center justify-center gap-2 rounded-lg bg-surface-2 px-3 py-2 text-xs min-h-[34px]">
		{#if draftFrom}
			<span class="font-medium text-text">{formatDisplay(draftFrom)}</span>
			{#if draftTo}
				<span class="text-muted">→</span>
				<span class="font-medium text-text">{formatDisplay(draftTo)}</span>
			{:else}
				<span class="text-muted">→ pick end date</span>
			{/if}
		{:else}
			<span class="text-muted">Select a start date</span>
		{/if}
	</div>

	<!-- Actions -->
	<div class="flex gap-2 border-t border-border px-4 py-3">
		<button
			type="button"
			onclick={() => onApply(draftFrom, draftTo)}
			disabled={!draftFrom}
			class="flex-1 rounded-lg bg-accent py-2 text-sm font-semibold text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
		>
			Apply
		</button>
		<button
			type="button"
			onclick={onClear}
			class="rounded-lg border border-border px-4 py-2 text-sm text-muted transition-colors hover:text-text"
		>
			Clear
		</button>
	</div>
</div>
