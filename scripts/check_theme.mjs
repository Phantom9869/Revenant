// Drives headless Chrome over the DevTools protocol to check the web UI theme toggle:
// first visit follows prefers-color-scheme, a click flips and saves the choice, the choice survives a reload.
//   google-chrome --headless --remote-debugging-port=9333 --user-data-dir=$(mktemp -d) about:blank &
//   node --experimental-websocket scripts/check_theme.mjs 9333 http://127.0.0.1:8000/p/psf/requests-html
const port = process.argv[2], url = process.argv[3];
const tabs = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
const ws = new WebSocket(tabs.find(t => t.type === 'page').webSocketDebuggerUrl);
let id = 0; const pend = {};
ws.onmessage = m => { const d = JSON.parse(m.data); if (pend[d.id]) { pend[d.id](d.result); delete pend[d.id]; } };
await new Promise(r => ws.onopen = r);
const send = (method, params = {}) => new Promise(r => { pend[++id] = r; ws.send(JSON.stringify({ id, method, params })); });
const ev = async e => (await send('Runtime.evaluate', { expression: e, returnByValue: true })).result.value;
const sleep = ms => new Promise(r => setTimeout(r, ms));
const state = () => ev(`JSON.stringify({theme:document.documentElement.dataset.theme, stored:localStorage.getItem('revenant-theme'), label:document.getElementById('theme-toggle').getAttribute('aria-label'), bg:getComputedStyle(document.body).backgroundColor})`);
for (const scheme of ['dark', 'light']) {
  await send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-color-scheme', value: scheme }] });
  await send('Page.navigate', { url }); await sleep(800);
  await ev(`localStorage.clear()`); await send('Page.reload'); await sleep(800);
  console.log(`first visit, system ${scheme}:`, await state());
}
await ev(`document.getElementById('theme-toggle').click()`); await sleep(100);
console.log('after click:', await state());
await send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-color-scheme', value: 'light' }] });
await send('Page.reload'); await sleep(800);
console.log('reload with system light (stored choice wins):', await state());
await ev(`document.getElementById('theme-toggle').focus()`);
console.log('focusable:', await ev(`document.activeElement.id`));
process.exit(0);
