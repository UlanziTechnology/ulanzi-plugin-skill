import fs from "node:fs";
import { promises as fsp } from "node:fs";
import { createHash } from "node:crypto";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { Utils } from "../actions/ulanzi-api/index.js";

const EXTENSION_ID = "com.ulanzi.aftereffects.bridge";

export default class AfterEffectsExtensionInstaller {
  constructor(options = {}) {
    const userHome = options.userHome || os.homedir();
    this.platform = options.platform || process.platform;
    this.pluginRoot = options.pluginRoot || Utils.getPluginPath();
    this.sourcePath = options.sourcePath || path.join(this.pluginRoot, "plugin", "cep", EXTENSION_ID);
    this.extensionsRoot = options.extensionsRoot || this.defaultExtensionsRoot(userHome);
    this.targetPath = options.targetPath || path.join(this.extensionsRoot, EXTENSION_ID);
    this.enableDebugMode = options.enableDebugMode !== false;
  }

  defaultExtensionsRoot(userHome) {
    if (this.platform === "darwin") {
      return path.join(userHome, "Library", "Application Support", "Adobe", "CEP", "extensions");
    }
    if (this.platform === "win32") {
      return path.join(userHome, "AppData", "Roaming", "Adobe", "CEP", "extensions");
    }
    return path.join(userHome, ".adobe", "CEP", "extensions");
  }

  async install() {
    if (!(await this.exists(this.sourcePath))) {
      throw new Error(`Bundled CEP extension was not found: ${this.sourcePath}`);
    }
    await fsp.mkdir(this.extensionsRoot, { recursive: true });
    const debugModeEnabled = this.enableDebugMode ? this.configureDebugMode() : true;
    const sourceVersion = await this.readVersion(this.sourcePath);
    if (!sourceVersion) throw new Error("Bundled CEP manifest has no version");

    if (!(await this.exists(this.targetPath))) {
      await this.safeReplace(false);
      return {
        status: "Installed",
        version: sourceVersion,
        bundledVersion: sourceVersion,
        installedVersion: sourceVersion,
        debugModeEnabled,
        targetPath: this.targetPath
      };
    }

    const targetVersion = await this.readVersion(this.targetPath);
    const versionComparison = this.compareVersions(targetVersion, sourceVersion);
    if (versionComparison === 0 && await this.contentsMatch(this.sourcePath, this.targetPath)) {
      return {
        status: "Unchanged",
        version: sourceVersion,
        bundledVersion: sourceVersion,
        installedVersion: targetVersion,
        debugModeEnabled,
        targetPath: this.targetPath
      };
    }
    if (versionComparison !== null && versionComparison > 0) {
      return {
        status: "NewerInstalled",
        version: targetVersion,
        bundledVersion: sourceVersion,
        installedVersion: targetVersion,
        debugModeEnabled,
        targetPath: this.targetPath
      };
    }

    await this.safeReplace(true);
    return {
      status: "Updated",
      version: sourceVersion,
      bundledVersion: sourceVersion,
      installedVersion: sourceVersion,
      previousVersion: targetVersion,
      debugModeEnabled,
      targetPath: this.targetPath
    };
  }

  async contentsMatch(source, target) {
    try {
      const [sourceDigest, targetDigest] = await Promise.all([
        this.directoryDigest(source),
        this.directoryDigest(target)
      ]);
      return sourceDigest === targetDigest;
    } catch {
      return false;
    }
  }

  async directoryDigest(root) {
    const digest = createHash("sha256");
    const walk = async (current, relative = "") => {
      const entries = await fsp.readdir(current, { withFileTypes: true });
      entries.sort((left, right) => left.name.localeCompare(right.name));
      for (const entry of entries) {
        const relativePath = relative ? path.join(relative, entry.name) : entry.name;
        const absolutePath = path.join(current, entry.name);
        digest.update(relativePath.split(path.sep).join("/"));
        digest.update("\0");
        if (entry.isDirectory()) {
          digest.update("directory\0");
          await walk(absolutePath, relativePath);
        } else if (entry.isSymbolicLink()) {
          digest.update("symlink\0");
          digest.update(await fsp.readlink(absolutePath));
          digest.update("\0");
        } else {
          digest.update("file\0");
          digest.update(await fsp.readFile(absolutePath));
          digest.update("\0");
        }
      }
    };
    await walk(root);
    return digest.digest("hex");
  }

  compareVersions(installedVersion, bundledVersion) {
    const installed = this.parseVersion(installedVersion);
    const bundled = this.parseVersion(bundledVersion);
    if (!installed || !bundled) return null;

    const length = Math.max(installed.core.length, bundled.core.length);
    for (let index = 0; index < length; index += 1) {
      const installedPart = installed.core[index] || 0;
      const bundledPart = bundled.core[index] || 0;
      if (installedPart !== bundledPart) return installedPart > bundledPart ? 1 : -1;
    }

    if (!installed.prerelease && !bundled.prerelease) return 0;
    if (!installed.prerelease) return 1;
    if (!bundled.prerelease) return -1;
    return installed.prerelease.localeCompare(bundled.prerelease, undefined, { numeric: true, sensitivity: "base" });
  }

  parseVersion(version) {
    if (typeof version !== "string") return null;
    const match = version.trim().match(/^(\d+(?:\.\d+){0,2})(?:(?:-([0-9A-Za-z.-]+))|(?:\.([0-9A-Za-z_-]+)))?(?:\+[0-9A-Za-z.-]+)?$/);
    if (!match) return null;
    return {
      core: match[1].split(".").map((part) => Number.parseInt(part, 10)),
      prerelease: match[2] || match[3] || ""
    };
  }

  async safeReplace(hasExistingTarget) {
    const suffix = `${process.pid}-${Date.now()}`;
    const stagePath = `${this.targetPath}.stage-${suffix}`;
    const backupPath = `${this.targetPath}.backup-${suffix}`;
    let backupCreated = false;
    try {
      await this.copyDir(this.sourcePath, stagePath);
      if (!(await this.readVersion(stagePath))) throw new Error("Staged CEP extension failed validation");
      if (hasExistingTarget) {
        await fsp.rename(this.targetPath, backupPath);
        backupCreated = true;
      }
      await fsp.rename(stagePath, this.targetPath);
      if (backupCreated) await fsp.rm(backupPath, { recursive: true, force: true }).catch(() => {});
    } catch (error) {
      await fsp.rm(stagePath, { recursive: true, force: true }).catch(() => {});
      if (backupCreated && !(await this.exists(this.targetPath))) {
        await fsp.rename(backupPath, this.targetPath).catch(() => {});
      }
      throw error;
    }
  }

  async copyDir(source, target) {
    const from = path.resolve(source);
    const to = path.resolve(target);
    if (to === from || to.startsWith(`${from}${path.sep}`)) throw new Error("CEP target cannot be inside its source");
    await fsp.cp(from, to, { recursive: true, force: true, preserveTimestamps: true });
  }

  async readVersion(extensionPath) {
    try {
      const manifest = await fsp.readFile(path.join(extensionPath, "CSXS", "manifest.xml"), "utf8");
      const bundle = manifest.match(/ExtensionBundleVersion=["']([^"']+)["']/i);
      const extension = manifest.match(/<Extension\s+Id=["'][^"']+["']\s+Version=["']([^"']+)["']/i);
      return (bundle && bundle[1]) || (extension && extension[1]) || null;
    } catch {
      return null;
    }
  }

  configureDebugMode() {
    if (this.platform !== "darwin" && this.platform !== "win32") return false;
    const versions = ["12", "11", "10"];
    let succeeded = false;
    for (const version of versions) {
      const result = this.platform === "darwin"
        ? spawnSync("defaults", ["write", `com.adobe.CSXS.${version}`, "PlayerDebugMode", "-string", "1"], { stdio: "ignore" })
        : spawnSync("reg", ["add", `HKCU\\Software\\Adobe\\CSXS.${version}`, "/v", "PlayerDebugMode", "/t", "REG_SZ", "/d", "1", "/f"], { stdio: "ignore" });
      if (result.status === 0) succeeded = true;
    }
    return succeeded;
  }

  async exists(filePath) {
    try {
      await fsp.access(filePath, fs.constants.F_OK);
      return true;
    } catch {
      return false;
    }
  }
}
