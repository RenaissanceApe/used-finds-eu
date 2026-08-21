# (f) Getting it to Portugal, including the unconventional routes

Most of the good stuff is in Germany, Poland or Spain, and most of those ads say
"envío solo nacional" / "Versand nur innerhalb Deutschlands". That is a **soft**
constraint. Almost every one of those sellers will hand over a parcel if the
label is already paid for and the drop-off is 300 metres away. Nearly everything
below is a variation on *removing work and risk from the seller* rather than
persuading them to take on more.

The app ranks these automatically per listing (the 🚚 **routes** button on any
result card, or `ufeu ship DE -i "washing machine" -p 150`). Ranking is by cost
**plus** an effort and risk penalty, because the cheapest route is very often
the one that costs you a Saturday.

The data lives in `backend/ufeu/data/shipping.yaml` — edit costs there as you
learn real numbers.

---

## The five that matter most

### 1. Prepaid label — the highest-leverage trick here

You buy the cross-border label yourself on a broker (Packlink PRO, Eurosender,
Sendcloud, ParcelABC), email the seller a PDF and QR code, and they drop the
parcel at a shop down the road. The seller pays nothing, fills in no customs
form (there is none inside the EU), and takes no risk. **This is why sellers who
"don't ship abroad" almost always say yes to it** — their objection was never
about geography, it was about hassle. Brokers also resell carrier contracts at
30–60% below counter rates, so it is usually cheaper than what the seller would
have paid anyway.

Sequence that protects you: agree the sale in writing → get real dimensions and
weight → buy the label → send it → **pay only once tracking shows "accepted at
drop-off"**. Insure above €100; broker default cover is typically €25.

### 2. Platform-native shipping — always check this first

Vinted, eBay International Shipping and OLX Envios handle the label, the money
and the dispute process themselves. Vinted is the standout: its connected
country pools mean a seller in France or Italy can ship to Portugal inside the
app, with Buyer Protection, at a price that undercuts anything you could
arrange. If the item exists on Vinted, buy it on Vinted and stop reading.

### 3. Spanish border pickup — Portugal's structural advantage

Portugal's only land border is with the EU's second-largest second-hand market,
and Spanish domestic shipping is cheap and universally offered. So: ask the
seller for **plain domestic Correos/SEUR shipping** — completely normal for
them, zero friction — to a Correos office in a border town, and collect by car:

| Office | Nearest PT crossing | Drive |
| --- | --- | --- |
| Tui (Pontevedra) | Valença | ~5 min |
| Badajoz | Elvas | ~15 min |
| Ayamonte (Huelva) | Vila Real de Santo António | ~10 min |
| Vigo / Salamanca | larger depots, more capacity | 1–2 h |

Correos holds parcels 15 days, so you can batch several purchases into one trip
— which you should, or the fuel eats the saving. For anything bulky (furniture,
bikes, appliances) this is dramatically cheaper than international freight.

### 4. Diaspora vans — the genuinely unconventional one

Dozens of small Portuguese transport firms run **weekly vans** along the
emigration corridors — France, Luxembourg, Switzerland, Germany, Belgium — door
to door, priced by volume rather than by chargeable weight. They will happily
take a washing machine, a motorbike fairing or six boxes of books, at a fraction
of what a courier charges for the same mass. France is by far the densest
corridor.

Finding them is the hard part: most live on Facebook groups rather than
websites. Search *"transporte de encomendas França Portugal"*, *"carrinhas para
Portugal"*, or the same with Luxemburgo / Alemanha / Suíça, plus your region.

Honest caveats, and they matter: this is an informal sector. No tracking, no
insurance, schedules slip by days. Use an operator with a real trading history
and reviews you can read; pay part on pickup and the rest on delivery; get the
driver's phone number and plate. **Ideal for bulky, low-value-density goods.
Never for high-value electronics.**

### 5. InPost lockers — the Poland corridor

Poland is the best-value EU market for used electronics, tools and photo gear,
*and* it has the slickest logistics: OLX Przesyłki runs on InPost Paczkomaty,
and InPost now operates lockers in Portugal. Seller walks to a locker, you
collect from a locker, nobody queues at a post office. Central Europe's
equivalent is **Packeta/Zásilkovna** (CZ/SK/HU/RO), which also delivers to
Portuguese pickup points — and Bazoš and Jófogás sellers already use it daily.

---

## The rest of the toolkit

| Route | Best for | Rough cost | Watch out for |
| --- | --- | --- | --- |
| **Forwarding address (ES)** | consolidating several Spanish buys | €14 + €1.1/kg | consolidation is where the saving is |
| **Forwarding address (DE)** | German sellers who refuse to ship abroad | €19 + €1.6/kg | storage fees after ~30 days |
| **Coach freight** (ALSA, Rede Expressos) | odd-shaped Iberian items, fast | €18 + €0.5/kg | station-to-station only |
| **Pallet freight** (Palletways, Raben) | furniture, machine tools, engines | €95 + €0.18/kg | absurd for a €60 chair, excellent for a €900 lathe |
| **Hand-carry on a flight** | dense, valuable, small (lenses, tools, vinyl) | €40–60 flat | 23kg has *no per-kilo penalty*; lithium batteries go in the cabin |
| **Crowdshipping** (Worldcraze, PiggyBee) | small items couriers refuse | €20 + €1.5/kg | matching is slow; keep value low |
| **Proxy buyer / inspection** | high-value buys with no buyer protection | €25–55 on top | an *overlay*, not a route — still needs one of the above |

## Two things worth internalising

**Landed cost is the only number that matters.** A €19 sofa in Romania and a
€107 sofa in Braga are not what they look like: shipping the Romanian one costs
€103, and the app will tell you so. Sort by *Cheapest delivered to PT* and the
comparison becomes honest. Set `sort: landed_asc` and the whole tool changes
character.

**A proxy buyer is insurance, not transport.** On platforms with no buyer
protection — Kleinanzeigen, Bazoš, SS.lv — the real risk is not the shipping, it
is that the item is not what the photos claim. Someone local who meets the
seller, tests the item and pays cash turns a stranger-danger transaction into a
normal one. Worth the coordination above roughly €300 of item value; the
resolver ranks it last on purpose, because you still need a real route on top.
