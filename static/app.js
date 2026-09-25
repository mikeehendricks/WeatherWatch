const labels = {0:'Clear sky',1:'Mainly clear',2:'Partly cloudy',3:'Overcast',45:'Fog',48:'Rime fog',51:'Light drizzle',53:'Drizzle',55:'Heavy drizzle',61:'Light rain',63:'Rain',65:'Heavy rain',71:'Light snow',80:'Rain showers',81:'Rain showers',82:'Heavy showers',95:'Thunderstorm',96:'Thunderstorm',99:'Severe thunderstorm'};
const glyphs = {0:'☀︎',1:'☀︎',2:'◒',3:'☁︎',45:'≋',48:'≋',51:'☂︎',53:'☂︎',55:'☂︎',61:'☂︎',63:'☂︎',65:'☂︎',71:'❄︎',80:'☂︎',81:'☂︎',82:'☂︎',95:'ϟ',96:'ϟ',99:'ϟ'};
const caps = {normal:'Normal',watch:'WeatherWatch',moderate:'Moderate',heavy:'Heavy / Strong',extreme:'Extreme'};
const esc = value => String(value ?? '').replace(/[&<>'"]/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[char]));
const number = (value, fallback = 0) => Number.isFinite(Number(value)) ? Number(value) : fallback;
const dayName = (date, index) => index === 0 ? 'Today' : new Date(`${date}T12:00:00`).toLocaleDateString([], {weekday:'short'});

function forecastHtml(days = []) {
  return `<div class="forecast" aria-label="Five-day forecast">${days.map((day, index) => `
    <button type="button" class="forecast-day" data-forecast-date="${esc(day.date)}" aria-pressed="false" title="Show hourly forecast for ${esc(dayName(day.date, index))}">
      <span>${esc(dayName(day.date, index))}</span>
      <span class="forecast-symbol" aria-label="${esc(labels[day.weather_code] || 'Weather')}">${glyphs[day.weather_code] || '◌'}</span>
      <b>${Math.round(number(day.temperature_max))}° <small>${Math.round(number(day.temperature_min))}°</small></b>
      <em title="MET Norway daily forecast rainfall total"><i class="${esc(day.severity)}"></i>${number(day.rain).toFixed(1)} mm</em><small class="forecast-caption">View hourly forecast</small>
    </button>`).join('')}</div>`;
}

function hourlyItemsHtml(hours = [], markNow = false) {
  return hours.map((hour, index) => {
    const date = new Date(hour.time);
    const time = markNow && index === 0 ? 'Now' : date.toLocaleTimeString([], {hour:'numeric'});
    const code = number(hour.weather_code);
    return `<div class="hour-item">
      <time datetime="${esc(hour.time)}">${esc(time)}</time>
      <span class="hour-glyph" title="${esc(labels[code] || 'Weather')}">${glyphs[code] || '◌'}</span>
      <b>${Math.round(number(hour.temperature))}°</b>
      <small>Feels ${Math.round(number(hour.apparent_temperature))}°</small>
      <span class="hour-rain" title="Forecast precipitation probability and amount">☂ ${Math.round(number(hour.precipitation_probability))}%</span>
      <small>${number(hour.precipitation).toFixed(1)} mm</small>
      <small title="Forecast sustained wind speed">Wind ${Math.round(number(hour.wind_gust))} kph</small>
    </div>`;
  }).join('');
}

function hourlyHtml(hours = []) {
  if (!hours.length) return '';
  return `<details class="hourly-panel">
    <summary><span><b class="hourly-title">Next 24 hours</b><small>MET Norway hourly forecast · Philippine time</small></span><i aria-hidden="true">⌄</i></summary>
    <div class="hourly-scroll" tabindex="0" aria-label="Scrollable 24-hour weather forecast"></div>
  </details>`;
}

function atmosphereFor(code) {
  if ([95,96,99].includes(code)) return 'storm';
  if ([80,81,82].includes(code)) return 'showers';
  if ([61,63,65,66,67,71,73,75].includes(code)) return 'rainy';
  if ([51,53,55,56,57].includes(code)) return 'drizzle';
  if ([45,48].includes(code)) return 'foggy';
  if (code === 3) return 'overcast';
  if (code === 2) return 'partly-cloudy';
  return 'sunny';
}

const radarSiteZoom = 14;
let radarFrames = [];
let radarTimer = null;
let radarRequest = null;
let radarMap = null;
let radarLayer = null;
let radarMarker = null;
let radarTileHost = '';

function showRadarFrame(index) {
  if (!radarFrames.length || !radarMap) return;
  const safeIndex = Math.max(0, Math.min(index, radarFrames.length - 1));
  const frame = radarFrames[safeIndex];
  const slider = document.querySelector('#radar-slider');
  if (radarLayer) radarMap.removeLayer(radarLayer);
  const radarStatus = document.querySelector('#radar-status');
  const radarLegend = document.querySelector('.radar-legend');
  radarStatus.hidden = false;
  radarStatus.className = 'radar-status checking';
  radarStatus.querySelector('span').textContent = 'Checking radar echoes…';
  radarLegend.hidden = false;
  let loadedTiles = 0;
  let echoTiles = 0;
  radarLayer = L.tileLayer(`${radarTileHost}${frame.path}/256/{z}/{x}/{y}/2/1_1.png`, {
    opacity:.92, zIndex:400, maxNativeZoom:7, maxZoom:12, tileSize:256,
    crossOrigin:true, attribution:'Radar © RainViewer'
  });
  radarLayer.on('tileload', event => {
    loadedTiles += 1;
    try {
      const canvas = document.createElement('canvas');
      canvas.width = 32; canvas.height = 32;
      const context = canvas.getContext('2d', {willReadFrequently:true});
      context.drawImage(event.tile, 0, 0, 32, 32);
      const pixels = context.getImageData(0, 0, 32, 32).data;
      for (let pixel = 3; pixel < pixels.length; pixel += 4) {
        if (pixels[pixel] > 40) { echoTiles += 1; break; }
      }
    } catch (_) { echoTiles = Math.max(echoTiles, 1); }
    radarStatus.className = `radar-status ${echoTiles ? 'echoes' : 'clear'}`;
    radarStatus.querySelector('span').textContent = echoTiles
      ? 'Observed precipitation shown'
      : `No precipitation detected in ${loadedTiles} map tile${loadedTiles === 1 ? '' : 's'}`;
  });
  radarLayer.on('tileerror', () => {
    radarStatus.className = 'radar-status unavailable';
    radarStatus.querySelector('span').textContent = 'Radar coverage unavailable';
  });
  radarLayer.addTo(radarMap);
  slider.value = safeIndex;
  document.querySelector('#radar-time').textContent = new Date(frame.time * 1000).toLocaleTimeString([], {hour:'numeric', minute:'2-digit'});
}

function stopRadar() {
  if (radarTimer) clearInterval(radarTimer);
  radarTimer = null;
  const button = document.querySelector('#radar-play');
  button.innerHTML = '<svg aria-hidden="true" viewBox="0 0 48 48"><path d="M9 5.5v37L41 24 9 5.5z"/></svg>';
  button.setAttribute('aria-label', 'Play radar timeline');
  button.title = 'Play';
}

function playRadar() {
  if (!radarFrames.length) return;
  if (radarTimer) { stopRadar(); return; }
  const slider = document.querySelector('#radar-slider');
  const button = document.querySelector('#radar-play');
  button.innerHTML = '<svg aria-hidden="true" viewBox="0 0 48 48"><rect x="10" y="6" width="10" height="36" rx="1.5"/><rect x="28" y="6" width="10" height="36" rx="1.5"/></svg>';
  button.setAttribute('aria-label', 'Pause radar timeline');
  button.title = 'Pause';
  radarTimer = setInterval(() => showRadarFrame((Number(slider.value) + 1) % radarFrames.length), 850);
}

async function loadRadar(card) {
  stopRadar();
  if (radarRequest) radarRequest.abort();
  radarRequest = new AbortController();
  const stage = document.querySelector('#radar-stage');
  const placeholder = stage.querySelector('.radar-placeholder');
  const button = document.querySelector('#radar-play');
  const slider = document.querySelector('#radar-slider');
  radarFrames = [];
  if (radarLayer && radarMap) { radarMap.removeLayer(radarLayer); radarLayer = null; }
  document.querySelector('#radar-status').hidden = true;
  document.querySelector('.radar-legend').hidden = true;
  placeholder.hidden = false;
  placeholder.innerHTML = '<span aria-hidden="true">↻</span><b>Loading live radar…</b><small>Retrieving recent observations.</small>';
  button.disabled = true; slider.disabled = true;
  document.querySelector('#radar-title').textContent = `Rain near ${card.dataset.siteName}`;
  document.querySelector('#radar-forecast').textContent = `Next hour · ${number(card.dataset.nextHourRain).toFixed(1)} mm MET Norway forecast`;
  try {
    const response = await fetch(`/api/radar?location_id=${encodeURIComponent(card.dataset.locationId)}`, {signal:radarRequest.signal, cache:'no-store'});
    const data = await response.json();
    if (!response.ok || !data.frames?.length) throw new Error(data.error || 'No radar frames available.');
    radarFrames = data.frames;
    radarTileHost = data.tile_host;
    const center = [number(data.latitude), number(data.longitude)];
    if (!radarMap) {
      radarMap = L.map('radar-map', {zoomControl:true, attributionControl:true}).setView(center, radarSiteZoom);
      L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom:19, attribution:'© OpenStreetMap contributors'
      }).addTo(radarMap);
    } else {
      radarMap.setView(center, radarSiteZoom);
    }
    if (radarMarker) radarMap.removeLayer(radarMarker);
    radarMarker = L.circleMarker(center, {radius:7, color:'#fff', weight:3, fillColor:'#d70015', fillOpacity:1})
      .bindTooltip(card.dataset.siteName, {direction:'top'}).addTo(radarMap);
    setTimeout(() => radarMap.invalidateSize(), 0);
    slider.max = radarFrames.length - 1;
    slider.value = radarFrames.length - 1;
    slider.disabled = false; button.disabled = false; placeholder.hidden = true;
    document.querySelector('#radar-description').textContent = 'Observed radar playback for the last two hours. Transparent radar areas mean no detected precipitation or unavailable coverage.';
    showRadarFrame(radarFrames.length - 1);
  } catch (error) {
    if (error.name === 'AbortError') return;
    placeholder.innerHTML = `<span aria-hidden="true">!</span><b>Radar unavailable</b><small>${esc(error.message)}</small>`;
  }
}

function selectSite(card) {
  document.querySelectorAll('.weather-card[aria-pressed]').forEach(item => item.setAttribute('aria-pressed', String(item === card)));
  const shell = document.querySelector('.site-shell');
  shell.dataset.weather = atmosphereFor(Number(card.dataset.weatherCode));
  shell.dataset.selectedSite = card.dataset.siteName;
  const condition = labels[Number(card.dataset.weatherCode)] || 'current weather';
  const hint = document.querySelector('#scene-hint');
  hint.textContent = `● ${card.dataset.siteName} · MET Norway modeled: ${condition}`;
  loadRadar(card);
  card.scrollIntoView({behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block:'nearest'});
}

let latestLocations = [];

function bindHourlyPanels() {
  document.querySelectorAll('.weather-card .hourly-panel').forEach(panel => {
    panel.addEventListener('toggle', () => {
      const scroll = panel.querySelector('.hourly-scroll');
      if (!panel.open || scroll.children.length) return;
      const card = panel.closest('.weather-card');
      const location = latestLocations.find(item => Number(item.id) === Number(card?.dataset.locationId));
      if (!location) return;
      scroll.innerHTML = hourlyItemsHtml((location.hourly_forecast || []).slice(0, 24), true);
      scroll.classList.add('hourly-enter');
    });
  });
}

function bindForecastDays() {
  document.querySelectorAll('.forecast-day[data-forecast-date]').forEach(button => {
    button.addEventListener('click', async event => {
      event.stopPropagation();
      const card = button.closest('.weather-card');
      const location = latestLocations.find(item => Number(item.id) === Number(card?.dataset.locationId));
      const panel = card?.querySelector('.hourly-panel');
      if (!location || !panel) return;
      const date = button.dataset.forecastDate;
      const wasSelected = button.getAttribute('aria-pressed') === 'true';
      const buttons = card.querySelectorAll('.forecast-day');
      buttons.forEach(item => item.setAttribute('aria-pressed', 'false'));
      clearTimeout(panel._closeTimer);

      if (wasSelected) {
        panel.classList.add('is-closing');
        panel._closeTimer = setTimeout(() => {
          panel.open = false;
          panel.classList.remove('is-closing');
          panel.querySelector('.hourly-title').textContent = 'Next 24 hours';
        }, 180);
        return;
      }

      button.setAttribute('aria-pressed', 'true');
      button.classList.remove('day-selected');
      void button.offsetWidth;
      button.classList.add('day-selected');
      const label = button.querySelector(':scope > span')?.textContent || date;
      panel.querySelector('.hourly-title').textContent = `${label} hourly forecast`;
      const hourlyScroll = panel.querySelector('.hourly-scroll');
      panel.classList.remove('is-closing');
      panel.open = true;
      hourlyScroll.innerHTML = '<p class="hourly-empty">Loading hourly forecast…</p>';
      let hours = [];
      const currentDate = String(location.current?.time || '').slice(0, 10);
      try {
        if (date === currentDate) {
          hours = (location.hourly_forecast || []).filter(hour => String(hour.time).startsWith(date));
        } else {
          location.hourly_days ||= {};
          if (!location.hourly_days[date]) {
            const response = await fetch(`/api/hourly/${number(location.id)}?date=${encodeURIComponent(date)}`, {headers:{Accept:'application/json'}, cache:'no-store'});
            const payload = await response.json();
            if (!response.ok) throw new Error(payload.error || 'Hourly forecast unavailable.');
            location.hourly_days[date] = payload.hours;
          }
          hours = location.hourly_days[date];
        }
        if (button.getAttribute('aria-pressed') !== 'true') return;
        hourlyScroll.innerHTML = hours.length ? hourlyItemsHtml(hours, date === currentDate) : '<p class="hourly-empty">Hourly forecast is unavailable for this day.</p>';
      } catch (error) {
        if (button.getAttribute('aria-pressed') !== 'true') return;
        hourlyScroll.innerHTML = `<p class="hourly-empty">${esc(error.message)}</p>`;
      }
      hourlyScroll.classList.remove('hourly-enter');
      void hourlyScroll.offsetWidth;
      hourlyScroll.classList.add('hourly-enter');
      panel.scrollIntoView({behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block:'nearest'});
    });
  });
}

function bindSiteScenes() {
  const cards = [...document.querySelectorAll('.weather-card[data-weather-code]')];
  cards.forEach(card => {
    card.addEventListener('click', event => { if (!event.target.closest('button,details,summary,.hourly-scroll')) selectSite(card); });
    card.addEventListener('keydown', event => {
      if (event.target.closest('details,summary,.hourly-scroll')) return;
      if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); selectSite(card); }
    });
  });
  const selected = document.querySelector('.site-shell').dataset.selectedSite;
  const previous = cards.find(card => card.dataset.siteName === selected);
  if (previous) selectSite(previous);
}

async function load() {
  const notice = document.querySelector('#notice');
  try {
    // The revision query prevents an upstream CDN rule from serving a color
    // classification created before the matrix was recalibrated.
    const response = await fetch(`/api/weather?refresh=${Date.now()}`, {headers:{Accept:'application/json'}, cache:'no-store'});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Could not load weather.');
    latestLocations = data.locations;
    document.querySelector('#grid').innerHTML = data.locations.map(location => {
      const code = location.current.weather_code;
      return `<article class="weather-card severity-${esc(location.severity)}" role="button" tabindex="0" aria-pressed="false" data-weather-code="${number(code)}" data-location-id="${number(location.id)}" data-next-hour-rain="${number(location.next_hour_rain)}" data-site-name="${esc(location.name)}" aria-label="Show ${esc(labels[code] || 'weather')} atmosphere for ${esc(location.name)}">
        <div class="card-heading">
          <div><p class="card-label">Site</p><h2>${esc(location.name)}</h2><p>${esc(location.address)}</p></div>
          <span class="severity-chip"><i></i>${esc(caps[location.severity])}</span>
        </div>
        <div class="current-weather">
          <div class="current-primary"><span class="weather-glyph" aria-hidden="true">${glyphs[code] || '◌'}</span><div><strong>${Math.round(number(location.current.temperature_2m))}°</strong><span>${esc(labels[code] || 'Weather update')}</span><small>Modeled feels-like ${Math.round(number(location.current.apparent_temperature))}°</small></div></div>
          <div class="current-metrics">
            <div><span>Forecast rain today</span><b>${number(location.rain).toFixed(1)} <small>mm</small></b></div>
            <div><span>Max wind</span><b>${Math.round(number(location.gust))} <small>kph</small></b></div>
          </div>
        </div>
        ${hourlyHtml(location.hourly_forecast)}
        ${forecastHtml(location.forecast)}
        <div class="card-meta"><span><b>Source</b>${esc(location.source)}</span><span title="${esc(location.plus_code)}">${number(location.latitude).toFixed(3)}, ${number(location.longitude).toFixed(3)}</span></div>
      </article>`;
    }).join('');
    bindSiteScenes();
    bindHourlyPanels();
    bindForecastDays();
    document.querySelector('#updated').textContent = `${data.stale ? 'Last available update' : 'Updated'} ${new Date(data.updated_at).toLocaleTimeString([], {hour:'numeric',minute:'2-digit'})}`;
    notice.hidden = true;
  } catch (error) {
    notice.textContent = `${error.message} Retrying automatically.`;
    notice.hidden = false;
    document.querySelector('#updated').textContent = 'Unable to refresh';
  }
}

async function heartbeat() {
  const token = document.querySelector('meta[name="csrf-token"]')?.content;
  if (!token || document.visibilityState !== 'visible') return;
  try { await fetch('/api/visitor-heartbeat', {method:'POST', headers:{'X-CSRF-Token':token}, cache:'no-store'}); }
  catch (_) { /* Weather refresh surfaces connectivity errors. */ }
}

document.querySelector('#radar-play')?.addEventListener('click', playRadar);
document.querySelector('#radar-slider')?.addEventListener('input', event => { stopRadar(); showRadarFrame(Number(event.target.value)); });
document.querySelector('#radar-fullscreen')?.addEventListener('click', async () => {
  const stage = document.querySelector('#radar-stage');
  try {
    if (document.fullscreenElement === stage) await document.exitFullscreen();
    else await stage.requestFullscreen();
  } catch (_) { /* Browser may deny full screen outside a direct user gesture. */ }
});
document.addEventListener('fullscreenchange', () => {
  const button = document.querySelector('#radar-fullscreen');
  const active = document.fullscreenElement === document.querySelector('#radar-stage');
  button.innerHTML = `<span aria-hidden="true">${active ? '×' : '⛶'}</span>`;
  button.setAttribute('aria-label', active ? 'Exit full screen map' : 'Enter full screen map');
  button.title = active ? 'Exit full screen' : 'Full screen';
  setTimeout(() => radarMap?.invalidateSize(), 50);
});

load();
setInterval(load, 300000);
setInterval(heartbeat, 120000);
