import React, { useEffect, useMemo, useState } from 'react'
import { createRoot } from 'react-dom/client'
import './style.css'

async function api(path, init) {
  const response = await fetch('/api' + path, { cache: 'no-store', headers: { 'Content-Type': 'application/json' }, ...init })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail || data))
  return data
}

const initial = { name: '', geo: '', offer_id: '', domain_id: '', group_id: '', source_id: '' }

function Select({ label, value, onChange, items, empty = 'Выберите' }) {
  return <label className="field"><span>{label}</span><select value={value} onChange={e => onChange(e.target.value)} required><option value="">{empty}</option>{items.map(item => <option key={item.id} value={item.id}>{item.name} · #{item.id}</option>)}</select></label>
}

function App() {
  const [tab, setTab] = useState('create')
  const [options, setOptions] = useState({ domains: [], groups: [], sources: [], offers: [] })
  const [campaigns, setCampaigns] = useState([])
  const [form, setForm] = useState(initial)
  const [selected, setSelected] = useState('')
  const [details, setDetails] = useState(null)
  const [offerChoice, setOfferChoice] = useState({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [query, setQuery] = useState('')

  const load = async () => {
    const [optionResult, campaignResult, detailResult] = await Promise.allSettled([api('/options'), api('/campaigns'), selected ? api('/campaigns/' + selected) : Promise.resolve(null)])
    if (optionResult.status === 'fulfilled') setOptions(optionResult.value)
    if (campaignResult.status === 'fulfilled') setCampaigns(campaignResult.value)
    if (detailResult.status === 'fulfilled' && detailResult.value) setDetails(detailResult.value)
    const failures = [optionResult, campaignResult, detailResult].filter(result => result.status === 'rejected')
    setError(failures.map(result => result.reason.message).join('; '))
  }
  useEffect(() => { load() }, [])
  const setField = (key, value) => setForm(prev => ({ ...prev, [key]: value }))
  const openCampaign = async id => {
    setSelected(String(id)); setError(''); setNotice('')
    if (!id) { setDetails(null); return }
    try { setDetails(await api('/campaigns/' + id)) } catch (err) { setError(err.message) }
  }
  const create = async e => {
    e.preventDefault(); setBusy(true); setError(''); setNotice('')
    try {
      const payload = { ...form, name: form.name.trim(), geo: form.geo.trim().toUpperCase(), offer_id: Number(form.offer_id), domain_id: Number(form.domain_id), group_id: Number(form.group_id), source_id: Number(form.source_id) }
      const result = await api('/campaigns', { method: 'POST', body: JSON.stringify(payload) })
      setForm(initial); await load(); setDetails(result); setSelected(String(result.campaign.id)); setTab('edit'); setNotice('Кампания и два потока созданы')
    } catch (err) { setError(err.message) } finally { setBusy(false) }
  }
  const changeOffer = async (streamId, offerId, action) => {
    setBusy(true); setError(''); setNotice('')
    try {
      const path = `/campaigns/${selected}/streams/${streamId}/offers`
      const result = action === 'add' ? await api(path, { method: 'POST', body: JSON.stringify({ offer_id: Number(offerId) }) }) : await api(path + '/' + offerId, { method: 'DELETE' })
      setDetails(result); setOfferChoice(prev => ({ ...prev, [streamId]: '' })); setNotice(action === 'add' ? 'Оффер добавлен' : 'Оффер отключён; его можно вернуть')
    } catch (err) { setError(err.message) } finally { setBusy(false) }
  }
  const refreshOffers = async () => {
    if (!selected) return
    setBusy(true); setError(''); setNotice('')
    try {
      const [opts, current] = await Promise.all([api('/options'), api('/campaigns/' + selected)])
      setOptions(opts); setDetails(current); setNotice('Информация об офферах обновлена')
    } catch (err) { setError(err.message) } finally { setBusy(false) }
  }
  const toggleLock = async (streamId, offerId, locked) => {
    setBusy(true); setError(''); setNotice('')
    try {
      const result = await api(`/campaigns/${selected}/streams/${streamId}/offers/${offerId}/lock`, { method: locked ? 'DELETE' : 'PUT' })
      setDetails(result); setNotice(locked ? 'Вес оффера откреплён' : 'Вес оффера закреплён')
    } catch (err) { setError(err.message) } finally { setBusy(false) }
  }
  const filtered = useMemo(() => campaigns.filter(c => `${c.name} ${c.id}`.toLowerCase().includes(query.toLowerCase())), [campaigns, query])
  const offerName = id => options.offers.find(o => o.id === id)?.name || `Оффер #${id}`
  return <div className="app">
    <aside className="sidebar"><div className="brand"><span className="brand-mark">K</span><div><b>Keitaro Studio</b><small>CAMPAIGN WORKSPACE</small></div></div><div className="side-label">РАБОЧАЯ ОБЛАСТЬ</div><button className={'nav ' + (tab === 'create' ? 'active' : '')} onClick={() => setTab('create')}><span>＋</span> Создать кампанию</button><button className={'nav ' + (tab === 'edit' ? 'active' : '')} onClick={() => setTab('edit')}><span>▤</span> Редактор офферов</button><div className="side-bottom"><span className="status-dot"/> Подключение через Keitaro API</div></aside>
    <main><header><div><div className="eyebrow">KEITARO / {tab === 'create' ? 'НОВАЯ КАМПАНИЯ' : 'РЕДАКТОР'}</div><h1>{tab === 'create' ? 'Создать кампанию' : 'Редактор кампании'}</h1><p>{tab === 'create' ? 'Настройте маршрут трафика за один шаг.' : 'Управляйте офферами и долями трафика в потоках.'}</p></div><button className="refresh" onClick={load}>↻ <span>Обновить данные</span></button></header>
      {error && <div className="alert error">{error}<button onClick={() => setError('')}>×</button></div>}{notice && <div className="alert success">{notice}<button onClick={() => setNotice('')}>×</button></div>}
      {tab === 'create' ? <div className="layout"><section className="card main-card"><div className="section-head"><div><span className="step">01</span><h2>Параметры кампании</h2></div><span className="hint">Все поля обязательны</span></div><form onSubmit={create}><label className="field"><span>Название кампании</span><input value={form.name} onChange={e => setField('name', e.target.value)} placeholder="Например, Summer campaign" required maxLength="255" /></label><div className="two"><label className="field"><span>Гео-код страны</span><input value={form.geo} onChange={e => setField('geo', e.target.value.toUpperCase())} placeholder="RU" required pattern="[A-Za-z]{2}" maxLength="2" /></label><Select label="Оффер Keitaro" value={form.offer_id} onChange={v => setField('offer_id', v)} items={options.offers}/></div><div className="separator"/><div className="section-head small"><div><span className="step">02</span><h2>Привязки</h2></div></div><div className="two"><Select label="Домен" value={form.domain_id} onChange={v => setField('domain_id', v)} items={options.domains}/><Select label="Группа кампаний" value={form.group_id} onChange={v => setField('group_id', v)} items={options.groups}/></div><Select label="Источник трафика" value={form.source_id} onChange={v => setField('source_id', v)} items={options.sources}/><div className="form-foot"><span>Будут созданы два потока с ротацией по позиции.</span><button className="primary" disabled={busy}>{busy ? 'Создание…' : 'Создать кампанию →'}</button></div></form></section><aside className="card preview"><div className="section-head"><div><span className="step">↳</span><h2>Маршрут трафика</h2></div></div><div className="route"><div className="route-node"><span className="node-icon">◎</span><div><small>ПОТОК 01 · GEO</small><b>{form.geo || 'Страна'}</b><p>HTTP-редирект на Google</p></div></div><div className="route-line"/><div className="route-node"><span className="node-icon green">↗</span><div><small>ПОТОК 02 · ОСТАЛЬНЫЕ</small><b>{form.offer_id ? offerName(Number(form.offer_id)) : 'Выбранный оффер'}</b><p>100% трафика на оффер</p></div></div></div><div className="info">Первый поток перехватывает выбранную страну. Остальной трафик получает замыкающий поток.</div></aside></div> : <div className="editor"><section className="card selector"><div className="section-head"><div><span className="step">01</span><h2>Выберите кампанию</h2></div><span className="count">{campaigns.length} кампаний</span></div><input className="search" value={query} onChange={e => setQuery(e.target.value)} placeholder="Поиск по названию или ID"/><select className="campaign-select" value={selected} onChange={e => openCampaign(e.target.value)}><option value="">Выберите кампанию</option>{filtered.map(c => <option value={c.id} key={c.id}>{c.name} · #{c.id}</option>)}</select></section>{details && <><div className="campaign-title"><div><div className="eyebrow">КАМПАНИЯ #{details.campaign.id}</div><h2>{details.campaign.name}</h2></div><div className="campaign-tools"><button className="secondary refresh-offers" disabled={busy} onClick={refreshOffers}>↻ Обновить офферы</button><a href={`https://tlgk.host/admin/#!/campaign/${details.campaign.id}/main`} target="_blank" rel="noreferrer">Открыть в Keitaro ↗</a></div></div>{details.streams.map(stream => <section className="card stream" key={stream.id}><div className="section-head"><div><span className="step">{String(stream.position || 0).padStart(2, '0')}</span><h2>{stream.name}</h2></div><span className="badge">Поток #{stream.id}</span></div>{stream.schema !== 'landings' ? <div className="redirect-box">Прямой URL · {stream.action_payload || '—'}</div> : <><div className="table-head"><span>ОФФЕР</span><span>ДОЛЯ ТРАФИКА</span><span>СТАТУС</span><span>ДЕЙСТВИЯ</span></div>{(stream.offers || []).map(item => <div className={'offer-row ' + (item.state !== 'active' ? 'muted' : '')} key={item.offer_id}><div><b>{offerName(item.offer_id)}</b><small>#{item.offer_id}</small></div><div className="share"><div className="bar"><i style={{ width: item.share + '%' }}/></div><b>{item.share}%</b></div><span className={'state ' + (item.state === 'active' ? 'on' : '')}>{item.state === 'active' ? 'Активен' : 'Отключён'}</span><div className="offer-actions">{item.state === 'active' && <button className={'pin-action ' + (item.locked ? 'pinned' : '')} aria-pressed={!!item.locked} title={item.locked ? `Закреплено ${item.locked_share}% — нажмите, чтобы открепить` : 'Закрепить текущий вес'} disabled={busy} onClick={() => toggleLock(stream.id, item.offer_id, item.locked)}>{item.locked ? '🔒 Закреплено' : '🔓 Закрепить'}</button>}<button className="row-action" disabled={busy} onClick={() => changeOffer(stream.id, item.offer_id, item.state === 'active' ? 'remove' : 'add')}>{item.state === 'active' ? 'Удалить' : 'Вернуть'}</button></div></div>)}<div className="add-row"><select value={offerChoice[stream.id] || ''} onChange={e => setOfferChoice(prev => ({ ...prev, [stream.id]: e.target.value }))}><option value="">Выберите оффер</option>{options.offers.filter(o => !stream.offers?.some(s => s.offer_id === o.id && s.state === 'active')).map(o => <option key={o.id} value={o.id}>{o.name} · #{o.id}</option>)}</select><button className="secondary" disabled={busy || !offerChoice[stream.id]} onClick={() => changeOffer(stream.id, offerChoice[stream.id], 'add')}>＋ Добавить оффер</button></div><div className="stream-foot"><span>Закреплённые доли сохраняются, остальные пересчитываются</span><b>Итого: {(stream.offers || []).filter(o => o.state === 'active').reduce((sum, o) => sum + o.share, 0)}%</b></div></>}</section>)}</>}</div>}
    </main></div>
}

createRoot(document.getElementById('root')).render(<App />)
