import test from 'node:test'
import assert from 'node:assert/strict'
import { changedStreamIds, cloneStreams, editOffers } from './draft.js'

const original = {
  streams: [{ id: 11, schema: 'landings', offers: [
    { offer_id: 1, state: 'active', share: 50, locked: true, locked_share: 50 },
    { offer_id: 2, state: 'active', share: 50, locked: false, locked_share: null },
  ] }],
}

test('staging does not mutate the saved campaign and undo clears dirty state', () => {
  const saved = structuredClone(original)
  const draft = cloneStreams(original.streams)
  const added = editOffers(draft[0], original.streams[0], 3, 'add')
  assert.deepEqual(added.offers.map(offer => offer.share), [50, 25, 25])
  assert.deepEqual(changedStreamIds(original, [added]), [11])
  assert.deepEqual(original, saved)

  const undone = editOffers(added, original.streams[0], 3, 'remove')
  assert.deepEqual(changedStreamIds(original, [undone]), [])
  assert.deepEqual(undone.offers, original.streams[0].offers)
})

test('deleted saved offer can be restored with its pinned share', () => {
  const removed = editOffers(original.streams[0], original.streams[0], 1, 'remove')
  assert.deepEqual(removed.offers.map(offer => offer.share), [0, 100])
  assert.equal(removed.offers[0].state, 'disabled')
  assert.deepEqual(changedStreamIds(original, [removed]), [11])

  const restored = editOffers(removed, original.streams[0], 1, 'restore')
  assert.deepEqual(restored.offers, original.streams[0].offers)
  assert.deepEqual(changedStreamIds(original, [restored]), [])
})

test('pinning changes draft state without changing shares', () => {
  const pinned = editOffers(original.streams[0], original.streams[0], 2, 'lock')
  assert.deepEqual(pinned.offers.map(offer => offer.share), [50, 50])
  assert.equal(pinned.offers[1].locked_share, 50)
  assert.deepEqual(changedStreamIds(original, [pinned]), [11])

  const unpinned = editOffers(pinned, original.streams[0], 2, 'lock')
  assert.deepEqual(changedStreamIds(original, [unpinned]), [])
})
