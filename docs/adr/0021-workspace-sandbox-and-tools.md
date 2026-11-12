# 0021. Workspace sandbox and tools: hardened Docker through the Harness, declared tools only

- Status: Accepted
- Date: 2026-11-11

## Context

The implementer and the reviewer read and change files and run commands. The project overview
says agents with file or shell access run in a sandbox with no network by default, and that
permissions are "enforced by the runtime and the sandbox, never by the prompt". Each agent's
`capabilities.tools` lists the tools it may call, and `permissions` sets `network` and the names
of the `secrets` it may read. Until now no tool names were defined and nothing enforced either.

The run also needs a copy of the target repository to work on, and a way to hand the result
back. Milestone 3 has no GitHub access, so a branch left inside a container would be stranded.

Checked on 2026-11-11: Pydantic AI Harness's `DockerSandbox`
([ADR 0020](0020-agent-runtime-pydantic-ai.md)) drives the `docker` command-line tool and is
POSIX-only. The Docker SDK for Python, `docker` 7.2.0, has no Python 3.14 classifier, is
untyped and ships its type stubs separately.

## Decision

**The sandbox is Harness `DockerSandbox`, driven through the `docker` CLI.** No Docker library is
added. `conveyor.sandbox` provides a `WorkspaceProvider` implementation over it.

**One hardened container per run, over a named volume.** It runs with exactly:

```
--network none --read-only --user 10001:10001 --cap-drop ALL
--security-opt no-new-privileges --pids-limit 512 --memory 2g --cpus 2 --tmpfs /tmp
```

`--network none` comes from the Harness option `allow_internet_access=False`, not from the
extra Docker arguments, because Docker refuses a second `--network`. The rest are passed as
extra Docker arguments. The Harness adds its own `--detach --init --pids-limit 2048
--tmpfs /run/pydantic-ai --entrypoint sh`; Conveyor's `--pids-limit 512` comes later and, since
the last one wins, overrides its default.

The workspace volume is the only persistent writable mount. The `/tmp` and `/run/pydantic-ai`
tmpfs mounts are also writable, and are discarded with the container.

**The default image is built from a Dockerfile shipped in the package**, with Python, git and a
non-root user. `conveyor run start --sandbox-image IMAGE` uses another image instead.

**Clone in from a Git bundle of `HEAD`.** The workspace is cloned from a bundle of the target
repository's `HEAD` (`--repo PATH`), so untracked and ignored files, such as `.env`, never enter
the sandbox.

**Export out as a Git bundle.** When the run completes, the engine writes the run's branch as a
bundle under `.conveyor/runs/<run>/`, and `conveyor run show` prints the `git fetch` line to
bring it into the repository. Nothing is pushed.

**The tool vocabulary for `capabilities.tools`:**

| Tool | Does |
|---|---|
| `fs.read_file`, `fs.write_file`, `fs.edit_file` | Read, write and edit a file |
| `fs.list_directory`, `fs.search_files`, `fs.find_files` | List, search or find files |
| `fs.create_directory`, `fs.file_info` | Create a folder, read a file's metadata |
| `shell.run_command` | Run a command in the workspace |

The `fs.*` tools come from the Harness `FileSystem` capability and `shell.run_command` from
`Shell`, both over the run's sandbox.

**Only declared tools exist for an agent.** The runtime registers the tools in the agent's
`capabilities.tools` and no others. A model that calls an undeclared tool gets an error, and
nothing executes. A tool name outside the vocabulary is a preflight error. The runtime passes
an explicit tool list to `FileSystem` and `Shell`: without one, `Shell` also registers
`start_command`, `check_command` and `stop_command`, and `FileSystem` can offer `list_files`
and `grep`.

**`permissions.secrets`.** Only the named environment variables are passed, per agent, to that
agent's commands. Every other variable of the Conveyor process stays out of the container.

**`permissions.network`.** The container never has a network. In M3 preflight rejects an agent
that uses tools and sets `network: true`, rather than running it without the access it asked for.

**Who commits.** The agent commits with git through `shell.run_command`. Conveyor creates the
branch and sets the commit identity before the stage, refuses the output while the working tree
is dirty (the agent is asked to retry), and records the real base and head commit on every
attempt. Crash resume resets the workspace to an attempt's start commit
([ADR 0018](0018-durable-execution-dbos.md)).

**POSIX hosts only.** Sandboxed stages are not supported on Windows hosts in M3. Preflight gives
a clear error, and the Docker tests skip on the Windows CI runner.

**Tests.** Offline unit tests snapshot the exact hardening arguments. Tests that need Docker are
marked `docker`, excluded by default, and run in a Linux-only `docker` CI job, like the Postgres
job ([ADR 0012](0012-storage.md)). They prove the process is not root, the root file system is
read-only, the workspace is writable and an outbound connection fails.

## Alternatives considered

- **The Docker SDK for Python.** Untyped, no Python 3.14 classifier, and an extra dependency,
  when the Harness backend already uses the CLI.
- **Hand-built file and shell tools.** Against "adopt before building".
- **Conveyor commits after the stage.** The model could then not report `head_commit` in its
  `CodeChanges`, because the commit would not exist yet.
- **Mount the repository into the container.** Untracked and ignored files, including secrets,
  would be visible to the agent, and its writes would land in the person's checkout.
- **Push the branch at the end.** Needs network access and a token, which M3 does not have and
  which belong to an operation, not the engine.

## Consequences

- Running a factory with tool-using agents needs Docker on a Linux or macOS host.
- An agent's toolkit is enforced: undeclared tools cannot be called and undeclared secrets are
  absent, whatever the prompt says.
- Agents' work comes back only as a bundle the person fetches and reviews.
- The design relies on alpha Harness behaviour: re-attaching to a container by reference, and
  its process tmpfs working under `--read-only --user`. If the Harness backend cannot be
  hardened this way, the fallback is a thin Conveyor backend over the `docker` CLI.
- Network access for agents, gVisor and Windows support are later decisions.
