import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import { clearToken, markLocked, markUnlocked } from '@/auth'
import { CreateTaskDialog } from './CreateTaskDialog'

beforeEach(() => {
  clearToken()
  markUnlocked()
})

test('une modale ouverte se ferme pendant le verrouillage et revient avec son brouillon', () => {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <CreateTaskDialog open onOpenChange={vi.fn()} />
    </QueryClientProvider>,
  )
  fireEvent.change(screen.getByLabelText('Titre'), { target: { value: 'Brouillon' } })

  act(() => markLocked('invalid_token'))
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()

  act(() => markUnlocked())
  expect(screen.getByRole('dialog', { name: 'Nouvelle tâche' })).toBeInTheDocument()
  expect(screen.getByLabelText('Titre')).toHaveValue('Brouillon')
})
