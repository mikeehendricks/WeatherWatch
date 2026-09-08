const labels = {0:'Clear sky',1:'Mainly clear',2:'Partly cloudy',3:'Overcast',45:'Fog',48:'Rime fog',51:'Light drizzle',53:'Drizzle',55:'Heavy drizzle',61:'Light rain',63:'Rain',65:'Heavy rain',71:'Light snow',80:'Rain showers',81:'Rain showers',82:'Heavy showers',95:'Thunderstorm',96:'Thunderstorm',99:'Severe thunderstorm'};
const caps = {normal:'Normal',watch:'WeatherWatch',moderate:'Moderate',heavy:'Heavy / Strong',extreme:'Extreme'};
const esc = value => String(value ?? '').replace(/[&<>'"]/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[char]));
const number = (value, fallback = 0) => Number.isFinite(Number(value)) ? Number(value) : fallback;
const dayName = (date, index) => index === 0 ? 'Today' : new Date(`${date}T12:00:00`).toLocaleDateString([], {weekday:'short'});

function forecastHtml(days = []) {
  return `<div class="forecast" aria-label="Five-day forecast">${days.map((day, index) => `
    <div class="forecast-day">
      <span>${esc(dayName(day.date, index))}</span>
      <i class="${esc(day.severity)}" title="${esc(caps[day.severity])}"></i>
      <b>${Math.round(number(day.temperature_max))}° <small>${Math.round(number(day.temperature_min))}°</small></b>
      <em>${number(day.rain).toFixed(1)} mm</em>
      <small>${esc(labels[day.weather_code] || 'Weather')}</small>
    </div>`).join('')}</div>`;
}

async function load() {
  const notice = document.querySelector('#notice');
  try {
    const response = await fetch('/api/weather', {headers:{Accept:'application/json'}, cache:'no-store'});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Could not load weather.');
    document.querySelector('#grid').innerHTML = data.locations.map(location => `
      <article class="card severity-${esc(location.severity)}">
        <div class="card-top"><div><small>SITE</small><h2>${esc(location.name)}</h2></div><span class="badge"><i></i>${esc(caps[location.severity])}</span></div>
        <p class="condition">${esc(labels[location.current.weather_code] || 'Weather update')}</p>
        <p class="address">${esc(location.address)}</p>
        <div class="metrics">
          <div><small>Temperature</small><b>${Math.round(number(location.current.temperature_2m))}°C</b><em>Feels ${Math.round(number(location.current.apparent_temperature))}°</em></div>
          <div><small>24h rain</small><b>${number(location.rain).toFixed(1)} <em>mm</em></b><em>Today's forecast</em></div>
          <div><small>Max gust</small><b>${Math.round(number(location.gust))} <em>kph</em></b><em>Today's forecast</em></div>
        </div>
        ${forecastHtml(location.forecast)}
        <div class="source-line"><b>Source:</b> ${esc(location.source)} <span>• ${esc(location.selection)}</span></div>
        <div class="card-foot"><span>${number(location.latitude).toFixed(4)}, ${number(location.longitude).toFixed(4)}</span><span>${esc(location.plus_code)}</span></div>
      </article>`).join('');
    document.querySelector('#updated').textContent = `Updated ${new Date(data.updated_at).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'})}`;
    notice.hidden = true;
  } catch (error) {
    notice.textContent = `${error.message} Retrying automatically.`;
    notice.hidden = false;
    document.querySelector('#updated').textContent = 'Connection issue';
  }
}

async function heartbeat() {
  const token = document.querySelector('meta[name="csrf-token"]')?.content;
  if (!token || document.visibilityState !== 'visible') return;
  try {
    await fetch('/api/visitor-heartbeat', {method:'POST', headers:{'X-CSRF-Token':token}, cache:'no-store'});
  } catch (_) { /* Weather refresh will surface connectivity errors. */ }
}

load();
setInterval(load, 300000);
setInterval(heartbeat, 120000);
