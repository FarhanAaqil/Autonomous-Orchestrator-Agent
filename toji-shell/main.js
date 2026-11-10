'use strict';
const { app, BrowserWindow, dialog, shell, session } = require('electron');
const path = require('node:path');
const { apiOrigin, healthy, internal, external } = require('./endpoint');
let window;
if (!app.requestSingleInstanceLock()) app.quit();
else {
  app.on('second-instance', () => {if (window) {if (window.isMinimized()) window.restore(); window.show(); window.focus();}});
  app.whenReady().then(async () => {
    let origin;
    try {origin = apiOrigin(process.env.TOJI_API_URL);}
    catch (error) {dialog.showErrorBox('Invalid backend address', error.message); app.quit(); return;}
    session.defaultSession.setPermissionRequestHandler((_webContents, _permission, callback) => callback(false));
    session.defaultSession.setPermissionCheckHandler(() => false);
    let ready = false;
    while (!ready) {
      try {const response = await fetch(origin + '/health', {signal: AbortSignal.timeout(3000), redirect: 'error'}); ready = response.ok && healthy(await response.json());} catch {ready = false;}
      if (!ready) {
        const result = await dialog.showMessageBox({type:'warning', title:'Start your workspace', message:'Toji cannot reach its backend.', detail:'Start Docker Desktop and run docker compose up -d in your project. Check TOJI_API_URL if using another server. No duplicate backend will be started.', buttons:['Retry','Quit'], defaultId:0, cancelId:1});
        if (result.response === 1) {app.quit(); return;}
      }
    }
    window = new BrowserWindow({show:!app.commandLine.hasSwitch('smoke-test'),width:1360,height:920,minWidth:390,minHeight:620,title:'Toji',backgroundColor:'#e4dac8',icon:path.join(__dirname,'assets/toji-tray.ico'),webPreferences:{sandbox:true,contextIsolation:true,nodeIntegration:false,webSecurity:true,allowRunningInsecureContent:false}});
    window.removeMenu();
    window.webContents.on('will-navigate', (event,url) => {if (!internal(url,origin)) event.preventDefault();});
    window.webContents.on('will-redirect', (event,url) => {if (!internal(url,origin)) event.preventDefault();});
    window.webContents.on('will-attach-webview', event => event.preventDefault());
    window.webContents.setWindowOpenHandler(({url}) => {if (external(url)) void shell.openExternal(url);return {action:'deny'};});
    session.defaultSession.on('will-download', event => event.preventDefault());
    await window.loadURL(origin);
  }).catch(() => {dialog.showErrorBox('Workspace unavailable','Unable to open the configured workspace. Check the backend and restart Toji.'); app.quit();});
  app.on('window-all-closed', () => app.quit());
}
