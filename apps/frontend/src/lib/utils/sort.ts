// Generic client-side column sort helpers for table views.
//
// Sort operates only on the rows passed in (the current page of API results).
// Cross-page sort would require a backend `ordering=` query param (out of scope).

export type SortDirection = 'asc' | 'desc';

export interface SortState<T> {
	key: keyof T | null;
	direction: SortDirection;
}

/**
 * Return a new array sorted by `key`. When `key` is null the original array is
 * returned unchanged (no copy). Handles strings, numbers, and ISO date strings
 * (which compare lexicographically correctly). Null/undefined sort last.
 */
export function sortRows<T>(rows: T[], key: keyof T | null, direction: SortDirection): T[] {
	if (key === null) return rows;

	const dir = direction === 'asc' ? 1 : -1;

	return [...rows].sort((a, b) => {
		const av = a[key];
		const bv = b[key];

		// Push null/undefined/empty values to the end regardless of direction.
		const aEmpty = av === null || av === undefined || av === '';
		const bEmpty = bv === null || bv === undefined || bv === '';
		if (aEmpty && bEmpty) return 0;
		if (aEmpty) return 1;
		if (bEmpty) return -1;

		if (typeof av === 'number' && typeof bv === 'number') {
			return (av - bv) * dir;
		}

		return String(av).localeCompare(String(bv)) * dir;
	});
}

/**
 * Toggle sort state for `key`. First click on a new column sorts ascending;
 * clicking the active column flips the direction.
 */
export function toggleSort<T>(current: SortState<T>, key: keyof T): SortState<T> {
	if (current.key === key) {
		return { key, direction: current.direction === 'asc' ? 'desc' : 'asc' };
	}
	return { key, direction: 'asc' };
}
