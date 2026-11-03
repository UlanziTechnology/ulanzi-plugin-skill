
import { RandomPort, Utils } from './ulanzi-api/index.js';
import net from 'net';

import lightroomPluginInstaller from './lightroomPluginInstaller.js';



export default class LrServer {
  constructor($UD) {
    this.LR_HOST = '127.0.0.1';
    this.LR_PORT = '39660';

    this.$UD = $UD;

    this.lrSocket = null;
    this.connected = false;
    this.hbTimer = null;
    this.reconnTimer = null;
    this.status = ''; 
  }

  async start() {
    await this.getStatus();
    if (this.status === 'Installed' || this.status === 'Updated') {
      Utils.log('LR plugin is installed, starting LR connection...');
      this.connectLR();
    }
  }

  async getStatus() {
    const isInastalled = await new lightroomPluginInstaller().install();
    this.status = isInastalled.status || '';
  }


  

  connectLR() {
    if (this.lrSocket) { try{this.lrSocket.destroy();}catch{} this.lrSocket=null; }
    Utils.log('connecting to LR', this.LR_HOST+':'+this.LR_PORT);
    const sock = net.createConnection({ host: this.LR_HOST, port: this.LR_PORT });
    this.lrSocket = sock;
  
    sock.on('connect', () => {
      this.connected = true; 
      this.status = 'Connected';
      this.sendStatusToPI();
      Utils.log('connected to LR');
      this.startHeartbeat();
    });
    sock.on('error', (e) => { Utils.log('lr error:', e.code || e.message); });
    sock.on('close', () => {
      this.connected = false; 
      this.status = 'Disconnected';
      this.sendStatusToPI();
      this.stopHeartbeat(); 
      Utils.log('lr closed');

      this.scheduleReconnect();
    });
    sock.on('data', (buf) => { 
      // Utils.log('lr data:', buf.toString().trim()); 
    });
  }

  sendStatusToPI(){
    if(!this.$UD.lastContext) return;
    this.$UD.sendToPropertyInspector({
      connectStatus:this.status
    },this.$UD.lastContext)
  }

   scheduleReconnect() {
    if (this.reconnTimer) return;
    this.reconnTimer = setTimeout(() => { this.reconnTimer=null; this.connectLR(); }, 5000);
  }
  
   startHeartbeat() {
    this.stopHeartbeat();
    this.hbTimer = setInterval(() => {
      try {
        if (this.connected && this.lrSocket) this.lrSocket.write("PING\n");
      } catch(e) {
        Utils.log('hb write error', e.message);

      }
    }, 3000);
  }
  
   stopHeartbeat() { if (this.hbTimer) { clearInterval(this.hbTimer); this.hbTimer=null; } }
  
   sendLine(line) {
    Utils.log('------LR SENDLINE:', line);
    if (!this.connected || !this.lrSocket) {
      return { ok:false, error:'plugin_offline' };
    }
    try {
      this.lrSocket.write(line.endsWith('\n') ? line : line + '\n');
      return { ok:true };
    } catch (e) {
      return { ok:false, error:e.message };
    }
  }

}