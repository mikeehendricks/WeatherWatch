const labels = {0:'Clear sky',1:'Mainly clear',2:'Partly cloudy',3:'Overcast',45:'Fog',48:'Rime fog',51:'Light drizzle',53:'Drizzle',55:'Heavy drizzle',61:'Light rain',63:'Rain',65:'Heavy rain',71:'Light snow',80:'Rain showers',81:'Rain showers',82:'Heavy showers',95:'Thunderstorm',96:'Thunderstorm',99:'Severe thunderstorm'};
const glyphs = {0:'☀︎',1:'☀︎',2:'◒',3:'☁︎',45:'≋',48:'≋',51:'☂︎',53:'☂︎',55:'☂︎',61:'☂︎',63:'☂︎',65:'☂︎',71:'❄︎',80:'☂︎',81:'☂︎',82:'☂︎',95:'ϟ',96:'ϟ',99:'ϟ'};
const caps = {normal:'Normal',watch:'WeatherWatch',moderate:'Moderate',heavy:'Heavy / Strong',extreme:'Extreme'};
const esc = value => String(value ?? '').replace(/[&<>'"]/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[char]));
const number = (value, fallback = 0) => Number.isFinite(Number(value)) ? Number(value) : fallback;
const dayName = (date, index) => index === 0 ? 'Today' : new Date(`${date}T12:00:00`).toLocaleDateString([], {weekday:'short'});

function forecastHtml(days = []) {
  return `<div class="forecast" aria-label="Five-day forecast">${days.map((day, index) => `
    <div class="forecast-day">
      <span>${esc(dayName(day.date, index))}</span>
      <div class="forecast-symbol" aria-label="${esc(labels[day.weather_code] || 'Weather')}">${glyphs[day.weather_code] || '◌'}</div>
      <b>${Math.round(number(day.temperature_max))}° <small>${Math.round(number(day.temperature_min))}°</small></b>
      <em><i class="${esc(day.severity)}"></i>${number(day.rain).toFixed(1)} mm</em>
    </div>`).join('')}</div>`;
}

async function load() {
  const notice = document.querySelector('#notice');
  try {
    const response = await fetch('/api/weather', {headers:{Accept:'application/json'}, cache:'no-store'});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Could not load weather.');
    document.querySelector('#grid').innerHTML = data.locations.map(location => {
      const code = location.current.weather_code;
      return `<article class="weather-card severity-${esc(location.severity)}">
        <div class="card-heading">
          <div><p class="card-label">Site</p><h2>${esc(location.name)}</h2><p>${esc(location.address)}</p></div>
          <span class="severity-chip"><i></i>${esc(caps[location.severity])}</span>
        </div>
        <div class="current-weather">
          <div class="current-primary"><span class="weather-glyph" aria-hidden="true">${glyphs[code] || '◌'}</span><div><strong>${Math.round(number(location.current.temperature_2m))}°</strong><span>${esc(labels[code] || 'Weather update')}</span><small>Feels like ${Math.round(number(location.current.apparent_temperature))}°</small></div></div>
          <div class="current-metrics">
            <div><span>Rain today</span><b>${number(location.rain).toFixed(1)} <small>mm</small></b></div>
            <div><span>Max gust</span><b>${Math.round(number(location.gust))} <small>kph</small></b></div>
          </div>
        </div>
        ${forecastHtml(location.forecast)}
        <div class="card-meta"><span><b>Source</b>${esc(location.source)}</span><span title="${esc(location.plus_code)}">${number(location.latitude).toFixed(3)}, ${number(location.longitude).toFixed(3)}</span></div>
      </article>`;
    }).join('');
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

load();
setInterval(load, 300000);
setInterval(heartbeat, 120000);
