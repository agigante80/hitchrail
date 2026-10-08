/* -- formatting --------------------------------------------------------
   One place, because the footer figure and the row memory column sit on the
   same screen and inconsistency between them reads as a bug. */
export function formatMb(mb) {
  if (mb === null || mb === undefined) return "";
  if (mb < 1024) return `${Math.round(mb)} MB`;
  return `${(mb / 1024).toFixed(1)} GB`;
}

/* #90. The figure and what bounds it, in one phrase: "1.4 GB of 4.0 GB" is
   a different sentence from "1.4 GB", and "no limit" is a fact worth reading
   beside a number rather than an absence. The ceiling is the tightest one
   on the process's cgroup ancestry, read by the server; null means nothing
   Hitchrail can see bounds it, which reads the same to the person holding
   the phone whether the tree was unreadable or genuinely unlimited. */
export function formatMemory(project) {
  const used = formatMb(project.ram_mb);
  const limit = project.ram_limit_mb;
  return typeof limit === "number" ? `${used} of ${formatMb(limit)}` : `${used}, no limit`;
}

export function formatUptime(seconds) {
  if (!seconds || seconds < 60) return `${Math.max(0, Math.round(seconds || 0))}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h`;
  return `${Math.floor(seconds / 86400)}d`;
}
