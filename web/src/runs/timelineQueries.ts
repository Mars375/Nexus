import { useInfiniteQuery } from '@tanstack/react-query'
import { REFRESH_MS } from '@/freshness'
import { timelineApi, type TimelineEntry } from '@/timelineApi'

/** Under `['tasks', id]` on purpose: `task_changed` and `event` messages refresh it too. */
export const timelineKey = (taskId: string) => ['tasks', taskId, 'timeline'] as const

/**
 * The story of a card, newest first, one page per cursor. A refresh reads again the pages already
 * loaded, from their own cursors: the list neither shrinks nor jumps; the 10 s read stays the
 * safety net of the live messages.
 */
export function useTimeline(taskId: string) {
  return useInfiniteQuery({
    queryKey: timelineKey(taskId),
    queryFn: ({ pageParam, signal }) => timelineApi.page(taskId, pageParam, signal),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
    refetchInterval: REFRESH_MS.tasks,
    networkMode: 'always',
    select: (data) => {
      const seen = new Set<string>()
      const entries: TimelineEntry[] = []
      for (const page of data.pages)
        for (const entry of page.entries)
          if (!seen.has(entry.id)) {
            seen.add(entry.id)
            entries.push(entry)
          }
      return entries
    },
  })
}
