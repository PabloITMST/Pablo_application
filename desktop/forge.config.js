// M6 packaging (Windows x64): `npm run package` -> out/Pablo-win32-x64/Pablo.exe, `npm run make` -> Squirrel Setup.exe.
// Executables the app spawns stay outside app.asar, in resources/ (process.resourcesPath):
//   pablo-backend/            PyInstaller onedir backend (`npm run backend` first)
//   x86_64-pc-windows-msvc/   the pinned Codex runtime (bin/codex.exe + codex-resources + codex-path)
// Writable state never goes there: it is all in userData.
module.exports = {
  packagerConfig: {
    name: "Pablo",
    executableName: "Pablo",
    icon: "assets/pablo",
    asar: true,
    // not shipped: the checks, and pdf.js's Node-only canvas/stream deps (the renderer uses pdf.js's browser build)
    ignore: [/^\/(check|rc|cover|forge\.config)\.js$/, /^\/node_modules\/(@napi-rs|node-readable-to-web-readable-stream)(\/|$)/, /^\/out(\/|$)/],
    extraResource: [
      "../build/dist/pablo-backend",
      "node_modules/@openai/codex-win32-x64/vendor/x86_64-pc-windows-msvc",
      "THIRD_PARTY_NOTICES.txt",
    ],
    win32metadata: { CompanyName: "Pablo", ProductName: "Pablo", FileDescription: "Pablo" },
  },
  makers: [
    { name: "@electron-forge/maker-squirrel", config: { name: "Pablo", setupExe: "PabloSetup.exe", setupIcon: "assets/pablo.ico" } },
  ],
};
