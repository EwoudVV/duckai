# Threat model (honest version)

## What we're protecting

- Host (Proxmox + GPU VM) from takeover / persistence
- Home LAN from lateral movement (VM must never reach LAN)
- Operator (you) from abuse letters tied to your IP
- Users from each other (no reading/killing each other's jobs)

## What we assume (zero trust-ish, 4 users)

- Users are not root, not trusted with network. Every job is untrusted code.
- AI review helps triage, it is NOT a security boundary. It misses obfuscation.
- Real boundaries: no SSH to GPU box, containers non-privileged + timeouts + wiped, egress forced through logging proxy or off, host firewall blocks SMTP/scanning, everything attributed to a user+job.

## Residual risks (read this before enabling internet)

1. `offline` mode: near-zero network-abuse risk. Job has no route out. Main risks left: resource hog (mitigated by limits), illegal content generation with local weights (log prompts/outputs, ToS), container escape (rare, keep docker patched, no --privileged ever).
2. `proxied` mode: low but non-zero. Allowlist + logs stop casual abuse and identify the user, but a determined user can tunnel C2/exfil over allowed HTTPS (e.g. via github/hf as dead drop). SMTP/ports blocked, but HTTPS-tunneled spam via a web API is still possible. Accept only with invite-only + per-user keys + 30-90d log retention + instant revoke.
3. `open` mode: same as giving shell + internet. Expect abuse eventually. Disabled by default.

Abuse letters come from L3/L4 behavior from your IP, not from GPU math. If a job has unrestricted egress, assume it can generate a letter no matter what the code review said.

## What we log (shown to users on signup)

- submitted code + requirements + run.yaml, per job, per user
- review score + reasons
- squid domains per job (SNI/host, bytes, timestamp)
- stdout/stderr (truncated at 2MB), exit code, runtime, peak GPU mem if available
- GPU-minutes per user for fairness

No expectation of privacy on shared box. Logs kept 90d, then pruned.

## Minimum host rules

- Proxmox UI + SSH on Tailscale only, 2FA on, no port-forward of 8006/22
- GPU VM on isolated bridge, firewall: VM can go out (via proxy), cannot reach LAN or Proxmox host
- host iptables: DROP 25,465,587 outbound from job network; rate-limit SYN; log drops
- nightly Proxmox snapshot; `scripts/firewall.sh` re-applied on boot
- docker rootless or at least no `--privileged`, no host mounts except artifacts dir, `no-new-privileges:true`
