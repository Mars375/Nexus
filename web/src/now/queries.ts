import { useQuery } from '@tanstack/react-query'
import { nodesApi, nowApi } from '@/api'
import { REFRESH_MS } from '@/freshness'

export const nowKey = ['now'] as const
export const nodesKey = ['nodes'] as const

// Serveur local : toujours tenter la requête, jamais de pause « hors ligne ».
const local = { networkMode: 'always' } as const

export function useNowSnapshot() {
  return useQuery({
    queryKey: nowKey,
    queryFn: ({ signal }) => nowApi.get(signal),
    refetchInterval: REFRESH_MS.now,
    ...local,
  })
}

export function useNodes() {
  return useQuery({
    queryKey: nodesKey,
    queryFn: ({ signal }) => nodesApi.list(signal),
    refetchInterval: REFRESH_MS.nodes,
    ...local,
  })
}
