export const cloneStreams = streams => streams.map(stream => ({
  ...stream,
  offers: (stream.offers || []).map(offer => ({ ...offer })),
}))

const comparable = offers => offers
  .map(({ offer_id, state, share, locked, locked_share }) => ({
    offer_id, state, share, locked: !!locked, locked_share: locked ? locked_share : null,
  }))
  .sort((a, b) => a.offer_id - b.offer_id)

export const changedStreamIds = (original, draft) => draft
  .filter(stream => {
    const before = original?.streams.find(item => item.id === stream.id)
    return before && JSON.stringify(comparable(before.offers || [])) !== JSON.stringify(comparable(stream.offers || []))
  })
  .map(stream => stream.id)

export function rebalance(offers) {
  const next = offers.map(offer => ({ ...offer }))
  const active = next.filter(offer => offer.state === 'active')
  const pinned = active.filter(offer => offer.locked)
  const free = active.filter(offer => !offer.locked)
  const pinnedTotal = pinned.reduce((sum, offer) => sum + offer.locked_share, 0)
  if (pinnedTotal > 100) throw new Error('Сумма закреплённых долей превышает 100%')
  if (active.length && !free.length && pinnedTotal !== 100) {
    throw new Error('Для остатка трафика нужен хотя бы один незакреплённый оффер')
  }
  const each = free.length ? Math.floor((100 - pinnedTotal) / free.length) : 0
  const remainder = free.length ? (100 - pinnedTotal) % free.length : 0
  let index = 0
  return next.map(offer => {
    if (offer.state !== 'active') return { ...offer, share: 0, locked: false, locked_share: null }
    if (offer.locked) return { ...offer, share: offer.locked_share }
    const share = each + (index++ < remainder ? 1 : 0)
    return { ...offer, share, locked_share: null }
  })
}

export function editOffers(stream, original, offerId, action) {
  const id = Number(offerId)
  let offers = (stream.offers || []).map(item => ({ ...item }))
  const current = offers.find(item => item.offer_id === id)
  if (action === 'add') {
    if (current) throw new Error('Оффер уже есть в потоке. Используйте «Восстановить».')
    offers.push({ offer_id: id, state: 'active', share: 0, locked: false, locked_share: null })
  } else if (action === 'remove') {
    if (!current || current.state !== 'active') throw new Error('Активный оффер не найден')
    if (!(original.offers || []).some(item => item.offer_id === id)) {
      offers = offers.filter(item => item.offer_id !== id)
    } else {
      current.state = 'disabled'
      current.locked = false
      current.locked_share = null
    }
  } else if (action === 'restore') {
    if (!current || current.state === 'active') throw new Error('Удалённый оффер не найден')
    current.state = 'active'
    const previous = (original.offers || []).find(item => item.offer_id === id)
    current.locked = !!previous?.locked
    current.locked_share = current.locked ? previous.locked_share : null
  } else if (action === 'lock') {
    if (!current || current.state !== 'active') throw new Error('Активный оффер не найден')
    current.locked = !current.locked
    current.locked_share = current.locked ? current.share : null
    return { ...stream, offers }
  }
  const membership = items => items.map(item => ({
    id: item.offer_id, state: item.state, locked: !!item.locked,
    locked_share: item.locked ? item.locked_share : null,
  })).sort((a, b) => a.id - b.id)
  if (JSON.stringify(membership(offers)) === JSON.stringify(membership(original.offers || []))) {
    return { ...stream, offers: (original.offers || []).map(item => ({ ...item })) }
  }
  return { ...stream, offers: rebalance(offers) }
}
