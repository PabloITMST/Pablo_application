// The viewer's only bridge to the host: locate a quote in its own Source webview, and chat with the agent (M4.0).
const { contextBridge, ipcRenderer, webUtils } = require("electron");

contextBridge.exposeInMainWorld("pabloHost", {
  locate: (webContentsId, quote) => ipcRenderer.invoke("pablo:locate", webContentsId, quote),
  chat: (text, task) => ipcRenderer.invoke("pablo:chat", text, task),
  ask: (text, task, only) => ipcRenderer.invoke("pablo:ask", text, task, only),  // M3.3: a question about the task's PDFs (C1: only = some)
  decide: (id, proceed) => ipcRenderer.invoke("pablo:decide", id, proceed),  // M4.2: the user's answer to a WARN
  retry: () => ipcRenderer.invoke("pablo:retry"),  // "다른 모델로 다시 시도" after a capacity failure
  stop: () => ipcRenderer.invoke("pablo:stop"),  // 중지: interrupt the running agent turn
  agentStatus: () => ipcRenderer.invoke("pablo:agent-status"),
  models: () => ipcRenderer.invoke("pablo:models"),
  setModel: m => ipcRenderer.invoke("pablo:set-model", m),
  // M5.1 app-first: live workspace state, a new task, the task's folder and material (dialogs run in main)
  state: () => ipcRenderer.invoke("pablo:state"),
  newTask: (text, opts) => ipcRenderer.invoke("pablo:new-task", text, opts),  // opts.repro: A3 research-integrity criteria
  spec: task => ipcRenderer.invoke("pablo:spec", task),  // A2: the task's paper -> reproduction conditions
  audit: task => ipcRenderer.invoke("pablo:audit", task),
  intent: (task, id, action) => ipcRenderer.invoke("pablo:intent", task, id, action),
  criterion: (task, id, action, reason) => ipcRenderer.invoke("pablo:criterion", task, id, action, reason),  // ④ hard | soft | drop  // B4: promote | reject a held-back criterion  // A5/A6: 재현 점검 of the work folder (read-only turn)
  pickFolder: task => ipcRenderer.invoke("pablo:pick-folder", task),
  pickPdfs: task => ipcRenderer.invoke("pablo:pick-pdfs", task),  // the dialog, several PDFs at once -> their paths
  addFiles: (task, files) => ipcRenderer.invoke("pablo:add-files", task, files),  // picked or dropped PDFs (main checks each)
  pathOf: file => webUtils.getPathForFile(file),  // a dropped File -> its path ("" for one that is not a file on disk)
  addArxiv: (task, text) => ipcRenderer.invoke("pablo:add-arxiv", task, text),  // C2: main downloads arxiv.org/pdf/<id>
  addWeb: (task, url) => ipcRenderer.invoke("pablo:add-web", task, url),  // D1: Pablo fetches the page and keeps its snapshot
  searchArxiv: text => ipcRenderer.invoke("pablo:search-arxiv", text),  // D2: the words go to the arXiv API (no key)
  removeSource: (task, id) => ipcRenderer.invoke("pablo:remove-source", task, id),  // C1: the records stay
  renameSource: (task, id, title) => ipcRenderer.invoke("pablo:rename-source", task, id, title),  // ⑧ ✎ the name the user knows it by
  report: task => ipcRenderer.invoke("pablo:report", task),  // ⑫ the reproduction report, saved where the user picks
  addOpenreview: (task, text) => ipcRenderer.invoke("pablo:add-openreview", task, text),  // ⑬ a paper from OpenReview
  renameTask: (task, name) => ipcRenderer.invoke("pablo:rename-task", task, name),  // ⑭ the task's own name ("" = its goal)
  archiveTask: (task, on) => ipcRenderer.invoke("pablo:archive-task", task, on),  // ⑭ 보관 / 보관 풀기
  lookupDoi: text => ipcRenderer.invoke("pablo:lookup-doi", text),  // ⑬ a DOI's title, looked up on arXiv
  setPrimary: (task, id) => ipcRenderer.invoke("pablo:set-primary", task, id),  // C1: the 주 논문 (재현 조건)
  compare: (task, columns) => ipcRenderer.invoke("pablo:compare", task, columns),  // C3: 비교표
  compareColumn: (task, matrix, column) => ipcRenderer.invoke("pablo:compare-column", task, matrix, column),  // ⑧ one more column
  condition: (task, action, o) => ipcRenderer.invoke("pablo:condition", task, action, o),  // ⑩ add (a picked sentence) | drop (why) | restore; ⑦ deviate (why) | undeviate
  setNet: (task, on) => ipcRenderer.invoke("pablo:set-net", task, on),
  setRoute: (task, route) => ipcRenderer.invoke("pablo:set-route", task, route),  // paper + folder: agent | ask  // D1: 인터넷 for this task's commands
  diff: (task, from, to) => ipcRenderer.invoke("pablo:diff", task, from, to),  // D4: what a turn changed in the work folder
  undo: (task, from, to) => ipcRenderer.invoke("pablo:undo", task, from, to),  // D4: put those files back
  readFile: (task, where, around, expect) => ipcRenderer.invoke("pablo:read-file", task, where, around, expect),
  recheck: (task, places) => ipcRenderer.invoke("pablo:recheck", task, places),  // ⑤ an audit card's confirmed places, now  // A3: a work-folder file, read-only
  openFile: (task, where, line, how) => ipcRenderer.invoke("pablo:open-file", task, where, line, how),  // "vscode" | "folder"
  onAgent: cb => ipcRenderer.on("pablo:agent", (_, ev) => cb(ev)),
  // M4.1 ChatGPT connection: commands and {state, error} only; tokens never cross this bridge
  login: () => ipcRenderer.invoke("pablo:login"),
  cancelLogin: () => ipcRenderer.invoke("pablo:login-cancel"),
  logout: () => ipcRenderer.invoke("pablo:logout"),
  authStatus: () => ipcRenderer.invoke("pablo:auth-status"),
  onAuth: cb => ipcRenderer.on("pablo:auth", (_, ev) => cb(ev)),
});
