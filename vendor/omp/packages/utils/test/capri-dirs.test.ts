import { afterEach, beforeEach, describe, expect, it } from "bun:test";
import * as os from "node:os";
import * as path from "node:path";
import * as dirs from "../src/dirs";

describe("Capri private root", () => {
	const keys = ["CAPRI_OMP_ROOT", "PI_CODING_AGENT_DIR", "PI_CONFIG_DIR", "OMP_PROFILE", "PI_PROFILE"];
	let saved: (string | undefined)[];
	beforeEach(() => {
		saved = keys.map(key => process.env[key]);
		for (const key of keys) delete process.env[key];
		dirs.__resetDirsFromEnvForTests();
	});
	afterEach(() => {
		keys.forEach((key, i) => {
			if (saved[i] === undefined) delete process.env[key];
			else process.env[key] = saved[i];
		});
		dirs.__resetDirsFromEnvForTests();
	});
	it.each([undefined, "", "  "])("preserves upstream root for %j", value => {
		if (value !== undefined) process.env.CAPRI_OMP_ROOT = value;
		process.env.PI_CONFIG_DIR = ".capri-omp";
		dirs.__resetDirsFromEnvForTests();
		expect(dirs.getBaseConfigRoot()).toBe(path.join(os.homedir(), ".capri-omp"));
		dirs.setProfile("work");
		expect(dirs.getConfigRootDir()).toBe(path.join(os.homedir(), ".capri-omp/profiles/work"));
	});
	it("redirects root and global paths while preserving explicit agent and sessions", () => {
		const data = path.resolve("Capri дані with spaces");
		const root = path.join(data, "omp-root");
		const agent = path.join(data, "agent");
		process.env.CAPRI_OMP_ROOT = `  ${root}  `;
		process.env.PI_CODING_AGENT_DIR = agent;
		process.env.OMP_PROFILE = process.env.PI_PROFILE = "";
		dirs.__resetDirsFromEnvForTests();
		expect(dirs.getBaseConfigRoot()).toBe(root);
		expect(dirs.getConfigRootDir()).toBe(root);
		for (const target of [dirs.getStatsDbPath(), dirs.getReportsDir(), dirs.getPluginsDir(),
			dirs.getGlobalDaemonRuntimeRoot(), dirs.getSessionOwnersDir(), dirs.getProviderInFlightRoot(),
			dirs.getNativesDir(), dirs.getFastembedCacheDir()]) {
			expect(path.relative(root, target).startsWith("..")).toBe(false);
		}
		expect(dirs.getAgentDir()).toBe(agent);
		expect(dirs.getSessionsDir()).toBe(path.join(agent, "sessions"));
		expect(dirs.getAgentDbPath()).toBe(path.join(agent, "agent.db"));
		expect(path.dirname(dirs.getModelDbPath())).toBe(agent);
		dirs.setProfile("work");
		expect(dirs.getConfigRootDir()).toBe(path.join(root, "profiles/work"));
		expect(dirs.getGlobalDaemonRuntimeRoot()).toBe(path.join(root, "run/daemons/global"));
	});
	it.each(["relative", "../relative", "~/private", "C:relative", "\\relative", "/relative"])(
		"rejects incomplete root %j before filesystem writes", value => {
			if (process.platform !== "win32" && value === "/relative") return;
			process.env.CAPRI_OMP_ROOT = value;
			expect(() => dirs.getBaseConfigRoot()).toThrow("CAPRI_OMP_ROOT");
		},
	);
	it("rejects an invalid import-time root in a fresh child", () => {
		const child = Bun.spawnSync([process.execPath, "-e", `await import(${JSON.stringify(path.resolve(import.meta.dir, "../src/dirs.ts"))})`], {
			env: { ...process.env, CAPRI_OMP_ROOT: "relative" },
		});
		expect(child.exitCode).not.toBe(0);
		expect(child.stderr.toString()).toContain("CAPRI_OMP_ROOT");
	});
});
