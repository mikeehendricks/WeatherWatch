document.querySelectorAll('form[data-confirm]').forEach(form => {
  form.addEventListener('submit', event => {
    if (!window.confirm(form.dataset.confirm)) event.preventDefault();
  });
});

document.querySelectorAll('time.local-time').forEach(element => {
  const date = new Date(element.dateTime);
  if (!Number.isNaN(date.getTime())) {
    element.textContent = date.toLocaleString([], {dateStyle:'medium', timeStyle:'short'});
  }
});

const exportForm = document.querySelector('.export-form');
if (exportForm) {
  const pad = value => String(value).padStart(2, '0');
  const localValue = date => `${date.getFullYear()}-${pad(date.getMonth()+1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
  const end = new Date();
  const start = new Date(end.getTime() - 24 * 60 * 60 * 1000);
  exportForm.elements.start.value = localValue(start);
  exportForm.elements.end.value = localValue(end);
}
