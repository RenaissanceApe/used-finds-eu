'use strict';

// ── state ─────────────────────────────────────────────────────────────────
const state = {
  catalog: null,
  response: null,
  facet: { countries: new Set(), marketplaces: new Set() },
  selectedCountries: new Set(),   // empty = all
};

const $  = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

const eur = (v) =>
  v === null || v === undefined ? '—' : '€' + v.toLocaleString('pt-PT', { maximumFractionDigits: 0 });

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === 'class') node.className = value;
    else if (key === 'text') node.textContent = value;
    else if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
    else if (key === 'style') node.setAttribute('style', value);
    else node.setAttribute(key, value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child.nodeType ? child : document.createTextNode(String(child)));
  }
  return node;
}

async function api(path, options) {
  const response = await fetch(path, options);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `${response.status} ${response.statusText}`);
  }
  return response.json();
}

// ── tabs ──────────────────────────────────────────────────────────────────
$$('.tab').forEach((tab) =>
  tab.addEventListener('click', () => {
    $$('.tab').forEach((t) => t.classList.toggle('active', t === tab));
    $$('.panel').forEach((p) => p.classList.toggle('active', p.id === `tab-${tab.dataset.tab}`));
  })
);

// ── boot ──────────────────────────────────────────────────────────────────
(async function boot() {
  try {
    const [health, catalog] = await Promise.all([api('/api/health'), api('/api/catalog')]);
    state.catalog = catalog;
    renderHealth(health);
    renderCountryPicker();
    renderMarkets();
    renderShipCountries();
    loadAccounts();
  } catch (err) {
    $('#health').textContent = 'Backend unreachable: ' + err.message;
  }
})();

function renderHealth(health) {
  const bits = [
    el('span', { class: 'pill', text: `catalog ${health.catalog_updated}` }),
    health.demo_mode ? el('span', { class: 'pill badge warn', text: 'DEMO MODE — synthetic results' }) : null,
    health.fx_stale
      ? el('span', { class: 'pill badge warn', text: 'FX rates offline (approximate)' })
      : el('span', { class: 'pill', text: `FX ${health.fx_as_of || 'live'}` }),
  ];
  $('#health').replaceChildren(...bits.filter(Boolean));
}

// ── country picker ────────────────────────────────────────────────────────
function renderCountryPicker() {
  const picker = $('#country-picker');
  picker.replaceChildren(
    ...state.catalog.countries.map((country) => {
      const box = el('input', { type: 'checkbox', value: country.code });
      box.addEventListener('change', () => {
        box.checked ? state.selectedCountries.add(country.code) : state.selectedCountries.delete(country.code);
        const n = state.selectedCountries.size;
        $('#pick-countries').textContent = n ? `Countries: ${n} selected` : 'Countries: all';
      });
      return el('label', {}, box, `${country.name} (${country.code})`);
    })
  );
}
$('#pick-countries').addEventListener('click', () => $('#country-picker').classList.toggle('hidden'));

// ── search ────────────────────────────────────────────────────────────────
$('#search-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const query = $('#q').value.trim();
  if (!query) return;

  const button = $('#go');
  button.disabled = true;
  state.facet.countries.clear();
  state.facet.marketplaces.clear();
  $('#stats').replaceChildren(el('span', { class: 'spinner' }), ' searching Europe…');
  $('#results').replaceChildren();
  $('#market-status').replaceChildren();

  const payload = {
    q: query,
    countries: state.selectedCountries.size ? [...state.selectedCountries] : null,
    sort: $('#sort').value,
    limit: Number($('#limit').value) || 24,
    min_price_eur: $('#min-price').value ? Number($('#min-price').value) : null,
    max_price_eur: $('#max-price').value ? Number($('#max-price').value) : null,
    include_disabled: $('#include-disabled').checked,
    fresh: $('#fresh').checked,
  };

  try {
    state.response = await api('/api/search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    renderFacets();
    renderResults();
    renderMarketStatus();
  } catch (err) {
    $('#stats').textContent = 'Search failed: ' + err.message;
  } finally {
    button.disabled = false;
  }
});

function visibleListings() {
  const { countries, marketplaces } = state.facet;
  return (state.response?.listings || []).filter(
    (l) =>
      (!countries.size || countries.has(l.country)) &&
      (!marketplaces.size || marketplaces.has(l.marketplace_id))
  );
}

function renderFacets() {
  const listings = state.response?.listings || [];
  const countByCountry = new Map();
  const countByMarket = new Map();
  for (const listing of listings) {
    countByCountry.set(listing.country, (countByCountry.get(listing.country) || 0) + 1);
    const key = listing.marketplace_id;
    if (!countByMarket.has(key)) countByMarket.set(key, { name: listing.marketplace_name, n: 0 });
    countByMarket.get(key).n += 1;
  }

  const makeFacet = (label, count, on, toggle) =>
    el('button', { class: `facet${on ? ' on' : ''}`, onclick: toggle },
      el('span', { text: label }), el('span', { class: 'n', text: count }));

  const countryName = (code) =>
    state.catalog.countries.find((c) => c.code === code)?.name || code;

  const nodes = [el('h3', { text: 'Country' })];
  [...countByCountry.entries()].sort((a, b) => b[1] - a[1]).forEach(([code, n]) =>
    nodes.push(makeFacet(countryName(code), n, state.facet.countries.has(code), () => {
      state.facet.countries.has(code) ? state.facet.countries.delete(code) : state.facet.countries.add(code);
      renderFacets(); renderResults();
    }))
  );

  nodes.push(el('h3', { text: 'Marketplace' }));
  [...countByMarket.entries()].sort((a, b) => b[1].n - a[1].n).forEach(([id, info]) =>
    nodes.push(makeFacet(info.name, info.n, state.facet.marketplaces.has(id), () => {
      state.facet.marketplaces.has(id) ? state.facet.marketplaces.delete(id) : state.facet.marketplaces.add(id);
      renderFacets(); renderResults();
    }))
  );

  if (state.facet.countries.size || state.facet.marketplaces.size) {
    nodes.push(el('button', {
      class: 'ghost', style: 'margin-top:.7rem', text: 'Clear filters',
      onclick: () => { state.facet.countries.clear(); state.facet.marketplaces.clear(); renderFacets(); renderResults(); },
    }));
  }
  $('#facets').replaceChildren(...nodes);
}

function renderResults() {
  const listings = visibleListings();
  const stats = state.response.stats;
  $('#stats').textContent =
    `${listings.length} of ${stats.listings_total} listings · ` +
    `${stats.markets_ok}/${stats.markets_queried} marketplaces answered · ` +
    `${stats.duplicates_removed} duplicates removed · ${(stats.elapsed_ms / 1000).toFixed(1)}s`;

  if (!listings.length) {
    $('#results').replaceChildren(el('p', { class: 'empty', text: 'Nothing found. Try a broader term, or enable more sites.' }));
    return;
  }

  $('#results').replaceChildren(...listings.map((listing) => {
    // Only http(s) images, and quote-escaped — a listing title/image URL is
    // attacker-controlled text from a marketplace we do not run.
    const safeImage = /^https?:\/\//i.test(listing.image || '')
      ? listing.image.replace(/["'\\()\s]/g, encodeURIComponent)
      : null;
    const thumb = safeImage
      ? el('div', { class: 'thumb', style: `background-image:url("${safeImage}")` })
      : el('div', { class: 'thumb', text: '📦' });

    const priceLine = el('div', { class: 'prices' },
      el('span', { class: 'price', text: eur(listing.price_eur) }),
      listing.price && listing.currency !== 'EUR'
        ? el('span', { class: 'landed', text: `${listing.price.toLocaleString()} ${listing.currency}` })
        : null,
    );

    const landed = listing.landed_cost_eur !== null && listing.country !== 'PT'
      ? el('div', { class: 'landed', text: `${eur(listing.landed_cost_eur)} delivered · +${eur(listing.shipping_cost_eur)} shipping` })
      : el('div', { class: 'landed', text: listing.country === 'PT' ? 'Local — collect in person' : '' });

    return el('article', { class: 'card' },
      thumb,
      el('div', { class: 'body' },
        el('a', { class: 'title', href: listing.url, target: '_blank', rel: 'noopener noreferrer', text: listing.title }),
        priceLine,
        landed,
        el('div', { class: 'meta' },
          el('span', { class: 'badge country', text: listing.country }),
          el('span', { class: 'badge', text: listing.marketplace_name }),
          listing.condition ? el('span', { class: 'badge', text: listing.condition }) : null,
          el('span', {
            class: 'badge ship', text: '🚚 routes',
            onclick: () => openShippingDrawer(listing),
          }),
        ),
      ),
    );
  }));
}

function renderMarketStatus() {
  const problems = (state.response.results || []).filter((r) => r.status !== 'ok');
  if (!problems.length) { $('#market-status').replaceChildren(); return; }

  const badgeClass = { manual: 'warn', needs_auth: 'warn', empty: '', error: 'bad' };
  $('#market-status').replaceChildren(
    el('h3', { text: `Marketplaces needing attention (${problems.length})` }),
    ...problems.map((result) =>
      el('div', { class: 'status-row' },
        el('span', { class: 'name', text: `${result.country} · ${result.marketplace_name}` }),
        el('span', { class: `badge ${badgeClass[result.status] || ''}`, text: result.status.replace('_', ' ') }),
        el('span', { class: 'msg', text: result.error || '' }),
        result.search_url
          ? el('a', { href: result.search_url, target: '_blank', rel: 'noopener noreferrer', text: 'open ↗' })
          : null,
      )
    )
  );
}

// ── shipping drawer ───────────────────────────────────────────────────────
async function openShippingDrawer(listing) {
  $('#drawer-backdrop').classList.remove('hidden');
  $('#drawer').classList.remove('hidden');
  $('#drawer-body').replaceChildren(el('p', {}, el('span', { class: 'spinner' }), ' working out routes…'));

  const params = new URLSearchParams({ country: listing.country, title: listing.title });
  if (listing.price_eur !== null) params.set('price_eur', listing.price_eur);
  if (listing.ships) params.set('native', 'true');

  try {
    const plan = await api('/api/shipping?' + params.toString());
    $('#drawer-body').replaceChildren(
      el('h2', { text: listing.title }),
      el('p', { class: 'sub', text:
        `${listing.marketplace_name} · ${listing.country} → PT · zone ${plan.zone} · ` +
        `est. ${plan.weight_kg}kg${plan.bulky ? ' · bulky' : ''}` }),
      ...plan.options.map(renderRoute)
    );
  } catch (err) {
    $('#drawer-body').replaceChildren(el('p', { class: 'empty', text: 'Could not load routes: ' + err.message }));
  }
}

function renderRoute(option) {
  return el('div', { class: `route${option.recommended ? ' top' : ''}` },
    el('div', { class: 'head' },
      el('span', { class: 'cost', text: eur(option.cost_eur) }),
      el('span', { class: 'name', text: option.name }),
      option.recommended ? el('span', { class: 'badge ok', text: 'best pick' }) : null,
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

const closeDrawer = () => {
  $('#drawer').classList.add('hidden');
  $('#drawer-backdrop').classList.add('hidden');
};
$('#drawer-close').addEventListener('click', closeDrawer);
$('#drawer-backdrop').addEventListener('click', closeDrawer);
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeDrawer(); });

// ── marketplaces tab ──────────────────────────────────────────────────────
function renderMarkets() {
  const byCountry = new Map();
  for (const market of state.catalog.marketplaces) {
    if (!byCountry.has(market.country)) byCountry.set(market.country, []);
    byCountry.get(market.country).push(market);
  }
  const blocks = state.catalog.countries
    .filter((country) => byCountry.has(country.code))
    .map((country) => {
      const markets = byCountry.get(country.code).sort((a, b) => a.rank - b.rank || a.name.localeCompare(b.name));
      return el('section', { class: 'country-block' },
        el('h2', {}, `${country.name} (${country.code})`,
          el('span', { class: 'zone', text: `shipping zone ${country.zone} · ${country.currency}` })),
        ...markets.map((market) =>
          el('div', { class: 'market-card' },
            el('div', { class: 'head' },
              el('strong', { text: `${market.rank}. ${market.name}` }),
              el('a', { href: market.site, target: '_blank', rel: 'noopener noreferrer', class: 'badge', text: 'visit ↗' }),
              el('span', { class: 'badge', text: market.engine }),
              el('span', { class: `badge ${market.enabled ? 'ok' : ''}`, text: market.enabled ? 'searched by default' : 'off by default' }),
              market.ships_to_pt ? el('span', { class: 'badge ok', text: 'ships to PT' }) : null,
              el('span', { class: `badge ${market.confidence === 'high' ? 'ok' : market.confidence === 'low' ? 'bad' : 'warn'}`,
                           text: `${market.confidence} confidence` }),
              market.configured ? el('span', { class: 'badge ok', text: 'account stored' }) : null,
            ),
            market.why ? el('p', { class: 'why', text: market.why }) : null,
            market.shipping_notes ? el('p', { class: 'ship-note' }, el('b', { text: 'Shipping: ' }), market.shipping_notes) : null,
          )
        ),
      );
    });
  $('#markets').replaceChildren(...blocks);
}

// ── accounts tab ──────────────────────────────────────────────────────────
async function loadAccounts() {
  let data;
  try { data = await api('/api/accounts'); }
  catch (err) { $('#accounts').replaceChildren(el('p', { class: 'empty', text: err.message })); return; }

  $('#accounts').replaceChildren(...data.accounts.map((account) => {
    const field = account.kind === 'api_key' ? 'client_id' : account.kind === 'session' ? 'cookie' : 'note';
    const input = el('input', {
      type: 'password',
      placeholder: account.kind === 'api_key' ? 'client_id:client_secret' : 'paste session cookie',
    });

    const save = el('button', { class: 'ghost', text: 'Save', onclick: async () => {
      const raw = input.value.trim();
      if (!raw) return;
      const body = {};
      if (account.kind === 'api_key' && raw.includes(':')) {
        const [id, ...rest] = raw.split(':');
        body.client_id = id; body.client_secret = rest.join(':');
      } else if (field === 'cookie') { body.cookie = raw; }
      else { body[field] = raw; }
      save.textContent = '…';
      try {
        await api(`/api/accounts/${account.id}`, {
          method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
        });
        input.value = ''; loadAccounts();
      } catch (err) { save.textContent = 'failed'; console.error(err); }
    }});

    const clear = account.configured
      ? el('button', { class: 'ghost', text: 'Forget', onclick: async () => {
          await api(`/api/accounts/${account.id}`, { method: 'DELETE' }); loadAccounts();
        }})
      : null;

    return el('div', { class: 'account-row' },
      el('div', {},
        el('div', {},
          el('strong', { text: account.name }),
          ' ',
          el('span', { class: 'badge country', text: account.country }),
          ' ',
          el('span', { class: 'badge', text: account.kind }),
          ' ',
          account.required_for_search
            ? el('span', { class: 'badge warn', text: 'required to search' })
            : el('span', { class: 'badge', text: 'optional — search works anonymously' }),
          account.captcha ? el('span', { class: 'badge warn', text: ' CAPTCHA at signup' }) : null,
          account.configured ? el('span', { class: 'badge ok', text: ' ✓ stored' }) : null,
        ),
        account.notes ? el('div', { class: 'sub', text: account.notes }) : null,
        account.signup_url
          ? el('div', { class: 'sub' },
              el('a', { href: account.signup_url, target: '_blank', rel: 'noopener noreferrer', text: 'Open signup page ↗' }),
              account.signup_method?.length ? ` · sign up with ${account.signup_method.join(', ')}` : '')
          : null,
      ),
      el('div', { class: 'actions' }, input, save, clear),
    );
  }));
}

// ── shipping tab ──────────────────────────────────────────────────────────
function renderShipCountries() {
  $('#ship-country').replaceChildren(
    ...state.catalog.countries
      .filter((c) => c.code !== 'EU')
      .map((c) => el('option', { value: c.code, selected: c.code === 'DE' }, `${c.name} (${c.code})`))
  );
}

$('#ship-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const params = new URLSearchParams({ country: $('#ship-country').value });
  if ($('#ship-item').value) params.set('title', $('#ship-item').value);
  if ($('#ship-price').value) params.set('price_eur', $('#ship-price').value);
  if ($('#ship-weight').value) params.set('weight_kg', $('#ship-weight').value);

  $('#ship-results').replaceChildren(el('p', {}, el('span', { class: 'spinner' }), ' ranking routes…'));
  try {
    const plan = await api('/api/shipping?' + params.toString());
    $('#ship-results').replaceChildren(
      el('p', { class: 'lede', text:
        `${plan.country} → PT · zone ${plan.zone} · estimated ${plan.weight_kg}kg${plan.bulky ? ', bulky' : ''} · ` +
        `${plan.options.length} viable routes` }),
      ...plan.options.map(renderRoute)
    );
  } catch (err) {
    $('#ship-results').replaceChildren(el('p', { class: 'empty', text: err.message }));
  }
});
