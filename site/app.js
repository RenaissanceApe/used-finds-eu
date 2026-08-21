'use strict';

/* used-finds-eu — static build.
 *
 * Runs with no server: the marketplace catalogue and the shipping resolver are
 * pure data and pure functions, so both work fully in the browser. What needs
 * the Python backend is the aggregation itself — 30 sites in parallel, merged
 * and de-duplicated — because a browser cannot call those marketplace APIs
 * cross-origin. The Live tab bridges to a backend when you have one running.
 */

const $  = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

const state = { data: null, api: localStorage.getItem('ufeu.api') || '' };

const eur = (v) =>
  v === null || v === undefined ? '—' : '€' + Number(v).toLocaleString('pt-PT', { maximumFractionDigits: 0 });

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === 'class') node.className = value;
    else if (key === 'text') node.textContent = value;
    else if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child.nodeType ? child : document.createTextNode(String(child)));
  }
  return node;
}

// ── tabs ──────────────────────────────────────────────────────────────────
function showTab(name) {
  $$('.tab').forEach((t) => t.classList.toggle('active', t.dataset.tab === name));
  $$('.panel').forEach((p) => p.classList.toggle('active', p.id === `tab-${name}`));
}
$$('.tab').forEach((tab) => tab.addEventListener('click', () => showTab(tab.dataset.tab)));
document.addEventListener('click', (event) => {
  const target = event.target.closest('[data-goto]');
  if (!target) return;
  event.preventDefault();
  showTab(target.dataset.goto);
});

// ── boot ──────────────────────────────────────────────────────────────────
(async function boot() {
  try {
    // Inlined by the standalone build; fetched on GitHub Pages.
    state.data = window.UFEU_DATA || await (await fetch('data.json')).json();
  } catch (err) {
    $('#health').textContent = 'Could not load catalogue data: ' + err.message;
    return;
  }

  const marketplaces = state.data.marketplaces;
  const countries = Object.keys(state.data.countries).filter((c) => c !== 'EU');
  $('#health').replaceChildren(
    el('span', { class: 'pill badge', text: `${marketplaces.length} marketplaces` }),
    el('span', { class: 'pill badge', text: `${countries.length} countries` }),
    el('span', { class: 'pill', text: `catalogue ${state.data.catalog_updated}` }),
  );
  $('#foot-meta').textContent =
    `Catalogue reviewed ${state.data.catalog_updated} · built ${state.data.generated} · ` +
    `costs are estimates for ranking, not quotes`;

  renderShipCountries();
  renderMarkets('');
  $('#api-url').value = state.api;

  // Deep-linkable: ?q=nikon+d750 runs the launcher on load.
  const initial = new URLSearchParams(location.search).get('q');
  if (initial) { $('#q').value = initial; renderLaunch(); }
})();

// ── search launcher ───────────────────────────────────────────────────────
function slugify(text) {
  return (text.normalize('NFKD').replace(/[\u0300-\u036f]/g, '').toLowerCase()
    .replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')) || 'x';
}

function searchUrl(market, query) {
  const encoding = market.search.encoding;
  const term =
    encoding === 'slug' ? slugify(query)
    : encoding === 'dash' ? encodeURIComponent(query.trim().replace(/\s+/g, '-'))
    : encodeURIComponent(query.trim());
  return market.search.url.replace('%QUERY%', term);
}

function launchSelection() {
  const onlyTop = $('#only-top').checked;
  const onlyShips = $('#only-ships').checked;
  const focus = $('#focus').value;

  let markets = state.data.marketplaces.filter((m) => !onlyShips || m.ships_to_pt);
  if (focus) markets = markets.filter((m) => (m.focus || []).includes(focus));
  if (onlyTop) {
    // One row per country: the highest-ranked survivor of the filters above.
    const best = new Map();
    for (const market of markets) {
      const current = best.get(market.country);
      if (!current || market.rank < current.rank) best.set(market.country, market);
    }
    markets = [...best.values()];
  }
  // Pan-EU sites first, then by country name, then by local rank.
  const name = (code) => state.data.countries[code]?.name || code;
  return markets.sort((a, b) =>
    (a.scope === 'pan_eu' ? 0 : 1) - (b.scope === 'pan_eu' ? 0 : 1) ||
    name(a.country).localeCompare(name(b.country)) ||
    a.rank - b.rank || a.name.localeCompare(b.name));
}

function launchCard(market, query, showCountry) {
  const country = state.data.countries[market.country] || { name: market.country, zone: 4 };
  return el('a', {
    class: `launch-card${market.rank === 1 ? ' rank1' : ''}`,
    href: searchUrl(market, query), target: '_blank', rel: 'noopener noreferrer',
  },
    el('div', { class: 'row' },
      showCountry ? el('span', { class: 'badge country', text: market.country }) : null,
      el('span', { class: 'site', text: market.name }),
      market.rank === 1 && !showCountry ? el('span', { class: 'badge country', text: '#1' }) : null,
      market.ships_to_pt ? el('span', { class: 'badge ok', text: 'ships PT' }) : null,
      market.account.required ? el('span', { class: 'badge warn', text: 'login' }) : null,
      el('span', { class: 'go', text: 'search ↗' }),
    ),
    showCountry
      ? el('div', { class: 'sub-row' },
          el('span', { text: country.name }),
          el('span', { class: 'badge', text: market.country === 'PT' ? 'home' : `zone ${country.zone}` }))
      : null,
    market.why ? el('p', { class: 'why', text: market.why }) : null,
  );
}

function renderLaunch() {
  const query = $('#q').value.trim();
  if (!query) return;

  const markets = launchSelection();
  $('#launch-count').textContent = `${markets.length} sites`;

  // One card per country tiles far better as a flat grid than as 28 sections
  // of one row each; the full list stays grouped so countries read as units.
  if ($('#only-top').checked) {
    $('#launch-results').replaceChildren(
      el('div', { class: 'launch-grid' }, ...markets.map((m) => launchCard(m, query, true)))
    );
    return;
  }

  const groups = new Map();
  for (const market of markets) {
    if (!groups.has(market.country)) groups.set(market.country, []);
    groups.get(market.country).push(market);
  }
  $('#launch-results').replaceChildren(...[...groups.entries()].map(([code, group]) => {
    const country = state.data.countries[code] || { name: code, zone: 4 };
    return el('section', { class: 'launch-country' },
      el('h2', {},
        country.name,
        el('span', { class: 'badge', text: code }),
        code === 'PT'
          ? el('span', { class: 'badge ok', text: 'home — no shipping' })
          : el('span', { class: 'badge', text: `shipping zone ${country.zone}` }),
      ),
      el('div', { class: 'launch-grid' }, ...group.map((m) => launchCard(m, query, false))),
    );
  }));
}

$('#launch-form').addEventListener('submit', (event) => { event.preventDefault(); renderLaunch(); });
['#only-top', '#only-ships', '#focus'].forEach((sel) =>
  $(sel).addEventListener('change', () => { if ($('#q').value.trim()) renderLaunch(); }));

$('#open-top').addEventListener('click', () => {
  const query = $('#q').value.trim();
  if (!query) { $('#q').focus(); return; }
  const top = launchSelection().filter((m) => m.rank === 1).slice(0, 8);
  // Browsers block bursts of window.open — say so rather than silently doing nothing.
  const opened = top.map((market) => window.open(searchUrl(market, query), '_blank', 'noopener'));
  if (opened.some((w) => !w)) {
    $('#launch-count').textContent = 'Your browser blocked the pop-ups — allow them for this site, or click the cards.';
  } else {
    $('#launch-count').textContent = `opened ${top.length} tabs`;
  }
});

// ── shipping resolver (ported from ufeu/shipping.py) ──────────────────────
function estimateWeight(text) {
  const low = (text || '').toLowerCase();
  for (const [pattern, kg, bulky] of state.data.shipping.weight_hints) {
    if (new RegExp(pattern, 'i').test(low)) return [kg, bulky];
  }
  return [state.data.shipping.default_weight_kg, false];
}

const zoneFor = (code) => state.data.shipping.zones[(code || '').toUpperCase()] ?? 4;

function strategyCost(strategy, zone, weightKg) {
  const cost = strategy.cost || {};
  const base = cost.base || 0, perKg = cost.per_kg || 0, fixed = cost.fixed_extra || 0;
  let total = base + perKg * Math.max(weightKg, 0.5) + fixed;

  if (cost.zone_multiplier !== undefined && cost.zone_multiplier !== null) {
    const row = state.data.shipping.zone_costs[String(zone)];
    total = (row.base + row.per_kg * weightKg) * cost.zone_multiplier;
  } else if (['broker', 'carrier', 'forwarder'].includes(strategy.kind) && zone >= 3) {
    total *= 1.15;
  }
  return Math.round(total * 100) / 100;
}

function applies(strategy, country, weightKg, bulky, nativeShipping) {
  const countries = strategy.countries || [];
  if (!countries.includes('ALL') && !countries.includes(country.toUpperCase())) return false;
  if (strategy.requires_marketplace_native && !nativeShipping) return false;
  if (weightKg > (strategy.max_weight_kg ?? 999)) return false;
  if (weightKg < (strategy.min_weight_kg ?? 0)) return false;
  if (bulky && !strategy.bulky_ok) return false;
  if (country.toUpperCase() === 'PT' && strategy.id !== 'local_pickup') return false;
  return true;
}

function shippingPlan(country, { title, weightKg, bulky, itemPriceEur, nativeShipping } = {}) {
  const [guessedWeight, guessedBulky] = estimateWeight(title);
  const weight = weightKg ?? guessedWeight;
  const isBulky = bulky ?? guessedBulky;
  const zone = zoneFor(country);

  const options = state.data.shipping.strategies
    .filter((s) => applies(s, country, weight, isBulky, !!nativeShipping))
    .map((s) => {
      const cost = strategyCost(s, zone, weight);
      const [dMin, dMax] = s.days || [3, 10];
      return {
        id: s.id, name: s.name, kind: s.kind, overlay: !!s.overlay,
        cost_eur: cost,
        cost_low_eur: Math.round(cost * 75) / 100,
        cost_high_eur: Math.round(cost * 145) / 100,
        days_min: dMin, days_max: dMax,
        effort: s.effort ?? 3, risk: s.risk ?? 3, confidence: s.confidence || 'medium',
        summary: (s.summary || '').split(/\s+/).join(' ').trim(),
        steps: s.steps || [], providers: s.providers || [], caveats: s.caveats || [],
        landed_cost_eur: itemPriceEur != null ? Math.round((itemPriceEur + cost) * 100) / 100 : null,
        recommended: false,
      };
    });

  // Cost first, then how much of your life it costs. Overlays (a proxy buyer
  // de-risks a purchase but still needs a real route) always sort last.
  options.sort((a, b) =>
    (a.overlay ? 1 : 0) - (b.overlay ? 1 : 0) ||
    (a.cost_eur + a.effort * 2.5 + a.risk * 2) - (b.cost_eur + b.effort * 2.5 + b.risk * 2) ||
    a.days_max - b.days_max);

  const primary = options.find((o) => !o.overlay);
  if (primary) primary.recommended = true;
  return { country: country.toUpperCase(), zone, weight_kg: weight, bulky: isBulky, options };
}

function renderRoute(option) {
  return el('div', { class: `route${option.recommended ? ' top' : ''}` },
    el('div', { class: 'head' },
      el('span', { class: 'cost', text: eur(option.cost_eur) }),
      el('span', { class: 'name', text: option.name }),
      option.recommended ? el('span', { class: 'badge ok', text: 'best pick' }) : null,
      option.overlay ? el('span', { class: 'badge warn', text: 'add-on, not a route' }) : null,
      el('span', { class: 'badge', text: `${option.days_min}–${option.days_max} days` }),
      el('span', { class: 'badge', text: `effort ${option.effort}/5` }),
      el('span', { class: 'badge', text: `risk ${option.risk}/5` }),
      option.landed_cost_eur ? el('span', { class: 'badge', text: `${eur(option.landed_cost_eur)} landed` }) : null,
    ),
    el('p', { text: option.summary }),
    option.steps.length ? el('ul', {}, ...option.steps.map((s) => el('li', { text: s }))) : null,
    option.caveats.length ? el('ul', { class: 'caveats' }, ...option.caveats.map((c) => el('li', { text: c }))) : null,
    option.providers.length
      ? el('div', { class: 'providers' }, ...option.providers.map((p) =>
          el('a', { class: 'badge', href: p.url, target: '_blank', rel: 'noopener noreferrer', text: p.name + ' ↗' })))
      : null,
  );
}

function renderShipCountries() {
  $('#ship-country').replaceChildren(
    ...Object.entries(state.data.countries)
      .filter(([code]) => code !== 'EU')
      .sort((a, b) => a[1].name.localeCompare(b[1].name))
      .map(([code, country]) =>
        el('option', { value: code, selected: code === 'DE' }, `${country.name} (${code})`))
  );
}

$('#ship-form').addEventListener('submit', (event) => {
  event.preventDefault();
  const plan = shippingPlan($('#ship-country').value, {
    title: $('#ship-item').value,
    itemPriceEur: $('#ship-price').value ? Number($('#ship-price').value) : null,
    weightKg: $('#ship-weight').value ? Number($('#ship-weight').value) : undefined,
  });
  $('#ship-results').replaceChildren(
    el('p', { class: 'lede', text:
      `${plan.country} → PT · zone ${plan.zone} · estimated ${plan.weight_kg}kg` +
      `${plan.bulky ? ', bulky' : ''} · ${plan.options.length} viable routes` }),
    ...plan.options.map(renderRoute),
  );
});

// ── marketplaces ──────────────────────────────────────────────────────────
function renderMarkets(filter) {
  const needle = (filter || '').trim().toLowerCase();
  const byCountry = new Map();
  for (const market of state.data.marketplaces) {
    if (market.derived_from) continue;   // the nine eBay storefronts are one entry here
    const country = state.data.countries[market.country] || { name: market.country };
    const haystack = [market.name, market.country, country.name, market.engine, (market.focus || []).join(' '), market.why]
      .join(' ').toLowerCase();
    if (needle && !haystack.includes(needle)) continue;
    if (!byCountry.has(market.country)) byCountry.set(market.country, []);
    byCountry.get(market.country).push(market);
  }

  const blocks = [...byCountry.entries()]
    .sort((a, b) => {
      const nameOf = (code) => state.data.countries[code]?.name || code;
      return (a[0] === 'EU' ? 0 : 1) - (b[0] === 'EU' ? 0 : 1) || nameOf(a[0]).localeCompare(nameOf(b[0]));
    })
    .map(([code, markets]) => {
      const country = state.data.countries[code] || { name: code, currency: '', zone: 4 };
      return el('section', { class: 'country-block' },
        el('h2', {}, `${country.name} (${code})`,
          el('span', { class: 'zone', text: `shipping zone ${country.zone} · ${country.currency}` })),
        ...markets.sort((a, b) => a.rank - b.rank || a.name.localeCompare(b.name)).map((market) =>
          el('div', { class: 'market-card' },
            el('div', { class: 'head' },
              el('strong', { text: `${market.rank}. ${market.name}` }),
              el('a', { href: market.site, target: '_blank', rel: 'noopener noreferrer', class: 'badge', text: 'visit ↗' }),
              el('span', { class: 'badge', text: market.engine }),
              market.ships_to_pt ? el('span', { class: 'badge ok', text: 'ships to PT' }) : null,
              el('span', {
                class: `badge ${market.confidence === 'high' ? 'ok' : market.confidence === 'low' ? 'bad' : 'warn'}`,
                text: `${market.confidence} confidence`,
              }),
              market.account.signup_url
                ? el('a', { class: 'badge', href: market.account.signup_url, target: '_blank', rel: 'noopener noreferrer', text: 'sign up ↗' })
                : null,
            ),
            market.why ? el('p', { class: 'why', text: market.why }) : null,
            market.shipping_notes ? el('p', { class: 'ship-note' }, el('b', { text: 'Shipping: ' }), market.shipping_notes) : null,
          )
        ),
      );
    });

  $('#markets').replaceChildren(...(blocks.length ? blocks : [el('p', { class: 'empty', text: 'Nothing matches that filter.' })]));
}
$('#market-filter').addEventListener('input', (event) => renderMarkets(event.target.value));

// ── live mode (talks to the Python backend) ───────────────────────────────
$('#live-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const base = $('#api-url').value.trim().replace(/\/$/, '');
  const query = $('#live-q').value.trim();
  if (!base || !query) return;
  localStorage.setItem('ufeu.api', base);
  state.api = base;

  $('#live-stats').replaceChildren(el('span', { class: 'spinner' }), ' searching Europe…');
  $('#live-results').replaceChildren();
  $('#live-status').replaceChildren();

  let body;
  try {
    const response = await fetch(base + '/api/search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ q: query, limit: 24, sort: $('#live-sort').value }),
    });
    if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
    body = await response.json();
  } catch (err) {
    $('#live-stats').replaceChildren(el('span', { class: 'badge bad', text: 'no backend' }),
      ` ${err.message}. Is it running, and does it allow this page's origin (${location.origin})? ` +
      `Set UFEU_ALLOWED_ORIGINS to include it.`);
    return;
  }

  const stats = body.stats;
  $('#live-stats').textContent =
    `${stats.listings_total} listings · ${stats.markets_ok}/${stats.markets_queried} marketplaces answered · ` +
    `${stats.duplicates_removed} duplicates removed · ${(stats.elapsed_ms / 1000).toFixed(1)}s`;

  $('#live-results').replaceChildren(...body.listings.map((listing) => {
    const safeImage = /^https?:\/\//i.test(listing.image || '')
      ? listing.image.replace(/["'\\()\s]/g, encodeURIComponent) : null;
    return el('article', { class: 'card' },
      safeImage
        ? el('div', { class: 'thumb', style: `background-image:url("${safeImage}")` })
        : el('div', { class: 'thumb', text: '📦' }),
      el('div', { class: 'body' },
        el('a', { class: 'title', href: listing.url, target: '_blank', rel: 'noopener noreferrer', text: listing.title }),
        el('div', { class: 'prices' }, el('span', { class: 'price', text: eur(listing.price_eur) })),
        el('div', { class: 'landed', text: listing.country === 'PT'
          ? 'Local — collect in person'
          : `${eur(listing.landed_cost_eur)} delivered · +${eur(listing.shipping_cost_eur)} shipping` }),
        el('div', { class: 'meta' },
          el('span', { class: 'badge country', text: listing.country }),
          el('span', { class: 'badge', text: listing.marketplace_name }),
          listing.condition ? el('span', { class: 'badge', text: listing.condition }) : null,
          el('span', { class: 'badge ship', text: '🚚 routes', onclick: () => openDrawer(listing) }),
        ),
      ),
    );
  }));

  const problems = (body.results || []).filter((r) => r.status !== 'ok');
  if (problems.length) {
    const badgeClass = { manual: 'warn', needs_auth: 'warn', empty: '', error: 'bad' };
    $('#live-status').replaceChildren(
      el('h3', { text: `Marketplaces needing attention (${problems.length})` }),
      ...problems.map((result) => el('div', { class: 'status-row' },
        el('span', { class: 'name', text: `${result.country} · ${result.marketplace_name}` }),
        el('span', { class: `badge ${badgeClass[result.status] || ''}`, text: result.status.replace('_', ' ') }),
        el('span', { class: 'msg', text: result.error || '' }),
        result.search_url ? el('a', { href: result.search_url, target: '_blank', rel: 'noopener noreferrer', text: 'open ↗' }) : null,
      )),
    );
  }
});

// ── shipping drawer (shared by live results) ──────────────────────────────
function openDrawer(listing) {
  const plan = shippingPlan(listing.country, {
    title: [listing.title, listing.description].filter(Boolean).join(' '),
    itemPriceEur: listing.price_eur,
    nativeShipping: !!listing.ships,
  });
  $('#drawer-body').replaceChildren(
    el('h2', { text: listing.title }),
    el('p', { class: 'sub', text:
      `${listing.marketplace_name} · ${listing.country} → PT · zone ${plan.zone} · ` +
      `est. ${plan.weight_kg}kg${plan.bulky ? ' · bulky' : ''}` }),
    ...plan.options.map(renderRoute),
  );
  $('#drawer').classList.remove('hidden');
  $('#drawer-backdrop').classList.remove('hidden');
}
const closeDrawer = () => {
  $('#drawer').classList.add('hidden');
  $('#drawer-backdrop').classList.add('hidden');
};
$('#drawer-close').addEventListener('click', closeDrawer);
$('#drawer-backdrop').addEventListener('click', closeDrawer);
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeDrawer(); });
