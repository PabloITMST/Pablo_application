// The viewer's only bridge to the host: locate a quote in its own Source webview, and chat with the agent (M4.0).
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("pabloHost", {
  locate: (webContentsId, quote) => ipcRenderer.invoke("pablo:locate", webContentsId, quote),
  chat: (text, task) => ipcRenderer.invoke("pablo:chat", text, task),
  ask: (text, task) => ipcRenderer.invoke("pablo:ask", text, task),  // M3.3: a question about the captured PDF
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
  audit: task => ipcRenderer.invoke("pablo:audit", task),  // A5/A6: 재현 점검 of the work folder (read-only turn)
  pickFolder: task => ipcRenderer.invoke("pablo:pick-folder", task),
  addSource: task => ipcRenderer.invoke("pablo:add-source", task),
  setNet: (task, on) => ipcRenderer.invoke("pablo:set-net", task, on),  // D1: 인터넷 for this task's commands
  diff: (task, from, to) => ipcRenderer.invoke("pablo:diff", task, from, to),  // D4: what a turn changed in the work folder
  undo: (task, from, to) => ipcRenderer.invoke("pablo:undo", task, from, to),  // D4: put those files back
  onAgent: cb => ipcRenderer.on("pablo:agent", (_, ev) => cb(ev)),
  // M4.1 ChatGPT connection: commands and {state, error} only; tokens never cross this bridge
  login: () => ipcRenderer.invoke("pablo:login"),
  cancelLogin: () => ipcRenderer.invoke("pablo:login-cancel"),
  logout: () => ipcRenderer.invoke("pablo:logout"),
  authStatus: () => ipcRenderer.invoke("pablo:auth-status"),
  onAuth: cb => ipcRenderer.on("pablo:auth", (_, ev) => cb(ev)),
});
