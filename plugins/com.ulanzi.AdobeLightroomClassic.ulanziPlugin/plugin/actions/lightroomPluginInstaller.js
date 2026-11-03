import fs from "fs";
import { promises as fsp } from "fs";
import path from "path";
import os from "os";
import { Utils } from "./ulanzi-api/index.js";

export default class LightroomPluginInstaller {
  /**
   * @param {Object} [opts]
   * @param {string} [opts.root] Lightroom 根目录
   * @param {string} [opts.sourceDir] 源插件所在目录（“我目录下”）
   * @param {string} [opts.pluginName] 插件文件夹名
   * @param {boolean} [opts.connected=false] 目标已有插件时返回该布尔值（此实现未使用）
   * @param {boolean} [opts.overwrite=true] 复制时是否覆盖已存在文件
   * @param {boolean} [opts.preserveTimestamps=true] 是否尽量保留时间戳
   * @param {boolean} [opts.dereference=false] 符号链接是否解引用
   */
  constructor() {
    const userHome = os.homedir();

    // 根据运行平台选择 Lightroom 根目录：
    // - macOS: ~/Library/Application Support/Adobe/Lightroom
    // - Windows: %USERPROFILE%/AppData/Roaming/Adobe/Lightroom
    let lrDir;
    if (process.platform === "darwin") {
      lrDir = path.join(userHome, "Library", "Application Support", "Adobe", "Lightroom");
    } else if (process.platform === "win32") {
      lrDir = path.join(userHome, "AppData", "Roaming", "Adobe", "Lightroom");
    } else {
      // 其他平台默认回退到 Windows 路径（可根据需要扩展）
      lrDir = path.join(userHome, "AppData", "Roaming", "Adobe", "Lightroom");
    }
    

    this.root = lrDir;

    this.sourceDir = Utils.getPluginPath();
    this.pluginName = "ulanzi.lrplugin";
    this.connected = false;
    this.overwrite = true;
    this.preserveTimestamps = true;
    this.dereference = false;
  }

  get modulesDir() {
    return path.join(this.root, "Modules");
  }

  get targetPluginPath() {
    return path.join(this.modulesDir, this.pluginName);
  }

  get sourcePluginPath() {
    return path.join(this.sourceDir, "plugin", this.pluginName);
  }

  // ---------- 公共主流程 ----------

  /**
   * 安装 / 更新
   * @param {boolean} [update] 若为 true，则无视版本差异强制覆盖
   * @returns {Promise<{status:"NotInstall"|"Installed"|"Updated"}>}
   */
  async install(update) {
    if (!(await this.#exists(this.root))) {
      return this.#result("NotInstalled");
    }

    await fsp.mkdir(this.modulesDir, { recursive: true });

    if (!(await this.#exists(this.sourcePluginPath))) {
      console.warn(`323234sourcePluginPath not found: ${this.sourcePluginPath}`);
      throw new Error(`not found sourcePluginPath: ${this.sourcePluginPath}`);
    }

    // 目标不存在：首次安装
    if (!(await this.#exists(this.targetPluginPath))) {
      await this.#copyDir(this.sourcePluginPath, this.targetPluginPath, {
        overwrite: this.overwrite,
        preserveTimestamps: this.preserveTimestamps,
        dereference: this.dereference,
      });
      return this.#result("Installed");
    }

    // 目标已存在：对比版本或强制更新
    const [srcV, tgtV] = await Promise.all([
      this.#readPluginVersion(this.sourcePluginPath),
      this.#readPluginVersion(this.targetPluginPath),
    ]);

    const same = this.#versionsEqual(srcV, tgtV);

    if (update === true || !same) {
      // 覆盖更新：删除旧目录后整包复制
      await fsp.rm(this.targetPluginPath, { recursive: true, force: true });
      await this.#copyDir(this.sourcePluginPath, this.targetPluginPath, {
        overwrite: true,
        preserveTimestamps: this.preserveTimestamps,
        dereference: this.dereference,
      });
      return this.#result("Updated");
    }

    // 版本一致：不动
    return this.#result("Installed");
  }

  // ---------- 私有工具 ----------

  #result(status) {
    return { status };
  }

  async #exists(p) {
    try {
      await fsp.access(p, fs.constants.F_OK);
      return true;
    } catch {
      return false;
    }
  }

  /**
   * 复制整个目录（不删除源），Node 16.7+ 优先使用 fs.promises.cp
   */
  async #copyDir(src, dest, { overwrite = false, preserveTimestamps = true, dereference = false } = {}) {
    const from = path.resolve(src);
    const to = path.resolve(dest);

    if (to === from || to.startsWith(from + path.sep)) {
      throw new Error(`(目标路径不能是源路径自身或其子目录) target path not source path：${to}`);
    }

    if (typeof fsp.cp === "function") {
      await fsp.mkdir(to, { recursive: true });
      await fsp.cp(from, to, {
        recursive: true,
        force: overwrite,
        preserveTimestamps,
        dereference,
      });
      return;
    }

    // 老版本 Node 兼容：手写递归复制
    await fsp.mkdir(to, { recursive: true });
    const entries = await fsp.readdir(from, { withFileTypes: true });

    for (const entry of entries) {
      const s = path.join(from, entry.name);
      const d = path.join(to, entry.name);

      if (entry.isDirectory()) {
        await this.#copyDir(s, d, { overwrite, preserveTimestamps, dereference });
      } else if (entry.isSymbolicLink()) {
        const linkTarget = await fsp.readlink(s);
        const destExists = await this.#exists(d);
        if (destExists && !overwrite) continue;
        if (destExists && overwrite) await fsp.rm(d, { force: true, recursive: true });

        if (dereference) {
          const real = path.resolve(path.dirname(s), linkTarget);
          const stat = await fsp.stat(real);
          if (stat.isDirectory()) {
            await this.#copyDir(real, d, { overwrite, preserveTimestamps, dereference });
          } else {
            await fsp.copyFile(real, d);
            if (preserveTimestamps) {
              const st = await fsp.stat(real);
              await fsp.utimes(d, st.atime, st.mtime);
            }
          }
        } else {
          await fsp.symlink(linkTarget, d);
        }
      } else {
        const destExists = await this.#exists(d);
        if (destExists && !overwrite) continue;
        await fsp.copyFile(s, d);
        if (preserveTimestamps) {
          const st = await fsp.stat(s);
          await fsp.utimes(d, st.atime, st.mtime);
        }
      }
    }
  }

  /**
   * 读取插件目录中的 Info.lua / info.lua 的 VERSION
   * 支持：
   *  - VERSION = { major=1, minor=2, revision=0, build=123 }
   *  - VERSION = "1.2.0" 或 '1.2.0'
   * @returns {Promise<number[]|null>} 数字数组（如 [1,2,0,123]），失败返回 null
   */
  async #readPluginVersion(pluginDir) {
    const infoPath = await this.#findInfoLua(pluginDir);
    if (!infoPath) return null;

    try {
      const txt = await fsp.readFile(infoPath, "utf8");

      // 表格写法
      const table = txt.match(/VERSION\s*=\s*{([\s\S]*?)}/i);
      if (table) {
        const body = table[1];
        const pick = (k) => {
          const m = body.match(new RegExp(`${k}\\s*=\\s*(\\d+)`, "i"));
          return m ? Number(m[1]) : undefined;
        };
        const arr = [
          pick("major"),
          pick("minor"),
          pick("revision") ?? pick("patch"),
          pick("build"),
        ].filter((v) => typeof v === "number");
        if (arr.length) return arr;
      }

      // 字符串写法
      const str = txt.match(/VERSION\s*=\s*["']([^"']+)["']/i);
      if (str) {
        const arr = str[1]
          .split(/[^0-9]+/)
          .filter(Boolean)
          .map((n) => Number(n));
        if (arr.length) return arr;
      }

      return null;
    } catch {
      return null;
    }
  }

  async #findInfoLua(pluginDir) {
    // 首选常见大小写
    const direct = [path.join(pluginDir, "Info.lua"), path.join(pluginDir, "info.lua")];
    for (const p of direct) {
      if (await this.#exists(p)) return p;
    }
    // 退而求其次：扫描目录做不区分大小写匹配
    try {
      const list = await fsp.readdir(pluginDir);
      const hit = list.find((n) => n.toLowerCase() === "info.lua");
      return hit ? path.join(pluginDir, hit) : null;
    } catch {
      return null;
    }
  }

  #versionsEqual(a, b) {
    // 任一方缺失 => 视为不相等（更安全，触发更新）
    if (!a || !b) return false;

    // 去掉末尾 0（如 1.2.0 与 1.2 视为相等）
    const trim = (arr) => {
      const x = [...arr];
      while (x.length > 1 && x[x.length - 1] === 0) x.pop();
      return x;
    };
    const A = trim(a);
    const B = trim(b);
    if (A.length !== B.length) return false;
    return A.every((n, i) => n === B[i]);
  }

  #versionToString(vArr) {
    if (!vArr || !vArr.length) return "unknown";
    const a = [...vArr];
    while (a.length > 1 && a[a.length - 1] === 0) a.pop();
    return a.join(".");
  }
}
