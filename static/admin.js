document.querySelectorAll('form[data-confirm]').forEach(form => {
  form.addEventListener('submit', event => {
    if (!window.confirm(form.dataset.confirm)) { event.preventDefault(); return; }
    if (form.matches('[data-update-form]')) sessionStorage.setItem('weatherwatch-update-pending', '1');
  });
});

document.querySelectorAll('time.local-time').forEach(element => {
  const date = new Date(element.dateTime);
  if (!Number.isNaN(date.getTime())) {
    element.textContent = date.toLocaleString([], {dateStyle:'medium', timeStyle:'short'});
  }
});

const updateStatus = document.querySelector('#live-update-status');
const updateForm = document.querySelector('[data-update-form]');
let sawUpdateRunning = updateStatus?.dataset.status === 'updating' || sessionStorage.getItem('weatherwatch-update-pending') === '1';
let updateReloadScheduled = false;

async function pollUpdateStatus() {
  if (!updateStatus) return;
  try {
    const response = await fetch('/admin/update-status', {headers:{Accept:'application/json'}, cache:'no-store'});
    if (!response.ok) return;
    const state = await response.json();
    const running = state.status === 'updating';
    if (running) {
      sawUpdateRunning = true;
      updateStatus.hidden = false;
      updateStatus.dataset.status = 'updating';
      updateStatus.querySelector('b').textContent = 'Updating WeatherWatch';
      document.querySelector('#update-phase').textContent = state.phase || 'Update in progress';
      const button = updateForm?.querySelector('button');
      if (button) { button.disabled = true; button.textContent = 'Updating…'; }
      return;
    }
    if (sawUpdateRunning && !updateReloadScheduled && ['updated','up_to_date','failed'].includes(state.status)) {
      updateReloadScheduled = true;
      updateStatus.hidden = false;
      updateStatus.dataset.status = state.status;
      updateStatus.querySelector('b').textContent = state.status === 'failed' ? 'Update failed' : 'Update finished';
      document.querySelector('#update-phase').textContent = state.status === 'failed'
        ? (state.error || 'See the service log for details.')
        : (state.updated_version ? `Version ${state.updated_version} is ready. Refreshing…` : 'Refreshing admin page…');
      sessionStorage.removeItem('weatherwatch-update-pending');
      setTimeout(() => window.location.reload(), 1200);
    }
  } catch (_) { /* The service can briefly disconnect while Gunicorn reloads. */ }
}

if (updateStatus) {
  pollUpdateStatus();
  setInterval(pollUpdateStatus, 1500);
}

const exportForm = document.querySelector('.export-form');
if (exportForm) {
  const pad = value => String(value).padStart(2, '0');
  const localValue = date => `${date.getFullYear()}-${pad(date.getMonth()+1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
  const end = new Date();
  const start = new Date(end.getTime() - 24 * 60 * 60 * 1000);
  exportForm.elements.start.value = localValue(start);
  exportForm.elements.end.value = localValue(end);
}
