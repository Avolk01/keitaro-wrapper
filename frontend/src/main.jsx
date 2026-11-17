import React, { useEffect, useMemo, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { changedStreamIds, cloneStreams, editOffers } from './draft.js'
import './style.css'

async function api(path, init) {
  const response = await fetch('/api' + path, {
    cache: 'no-store',
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail || data))
  return data
}

const initial = { name: '', geo: '', offer_id: '', domain_id: '', group_id: '', source_id: '' }

function Select({ label, value, onChange, items }) {
  return <label className="field">
    <span>{label}</span>
    <select value={value} onChange={event => onChange(event.target.value)} required>
      <option value="">Выберите</option>
      {items.map(item => <option key={item.id} value={item.id}>{item.name} · #{item.id}</option>)}
    </select>
  </label>
}

function App() {
  const [tab, setTab] = useState('create')
  const [options, setOptions] = useState({ domains: [], groups: [], sources: [], offers: [] })
  const [campaigns, setCampaigns] = useState([])
  const [form, setForm] = useState(initial)
  const [selected, setSelected] = useState('')
  const [details, setDetails] = useState(null)
  const [draftStreams, setDraftStreams] = useState([])
  const [offerChoice, setOfferChoice] = useState({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [query, setQuery] = useState('')

  const changedIds = useMemo(() => changedStreamIds(details, draftStreams), [details, draftStreams])
  const hasChanges = changedIds.length > 0
  useEffect(() => {
    if (!hasChanges) return
    const warnOnLeave = event => { event.preventDefault(); event.returnValue = '' }
    window.addEventListener('beforeunload', warnOnLeave)
    return () => window.removeEventListener('beforeunload', warnOnLeave)
  }, [hasChanges])
  const offerName = id => options.offers.find(offer => offer.id === id)?.name || `Оффер #${id}`
  const setField = (key, value) => setForm(previous => ({ ...previous, [key]: value }))

  const load = async () => {
    const requests = [api('/options'), api('/campaigns'), selected && !hasChanges ? api('/campaigns/' + selected) : Promise.resolve(null)]
    const [optionResult, campaignResult, detailResult] = await Promise.allSettled(requests)
    if (optionResult.status === 'fulfilled') setOptions(optionResult.value)
    if (campaignResult.status === 'fulfilled') setCampaigns(campaignResult.value)
    if (detailResult.status === 'fulfilled' && detailResult.value) {
      setDetails(detailResult.value)
      setDraftStreams(cloneStreams(detailResult.value.streams))
    }
    const failures = [optionResult, campaignResult, detailResult].filter(result => result.status === 'rejected')
    setError(failures.map(result => result.reason.message).join('; '))
    if (selected && hasChanges && !failures.length) setNotice('Справочники обновлены. Несохранённые изменения оставлены в черновике.')
  }
  useEffect(() => { load() }, [])

  const openCampaign = async id => {
    if (hasChanges) { setError('Сначала отправьте или отмените несохранённые изменения'); return }
    setSelected(String(id)); setDetails(null); setDraftStreams([]); setError(''); setNotice('')
    if (!id) return
    try {
      const result = await api('/campaigns/' + id)
      setDetails(result)
      setDraftStreams(cloneStreams(result.streams))
    } catch (err) { setError(err.message) }
  }

  const create = async event => {
    event.preventDefault()
    if (hasChanges) { setError('Сначала отправьте или отмените несохранённые изменения'); return }
    setBusy(true); setError(''); setNotice('')
    try {
      const payload = {
        ...form, name: form.name.trim(), geo: form.geo.trim().toUpperCase(),
        offer_id: Number(form.offer_id), domain_id: Number(form.domain_id),
        group_id: Number(form.group_id), source_id: Number(form.source_id),
      }
      const result = await api('/campaigns', { method: 'POST', body: JSON.stringify(payload) })
      setForm(initial); setDetails(result); setDraftStreams(cloneStreams(result.streams))
      setSelected(String(result.campaign.id)); setTab('edit')
      setNotice('Кампания и два потока созданы в Keitaro')
      setCampaigns(await api('/campaigns'))
    } catch (err) { setError(err.message) } finally { setBusy(false) }
  }

  const stageChange = (streamId, offerId, action) => {
    const stream = draftStreams.find(item => item.id === streamId)
    const original = details?.streams.find(item => item.id === streamId)
    if (!stream || !original) return
    try {
      const updated = editOffers(stream, original, offerId, action)
      setDraftStreams(previous => previous.map(item => item.id === streamId ? updated : item))
      setError(''); setNotice('')
      if (action === 'add') setOfferChoice(previous => ({ ...previous, [streamId]: '' }))
    } catch (err) { setError(err.message) }
  }

  const discardChanges = () => {
    setDraftStreams(cloneStreams(details.streams))
    setError(''); setNotice('Черновик отменён')
  }

  const refreshOffers = async () => {
    if (!selected) return
    setBusy(true); setError(''); setNotice('')
    try {
      const opts = await api('/options')
      setOptions(opts)
      if (hasChanges) {
        setNotice('Справочник офферов обновлён. Черновик сохранён без изменений.')
      } else {
        const current = await api('/campaigns/' + selected)
        setDetails(current); setDraftStreams(cloneStreams(current.streams))
        setNotice('Информация об офферах обновлена')
      }
    } catch (err) { setError(err.message) } finally { setBusy(false) }
  }

  const sendChanges = async () => {
    if (!hasChanges) return
    setBusy(true); setError(''); setNotice('')
    let base = details
    let draft = draftStreams
    let saved = 0
    try {
      for (const streamId of changedIds) {
        const stream = draft.find(item => item.id === streamId)
        const original = base.streams.find(item => item.id === streamId)
        const body = {
          expected_updated_at: original.updated_at,
          offers: stream.offers.map(item => ({
            offer_id: item.offer_id, state: item.state, share: item.share,
            locked: !!item.locked, locked_share: item.locked ? item.locked_share : null,
          })),
        }
        const result = await api(`/campaigns/${selected}/streams/${streamId}/draft`, {
          method: 'PUT', body: JSON.stringify(body),
        })
        base = result
        draft = draft.map(item => item.id === streamId
          ? cloneStreams([result.streams.find(savedStream => savedStream.id === streamId)])[0] : item)
        setDetails(base); setDraftStreams(draft)
        saved += 1
      }
      setNotice('Изменения отправлены в Keitaro')
    } catch (err) {
      setDetails(base); setDraftStreams(draft)
      setError((saved ? `${saved} поток(ов) сохранено. Остальные изменения остались в черновике. ` : '') + err.message)
    } finally { setBusy(false) }
  }

  const filtered = useMemo(() => campaigns.filter(campaign =>
    `${campaign.name} ${campaign.id}`.toLowerCase().includes(query.toLowerCase())), [campaigns, query])

  return <div className="app">
    <aside className="sidebar">
      <div className="brand"><span className="brand-mark">K</span><div><b>Keitaro Studio</b><small>CAMPAIGN WORKSPACE</small></div></div>
      <div className="side-label">РАБОЧАЯ ОБЛАСТЬ</div>
      <button className={'nav ' + (tab === 'create' ? 'active' : '')} disabled={hasChanges || busy} onClick={() => setTab('create')}><span>＋</span> Создать кампанию</button>
      <button className={'nav ' + (tab === 'edit' ? 'active' : '')} onClick={() => setTab('edit')}><span>▤</span> Редактор офферов</button>
      <div className="side-bottom"><span className="status-dot"/> Подключение через Keitaro API</div>
    </aside>
    <main>
      <header><div>
        <div className="eyebrow">KEITARO / {tab === 'create' ? 'НОВАЯ КАМПАНИЯ' : 'РЕДАКТОР'}</div>
        <h1>{tab === 'create' ? 'Создать кампанию' : 'Редактор кампании'}</h1>
        <p>{tab === 'create' ? 'Настройте маршрут трафика за один шаг.' : 'Изменения отправятся в Keitaro после подтверждения.'}</p>
      </div><button className="refresh" onClick={load}>↻ <span>Обновить данные</span></button></header>
      {error && <div className="alert error">{error}<button onClick={() => setError('')}>×</button></div>}
      {notice && <div className="alert success">{notice}<button onClick={() => setNotice('')}>×</button></div>}

      {tab === 'create' ? <div className="layout">
        <section className="card main-card">
          <div className="section-head"><div><span className="step">01</span><h2>Параметры кампании</h2></div><span className="hint">Все поля обязательны</span></div>
          <form onSubmit={create}>
            <label className="field"><span>Название кампании</span><input value={form.name} onChange={event => setField('name', event.target.value)} placeholder="Например, Summer campaign" required maxLength="255" /></label>
            <div className="two">
              <label className="field"><span>Гео-код страны</span><input value={form.geo} onChange={event => setField('geo', event.target.value.toUpperCase())} placeholder="RU" required pattern="[A-Za-z]{2}" maxLength="2" /></label>
              <Select label="Оффер Keitaro" value={form.offer_id} onChange={value => setField('offer_id', value)} items={options.offers}/>
            </div>
            <div className="separator"/>
            <div className="section-head small"><div><span className="step">02</span><h2>Привязки</h2></div></div>
            <div className="two">
              <Select label="Домен" value={form.domain_id} onChange={value => setField('domain_id', value)} items={options.domains}/>
              <Select label="Группа кампаний" value={form.group_id} onChange={value => setField('group_id', value)} items={options.groups}/>
            </div>
            <Select label="Источник трафика" value={form.source_id} onChange={value => setField('source_id', value)} items={options.sources}/>
            <div className="form-foot"><span>Будут созданы два потока с ротацией по позиции.</span><button className="primary" disabled={busy}>{busy ? 'Создание…' : 'Создать и отправить →'}</button></div>
          </form>
        </section>
        <aside className="card preview">
          <div className="section-head"><div><span className="step">↳</span><h2>Маршрут трафика</h2></div></div>
          <div className="route">
            <div className="route-node"><span className="node-icon">◎</span><div><small>ПОТОК 01 · GEO</small><b>{form.geo || 'Страна'}</b><p>HTTP-редирект на Google</p></div></div>
            <div className="route-line"/>
            <div className="route-node"><span className="node-icon green">↗</span><div><small>ПОТОК 02 · ОСТАЛЬНЫЕ</small><b>{form.offer_id ? offerName(Number(form.offer_id)) : 'Выбранный оффер'}</b><p>100% трафика на оффер</p></div></div>
          </div>
          <div className="info">Первый поток перехватывает выбранную страну. Остальной трафик получает замыкающий поток.</div>
        </aside>
      </div> : <div className="editor">
        <section className="card selector">
          <div className="section-head"><div><span className="step">01</span><h2>Выберите кампанию</h2></div><span className="count">{campaigns.length} кампаний</span></div>
          <input className="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="Поиск по названию или ID"/>
          <select className="campaign-select" value={selected} disabled={hasChanges || busy} onChange={event => openCampaign(event.target.value)}>
            <option value="">Выберите кампанию</option>
            {filtered.map(campaign => <option value={campaign.id} key={campaign.id}>{campaign.name} · #{campaign.id}</option>)}
          </select>
        </section>
        {details && <>
          <div className="campaign-title"><div><div className="eyebrow">КАМПАНИЯ #{details.campaign.id}</div><h2>{details.campaign.name}</h2></div>
            <div className="campaign-tools"><button className="secondary refresh-offers" disabled={busy} onClick={refreshOffers}>↻ Обновить офферы</button><a href={`https://tlgk.host/admin/#!/campaign/${details.campaign.id}/main`} target="_blank" rel="noreferrer">Открыть в Keitaro ↗</a></div>
          </div>
          <div className={'draft-banner ' + (hasChanges ? 'dirty' : '')}>
            <div><b>{hasChanges ? 'Есть несохранённые изменения' : 'Все изменения сохранены'}</b><span>{hasChanges ? `Изменено потоков: ${changedIds.length}. Keitaro пока не обновлён.` : 'Данные синхронизированы с Keitaro.'}</span></div>
            {hasChanges && <div className="draft-actions"><button className="draft-cancel" disabled={busy} onClick={discardChanges}>Отменить изменения</button><button className="primary" disabled={busy} onClick={sendChanges}>{busy ? 'Отправка…' : 'Отправить изменения →'}</button></div>}
          </div>
          {draftStreams.map(stream => <section className="card stream" key={stream.id}>
            <div className="section-head"><div><span className="step">{String(stream.position || 0).padStart(2, '0')}</span><h2>{stream.name}</h2></div><span className={'badge ' + (changedIds.includes(stream.id) ? 'pending' : '')}>{changedIds.includes(stream.id) ? '● Не сохранено' : `Поток #${stream.id}`}</span></div>
            {stream.schema !== 'landings' ? <div className="redirect-box">Прямой URL · {stream.action_payload || '—'}</div> : <>
              <div className="table-head"><span>ОФФЕР</span><span>ДОЛЯ ТРАФИКА</span><span>СТАТУС</span><span>ДЕЙСТВИЯ</span></div>
              {(stream.offers || []).map(item => <div className={'offer-row ' + (item.state !== 'active' ? 'muted' : '')} key={item.offer_id}>
                <div><b>{offerName(item.offer_id)}</b><small>#{item.offer_id}</small></div>
                <div className="share"><div className="bar"><i style={{ width: item.share + '%' }}/></div><b>{item.share}%</b></div>
                <span className={'state ' + (item.state === 'active' ? 'on' : '')}>{item.state === 'active' ? 'Активен' : 'Удалён'}</span>
                <div className="offer-actions">
                  {item.state === 'active' && <button className={'pin-action ' + (item.locked ? 'pinned' : '')} aria-pressed={!!item.locked} title={item.locked ? `Закреплено ${item.locked_share}% — нажмите, чтобы открепить` : 'Закрепить текущий вес'} disabled={busy} onClick={() => stageChange(stream.id, item.offer_id, 'lock')}>{item.locked ? '🔒 Закреплено' : '🔓 Закрепить'}</button>}
                  <button className="row-action" disabled={busy} onClick={() => stageChange(stream.id, item.offer_id, item.state === 'active' ? 'remove' : 'restore')}>{item.state === 'active' ? 'Удалить' : 'Восстановить'}</button>
                </div>
              </div>)}
              <div className="add-row"><select value={offerChoice[stream.id] || ''} onChange={event => setOfferChoice(previous => ({ ...previous, [stream.id]: event.target.value }))}>
                <option value="">Выберите оффер</option>
                {options.offers.filter(offer => !stream.offers?.some(item => item.offer_id === offer.id)).map(offer => <option key={offer.id} value={offer.id}>{offer.name} · #{offer.id}</option>)}
              </select><button className="secondary" disabled={busy || !offerChoice[stream.id]} onClick={() => stageChange(stream.id, offerChoice[stream.id], 'add')}>＋ Добавить оффер</button></div>
              <div className="stream-foot"><span>Закреплённые доли сохраняются, остальные пересчитываются</span><b>Итого: {(stream.offers || []).filter(item => item.state === 'active').reduce((sum, item) => sum + item.share, 0)}%</b></div>
            </>}
          </section>)}
        </>}
      </div>}
    </main>
  </div>
}

createRoot(document.getElementById('root')).render(<App />)
